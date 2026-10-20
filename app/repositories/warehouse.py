import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from pipelines.etl.models import Change, Event, Fault, Record, ValidationError, canonical, digest
from pipelines.etl.validate import validate_record


def restore_record(body: str) -> Record:
    value = json.loads(body)
    return Record(
        Event(**value["event"]), value["extended_cost_cents"], value["extended_price_cents"]
    )


class Warehouse:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    source TEXT PRIMARY KEY, cursor INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS scopes (
                    source TEXT NOT NULL, entity_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    PRIMARY KEY(source, entity_id)
                );
                CREATE TABLE IF NOT EXISTS batches (
                    batch_id TEXT PRIMARY KEY, source TEXT NOT NULL,
                    lower_cursor INTEGER NOT NULL, upper_cursor INTEGER NOT NULL,
                    input_hash TEXT NOT NULL, state TEXT NOT NULL,
                    publication_id INTEGER, report TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(source, lower_cursor)
                );
                CREATE TABLE IF NOT EXISTS raw_changes (
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    offset INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(batch_id, offset)
                );
                CREATE TABLE IF NOT EXISTS staged_records (
                    batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                    position INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(batch_id, position)
                );
                CREATE TABLE IF NOT EXISTS quarantine (
                    batch_id TEXT PRIMARY KEY REFERENCES batches(batch_id),
                    reasons TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publications (
                    publication_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL UNIQUE REFERENCES batches(batch_id)
                );
                CREATE TABLE IF NOT EXISTS manifest (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    publication_id INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO manifest VALUES (1, 0);
                CREATE TABLE IF NOT EXISTS record_versions (
                    source TEXT NOT NULL, entity_id TEXT NOT NULL,
                    version INTEGER NOT NULL, publication_id INTEGER NOT NULL
                        REFERENCES publications(publication_id),
                    customer_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    operation TEXT NOT NULL, content_hash TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(source, entity_id, version)
                );
                CREATE TABLE IF NOT EXISTS processed_events (
                    source TEXT NOT NULL, event_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL, batch_id TEXT NOT NULL,
                    PRIMARY KEY(source, event_id)
                );
                CREATE INDEX IF NOT EXISTS idx_record_scope ON record_versions(
                    customer_id, project_id, source, entity_id, version
                );
                """
            )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def authorize(self, source: str, entity_id: str, customer_id: str, project_id: str):
        self.authorize_many(source, [(entity_id, customer_id, project_id)])

    def authorize_many(self, source: str, ownerships: list[tuple[str, str, str]]):
        with self.transaction() as connection:
            for entity_id, customer_id, project_id in ownerships:
                if not all(
                    isinstance(value, str) and value.strip()
                    for value in (source, entity_id, customer_id, project_id)
                ):
                    raise ValueError("non-empty source and scope identifiers required")
                prior = connection.execute(
                    "SELECT customer_id, project_id FROM scopes WHERE source=? AND entity_id=?",
                    (source, entity_id),
                ).fetchone()
                history = connection.execute(
                    "SELECT customer_id, project_id FROM record_versions WHERE source=? AND entity_id=? LIMIT 1",
                    (source, entity_id),
                ).fetchone()
                if any(row and tuple(row) != (customer_id, project_id) for row in [prior, history]):
                    raise ValueError("entity ownership cannot be reassigned by this prototype")
                connection.execute(
                    "INSERT OR IGNORE INTO scopes VALUES (?, ?, ?, ?)",
                    (source, entity_id, customer_id, project_id),
                )

    def revoke(self, source: str, entity_id: str):
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM scopes WHERE source=? AND entity_id=?", (source, entity_id)
            )

    def scope(self, source: str, entity_id: str) -> tuple | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT customer_id, project_id FROM scopes WHERE source=? AND entity_id=?",
                (source, entity_id),
            ).fetchone()
        return tuple(row) if row else None

    def scopes_for(self, source: str, entity_ids: set[str]) -> dict:
        result = {}
        keys = sorted(entity_ids)
        with self.connect() as connection:
            for start in range(0, len(keys), 500):
                portion = keys[start : start + 500]
                placeholders = ",".join("?" for _ in portion)
                rows = connection.execute(
                    f"SELECT entity_id, customer_id, project_id FROM scopes WHERE source=? AND entity_id IN ({placeholders})",
                    (source, *portion),
                ).fetchall()
                result.update({row[0]: (row[1], row[2]) for row in rows})
        return result

    def cursor(self, source: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT cursor FROM checkpoints WHERE source=?", (source,)
            ).fetchone()
        return row[0] if row else 0

    def batch(self, batch_id: str) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
        if row is None:
            raise KeyError(batch_id)
        return dict(row)

    def pending(self, source: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM batches WHERE source=? AND state!='completed' ORDER BY lower_cursor LIMIT 1",
                (source,),
            ).fetchone()
        return dict(row) if row else None

    def save_batch(self, source: str, lower: int, changes: list[Change]) -> str:
        raw = [[change.offset, change.payload] for change in changes]
        input_hash = digest(raw)
        batch_id = digest([source, lower, changes[-1].offset, input_hash])
        with self.transaction() as connection:
            connection.execute("INSERT OR IGNORE INTO checkpoints VALUES (?, 0)", (source,))
            current = connection.execute(
                "SELECT cursor FROM checkpoints WHERE source=?", (source,)
            ).fetchone()[0]
            if current != lower:
                raise RuntimeError("source checkpoint changed; retry extraction")
            prior = connection.execute(
                "SELECT batch_id FROM batches WHERE source=? AND lower_cursor=?",
                (source, lower),
            ).fetchone()
            if prior:
                return prior[0]
            connection.execute(
                "INSERT INTO batches(batch_id,source,lower_cursor,upper_cursor,input_hash,state) VALUES (?,?,?,?,?,'extracted')",
                (batch_id, source, lower, changes[-1].offset, input_hash),
            )
            connection.executemany(
                "INSERT INTO raw_changes VALUES (?,?,?)",
                [(batch_id, change.offset, canonical(change.payload)) for change in changes],
            )
        return batch_id

    def raw(self, batch_id: str) -> list[Change]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT offset, body FROM raw_changes WHERE batch_id=? ORDER BY offset",
                (batch_id,),
            ).fetchall()
        changes = [Change(row[0], json.loads(row[1])) for row in rows]
        if (
            digest([[change.offset, change.payload] for change in changes])
            != self.batch(batch_id)["input_hash"]
        ):
            raise ValidationError("pinned input digest mismatch")
        return changes

    def quarantine(self, batch_id: str, reasons: list[dict]):
        with self.transaction() as connection:
            state = connection.execute(
                "SELECT state FROM batches WHERE batch_id=?", (batch_id,)
            ).fetchone()[0]
            if state in {"published", "completed"}:
                return
            connection.execute(
                "UPDATE batches SET state='quarantined' WHERE batch_id=?", (batch_id,)
            )
            connection.execute(
                "INSERT INTO quarantine VALUES (?,?) ON CONFLICT(batch_id) DO UPDATE SET reasons=excluded.reasons",
                (batch_id, canonical(reasons)),
            )

    def stage(self, batch_id: str, records: list[Record]):
        with self.transaction() as connection:
            state = connection.execute(
                "SELECT state FROM batches WHERE batch_id=?", (batch_id,)
            ).fetchone()[0]
            if state in {"published", "completed"}:
                return
            connection.execute("DELETE FROM staged_records WHERE batch_id=?", (batch_id,))
            connection.executemany(
                "INSERT INTO staged_records VALUES (?,?,?)",
                [
                    (batch_id, index, canonical(asdict(record)))
                    for index, record in enumerate(records)
                ],
            )
            connection.execute("UPDATE batches SET state='staged' WHERE batch_id=?", (batch_id,))

    def publish(self, batch_id: str, fault: Fault) -> int:
        with self.transaction() as connection:
            batch = connection.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if batch["state"] in {"published", "completed"}:
                return batch["publication_id"]
            if batch["state"] != "staged":
                raise RuntimeError("only staged batches can publish")
            cursor = connection.execute(
                "SELECT cursor FROM checkpoints WHERE source=?", (batch["source"],)
            ).fetchone()[0]
            if cursor != batch["lower_cursor"]:
                raise RuntimeError("checkpoint conflict during publication")
            records = [
                restore_record(row[0])
                for row in connection.execute(
                    "SELECT body FROM staged_records WHERE batch_id=? ORDER BY position",
                    (batch_id,),
                )
            ]
            if (
                len(records)
                != connection.execute(
                    "SELECT COUNT(*) FROM raw_changes WHERE batch_id=?", (batch_id,)
                ).fetchone()[0]
            ):
                raise ValidationError("stage/raw count mismatch")
            publication = connection.execute(
                "INSERT INTO publications(batch_id) VALUES (?)", (batch_id,)
            ).lastrowid
            stats = {
                "input_rows": len(records),
                "inserted_versions": 0,
                "duplicate_events": 0,
                "same_versions": 0,
                "stale_versions": 0,
            }
            for record in records:
                event = record.event
                validate_record(record)
                scope = connection.execute(
                    "SELECT customer_id, project_id FROM scopes WHERE source=? AND entity_id=?",
                    (event.source, event.entity_id),
                ).fetchone()
                if scope is None or tuple(scope) != (event.customer_id, event.project_id):
                    raise ValidationError("scope changed before publication")
                previous_event = connection.execute(
                    "SELECT content_hash FROM processed_events WHERE source=? AND event_id=?",
                    (event.source, event.event_id),
                ).fetchone()
                if previous_event:
                    if previous_event[0] != event.content_hash:
                        raise ValidationError("event ID reused with different content")
                    stats["duplicate_events"] += 1
                    continue
                previous_version = connection.execute(
                    "SELECT content_hash FROM record_versions WHERE source=? AND entity_id=? AND version=?",
                    (event.source, event.entity_id, event.version),
                ).fetchone()
                if previous_version and previous_version[0] != event.content_hash:
                    raise ValidationError("business version has conflicting content")
                latest = connection.execute(
                    "SELECT MAX(version) FROM record_versions WHERE source=? AND entity_id=?",
                    (event.source, event.entity_id),
                ).fetchone()[0]
                if previous_version:
                    stats["same_versions"] += 1
                elif latest is not None and event.version < latest:
                    stats["stale_versions"] += 1
                else:
                    connection.execute(
                        "INSERT INTO record_versions VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            event.source,
                            event.entity_id,
                            event.version,
                            publication,
                            event.customer_id,
                            event.project_id,
                            event.operation,
                            event.content_hash,
                            canonical(asdict(record)),
                        ),
                    )
                    stats["inserted_versions"] += 1
                connection.execute(
                    "INSERT INTO processed_events VALUES (?,?,?,?)",
                    (event.source, event.event_id, event.content_hash, batch_id),
                )
                fault.hit("during_publish")
            connection.execute(
                "UPDATE manifest SET publication_id=? WHERE singleton=1", (publication,)
            )
            connection.execute(
                "UPDATE batches SET state='published',publication_id=?,report=? WHERE batch_id=?",
                (publication, canonical(stats), batch_id),
            )
        return publication

    def commit_checkpoint(self, batch_id: str):
        with self.transaction() as connection:
            batch = connection.execute(
                "SELECT * FROM batches WHERE batch_id=?", (batch_id,)
            ).fetchone()
            if batch["state"] == "completed":
                return
            if batch["state"] != "published":
                raise RuntimeError("only published batches can advance a checkpoint")
            changed = connection.execute(
                "UPDATE checkpoints SET cursor=? WHERE source=? AND cursor=?",
                (batch["upper_cursor"], batch["source"], batch["lower_cursor"]),
            ).rowcount
            if changed != 1:
                raise RuntimeError("checkpoint conflict during acknowledgement")
            connection.execute("UPDATE batches SET state='completed' WHERE batch_id=?", (batch_id,))

    def current(
        self, customer_id: str, project_id: str, publication: int | None = None
    ) -> list[dict]:
        with self.connect() as connection:
            if publication is None:
                publication = connection.execute("SELECT publication_id FROM manifest").fetchone()[
                    0
                ]
            rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT body, operation, ROW_NUMBER() OVER (
                        PARTITION BY source, entity_id ORDER BY version DESC
                    ) AS rank
                    FROM record_versions
                    WHERE publication_id<=? AND customer_id=? AND project_id=?
                )
                SELECT body FROM ranked WHERE rank=1 AND operation!='delete'
                ORDER BY json_extract(body, '$.event.entity_id')
                """,
                (publication, customer_id, project_id),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def counts(self) -> dict:
        with self.connect() as connection:
            return {
                "record_versions": connection.execute(
                    "SELECT COUNT(*) FROM record_versions"
                ).fetchone()[0],
                "processed_events": connection.execute(
                    "SELECT COUNT(*) FROM processed_events"
                ).fetchone()[0],
                "publications": connection.execute("SELECT COUNT(*) FROM publications").fetchone()[
                    0
                ],
                "quarantined_batches": connection.execute(
                    "SELECT COUNT(*) FROM quarantine"
                ).fetchone()[0],
                "active_publication": connection.execute(
                    "SELECT publication_id FROM manifest"
                ).fetchone()[0],
            }
