import json
from pathlib import Path

from config.contracts import fingerprint
from evaluation.judge import dataset_hash


def implementation_hash():
    root = Path(__file__).resolve().parents[1]
    files = {
        str(path.relative_to(root)): path.read_text()
        for directory in [
            "agent",
            "memory",
            "rag",
            "config",
            "deployment",
            "evaluation",
            "data_pipeline",
        ]
        for path in (root / directory).rglob("*")
        if path.suffix in {".py", ".md", ".json"}
    }
    for name in ["pyproject.toml", "requirements-lock.txt", "deployment/Dockerfile"]:
        path = root / name
        if path.exists():
            files[name] = path.read_text()
    return fingerprint(files)


def release_gates(report, root):
    root = Path(root)

    def read(name):
        path = root / name
        try:
            return json.loads(path.read_text()) if path.exists() else {}
        except (ValueError, OSError):
            return {}

    labels = read("label-review.json")
    deployment = read("deployment-checks.json")
    evidence = read("live-evaluation.json")
    local_pass = report["passed"] == report["cases"] == 23 and report.get("memory", {}).get(
        "passed", False
    )
    label_pass = (
        labels.get("review_status") == "passed"
        and labels.get("mode") == "llm"
        and labels.get("model_separate_from_agent") is True
        and labels.get("dataset_hash") == dataset_hash()
        and len(labels.get("rows", [])) == 23
        and all(row.get("review_status") == "passed" for row in labels.get("rows", []))
        and labels.get("logical_model_calls", 0) >= 23
        and labels.get("reference_review", {}).get("status") == "passed"
        and labels.get("reference_review", {}).get("dataset_hash") == dataset_hash()
    )
    live_pass = (
        evidence.get("dataset_hash") == dataset_hash()
        and evidence.get("implementation_hash") == implementation_hash()
        and evidence.get("cases") == 23
        and evidence.get("passed") == 23
        and evidence.get("all_real_llm") is True
        and evidence.get("all_semantic") is True
        and evidence.get("no_fallbacks") is True
        and evidence.get("tracing_verified") is True
    )
    cloud_deploy_pass = deployment.get("implementation_hash") == implementation_hash() and all(
        deployment.get(key) is True
        for key in [
            "http_contract_passed",
            "container_arm64_passed",
            "identity_access_checked",
            "aws_runtime_verified",
        ]
    )
    local_deploy_pass = (
        deployment.get("implementation_hash") == implementation_hash()
        and deployment.get("http_contract_passed") is True
        and deployment.get("identity_access_checked") is True
        and deployment.get("dockerfile_checks", {}).get("passed") is True
    )
    local_scope = report.get("qualification_scope") == "local_release"
    deploy_pass = local_deploy_pass if local_scope else cloud_deploy_pass
    checks = {
        "local_contracts_pass": local_pass,
        "independent_labels_reviewed": label_pass,
        "real_llm_evaluated": live_pass,
        "deployment_checks_pass": deploy_pass,
    }
    return {
        **checks,
        "local_acceptance_passed": local_pass,
        "production_approved": all(checks.values()),
        "qualification_scope": "local_release" if local_scope else "cloud_production",
        "aws_production_approved": all(checks.values()) and cloud_deploy_pass,
        "blockers": [key for key, value in checks.items() if not value],
    }
