import uuid
from pathlib import Path

from config.contracts import Scope
from memory.architecture import MemorySystem


def evaluate_memory(root, semantic_backend=None):
    path = Path(root) / f"memory-eval-{uuid.uuid4().hex}.sqlite"
    memory = MemorySystem(path)
    memory.semantic_backend = semantic_backend
    scope = Scope(customer_id="CUSTOMER-A", project_id="PROJECT-A")
    other = Scope(customer_id="CUSTOMER-B", project_id="PROJECT-B")
    event1 = memory.save_event(
        scope,
        "thread",
        {
            "event": "rush quote January",
            "facts": [
                {
                    "name": "shipping",
                    "value": "FOB Alpha",
                    "confirmed": True,
                    "authority": "customer",
                }
            ],
        },
        "2026-01-01T10:00:00Z",
        "first",
    )
    memory.save_event(
        scope,
        "thread",
        {
            "event": "rush quote February",
            "facts": [
                {
                    "name": "shipping",
                    "value": "FOB Beta",
                    "confirmed": True,
                    "authority": "customer",
                }
            ],
        },
        "2026-02-01T10:00:00Z",
        "second",
    )
    recalled = memory.recall_events(
        scope, "rush quote", start="2026-01-01T00:00:00Z", end="2026-01-31T23:59:59Z"
    )
    temporal = [
        any(row["event_id"] == event1["event_id"] for row in recalled),
        all(row["event_id"] != "second" for row in recalled),
        memory.recall(scope, "2026-01-15T00:00:00Z")["shipping"]["value"] == "FOB Alpha",
    ]
    memory.save_event(
        scope,
        "engineering",
        {
            "facts": [
                {
                    "name": "ecn:ECN-001",
                    "value": "14 days",
                    "confirmed": True,
                    "authority": "engineering",
                }
            ]
        },
        "2026-01-01T10:00:00Z",
        "ecn1",
    )
    memory.save_event(
        scope,
        "engineering",
        {
            "facts": [
                {
                    "name": "ecn:ECN-001",
                    "value": "28 days",
                    "confirmed": True,
                    "authority": "engineering",
                }
            ]
        },
        "2026-02-01T10:00:00Z",
        "ecn2",
    )
    contradictions = [
        memory.recall(scope)["shipping"]["value"] == "FOB Beta",
        memory.recall(scope)["ecn:ECN-001"]["value"] == "28 days",
    ]
    unknown = [
        not memory.retrieve_facts(scope, "unmentioned warranty certification"),
        not memory.retrieve_facts(other, "shipping"),
        not memory.recall_events(
            scope, "rush quote", start="2027-01-01T00:00:00Z", end="2027-02-01T00:00:00Z"
        ),
    ]
    known_answered = bool(memory.retrieve_facts(scope, "shipping"))
    return {
        "scope": "Synthetic memory lifecycle tests; not a real-model memory benchmark",
        "metrics": {
            "temporal_recall": float(
                any(row["event_id"] == event1["event_id"] for row in recalled)
            ),
            "temporal_consistency_pass_rate": sum(temporal) / len(temporal),
            "contradiction_resolution": sum(contradictions) / len(contradictions),
            "abstention_rate": sum(unknown) / len(unknown),
            "answerable_query_success_rate": float(known_answered),
        },
        "denominators": {
            "temporal_relevant_events": 1,
            "temporal_checks": len(temporal),
            "conflict_checks": len(contradictions),
            "unanswerable_cases": len(unknown),
            "answerable_cases": 1,
        },
        "passed": all([*temporal, *contradictions, *unknown, known_answered]),
    }
