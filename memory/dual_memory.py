import json
import sqlite3

from config.contracts import fingerprint


class CustomerMemory:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (scope TEXT, name TEXT, version INTEGER, value TEXT, source TEXT, PRIMARY KEY(scope,name,version));
            CREATE TABLE IF NOT EXISTS messages (scope TEXT, thread TEXT, sequence INTEGER, content TEXT, PRIMARY KEY(scope,thread,sequence));
        """)

    def store_preference(self, scope, name, value, source, confirmed=False):
        if not confirmed:
            return {"status": "pending_confirmation"}
        previous = self.db.execute(
            "SELECT * FROM preferences WHERE scope=? AND name=? ORDER BY version DESC LIMIT 1",
            (scope.key, name),
        ).fetchone()
        if previous and previous["value"].strip().casefold() == value.strip().casefold():
            return {"status": "duplicate", "version": previous["version"]}
        version = previous["version"] + 1 if previous else 1
        with self.db:
            self.db.execute(
                "INSERT INTO preferences VALUES (?,?,?,?,?)",
                (scope.key, name, version, value, source),
            )
        return {"status": "updated", "version": version}

    def recall(self, scope):
        rows = self.db.execute(
            "SELECT * FROM preferences WHERE scope=? ORDER BY name,version DESC", (scope.key,)
        ).fetchall()
        latest = {}
        for row in rows:
            latest.setdefault(
                row["name"],
                {"value": row["value"], "source": row["source"], "version": row["version"]},
            )
        return latest

    def forget(self, scope, name):
        with self.db:
            self.db.execute("DELETE FROM preferences WHERE scope=? AND name=?", (scope.key, name))

    def add_turn(self, scope, thread, content):
        key = fingerprint([scope.key, thread])
        with self.db:
            sequence = self.db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE scope=? AND thread=?",
                (scope.key, key),
            ).fetchone()[0]
            self.db.execute(
                "INSERT INTO messages VALUES (?,?,?,?)",
                (scope.key, key, sequence, json.dumps(content)),
            )

    def context(self, scope, thread, recent=6, max_chars=2000):
        key = fingerprint([scope.key, thread])
        rows = self.db.execute(
            "SELECT content FROM messages WHERE scope=? AND thread=? ORDER BY sequence",
            (scope.key, key),
        ).fetchall()
        turns = [json.loads(row[0]) for row in rows]
        latest = turns[-recent:]
        notes = {
            "earlier_turns": max(0, len(turns) - recent),
            "confirmed_preferences": self.recall(scope),
        }
        context = json.dumps({"summary": notes, "recent": latest})
        while len(context) > max_chars and latest:
            latest.pop(0)
            context = json.dumps({"summary": notes, "recent": latest})
        if len(context) > max_chars:
            raise ValueError("Confirmed memory exceeds context budget; narrow scope")
        return {
            "summary": notes,
            "recent": latest,
            "characters": len(context),
            "mode": "structured-compaction",
        }
