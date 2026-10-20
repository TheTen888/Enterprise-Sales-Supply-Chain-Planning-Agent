import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pipelines.etl.models import canonical, digest


class DraftStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                    request TEXT NOT NULL, request_hash TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    parent_id TEXT, revision INTEGER NOT NULL, status TEXT NOT NULL,
                    payload TEXT, payload_hash TEXT, approval TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    event TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    actor TEXT NOT NULL, revision INTEGER NOT NULL,
                    payload_hash TEXT NOT NULL, input_fingerprints TEXT NOT NULL,
                    reason_code TEXT NOT NULL, note TEXT NOT NULL,
                    review_status TEXT NOT NULL, created_at_utc TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, job_id):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise LookupError("draft job not found")
        result = dict(row)
        for key in ("request", "payload", "approval"):
            result[key] = json.loads(result[key]) if result[key] is not None else None
        if result["request_hash"] != digest(result["request"]):
            raise ValueError("stored request integrity check failed")
        if result["payload"] is not None and digest(result["payload"]) != result["payload_hash"]:
            raise ValueError("stored draft integrity check failed")
        return result

    def enqueue(self, actor, request, idempotency_key, parent_id=None):
        with self.connect() as connection:
            prior = connection.execute(
                "SELECT job_id, request_hash, parent_id FROM jobs WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if prior:
                if prior["request_hash"] != digest(request) or prior["parent_id"] != parent_id:
                    raise ValueError("idempotency key reused with different inputs")
                return prior["job_id"]
            revision = 1
            if parent_id:
                parent = connection.execute(
                    "SELECT * FROM jobs WHERE job_id=?", (parent_id,)
                ).fetchone()
                if parent is None or parent["actor"] != actor:
                    raise PermissionError("parent draft access denied")
                if parent["status"] not in {
                    "needs_review",
                    "needs_capacity_review",
                    "approved_internal",
                    "rejected",
                }:
                    raise ValueError("parent draft is not current and revisable")
                revision = parent["revision"] + 1
                connection.execute(
                    "UPDATE jobs SET status='superseded' WHERE job_id=?", (parent_id,)
                )
                connection.execute(
                    "INSERT INTO events(job_id,event,body) VALUES (?,?,?)",
                    (
                        parent_id,
                        "manager.revision_invalidates_approval",
                        canonical({"next_revision": revision}),
                    ),
                )
            job_id = uuid4().hex
            connection.execute(
                "INSERT INTO jobs(job_id,actor,request,request_hash,idempotency_key,parent_id,revision,status) VALUES (?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    actor,
                    canonical(request),
                    digest(request),
                    idempotency_key,
                    parent_id,
                    revision,
                    "queued",
                ),
            )
            connection.execute(
                "INSERT INTO events(job_id,event,body) VALUES (?,?,?)",
                (job_id, "draft.queued", canonical({"revision": revision})),
            )
        return job_id

    def claim(self, job_id):
        with self.connect() as connection:
            changed = connection.execute(
                "UPDATE jobs SET status='running' WHERE job_id=? AND status='queued'", (job_id,)
            ).rowcount
        return bool(changed)

    def publish(self, job_id, payload):
        status = (
            "needs_capacity_review"
            if payload["engineering"]["risk"]["requires_capacity_review"]
            else "needs_review"
        )
        with self.connect() as connection:
            if (
                connection.execute(
                    "UPDATE jobs SET status=?,payload=?,payload_hash=? WHERE job_id=? AND status='running'",
                    (status, canonical(payload), digest(payload), job_id),
                ).rowcount
                != 1
            ):
                raise ValueError("draft publication state conflict")

    def transition(self, job_id, status):
        with self.connect() as connection:
            connection.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))

    def approve(self, job_id, approval):
        with self.connect() as connection:
            if (
                connection.execute(
                    "UPDATE jobs SET status='approved_internal',approval=? WHERE job_id=? AND status='needs_review'",
                    (canonical(approval), job_id),
                ).rowcount
                != 1
            ):
                raise ValueError("draft cannot be approved in current state")
            connection.execute(
                "INSERT INTO events(job_id,event,body) VALUES (?,?,?)",
                (job_id, "manager.approved_internal", canonical(approval)),
            )

    def reject(self, job, reason_code, note, idempotency_key):
        with self.connect() as connection:
            previous = connection.execute(
                "SELECT * FROM feedback WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if previous:
                if any(
                    previous[name] != value
                    for name, value in (
                        ("job_id", job["job_id"]),
                        ("actor", job["actor"]),
                        ("reason_code", reason_code),
                        ("note", note),
                    )
                ):
                    raise ValueError("feedback idempotency key reused with different inputs")
                return previous["feedback_id"]
            if (
                connection.execute(
                    "UPDATE jobs SET status='rejected' WHERE job_id=? AND actor=? "
                    "AND payload_hash=? AND status IN ('needs_review','needs_capacity_review')",
                    (job["job_id"], job["actor"], job["payload_hash"]),
                ).rowcount
                != 1
            ):
                raise ValueError("draft is not eligible for rejection")
            feedback_id = uuid4().hex
            connection.execute(
                "INSERT INTO feedback VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    feedback_id,
                    job["job_id"],
                    job["actor"],
                    job["revision"],
                    job["payload_hash"],
                    canonical(job["payload"]["input_fingerprints"]),
                    reason_code,
                    note,
                    "pending_review",
                    datetime.now(UTC).isoformat(),
                    idempotency_key,
                ),
            )
            connection.execute(
                "INSERT INTO events(job_id,event,body) VALUES (?,?,?)",
                (
                    job["job_id"],
                    "manager.rejected",
                    canonical({"feedback_id": feedback_id, "reason_code": reason_code}),
                ),
            )
            return feedback_id

    def feedback(self, job_id):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM feedback WHERE job_id=? ORDER BY rowid", (job_id,)
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["input_fingerprints"] = json.loads(row["input_fingerprints"])
            row.pop("idempotency_key")
        return result

    def job_ids(self, actor):
        with self.connect() as connection:
            return [
                row[0]
                for row in connection.execute(
                    "SELECT job_id FROM jobs WHERE actor=? ORDER BY rowid", (actor,)
                )
            ]

    def event(self, job_id, name, body):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO events(job_id,event,body) VALUES (?,?,?)",
                (job_id, name, canonical(body)),
            )

    def trace(self, job_id):
        with self.connect() as connection:
            return [
                {"seq": row["seq"], "event": row["event"], "body": json.loads(row["body"])}
                for row in connection.execute(
                    "SELECT * FROM events WHERE job_id=? ORDER BY seq", (job_id,)
                )
            ]
