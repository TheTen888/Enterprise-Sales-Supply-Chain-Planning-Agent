from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent.service import Service
from agent.tools import CapacityInput
from config.contracts import Scope
from deployment.app import invoke_local
from evaluation.eval_pipeline import evaluate
from evaluation.evaluator import assess


def test_quote_switches_factory_and_respects_ecn(service, scope):
    result = service.run("demo-manager", scope, {"prompt": "Prepare a discounted quote"})
    artifact = result["artifact"]
    assert artifact["status"] == "needs_review"
    assert artifact["result"]["factory_id"] == "PLANT-B"
    assert artifact["result"]["lead_days"] == 28
    assert artifact["result"]["unit_price_cents"] == 1445
    assert artifact["result"]["total_cost_cents"] == 15600000
    assert any(row["sender"] == "CapacityAgent" for row in result["messages"])
    assert result["attempt"] == 2


def test_quantity_change_recalculates_and_blocks_approval(service, scope):
    request = {"prompt": "Prepare quote"}
    original = service.run("demo-manager", scope, request)["artifact"]
    revised = {**request, "quantity": 50000}
    result = service.run("demo-manager", scope, revised)["artifact"]
    assert result["result"]["total_cost_cents"] == 65000000
    assert result["status"] == "blocked"
    assert result["revision"] != original["revision"]
    with pytest.raises(ValueError, match="Stale"):
        service.approve("demo-manager", scope, original, revised)


def test_tampered_artifact_cannot_be_approved(service, scope):
    request = {"prompt": "Prepare quote"}
    artifact = service.run("demo-manager", scope, request)["artifact"]
    artifact["result"]["unit_price_cents"] = 1
    with pytest.raises(ValueError, match="altered"):
        service.approve("demo-manager", scope, artifact, request)


def test_approval_rechecks_live_capacity(service, scope):
    import json

    request = {"prompt": "Prepare quote"}
    artifact = service.run("demo-manager", scope, request)["artifact"]
    path = service.source / "factory_capacity.json"
    rows = json.loads(path.read_text())
    rows[1]["committed_units"] = 80000
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        service.approve("demo-manager", scope, artifact, request)


def test_approval_rechecks_revoked_access(service, scope):
    request = {"prompt": "Prepare quote"}
    artifact = service.run("demo-manager", scope, request)["artifact"]
    service.grants.clear()
    with pytest.raises(PermissionError):
        service.approve("demo-manager", scope, artifact, request)


def test_approval_is_internal_and_does_not_book_capacity(service, scope):
    request = {"prompt": "Prepare quote"}
    artifact = service.run("demo-manager", scope, request)["artifact"]
    approved = service.approve("demo-manager", scope, artifact, request)
    assert approved["status"] == "approved"
    assert "internal proposal only" in approved["approval_scope"]


def test_wrong_customer_denied(service):
    with pytest.raises(PermissionError):
        service.run(
            "demo-manager",
            Scope(customer_id="CUSTOMER-B", project_id="PROJECT-B"),
            {"prompt": "Prepare quote"},
        )


def test_no_current_ecn_requires_engineering_review(service, scope):
    service.ingestion.delete(scope, "ECN-001")
    with pytest.raises(ValueError, match="review required"):
        service.run("demo-manager", scope, {"prompt": "Prepare quote"})


@pytest.mark.parametrize("quarter", ["Q4-2026", "2026-Q5", "2026", "2026-Q4;DROP"])
def test_malformed_tool_input_not_silently_repaired(quarter):
    with pytest.raises(ValidationError):
        CapacityInput(factory_id="PLANT-A", target_quarter=quarter, required_units=100)


def test_direct_answer_avoids_tool_calls(service, scope):
    result = service.run("demo-manager", scope, {"prompt": "What is FOB?"})
    assert result["route"] == "direct"
    assert len(result["events"]) == 1


def test_lookup_uses_current_ecn(service, scope):
    result = service.run("demo-manager", scope, {"prompt": "Lookup ECN-001"})
    assert result["route"] == "lookup"
    assert "28 days" in result["answer"]


def test_graph_checkpoint_survives_service_restart(service, scope):
    service.run("demo-manager", scope, {"prompt": "Prepare quote"}, thread_id="stable")
    from config.contracts import fingerprint

    thread = fingerprint(["demo-manager", scope.key, "stable"])
    restarted = Service(service.root)
    state = restarted.graph.get_state({"configurable": {"thread_id": thread}})
    assert state.values["artifact"]["result"]["quantity"] == 12000


def test_eval_rejects_corrupted_solution(service, scope):
    result = service.run("demo-manager", scope, {"prompt": "Prepare quote"})
    case = {
        "request": {"prompt": "Prepare quote"},
        "expected_route": "quote",
        "oracle": {
            "unit_cost_cents": 1300,
            "minimum_days": 28,
            "factory_available": {"PLANT-A": 2000, "PLANT-B": 40000},
        },
    }
    assert all(assess(case, result).values())
    corrupt = deepcopy(result)
    corrupt["artifact"]["result"]["lead_days"] = 14
    corrupt["artifact"]["result"]["total_cost_cents"] -= 1
    corrupt["artifact"]["result"]["required_conditions"] = []
    checks = assess(case, corrupt)
    assert not checks["timeline"]
    assert not checks["calculation"]
    assert not checks["critical_conditions"]


def test_full_eval_and_release_boundary(service):
    report = evaluate(service)
    assert report["cases"] == 23
    assert report["passed"] == 23
    assert report["metrics"]["capacity_overcommitment_rate"] == 0
    assert report["metrics"]["negative_control_pass_rate"] < report["metrics"]["case_pass_rate"]
    assert report["release"]["production_approved"] is False


def test_model_adapter_network_disabled_by_default():
    from deployment.adapters import OpenAIPlanner

    with pytest.raises(RuntimeError, match="disabled"):
        OpenAIPlanner("unused").invoke([], dict)


def test_entrypoint_ignores_no_unauthorized_identity(service):
    with pytest.raises(ValidationError):
        invoke_local({"prompt": "Prepare quote", "customer_id": "CUSTOMER-B"}, service)
