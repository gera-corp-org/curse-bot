"""SQLite-хранилище бота: аддоны, ожидающие публикации, и служебные значения."""
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path


class Storage:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS pending (mod_id INTEGER PRIMARY KEY, first_seen TEXT NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._db.commit()

    def add_pending(self, mod_ids: Iterable[int], first_seen: datetime) -> None:
        """Поставить id в очередь на публикацию; уже ожидающие сохраняют прежний first_seen."""
        stamp = first_seen.astimezone(UTC).isoformat()
        self._db.executemany("INSERT OR IGNORE INTO pending (mod_id, first_seen) VALUES (?, ?)", ((i, stamp) for i in mod_ids))
        self._db.commit()

    def pending(self) -> dict[int, datetime]:
        """Ожидающие id → когда бот их впервые увидел (aware UTC)."""
        rows = self._db.execute("SELECT mod_id, first_seen FROM pending ORDER BY mod_id")
        return {mod_id: datetime.fromisoformat(stamp) for mod_id, stamp in rows}

    def remove_pending(self, mod_ids: Iterable[int]) -> None:
        self._db.executemany("DELETE FROM pending WHERE mod_id = ?", ((i,) for i in mod_ids))
        self._db.commit()

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def set_meta(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()
