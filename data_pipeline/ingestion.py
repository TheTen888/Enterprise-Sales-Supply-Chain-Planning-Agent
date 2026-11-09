import json
import re
import sqlite3
from pathlib import Path

from config.contracts import Document, fingerprint
from data_pipeline.conversion import convert


class RateLimitError(RuntimeError):
    pass


class LocalIngestion:
    steps = ("fetch", "convert", "chunk", "embed", "upsert")

    def __init__(self, database):
        self.snapshots = Path(database).parent / "source-snapshots"
        self.snapshots.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS checkpoints (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (key TEXT PRIMARY KEY, metadata TEXT NOT NULL, chunks TEXT NOT NULL, converted TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS heads (key TEXT PRIMARY KEY, version INTEGER NOT NULL, hash TEXT NOT NULL, status TEXT NOT NULL);
        """)

    def ingest(self, root, metadata, simulate_rate_limit=False, fault=None):
        doc = Document.model_validate(metadata)
        root = Path(root).resolve()
        path = (root / doc.path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Source path escapes root")
        raw = path.read_bytes()
        raw_hash = fingerprint(raw.hex())
        version_hash = fingerprint([raw_hash, doc.model_dump()])
        scope_id = [doc.customer_id, doc.project_id, doc.document_id]
        head_key = fingerprint(scope_id)
        run_key = fingerprint([*scope_id, version_hash, "pipeline-v1"])
        snapshot = self.snapshots / f"{run_key}{path.suffix}"
        head = self.db.execute("SELECT * FROM heads WHERE key=?", (head_key,)).fetchone()
        if head and (
            doc.version < head["version"]
            or (doc.version == head["version"] and version_hash != head["hash"])
        ):
            raise ValueError("Stale or conflicting document version")
        if head and head["status"] == "deleted" and doc.version <= head["version"]:
            raise ValueError("Deleted source cannot be resurrected")
        completed, skipped = [], []
        values = {}
        for step in self.steps:
            key = fingerprint([run_key, step])
            saved = self.db.execute("SELECT value FROM checkpoints WHERE key=?", (key,)).fetchone()
            if saved:
                values[step] = json.loads(saved[0])
                skipped.append(step)
                continue
            if step == "fetch":
                snapshot.write_bytes(raw)
                result = {"sha256": raw_hash, "size": path.stat().st_size}
            elif step == "convert":
                result = convert(snapshot)
                if doc.kind == "ecn":
                    lead = re.search(r"Minimum lead time: (\d+) days", result["text"])
                    if (
                        not lead
                        or int(lead[1]) != doc.lead_days
                        or f"Status: {doc.status}" not in result["text"]
                        or doc.part_id not in result["text"]
                    ):
                        raise ValueError("ECN content and controlled metadata disagree")
            elif step == "chunk":
                text = values["convert"]["text"]
                result = [
                    {
                        "chunk_id": fingerprint([run_key, i, text[i : i + 600]]),
                        "text": text[i : i + 600],
                    }
                    for i in range(0, len(text), 500)
                ]
            elif step == "embed":
                if simulate_rate_limit:
                    raise RateLimitError(
                        "Simulated 429 before provider acceptance; retry this step"
                    )
                from rag.hybrid_rag import vector

                result = {
                    "mode": "offline-feature-hash",
                    "items": len(values["chunk"]),
                    "api_calls": 0,
                    "vectors": [vector(chunk["text"]) for chunk in values["chunk"]],
                }
            else:
                result = {"document_id": doc.document_id, "version": doc.version}
            with self.db:
                if step == "upsert":
                    latest = self.db.execute(
                        "SELECT * FROM heads WHERE key=?", (head_key,)
                    ).fetchone()
                    if latest and (
                        doc.version < latest["version"]
                        or (doc.version == latest["version"] and version_hash != latest["hash"])
                    ):
                        raise ValueError("Concurrent newer version detected")
                    embedded_chunks = [
                        {**chunk, "embedding": embedding}
                        for chunk, embedding in zip(
                            values["chunk"], values["embed"]["vectors"], strict=True
                        )
                    ]
                    self.db.execute(
                        "INSERT OR REPLACE INTO documents VALUES (?,?,?,?)",
                        (
                            run_key,
                            doc.model_dump_json(),
                            json.dumps(embedded_chunks),
                            json.dumps(values["convert"]),
                        ),
                    )
                    self.db.execute(
                        "INSERT OR REPLACE INTO heads VALUES (?,?,?,?)",
                        (head_key, doc.version, version_hash, doc.status),
                    )
                self.db.execute("INSERT INTO checkpoints VALUES (?,?)", (key, json.dumps(result)))
                if step == "upsert" and fault == "before_publish_commit":
                    raise RuntimeError("Injected failure before publication commit")
            if step == "upsert" and fault == "after_publish_commit":
                raise RuntimeError("Injected failure after publication commit")
            values[step] = result
            completed.append(step)
        return {
            "document_id": doc.document_id,
            "completed": completed,
            "skipped": skipped,
            "lane": values["convert"]["lane"],
        }

    def current(self, scope):
        results = []
        for row in self.db.execute("SELECT * FROM documents"):
            doc = json.loads(row["metadata"])
            if (doc["customer_id"], doc["project_id"]) != (scope.customer_id, scope.project_id):
                continue
            key = fingerprint([doc["customer_id"], doc["project_id"], doc["document_id"]])
            head = self.db.execute("SELECT * FROM heads WHERE key=?", (key,)).fetchone()
            if (
                head["status"] != "active"
                or doc["status"] != "active"
                or doc["version"] != head["version"]
            ):
                continue
            results.append(
                {
                    "metadata": doc,
                    "chunks": json.loads(row["chunks"]),
                    "converted": json.loads(row["converted"]),
                }
            )
        return results

    def delete(self, scope, document_id):
        key = fingerprint([scope.customer_id, scope.project_id, document_id])
        with self.db:
            self.db.execute("UPDATE heads SET status='deleted' WHERE key=?", (key,))
