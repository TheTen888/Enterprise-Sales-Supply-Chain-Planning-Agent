import json
import os
from pathlib import Path

from pydantic import Field, ValidationError

from agent.runtime import CountingModel, create_model
from config.contracts import Contract, QuoteRequest, fingerprint
from evaluation.synthetic_generator import generate_cases


def dataset():
    return (
        json.loads((Path(__file__).parent / "golden_dataset.json").read_text()) + generate_cases()
    )


def dataset_hash():
    return fingerprint(dataset())


def approve_existing_rules(root):
    report = {
        "status": "passed" if all(check_labels(case) for case in dataset()) else "failed",
        "dataset_hash": dataset_hash(),
        "case_count": len(dataset()),
        "reference_type": "project_authored_expected_rules",
        "approval_basis": "User selected existing authored rules for shift-left validation",
        "independent_expert_review": False,
    }
    Path(root).mkdir(parents=True, exist_ok=True)
    (Path(root) / "reference-review.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


class JudgeVerdict(Contract):
    passed: bool = Field(
        description="Whether the expected behavior and oracle are correct, not whether the customer's desired request is feasible"
    )
    business_consistent: bool = Field(
        description="Whether expected outputs respect the supplied authoritative source facts"
    )
    issues: list[str] = Field(
        description="Actual defects in the expected behavior or oracle only. Use an empty list if there are no defects; feasibility conflicts in the customer request are deliberate test inputs."
    )


def review_packet(case):
    expected = {"route": case["expected_route"]}
    if case["expected_route"] == "quote":
        request = QuoteRequest.model_validate(case["request"])
        expected.update(
            {
                "disposition": "blocked" if request.quantity > 40000 else "needs_review",
                "delivery_rule": "Propose at least max(active ECN minimum days, chosen factory process days); customer requested_days is a desired deadline, never an authoritative constraint",
                "capacity_rule": "Any factory with available units >= requested quantity; preferred factory may be replaced. If none fits, block approval.",
                "pricing_rule": "1300 cents cost; integer-cent quote at or above ceiling(1300/0.9)=1445 cents",
                "mandatory_conditions": [
                    "Required inspection remains included",
                    "Future volume is not a signed commitment",
                ],
            }
        )
    elif case["expected_route"] == "validation_error":
        expected["reason"] = (
            "Quarter must match YYYY-Q1 through YYYY-Q4. Q4-2026 must be rejected before model/tool execution."
        )
    else:
        expected.update(
            {
                "behavior": "Explain FOB as a shipping trade term using no tools",
                "oracle_policy": "Empty numeric oracle is intentional for a general-knowledge routing test",
            }
        )
    return {
        "case": {key: value for key, value in case.items() if key != "label_status"},
        "expected_behavior": expected,
        "provenance_note": "Prior unreviewed status is why this independent review is being run; it is not a defect in label correctness.",
    }


def check_labels(case):
    if case["expected_route"] == "validation_error":
        try:
            QuoteRequest.model_validate(case["request"])
        except ValidationError:
            return True
        return False
    if case["expected_route"] == "direct":
        return not case["oracle"]
    oracle = case["oracle"]
    return (
        oracle.get("unit_cost_cents") == 800 + 300 + 200
        and oracle.get("minimum_days") == 28
        and oracle.get("factory_available") == {"PLANT-A": 100000 - 98000, "PLANT-B": 80000 - 40000}
    )


def review_labels(root, judge_model=None, client=None):
    from config.environment import load_environment

    load_environment()
    rows = []
    mode = (
        "llm"
        if client is None and os.getenv("OPENAI_API_KEY") and judge_model
        else "injected_test_judge"
        if client
        else "unavailable"
    )
    independent = bool(judge_model and judge_model != os.getenv("OPENAI_MODEL"))
    calls = 0
    if mode == "llm":
        client = CountingModel(create_model(judge_model))
    if client:
        reviewer = client.with_structured_output(JudgeVerdict)
    for case in dataset():
        rule_valid = check_labels(case)
        verdict = None
        error = None
        if client:
            try:
                calls += 1
                verdict = reviewer.invoke(
                    [
                        {
                            "role": "system",
                            "content": "Independently audit EXPECTED OUTPUTS, not the feasibility of the customer's request. Infeasible requests are deliberate negative tests: they are valid cases when expected behavior proposes a corrected plan or blocks approval. Authoritative sources: BOM 800+300+200=1300 cents; active ECN v2 requires 28 days, obsolete v1 allowed 14 days. PLANT-A total 100000 minus committed 98000 equals available 2000 and process days 14. PLANT-B total 80000 minus committed 40000 equals available 40000 and process days 21. 'quote' is a workflow route, not a promise to accept the requested date or factory. Reject wrong oracle numbers or an unsafe expected behavior. Do not list normal observations or the absence of prior review as issues. If the expected behavior handles a deliberately infeasible request correctly, use passed=true, business_consistent=true, issues=[]. Evaluate each case on its merits; do not assume it is correct.",
                        },
                        {"role": "user", "content": json.dumps(review_packet(case))},
                    ]
                )
                if not isinstance(verdict, JudgeVerdict):
                    verdict = JudgeVerdict.model_validate(verdict)
            except Exception as exc:
                error = type(exc).__name__
        passed = bool(
            rule_valid
            and verdict
            and verdict.passed
            and verdict.business_consistent
            and not verdict.issues
        )
        rows.append(
            {
                "case_id": case["id"],
                "rule_consistency": rule_valid,
                "review_status": "passed" if passed else "failed" if client else "pending",
                "issues": verdict.issues if verdict else [],
                "error": error,
            }
        )
    report = {
        "dataset_hash": dataset_hash(),
        "mode": mode,
        "judge_model": judge_model,
        "model_separate_from_agent": independent,
        "logical_model_calls": calls,
        "review_status": "passed"
        if mode == "llm" and independent and all(row["review_status"] == "passed" for row in rows)
        else "pending"
        if mode == "unavailable"
        else "failed",
        "review_type": "independent_model_consistency_audit_not_human_review",
        "rows": rows,
        "usage": {
            name: client.counter[name] for name in ["input_tokens", "output_tokens", "total_tokens"]
        }
        if isinstance(client, CountingModel)
        else {},
    }
    report["model_review_status"] = report["review_status"]
    reference_path = Path(root) / "reference-review.json"
    reference = (
        json.loads(reference_path.read_text()) if reference_path.exists() else {"status": "pending"}
    )
    report["reference_review"] = reference
    if report["review_status"] == "passed" and not (
        reference.get("status") == "passed" and reference.get("dataset_hash") == dataset_hash()
    ):
        report["review_status"] = "pending_reference_review"
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "label-review.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
