from datetime import UTC, datetime, timedelta, timezone

from bot.storage import Storage

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def test_new_storage_has_no_pending():
    assert Storage(":memory:").pending() == {}


def test_add_and_list_pending():
    storage = Storage(":memory:")
    storage.add_pending([5, 3], T0)
    assert storage.pending() == {3: T0, 5: T0}


def test_add_pending_keeps_first_seen():
    storage = Storage(":memory:")
    storage.add_pending([1], T0)
    storage.add_pending([1, 2], T0 + timedelta(hours=1))
    assert storage.pending() == {1: T0, 2: T0 + timedelta(hours=1)}


def test_remove_pending():
    storage = Storage(":memory:")
    storage.add_pending([1, 2, 3], T0)
    storage.remove_pending([1, 3, 99])
    assert list(storage.pending()) == [2]


def test_first_seen_roundtrips_as_aware_utc():
    storage = Storage(":memory:")
    storage.add_pending([1], datetime(2026, 10, 24, 15, 0, tzinfo=timezone(timedelta(hours=3))))
    stamp = storage.pending()[1]
    assert stamp == T0
    assert stamp.utcoffset() == timedelta(0)


def test_persists_between_instances(tmp_path):
    path = tmp_path / "sub" / "bot.db"
    storage = Storage(path)
    storage.add_pending([7], T0)
    storage.set_meta("next_id", "100")
    storage.close()
    again = Storage(path)
    assert again.pending() == {7: T0}
    assert again.get_meta("next_id") == "100"


def test_meta_roundtrip_and_upsert():
    storage = Storage(":memory:")
    assert storage.get_meta("k") is None
    storage.set_meta("k", "1")
    storage.set_meta("k", "2")
    assert storage.get_meta("k") == "2"
