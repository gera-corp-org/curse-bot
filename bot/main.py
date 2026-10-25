"""Loop that polls CurseForge and sends new WoW addons to Telegram."""
import argparse
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bot.commands import Commands
from bot.config import ConfigError, load_config
from bot.curseforge import BATCH_SIZE, WOW_GAME_ID, CurseForgeClient, CurseForgeError
from bot.flavors import Flavor, build_flavor_map, format_flavors, mod_flavors, passes_filter
from bot.formatter import build_caption, pick_images
from bot.storage import Storage
from bot.telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)

SEND_PAUSE = 3  # seconds between messages, to stay within Telegram limits
MAX_BATCHES_PER_CYCLE = 20  # how many BATCH_SIZE-id windows to read per poll
PENDING_MAX_AGE = timedelta(days=14)  # how long to wait for approval/files before dropping an addon
CURSOR_KEY = "next_id"  # first id the bot has not scanned yet
LAST_CYCLE_KEY = "last_cycle"  # when the last poll finished without errors (for /status)
FLAVORS_KEY = "flavors"  # version filter set by /flavors; overrides FLAVORS from settings
ALL_FLAVORS = "*"  # FLAVORS_KEY value meaning "no filter"
STATUS_APPROVED = 4
STATUS_GONE = frozenset({5, 9})  # Rejected, Deleted


class Bot:
    def __init__(
        self,
        curseforge,
        telegram,
        storage: Storage,
        flavor_map: dict[int, Flavor],
        wanted: frozenset[str],
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        heartbeat: Path | None = None,
    ):
        self._curseforge = curseforge
        self._telegram = telegram
        self._storage = storage
        self._flavor_map = flavor_map
        self._default_wanted = wanted
        self._sleep = sleep
        self._now = now
        self._heartbeat = heartbeat

    def run_forever(self, interval: int, wait: Callable[[float], None] | None = None) -> None:
        """Poll every interval seconds; between polls call wait (plain sleep by default)."""
        wait = wait or self._sleep
        self._beat()
        while True:
            try:
                self.run_once()
            except CurseForgeError as e:
                log.error("%s", e)
            except Exception:
                log.exception("unexpected error in the poll loop")
            self._beat()
            wait(interval)

    def _beat(self) -> None:
        """Mark the loop as alive: the liveness probe checks the file's modification time."""
        if self._heartbeat is None:
            return
        try:
            self._heartbeat.touch()
        except OSError as e:
            log.warning("could not update heartbeat %s: %s", self._heartbeat, e)

    def run_once(self) -> None:
        cursor = self._storage.get_meta(CURSOR_KEY)
        if cursor is None:
            next_id = self._curseforge.find_max_id() + 1
            self._storage.set_meta(CURSOR_KEY, str(next_id))
            log.info("baseline: next id %d", next_id)
        else:
            self._scan_forward(int(cursor))
            self._process_pending()
        self._storage.set_meta(LAST_CYCLE_KEY, self._now().isoformat())

    def cursor(self) -> int | None:
        """First id the bot has not scanned yet; None before baseline."""
        value = self._storage.get_meta(CURSOR_KEY)
        return None if value is None else int(value)

    def last_cycle(self) -> datetime | None:
        """When the last poll finished without errors."""
        value = self._storage.get_meta(LAST_CYCLE_KEY)
        return None if value is None else datetime.fromisoformat(value)

    def wanted(self) -> frozenset[str]:
        """Effective version filter: set by /flavors or from settings."""
        override = self._storage.get_meta(FLAVORS_KEY)
        if override is None:
            return self._default_wanted
        return frozenset() if override == ALL_FLAVORS else frozenset(override.split(","))

    def wanted_overridden(self) -> bool:
        return self._storage.get_meta(FLAVORS_KEY) is not None

    def set_wanted(self, wanted: frozenset[str] | None) -> None:
        """Set the filter (empty - no filter); None - revert to the value from settings."""
        if wanted is None:
            self._storage.delete_meta(FLAVORS_KEY)
        else:
            self._storage.set_meta(FLAVORS_KEY, ",".join(sorted(wanted)) or ALL_FLAVORS)

    def _scan_forward(self, next_id: int) -> None:
        """Scan new ids in windows; WoW addons go to the waiting queue."""
        for _ in range(MAX_BATCHES_PER_CYCLE):
            window_end = next_id + BATCH_SIZE
            mods = _valid(self._curseforge.get_mods(list(range(next_id, window_end))))
            if not mods:
                return
            wow_ids = [m["id"] for m in mods if m.get("gameId") == WOW_GAME_ID]
            if wow_ids:
                self._storage.add_pending(wow_ids, self._now())
                log.info("new WoW addons found: %d", len(wow_ids))
            top = max(m["id"] for m in mods)
            next_id = top + 1
            self._storage.set_meta(CURSOR_KEY, str(next_id))
            if top < window_end - BATCH_SIZE // 10:  # window not filled to the end - nothing further yet
                return
        log.warning("read %d id windows in one poll, the rest will be handled in the next poll", MAX_BATCHES_PER_CYCLE)

    def _process_pending(self) -> None:
        pending = self._storage.pending()
        if not pending:
            return
        wanted = self.wanted()
        for mod_id, mod, first_seen in self.pending_mods():
            try:
                self._process(mod_id, mod, first_seen, wanted)
            except Exception:
                log.exception("error while processing addon %s, will retry in the next poll", mod_id)

    def pending_mods(self) -> list[tuple[int, dict | None, datetime]]:
        """Waiting queue in ascending id order: (id, fresh data from the API or None when first seen)."""
        pending = self._storage.pending()
        if not pending:
            return []
        ids = sorted(pending)
        by_id = {m["id"]: m for m in _valid(self._curseforge.get_mods(ids))}
        return [(mod_id, by_id.get(mod_id), pending[mod_id]) for mod_id in ids]

    def _process(self, mod_id: int, mod: dict | None, first_seen: datetime, wanted: frozenset[str]) -> None:
        expired = self._now() - first_seen > PENDING_MAX_AGE
        if mod is None:
            if expired:
                log.info("skipping %s: the API has not returned it for over %s", mod_id, PENDING_MAX_AGE)
                self._storage.remove_pending([mod_id])
            return
        if mod.get("status") in STATUS_GONE:
            log.info("skipping %s '%s': rejected or deleted (status %s)", mod_id, mod.get("name"), mod.get("status"))
            self._storage.remove_pending([mod_id])
            return
        if not _approved(mod):
            if expired:
                log.info("skipping %s '%s': not approved within %s", mod_id, mod.get("name"), PENDING_MAX_AGE)
                self._storage.remove_pending([mod_id])
            return
        flavors = mod_flavors(mod, self._flavor_map)
        if wanted and not flavors:
            if expired:
                log.info("skipping %s '%s': no files ever appeared", mod_id, mod.get("name"))
                self._storage.remove_pending([mod_id])
            return  # files not uploaded yet - wait
        if not passes_filter(flavors, wanted):
            log.info("skipping %s '%s': versions [%s] not in FLAVORS", mod_id, mod.get("name"), format_flavors(flavors))
            self._storage.remove_pending([mod_id])
            return
        if self._send(mod, flavors):
            self._storage.remove_pending([mod_id])
            self._storage.record_sent(mod_id, self._now())

    def send_latest(self, count: int) -> None:
        """Send the count latest approved WoW addons once - without the filter and without changes to the database."""
        for mod in self.latest_approved(count):
            self._send(mod, mod_flavors(mod, self._flavor_map))

    def latest_approved(self, count: int) -> list[dict]:
        """The count latest approved WoW addons (oldest to newest), found by scanning ids backwards from the cursor."""
        cursor = self._storage.get_meta(CURSOR_KEY)
        end = int(cursor) if cursor is not None else self._curseforge.find_max_id() + 1
        found: list[dict] = []
        for _ in range(MAX_BATCHES_PER_CYCLE):
            start = max(end - BATCH_SIZE, 1)
            mods = _valid(self._curseforge.get_mods(list(range(start, end))))
            found += [m for m in mods if m.get("gameId") == WOW_GAME_ID and _approved(m)]
            end = start
            if len(found) >= count or end <= 1:
                break
        return sorted(found, key=lambda m: m["id"])[-count:]

    def render(self, mod: dict) -> tuple[str, list[str]]:
        """Caption and images for an addon message."""
        return build_caption(mod, mod_flavors(mod, self._flavor_map)), pick_images(mod)

    def _send(self, mod: dict, flavors: list[Flavor]) -> bool:
        try:
            self._telegram.send_addon(build_caption(mod, flavors), pick_images(mod))
        except TelegramError as e:
            log.error("could not send %s '%s': %s", mod["id"], mod.get("name"), e)
            return False
        log.info("sent %s '%s'", mod["id"], mod.get("name"))
        self._sleep(SEND_PAUSE)
        return True


def _approved(mod: dict) -> bool:
    return mod.get("status") == STATUS_APPROVED and bool(mod.get("isAvailable"))


def _valid(mods: list[dict]) -> list[dict]:
    """Only entries with an integer id: one malformed entry must not break the loop."""
    return [m for m in mods if isinstance(m, dict) and isinstance(m.get("id"), int)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bot", description="Telegram notifications about new WoW addons from CurseForge"
    )
    parser.add_argument(
        "--send-latest", type=int, metavar="N", help="send the N latest addons once (a check) and exit"
    )
    args = parser.parse_args(argv)
    if args.send_latest is not None and args.send_latest < 1:
        parser.error("--send-latest: N must be at least 1")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx at INFO level logs request URLs, and the Telegram URL contains the bot token
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        config = load_config()
    except ConfigError as e:
        log.error("%s", e)
        return 2

    curseforge = CurseForgeClient(config.curseforge_api_key)
    try:
        version_types = curseforge.version_types()
    except CurseForgeError as e:
        log.warning("version types not loaded (%s), using the built-in list", e)
        version_types = []

    telegram = TelegramClient(config.telegram_bot_token, config.telegram_chat_id)
    storage = Storage(config.db_path)
    bot = Bot(
        curseforge,
        telegram,
        storage,
        build_flavor_map(version_types),
        config.flavors,
        heartbeat=config.heartbeat_file,
    )

    if args.send_latest is not None:
        try:
            bot.send_latest(args.send_latest)
        except CurseForgeError as e:
            log.error("%s", e)
            return 1
        return 0

    log.info(
        "start: polling every %d s, FLAVORS=%s", config.poll_interval, ",".join(sorted(config.flavors)) or "all"
    )
    if config.admin_ids:
        commands = Commands(bot, telegram, storage, config.admin_ids)
        commands.register_menu()
        log.info("Telegram commands enabled for %d users", len(config.admin_ids))
        bot.run_forever(config.poll_interval, wait=commands.wait)
    else:
        log.info("Telegram commands disabled: TELEGRAM_ADMIN_IDS is empty")
        bot.run_forever(config.poll_interval)
    return 0
