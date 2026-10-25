"""Bot commands in Telegram private messages: /status, /latest, /pending, /flavors, /help.

Incoming messages are fetched by long polling (getUpdates) in the pauses between
CurseForge polls, in the same thread, so nothing is shared concurrently with the poll loop.
The bot answers only in private chats with users from TELEGRAM_ADMIN_IDS.
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

if TYPE_CHECKING:  # bot.main imports this module itself
    from bot.main import Bot

log = logging.getLogger(__name__)

OFFSET_KEY = "tg_offset"  # next update_id: old commands are not repeated after a restart
POLL_TIMEOUT = 30  # seconds to hold one getUpdates
ERROR_PAUSE = 10  # pause after a getUpdates error, to avoid spinning idly
LATEST_DEFAULT = 3
LATEST_MAX = 10
PENDING_LIMIT = 20
LATEST_PAUSE = 1  # seconds between addons in the /latest reply
_DAY = timedelta(days=1)

MENU = [
    ("status", "Status: last poll, queue, sent in the last 24 h"),
    ("latest", "Latest approved addons (/latest 5)"),
    ("pending", "Addons awaiting moderation"),
    ("flavors", "Version filter: /flavors forever,retail | all | reset"),
    ("help", "List of commands"),
]

_GROUP_TITLES = {RETAIL: "Retail", CLASSIC: "Classic", FOREVER: "Forever"}
_STATUS_TEXT = {
    1: "in moderation",
    2: "needs changes",
    3: "under review",
    4: "approved, waiting for files",
    6: "changes made",
    10: "under review",
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
        """Command menu in the Telegram client; commands work without it too."""
        try:
            self._telegram.set_my_commands(MENU)
        except TelegramError as e:
            log.warning("could not register the command menu: %s", e)

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
                    "message from a user who is not allowed, id=%s (@%s); to allow them, add the id to TELEGRAM_ADMIN_IDS",
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
            self._reply(chat_id, f"Unknown command /{escape(command)}. See /help for the list of commands")
            return
        handler()

    # --- commands ---

    def _help(self, user_id: int) -> str:
        lines = ["<b>curse-bot</b> — new WoW addons from CurseForge", ""]
        lines += [f"/{command} — {escape(description)}" for command, description in MENU]
        lines += ["", f"Your id: <code>{user_id}</code>"]
        return "\n".join(lines)

    def _status(self) -> str:
        at = self._bot.last_cycle()
        last_text = "never" if at is None else f"{at:%d.%m %H:%M} UTC, {_ago(self._now() - at)} ago"
        cursor = self._bot.cursor()
        cursor = "—" if cursor is None else cursor
        sent = self._storage.sent_since(self._now() - _DAY)
        return "\n".join(
            [
                "<b>curse-bot</b>",
                f"Last poll: {last_text}",
                f"Next id: {cursor}",
                f"Awaiting moderation: {len(self._storage.pending())}",
                f"Sent to channel in 24 h: {sent}",
                f"Versions: {self._flavors_state()}",
            ]
        )

    def _pending(self) -> str:
        try:
            items = self._bot.pending_mods()
        except CurseForgeError as e:
            return f"Could not query CurseForge: {escape(str(e))}"
        if not items:
            return "The waiting queue is empty."
        lines = [f"<b>Awaiting moderation: {len(items)}</b>"]
        for mod_id, mod, first_seen in items[:PENDING_LIMIT]:
            waited = _ago(self._now() - first_seen)
            if mod is None:
                lines.append(f"• id {mod_id} — not in API, waiting {waited}")
                continue
            name = escape(mod.get("name") or f"id {mod_id}")
            url = (mod.get("links") or {}).get("websiteUrl")
            title = f'<a href="{escape(url)}">{name}</a>' if url else name
            status = _STATUS_TEXT.get(mod.get("status"), f"status {mod.get('status')}")
            lines.append(f"• {title} — {status}, waiting {waited}")
        if len(items) > PENDING_LIMIT:
            lines.append(f"…and {len(items) - PENDING_LIMIT} more")
        return "\n".join(lines)

    def _latest(self, chat_id: int, arg: str) -> None:
        try:
            count = int(arg) if arg else LATEST_DEFAULT
        except ValueError:
            count = 0
        if not 1 <= count <= LATEST_MAX:
            self._reply(chat_id, f"Give a number from 1 to {LATEST_MAX}: /latest 5")
            return
        try:
            mods = self._bot.latest_approved(count)
        except CurseForgeError as e:
            self._reply(chat_id, f"Could not query CurseForge: {escape(str(e))}")
            return
        if not mods:
            self._reply(chat_id, "Found no approved WoW addons among the latest ids.")
            return
        for mod in mods:
            caption, images = self._bot.render(mod)
            try:
                self._telegram.send_addon(caption, images, chat_id=chat_id)
            except TelegramError as e:
                log.error("could not send %s in reply to /latest: %s", mod.get("id"), e)
                self._reply(chat_id, f"Could not send '{escape(mod.get('name') or '')}': {escape(str(e))}")
                return
            self._sleep(LATEST_PAUSE)

    def _flavors(self, arg: str) -> str:
        usage = "Set: /flavors forever,retail · no filter: /flavors all · as in settings: /flavors reset"
        if not arg:
            return f"Versions: {self._flavors_state()}\n{usage}"
        word = arg.lower()
        if word == "reset":
            self._bot.set_wanted(None)
        elif word == "all":
            self._bot.set_wanted(frozenset())
        else:
            wanted = frozenset(part for part in word.replace(",", " ").split() if part)
            unknown = wanted - GROUPS
            if unknown:
                return f"Unknown versions: {escape(', '.join(sorted(unknown)))}. Allowed: retail, classic, forever."
            self._bot.set_wanted(wanted)
        return f"Versions: {self._flavors_state()}"

    # --- helpers ---

    def _flavors_state(self) -> str:
        wanted = self._bot.wanted()
        groups = ", ".join(title for group, title in _GROUP_TITLES.items() if group in wanted) or "all"
        source = "set by /flavors" if self._bot.wanted_overridden() else "from settings"
        return f"{groups} ({source})"

    def _reply(self, chat_id: int, text: str) -> None:
        try:
            self._telegram.send_text(chat_id, text)
        except TelegramError as e:
            log.error("could not reply in chat %s: %s", chat_id, e)


def _ago(delta: timedelta) -> str:
    """Human-readable interval: "3 min", "5 h", "2 d"."""
    minutes = max(int(delta.total_seconds() // 60), 0)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // (24 * 60)} d"
