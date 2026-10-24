"""Цикл опроса CurseForge и отправки новых аддонов WoW в Telegram."""
import argparse
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from bot.config import ConfigError, load_config
from bot.curseforge import BATCH_SIZE, WOW_GAME_ID, CurseForgeClient, CurseForgeError
from bot.flavors import Flavor, build_flavor_map, format_flavors, mod_flavors, passes_filter
from bot.formatter import build_caption, pick_images
from bot.storage import Storage
from bot.telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)

SEND_PAUSE = 3  # секунд между сообщениями, чтобы не упереться в лимиты Telegram
MAX_BATCHES_PER_CYCLE = 20  # сколько окон по BATCH_SIZE id читать за один опрос
PENDING_MAX_AGE = timedelta(days=14)  # сколько ждать одобрения/файлов, прежде чем бросить аддон
CURSOR_KEY = "next_id"  # первый id, который бот ещё не просматривал
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
    ):
        self._curseforge = curseforge
        self._telegram = telegram
        self._storage = storage
        self._flavor_map = flavor_map
        self._wanted = wanted
        self._sleep = sleep
        self._now = now

    def run_forever(self, interval: int) -> None:
        while True:
            try:
                self.run_once()
            except CurseForgeError as e:
                log.error("%s", e)
            except Exception:
                log.exception("непредвиденная ошибка в цикле опроса")
            self._sleep(interval)

    def run_once(self) -> None:
        cursor = self._storage.get_meta(CURSOR_KEY)
        if cursor is None:
            next_id = self._curseforge.find_max_id() + 1
            self._storage.set_meta(CURSOR_KEY, str(next_id))
            log.info("baseline: следующий id %d", next_id)
            return
        self._scan_forward(int(cursor))
        self._process_pending()

    def _scan_forward(self, next_id: int) -> None:
        """Просмотреть новые id окнами; WoW-аддоны попадают в очередь ожидания."""
        for _ in range(MAX_BATCHES_PER_CYCLE):
            window_end = next_id + BATCH_SIZE
            mods = _valid(self._curseforge.get_mods(list(range(next_id, window_end))))
            if not mods:
                return
            wow_ids = [m["id"] for m in mods if m.get("gameId") == WOW_GAME_ID]
            if wow_ids:
                self._storage.add_pending(wow_ids, self._now())
                log.info("найдено новых аддонов WoW: %d", len(wow_ids))
            top = max(m["id"] for m in mods)
            next_id = top + 1
            self._storage.set_meta(CURSOR_KEY, str(next_id))
            if top < window_end - BATCH_SIZE // 10:  # окно не добито до конца — дальше пока пусто
                return
        log.warning("за один опрос прочитано %d окон id, остальное будет в следующем опросе", MAX_BATCHES_PER_CYCLE)

    def _process_pending(self) -> None:
        pending = self._storage.pending()
        if not pending:
            return
        ids = sorted(pending)
        by_id = {m["id"]: m for m in _valid(self._curseforge.get_mods(ids))}
        for mod_id in ids:
            try:
                self._process(mod_id, by_id.get(mod_id), pending[mod_id])
            except Exception:
                log.exception("ошибка при обработке аддона %s, повторю в следующем опросе", mod_id)

    def _process(self, mod_id: int, mod: dict | None, first_seen: datetime) -> None:
        expired = self._now() - first_seen > PENDING_MAX_AGE
        if mod is None:
            if expired:
                log.info("пропуск %s: API его не отдаёт дольше %s", mod_id, PENDING_MAX_AGE)
                self._storage.remove_pending([mod_id])
            return
        if mod.get("status") in STATUS_GONE:
            log.info("пропуск %s «%s»: отклонён или удалён (status %s)", mod_id, mod.get("name"), mod.get("status"))
            self._storage.remove_pending([mod_id])
            return
        if not _approved(mod):
            if expired:
                log.info("пропуск %s «%s»: не одобрен за %s", mod_id, mod.get("name"), PENDING_MAX_AGE)
                self._storage.remove_pending([mod_id])
            return
        flavors = mod_flavors(mod, self._flavor_map)
        if self._wanted and not flavors:
            if expired:
                log.info("пропуск %s «%s»: так и не появилось файлов", mod_id, mod.get("name"))
                self._storage.remove_pending([mod_id])
            return  # файлы ещё не загружены — ждём
        if not passes_filter(flavors, self._wanted):
            log.info("пропуск %s «%s»: версии [%s] не в FLAVORS", mod_id, mod.get("name"), format_flavors(flavors))
            self._storage.remove_pending([mod_id])
            return
        if self._send(mod, flavors):
            self._storage.remove_pending([mod_id])

    def send_latest(self, count: int) -> None:
        """Разово отправить count последних одобренных аддонов WoW — без фильтра и без изменений в базе."""
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
        for mod in sorted(found, key=lambda m: m["id"])[-count:]:
            self._send(mod, mod_flavors(mod, self._flavor_map))

    def _send(self, mod: dict, flavors: list[Flavor]) -> bool:
        try:
            self._telegram.send_addon(build_caption(mod, flavors), pick_images(mod))
        except TelegramError as e:
            log.error("не удалось отправить %s «%s»: %s", mod["id"], mod.get("name"), e)
            return False
        log.info("отправлен %s «%s»", mod["id"], mod.get("name"))
        self._sleep(SEND_PAUSE)
        return True


def _approved(mod: dict) -> bool:
    return mod.get("status") == STATUS_APPROVED and bool(mod.get("isAvailable"))


def _valid(mods: list[dict]) -> list[dict]:
    """Только записи, у которых есть целочисленный id: одна кривая запись не должна ломать цикл."""
    return [m for m in mods if isinstance(m, dict) and isinstance(m.get("id"), int)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bot", description="Уведомления о новых аддонах WoW с CurseForge в Telegram"
    )
    parser.add_argument(
        "--send-latest", type=int, metavar="N", help="разово отправить N последних аддонов (проверка) и выйти"
    )
    args = parser.parse_args(argv)
    if args.send_latest is not None and args.send_latest < 1:
        parser.error("--send-latest: N должно быть не меньше 1")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx на уровне INFO пишет URL запросов, а в URL Telegram — токен бота
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
        log.warning("типы версий не загружены (%s), использую встроенный список", e)
        version_types = []

    bot = Bot(
        curseforge,
        TelegramClient(config.telegram_bot_token, config.telegram_chat_id),
        Storage(config.db_path),
        build_flavor_map(version_types),
        config.flavors,
    )

    if args.send_latest is not None:
        try:
            bot.send_latest(args.send_latest)
        except CurseForgeError as e:
            log.error("%s", e)
            return 1
        return 0

    log.info(
        "старт: опрос каждые %d с, FLAVORS=%s", config.poll_interval, ",".join(sorted(config.flavors)) or "все"
    )
    bot.run_forever(config.poll_interval)
    return 0
