import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from a2a.types import Task

from agent.service import Service
from evaluation.gates import implementation_hash
from mock_data.generator import generate


def request_json(base, path, payload=None, token=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(base + path, data=data, headers=headers), timeout=20
        ) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def check_http(base, token):
    ping, health = request_json(base, "/ping")
    unauthorized, _ = request_json(base, "/invocations", {"prompt": "What is FOB?"})
    status, response = request_json(base, "/invocations", {"prompt": "Prepare quote"}, token)
    invalid, _ = request_json(
        base, "/invocations", {"prompt": "Prepare quote", "quantity": -1}, token
    )
    injected, _ = request_json(
        base, "/invocations", {"prompt": "Prepare quote", "customer_id": "CUSTOMER-B"}, token
    )
    task_valid = False
    if status == 200:
        Task.model_validate(response.get("a2a_task", {}))
        task_valid = all(
            name in response for name in ["task_id", "status", "messages", "artifacts"]
        )
    return {
        "ping": ping == 200 and health.get("status") in {"Healthy", "HealthyBusy"},
        "invocation": status == 200 and task_valid,
        "payload_validation": invalid == 422,
        "customer_injection_rejected": injected == 422,
        "unauthorized_rejected": unauthorized == 401,
    }


def local_check(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    state = root / f"deployment-{uuid.uuid4().hex}"
    generate(state / "source")
    Service(state).ingest_all()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = uuid.uuid4().hex
    environment = {
        **os.environ,
        "AGENT_MODE": "mock",
        "AGENT_RUNTIME_ROOT": str(state),
        "AGENT_HOST": "127.0.0.1",
        "AGENT_PORT": str(port),
        "AGENT_CALLER_TOKENS": json.dumps({token: "demo-manager"}),
        "AGENT_ENV": "local",
        "LANGCHAIN_TRACING_V2": "false",
    }
    log = (state / "server.log").open("w")
    process = subprocess.Popen(
        [sys.executable, "-m", "deployment.agentcore_app"], env=environment, stdout=log, stderr=log
    )
    base = f"http://127.0.0.1:{port}"
    checks = {}
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                if request_json(base, "/ping")[0] == 200:
                    checks = check_http(base, token)
                    break
            except (OSError, ValueError):
                time.sleep(0.1)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()
    report = {
        "implementation_hash": implementation_hash(),
        "http_contract_passed": bool(checks) and all(checks.values()),
        "checks": checks,
        "tested_sdk": "bedrock-agentcore",
        "tested_transport": "real_loopback_http",
        "container_arm64_passed": False,
        "identity_access_checked": checks.get("unauthorized_rejected", False)
        and checks.get("customer_injection_rejected", False),
        "aws_runtime_verified": False,
        "dockerfile_checks": dockerfile_checks(),
        "docker_available": bool(shutil.which("docker")),
        "scope": "Native SDK HTTP and local bearer identity contract; not a deployed AWS runtime",
    }
    (root / "deployment-checks.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def dockerfile_checks():
    project = Path(__file__).resolve().parents[1]
    text = (project / "deployment/Dockerfile").read_text()
    ignored = (project / ".dockerignore").read_text()
    checks = {
        "arm64_target": "--platform=linux/arm64" in text,
        "nonroot_user": "USER agent" in text,
        "port_8080": "EXPOSE 8080" in text,
        "healthcheck": "HEALTHCHECK" in text and "/ping" in text,
        "entrypoint": '"deployment.agentcore_app"' in text,
        "secrets_excluded": ".env*" in ignored,
        "runtime_secrets_not_baked": "OPENAI_API_KEY=" not in text
        and "LANGCHAIN_API_KEY=" not in text,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "scope": "Static Dockerfile configuration; no image build or container execution claimed",
    }


def container_check(root):
    root = Path(root).resolve()
    path = root / "deployment-checks.json"
    report = json.loads(path.read_text()) if path.exists() else local_check(root)
    if not shutil.which("docker"):
        report["container_error"] = "Docker is not installed"
    else:
        project = Path(__file__).resolve().parents[1]
        image = f"sales-agent-contract:{uuid.uuid4().hex[:8]}"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        token = uuid.uuid4().hex
        container = None
        try:
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--platform",
                    "linux/arm64",
                    "-f",
                    "deployment/Dockerfile",
                    "-t",
                    image,
                    ".",
                ],
                cwd=project,
                check=True,
                timeout=600,
                capture_output=True,
            )
            architecture = subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Architecture}}", image],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            container = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-d",
                    "-p",
                    f"127.0.0.1:{port}:8080",
                    "-e",
                    "AGENT_ENV=local",
                    "-e",
                    "AGENT_MODE=mock",
                    "-e",
                    f"AGENT_CALLER_TOKENS={json.dumps({token: 'demo-manager'})}",
                    image,
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            deadline = time.monotonic() + 40
            checks = {}
            while time.monotonic() < deadline:
                try:
                    if request_json(f"http://127.0.0.1:{port}", "/ping")[0] == 200:
                        checks = check_http(f"http://127.0.0.1:{port}", token)
                        break
                except (OSError, ValueError):
                    time.sleep(0.2)
            report["container_checks"] = checks
            report["container_arm64_passed"] = (
                architecture == "arm64" and bool(checks) and all(checks.values())
            )
        except (OSError, subprocess.SubprocessError) as exc:
            report["container_error"] = type(exc).__name__
            report["container_arm64_passed"] = False
        finally:
            if container:
                subprocess.run(["docker", "stop", container], capture_output=True, timeout=15)
    report["implementation_hash"] = implementation_hash()
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def verify_aws(root, runtime_arn):
    import boto3

    path = Path(root) / "deployment-checks.json"
    report = json.loads(path.read_text()) if path.exists() else {}
    client = boto3.client("bedrock-agentcore")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=str(uuid.uuid4()),
        payload=json.dumps({"prompt": "Prepare quote"}).encode(),
        contentType="application/json",
    )
    payload = json.loads(response["response"].read())
    Task.model_validate(payload["a2a_task"])
    report["aws_runtime_verified"] = (
        payload.get("implementation_hash") == implementation_hash()
        and payload.get("runtime", {}).get("mode") == "llm"
        and payload["runtime"].get("fallback_reason") is None
    )
    report["implementation_hash"] = implementation_hash()
    path.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runtime/studio")
    parser.add_argument("--container", action="store_true")
    arguments = parser.parse_args()
    report = local_check(arguments.root)
    if arguments.container:
        report = container_check(arguments.root)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["http_contract_passed"] else 1)
