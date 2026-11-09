import json

import pytest
from openpyxl import load_workbook

from config.contracts import Scope
from data_pipeline.conversion import FormulaEngine, FormulaError, convert
from data_pipeline.ingestion import LocalIngestion, RateLimitError
from mock_data.generator import generate


def test_formula_recomputed_without_excel_cache(tmp_path):
    generate(tmp_path)
    path = tmp_path / "bom_quote_v1.xlsx"
    assert load_workbook(path, data_only=True).active["D5"].value is None
    result = convert(path)
    assert result["unit_cost_cents"] == 1300
    assert result["lane"] == "server"
    assert FormulaEngine(load_workbook(path).active).cell("D7") == 5


def test_inconsistent_bom_rejected(tmp_path):
    generate(tmp_path)
    with pytest.raises(FormulaError, match="disagree"):
        convert(tmp_path / "bom_quote_invalid.xlsx")


@pytest.mark.parametrize("value", [-1, 0, 1.25])
def test_invalid_bom_amounts_rejected(tmp_path, value):
    generate(tmp_path)
    path = tmp_path / "bom_quote_v1.xlsx"
    workbook = load_workbook(path)
    workbook.active["C2"] = value
    workbook.save(path)
    with pytest.raises(FormulaError, match="positive integers"):
        convert(path)


@pytest.mark.parametrize(
    "formula",
    ['=HYPERLINK("https://example.invalid")', "=D5", "=__import__('os')", "=[external.xlsx]A1"],
)
def test_unsupported_or_circular_formula_rejected(tmp_path, formula):
    generate(tmp_path)
    workbook = load_workbook(tmp_path / "bom_quote_v1.xlsx")
    workbook.active["D5"] = formula
    with pytest.raises(FormulaError):
        FormulaEngine(workbook.active).cell("D5")


def test_retry_resumes_from_embedding(tmp_path):
    metadata = generate(tmp_path / "source")[2]
    pipeline = LocalIngestion(tmp_path / "ingestion.sqlite")
    with pytest.raises(RateLimitError):
        pipeline.ingest(tmp_path / "source", metadata, simulate_rate_limit=True)
    recovered = LocalIngestion(tmp_path / "ingestion.sqlite").ingest(tmp_path / "source", metadata)
    assert recovered["skipped"] == ["fetch", "convert", "chunk"]
    assert recovered["completed"] == ["embed", "upsert"]


def test_repeated_ingestion_does_not_duplicate(service, scope):
    before = service.ingestion.current(scope)
    doc = json.loads((service.source / "manifest.json").read_text())[2]
    result = service.ingestion.ingest(service.source, doc)
    assert result["skipped"] == list(LocalIngestion.steps)
    assert service.ingestion.current(scope) == before
    assert service.ingestion.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 5


def test_older_version_rejected(service):
    old = json.loads((service.source / "manifest.json").read_text())[0]
    with pytest.raises(ValueError, match="Stale"):
        service.ingestion.ingest(service.source, old)


def test_content_and_metadata_must_agree(tmp_path):
    doc = generate(tmp_path / "source")[1]
    doc["lead_days"] = 1
    with pytest.raises(ValueError, match="metadata"):
        LocalIngestion(tmp_path / "index.sqlite").ingest(tmp_path / "source", doc)


def test_conflicting_same_version_rejected(service):
    doc = json.loads((service.source / "manifest.json").read_text())[1]
    doc["lead_days"] = 1
    with pytest.raises(ValueError, match="conflicting"):
        service.ingestion.ingest(service.source, doc)


def test_source_path_escape_rejected(service):
    doc = json.loads((service.source / "manifest.json").read_text())[1]
    doc["path"] = "../knowledge.sqlite"
    with pytest.raises(ValueError, match="escapes"):
        service.ingestion.ingest(service.source, doc)


def test_rag_filters_customer_and_deprecated_version(service, scope):
    result = service.graph
    assert result is not None
    from rag.hybrid_rag import HybridRAG

    rows = HybridRAG(service.ingestion).retrieve(scope, "ECN-001 PART-001", "PART-001")
    assert all(row["metadata"]["customer_id"] == "CUSTOMER-A" for row in rows)
    assert all(row["metadata"]["version"] == 2 for row in rows if row["metadata"]["kind"] == "ecn")


def test_deleted_ecn_not_returned_or_reactivated(service, scope):
    from rag.hybrid_rag import HybridRAG

    service.ingestion.delete(scope, "ECN-001")
    assert all(
        row["metadata"]["kind"] != "ecn"
        for row in HybridRAG(service.ingestion).retrieve(scope, "ECN-001", "PART-001")
    )
    doc = json.loads((service.source / "manifest.json").read_text())[1]
    with pytest.raises(ValueError, match="resurrected"):
        service.ingestion.ingest(service.source, doc)


def test_memory_dedup_update_scope_and_delete(service, scope):
    memory = service.memory
    assert (
        memory.store_preference(scope, "shipping", "FOB Alpha", "MAIL:v1")["status"]
        == "pending_confirmation"
    )
    assert memory.recall(scope) == {}
    assert memory.store_preference(scope, "shipping", "FOB Alpha", "MAIL:v1", True)["version"] == 1
    assert (
        memory.store_preference(scope, "shipping", "FOB Alpha", "MAIL:v1", True)["status"]
        == "duplicate"
    )
    assert memory.store_preference(scope, "shipping", "FOB Beta", "MAIL:v2", True)["version"] == 2
    assert memory.recall(scope)["shipping"]["value"] == "FOB Beta"
    assert memory.recall(Scope(customer_id="CUSTOMER-B", project_id="PROJECT-B")) == {}
    memory.forget(scope, "shipping")
    assert memory.recall(scope) == {}


def test_context_compaction_has_budget(service, scope):
    for i in range(20):
        service.memory.add_turn(scope, "thread", {"turn": i, "text": "x" * 200})
    context = service.memory.context(scope, "thread", max_chars=1000)
    assert context["characters"] <= 1000
    assert context["summary"]["earlier_turns"] == 14
    assert service.memory.context(scope, "other")["recent"] == []
