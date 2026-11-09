import hashlib
import json
from pathlib import Path

from evaluation.judge import dataset, dataset_hash


def inspect_expert_labels(path):
    if not path:
        return {"status": "pending", "reason": "Independent expert annotation file not supplied"}
    path = Path(path)
    if not path.is_file():
        return {"status": "pending", "reason": "Annotation file does not exist"}
    content = json.loads(path.read_text())
    entries = (
        content if isinstance(content, list) else content.get("cases", content.get("labels", []))
    )
    indexed = {row.get("case_id", row.get("id")): row for row in entries}
    failures = []
    for case in dataset():
        row = indexed.get(case["id"])
        if row is None:
            failures.append({"case_id": case["id"], "issue": "missing expert label"})
            continue
        expected = row.get("expected_route", row.get("expected", {}).get("route"))
        oracle = row.get("oracle", row.get("expected", {}).get("oracle"))
        if expected != case["expected_route"] or oracle != case["oracle"]:
            failures.append(
                {
                    "case_id": case["id"],
                    "issue": "expert result differs from fixture; reconcile business facts",
                }
            )
    reviewer = content.get("reviewer") if isinstance(content, dict) else None
    if not reviewer and not all(row.get("reviewer") for row in entries):
        failures.append({"issue": "reviewer provenance missing"})
    return {
        "status": "passed" if not failures and len(indexed) == 23 else "failed",
        "dataset_hash": dataset_hash(),
        "annotation_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        "case_count": len(indexed),
        "source_file": path.name,
        "reviewer_provenance_present": bool(reviewer)
        or all(row.get("reviewer") for row in entries),
        "failures": failures,
    }


def attach_expert_labels(root, path):
    report_path = Path(root) / "label-review.json"
    report = json.loads(report_path.read_text())
    report["expert_review"] = inspect_expert_labels(path)
    model_pass = report.get("model_review_status", report.get("review_status")) == "passed"
    report["model_review_status"] = "passed" if model_pass else "failed"
    report["review_status"] = (
        "passed"
        if model_pass and report["expert_review"]["status"] == "passed"
        else "pending_expert_review"
        if model_pass
        else "failed"
    )
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report
