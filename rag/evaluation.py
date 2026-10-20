import json
from dataclasses import replace
from pathlib import Path

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.pipeline import IncrementalETL
from scripts.fixtures import order_event


def condition_checks(passages: list[dict], conditions: list[dict]) -> list[dict]:
    return [
        {
            "condition_id": condition["condition_id"],
            "covered": any(
                row.get("chunk_id") == condition["chunk_id"]
                and row.get("document_id") == condition["document_id"]
                and row.get("version") == condition["version"]
                and condition["required_text"] in row.get("text", "")
                for row in passages
            ),
        }
        for condition in conditions
    ]


def evaluate_cases(service, as_of: str, path: Path) -> dict:
    fixture = json.loads(path.read_text())
    if fixture.get("synthetic") is not True or fixture.get("format_version") != 1:
        raise ValueError("version-one synthetic evaluation fixture required")
    results = []
    for case in fixture["cases"]:
        try:
            pack = service.retrieve(
                case["actor"],
                case["customer"],
                case["project"],
                case["entity"],
                case["query"],
                as_of,
                case["k"],
                case["task"],
            )
        except PermissionError:
            results.append(
                {
                    "case_id": case["case_id"],
                    "passed": case.get("expect_denied") is True,
                    "denied": True,
                }
            )
            continue
        expected = set(case.get("expected_document_ids", []))
        actual = {citation["document_id"] for citation in pack["citations"]}
        conditions = case.get("expected_conditions", [])
        covered = condition_checks(pack["citations"], conditions)
        match_ids = {row["chunk_id"] for row in pack["retrieval_matches"]}
        baseline = condition_checks(
            [row for row in pack["citations"] if row["chunk_id"] in match_ids], conditions
        )
        checks = {
            "access_behavior": not case.get("expect_denied", False),
            "expected_documents": actual == expected,
            "expected_status": pack["status"] == case.get("expected_status"),
            "expected_document_versions": all(
                row["version"] == case.get("expected_versions", {}).get(row["document_id"])
                for row in pack["citations"]
            ),
            "expected_sql_facts": all(
                pack["facts"].get(key) == value
                for key, value in case.get("expected_facts", {}).items()
            ),
            "authorized_evidence_only": all(
                (row["customer_id"], row["project_id"], row["entity_id"])
                == (case["customer"], case["project"], case["entity"])
                for row in pack["citations"]
            ),
            "no_model_calls": pack["model_calls"] == 0,
            "expected_context_complete": pack["context"]["complete"]
            == case.get("expected_context_complete", True),
            "expected_chunks": "expected_chunk_ids" not in case
            or {row["chunk_id"] for row in pack["citations"]} == set(case["expected_chunk_ids"]),
            "required_conditions_covered": all(row["covered"] for row in covered),
        }
        results.append(
            {
                "case_id": case["case_id"],
                "passed": all(checks.values()),
                "checks": checks,
                "expected_documents": sorted(expected),
                "actual_documents": sorted(actual),
                "recall_at_k": len(actual & expected) / len(expected) if expected else None,
                "precision_at_k": len(actual & expected) / case["k"] if expected else None,
                "elapsed_ms": pack["elapsed_ms"],
                "condition_checks": covered,
                "condition_coverage": sum(row["covered"] for row in covered) / len(covered)
                if covered
                else None,
                "single_passage_condition_coverage": sum(row["covered"] for row in baseline)
                / len(baseline)
                if baseline
                else None,
                "returned_chunk_count": len(pack["citations"]),
                "context_chars": pack["context"]["returned_chars"],
            }
        )
    positives = [row for row in results if row.get("recall_at_k") is not None]
    labeled = [row for row in results if row.get("condition_coverage") is not None]
    return {
        "passed": bool(results) and all(row["passed"] for row in results),
        "cases": results,
        "case_count": len(results),
        "positive_retrieval_case_count": len(positives),
        "access_denial_cases": sum(row.get("denied", False) for row in results),
        "mean_recall_at_k": sum(row["recall_at_k"] for row in positives) / len(positives)
        if positives
        else None,
        "mean_precision_at_k": sum(row["precision_at_k"] or 0 for row in positives) / len(positives)
        if positives
        else None,
        "metric_unit": fixture["metric_unit"],
        "condition_labeled_cases": len(labeled),
        "mean_condition_coverage": sum(row["condition_coverage"] for row in labeled) / len(labeled)
        if labeled
        else None,
        "mean_single_passage_condition_coverage": sum(
            row["single_passage_condition_coverage"] for row in labeled
        )
        / len(labeled)
        if labeled
        else None,
        "measurement_scope": "Small reviewed English synthetic corpus; distinct-document lexical retrieval, exact SQL facts and manually labeled source-bound condition spans. No semantic generalization, LLM faithfulness or production latency claim.",
    }


def lifecycle_experiments(root: Path, prepare) -> list[dict]:
    query = "customer price discount design D2 material inspection engineering cost change"

    def request(service, as_of):
        return service.retrieve(
            "demo-manager-a", "CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1", query, as_of, 2
        )

    results = []
    service, as_of = prepare(root / "update")
    first = request(service, as_of)
    cached = request(service, as_of)
    prior = service.store.latest("ENG-A-001")
    updated = replace(
        prior,
        version=3,
        body="# Revised engineering evidence\n\nDesign D2 material inspection cost change explains the customer price discount request. A new process review supersedes the previous engineering explanation.\n",
    )
    service.store.put_documents([updated])
    pending = request(service, as_of)
    service.store.refresh_index()
    refreshed = request(service, as_of)
    checks = {
        "initial_quote_ready": first["status"] == "ready",
        "cache_exercised": cached["cache_hit"],
        "stale_version_blocked_before_refresh": not any(
            row["document_id"] == "ENG-A-001" for row in pending["citations"]
        ),
        "incomplete_before_refresh": pending["status"] == "insufficient_evidence"
        and not pending["index_fresh"],
        "new_version_after_refresh": any(
            row["document_id"] == "ENG-A-001" and row["version"] == 3
            for row in refreshed["citations"]
        ),
    }
    results.append(
        {
            "experiment": "Source update while index and answer cache are stale",
            "checks": checks,
            "passed": all(checks.values()),
        }
    )

    service, as_of = prepare(root / "delete")
    request(service, as_of)
    prior = service.store.latest("ENG-A-001")
    service.store.delete("ENG-A-001", as_of)
    deleted = request(service, as_of)
    historical = request(service, "2026-10-15")
    service.store.refresh_index()
    service.store.put_documents([prior])
    replayed = request(service, as_of)
    with service.store.connect() as connection:
        remaining_chunks = connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id='ENG-A-001'"
        ).fetchone()[0]
    checks = {
        "deleted_evidence_blocked_before_refresh": not any(
            row["document_id"] == "ENG-A-001" for row in deleted["citations"]
        ),
        "historical_query_cannot_bypass_current_deletion": not any(
            row["document_id"] == "ENG-A-001" for row in historical["citations"]
        ),
        "deleted_index_chunks_removed": remaining_chunks == 0,
        "old_ingestion_cannot_resurrect": replayed["status"] == "insufficient_evidence"
        and not any(row["document_id"] == "ENG-A-001" for row in replayed["citations"]),
    }
    results.append(
        {
            "experiment": "Deletion propagation and late old-version replay",
            "checks": checks,
            "passed": all(checks.values()),
        }
    )

    service, as_of = prepare(root / "revoke")
    request(service, as_of)
    service.store.revoke("demo-manager-a", "CUSTOMER-A", "PROJECT-A")
    denied = False
    try:
        request(service, as_of)
    except PermissionError:
        denied = True
    results.append({"experiment": "Access revoked after cache population", "passed": denied})

    service, as_of = prepare(root / "conflict")
    document = service.store.latest("ENG-A-001")
    before = service.store.revisions()
    rejected = []
    for invalid in [
        replace(document, body="Conflicting same-version content"),
        replace(document, version=3, customer_id="CUSTOMER-B", project_id="PROJECT-B"),
    ]:
        try:
            service.store.put_documents([invalid])
        except ValueError:
            rejected.append(True)
    checks = {
        "version_and_ownership_conflicts_rejected": len(rejected) == 2,
        "failed_ingestion_does_not_change_revision": service.store.revisions() == before,
        "previous_quote_still_ready": request(service, as_of)["status"] == "ready",
    }
    results.append(
        {
            "experiment": "Conflicting version and reassigned document ownership",
            "checks": checks,
            "passed": all(checks.values()),
        }
    )

    service, as_of = prepare(root / "order-update")
    request(service, as_of)
    source = Source(service.warehouse.parent / "source.db")
    warehouse = Warehouse(service.warehouse)
    source.append(
        [order_event("ORDER-A001-L1", 4, quantity=20000, unit_cost="13.50", design_version="D2")]
    )
    IncrementalETL(source, warehouse).run_once()
    changed = request(service, as_of)
    checks = {
        "new_order_version_used": changed["facts"]["business_version"] == 4,
        "new_quantity_and_cost_used": changed["facts"]["quantity"] == 20000
        and changed["facts"]["unit_cost_cents"] == 1350,
        "old_fact_cache_not_used": not changed["cache_hit"],
    }
    results.append(
        {
            "experiment": "New ETL publication invalidates cached order facts",
            "checks": checks,
            "passed": all(checks.values()),
        }
    )
    return results
