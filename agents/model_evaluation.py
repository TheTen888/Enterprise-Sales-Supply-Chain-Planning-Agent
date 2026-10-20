import copy
import json
import math
import time
from pathlib import Path

from agents.assessment import CONDITIONS, TOOLS, RulesAssessor
from agents.llm_roles import ModelBusinessAgent, ModelEngineeringAgent
from integrations.bedrock import BedrockClient
from integrations.model_mock import ScriptedBedrock
from pipelines.etl.models import digest
from scripts.run_agents import prepare

DATA = Path(__file__).resolve().parent.parent / "data/llm-eval"


def load_cases(split):
    if split not in {"development", "holdout"}:
        raise ValueError("unsupported evaluation split")
    data = json.loads((DATA / (split + ".json")).read_text())
    identifiers = [row["case_id"] for row in data["cases"]]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate evaluation cases")
    for case in data["cases"]:
        if "expected" in case["input"] or case["input"]["role"] not in TOOLS:
            raise ValueError("invalid input boundary")
        for key, citations in case["expected"]["support"].items():
            if (
                key not in CONDITIONS
                or not citations
                or not set(citations) <= {row["citation_id"] for row in case["input"]["documents"]}
            ):
                raise ValueError("invalid annotation citation")
    return data


def score_case(assessor, case):
    started = time.monotonic()
    expected = case["expected"]
    try:
        result = assessor.assess(copy.deepcopy(case["input"]))
        decision = result["decision"]
        pairs = decision["condition_evidence"]
        supported = sum(
            row["citation_id"] in expected["support"].get(row["condition_id"], []) for row in pairs
        )
        recalled = {
            row["condition_id"]
            for row in pairs
            if row["citation_id"] in expected["support"].get(row["condition_id"], [])
        }
        scope_denied = result["preflight"] == "scope_denied"
        tool_correct = (
            not result["tools"]
            if scope_denied
            else {row["tool"] for row in result["tools"] if row["executed"]}
            == set(TOOLS[case["input"]["role"]])
            and all(row["allowed"] for row in result["tools"])
        )
        status_correct = decision["status"] == expected["status"]
        action_correct = decision["next_action"] == expected["next_action"]
        condition_recall = len(recalled) / len(expected["support"]) if expected["support"] else None
        citation_precision = supported / len(pairs) if pairs else None
        passed = status_correct and action_correct and tool_correct and supported == len(pairs)
        if expected["status"] == "ready":
            passed = passed and condition_recall == 1
        return {
            "case_id": case["case_id"],
            "category": case["category"],
            "language": case["language"],
            "passed": passed,
            "status_correct": status_correct,
            "action_correct": action_correct,
            "tool_selection_correct": tool_correct,
            "condition_recall": condition_recall,
            "citation_precision": citation_precision,
            "decision": decision,
            "expected_status": expected["status"],
            "preflight": result["preflight"],
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
        }
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "category": case["category"],
            "language": case["language"],
            "passed": False,
            "error_type": type(exc).__name__,
        }


def release_gate(contracts_passed, annotation_status, model_report=None):
    report = model_report or {}
    thresholds = json.loads((DATA / "gate.json").read_text())
    checks = {
        "offline_contracts_passed": contracts_passed is True,
        "real_model_evaluation_available": report.get("real_inference") is True
        and type(report.get("model_calls")) is int
        and report.get("model_calls", 0) > 0,
        "independent_human_labels_reviewed": annotation_status == "approved",
    }
    for name, threshold in (
        ("task_success", "minimum_task_success"),
        ("ready_condition_recall", "minimum_ready_condition_recall"),
        ("citation_precision", "minimum_citation_precision"),
        ("refusal_accuracy", "minimum_refusal_accuracy"),
    ):
        value = report.get(name)
        checks[name] = (
            type(value) in {float, int}
            and math.isfinite(value)
            and 0 <= value <= 1
            and value >= thresholds[threshold]
        )
    for name, threshold in (
        ("unauthorized_tool_executions", "maximum_unauthorized_tool_executions"),
        ("case_p95_ms", "maximum_case_p95_ms"),
    ):
        value = report.get(name)
        checks[name] = type(value) in {float, int} and 0 <= value <= thresholds[threshold]
    return {
        "deployment_allowed": all(checks.values()),
        "checks": checks,
        "failed_requirements": [key for key, value in checks.items() if not value],
        "scope": "Future local shadow qualification only; never customer dispatch or production approval",
    }


def evaluate_contracts(root, model_path=None):
    root.mkdir(parents=True, exist_ok=True)
    workflow, config = prepare(root / "workflow", model_path)
    sdk = ScriptedBedrock()
    client = BedrockClient("offline-contract-model", sdk_client=sdk)
    workflow.engineering, workflow.business = (
        ModelEngineeringAgent(client),
        ModelBusinessAgent(client),
    )
    actor = config["actor"]
    job_id = workflow.submit(
        *[config[key] for key in ("actor", "customer_id", "project_id", "entity_id")]
    )
    original = workflow.run(actor, job_id)
    revised_id = workflow.revise_quantity(actor, job_id, 18000)
    revised = workflow.run(actor, revised_id)
    denied = False
    try:
        workflow.approve(actor, revised_id, "counteroffer")
    except ValueError:
        denied = True
    checks = {
        "sdk_converse_request_path_exercised": len(sdk.requests) == 8,
        "structured_response_validation_exercised": original["draft"]["engineering"][
            "model_analysis"
        ]["decision"]["status"]
        == "ready",
        "all_four_source_conditions_preserved": len(original["draft"]["engineering"]["constraints"])
        == 4,
        "numeric_quote_checked_independently": original["draft"]["business"]["options"][2][
            "unit_price_cents"
        ]
        == 1445,
        "capacity_recalculation_blocks_approval": denied
        and revised["status"] == "needs_capacity_review",
        "simulated_calls_not_counted_as_real_inference": original["draft"]["llm_calls"]
        == revised["draft"]["llm_calls"]
        == 0
        and original["draft"]["mock_model_calls"] == 4,
        "no_remote_calls": original["draft"]["external_api_calls"]
        == revised["draft"]["external_api_calls"]
        == 0,
    }
    splits = {}
    for split in ("development", "holdout"):
        data = load_cases(split)
        rows = [score_case(RulesAssessor(), case) for case in data["cases"]]
        splits[split] = {
            "case_count": len(rows),
            "rules_passed_count": sum(row["passed"] for row in rows),
            "rules_task_success": sum(row["passed"] for row in rows) / len(rows),
            "cases": rows,
            "dataset_sha256": digest(data),
            "model_task_success": None,
            "model_status": "not_measured",
        }
    result = {
        "passed": all(checks.values()),
        "mode": "offline_model_contracts",
        "checks": checks,
        "real_inference_calls": 0,
        "network_calls": 0,
        "mock_sdk_calls": len(sdk.requests),
        "annotation_status": "pending_independent_human_review",
        "splits": splits,
        "release_gate": release_gate(all(checks.values()), "pending"),
        "scope": "Authored fake SDK responses test wiring and guards. Rules scores are measured; model quality and performance gains are not measured.",
    }
    (root / "report.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result
