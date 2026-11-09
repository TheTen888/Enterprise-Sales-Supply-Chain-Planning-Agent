import pytest

from agent.service import Service
from config.contracts import Scope
from mock_data.generator import generate


@pytest.fixture(autouse=True)
def offline_test_environment(monkeypatch):
    for name in ["OPENAI_API_KEY", "OPENAI_MODEL", "JUDGE_MODEL", "REDIS_URL", "LANGSMITH_API_KEY"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.setenv("AGENT_MODE", "mock")
    monkeypatch.setenv("AGENT_ENV", "local")


@pytest.fixture
def scope():
    return Scope(customer_id="CUSTOMER-A", project_id="PROJECT-A")


@pytest.fixture
def service(tmp_path):
    generate(tmp_path / "source")
    instance = Service(tmp_path)
    instance.ingest_all()
    return instance
