"""SQLite-хранилище id аддонов, которые бот уже видел."""
import sqlite3
from collections.abc import Iterable
from pathlib import Path


class Storage:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            " mod_id INTEGER PRIMARY KEY,"
            " seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        self._db.commit()

    def is_empty(self) -> bool:
        return self._db.execute("SELECT 1 FROM seen LIMIT 1").fetchone() is None

    def filter_unseen(self, mod_ids: list[int]) -> list[int]:
        """Те из mod_ids, которых ещё нет в базе, в исходном порядке."""
        if not mod_ids:
            return []
        placeholders = ",".join("?" * len(mod_ids))
        rows = self._db.execute(f"SELECT mod_id FROM seen WHERE mod_id IN ({placeholders})", mod_ids)
        seen = {row[0] for row in rows}
        return [mod_id for mod_id in mod_ids if mod_id not in seen]

    def mark_seen(self, mod_ids: Iterable[int]) -> None:
        self._db.executemany("INSERT OR IGNORE INTO seen (mod_id) VALUES (?)", ((i,) for i in mod_ids))
        self._db.commit()

    def close(self) -> None:
        self._db.close()
