import json
import time
from contextlib import nullcontext
from pathlib import Path

from pydantic import ValidationError

from config.contracts import Scope
from evaluation.evaluator import assess, unsafe_negative_control
from evaluation.gates import implementation_hash, release_gates
from evaluation.judge import dataset_hash
from evaluation.memory_eval import evaluate_memory
from evaluation.synthetic_generator import generate_cases


def evaluate(service, include_matrix=True, progress=None):
    from langsmith import trace, tracing_context

    cases = json.loads((Path(__file__).parent / "golden_dataset.json").read_text())
    if include_matrix:
        cases += generate_cases()
    scope = Scope(customer_id="CUSTOMER-A", project_id="PROJECT-A")
    rows = []
    for case in cases:
        started = time.perf_counter()
        with tracing_context(enabled=service.tracing_enabled):
            context = (
                trace(
                    "qualification-case",
                    inputs={"case_id": case["id"], "request": case["request"]},
                    metadata={"case_id": case["id"]},
                )
                if service.tracing_enabled
                else nullcontext(None)
            )
            with context as case_trace:
                try:
                    output = service.run("demo-manager", scope, case["request"])
                except ValidationError:
                    output = {"route": "validation_error", "events": []}
                if case_trace:
                    case_trace.end(
                        outputs={"route": output.get("route"), "runtime": output.get("runtime", {})}
                    )
        checks = assess(case, output)
        control_checks = assess(case, unsafe_negative_control(case, output))
        rows.append(
            {
                "case_id": case["id"],
                "expected_route": case["expected_route"],
                "passed": all(checks.values()),
                "checks": checks,
                "negative_control_passed": all(control_checks.values()),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                "label_status": case["label_status"],
                "events": output.get("events", []),
                "runtime": output.get("runtime", {}),
                "llm_trajectory": output.get("llm_trajectory", []),
                "case_trace_id": str(case_trace.id) if case_trace else None,
                "result": output.get("artifact", output.get("answer")),
                "failure_categories": [name for name, passed in checks.items() if not passed],
            }
        )
        if progress:
            progress(rows[-1])
    quote_rows = [row for row in rows if row["expected_route"] == "quote"]
    offered = [row for row in quote_rows if row["result"]["status"] != "blocked"]

    def rate(values):
        return sum(values) / len(values) if values else None

    report = {
        "scope": "Synthetic business acceptance evaluation; runtime mode is recorded per case; not production business impact",
        "cases": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "metrics": {
            "case_pass_rate": rate([row["passed"] for row in rows]),
            "capacity_overcommitment_rate": rate(
                [not row["checks"]["capacity"] for row in offered]
            ),
            "delivery_constraint_pass_rate": rate(
                [row["checks"]["timeline"] for row in quote_rows]
            ),
            "calculation_pass_rate": rate([row["checks"]["calculation"] for row in quote_rows]),
            "critical_condition_pass_rate": rate(
                [row["checks"]["critical_conditions"] for row in quote_rows]
            ),
            "negative_control_pass_rate": rate([row["negative_control_passed"] for row in rows]),
        },
        "denominators": {"quote_cases": len(quote_rows), "offered_proposals": len(offered)},
        "external_api_calls": sum(
            row.get("runtime", {}).get("logical_model_calls", 0)
            for row in rows
            if row.get("runtime", {}).get("provider_backed")
        ),
        "logical_model_calls": sum(
            row.get("runtime", {}).get("logical_model_calls", 0) for row in rows
        ),
        "usage": {
            name: sum(row.get("runtime", {}).get("usage", {}).get(name, 0) for row in rows)
            for name in ["input_tokens", "output_tokens", "total_tokens"]
        },
        "call_count_scope": "Logical model invocations; excludes SDK retries and telemetry HTTP requests",
        "rows": rows,
    }
    report["memory"] = evaluate_memory(service.root, service.semantic_backend)
    report["dataset_hash"] = dataset_hash()
    report["implementation_hash"] = implementation_hash()
    report["runtime_mode"] = (
        "llm"
        if all(
            row.get("runtime", {}).get("mode") == "llm"
            for row in rows
            if row["expected_route"] != "validation_error"
        )
        else "mock_or_fallback"
    )
    report["release"] = release_gates(report, service.root)
    return report
