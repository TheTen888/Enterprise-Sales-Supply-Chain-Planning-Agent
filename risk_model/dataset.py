import json
import math
from collections import Counter
from datetime import date
from itertools import groupby

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.models import digest
from pipelines.etl.pipeline import IncrementalETL

FEATURES = (
    "order_quantity",
    "capacity_load_ratio",
    "schedule_slack_days",
    "recent_yield",
    "design_changes_30d",
    "allocation_utilization_ratio",
    "pickup_forecast_gap_ratio",
)


def canonical_day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("dates must use YYYY-MM-DD")
    return value


def replay(root, raw):
    for row in raw["changes"]:
        for key in ("effective_at", "observed_at", "available_at"):
            canonical_day(row[key])
    source = Source(root / "source.db")
    warehouse = Warehouse(root / "warehouse.db")
    warehouse.authorize_many(
        source.name,
        [(row["entity_id"], row["customer_id"], row["project_id"]) for row in raw["orders"]],
    )
    with warehouse.connect() as connection:
        connection.execute(
            "CREATE TABLE risk_availability (event_id TEXT PRIMARY KEY, effective_at TEXT, "
            "observed_at TEXT, available_at TEXT, publication_id INTEGER)"
        )
    pipeline = IncrementalETL(source, warehouse, batch_size=100)
    reports = []
    for available, changes in groupby(
        sorted(raw["changes"], key=lambda row: (row["available_at"], row["payload"]["event_id"])),
        key=lambda row: row["available_at"],
    ):
        changes = list(changes)
        source.append([row["payload"] for row in changes])
        batches = pipeline.drain()
        if any(batch["status"] == "quarantined" for batch in batches):
            raise ValueError("risk replay rejected by ETL")
        reports.extend(batches)
        with warehouse.connect() as connection:
            for row in changes:
                payload = row["payload"]
                published = connection.execute(
                    "SELECT publication_id FROM record_versions WHERE source=? AND entity_id=? AND version=?",
                    (source.name, payload["entity_id"], payload["version"]),
                ).fetchone()
                if published is None:
                    raise ValueError("missing ETL publication")
                connection.execute(
                    "INSERT INTO risk_availability VALUES (?, ?, ?, ?, ?)",
                    (
                        payload["event_id"],
                        row["effective_at"],
                        row["observed_at"],
                        available,
                        published[0],
                    ),
                )
    return warehouse, reports


def visible(row, prediction):
    canonical_day(prediction)
    for key in ("effective_at", "observed_at", "available_at"):
        canonical_day(row[key])
    return all(row[key] <= prediction for key in ("effective_at", "observed_at", "available_at"))


def latest(rows, prediction):
    eligible = [row for row in rows if visible(row, prediction)]
    if not eligible:
        raise ValueError("missing point-in-time source")
    versions = [row["version"] for row in eligible]
    if len(set(versions)) != len(versions):
        raise ValueError("conflicting source versions")
    return max(eligible, key=lambda row: row["version"])


def order_at(warehouse, entity, prediction):
    canonical_day(prediction)
    with warehouse.connect() as connection:
        rows = connection.execute(
            "SELECT r.body, a.effective_at, a.observed_at, a.available_at FROM record_versions r "
            "JOIN risk_availability a ON a.publication_id=r.publication_id "
            "AND a.event_id=json_extract(r.body, '$.event.event_id') "
            "WHERE r.source='internal-db' AND r.entity_id=? "
            "AND a.effective_at<=? AND a.observed_at<=? AND a.available_at<=? "
            "ORDER BY r.version DESC LIMIT 1",
            (entity, prediction, prediction, prediction),
        ).fetchall()
    if not rows:
        raise ValueError("missing point-in-time order")
    row = rows[0]
    record = json.loads(row["body"])["event"]
    if record["operation"] != "upsert":
        raise ValueError("deleted order")
    return record, {key: row[key] for key in ("effective_at", "observed_at", "available_at")}


def features_at(warehouse, raw, request):
    entity, prediction = request["entity_id"], request["prediction_at"]
    canonical_day(prediction)
    event, availability = order_at(warehouse, entity, prediction)
    plan = latest([row for row in raw["plans"] if row["entity_id"] == entity], prediction)
    for row in (event, plan):
        if any(row[key] != request[key] for key in ("customer_id", "project_id")):
            raise ValueError("ownership mismatch")
    capacity = latest(
        [
            row
            for row in raw["capacity"]
            if row["line"] == plan["line"] and row["window"] == plan["window"]
        ],
        prediction,
    )
    for value in (
        capacity["yield_window_end"],
        capacity["window_end"],
        plan["due_date"],
        plan["planned_finish"],
    ):
        canonical_day(value)
    if (
        capacity["yield_window_end"] >= prediction
        or plan["window"] != prediction
        or capacity["window_end"] < plan["due_date"]
    ):
        raise ValueError("invalid capacity measurement window")
    horizon = (date.fromisoformat(plan["due_date"]) - date.fromisoformat(prediction)).days
    if not 0 < horizon <= 30:
        raise ValueError("order outside forecast horizon")
    positive = (
        event["quantity"],
        capacity["gross_capacity"],
        plan["allocated_quarter_units"],
        plan["forecast_pickup_units"],
    )
    nonnegative = (
        capacity["committed_units"],
        plan["committed_quarter_units"],
        plan["confirmed_pickup_units"],
        plan["design_changes_30d"],
    )
    if not all(math.isfinite(value) and value > 0 for value in positive):
        raise ValueError("invalid feature denominator")
    if not all(math.isfinite(value) and value >= 0 for value in nonnegative):
        raise ValueError("invalid business measure")
    if not 0 < capacity["recent_yield"] <= 1:
        raise ValueError("invalid historical yield")
    values = [
        event["quantity"],
        capacity["committed_units"] / (capacity["gross_capacity"] * capacity["recent_yield"]),
        (date.fromisoformat(plan["due_date"]) - date.fromisoformat(plan["planned_finish"])).days,
        capacity["recent_yield"],
        plan["design_changes_30d"],
        plan["committed_quarter_units"] / plan["allocated_quarter_units"],
        max(0, plan["forecast_pickup_units"] - plan["confirmed_pickup_units"])
        / plan["forecast_pickup_units"],
    ]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("non-finite feature")
    return {
        **request,
        "features": dict(zip(FEATURES, values, strict=True)),
        "frozen_due": plan["due_date"],
        "frozen_quantity": event["quantity"],
        "line": plan["line"],
        "order_version": event["version"],
        "lineage": {"order": availability, "plan": plan, "capacity": capacity},
    }


def label_for(row, outcome, as_of):
    for value in (row["frozen_due"], outcome["closed_at"], as_of):
        canonical_day(value)
    if outcome["status"] != "completed":
        raise ValueError("censored_" + outcome["status"])
    closed = outcome["closed_at"]
    if closed <= row["frozen_due"] or closed > as_of:
        raise ValueError("unmatured_label")
    delivered = 0
    completed = None
    observed = [closed]
    for delivery in sorted(outcome["deliveries"], key=lambda item: item["date"]):
        canonical_day(delivery["date"])
        canonical_day(delivery["observed_at"])
        if (
            isinstance(delivery["quantity"], bool)
            or not isinstance(delivery["quantity"], int)
            or delivery["quantity"] <= 0
            or delivery["observed_at"] < delivery["date"]
            or delivery["observed_at"] > closed
        ):
            raise ValueError("invalid delivery ledger")
        observed.append(delivery["observed_at"])
        delivered += delivery["quantity"]
        if completed is None and delivered >= row["frozen_quantity"]:
            completed = delivery["date"]
    if completed is None:
        raise ValueError("incomplete_fulfillment")
    return int(completed > row["frozen_due"]), max(observed)


def build_dataset(warehouse, raw, config):
    rows, rejected = [], []
    outcomes = {row["entity_id"]: row for row in raw["outcomes"]}
    if len(outcomes) != len(raw["outcomes"]):
        raise ValueError("duplicate outcome records")
    requests = {(row["entity_id"], row["prediction_at"]) for row in raw["orders"]}
    if len(requests) != len(raw["orders"]):
        raise ValueError("duplicate prediction requests")
    for request in raw["orders"]:
        try:
            row = features_at(warehouse, raw, request)
            label, ready = label_for(
                row, outcomes[request["entity_id"]], config["evaluation_as_of"]
            )
            rows.append({**row, "label": label, "label_available_at": ready})
        except (ValueError, KeyError) as exc:
            rejected.append({"entity_id": request["entity_id"], "reason": str(exc)})
    return rows, rejected


def split_dataset(rows, config):
    splits = {"train": [], "validation": [], "test": []}
    purged = []
    for row in rows:
        prediction = row["prediction_at"]
        if prediction < config["validation_start"]:
            name, cutoff = "train", config["validation_start"]
        elif prediction < config["test_start"]:
            name, cutoff = "validation", config["test_start"]
        else:
            name, cutoff = "test", config["evaluation_as_of"]
        if row["label_available_at"] >= cutoff:
            purged.append(
                {
                    "entity_id": row["entity_id"],
                    "split": name,
                    "reason": "label not available before cutoff",
                }
            )
        else:
            splits[name].append(row)
    ids = [[row["entity_id"] for row in split] for split in splits.values()]
    if len(set(sum(ids, []))) != sum(map(len, ids)):
        raise ValueError("orders overlap across splits")
    for name, split in splits.items():
        if len({row["label"] for row in split}) != 2:
            raise ValueError(f"{name} requires both label classes")
    return splits, purged


def dataset_summary(splits, rejected, purged):
    return {
        "splits": {
            name: {
                "rows": len(rows),
                "late": sum(row["label"] for row in rows),
                "first_prediction": min(row["prediction_at"] for row in rows),
                "last_prediction": max(row["prediction_at"] for row in rows),
                "sha256": digest(rows),
            }
            for name, rows in splits.items()
        },
        "excluded": dict(Counter(row["reason"] for row in rejected)),
        "purged_at_boundaries": dict(Counter(row["split"] for row in purged)),
    }


def audit_dataset(raw, rows, rejected, splits, purged, config):
    lineage_ok = all(
        visible(source, row["prediction_at"]) for row in rows for source in row["lineage"].values()
    )
    checks = {
        "input_orders_accounted_for": len(rows) + len(rejected) == len(raw["orders"]),
        "split_rows_accounted_for": sum(map(len, splits.values())) + len(purged) == len(rows),
        "features_available_at_prediction": lineage_ok,
        "historical_yield_only": all(
            row["lineage"]["capacity"]["yield_window_end"] < row["prediction_at"] for row in rows
        ),
        "feature_allowlist": all(tuple(row["features"]) == FEATURES for row in rows),
        "unique_orders_across_splits": len(
            {row["entity_id"] for part in splits.values() for row in part}
        )
        == sum(map(len, splits.values())),
        "labels_available_before_fitting_cutoffs": all(
            row["label_available_at"] < config[cutoff]
            for name, cutoff in (
                ("train", "validation_start"),
                ("validation", "test_start"),
                ("test", "evaluation_as_of"),
            )
            for row in splits[name]
        ),
        "chronological_prediction_windows": all(
            row["prediction_at"] < config["validation_start"] for row in splits["train"]
        )
        and all(
            config["validation_start"] <= row["prediction_at"] < config["test_start"]
            for row in splits["validation"]
        )
        and all(row["prediction_at"] >= config["test_start"] for row in splits["test"]),
    }
    if not all(checks.values()):
        raise ValueError(
            "dataset audit failed: " + ", ".join(key for key, value in checks.items() if not value)
        )
    return checks
