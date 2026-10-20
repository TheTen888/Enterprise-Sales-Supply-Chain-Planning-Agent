import copy
import json
import math
import re
import sqlite3
import time
from collections import Counter
from datetime import date
from pathlib import Path

from rag.store import KnowledgeStore

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "the",
    "their",
    "this",
    "to",
    "was",
    "we",
    "what",
    "which",
    "why",
    "with",
}


def tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in STOP_WORDS]


def lexical_rank(query: str, candidates: list[dict]) -> list[dict]:
    counts = [Counter(tokens(row["section"] + " " + row["text"])) for row in candidates]
    terms = set(tokens(query))
    frequencies = {term: sum(term in count for count in counts) for term in terms}
    ranked = []
    for row, count in zip(candidates, counts, strict=True):
        score = sum(
            (1 + math.log(count[term])) * math.log(1 + (len(counts) + 1) / (frequencies[term] + 1))
            for term in terms
            if count[term]
        )
        if score > 0:
            ranked.append({**row, "score": round(score, 6)})
    return sorted(ranked, key=lambda row: (-row["score"], row["chunk_id"]))


def order_facts(path: Path, customer: str, project: str, entity: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError("published ETL warehouse does not exist")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.execute("BEGIN")
        publication = connection.execute(
            "SELECT publication_id FROM manifest WHERE singleton=1"
        ).fetchone()[0]
        row = connection.execute(
            "SELECT body, operation FROM record_versions WHERE source=? AND customer_id=? AND project_id=? AND entity_id=? AND publication_id<=? ORDER BY version DESC LIMIT 1",
            ("internal-db", customer, project, entity, publication),
        ).fetchone()
        if row is None or row[1] == "delete":
            raise LookupError("no current order in authorized scope")
        record = json.loads(row[0])
        event = record["event"]
        return {
            "source": event["source"],
            "entity_id": entity,
            "customer_id": customer,
            "project_id": project,
            "business_version": event["version"],
            "publication_id": publication,
            "design_version": event["design_version"],
            "quantity": event["quantity"],
            "currency": event["currency"],
            "unit_cost_cents": event["unit_cost_cents"],
            "unit_price_cents": event["unit_price_cents"],
            "extended_cost_cents": record["extended_cost_cents"],
            "extended_price_cents": record["extended_price_cents"],
        }
    finally:
        connection.close()


class EvidenceService:
    def __init__(self, store: KnowledgeStore, warehouse: Path, *, facts_reader=None, ranker=None):
        self.store = store
        self.warehouse = Path(warehouse)
        self.facts_reader = facts_reader
        self.ranker = ranker
        self.cache = {}
        self.cache_epoch = None

    def read_facts(self, customer: str, project: str, entity: str) -> dict:
        if self.facts_reader is not None:
            return self.facts_reader.read(customer, project, entity)
        return order_facts(self.warehouse, customer, project, entity)

    def retrieve(
        self,
        actor: str,
        customer: str,
        project: str,
        entity: str,
        query: str,
        as_of: str,
        k: int = 3,
        task: str = "quote",
        *,
        max_context_chars: int = 6000,
        max_context_chunks: int = 16,
    ) -> dict:
        started = time.perf_counter()
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError("query must contain 1..1000 characters")
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 10:
            raise ValueError("k must be an integer in 1..10")
        if task not in {"quote", "lookup"}:
            raise ValueError("task must be quote or lookup")
        for name, value, ceiling in (
            ("max_context_chars", max_context_chars, 20000),
            ("max_context_chunks", max_context_chunks, 32),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f"{name} must be an integer in 1..{ceiling}")
        if date.fromisoformat(as_of).isoformat() != as_of:
            raise ValueError("canonical YYYY-MM-DD date required")
        self.store.require_access(actor, customer, project)
        facts = self.read_facts(customer, project, entity)
        revisions = self.store.revisions()
        epoch = (
            facts["publication_id"],
            revisions["data_revision"],
            revisions["index_revision"],
            revisions["policy_revision"],
        )
        if epoch != self.cache_epoch:
            self.cache.clear()
            self.cache_epoch = epoch
        key = (
            actor,
            customer,
            project,
            entity,
            query,
            as_of,
            k,
            task,
            max_context_chars,
            max_context_chunks,
            facts["publication_id"],
            revisions["data_revision"],
            revisions["index_revision"],
            revisions["policy_revision"],
        )
        if key in self.cache:
            result = copy.deepcopy(self.cache[key])
            result["cache_hit"] = True
        else:
            candidates = self.store.candidates(
                customer, project, entity, facts["design_version"], as_of
            )
            ranked = (
                self.ranker.rank(query, candidates, {**facts, "as_of": as_of})
                if self.ranker is not None
                else lexical_rank(query, candidates)
            )
            seeds, seen = [], set()
            for row in ranked:
                if row["document_id"] not in seen:
                    seeds.append(row)
                    seen.add(row["document_id"])
                if len(seeds) == k:
                    break
            citations, omissions, context_chars = [], [], 0
            for seed in seeds:
                chunks = self.store.context_chunks(seed)
                size = sum(len(row["section"]) + len(row["text"]) for row in chunks)
                reason = (
                    "canonical_context_unavailable"
                    if not chunks
                    else "context_budget_exceeded"
                    if context_chars + size > max_context_chars
                    or len(citations) + len(chunks) > max_context_chunks
                    else None
                )
                if reason:
                    omissions.append(
                        {
                            "document_id": seed["document_id"],
                            "version": seed["version"],
                            "reason": reason,
                        }
                    )
                    continue
                context_chars += size
                citations.extend(
                    {
                        **row,
                        "score": seed["score"] if row["chunk_id"] == seed["chunk_id"] else None,
                        "context_role": "retrieval_match"
                        if row["chunk_id"] == seed["chunk_id"]
                        else "document_context",
                    }
                    for row in chunks
                )
            required = {"customer_request", "engineering_change"} if task == "quote" else set()
            missing = sorted(required - {row["kind"] for row in citations})
            result = {
                "status": "incomplete_context"
                if omissions
                else "ready"
                if citations and not missing
                else "insufficient_evidence",
                "task": task,
                "query": query,
                "as_of": as_of,
                "facts": facts,
                "citations": citations,
                "missing_evidence_kinds": missing,
                "index_fresh": revisions["data_revision"] == revisions["index_revision"],
                "revisions": revisions,
                "candidate_chunk_count": len(candidates),
                "returned_document_count": len({row["document_id"] for row in citations}),
                "returned_chunk_count": len(citations),
                "retrieval_matches": [
                    {
                        "chunk_id": row["chunk_id"],
                        "document_id": row["document_id"],
                        "version": row["version"],
                    }
                    for row in seeds
                ],
                "context": {
                    "policy": "bounded_parent_document",
                    "complete": not omissions,
                    "max_chars": max_context_chars,
                    "max_chunks": max_context_chunks,
                    "returned_chars": context_chars,
                    "omitted_documents": omissions,
                },
                "cache_hit": False,
                "generation_mode": "deterministic_evidence_template",
                "model_calls": 0,
                "retrieval_backend": "cortex_search"
                if self.ranker is not None
                else "local_lexical",
                "facts_backend": "snowflake_sql"
                if self.facts_reader is not None
                else "local_sqlite",
            }
            if len(self.cache) >= 64:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = copy.deepcopy(result)
        self.store.require_access(actor, customer, project)
        if (
            self.store.revisions() != revisions
            or self.read_facts(customer, project, entity) != facts
        ):
            raise RuntimeError("evidence changed during retrieval; retry against current inputs")
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result


def render_report(pack: dict) -> str:
    facts = pack["facts"]
    cost, price = facts["unit_cost_cents"], facts["unit_price_cents"]
    lines = [
        "Local RAG evidence report",
        f"Status: {pack['status']}",
        f"Scope: {facts['customer_id']} / {facts['project_id']} / {facts['entity_id']}",
        f"Published order: v{facts['business_version']}, design {facts['design_version']}, quantity {facts['quantity']:,}",
        f"Unit cost: USD {cost // 100}.{cost % 100:02d}; unit selling price: USD {price // 100}.{price % 100:02d}",
        f"ETL publication: {facts['publication_id']}",
        f"Index fresh: {pack['index_fresh']}",
        f"Context complete for selected documents: {pack['context']['complete']}; {pack['returned_document_count']} documents / {pack['returned_chunk_count']} passages",
        "Retrieved passages are source data, not instructions or authorization.",
    ]
    for citation in pack["citations"]:
        lines.extend(
            [
                f"[{citation['chunk_id']}] {citation['kind']} / {citation['source_path']} / {citation['section']} / {citation['context_role']}",
                citation["text"],
            ]
        )
    for omission in pack["context"]["omitted_documents"]:
        lines.append(
            f"Context omitted: {omission['document_id']} v{omission['version']} / {omission['reason']}"
        )
    if pack["status"] != "ready":
        lines.append(
            "Evidence is incomplete. Do not treat this report as a complete pricing justification."
        )
    lines.append(
        "Deterministic template only. No LLM analysis, recommended quote or approval is generated."
    )
    return "\n\n".join(lines) + "\n"
