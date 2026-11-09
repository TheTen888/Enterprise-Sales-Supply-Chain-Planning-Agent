import json

import pytest
from streamlit.testing.v1 import AppTest

from data_pipeline.ingestion import LocalIngestion
from deployment.adapters import inngest_document_handler
from mock_data.generator import generate
from rag.hybrid_rag import CrossEncoderReranker


@pytest.mark.parametrize("boundary", ["before_publish_commit", "after_publish_commit"])
def test_publication_boundary_recovery(tmp_path, scope, boundary):
    doc = generate(tmp_path / "source")[2]
    pipeline = LocalIngestion(tmp_path / "index.sqlite")
    with pytest.raises(RuntimeError, match="Injected"):
        pipeline.ingest(tmp_path / "source", doc, fault=boundary)
    restarted = LocalIngestion(tmp_path / "index.sqlite")
    before = restarted.current(scope)
    assert len(before) == (1 if boundary == "after_publish_commit" else 0)
    recovered = restarted.ingest(tmp_path / "source", doc)
    assert len(restarted.current(scope)) == 1
    assert (
        recovered["skipped"] == list(LocalIngestion.steps)
        if boundary == "after_publish_commit"
        else recovered["completed"] == ["upsert"]
    )


def test_cross_encoder_adapter_uses_supplied_model():
    class FakeModel:
        def predict(self, pairs):
            assert pairs == [("query", "a"), ("query", "b")]
            return [0.1, 0.9]

    rows = CrossEncoderReranker(FakeModel())("query", [{"text": "a"}, {"text": "b"}])
    assert rows[0]["text"] == "b"


def test_inngest_adapter_step_contract(tmp_path):
    import asyncio

    metadata = generate(tmp_path / "source")[2]
    calls = []

    class Step:
        async def run(self, name, function):
            calls.append(name)
            return function()

    class Context:
        step = Step()

    pipeline = LocalIngestion(tmp_path / "index.sqlite")
    result = asyncio.run(
        inngest_document_handler(Context(), pipeline, tmp_path / "source", metadata)
    )
    assert calls == ["ingest-document"]
    assert result["completed"] == list(LocalIngestion.steps)


def test_dashboard_scenario_eval_and_recalculation(tmp_path, monkeypatch):
    from pathlib import Path

    entrypoint = Path(__file__).resolve().parents[1] / "evaluation/dashboard.py"
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(entrypoint)).run(timeout=20)
    assert not app.exception
    app.button[0].click().run(timeout=20)
    assert not app.exception
    assert any(metric.value == "$14.45" for metric in app.metric)
    app.number_input[0].set_value(50000).run(timeout=20)
    assert app.button[1].disabled
    app.button[0].click().run(timeout=20)
    assert any("Neither factory" in error.value for error in app.error)
    next(button for button in app.button if button.label == "Run evaluation").click().run(
        timeout=20
    )
    assert not app.exception
    assert any(metric.value == "23 / 23" for metric in app.metric)


def test_no_private_fixtures_in_manifest(service):
    docs = json.loads((service.source / "manifest.json").read_text())
    assert {doc["customer_id"] for doc in docs} == {"CUSTOMER-A", "CUSTOMER-B"}
