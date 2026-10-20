import argparse
import copy
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from rag.documents import chunk_document, load_documents
from rag.evaluation import condition_checks
from rag.retrieval import render_report
from scripts.run_rag import DEFAULT_QUERY, RAG_FIXTURES, prepare_demo


def review(root: Path) -> dict:
    service, as_of = prepare_demo(root / "run")
    arguments = dict(
        actor="demo-manager-a",
        customer="CUSTOMER-A",
        project="PROJECT-A",
        entity="ORDER-A001-L1",
        query=DEFAULT_QUERY,
        as_of=as_of,
        k=2,
    )

    def record(name):
        pack = service.retrieve(**arguments)
        (root / (name + ".txt")).write_text(render_report(pack))
        return {
            key: pack[key]
            for key in (
                "status",
                "index_fresh",
                "cache_hit",
                "revisions",
                "facts",
                "citations",
                "context",
                "retrieval_matches",
                "returned_document_count",
                "returned_chunk_count",
            )
        }

    documents, _, _ = load_documents(RAG_FIXTURES)
    initial = record("01-initial")
    conditions = json.loads((RAG_FIXTURES / "eval-cases.json").read_text())["cases"][0][
        "expected_conditions"
    ]
    match_ids = {row["chunk_id"] for row in initial["retrieval_matches"]}
    baseline = copy.deepcopy(initial)
    baseline["citations"] = [row for row in baseline["citations"] if row["chunk_id"] in match_ids]
    baseline["status"] = "reference_baseline_missing_conditions"
    baseline["returned_chunk_count"] = len(baseline["citations"])
    baseline["context"]["complete"] = False
    (root / "00-single-passage-baseline.txt").write_text(render_report(baseline))
    baseline_checks = condition_checks(baseline["citations"], conditions)
    expanded_checks = condition_checks(initial["citations"], conditions)
    budget = service.retrieve(**arguments, max_context_chunks=1)
    (root / "00-context-budget-exceeded.txt").write_text(render_report(budget))
    cache_populated = service.retrieve(**arguments)["cache_hit"]
    prior = service.store.latest("ENG-A-001")
    service.store.put_documents(
        [
            replace(
                prior,
                version=3,
                body="# Approved D2 update\n\nRevised material and additional inspection remain required. No volume-based cost reduction is approved for the customer discount request.",
            )
        ]
    )
    stale = record("02-source-updated-index-stale")
    service.store.refresh_index()
    updated = record("03-index-refreshed")
    service.store.delete("ENG-A-001", as_of)
    deleted = record("04-deleted-before-index-refresh")
    service.store.put_documents([prior])
    replay = record("05-old-version-replayed")
    historical = service.retrieve(**{**arguments, "as_of": "2026-10-18"})
    service.store.refresh_index()
    with service.store.connect() as connection:
        remaining_chunks = connection.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id='ENG-A-001'"
        ).fetchone()[0]
    service.retrieve(**arguments)
    service.store.revoke("demo-manager-a", "CUSTOMER-A", "PROJECT-A")
    denied = False
    try:
        service.retrieve(**arguments)
    except PermissionError:
        denied = True

    def versions(step):
        return {row["document_id"]: row["version"] for row in step["citations"]}

    checks = {
        "initial_order_v3_quantity_12000_cost_1300": initial["facts"]["business_version"] == 3
        and initial["facts"]["quantity"] == 12000
        and initial["facts"]["unit_cost_cents"] == 1300,
        "initial_current_sources_only": versions(initial) == {"MAIL-A-001": 2, "ENG-A-001": 2},
        "all_four_reviewed_conditions_present": len(expanded_checks) == 4
        and all(row["covered"] for row in expanded_checks),
        "single_passage_baseline_misses_three_conditions": sum(
            row["covered"] for row in baseline_checks
        )
        == 1,
        "budget_exhaustion_is_not_silent_truncation": budget["status"] == "incomplete_context"
        and not budget["citations"]
        and not budget["context"]["complete"],
        "cache_was_populated": cache_populated,
        "stale_old_engineering_blocked": stale["status"] == "insufficient_evidence"
        and "ENG-A-001" not in versions(stale)
        and not stale["index_fresh"],
        "new_version_cited_after_refresh": updated["status"] == "ready"
        and versions(updated).get("ENG-A-001") == 3,
        "delete_blocks_stale_index": "ENG-A-001" not in versions(deleted),
        "old_replay_does_not_resurrect": "ENG-A-001" not in versions(replay),
        "historical_query_cannot_bypass_delete": all(
            row["document_id"] != "ENG-A-001" for row in historical["citations"]
        ),
        "deleted_index_chunks_removed": remaining_chunks == 0,
        "revocation_blocks_cached_evidence": denied,
    }
    result = {
        "passed": all(checks.values()),
        "checks": checks,
        "scenario": "Customer A asks for a 5 percent discount on design D2; future volume is not a signed commitment.",
        "condition_comparison": {
            "metric": "Exact source-bound coverage of four manually reviewed conditions in this synthetic discount example",
            "single_passage_baseline": {
                "coverage": sum(row["covered"] for row in baseline_checks) / len(baseline_checks),
                "checks": baseline_checks,
            },
            "bounded_document_context": {
                "coverage": sum(row["covered"] for row in expanded_checks) / len(expanded_checks),
                "checks": expanded_checks,
            },
            "context_chars": initial["context"]["returned_chars"],
            "returned_documents": initial["returned_document_count"],
            "returned_passages": initial["returned_chunk_count"],
        },
        "source_chunks": [
            {
                "document_id": doc.document_id,
                "version": doc.version,
                "customer_id": doc.customer_id,
                "status": doc.status,
                "chunks": chunk_document(doc.body),
            }
            for doc in documents
        ],
        "stages": {
            "budget_exceeded": {"status": budget["status"], "context": budget["context"]},
            "initial": initial,
            "source_updated_index_stale": stale,
            "index_refreshed": updated,
            "deleted_before_index_refresh": deleted,
            "old_version_replayed": replay,
            "revoked": {"denied": denied, "facts_returned": False},
        },
        "limits": "Logical retrieval deletion only. Retained source history and exported reports are not erased. Demo grants are not authentication. No LLM or cloud API is called.",
    }
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Walk through a discount request and RAG lifecycle boundaries"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="rag-walkthrough-", dir=args.output))
    result = review(root)
    print(
        json.dumps(
            result
            if args.full
            else {
                "passed": result["passed"],
                "checks": result["checks"],
                "report": str(root / "report.json"),
                "initial_evidence": str(root / "01-initial.txt"),
                "condition_comparison": result["condition_comparison"],
            },
            indent=2,
        )
    )
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
