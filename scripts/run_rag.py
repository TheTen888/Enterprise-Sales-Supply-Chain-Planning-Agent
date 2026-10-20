import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from rag.documents import load_documents
from rag.retrieval import EvidenceService, render_report
from rag.store import KnowledgeStore
from scripts.run_local import run_demo as run_etl_demo

RAG_FIXTURES = Path(__file__).resolve().parent.parent / "data" / "rag-fixtures"
DEFAULT_QUERY = "customer price discount design D2 material inspection engineering cost change"


def prepare_demo(
    root: Path, warehouse: Path | None = None, fixtures: Path = RAG_FIXTURES
) -> tuple[EvidenceService, str]:
    documents, grants, as_of = load_documents(fixtures)
    if (root / "knowledge.db").exists():
        raise ValueError("RAG workspace already exists; use a fresh directory")
    if warehouse is not None and not warehouse.is_file():
        raise FileNotFoundError("published ETL warehouse does not exist")
    if warehouse is None:
        etl = run_etl_demo(root / "etl")
        if not etl["passed"]:
            raise RuntimeError("ETL fixture verification failed")
        warehouse = root / "etl" / "warehouse.db"
    store = KnowledgeStore(root / "knowledge.db")
    store.put_documents(documents)
    for grant in grants:
        store.grant(grant["actor"], grant["customer_id"], grant["project_id"])
    store.refresh_index()
    return EvidenceService(store, warehouse), as_of


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a local scoped RAG evidence pack without an LLM"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--warehouse", type=Path)
    parser.add_argument("--fixtures", type=Path, default=RAG_FIXTURES)
    parser.add_argument("--actor", default="demo-manager-a")
    parser.add_argument("--customer", default="CUSTOMER-A")
    parser.add_argument("--project", default="PROJECT-A")
    parser.add_argument("--entity", default="ORDER-A001-L1")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--task", choices=["quote", "lookup"], default="quote")
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--max-context-chars", type=int, default=6000)
    parser.add_argument("--max-context-chunks", type=int, default=16)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="rag-demo-", dir=args.output))
        service, as_of = prepare_demo(root, args.warehouse, args.fixtures)
        pack = service.retrieve(
            args.actor,
            args.customer,
            args.project,
            args.entity,
            args.query,
            as_of,
            args.k,
            args.task,
            max_context_chars=args.max_context_chars,
            max_context_chunks=args.max_context_chunks,
        )
    except PermissionError:
        parser.exit(3, "Access denied. No evidence or order facts returned.\n")
    except (ValueError, LookupError, OSError, TypeError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(2, f"RAG demo failed: {exc}\n")
    pack["workspace"] = str(root)
    (root / "evidence-pack.json").write_text(json.dumps(pack, indent=2) + "\n")
    (root / "evidence-report.txt").write_text(render_report(pack))
    if args.json:
        print(json.dumps(pack, indent=2))
    else:
        print(render_report(pack))
        print(f"Evidence pack: {root / 'evidence-pack.json'}")
        print(f"Readable report: {root / 'evidence-report.txt'}")
    return 0 if pack["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
