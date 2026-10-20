import argparse
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from rag.evaluation import evaluate_cases, lifecycle_experiments
from scripts.run_rag import RAG_FIXTURES, prepare_demo


def evaluate(root: Path) -> dict:
    service, as_of = prepare_demo(root / "retrieval")
    retrieval = evaluate_cases(service, as_of, RAG_FIXTURES / "eval-cases.json")
    lifecycle = lifecycle_experiments(root / "lifecycle", prepare_demo)
    result = {
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "workspace": str(root),
        "passed": retrieval["passed"] and all(row["passed"] for row in lifecycle),
        "retrieval": retrieval,
        "lifecycle": lifecycle,
        "fixture_sha256": {
            str(path.relative_to(RAG_FIXTURES)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(RAG_FIXTURES.rglob("*"))
            if path.is_file()
        },
        "scope": "Local synthetic RAG only; static demo principals, keyword retrieval, logical deletion and deterministic evidence report. No cloud services or LLM calls.",
    }
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate local retrieval and lifecycle safeguards"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="rag-eval-", dir=args.output))
    result = evaluate(root)
    summary = {
        "passed": result["passed"],
        "retrieval_cases": result["retrieval"]["case_count"],
        "mean_recall_at_k": result["retrieval"]["mean_recall_at_k"],
        "mean_precision_at_k": result["retrieval"]["mean_precision_at_k"],
        "mean_condition_coverage": result["retrieval"]["mean_condition_coverage"],
        "single_passage_baseline_condition_coverage": result["retrieval"][
            "mean_single_passage_condition_coverage"
        ],
        "lifecycle_experiments": len(result["lifecycle"]),
        "report": str(root / "report.json"),
        "scope": result["scope"],
    }
    print(json.dumps(result if args.full else summary, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
