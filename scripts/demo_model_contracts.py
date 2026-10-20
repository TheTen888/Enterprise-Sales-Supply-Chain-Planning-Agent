import argparse
import json
import tempfile
from pathlib import Path

from agents.model_evaluation import evaluate_contracts


def main():
    parser = argparse.ArgumentParser(
        description="Exercise model adapters and evaluation without model inference or network access"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="model-contracts-", dir=args.output))
    result = evaluate_contracts(destination, args.model)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "checks": result["checks"],
                "real_inference_calls": 0,
                "network_calls": 0,
                "model_quality": "not_measured",
                "deployment_allowed": result["release_gate"]["deployment_allowed"],
                "report": str(destination / "report.json"),
            },
            indent=2,
        )
    )
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
