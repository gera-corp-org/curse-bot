from bot.storage import Storage


def test_new_storage_is_empty():
    assert Storage(":memory:").is_empty()


def test_mark_and_filter():
    storage = Storage(":memory:")
    storage.mark_seen([1, 2])
    assert not storage.is_empty()
    assert storage.filter_unseen([3, 1, 4, 2]) == [3, 4]


def test_filter_empty_list():
    assert Storage(":memory:").filter_unseen([]) == []


def test_mark_seen_twice_is_ok():
    storage = Storage(":memory:")
    storage.mark_seen([1])
    storage.mark_seen([1])
    assert storage.filter_unseen([1]) == []


def test_persists_between_instances(tmp_path):
    path = tmp_path / "sub" / "bot.db"
    storage = Storage(path)
    storage.mark_seen([7])
    storage.close()
    assert Storage(path).filter_unseen([7, 8]) == [8]
