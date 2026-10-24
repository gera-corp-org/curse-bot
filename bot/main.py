"""Цикл опроса CurseForge и отправки новых аддонов WoW в Telegram."""
import argparse
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from bot.config import ConfigError, load_config
from bot.curseforge import PAGE_SIZE, CurseForgeClient, CurseForgeError, parse_date
from bot.flavors import Flavor, build_flavor_map, format_flavors, mod_flavors, passes_filter
from bot.formatter import build_caption, pick_images
from bot.storage import Storage
from bot.telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)

SEND_PAUSE = 3  # секунд между сообщениями, чтобы не упереться в лимиты Telegram
NEW_MAX_AGE = timedelta(days=14)  # аддон, созданный раньше, — не новый, а обновление старого
MAX_PAGES = 4  # сколько страниц выдачи читать за один опрос
WATERMARK_KEY = "last_released"  # максимальный dateReleased, который бот уже видел


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
        mods = _with_ids(self._curseforge.latest_released())
        if self._storage.is_empty():
            self._storage.mark_seen(m["id"] for m in mods)
            log.info("baseline: %d addons", len(mods))
            self._advance_watermark(mods, None)
            return

        watermark = parse_date(self._storage.get_meta(WATERMARK_KEY))
        mods = self._fetch_more_pages(mods, watermark)
        unseen = set(self._storage.filter_unseen([m["id"] for m in mods]))
        for mod in reversed(mods):  # API отдаёт от новых к старым, а в канал — по порядку выхода
            if mod["id"] not in unseen:
                continue
            try:
                self._process(mod)
            except Exception:
                log.exception("ошибка при обработке аддона %s, повторю в следующем опросе", mod["id"])
        self._advance_watermark(mods, watermark)

    def _fetch_more_pages(self, mods: list[dict], watermark: datetime | None) -> list[dict]:
        """Дочитать страницы, пока на последней есть что-то новее watermark; без watermark — только первая."""
        page, pages, result = mods, 1, list(mods)
        while watermark is not None and len(page) == PAGE_SIZE:
            oldest = min((d for d in map(_released, page) if d), default=None)
            if oldest is None or oldest <= watermark:
                break
            if pages >= MAX_PAGES:
                log.warning("прочитано %d страниц, но граница не достигнута: часть аддонов могла быть пропущена", pages)
                break
            page = _with_ids(self._curseforge.latest_released(pages * PAGE_SIZE))
            pages += 1
            result += page
        return _dedupe(result)

    def _process(self, mod: dict) -> None:
        created = parse_date(mod.get("dateCreated"))
        if created is not None and created < self._now() - NEW_MAX_AGE:
            log.info("пропуск %s «%s»: это обновление старого аддона (создан %s)", mod["id"], mod.get("name"), created.date())
            self._storage.mark_seen([mod["id"]])
            return
        flavors = mod_flavors(mod, self._flavor_map)
        if not passes_filter(flavors, self._wanted):
            log.info("пропуск %s «%s»: версии [%s] не в FLAVORS", mod["id"], mod.get("name"), format_flavors(flavors))
            self._storage.mark_seen([mod["id"]])
            return
        if self._send(mod, flavors):
            self._storage.mark_seen([mod["id"]])

    def _advance_watermark(self, mods: list[dict], stored: datetime | None) -> None:
        newest = max((d for d in map(_released, mods) if d), default=None)
        if newest is not None and (stored is None or newest > stored):
            self._storage.set_meta(WATERMARK_KEY, newest.isoformat())

    def send_latest(self, count: int) -> None:
        """Разово отправить count последних аддонов — без фильтра и без пометки в базе."""
        for mod in reversed(self._curseforge.latest_released()[:count]):
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


def _released(mod: dict) -> datetime | None:
    return parse_date(mod.get("dateReleased"))


def _with_ids(mods: list[dict]) -> list[dict]:
    return [m for m in mods if isinstance(m, dict) and "id" in m]


def _dedupe(mods: list[dict]) -> list[dict]:
    seen: set = set()
    result = []
    for m in mods:
        if m["id"] not in seen:
            seen.add(m["id"])
            result.append(m)
    return result


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
