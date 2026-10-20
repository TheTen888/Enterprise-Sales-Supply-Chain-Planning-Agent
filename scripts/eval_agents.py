import argparse
import json
import tempfile
from pathlib import Path

from agents.evaluation import evaluate


def main():
    parser = argparse.ArgumentParser(description="Run controlled local Agent evaluation faults")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="agent-eval-", dir=args.output))
    result = evaluate(root, args.model)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "cases": result["case_count"],
                "passed_cases": result["passed_count"],
                "report": str(root / "report.json"),
            },
            indent=2,
        )
    )
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
