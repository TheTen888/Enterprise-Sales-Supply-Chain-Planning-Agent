import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.pipeline import IncrementalETL

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"


def load_fixture(directory: Path) -> tuple[str, list[tuple], list[dict], dict]:
    scope = json.loads((directory / "scopes.json").read_text())
    expected = json.loads((directory / "expected-current.json").read_text())
    if scope.get("format_version") != 1 or expected.get("format_version") != 1:
        raise ValueError("unsupported fixture format")
    if scope.get("synthetic") is not True:
        raise ValueError("only explicitly synthetic fixtures are accepted")
    source = scope["source"]
    if not isinstance(source, str) or not source.strip() or source != source.strip():
        raise ValueError("fixture source must be non-empty trimmed text")
    ownerships = [
        (row["entity_id"], row["customer_id"], row["project_id"])
        for row in scope["ownerships"]
    ]
    if not ownerships or len({row[0] for row in ownerships}) != len(ownerships):
        raise ValueError("fixture ownerships must have unique entity identifiers")
    changes = [
        json.loads(line)
        for line in (directory / "order-changes.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if not changes:
        raise ValueError("fixture changes must not be empty")
    return source, ownerships, changes, expected


def current_records(warehouse: Warehouse, ownerships: list[tuple]) -> list[dict]:
    records = []
    fields = (
        "source",
        "entity_id",
        "customer_id",
        "project_id",
        "version",
        "currency",
        "quantity",
        "unit_cost_cents",
        "unit_price_cents",
        "design_version",
    )
    for customer, project in sorted({(row[1], row[2]) for row in ownerships}):
        for record in warehouse.current(customer, project):
            value = {key: record["event"][key] for key in fields}
            value["extended_cost_cents"] = record["extended_cost_cents"]
            value["extended_price_cents"] = record["extended_price_cents"]
            records.append(value)
    return sorted(records, key=lambda row: (row["source"], row["entity_id"]))


def run_demo(root: Path, fixtures: Path = FIXTURES, batch_size: int = 3) -> dict:
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch-size must be a positive integer")
    source_name, ownerships, changes, expected = load_fixture(fixtures)
    if any((root / name).exists() for name in ("source.db", "warehouse.db", "report.json")):
        raise ValueError("demo workspace already contains a run; use a fresh directory")
    root.mkdir(parents=True, exist_ok=True)
    source = Source(root / "source.db", source_name)
    warehouse = Warehouse(root / "warehouse.db")
    warehouse.authorize_many(source_name, ownerships)
    source.append(changes)
    worker = IncrementalETL(source, warehouse, batch_size)
    batches = worker.drain()
    actual = current_records(warehouse, ownerships)
    with warehouse.connect() as connection:
        event_ids = {
            row[0]
            for row in connection.execute(
                "SELECT event_id FROM processed_events WHERE source=?", (source_name,)
            )
        }
        offsets = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT r.offset, COUNT(*) FROM raw_changes r JOIN batches b USING(batch_id) WHERE b.source=? GROUP BY r.offset",
                (source_name,),
            )
        }
        quarantine = [dict(row) for row in connection.execute("SELECT * FROM quarantine")]
    counts = warehouse.counts()
    idle = worker.run_once()
    expected_events = set(expected["unique_event_ids"])
    expected_offsets = set(range(1, len(changes) + 1))
    checks = {
        "matches_reviewed_expected_records": actual == expected["current_records"],
        "fixture_delivery_count_matches": len(changes) == expected["input_deliveries"],
        "fixture_event_ids_match": {row["event_id"] for row in changes} == expected_events,
        "logical_event_ids_match": event_ids == expected_events,
        "source_offsets_covered_once": set(offsets) == expected_offsets
        and all(count == 1 for count in offsets.values()),
        "checkpoint_acknowledges_all_deliveries": warehouse.cursor(source_name) == len(changes),
        "all_batches_completed": bool(batches)
        and all(batch["status"] == "completed" for batch in batches),
        "no_quarantine": not quarantine,
        "drained_worker_is_idle": idle["status"] == "idle" and warehouse.counts() == counts,
    }
    result = {
        "format_version": 1,
        "workspace": str(root),
        "source": source_name,
        "input_deliveries": len(changes),
        "unique_events": len(event_ids),
        "current_order_lines": len(actual),
        "checkpoint": warehouse.cursor(source_name),
        "counts": counts,
        "current_records": actual,
        "batches": batches,
        "quarantine": quarantine,
        "checks": checks,
        "passed": all(checks.values()),
        "fixture_sha256": {
            name: hashlib.sha256((fixtures / name).read_bytes()).hexdigest()
            for name in ("scopes.json", "order-changes.jsonl", "expected-current.json")
        },
        "scope": "Local synthetic incremental ETL only; no model, cloud connection or external API",
    }
    (root / "current-records.json").write_text(json.dumps(actual, indent=2) + "\n")
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic two-customer ETL example")
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("batch-size must be positive")
    try:
        load_fixture(args.fixtures)
        args.output.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="local-demo-", dir=args.output))
        result = run_demo(workspace, args.fixtures, args.batch_size)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        parser.exit(2, f"Demo failed: {exc}\n")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Local ETL demo: " + ("PASS" if result["passed"] else "FAIL"))
        print(
            f"{result['input_deliveries']} deliveries -> {result['unique_events']} unique events"
            f" -> {result['current_order_lines']} current order lines"
        )
        for row in result["current_records"]:
            cost = row["extended_cost_cents"]
            price = row["extended_price_cents"]
            print(
                f"{row['customer_id']} / {row['entity_id']} / v{row['version']}"
                f" / quantity {row['quantity']:,}"
                f" / cost USD {cost // 100:,}.{cost % 100:02d}"
                f" / price USD {price // 100:,}.{price % 100:02d}"
            )
        for name, passed in result["checks"].items():
            print(f"{'PASS' if passed else 'FAIL'} {name}")
        print(f"Report: {workspace / 'report.json'}")
        print(f"Published rows: {workspace / 'current-records.json'}")
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
