import json
import time
from dataclasses import replace
from pathlib import Path

from agents.roles import BusinessAgent, EngineeringAgent
from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.models import canonical, digest
from pipelines.etl.pipeline import IncrementalETL
from scripts.fixtures import order_event
from scripts.run_agents import prepare

CASES = [
    (
        "engineering-math",
        "Pricing",
        "Engineering cost changed by one cent",
        "engineering handoff",
        "failed",
    ),
    ("business-math", "Pricing", "Business revenue changed by one cent", "arithmetic", "failed"),
    (
        "missing-condition",
        "Evidence",
        "Required engineering condition removed",
        "engineering handoff",
        "failed",
    ),
    (
        "document-update",
        "Evidence",
        "Source revised after draft generation",
        "inputs changed",
        "invalidated",
    ),
    (
        "order-update",
        "Recalculation",
        "Published order cost changed after draft",
        "inputs changed",
        "invalidated",
    ),
    (
        "capacity-approval",
        "Recalculation",
        "Approval attempted with a capacity gap",
        "not eligible",
        "needs_capacity_review",
    ),
    (
        "revoked-access",
        "Access",
        "Manager access revoked before approval",
        "access denied",
        "needs_review",
    ),
    (
        "wrong-customer",
        "Access",
        "Customer A manager requests Customer B facts",
        "access denied",
        None,
    ),
    (
        "tampered-payload",
        "Approval",
        "Stored draft modified after validation",
        "integrity",
        "needs_review",
    ),
]


class IncorrectEngineering(EngineeringAgent):
    def run(self, *args):
        result = super().run(*args)
        result["costing"]["total_cost_cents"] -= 1
        return result


class IncorrectBusiness(BusinessAgent):
    def run(self, *args):
        result = super().run(*args)
        result["options"][2]["revenue_cents"] -= 1
        return result


class MissingCondition(EngineeringAgent):
    def run(self, *args):
        result = super().run(*args)
        result["constraints"].pop()
        return result


def evaluate_case(root, spec, model_path):
    case_id, category, title, expected_reason, expected_state = spec
    started = time.perf_counter()
    workflow, config = prepare(root, model_path)
    actor = config["actor"]
    args = [config[name] for name in ("actor", "customer_id", "project_id", "entity_id")]
    job_id = None
    if case_id == "wrong-customer":

        def action():
            workflow.submit(actor, "CUSTOMER-B", "PROJECT-B", "ORDER-B001-L1")
    else:
        job_id = workflow.submit(*args)
        if case_id in {"engineering-math", "business-math", "missing-condition"}:
            if case_id == "engineering-math":
                workflow.engineering = IncorrectEngineering()
            elif case_id == "business-math":
                workflow.business = IncorrectBusiness()
            else:
                workflow.engineering = MissingCondition()

            def action():
                workflow.run(actor, job_id)
        else:
            workflow.run(actor, job_id)
            if case_id == "document-update":
                prior = workflow.service.store.latest("ENG-A-001")
                workflow.service.store.put_documents(
                    [
                        replace(
                            prior, version=3, body=prior.body + "\nNew engineering review required."
                        )
                    ]
                )
            elif case_id == "order-update":
                source = Source(root / "inputs/etl/source.db")
                warehouse = Warehouse(root / "inputs/etl/warehouse.db")
                source.append(
                    [
                        order_event(
                            "ORDER-A001-L1",
                            version=4,
                            quantity=12000,
                            unit_cost="14.00",
                            unit_price="15.00",
                            design_version="D2",
                        )
                    ]
                )
                IncrementalETL(source, warehouse).drain()
            elif case_id == "capacity-approval":
                job_id = workflow.revise_quantity(actor, job_id, 18000)
                workflow.run(actor, job_id)
            elif case_id == "revoked-access":
                workflow.service.store.revoke(actor, "CUSTOMER-A", "PROJECT-A")
            elif case_id == "tampered-payload":
                payload = workflow.store.get(job_id)["payload"]
                payload["business"]["options"][2]["unit_price_cents"] = 1
                with workflow.store.connect() as connection:
                    connection.execute(
                        "UPDATE jobs SET payload=? WHERE job_id=?", (canonical(payload), job_id)
                    )

            def action():
                workflow.approve(actor, job_id, "counteroffer")

    rejected, reason, error_type = False, "Action unexpectedly accepted", None
    try:
        action()
    except (ValueError, PermissionError) as exc:
        rejected, reason, error_type = True, str(exc), type(exc).__name__
    except Exception as exc:
        reason, error_type = "Unexpected evaluator error", type(exc).__name__
    state, payload_exists, approval_exists = None, False, False
    if job_id:
        with workflow.store.connect() as connection:
            row = connection.execute(
                "SELECT status,payload,approval FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            state, payload_exists, approval_exists = (
                row["status"],
                row["payload"] is not None,
                row["approval"] is not None,
            )
    trace = workflow.store.trace(job_id) if job_id else []
    checks = {
        "expected_rejection": rejected and expected_reason in reason,
        "expected_state": state == expected_state,
        "no_approval_created": not approval_exists,
    }
    if expected_state == "failed":
        checks["invalid_payload_not_published"] = not payload_exists
    if case_id in {"engineering-math", "missing-condition"}:
        checks["bad_handoff_did_not_reach_business"] = not any(
            row["event"] == "business.complete" for row in trace
        )
    return {
        "case_id": case_id,
        "category": category,
        "title": title,
        "expected": "Reject unsafe action",
        "observed": "rejected"
        if rejected
        else "accepted"
        if error_type is None
        else "unexpected_failure",
        "passed": all(checks.values()),
        "checks": checks,
        "reason": reason,
        "error_type": error_type,
        "draft_state": state,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "trace": trace,
        "model_hash": digest(workflow.model),
        "config_hash": digest(config),
    }


def evaluate(root, model_path):
    root.mkdir(parents=True, exist_ok=True)
    cases = []
    for spec in CASES:
        try:
            cases.append(evaluate_case(root / spec[0], spec, model_path))
        except Exception as exc:
            cases.append(
                {
                    "case_id": spec[0],
                    "category": spec[1],
                    "title": spec[2],
                    "expected": "Reject unsafe action",
                    "observed": "setup_failed",
                    "passed": False,
                    "checks": {"setup_completed": False},
                    "reason": "Case setup failed",
                    "error_type": type(exc).__name__,
                    "trace": [],
                }
            )
    try:
        manager_feedback = evaluate_feedback(root / "manager-feedback", model_path)
    except Exception as exc:
        manager_feedback = {"passed": False, "error_type": type(exc).__name__}
    result = {
        "passed": all(row["passed"] for row in cases) and manager_feedback["passed"],
        "case_count": len(cases),
        "passed_count": sum(row["passed"] for row in cases),
        "cases": cases,
        "scope": "Controlled local fault experiments, not LLM accuracy or production monitoring",
        "llm_calls": 0,
        "external_api_calls": 0,
        "manager_feedback": manager_feedback,
    }
    (Path(root) / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def evaluate_feedback(root, model_path):
    workflow, config = prepare(root, model_path)
    actor = config["actor"]
    args = [config[name] for name in ("actor", "customer_id", "project_id", "entity_id")]
    job_id = workflow.submit(*args, key="feedback-example")
    original = workflow.run(actor, job_id)
    rejected = workflow.reject(
        actor,
        job_id,
        "commercial_context",
        "Review an 18,000-unit scenario; the additional customer volume is not signed.",
        key="feedback-example-reason",
    )
    feedback = rejected["feedback"][0]
    approval_blocked = False
    try:
        workflow.approve(actor, job_id, "counteroffer")
    except ValueError as exc:
        approval_blocked = "not eligible" in str(exc)
    revised_id = workflow.revise_quantity(actor, job_id, 18000, key="feedback-example-revision")
    revised = workflow.run(actor, revised_id)
    checks = {
        "rejection_stops_approval": rejected["status"] == "rejected" and approval_blocked,
        "feedback_bound_to_original_payload": feedback["payload_hash"]
        == workflow.store.get(job_id)["payload_hash"],
        "feedback_bound_to_source_versions": feedback["input_fingerprints"]
        == original["draft"]["input_fingerprints"],
        "feedback_kept_for_review_not_ground_truth": feedback["review_status"] == "pending_review",
        "new_revision_links_to_rejected_draft": revised["parent_id"] == job_id
        and revised["revision"] == 2,
        "new_quantity_recalculates_capacity": revised["status"] == "needs_capacity_review"
        and revised["draft"]["engineering"]["risk"]["capacity_shortfall_units"] == 4000,
        "feedback_survives_supersession": len(workflow.store.feedback(job_id)) == 1
        and workflow.read(actor, job_id)["status"] == "superseded",
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "feedback": feedback,
        "revised_status": revised["status"],
        "revised_quantity": revised["draft"]["quantity"],
        "capacity_shortfall_units": revised["draft"]["engineering"]["risk"][
            "capacity_shortfall_units"
        ],
        "limits": "Manager feedback awaits independent review; no automatic label creation or training",
    }
