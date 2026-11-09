import argparse
import json
import os
import time
from pathlib import Path

from agent.runtime import RuntimeConfig
from agent.service import Service
from deployment.self_check import container_check, local_check, verify_aws
from evaluation.eval_pipeline import evaluate
from evaluation.gates import implementation_hash, release_gates
from evaluation.judge import approve_existing_rules, review_labels
from mock_data.generator import generate


def verify_traces(rows):
    from langsmith import Client

    client = Client()
    identifiers = [
        (row.get("case_trace_id") or row.get("runtime", {}).get("trace_id"), row["expected_route"])
        for row in rows
    ]
    if not identifiers or any(not identifier for identifier, route in identifiers):
        return False
    for identifier, route in identifiers:
        verified = False
        for attempt in range(3):
            try:
                run = client.read_run(identifier, load_child_runs=True)
                verified = (
                    run.end_time is not None
                    and not run.error
                    and (route == "validation_error" or bool(run.child_runs))
                )
                if verified:
                    break
            except Exception:
                pass
            time.sleep(0.2 * (attempt + 1))
        if not verified:
            return False
    return True


def qualify(
    root,
    labels=False,
    http=False,
    container=False,
    live=False,
    aws_runtime=None,
    reference_existing=False,
    reuse_evaluation=False,
):
    root = Path(root)
    first = not (root / "source/manifest.json").exists()
    if first:
        generate(root / "source")
    service = Service(root)
    if first:
        service.ingest_all()
    if reference_existing:
        approve_existing_rules(root)
    if labels:
        review_labels(root, service.config.judge_model)
    if http:
        local_check(root)
    if container:
        container_check(root)
    if aws_runtime:
        verify_aws(root, aws_runtime)
    if reuse_evaluation:
        report = json.loads((root / "evaluation.json").read_text())
        if report.get("implementation_hash") != implementation_hash():
            raise ValueError("Saved evaluation is stale; run the current candidate again")
    else:
        report = evaluate(
            service,
            progress=lambda row: print(
                json.dumps(
                    {
                        "case": row["case_id"],
                        "passed": row["passed"],
                        "mode": row.get("runtime", {}).get("mode", row["expected_route"]),
                    }
                ),
                flush=True,
            ),
        )
    report["qualification_scope"] = (
        "local_release"
        if os.getenv("QUALIFICATION_SCOPE") == "local_release"
        else "cloud_production"
    )
    if live:
        real_rows = [row for row in report["rows"] if row["expected_route"] != "validation_error"]
        evidence = {
            "implementation_hash": report["implementation_hash"],
            "dataset_hash": report["dataset_hash"],
            "cases": report["cases"],
            "passed": report["passed"],
            "all_real_llm": all(row["runtime"].get("mode") == "llm" for row in real_rows),
            "all_semantic": all(
                row["runtime"].get("semantic_backend") == "sentence-transformers"
                for row in real_rows
            ),
            "no_fallbacks": all(row["runtime"].get("fallback_reason") is None for row in real_rows),
            "tracing_verified": verify_traces(report["rows"]) if service.tracing_enabled else False,
            "tracing_requested": service.tracing_enabled,
            "trace_verification_note": "Remote LangSmith run and child-run existence checked",
            "agent_model": RuntimeConfig.from_env().model,
            "project_name": os.getenv("LANGSMITH_PROJECT"),
            "case_run_ids": [row.get("case_trace_id") for row in report["rows"]],
            "usage": report.get("usage", {}),
        }
        (root / "live-evaluation.json").write_text(json.dumps(evidence, indent=2) + "\n")
    report["release"] = release_gates(report, root)
    (root / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runtime/studio")
    parser.add_argument("--review-labels", action="store_true")
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--container", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--aws-runtime-arn")
    parser.add_argument("--reference-existing-rules", action="store_true")
    parser.add_argument("--reuse-evaluation", action="store_true")
    args = parser.parse_args()
    report = qualify(
        args.root,
        args.review_labels,
        args.http,
        args.container,
        args.live,
        args.aws_runtime_arn,
        args.reference_existing_rules,
        args.reuse_evaluation,
    )
    print(
        json.dumps(
            {
                "cases": report["cases"],
                "passed": report["passed"],
                "memory": report["memory"],
                "release": report["release"],
            },
            indent=2,
        )
    )
