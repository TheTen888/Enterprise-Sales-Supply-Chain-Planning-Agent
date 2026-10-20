import json
import sqlite3
from pathlib import Path

from pipelines.etl.models import Change, canonical


class Source:
    def __init__(self, path: Path, name: str = "internal-db"):
        self.path = Path(path)
        self.name = name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS changes (offset INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)"
            )

    def append(self, payloads: list[dict]):
        with sqlite3.connect(self.path) as connection:
            connection.executemany(
                "INSERT INTO changes(payload) VALUES (?)",
                [(canonical(payload),) for payload in payloads],
            )

    def read_after(self, cursor: int, limit: int) -> list[Change]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT offset, payload FROM changes WHERE offset > ? ORDER BY offset LIMIT ?",
                (cursor, limit),
            ).fetchall()
        return [Change(offset, json.loads(payload)) for offset, payload in rows]

    def remaining(self, cursor: int) -> int:
        with sqlite3.connect(self.path) as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM changes WHERE offset > ?", (cursor,)
            ).fetchone()[0]
