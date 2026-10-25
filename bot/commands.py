"""Bot commands in Telegram private messages: /status, /latest, /pending, /flavors, /lang, /help.

Incoming messages are fetched by long polling (getUpdates) in the pauses between
CurseForge polls, in the same thread, so nothing is shared concurrently with the poll loop.
The bot answers only in private chats with users from TELEGRAM_ADMIN_IDS, in the language
each of them chose with /lang, or else the language of their Telegram client.
"""
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape
from typing import TYPE_CHECKING

from bot.curseforge import CurseForgeError
from bot.flavors import CLASSIC, FOREVER, GROUPS, RETAIL
from bot.i18n import DEFAULT, LANGUAGE_NAMES, LANGUAGES, menu, pick, t
from bot.storage import Storage
from bot.telegram import TelegramError

if TYPE_CHECKING:  # bot.main imports this module itself
    from bot.main import Bot

log = logging.getLogger(__name__)

OFFSET_KEY = "tg_offset"  # next update_id: old commands are not repeated after a restart
LANG_KEY = "lang.{user_id}"  # reply language chosen with /lang
LANG_BUTTON = "lang:"  # callback data prefix of the language buttons
POLL_TIMEOUT = 30  # seconds to hold one getUpdates
ERROR_PAUSE = 10  # pause after a getUpdates error, to avoid spinning idly
LATEST_DEFAULT = 3
LATEST_MAX = 10
PENDING_LIMIT = 20
LATEST_PAUSE = 1  # seconds between addons in the /latest reply
_DAY = timedelta(days=1)

_GROUP_TITLES = {RETAIL: "Retail", CLASSIC: "Classic", FOREVER: "Forever"}
_KNOWN_STATUSES = {1, 2, 3, 4, 6, 10}


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
        """Command menu in the Telegram client, per language; commands work without it too."""
        for lang in LANGUAGES:
            try:
                self._telegram.set_my_commands(menu(lang), language_code=None if lang == DEFAULT else lang)
            except TelegramError as e:
                log.warning("could not register the %s command menu: %s", lang, e)

    def wait(self, seconds: float) -> None:
        """Wait seconds seconds, answering incoming commands. Plugged into Bot.run_forever."""
        deadline = self._monotonic() + seconds
        while (remaining := deadline - self._monotonic()) > 0:
            offset = self._storage.get_meta(OFFSET_KEY)
            try:
                updates = self._telegram.get_updates(
                    int(offset) if offset is not None else None, timeout=max(1, min(POLL_TIMEOUT, int(remaining)))
                )
            except TelegramError as e:
                log.warning("could not fetch messages: %s", e)
                self._sleep(min(remaining, ERROR_PAUSE))
                continue
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    # advance before handling: a command that crashes will not repeat forever
                    self._storage.set_meta(OFFSET_KEY, str(update_id + 1))
                try:
                    self.handle(update)
                except Exception:
                    log.exception("error while handling command from update %s", update_id)

    def handle(self, update: dict) -> None:
        if isinstance(update.get("callback_query"), dict):
            self._handle_button(update["callback_query"])
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        if chat.get("type") != "private" or not self._allowed(user):
            return

        chat_id = chat["id"]
        user_id = user["id"]
        lang = self._lang(user)
        text = (message.get("text") or "").strip()
        if not text.startswith("/"):
            self._reply(chat_id, self._help(lang, user_id))
            return
        command, _, arg = text.partition(" ")
        command = command[1:].split("@", 1)[0].lower()
        arg = arg.strip()

        handler = {
            "start": lambda: self._reply(chat_id, self._help(lang, user_id)),
            "help": lambda: self._reply(chat_id, self._help(lang, user_id)),
            "status": lambda: self._reply(chat_id, self._status(lang)),
            "pending": lambda: self._reply(chat_id, self._pending(lang)),
            "flavors": lambda: self._reply(chat_id, self._flavors(lang, arg)),
            "latest": lambda: self._latest(lang, chat_id, arg),
            "lang": lambda: self._lang_command(lang, chat_id, user_id, arg),
        }.get(command)
        if handler is None:
            self._reply(chat_id, t(lang, "unknown_command", command=escape(command)))
            return
        handler()

    def _handle_button(self, query: dict) -> None:
        user = query.get("from") or {}
        chat = (query.get("message") or {}).get("chat") or {}
        if chat.get("type") != "private" or not self._allowed(user):
            return
        self._answer(query.get("id"))
        data = query.get("data") or ""
        if data.startswith(LANG_BUTTON):
            self._set_lang(chat["id"], user["id"], data.removeprefix(LANG_BUTTON))

    # --- commands ---

    def _help(self, lang: str, user_id: int) -> str:
        lines = [t(lang, "help.title"), ""]
        lines += [f"/{command} — {escape(description)}" for command, description in menu(lang)]
        lines += ["", t(lang, "help.your_id", user_id=user_id)]
        return "\n".join(lines)

    def _status(self, lang: str) -> str:
        at = self._bot.last_cycle()
        if at is None:
            when = t(lang, "status.never")
        else:
            when = t(lang, "status.ago", at=f"{at:%d.%m %H:%M}", ago=_ago(lang, self._now() - at))
        cursor = self._bot.cursor()
        return "\n".join(
            [
                "<b>curse-bot</b>",
                t(lang, "status.last_poll", when=when),
                t(lang, "status.next_id", cursor="—" if cursor is None else cursor),
                t(lang, "status.pending", count=len(self._storage.pending())),
                t(lang, "status.sent", count=self._storage.sent_since(self._now() - _DAY)),
                t(lang, "versions", state=self._flavors_state(lang)),
            ]
        )

    def _pending(self, lang: str) -> str:
        try:
            items = self._bot.pending_mods()
        except CurseForgeError as e:
            return t(lang, "curseforge_error", error=escape(str(e)))
        if not items:
            return t(lang, "pending.empty")
        lines = [t(lang, "pending.title", count=len(items))]
        for mod_id, mod, first_seen in items[:PENDING_LIMIT]:
            waited = _ago(lang, self._now() - first_seen)
            if mod is None:
                lines.append(t(lang, "pending.missing", mod_id=mod_id, waited=waited))
                continue
            name = escape(mod.get("name") or f"id {mod_id}")
            url = (mod.get("links") or {}).get("websiteUrl")
            title = f'<a href="{escape(url)}">{name}</a>' if url else name
            lines.append(t(lang, "pending.item", title=title, status=_mod_status(lang, mod.get("status")), waited=waited))
        if len(items) > PENDING_LIMIT:
            lines.append(t(lang, "pending.more", count=len(items) - PENDING_LIMIT))
        return "\n".join(lines)

    def _latest(self, lang: str, chat_id: int, arg: str) -> None:
        try:
            count = int(arg) if arg else LATEST_DEFAULT
        except ValueError:
            count = 0
        if not 1 <= count <= LATEST_MAX:
            self._reply(chat_id, t(lang, "latest.bad_count", max=LATEST_MAX))
            return
        try:
            mods = self._bot.latest_approved(count)
        except CurseForgeError as e:
            self._reply(chat_id, t(lang, "curseforge_error", error=escape(str(e))))
            return
        if not mods:
            self._reply(chat_id, t(lang, "latest.none"))
            return
        for mod in mods:
            caption, images = self._bot.render(mod)
            try:
                self._telegram.send_addon(caption, images, chat_id=chat_id)
            except TelegramError as e:
                log.error("could not send %s in reply to /latest: %s", mod.get("id"), e)
                self._reply(
                    chat_id, t(lang, "latest.send_failed", name=escape(mod.get("name") or ""), error=escape(str(e)))
                )
                return
            self._sleep(LATEST_PAUSE)

    def _flavors(self, lang: str, arg: str) -> str:
        if not arg:
            return t(lang, "versions", state=self._flavors_state(lang)) + "\n" + t(lang, "flavors.usage")
        word = arg.lower()
        if word == "reset":
            self._bot.set_wanted(None)
        elif word == "all":
            self._bot.set_wanted(frozenset())
        else:
            wanted = frozenset(part for part in word.replace(",", " ").split() if part)
            unknown = wanted - GROUPS
            if unknown:
                return t(lang, "flavors.unknown", names=escape(", ".join(sorted(unknown))))
            self._bot.set_wanted(wanted)
        return t(lang, "versions", state=self._flavors_state(lang))

    def _lang_command(self, lang: str, chat_id: int, user_id: int, arg: str) -> None:
        if arg:
            self._set_lang(chat_id, user_id, arg.lower(), current=lang)
            return
        text = t(lang, "lang.current", name=LANGUAGE_NAMES[lang]) + "\n" + t(lang, "lang.choose")
        buttons = [(LANGUAGE_NAMES[code], f"{LANG_BUTTON}{code}") for code in LANGUAGES]
        self._reply(chat_id, text, buttons=buttons)

    # --- helpers ---

    def _set_lang(self, chat_id: int, user_id: int, code: str, current: str = DEFAULT) -> None:
        if code not in LANGUAGES:
            self._reply(chat_id, t(current, "lang.unknown", code=escape(code)))
            return
        self._storage.set_meta(LANG_KEY.format(user_id=user_id), code)
        self._reply(chat_id, t(code, "lang.current", name=LANGUAGE_NAMES[code]))

    def _lang(self, user: dict) -> str:
        """The language chosen with /lang, or else the one of the user's Telegram client."""
        chosen = self._storage.get_meta(LANG_KEY.format(user_id=user["id"]))
        return chosen if chosen in LANGUAGES else pick(user.get("language_code"))

    def _allowed(self, user: dict) -> bool:
        user_id = user.get("id")
        if user_id in self._admin_ids:
            return True
        if user_id not in self._strangers_logged:
            self._strangers_logged.add(user_id)
            log.info(
                "message from a user who is not allowed, id=%s (@%s); to allow them, add the id to TELEGRAM_ADMIN_IDS",
                user_id,
                user.get("username"),
            )
        return False

    def _flavors_state(self, lang: str) -> str:
        wanted = self._bot.wanted()
        groups = ", ".join(title for group, title in _GROUP_TITLES.items() if group in wanted) or t(lang, "flavors.all")
        source = t(lang, "flavors.overridden" if self._bot.wanted_overridden() else "flavors.from_settings")
        return f"{groups} ({source})"

    def _reply(self, chat_id: int, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
        try:
            if buttons:
                self._telegram.send_text(chat_id, text, buttons=buttons)
            else:
                self._telegram.send_text(chat_id, text)
        except TelegramError as e:
            log.error("could not reply in chat %s: %s", chat_id, e)

    def _answer(self, callback_query_id: str | None) -> None:
        if not callback_query_id:
            return
        try:
            self._telegram.answer_callback_query(callback_query_id)
        except TelegramError as e:
            log.warning("could not answer a button press: %s", e)


def _mod_status(lang: str, status) -> str:
    if status in _KNOWN_STATUSES:
        return t(lang, f"mod_status.{status}")
    return t(lang, "mod_status.other", status=status)


def _ago(lang: str, delta: timedelta) -> str:
    """Human-readable interval: "3 min", "5 h", "2 d" (or "3 мин", "5 ч", "2 дн")."""
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 60:
        return t(lang, "ago.min", n=minutes)
    if minutes < 48 * 60:
        return t(lang, "ago.h", n=minutes // 60)
    return t(lang, "ago.d", n=minutes // (24 * 60))
