import argparse
import json
import tempfile
from pathlib import Path

from pipelines.etl.models import digest
from risk_model.dataset import (
    audit_dataset,
    build_dataset,
    dataset_summary,
    features_at,
    replay,
    split_dataset,
)
from risk_model.fixtures import generate
from risk_model.training import evaluate, score, select_model

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "data/risk-fixtures/scenario.json"


def run(root, config):
    raw = generate(config)
    (root / "synthetic-input.json").write_text(json.dumps(raw, indent=2) + "\n")
    warehouse, batches = replay(root, raw)
    rows, rejected = build_dataset(warehouse, raw, config)
    splits, purged = split_dataset(rows, config)
    prediction_rows = [
        features_at(warehouse, raw, request)
        for request in raw["orders"]
        if request["prediction_at"] >= config["test_start"]
    ]
    pipeline, model, candidates = select_model(splits["train"], splits["validation"])
    model["cutoffs"] = {
        key: config[key] for key in ("validation_start", "test_start", "evaluation_as_of")
    }
    report = {
        "scope": "Local synthetic delivery-risk prototype; existing ETL replay, no live cloud service",
        "config": config,
        "raw_sha256": digest(raw),
        "etl": {"batches": len(batches), "counts": warehouse.counts()},
        "dataset": dataset_summary(splits, rejected, purged),
        "audit": audit_dataset(raw, rows, rejected, splits, purged, config),
        "selection": candidates,
        "evaluation": evaluate(pipeline, model, splits, config["alert_fraction"], prediction_rows),
    }
    example = next(row for row in splits["test"] if row["entity_id"] == "ORDER-41-05")
    report["example"] = {
        **example,
        "risk_score": score(model, example["features"]) * 100,
        "outcome": next(row for row in raw["outcomes"] if row["entity_id"] == example["entity_id"]),
        "ignored_later_plan": next(
            row
            for row in raw["plans"]
            if row["entity_id"] == example["entity_id"] and row["version"] == 2
        ),
    }
    report["review_decision"] = (
        "Keep rules as baseline; synthetic ranking metrics alone do not justify production model promotion"
    )
    for name, value in (
        ("dataset", {"splits": splits, "excluded": rejected, "purged": purged}),
        (
            "scoring-input",
            [
                {key: row[key] for key in ("entity_id", "prediction_at", "features")}
                for row in prediction_rows
            ],
        ),
        ("model", model),
        ("report", report),
        (
            "scores",
            [
                {
                    "entity_id": row["entity_id"],
                    "prediction_at": row["prediction_at"],
                    "risk_score": 100 * score(model, row["features"]),
                }
                for row in prediction_rows
            ],
        ),
    ):
        (root / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Train and evaluate a local synthetic delivery-risk model"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="risk-model-", dir=args.output))
    report = run(destination, json.loads(CONFIG.read_text()))
    print(
        json.dumps(
            {
                "report": str(destination / "report.json"),
                "dataset": report["dataset"],
                "evaluation": report["evaluation"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
