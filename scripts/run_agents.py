import argparse
import json
import tempfile
from pathlib import Path

from agents.store import DraftStore
from agents.workflow import DraftWorkflow
from pipelines.etl.models import digest
from risk_model.dataset import FEATURES
from scripts.run_rag import prepare_demo
from scripts.run_risk_model import CONFIG
from scripts.run_risk_model import run as train_risk_model

ROOT = Path(__file__).resolve().parent.parent
SCENARIO = ROOT / "data/agent-fixtures/scenario.json"


def prepare(root, model_path=None):
    root.mkdir(parents=True, exist_ok=True)
    config = json.loads(SCENARIO.read_text())
    if model_path is None:
        training = root / "risk-training"
        training.mkdir()
        train_risk_model(training, json.loads(CONFIG.read_text()))
        model_path = training / "model.json"
    model_path = Path(model_path)
    model = json.loads(model_path.read_text())
    dataset_path = model_path.parent / "dataset.json"
    if dataset_path.is_file() and "training_feature_bounds" not in model:
        dataset = json.loads(dataset_path.read_text())["splits"]["train"]
        if digest(dataset) != model["train_sha256"]:
            raise ValueError("training feature bounds do not match model lineage")
        model["training_feature_bounds"] = {
            name: [
                min(row["features"][name] for row in dataset),
                max(row["features"][name] for row in dataset),
            ]
            for name in FEATURES
        }
    (root / "model.json").write_text(json.dumps(model, indent=2) + "\n")
    service, _ = prepare_demo(root / "inputs")
    workflow = DraftWorkflow(service, DraftStore(root / "drafts.db"), config, model)
    return workflow, config


def money(cents):
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"USD {sign}{value // 100:,}.{value % 100:02d}"


def render(job):
    draft = job["draft"]
    lines = [
        "Local Multi-Agent quote draft",
        f"State: {job['status']}; revision: {job['revision']}",
        f"Quantity: {draft['quantity']:,}; scenario: {draft['scenario_kind']}",
        f"Unit cost: {money(draft['engineering']['costing']['unit_cost_cents'])}",
        f"Synthetic risk score: {draft['engineering']['risk']['risk_score']:.2f} / 100",
        f"Capacity shortfall: {draft['engineering']['risk']['capacity_shortfall_units']:,} units",
        f"Outside training range: {', '.join(draft['engineering']['risk']['outside_training_range']) or 'none recorded'}",
    ]
    for option in draft["business"]["options"]:
        lines.append(
            f"{option['option_id']}: {money(option['unit_price_cents'])} per unit; "
            f"revenue {money(option['revenue_cents'])}; profit {money(option['gross_profit_cents'])}; "
            f"margin {option['margin_bps'] / 100:.2f}%; pricing allowed: {option['margin_allowed']}"
        )
    lines.extend(
        [
            draft["business"]["next_action"],
            "Manager what-if volume is not a signed commitment. No customer send is enabled.",
        ]
    )
    return "\n".join(lines) + "\n"


def review(root, model_path=None):
    workflow, config = prepare(root, model_path)
    args = [config[name] for name in ("actor", "customer_id", "project_id", "entity_id")]
    actor = config["actor"]
    first_id = workflow.submit(*args, key="customer-discount")
    queued = workflow.read(actor, first_id)
    initial = workflow.run(actor, first_id)
    question = workflow.explain(actor, first_id, "discount_limit")
    approved = workflow.approve(actor, first_id, "counteroffer")
    revised_id = workflow.revise_quantity(actor, first_id, 18000, key="manager-volume-18000")
    superseded = workflow.read(actor, first_id)
    revised = workflow.run(actor, revised_id)
    blocked = []
    for job_id in (first_id, revised_id):
        try:
            workflow.approve(actor, job_id, "counteroffer")
        except ValueError:
            blocked.append(job_id)
    current = workflow.service.read_facts(
        config["customer_id"], config["project_id"], config["entity_id"]
    )
    first, second = initial["draft"], revised["draft"]
    checks = {
        "draft_generation_is_queued": queued["status"] == "queued" and queued["draft"] is None,
        "current_etl_and_four_rag_conditions_used": first["facts"]["business_version"] == 3
        and len(first["engineering"]["constraints"]) == 4,
        "requested_five_percent_below_demo_margin_floor": first["business"]["options"][1][
            "unit_price_cents"
        ]
        == 1425
        and not first["business"]["options"][1]["margin_allowed"],
        "counteroffer_1445_cents_passes": first["business"]["options"][2]["unit_price_cents"]
        == 1445
        and approved["approval_valid"],
        "approval_bound_to_payload": approved["approval"]["payload_hash"]
        == workflow.store.get(first_id)["payload_hash"],
        "revision_invalidates_old_approval": superseded["status"] == "superseded"
        and not superseded["approval_valid"],
        "hypothetical_volume_is_not_customer_commitment": second["quantity"] == 18000
        and not second["customer_volume_committed"],
        "unit_cost_does_not_fall_without_approved_evidence": first["engineering"]["costing"][
            "unit_cost_cents"
        ]
        == second["engineering"]["costing"]["unit_cost_cents"]
        == 1300,
        "revised_cost_and_counteroffer_recomputed": second["engineering"]["costing"][
            "total_cost_cents"
        ]
        == 23400000
        and second["business"]["options"][2]["revenue_cents"] == 26010000,
        "shared_capacity_shortfall_blocks_approval": revised["status"] == "needs_capacity_review"
        and second["engineering"]["risk"]["capacity_shortfall_units"] == 4000,
        "stale_and_infeasible_approvals_rejected": len(blocked) == 2,
        "what_if_does_not_modify_etl": current == first["facts"],
        "same_model_reused_without_retraining": first["engineering"]["risk"]["model_hash"]
        == second["engineering"]["risk"]["model_hash"],
        "no_paid_calls_or_customer_send": first["external_api_calls"]
        == second["external_api_calls"]
        == 0
        and not second["customer_send_enabled"],
    }
    result = {
        "passed": all(checks.values()),
        "checks": checks,
        "initial": initial,
        "manager_follow_up": question,
        "initial_internal_approval": approved["approval"],
        "superseded_status": superseded["status"],
        "revised": revised,
        "traces": {
            "initial": workflow.trace(actor, first_id),
            "revised": workflow.trace(actor, revised_id),
        },
        "limits": "Deterministic two-role workflow with reviewed extraction rules; no LLM, LangGraph, AgentCore, real authentication or customer dispatch. Model scores are synthetic and unpromoted.",
    }
    for name, value in (("initial", initial), ("revised", revised)):
        (root / f"{name}.json").write_text(json.dumps(value, indent=2) + "\n")
        (root / f"{name}.txt").write_text(render(value))
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Run a local two-role quote draft and manager quantity revision"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="agents-review-", dir=args.output))
    result = review(root, args.model)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "checks": result["checks"],
                "report": str(root / "report.json"),
                "initial": str(root / "initial.txt"),
                "revised": str(root / "revised.txt"),
            },
            indent=2,
        )
    )
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
