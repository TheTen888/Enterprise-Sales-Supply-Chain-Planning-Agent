import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from config.contracts import fingerprint
from memory.dual_memory import CustomerMemory
from rag.hybrid_rag import cosine, tokens, vector


def timestamp(value=None):
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value
        else datetime.now(timezone.utc)
    )
    if parsed.tzinfo is None:
        raise ValueError("Memory timestamps require a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def hybrid_rank(rows, query, text_key="text", k=5):
    if not rows:
        return []
    from rank_bm25 import BM25Okapi

    query_tokens = tokens(query)
    if not query_tokens:
        return []
    keyword = BM25Okapi([tokens(row[text_key]) or ["empty"] for row in rows]).get_scores(
        query_tokens
    )
    semantic = [cosine(vector(query), row["embedding"]) for row in rows]
    scores = [0.0] * len(rows)
    for values in (keyword, semantic):
        for rank, index in enumerate(sorted(range(len(rows)), key=lambda i: -values[i])):
            scores[index] += 1 / (61 + rank)
    eligible = [
        i
        for i, row in enumerate(rows)
        if set(query_tokens).intersection(tokens(row[text_key])) or semantic[i] >= 0.25
    ]
    return [
        {**{key: value for key, value in rows[i].items() if key != "embedding"}, "score": scores[i]}
        for i in sorted(eligible, key=lambda i: -scores[i])[:k]
    ]


class ContextEditor:
    def edit(self, messages, max_chars=6000, tool_chars=1200):
        output = []
        for message in messages:
            if message.get("role") == "thinking":
                continue
            clean = {
                key: value
                for key, value in message.items()
                if key not in {"thinking", "reasoning", "reasoning_content", "analysis"}
            }
            content = clean.get("content", "")
            if isinstance(content, list):
                content = [
                    block
                    for block in content
                    if block.get("type") not in {"thinking", "reasoning", "redacted_thinking"}
                ]
            if clean.get("role") == "tool" and len(json.dumps(content)) > tool_chars:
                clean["content"] = json.dumps(
                    {
                        "pruned": True,
                        "preview": str(content)[:tool_chars],
                        "source_ref": clean.get("source_ref", "persisted tool result"),
                        "must_refetch_before_decision": True,
                    }
                )
            else:
                clean["content"] = content
            output.append(clean)
        while len(json.dumps(output)) > max_chars and len(output) > 1:
            output.pop(0)
        if len(json.dumps(output)) > max_chars:
            raise ValueError("Working context exceeds budget; split the input")
        call_ids = {call["id"] for item in output for call in item.get("tool_calls", [])}
        output = [
            item
            for item in output
            if item.get("role") != "tool" or item.get("tool_call_id") in call_ids
        ]
        return output


class MemorySystem(CustomerMemory):
    def __init__(self, path, skills_root=None):
        super().__init__(path)
        self.skills_root = Path(skills_root or Path(__file__).parent / "skills")
        self.editor = ContextEditor()
        self.semantic_backend = None
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (scope TEXT, id TEXT, thread TEXT, happened TEXT, received TEXT, payload TEXT, embedding TEXT, PRIMARY KEY(scope,id));
            CREATE TABLE IF NOT EXISTS facts (scope TEXT, name TEXT, version INTEGER, value TEXT, source TEXT, valid_from TEXT, valid_to TEXT, received TEXT, embedding TEXT, PRIMARY KEY(scope,name,version));
            CREATE TABLE IF NOT EXISTS consolidation (scope TEXT, episode TEXT, report TEXT, PRIMARY KEY(scope,episode));
        """)
        for row in self.db.execute(
            "SELECT p.* FROM preferences p WHERE p.version=(SELECT MAX(q.version) FROM preferences q WHERE q.scope=p.scope AND q.name=p.name)"
        ).fetchall():
            exists = self.db.execute(
                "SELECT 1 FROM facts WHERE scope=? AND name=?", (row["scope"], row["name"])
            ).fetchone()
            if not exists:
                self.store_fact(
                    SimpleNamespace(key=row["scope"]),
                    row["name"],
                    row["value"],
                    row["source"] + " [legacy confirmed import]",
                )

    def save_event(self, scope, thread, content, occurred_at=None, event_id=None):
        happened = timestamp(occurred_at)
        identifier = event_id or fingerprint([scope.key, thread, happened, content])
        encoded = json.dumps(content, sort_keys=True)
        existing = self.db.execute(
            "SELECT payload,happened FROM episodes WHERE scope=? AND id=?", (scope.key, identifier)
        ).fetchone()
        if existing and occurred_at is None:
            happened = existing["happened"]
        if existing and (existing["payload"] != encoded or existing["happened"] != happened):
            raise ValueError("Conflicting event identity")
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO episodes VALUES (?,?,?,?,?,?,?)",
                (
                    scope.key,
                    identifier,
                    thread,
                    happened,
                    timestamp(),
                    encoded,
                    json.dumps(vector(encoded)),
                ),
            )
        report = self.consolidate(scope, identifier)
        return {"event_id": identifier, "consolidation": report}

    def consolidate(self, scope, event_id):
        previous = self.db.execute(
            "SELECT report FROM consolidation WHERE scope=? AND episode=?", (scope.key, event_id)
        ).fetchone()
        if previous:
            return json.loads(previous[0])
        event = self.db.execute(
            "SELECT * FROM episodes WHERE scope=? AND id=?", (scope.key, event_id)
        ).fetchone()
        if not event:
            raise ValueError("Unknown scoped event")
        content = json.loads(event["payload"])
        outcomes = []
        for fact in content.get("facts", []):
            if not fact.get("confirmed") or fact.get("authority") not in {
                "customer",
                "engineering",
            }:
                outcomes.append({"status": "pending_confirmation"})
                continue
            if fact["name"].startswith("ecn:") and fact["authority"] != "engineering":
                outcomes.append({"status": "pending_engineering_confirmation"})
                continue
            outcomes.append(
                self.store_fact(
                    scope,
                    fact["name"],
                    fact["value"],
                    fact.get("source", event_id),
                    fact.get("valid_from", event["happened"]),
                )
            )
        report = {
            "outcomes": outcomes,
            "mode": "confirmed-field-distillation",
            "event_id": event_id,
        }
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO consolidation VALUES (?,?,?)",
                (scope.key, event_id, json.dumps(report)),
            )
        return report

    def store_fact(self, scope, name, value, source, valid_from=None):
        effective = timestamp(valid_from)
        if not isinstance(value, str) or not name or not value.strip():
            raise ValueError("Fact requires a name and nonempty string value")
        with self.db:
            latest = self.db.execute(
                "SELECT * FROM facts WHERE scope=? AND name=? ORDER BY version DESC LIMIT 1",
                (scope.key, name),
            ).fetchone()
            embedding = self.encode(value)
            if latest:
                similarity = cosine(embedding, self.encode(latest["value"]))
                if (
                    similarity >= 0.85
                    and latest["value"].strip().casefold() == value.strip().casefold()
                ):
                    return {
                        "status": "duplicate",
                        "version": latest["version"],
                        "cosine_similarity": similarity,
                    }
                if effective <= latest["valid_from"]:
                    return {"status": "out_of_order_review", "version": latest["version"]}
                self.db.execute(
                    "UPDATE facts SET valid_to=? WHERE scope=? AND name=? AND version=?",
                    (effective, scope.key, name, latest["version"]),
                )
            version = latest["version"] + 1 if latest else 1
            self.db.execute(
                "INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    scope.key,
                    name,
                    version,
                    value,
                    source,
                    effective,
                    None,
                    timestamp(),
                    json.dumps(embedding),
                ),
            )
        return {"status": "updated", "version": version}

    def store_preference(self, scope, name, value, source, confirmed=False):
        if not confirmed:
            return {"status": "pending_confirmation"}
        return self.store_fact(scope, name, value, source)

    def recall(self, scope, as_of=None):
        when = timestamp(as_of)
        rows = self.db.execute(
            "SELECT * FROM facts WHERE scope=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>?) ORDER BY version DESC",
            (scope.key, when, when),
        ).fetchall()
        return {
            row["name"]: {
                "value": row["value"],
                "source": row["source"],
                "version": row["version"],
                "valid_from": row["valid_from"],
            }
            for row in rows
        }

    def retrieve_facts(self, scope, query, as_of=None, k=5):
        active = self.recall(scope, as_of)
        rows = [
            {
                "name": name,
                **fact,
                "text": f"{name}: {fact['value']}",
                "embedding": vector(f"{name}: {fact['value']}"),
            }
            for name, fact in active.items()
        ]
        return self.rank(rows, query, k)

    def recall_events(self, scope, query, start=None, end=None, k=5):
        rows = self.db.execute(
            "SELECT * FROM episodes WHERE scope=? AND happened>=? AND happened<=? ORDER BY happened DESC",
            (
                scope.key,
                timestamp(start) if start else "0000",
                timestamp(end) if end else timestamp(),
            ),
        ).fetchall()
        candidates = [
            {
                "event_id": row["id"],
                "occurred_at": row["happened"],
                "content": json.loads(row["payload"]),
                "text": row["payload"],
                "embedding": json.loads(row["embedding"]),
            }
            for row in rows
        ]
        return self.rank(candidates, query, k)

    def encode(self, text):
        return self.semantic_backend.encode([text])[0] if self.semantic_backend else vector(text)

    def rank(self, rows, query, k):
        if not self.semantic_backend:
            return hybrid_rank(rows, query, k=k)
        if not rows:
            return []
        from rank_bm25 import BM25Okapi

        embeddings = self.semantic_backend.encode([query, *[row["text"] for row in rows]])
        keyword = BM25Okapi([tokens(row["text"]) or ["empty"] for row in rows]).get_scores(
            tokens(query)
        )
        dense = [cosine(embeddings[0], embedding) for embedding in embeddings[1:]]
        scores = [0.0] * len(rows)
        for values in [keyword, dense]:
            for rank, index in enumerate(sorted(range(len(rows)), key=lambda i: -values[i])):
                scores[index] += 1 / (61 + rank)
        candidates = [
            {**rows[i], "score": scores[i]}
            for i in sorted(range(len(rows)), key=lambda i: -scores[i])[:20]
            if dense[i] >= 0.25 or set(tokens(query)).intersection(tokens(rows[i]["text"]))
        ]
        ranked = self.semantic_backend.rerank(query, candidates) if candidates else []
        ranked = [
            row
            for row in ranked
            if "rerank_score" not in row
            or row["rerank_score"] >= getattr(self.semantic_backend, "minimum_memory_score", -5.0)
        ][:k]
        return [{key: value for key, value in row.items() if key != "embedding"} for row in ranked]

    def load_skills(self):
        allowed = ["pricing.md", "capacity.md"]
        return {name: (self.skills_root / name).read_text() for name in allowed}

    def add_turn(self, scope, thread, content):
        super().add_turn(scope, thread, content)
        return self.save_event(scope, thread, content)

    def forget(self, scope, name):
        with self.db:
            self.db.execute("DELETE FROM facts WHERE scope=? AND name=?", (scope.key, name))
        super().forget(scope, name)
