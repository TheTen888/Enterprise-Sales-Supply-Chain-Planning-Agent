import json
import logging
import subprocess
from pathlib import Path

from config.environment import load_environment, redact


def test_dotenv_aliases_without_logging_values(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_MODE", raising=False)
    for name in [
        "OPENAI_API_KEY",
        "LANGCHAIN_API_KEY",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_PROJECT",
        "LANGSMITH_PROJECT",
    ]:
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        'OPENAI_API_KEY=test-private-openai\nLANGCHAIN_API_KEY=test-private-tracing\nLANGCHAIN_PROJECT=Test-Project\nLANGCHAIN_TRACING_V2="true"\n'
    )
    load_environment(env)
    import os

    assert os.getenv("LANGSMITH_API_KEY") == "test-private-tracing"
    assert os.getenv("LANGSMITH_PROJECT") == "Test-Project"
    assert env.stat().st_mode & 0o777 == 0o600
    assert "test-private-openai" not in redact("test-private-openai")
    record = logging.getLogger("test-security").makeRecord(
        "test-security", logging.ERROR, "", 0, "value=%s", ("test-private-tracing",), None
    )
    assert "test-private-tracing" not in record.getMessage()


def test_gitignore_excludes_env_and_includes_example(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text((root / ".gitignore").read_text())
    assert (
        subprocess.run(["git", "check-ignore", "-q", "--no-index", ".env"], cwd=tmp_path).returncode
        == 0
    )
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", ".env.example"], cwd=tmp_path
        ).returncode
        == 1
    )


def test_local_release_does_not_claim_aws_deployment(service):
    from evaluation.eval_pipeline import evaluate
    from evaluation.gates import implementation_hash, release_gates

    report = evaluate(service)
    report["qualification_scope"] = "local_release"
    deployment = {
        "implementation_hash": implementation_hash(),
        "http_contract_passed": True,
        "identity_access_checked": True,
        "dockerfile_checks": {"passed": True},
        "aws_runtime_verified": False,
        "container_arm64_passed": False,
    }
    (service.root / "deployment-checks.json").write_text(json.dumps(deployment))
    gate = release_gates(report, service.root)
    assert gate["deployment_checks_pass"]
    assert not gate["aws_production_approved"]
