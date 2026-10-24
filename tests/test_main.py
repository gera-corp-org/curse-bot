import logging
from datetime import UTC, datetime, timedelta

import pytest

from bot.curseforge import BATCH_SIZE, CurseForgeError
from bot.flavors import CLASSIC, FOREVER, build_flavor_map
from bot.main import MAX_BATCHES_PER_CYCLE, PENDING_MAX_AGE, SEND_PAUSE, Bot, main
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


def test_first_run_sets_baseline_and_sends_nothing(caplog):
    curseforge = FakeCurseForge(mod(10), mod(11), max_id=11)
    telegram, storage = FakeTelegram(), Storage(":memory:")
    with caplog.at_level(logging.INFO):
        make_bot(curseforge, telegram, storage).run_once()
    assert storage.get_meta("next_id") == "12"
    assert storage.pending() == {}
    assert telegram.sent == []
    assert curseforge.requests == []
    assert "baseline: следующий id 12" in caplog.text


def test_new_mod_goes_pending_then_sent_once_approved():
    curseforge, bot, storage = started(mod(10))
    telegram = bot._telegram
    curseforge.add(new(11))
    bot.run_once()
    assert list(storage.pending()) == [11]
    assert telegram.sent == []
    curseforge.mods[11] = mod(11)
    bot.run_once()
    assert telegram.names == ["Addon 11"]
    assert telegram.sent[0][1] == ["https://img/11.png"]
    assert storage.pending() == {}
    bot.run_once()
    assert telegram.names == ["Addon 11"]


def test_already_approved_mod_sent_in_same_cycle_in_id_order_with_pause():
    sleeps = []
    curseforge, bot, _ = started(mod(10), sleep=sleeps.append)
    curseforge.add(mod(13), mod(11), mod(12))
    bot.run_once()
    assert bot._telegram.names == ["Addon 11", "Addon 12", "Addon 13"]
    assert sleeps == [SEND_PAUSE] * 3


def test_non_wow_mods_ignored_but_cursor_moves():
    curseforge, bot, storage = started(mod(10))
    curseforge.add(mod(11, game=432), mod(12))
    bot.run_once()
    assert bot._telegram.names == ["Addon 12"]
    assert storage.get_meta("next_id") == "13"


def test_cursor_advances_and_persists():
    curseforge, bot, storage = started(mod(10))
    curseforge.add(mod(15))
    bot.run_once()
    assert storage.get_meta("next_id") == "16"
    assert curseforge.requests[0] == list(range(11, 11 + BATCH_SIZE))
    bot.run_once()
    assert curseforge.requests[-1] == list(range(16, 16 + BATCH_SIZE))  # без новых — курсор прежний
    assert storage.get_meta("next_id") == "16"


def test_empty_window_keeps_cursor():
    curseforge, bot, storage = started(mod(10))
    bot.run_once()
    assert storage.get_meta("next_id") == "11"


def test_catches_up_across_several_windows():
    curseforge, bot, storage = started(mod(10))
    ids = [11, 11 + BATCH_SIZE - 1, 11 + 2 * BATCH_SIZE - 5, 11 + 2 * BATCH_SIZE + 20]
    curseforge.add(*(mod(i) for i in ids))
    bot.run_once()
    assert bot._telegram.names == [f"Addon {i}" for i in ids]
    assert storage.get_meta("next_id") == str(ids[-1] + 1)
    scan_requests = [r for r in curseforge.requests if len(r) == BATCH_SIZE]
    assert len(scan_requests) == 3  # 3-е окно не добито до конца — остановились


def test_batch_cap_warns_and_continues_next_cycle(caplog):
    curseforge, bot, storage = started(mod(10))
    curseforge.add(*(mod(11 + i * BATCH_SIZE + BATCH_SIZE - 1) for i in range(MAX_BATCHES_PER_CYCLE + 3)))
    with caplog.at_level(logging.WARNING):
        bot.run_once()
    assert len([r for r in curseforge.requests if len(r) == BATCH_SIZE]) == MAX_BATCHES_PER_CYCLE
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert storage.get_meta("next_id") == str(11 + MAX_BATCHES_PER_CYCLE * BATCH_SIZE)
    before = len(bot._telegram.sent)
    bot.run_once()
    assert len(bot._telegram.sent) > before


@pytest.mark.parametrize("status", [5, 9])
def test_rejected_or_deleted_removed_without_sending(status):
    curseforge, bot, storage = started(mod(10))
    curseforge.add(new(11))
    bot.run_once()
    curseforge.mods[11] = mod(11, status=status, available=False)
    bot.run_once()
    assert storage.pending() == {}
    assert bot._telegram.sent == []


def test_stale_pending_removed():
    clock = Clock()
    curseforge, bot, storage = started(mod(10), clock=clock)
    curseforge.add(new(11))
    bot.run_once()
    clock.value = NOW + PENDING_MAX_AGE - timedelta(minutes=1)
    bot.run_once()
    assert list(storage.pending()) == [11]
    clock.value = NOW + PENDING_MAX_AGE + timedelta(minutes=1)
    bot.run_once()
    assert storage.pending() == {}
    assert bot._telegram.sent == []


def test_missing_from_api_kept_then_dropped_when_stale():
    clock = Clock()
    curseforge, bot, storage = started(mod(10), clock=clock)
    curseforge.add(new(11))
    bot.run_once()
    del curseforge.mods[11]
    bot.run_once()
    assert list(storage.pending()) == [11]
    clock.value = NOW + PENDING_MAX_AGE + timedelta(minutes=1)
    bot.run_once()
    assert storage.pending() == {}


def test_filter_mismatch_removed_without_sending():
    curseforge, bot, storage = started(mod(10), wanted=frozenset({FOREVER}))
    curseforge.add(mod(11, 517), mod(12, 88568))
    bot.run_once()
    assert bot._telegram.names == ["Addon 12"]
    assert storage.pending() == {}


def test_filter_set_and_no_files_yet_keeps_waiting():
    curseforge, bot, storage = started(mod(10), wanted=frozenset({CLASSIC}))
    curseforge.add(mod(11, files=False))
    bot.run_once()
    assert list(storage.pending()) == [11]
    curseforge.mods[11] = mod(11, 67408)
    bot.run_once()
    assert bot._telegram.names == ["Addon 11"]
    assert storage.pending() == {}


def test_no_filter_sends_even_without_files():
    curseforge, bot, _ = started(mod(10))
    curseforge.add(mod(11, files=False))
    bot.run_once()
    assert bot._telegram.names == ["Addon 11"]


def test_failed_send_stays_pending_and_is_retried():
    telegram = FakeTelegram(fail_times=1)
    curseforge, bot, storage = started(mod(10), telegram=telegram)
    curseforge.add(mod(11))
    bot.run_once()
    assert telegram.names == []
    assert list(storage.pending()) == [11]
    bot.run_once()
    assert telegram.names == ["Addon 11"]
    assert storage.pending() == {}


def test_bad_mod_does_not_block_others():
    curseforge, bot, storage = started(mod(10))
    broken = mod(12)
    broken["authors"] = 5  # форматирование упадёт с TypeError
    curseforge.add(mod(11), broken, mod(13))
    bot.run_once()
    assert bot._telegram.names == ["Addon 11", "Addon 13"]
    assert list(storage.pending()) == [12]


def test_record_without_id_is_ignored():
    curseforge, bot, _ = started(mod(10))
    original = curseforge.get_mods
    curseforge.get_mods = lambda ids: original(ids) + [{"name": "мусор"}, "строка"]
    curseforge.add(mod(11))
    bot.run_once()
    assert bot._telegram.names == ["Addon 11"]


def test_send_latest_collects_approved_wow_backwards_without_touching_storage():
    far = 11 + 3 * BATCH_SIZE
    curseforge = FakeCurseForge(
        mod(11), mod(12), new(13), mod(14, game=432), mod(far, 88568), mod(far + 5)
    )
    telegram, storage = FakeTelegram(), Storage(":memory:")
    bot = make_bot(curseforge, telegram, storage, wanted=frozenset({CLASSIC}))  # фильтр игнорируется
    bot.send_latest(3)
    assert telegram.names == ["Addon 12", f"Addon {far}", f"Addon {far + 5}"]
    assert storage.get_meta("next_id") is None
    assert storage.pending() == {}


def test_send_latest_starts_from_cursor_when_present():
    curseforge = FakeCurseForge(mod(11), mod(12))
    storage = Storage(":memory:")
    storage.set_meta("next_id", "12")
    make_bot(curseforge, FakeTelegram(), storage).send_latest(5)
    assert storage.get_meta("next_id") == "12"
    assert [i for r in curseforge.requests for i in r if i >= 12] == []


def test_send_latest_stops_after_max_windows():
    curseforge = FakeCurseForge(mod(1), max_id=5 * MAX_BATCHES_PER_CYCLE * BATCH_SIZE)
    make_bot(curseforge).send_latest(1)
    assert len(curseforge.requests) == MAX_BATCHES_PER_CYCLE


def test_run_forever_survives_curseforge_errors():
    class Stop(Exception):
        pass

    calls = []

    class Flaky(FakeCurseForge):
        def find_max_id(self):
            calls.append(1)
            if len(calls) == 1:
                raise CurseForgeError("CurseForge ответил 503")
            return 5

    def sleep(seconds):
        assert seconds == 600
        if len(calls) >= 2:
            raise Stop

    storage = Storage(":memory:")
    bot = make_bot(Flaky(), storage=storage, sleep=sleep)
    with pytest.raises(Stop):
        bot.run_forever(600)
    assert storage.get_meta("next_id") == "6"


def test_run_forever_survives_unexpected_errors():
    class Stop(Exception):
        pass

    calls = []

    class Broken(FakeCurseForge):
        def find_max_id(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("неожиданно")
            return 5

    def sleep(seconds):
        if len(calls) >= 2:
            raise Stop

    bot = make_bot(Broken(), sleep=sleep)
    with pytest.raises(Stop):
        bot.run_forever(600)
    assert len(calls) == 2


@pytest.mark.parametrize("value", ["0", "-3"])
def test_send_latest_rejects_non_positive(value):
    with pytest.raises(SystemExit) as exc:
        main(["--send-latest", value])
    assert exc.value.code == 2


def test_run_forever_touches_heartbeat_before_and_after_each_cycle(tmp_path):
    class Stop(Exception):
        pass

    heartbeat = tmp_path / "heartbeat"
    seen = []

    class Watching(FakeCurseForge):
        def find_max_id(self):
            seen.append(heartbeat.exists())  # файл уже есть до первого цикла
            raise RuntimeError("сбой цикла не должен мешать heartbeat")

    def sleep(seconds):
        seen.append(heartbeat.stat().st_mtime_ns)
        if len(seen) >= 4:
            raise Stop

    bot = Bot(Watching(), FakeTelegram(), Storage(":memory:"), build_flavor_map([]), frozenset(),
              sleep=sleep, now=lambda: NOW, heartbeat=heartbeat)
    with pytest.raises(Stop):
        bot.run_forever(600)
    assert seen[0] is True and seen[2] is True
    assert seen[3] >= seen[1]


def test_heartbeat_write_failure_is_logged_not_fatal(tmp_path, caplog):
    class Stop(Exception):
        pass

    def sleep(seconds):
        raise Stop

    bot = Bot(FakeCurseForge(), FakeTelegram(), Storage(":memory:"), build_flavor_map([]), frozenset(),
              sleep=sleep, now=lambda: NOW, heartbeat=tmp_path / "missing-dir" / "heartbeat")
    with caplog.at_level(logging.WARNING), pytest.raises(Stop):
        bot.run_forever(600)
    assert any("heartbeat" in r.getMessage() for r in caplog.records)
