"""Фейковые CurseForge и Telegram и сборка Bot для тестов."""
from datetime import UTC, datetime

from bot.flavors import build_flavor_map
from bot.main import Bot
from bot.storage import Storage
from bot.telegram import TelegramError

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def mod(mod_id, *type_ids, game=1, status=4, available=True, files=True):
    indexes = [{"gameVersionTypeId": t} for t in (type_ids or (517,))] if files else []
    return {
        "id": mod_id,
        "gameId": game,
        "name": f"Addon {mod_id}",
        "summary": "",
        "links": {},
        "authors": [],
        "categories": [],
        "logo": {"url": f"https://img/{mod_id}.png"},
        "screenshots": [],
        "status": status,
        "isAvailable": available,
        "latestFilesIndexes": indexes,
    }


def new(mod_id, *type_ids, **kwargs):
    """Аддон на модерации: status 1, isAvailable false."""
    return mod(mod_id, *type_ids, status=1, available=False, **kwargs)


class FakeCurseForge:
    def __init__(self, *mods, max_id=None):
        self.mods = {m["id"]: m for m in mods}
        self.max_id = max_id
        self.requests = []

    def get_mods(self, ids):
        self.requests.append(list(ids))
        return [self.mods[i] for i in ids if i in self.mods]

    def find_max_id(self):
        return self.max_id if self.max_id is not None else max(self.mods)

    def add(self, *mods):
        for m in mods:
            self.mods[m["id"]] = m


class FakeTelegram:
    def __init__(self, fail_times=0, updates=None, on_poll=None):
        self.sent = []  # публикации в канал: (caption, images)
        self.private = []  # аддоны в личный чат: (chat_id, caption, images)
        self.texts = []  # текстовые ответы: (chat_id, text)
        self.fail_times = fail_times
        self.updates = list(updates or [])  # пачки для getUpdates (или исключения)
        self.polls = []  # (offset, timeout)
        self.on_poll = on_poll  # вызывается с timeout — двигать фейковые часы
        self.menu = None

    def send_addon(self, caption, images, chat_id=None):
        if self.fail_times:
            self.fail_times -= 1
            raise TelegramError("sendPhoto: 400 chat not found")
        if chat_id is None:
            self.sent.append((caption, images))
        else:
            self.private.append((chat_id, caption, images))

    def send_text(self, chat_id, text):
        self.texts.append((chat_id, text))

    def get_updates(self, offset, timeout):
        self.polls.append((offset, timeout))
        batch = self.updates.pop(0) if self.updates else []
        if isinstance(batch, Exception):
            raise batch  # ошибка возвращается сразу, без ожидания
        if self.on_poll:
            self.on_poll(timeout)  # пустой long poll держится весь timeout
        return batch

    def set_my_commands(self, commands):
        self.menu = commands

    @property
    def names(self):
        return [caption.split("</b>")[0].removeprefix("🆕 <b>") for caption, _ in self.sent]


class Clock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        return self.value


def make_bot(curseforge, telegram=None, storage=None, wanted=frozenset(), sleep=lambda seconds: None, clock=None):
    return Bot(
        curseforge,
        telegram or FakeTelegram(),
        storage or Storage(":memory:"),
        build_flavor_map([]),
        wanted,
        sleep=sleep,
        now=clock or (lambda: NOW),
    )


def started(*mods, cursor=None, **kwargs):
    """Бот после baseline: курсор стоит сразу за последним из mods (или на cursor)."""
    curseforge = FakeCurseForge(*mods)
    storage = kwargs.setdefault("storage", Storage(":memory:"))
    storage.set_meta("next_id", str(cursor if cursor is not None else max(curseforge.mods) + 1))
    return curseforge, make_bot(curseforge, **kwargs), storage
