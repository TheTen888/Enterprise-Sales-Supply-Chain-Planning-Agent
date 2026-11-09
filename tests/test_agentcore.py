from a2a.types import Task
from starlette.testclient import TestClient

from deployment.agentcore_app import create_app, invoke_payload
from deployment.self_check import local_check


def test_real_sdk_invocation_and_payload_contract(service):
    with TestClient(create_app(service, {"test-token": "demo-manager"})) as client:
        assert client.get("/ping").status_code == 200
        assert client.post("/invocations", json={"prompt": "Prepare quote"}).status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        response = client.post("/invocations", headers=headers, json={"prompt": "Prepare quote"})
        assert response.status_code == 200
        result = response.json()
        Task.model_validate(result["a2a_task"])
        assert result["status"]["state"] == "input-required"
        assert result["artifacts"] and result["messages"]
        assert (
            client.post(
                "/invocations", headers=headers, json={"prompt": "Prepare quote", "quantity": -1}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/invocations",
                headers=headers,
                json={"prompt": "Prepare quote", "customer_id": "OTHER"},
            ).status_code
            == 422
        )


def test_authenticated_principal_still_needs_customer_grant(service):
    with TestClient(create_app(service, {"token": "unknown-manager"})) as client:
        assert (
            client.post(
                "/invocations",
                headers={"Authorization": "Bearer token"},
                json={"prompt": "Prepare quote"},
            ).status_code
            == 403
        )


def test_direct_response_has_valid_a2a_task(service):
    result = invoke_payload({"prompt": "What is FOB?"}, service)
    assert result["status"]["state"] == "completed"
    Task.model_validate(result["a2a_task"])


def test_real_network_localhost_deployment_check(tmp_path):
    result = local_check(tmp_path)
    assert result["http_contract_passed"]
    assert result["identity_access_checked"]
    assert not result["aws_runtime_verified"]
    assert not result["container_arm64_passed"]
