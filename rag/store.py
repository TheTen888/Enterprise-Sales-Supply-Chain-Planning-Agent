import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

from rag.documents import Document, chunk_document


class KnowledgeStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT NOT NULL, version INTEGER NOT NULL,
                    customer_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(document_id, version)
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                    version INTEGER NOT NULL, section TEXT NOT NULL, text TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    FOREIGN KEY(document_id, version) REFERENCES documents(document_id, version)
                );
                CREATE TABLE IF NOT EXISTS grants (
                    actor TEXT NOT NULL, customer_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    PRIMARY KEY(actor, customer_id, project_id)
                );
                CREATE TABLE IF NOT EXISTS state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    data_revision INTEGER NOT NULL, index_revision INTEGER NOT NULL,
                    policy_revision INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO state VALUES (1, 0, 0, 0);
                """
            )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def revisions(self) -> dict:
        with self.connect() as connection:
            return dict(connection.execute("SELECT * FROM state").fetchone())

    def grant(self, actor: str, customer: str, project: str):
        if not all(
            isinstance(value, str) and value.strip() == value and value
            for value in (actor, customer, project)
        ):
            raise ValueError("grant identifiers must be non-empty trimmed text")
        with self.connect() as connection:
            changed = connection.execute(
                "INSERT OR IGNORE INTO grants VALUES (?,?,?)", (actor, customer, project)
            ).rowcount
            if changed:
                connection.execute("UPDATE state SET policy_revision=policy_revision+1")

    def revoke(self, actor: str, customer: str, project: str):
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM grants WHERE actor=? AND customer_id=? AND project_id=?",
                (actor, customer, project),
            )
            connection.execute("UPDATE state SET policy_revision=policy_revision+1")

    def require_access(self, actor: str, customer: str, project: str):
        with self.connect() as connection:
            allowed = connection.execute(
                "SELECT 1 FROM grants WHERE actor=? AND customer_id=? AND project_id=?",
                (actor, customer, project),
            ).fetchone()
        if not allowed:
            raise PermissionError("customer/project access denied")

    def put_documents(self, documents: list[Document]):
        for document in documents:
            document.validate()
        with self.connect() as connection:
            for document in documents:
                scope = connection.execute(
                    "SELECT customer_id, project_id, entity_id FROM documents WHERE document_id=? LIMIT 1",
                    (document.document_id,),
                ).fetchone()
                if scope and tuple(scope) != (
                    document.customer_id,
                    document.project_id,
                    document.entity_id,
                ):
                    raise ValueError("document ownership cannot be reassigned")
                body = json.dumps(asdict(document), sort_keys=True)
                prior = connection.execute(
                    "SELECT body FROM documents WHERE document_id=? AND version=?",
                    (document.document_id, document.version),
                ).fetchone()
                if prior:
                    if prior[0] != body:
                        raise ValueError("document version reused with conflicting content")
                    continue
                connection.execute(
                    "INSERT INTO documents VALUES (?,?,?,?,?,?)",
                    (
                        document.document_id,
                        document.version,
                        document.customer_id,
                        document.project_id,
                        document.entity_id,
                        body,
                    ),
                )
                connection.execute("UPDATE state SET data_revision=data_revision+1")

    def latest(self, document_id: str) -> Document:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT body FROM documents WHERE document_id=? ORDER BY version DESC LIMIT 1",
                (document_id,),
            ).fetchone()
        if row is None:
            raise KeyError(document_id)
        return Document(**json.loads(row[0]))

    def delete(self, document_id: str, effective_on: str):
        prior = self.latest(document_id)
        tombstone = replace(
            prior,
            version=prior.version + 1,
            status="deleted",
            body="",
            effective_from=effective_on,
            observed_on=effective_on,
        )
        self.put_documents([tombstone])

    def refresh_index(self):
        with self.connect() as connection:
            documents = [
                Document(**json.loads(row[0]))
                for row in connection.execute(
                    "SELECT body FROM documents ORDER BY document_id, version"
                )
            ]
            latest = {document.document_id: document for document in documents}
            deleted = {key for key, document in latest.items() if document.status == "deleted"}
            connection.execute("DELETE FROM chunks")
            for document in documents:
                if document.status in {"deleted", "draft"} or document.document_id in deleted:
                    continue
                for index, chunk in enumerate(chunk_document(document.body)):
                    connection.execute(
                        "INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                        (
                            f"{document.document_id}:v{document.version}:c{index + 1}",
                            document.document_id,
                            document.version,
                            chunk["section"],
                            chunk["text"],
                            document.content_hash,
                        ),
                    )
            connection.execute("UPDATE state SET index_revision=data_revision")

    def candidates(
        self, customer: str, project: str, entity: str, design: str, as_of: str
    ) -> list[dict]:
        if date.fromisoformat(as_of).isoformat() != as_of:
            raise ValueError("canonical YYYY-MM-DD date required")
        with self.connect() as connection:
            documents = [
                Document(**json.loads(row[0]))
                for row in connection.execute(
                    "SELECT body FROM documents WHERE customer_id=? AND project_id=? AND entity_id=? ORDER BY version",
                    (customer, project, entity),
                )
            ]
            current = {document.document_id: document for document in documents}
            deleted = {key for key, document in current.items() if document.status == "deleted"}
            latest = {}
            for document in documents:
                if document.observed_on <= as_of and document.effective_from <= as_of:
                    latest[document.document_id] = document
            eligible = {
                key: document
                for key, document in latest.items()
                if document.status in {"approved", "request"}
                and key not in deleted
                and (not document.design_version or document.design_version == design)
            }
            result = []
            for key, document in eligible.items():
                expected = {
                    f"{key}:v{document.version}:c{index + 1}": (chunk["section"], chunk["text"])
                    for index, chunk in enumerate(chunk_document(document.body))
                }
                for row in connection.execute(
                    "SELECT * FROM chunks WHERE document_id=? AND version=? AND source_hash=? ORDER BY chunk_id",
                    (key, document.version, document.content_hash),
                ):
                    if expected.get(row["chunk_id"]) != (row["section"], row["text"]):
                        continue
                    result.append(
                        {
                            **dict(row),
                            "kind": document.kind,
                            "status": document.status,
                            "source_path": document.source_path,
                            "customer_id": document.customer_id,
                            "project_id": document.project_id,
                            "entity_id": document.entity_id,
                            "design_version": document.design_version,
                        }
                    )
            return result

    def context_chunks(self, seed: dict) -> list[dict]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT body FROM documents WHERE document_id=? AND version=?",
                (seed["document_id"], seed["version"]),
            ).fetchone()
        if row is None:
            return []
        document = Document(**json.loads(row[0]))
        if document.status not in {"approved", "request"}:
            return []
        context = [
            {
                "chunk_id": f"{document.document_id}:v{document.version}:c{index + 1}",
                "document_id": document.document_id,
                "version": document.version,
                "section": chunk["section"],
                "text": chunk["text"],
                "source_hash": document.content_hash,
                "kind": document.kind,
                "status": document.status,
                "source_path": document.source_path,
                "customer_id": document.customer_id,
                "project_id": document.project_id,
                "entity_id": document.entity_id,
                "design_version": document.design_version,
            }
            for index, chunk in enumerate(chunk_document(document.body))
        ]
        fields = (
            "chunk_id",
            "document_id",
            "version",
            "section",
            "text",
            "source_hash",
            "customer_id",
            "project_id",
            "entity_id",
            "design_version",
        )
        if not any(all(seed.get(name) == chunk[name] for name in fields) for chunk in context):
            return []
        return context
