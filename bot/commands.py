"""Команды бота в личных сообщениях Telegram: /status, /latest, /pending, /flavors, /help.

Входящие сообщения забираются long polling'ом (getUpdates) в паузах между опросами
CurseForge — в том же потоке, поэтому с циклом опроса ничего не делится конкурентно.
Отвечает бот только в личных чатах с пользователями из TELEGRAM_ADMIN_IDS.
"""
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape
from typing import TYPE_CHECKING

from bot.curseforge import CurseForgeError
from bot.flavors import CLASSIC, FOREVER, GROUPS, RETAIL
from bot.storage import Storage
from bot.telegram import TelegramError

if TYPE_CHECKING:  # bot.main сам импортирует этот модуль
    from bot.main import Bot

log = logging.getLogger(__name__)

OFFSET_KEY = "tg_offset"  # следующий update_id: после рестарта старые команды не повторяются
POLL_TIMEOUT = 30  # секунд держать один getUpdates
ERROR_PAUSE = 10  # пауза после ошибки getUpdates, чтобы не крутиться вхолостую
LATEST_DEFAULT = 3
LATEST_MAX = 10
PENDING_LIMIT = 20
LATEST_PAUSE = 1  # секунд между аддонами в ответе на /latest
_DAY = timedelta(days=1)

MENU = [
    ("status", "Состояние: последний опрос, очередь, отправлено за сутки"),
    ("latest", "Последние одобренные аддоны (/latest 5)"),
    ("pending", "Аддоны, ждущие модерации"),
    ("flavors", "Фильтр версий: /flavors forever,retail | all | reset"),
    ("help", "Список команд"),
]

_GROUP_TITLES = {RETAIL: "Retail", CLASSIC: "Classic", FOREVER: "Forever"}
_STATUS_TEXT = {
    1: "на модерации",
    2: "нужны правки",
    3: "на проверке",
    4: "одобрен, ждёт файлов",
    6: "правки внесены",
    10: "на проверке",
}


class Commands:
    def __init__(
        self,
        bot: "Bot",
        telegram,
        storage: Storage,
        admin_ids: frozenset[int],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._bot = bot
        self._telegram = telegram
        self._storage = storage
        self._admin_ids = admin_ids
        self._now = now
        self._monotonic = monotonic
        self._sleep = sleep
        self._strangers_logged: set[int] = set()

    def register_menu(self) -> None:
        """Меню команд в клиенте Telegram; без него команды тоже работают."""
        try:
            self._telegram.set_my_commands(MENU)
        except TelegramError as e:
            log.warning("не удалось зарегистрировать меню команд: %s", e)

    def wait(self, seconds: float) -> None:
        """Ждать seconds секунд, отвечая на входящие команды. Подставляется в Bot.run_forever."""
        deadline = self._monotonic() + seconds
        while (remaining := deadline - self._monotonic()) > 0:
            offset = self._storage.get_meta(OFFSET_KEY)
            try:
                updates = self._telegram.get_updates(
                    int(offset) if offset is not None else None, timeout=max(1, min(POLL_TIMEOUT, int(remaining)))
                )
            except TelegramError as e:
                log.warning("не удалось получить сообщения: %s", e)
                self._sleep(min(remaining, ERROR_PAUSE))
                continue
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    # сдвигаем до обработки: команда, которая падает, не будет повторяться вечно
                    self._storage.set_meta(OFFSET_KEY, str(update_id + 1))
                try:
                    self.handle(update)
                except Exception:
                    log.exception("ошибка при выполнении команды из update %s", update_id)

    def handle(self, update: dict) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        if chat.get("type") != "private":
            return
        user_id = user.get("id")
        if user_id not in self._admin_ids:
            if user_id not in self._strangers_logged:
                self._strangers_logged.add(user_id)
                log.info(
                    "сообщение от неразрешённого пользователя id=%s (@%s); чтобы разрешить — добавьте id в TELEGRAM_ADMIN_IDS",
                    user_id,
                    user.get("username"),
                )
            return

        chat_id = chat["id"]
        text = (message.get("text") or "").strip()
        if not text.startswith("/"):
            self._reply(chat_id, self._help(user_id))
            return
        command, _, arg = text.partition(" ")
        command = command[1:].split("@", 1)[0].lower()
        arg = arg.strip()

        handler = {
            "start": lambda: self._reply(chat_id, self._help(user_id)),
            "help": lambda: self._reply(chat_id, self._help(user_id)),
            "status": lambda: self._reply(chat_id, self._status()),
            "pending": lambda: self._reply(chat_id, self._pending()),
            "flavors": lambda: self._reply(chat_id, self._flavors(arg)),
            "latest": lambda: self._latest(chat_id, arg),
        }.get(command)
        if handler is None:
            self._reply(chat_id, f"Не знаю команду /{escape(command)}. Список команд — /help")
            return
        handler()

    # --- команды ---

    def _help(self, user_id: int) -> str:
        lines = ["<b>curse-bot</b> — новые аддоны WoW с CurseForge", ""]
        lines += [f"/{command} — {escape(description)}" for command, description in MENU]
        lines += ["", f"Ваш id: <code>{user_id}</code>"]
        return "\n".join(lines)

    def _status(self) -> str:
        at = self._bot.last_cycle()
        last_text = "ещё не было" if at is None else f"{at:%d.%m %H:%M} UTC, {_ago(self._now() - at)} назад"
        cursor = self._bot.cursor()
        cursor = "—" if cursor is None else cursor
        sent = self._storage.sent_since(self._now() - _DAY)
        return "\n".join(
            [
                "<b>curse-bot</b>",
                f"Последний опрос: {last_text}",
                f"Следующий id: {cursor}",
                f"Ждут модерации: {len(self._storage.pending())}",
                f"В канал за 24 ч: {sent}",
                f"Версии: {self._flavors_state()}",
            ]
        )

    def _pending(self) -> str:
        try:
            items = self._bot.pending_mods()
        except CurseForgeError as e:
            return f"Не удалось спросить CurseForge: {escape(str(e))}"
        if not items:
            return "Очередь ожидания пуста."
        lines = [f"<b>Ждут модерации: {len(items)}</b>"]
        for mod_id, mod, first_seen in items[:PENDING_LIMIT]:
            waited = _ago(self._now() - first_seen)
            if mod is None:
                lines.append(f"• id {mod_id} — нет в API, ждёт {waited}")
                continue
            name = escape(mod.get("name") or f"id {mod_id}")
            url = (mod.get("links") or {}).get("websiteUrl")
            title = f'<a href="{escape(url)}">{name}</a>' if url else name
            status = _STATUS_TEXT.get(mod.get("status"), f"статус {mod.get('status')}")
            lines.append(f"• {title} — {status}, ждёт {waited}")
        if len(items) > PENDING_LIMIT:
            lines.append(f"…и ещё {len(items) - PENDING_LIMIT}")
        return "\n".join(lines)

    def _latest(self, chat_id: int, arg: str) -> None:
        try:
            count = int(arg) if arg else LATEST_DEFAULT
        except ValueError:
            count = 0
        if not 1 <= count <= LATEST_MAX:
            self._reply(chat_id, f"Укажите число от 1 до {LATEST_MAX}: /latest 5")
            return
        try:
            mods = self._bot.latest_approved(count)
        except CurseForgeError as e:
            self._reply(chat_id, f"Не удалось спросить CurseForge: {escape(str(e))}")
            return
        if not mods:
            self._reply(chat_id, "Не нашёл одобренных аддонов WoW среди последних id.")
            return
        for mod in mods:
            caption, images = self._bot.render(mod)
            try:
                self._telegram.send_addon(caption, images, chat_id=chat_id)
            except TelegramError as e:
                log.error("не удалось отправить %s в ответ на /latest: %s", mod.get("id"), e)
                self._reply(chat_id, f"Не удалось отправить «{escape(mod.get('name') or '')}»: {escape(str(e))}")
                return
            self._sleep(LATEST_PAUSE)

    def _flavors(self, arg: str) -> str:
        usage = "Задать: /flavors forever,retail · без фильтра: /flavors all · как в настройках: /flavors reset"
        if not arg:
            return f"Версии: {self._flavors_state()}\n{usage}"
        word = arg.lower()
        if word == "reset":
            self._bot.set_wanted(None)
        elif word == "all":
            self._bot.set_wanted(frozenset())
        else:
            wanted = frozenset(part for part in word.replace(",", " ").split() if part)
            unknown = wanted - GROUPS
            if unknown:
                return f"Неизвестные версии: {escape(', '.join(sorted(unknown)))}. Можно: retail, classic, forever."
            self._bot.set_wanted(wanted)
        return f"Версии: {self._flavors_state()}"

    # --- вспомогательное ---

    def _flavors_state(self) -> str:
        wanted = self._bot.wanted()
        groups = ", ".join(title for group, title in _GROUP_TITLES.items() if group in wanted) or "все"
        source = "задан командой /flavors" if self._bot.wanted_overridden() else "из настроек"
        return f"{groups} ({source})"

    def _reply(self, chat_id: int, text: str) -> None:
        try:
            self._telegram.send_text(chat_id, text)
        except TelegramError as e:
            log.error("не удалось ответить в чат %s: %s", chat_id, e)


def _ago(delta: timedelta) -> str:
    """Человекочитаемый интервал: «3 мин», «5 ч», «2 дн»."""
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 60:
        return f"{minutes} мин"
    if minutes < 48 * 60:
        return f"{minutes // 60} ч"
    return f"{minutes // (24 * 60)} дн"
