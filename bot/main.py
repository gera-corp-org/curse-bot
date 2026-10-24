"""Цикл опроса CurseForge и отправки новых аддонов WoW в Telegram."""
import argparse
import logging
import time
from collections.abc import Callable

from bot.config import ConfigError, load_config
from bot.curseforge import CurseForgeClient, CurseForgeError
from bot.flavors import Flavor, build_flavor_map, format_flavors, mod_flavors, passes_filter
from bot.formatter import build_caption, pick_images
from bot.storage import Storage
from bot.telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)

SEND_PAUSE = 3  # секунд между сообщениями, чтобы не упереться в лимиты Telegram


class Bot:
    def __init__(
        self,
        curseforge,
        telegram,
        storage: Storage,
        flavor_map: dict[int, Flavor],
        wanted: frozenset[str],
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._curseforge = curseforge
        self._telegram = telegram
        self._storage = storage
        self._flavor_map = flavor_map
        self._wanted = wanted
        self._sleep = sleep

    def run_forever(self, interval: int) -> None:
        while True:
            try:
                self.run_once()
            except CurseForgeError as e:
                log.error("%s", e)
            self._sleep(interval)

    def run_once(self) -> None:
        mods = self._curseforge.latest_released()
        if self._storage.is_empty():
            self._storage.mark_seen(m["id"] for m in mods)
            log.info("baseline: %d addons", len(mods))
            return

        unseen = set(self._storage.filter_unseen([m["id"] for m in mods]))
        for mod in reversed(mods):  # API отдаёт от новых к старым, а в канал — по порядку выхода
            if mod["id"] not in unseen:
                continue
            flavors = mod_flavors(mod, self._flavor_map)
            if not passes_filter(flavors, self._wanted):
                log.info("пропуск %s «%s»: версии [%s] не в FLAVORS", mod["id"], mod["name"], format_flavors(flavors))
                self._storage.mark_seen([mod["id"]])
                continue
            if self._send(mod, flavors):
                self._storage.mark_seen([mod["id"]])

    def send_latest(self, count: int) -> None:
        """Разово отправить count последних аддонов — без фильтра и без пометки в базе."""
        for mod in reversed(self._curseforge.latest_released()[:count]):
            self._send(mod, mod_flavors(mod, self._flavor_map))

    def _send(self, mod: dict, flavors: list[Flavor]) -> bool:
        try:
            self._telegram.send_addon(build_caption(mod, flavors), pick_images(mod))
        except TelegramError as e:
            log.error("не удалось отправить %s «%s»: %s", mod["id"], mod["name"], e)
            return False
        log.info("отправлен %s «%s»", mod["id"], mod["name"])
        self._sleep(SEND_PAUSE)
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bot", description="Уведомления о новых аддонах WoW с CurseForge в Telegram"
    )
    parser.add_argument(
        "--send-latest", type=int, metavar="N", help="разово отправить N последних аддонов (проверка) и выйти"
    )
    args = parser.parse_args(argv)

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

    if args.send_latest:
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
