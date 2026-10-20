import argparse
import json
from pathlib import Path

from risk_model.training import score


def main():
    parser = argparse.ArgumentParser(
        description="Score numeric features with a portable local JSON model"
    )
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    model = json.loads(args.model.read_text())
    inputs = json.loads(args.input.read_text())
    results = [
        {
            "entity_id": row["entity_id"],
            "prediction_at": row["prediction_at"],
            "risk_score": score(model, row["features"]) * 100,
        }
        for row in inputs
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"rows": len(results), "output": str(args.output)}))


if __name__ == "__main__":
    main()
