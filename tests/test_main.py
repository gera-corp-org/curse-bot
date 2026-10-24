import pytest

from bot.curseforge import CurseForgeError
from bot.flavors import CLASSIC, FOREVER, build_flavor_map
from bot.main import SEND_PAUSE, Bot
from bot.storage import Storage
from bot.telegram import TelegramError


def mod(mod_id, *type_ids):
    return {
        "id": mod_id,
        "name": f"Addon {mod_id}",
        "summary": "",
        "links": {},
        "authors": [],
        "categories": [],
        "logo": {"url": f"https://img/{mod_id}.png"},
        "screenshots": [],
        "latestFilesIndexes": [{"gameVersionTypeId": t} for t in (type_ids or (517,))],
    }


class FakeCurseForge:
    def __init__(self, *pages):
        self.pages = list(pages)

    def latest_released(self):
        return self.pages.pop(0)


class FakeTelegram:
    def __init__(self, fail_times=0):
        self.sent = []
        self.fail_times = fail_times

    def send_addon(self, caption, images):
        if self.fail_times:
            self.fail_times -= 1
            raise TelegramError("sendPhoto: 400 chat not found")
        self.sent.append((caption, images))

    @property
    def names(self):
        return [caption.split("</b>")[0].removeprefix("🆕 <b>") for caption, _ in self.sent]


def make_bot(curseforge, telegram, storage=None, wanted=frozenset(), sleep=lambda seconds: None):
    return Bot(curseforge, telegram, storage or Storage(":memory:"), build_flavor_map([]), wanted, sleep=sleep)


def test_first_run_is_baseline():
    telegram = FakeTelegram()
    bot = make_bot(FakeCurseForge([mod(2), mod(1)], [mod(2), mod(1)]), telegram)
    bot.run_once()
    bot.run_once()
    assert telegram.sent == []


def test_new_addons_sent_oldest_first_with_pause():
    telegram = FakeTelegram()
    sleeps = []
    bot = make_bot(FakeCurseForge([mod(1)], [mod(4), mod(3), mod(2), mod(1)]), telegram, sleep=sleeps.append)
    bot.run_once()
    bot.run_once()
    assert telegram.names == ["Addon 2", "Addon 3", "Addon 4"]
    assert telegram.sent[0][1] == ["https://img/2.png"]
    assert sleeps == [SEND_PAUSE] * 3


def test_sent_addon_not_repeated():
    telegram = FakeTelegram()
    bot = make_bot(FakeCurseForge([mod(1)], [mod(2), mod(1)], [mod(2), mod(1)]), telegram)
    for _ in range(3):
        bot.run_once()
    assert telegram.names == ["Addon 2"]


def test_filtered_addon_marked_seen_without_sending():
    telegram = FakeTelegram()
    storage = Storage(":memory:")
    page = [mod(3, 88568), mod(2, 517)]
    bot = make_bot(FakeCurseForge([mod(1)], page, page), telegram, storage, wanted=frozenset({FOREVER}))
    for _ in range(3):
        bot.run_once()
    assert telegram.names == ["Addon 3"]
    assert storage.filter_unseen([2, 3]) == []


def test_failed_send_retried_next_cycle():
    telegram = FakeTelegram(fail_times=1)
    storage = Storage(":memory:")
    bot = make_bot(FakeCurseForge([mod(1)], [mod(2), mod(1)], [mod(2), mod(1)]), telegram, storage)
    bot.run_once()
    bot.run_once()
    assert telegram.names == []
    assert storage.filter_unseen([2]) == [2]
    bot.run_once()
    assert telegram.names == ["Addon 2"]


def test_send_latest_ignores_storage_and_filter():
    telegram = FakeTelegram()
    storage = Storage(":memory:")
    bot = make_bot(
        FakeCurseForge([mod(3, 88568), mod(2), mod(1)]), telegram, storage, wanted=frozenset({CLASSIC})
    )
    bot.send_latest(2)
    assert telegram.names == ["Addon 2", "Addon 3"]
    assert storage.is_empty()


def test_run_forever_survives_curseforge_errors():
    class Stop(Exception):
        pass

    calls = []

    class FlakyCurseForge:
        def latest_released(self):
            calls.append(1)
            if len(calls) == 1:
                raise CurseForgeError("CurseForge ответил 503")
            return [mod(1)]

    def sleep(seconds):
        assert seconds == 600
        if len(calls) >= 2:
            raise Stop

    storage = Storage(":memory:")
    bot = make_bot(FlakyCurseForge(), FakeTelegram(), storage, sleep=sleep)
    with pytest.raises(Stop):
        bot.run_forever(600)
    assert len(calls) == 2
    assert not storage.is_empty()
