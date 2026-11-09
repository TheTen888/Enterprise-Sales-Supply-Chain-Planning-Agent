import pytest

from config.contracts import Scope
from evaluation.memory_eval import evaluate_memory
from memory.architecture import ContextEditor


def test_new_events_distill_only_confirmed_facts(service, scope):
    memory = service.memory
    result = memory.save_event(
        scope,
        "thread",
        {
            "facts": [
                {
                    "name": "shipping",
                    "value": "FOB Alpha",
                    "confirmed": True,
                    "authority": "customer",
                },
                {"name": "volume", "value": "50000", "confirmed": False, "authority": "customer"},
            ]
        },
        "2026-01-01T00:00:00Z",
        "event1",
    )
    assert memory.recall(scope)["shipping"]["value"] == "FOB Alpha"
    assert "volume" not in memory.recall(scope)
    assert result["consolidation"]["outcomes"][1]["status"] == "pending_confirmation"


def test_semantic_dedup_and_temporal_replacement(service, scope):
    memory = service.memory
    assert (
        memory.store_fact(scope, "shipping", "FOB Alpha", "mail1", "2026-01-01T00:00:00Z")[
            "version"
        ]
        == 1
    )
    duplicate = memory.store_fact(
        scope, "shipping", "FOB Alpha", "mail1-repeat", "2026-01-02T00:00:00Z"
    )
    assert duplicate["status"] == "duplicate"
    assert duplicate["cosine_similarity"] > 0.99
    assert (
        memory.store_fact(scope, "shipping", "FOB Beta", "mail2", "2026-02-01T00:00:00Z")["version"]
        == 2
    )
    assert memory.recall(scope, "2026-01-15T00:00:00Z")["shipping"]["value"] == "FOB Alpha"
    assert memory.recall(scope)["shipping"]["value"] == "FOB Beta"
    late = memory.store_fact(scope, "shipping", "FOB Old", "late-mail", "2026-01-10T00:00:00Z")
    assert late["status"] == "out_of_order_review"
    assert memory.recall(scope)["shipping"]["value"] == "FOB Beta"


def test_cosine_similarity_cannot_merge_different_numbers(service, scope):
    memory = service.memory
    memory.store_fact(scope, "volume", "confirmed volume 12000 units", "v1", "2026-01-01T00:00:00Z")
    result = memory.store_fact(
        scope, "volume", "confirmed volume 12001 units", "v2", "2026-02-01T00:00:00Z"
    )
    assert result["status"] == "updated"
    assert memory.recall(scope)["volume"]["value"].endswith("12001 units")


def test_episodic_time_filter_and_customer_isolation(service, scope):
    memory = service.memory
    memory.save_event(scope, "thread", {"event": "January quote"}, "2026-01-01T00:00:00Z", "jan")
    memory.save_event(scope, "thread", {"event": "February quote"}, "2026-02-01T00:00:00Z", "feb")
    result = memory.recall_events(scope, "quote", end="2026-01-31T00:00:00Z")
    assert [row["event_id"] for row in result] == ["jan"]
    assert memory.recall_events(Scope(customer_id="OTHER", project_id="OTHER"), "quote") == []


def test_ecn_memory_requires_engineering_authority(service, scope):
    memory = service.memory
    result = memory.save_event(
        scope,
        "thread",
        {
            "facts": [
                {
                    "name": "ecn:ECN-001",
                    "value": "1 day",
                    "confirmed": True,
                    "authority": "customer",
                }
            ]
        },
        event_id="untrusted-ecn",
    )
    assert result["consolidation"]["outcomes"][0]["status"] == "pending_engineering_confirmation"
    assert "ecn:ECN-001" not in memory.recall(scope)


def test_context_editor_prunes_tools_and_application_reasoning():
    messages = [
        {"role": "thinking", "content": "private"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "private"},
                {"type": "text", "text": "visible"},
            ],
            "reasoning_content": "private",
            "tool_calls": [{"id": "call1", "name": "test", "args": {}}],
        },
        {"role": "tool", "tool_call_id": "call1", "content": "x" * 10000},
    ]
    edited = ContextEditor().edit(messages)
    assert "private" not in str(edited)
    assert len(str(edited)) < 2500
    assert "must_refetch_before_decision" in edited[-1]["content"]


def test_skills_are_loaded_dynamically(service, tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    for name in ["pricing.md", "capacity.md"]:
        (root / name).write_text("Rule one")
    service.memory.skills_root = root
    assert service.memory.load_skills()["pricing.md"] == "Rule one"
    (root / "pricing.md").write_text("Rule two")
    assert service.memory.load_skills()["pricing.md"] == "Rule two"


def test_memory_eval_reports_all_denominators(tmp_path):
    report = evaluate_memory(tmp_path)
    assert report["passed"]
    assert all(value == 1 for value in report["metrics"].values())
    assert report["denominators"]["unanswerable_cases"] == 3


def test_conflicting_episode_id_rejected(service, scope):
    memory = service.memory
    memory.save_event(scope, "thread", {"event": "first"}, "2026-01-01T00:00:00Z", "same")
    with pytest.raises(ValueError, match="Conflicting"):
        memory.save_event(scope, "thread", {"event": "changed"}, "2026-01-01T00:00:00Z", "same")


def test_legacy_confirmed_preferences_survive_upgrade(tmp_path, scope):
    from memory.architecture import MemorySystem
    from memory.dual_memory import CustomerMemory

    path = tmp_path / "legacy.sqlite"
    old = CustomerMemory(path)
    old.store_preference(scope, "shipping", "FOB Alpha", "mail1", confirmed=True)
    upgraded = MemorySystem(path)
    assert upgraded.recall(scope)["shipping"]["value"] == "FOB Alpha"
    assert len(upgraded.retrieve_facts(scope, "shipping")) == 1


def test_high_cosine_unrelated_memory_is_rejected_by_reranker(service, scope):
    class Backend:
        minimum_memory_score = -5.0

        def encode(self, texts):
            return [[1.0, 0.0] for text in texts]

        def rerank(self, query, rows):
            return [
                {**row, "rerank_score": -12.0 if "certification" in query else 2.0} for row in rows
            ]

    memory = service.memory
    memory.semantic_backend = Backend()
    memory.store_fact(scope, "shipping", "FOB Alpha", "mail")
    assert memory.retrieve_facts(scope, "shipping")
    assert memory.retrieve_facts(scope, "unmentioned warranty certification") == []
