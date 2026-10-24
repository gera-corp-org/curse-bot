from datetime import UTC, datetime, timedelta

import pytest

from bot.curseforge import PAGE_SIZE, CurseForgeError
from bot.flavors import CLASSIC, FOREVER, build_flavor_map
from bot.main import MAX_PAGES, NEW_MAX_AGE, SEND_PAUSE, Bot, main
from bot.storage import Storage
from bot.telegram import TelegramError


NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
RECENT = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
OLD = (NOW - NEW_MAX_AGE - timedelta(days=1)).isoformat().replace("+00:00", "Z")


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def mod(mod_id, *type_ids, created=RECENT, released=RECENT):
    result = {
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
    if created is not None:
        result["dateCreated"] = created
    if released is not None:
        result["dateReleased"] = released
    return result


class FakeCurseForge:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.indexes = []

    def latest_released(self, index=0):
        self.indexes.append(index)
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
    return Bot(
        curseforge, telegram, storage or Storage(":memory:"), build_flavor_map([]), wanted, sleep=sleep, now=lambda: NOW
    )


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
        def latest_released(self, index=0):
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


def test_updated_old_addon_marked_seen_without_sending():
    telegram = FakeTelegram()
    storage = Storage(":memory:")
    page = [mod(3), mod(2, created=OLD)]
    bot = make_bot(FakeCurseForge([mod(1)], page, page), telegram, storage)
    for _ in range(3):
        bot.run_once()
    assert telegram.names == ["Addon 3"]
    assert storage.filter_unseen([2, 3]) == []


def test_missing_or_bad_created_counts_as_new():
    telegram = FakeTelegram()
    bot = make_bot(FakeCurseForge([mod(1)], [mod(3, created="мусор"), mod(2, created=None)]), telegram)
    bot.run_once()
    bot.run_once()
    assert telegram.names == ["Addon 2", "Addon 3"]


def full_page(first_id, newest):
    """PAGE_SIZE аддонов от новых к старым; dateReleased убывает на минуту."""
    return [
        mod(first_id + i, released=iso(newest - timedelta(minutes=i)), created=iso(newest - timedelta(minutes=i)))
        for i in range(PAGE_SIZE)
    ]


def seeded_storage(watermark):
    storage = Storage(":memory:")
    storage.mark_seen([1])
    if watermark:
        storage.set_meta("last_released", iso(watermark))
    return storage


def test_fetches_next_page_while_watermark_not_reached():
    curseforge = FakeCurseForge(full_page(1000, NOW), [mod(5, released=iso(NOW - timedelta(days=1)))])
    telegram = FakeTelegram()
    storage = seeded_storage(NOW - timedelta(days=2))
    make_bot(curseforge, telegram, storage).run_once()
    assert curseforge.indexes == [0, PAGE_SIZE]
    assert "Addon 5" in telegram.names
    assert len(telegram.names) == PAGE_SIZE + 1


def test_stops_when_watermark_reached():
    curseforge = FakeCurseForge(full_page(1000, NOW))
    storage = seeded_storage(NOW - timedelta(minutes=10))  # внутри первой страницы
    make_bot(curseforge, FakeTelegram(), storage).run_once()
    assert curseforge.indexes == [0]


def test_stops_at_max_pages_with_warning(caplog):
    pages = [full_page(1000 * (i + 1), NOW) for i in range(MAX_PAGES + 2)]
    curseforge = FakeCurseForge(*pages)
    storage = seeded_storage(NOW - timedelta(days=2))
    with caplog.at_level("WARNING"):
        make_bot(curseforge, FakeTelegram(), storage).run_once()
    assert curseforge.indexes == [PAGE_SIZE * i for i in range(MAX_PAGES)]
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_no_watermark_means_first_page_only():
    curseforge = FakeCurseForge(full_page(1000, NOW))
    make_bot(curseforge, FakeTelegram(), seeded_storage(None)).run_once()
    assert curseforge.indexes == [0]


def test_short_page_means_no_more_pages():
    curseforge = FakeCurseForge([mod(5)])
    make_bot(curseforge, FakeTelegram(), seeded_storage(NOW - timedelta(days=2))).run_once()
    assert curseforge.indexes == [0]


def test_duplicates_across_pages_sent_once():
    page1 = full_page(1000, NOW)
    page2 = [page1[-1], mod(5, released=iso(NOW - timedelta(days=1)))]
    telegram = FakeTelegram()
    make_bot(FakeCurseForge(page1, page2), telegram, seeded_storage(NOW - timedelta(days=2))).run_once()
    assert len(telegram.names) == len(set(telegram.names)) == PAGE_SIZE + 1


def test_baseline_stores_watermark():
    storage = Storage(":memory:")
    older = iso(NOW - timedelta(hours=5))
    page = [mod(2, released=iso(NOW)), mod(1, released=older), mod(3, released=None)]
    make_bot(FakeCurseForge(page), FakeTelegram(), storage).run_once()
    assert storage.get_meta("last_released") == NOW.isoformat()


def test_watermark_advances_after_cycle_and_never_goes_back():
    storage = seeded_storage(NOW - timedelta(days=1))
    newer = NOW - timedelta(minutes=5)
    bot = make_bot(FakeCurseForge([mod(2, released=iso(newer))], [mod(2, released=iso(NOW - timedelta(days=3)))]),
                   FakeTelegram(), storage)
    bot.run_once()
    assert storage.get_meta("last_released") == newer.isoformat()
    bot.run_once()
    assert storage.get_meta("last_released") == newer.isoformat()


def test_bad_mod_does_not_block_next_ones():
    broken = mod(3)
    broken["authors"] = 5  # форматирование упадёт с TypeError
    telegram = FakeTelegram()
    storage = Storage(":memory:")
    bot = make_bot(FakeCurseForge([mod(1)], [mod(4), broken, mod(2)]), telegram, storage)
    bot.run_once()
    bot.run_once()
    assert telegram.names == ["Addon 2", "Addon 4"]
    assert storage.filter_unseen([3]) == [3]


def test_run_forever_survives_unexpected_errors():
    class Stop(Exception):
        pass

    calls = []

    class BrokenCurseForge:
        def latest_released(self, index=0):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("неожиданно")
            return [mod(1)]

    def sleep(seconds):
        if len(calls) >= 2:
            raise Stop

    bot = make_bot(BrokenCurseForge(), FakeTelegram(), sleep=sleep)
    with pytest.raises(Stop):
        bot.run_forever(600)
    assert len(calls) == 2


@pytest.mark.parametrize("value", ["0", "-3"])
def test_send_latest_rejects_non_positive(value):
    with pytest.raises(SystemExit) as exc:
        main(["--send-latest", value])
    assert exc.value.code == 2
