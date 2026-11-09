import json
from pathlib import Path


def write_report(root):
    root = Path(root)
    report = json.loads((root / "evaluation.json").read_text())
    labels = json.loads((root / "label-review.json").read_text())
    deployment = json.loads((root / "deployment-checks.json").read_text())
    live = json.loads((root / "live-evaluation.json").read_text())
    lines = [
        "# Live qualification report",
        "",
        f"Qualification scope: **{report['release']['qualification_scope']}**",
        "",
        f"Production Gate: **{'Passed' if report['release']['production_approved'] else 'Pending'}**",
        "",
        "AWS cloud rollout and container execution are not certified by a local-release pass.",
        "",
        f"LangSmith project: `{live.get('project_name')}`",
        "",
        f"Business cases: **{report['passed']} / {report['cases']}**. The malformed-quarter case is rejected before inference; the remaining cases must use the real model without fallback.",
        "",
        f"Agent logical model calls: {report['external_api_calls']}. Token usage: {json.dumps(report.get('usage', {}))}.",
        "",
        f"Independent model judge: `{labels['judge_model']}`, {sum(row['review_status'] == 'passed' for row in labels['rows'])} / {len(labels['rows'])} cases passed. Reference: user-approved project-authored rules; no independent expert sign-off claimed.",
        "",
        "## Evaluation metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for name, value in report["metrics"].items():
        lines.append(
            f"| {name} | {value:.4f} |"
            if isinstance(value, (int, float))
            else f"| {name} | {value} |"
        )
    lines.extend(
        [
            "",
            "## Memory Eval",
            "",
            "```json",
            json.dumps(report["memory"], indent=2),
            "```",
            "",
            "## Gate evidence",
            "",
            "| Requirement | Status |",
            "|---|---|",
        ]
    )
    for key in [
        "local_contracts_pass",
        "independent_labels_reviewed",
        "real_llm_evaluated",
        "deployment_checks_pass",
    ]:
        lines.append(f"| {key} | {'Passed' if report['release'][key] else 'Pending'} |")
    lines.extend(
        [
            "",
            "## Local deployment checks",
            "",
            "```json",
            json.dumps(
                {
                    "http": deployment["checks"],
                    "dockerfile": deployment.get("dockerfile_checks"),
                    "container_executed": deployment.get("container_arm64_passed"),
                    "aws_verified": deployment.get("aws_runtime_verified"),
                },
                indent=2,
            ),
            "```",
            "",
            "## Case traces",
            "",
            "| Case | LangSmith Run ID | Mode | Tokens | Elapsed ms |",
            "|---|---|---|---|---|",
        ]
    )
    for row in report["rows"]:
        runtime = row.get("runtime", {})
        lines.append(
            f"| {row['case_id']} | `{row.get('case_trace_id')}` | {runtime.get('mode', 'validation_error')} | {runtime.get('usage', {}).get('total_tokens', 0)} | {row['elapsed_ms']} |"
        )
    metadata_path = root / "langsmith-project.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        lines.extend(["", "## LangSmith access", "", f"[Open a verified run]({metadata['example_run_url']})", "", f"Project ID: `{metadata['project_id']}`."])
    lines.extend(["", "## Security and models", "", "The private .env is Git-ignored, excluded from Docker context, and restricted to file mode 0600. Project text scanning found no plaintext credential values. LangChain credential/project aliases are mapped in process without printing secrets.", "", "Local encoder weights: sentence-transformers/all-MiniLM-L6-v2 and cross-encoder/ms-marco-TinyBERT-L-2-v2. Repository revisions and download sizes are recorded in runtime/models/manifest.json. CPU inference is limited to two Torch threads.", "", "## Retained failure evidence", "", "The earlier failed judge contract, agent-tool completion failures and the real-vector memory abstention failure remain in label-review-attempt1.json, evaluation-attempt1.json and evaluation-attempt2-memory-abstention.json. The fixes clarified expected-output contracts, required both current factory checks, moved numeric constraints to deterministic tools, removed vectors from prompts and rejected low-relevance memory after reranking. Business assertions were not weakened.", "", "Token figures above describe the final acceptance batch; earlier diagnostics, retries and judge probes are separate provider usage. Passing this synthetic local release suite does not establish general production business accuracy."])
    destination = root / "qualification-summary.md"
    destination.write_text("\n".join(lines) + "\n")
    return destination


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runtime/live-qualification")
    print(write_report(parser.parse_args().root))
