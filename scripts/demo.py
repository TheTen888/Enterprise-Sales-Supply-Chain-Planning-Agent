import argparse
import json
import tempfile
import time
from pathlib import Path

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.models import Fault, InjectedFailure
from pipelines.etl.pipeline import IncrementalETL
from scripts.fixtures import order_event


def environment(root: Path, count: int = 1, batch_size: int = 1000):
    source = Source(root / "source.db")
    warehouse = Warehouse(root / "warehouse.db")
    warehouse.authorize_many(
        source.name, [(f"ORDER-{index:05d}", "CUSTOMER-A", "PROJECT-A") for index in range(count)]
    )
    return source, warehouse, IncrementalETL(source, warehouse, batch_size)


def experiments(root: Path, backlog_rows: int) -> list[dict]:
    results = []
    source, warehouse, pipeline = environment(root / "01-replay")
    event = order_event("ORDER-00000")
    source.append([event])
    first = pipeline.run_once()
    before = warehouse.counts()
    pipeline.process_batch(first["batch_id"])
    assert warehouse.counts() == before
    source.append([event])
    duplicate = pipeline.run_once()
    assert duplicate["metrics"]["duplicate_events"] == 1
    assert warehouse.counts()["record_versions"] == 1
    results.append(
        {
            "experiment": "1. Replay and duplicate delivery",
            "passed": True,
            "duplicate_events": 1,
            "record_versions": 1,
        }
    )

    source, warehouse, pipeline = environment(root / "02-late")
    source.append([order_event("ORDER-00000", 3, quantity=300)])
    pipeline.run_once()
    source.append([order_event("ORDER-00000", 2, quantity=200)])
    late = pipeline.run_once()
    visible = warehouse.current("CUSTOMER-A", "PROJECT-A")[0]["event"]
    assert visible["version"] == 3 and visible["quantity"] == 300
    results.append(
        {
            "experiment": "2. Late old version",
            "passed": True,
            "visible_version": 3,
            "stale_versions": late["metrics"]["stale_versions"],
        }
    )

    source, warehouse, pipeline = environment(root / "03-scope", count=2)
    source.append([order_event("ORDER-00000")])
    pipeline.run_once()
    before = warehouse.counts()
    bad = order_event("ORDER-00001", customer_id="CUSTOMER-B", project_id="PROJECT-B")
    source.append([bad])
    rejected = pipeline.run_once()
    assert rejected["status"] == "quarantined"
    assert warehouse.cursor(source.name) == 1
    assert warehouse.counts()["active_publication"] == before["active_publication"]
    assert not warehouse.current("CUSTOMER-B", "PROJECT-B")
    results.append(
        {
            "experiment": "3. Missing or forged scope",
            "passed": True,
            "status": "quarantined",
            "checkpoint_unchanged": True,
        }
    )

    source, warehouse, pipeline = environment(root / "04-atomic", count=2)
    source.append([order_event("ORDER-00000"), order_event("ORDER-00001")])
    pipeline.run_once()
    old = warehouse.current("CUSTOMER-A", "PROJECT-A")
    old_manifest = warehouse.counts()["active_publication"]
    source.append(
        [order_event("ORDER-00000", 2, quantity=200), order_event("ORDER-00001", 2, quantity=300)]
    )
    try:
        pipeline.run_once(Fault("during_publish"))
    except InjectedFailure:
        pass
    assert warehouse.current("CUSTOMER-A", "PROJECT-A") == old
    assert warehouse.counts()["active_publication"] == old_manifest
    assert warehouse.cursor(source.name) == 2
    IncrementalETL(Source(source.path), Warehouse(warehouse.path)).run_once()
    assert all(row["event"]["version"] == 2 for row in warehouse.current("CUSTOMER-A", "PROJECT-A"))
    results.append(
        {
            "experiment": "4. Partial publication failure",
            "passed": True,
            "old_snapshot_preserved": True,
            "resumed_successfully": True,
        }
    )

    source, warehouse, pipeline = environment(
        root / "05-recovery", count=backlog_rows, batch_size=1000
    )
    source.append([order_event(f"ORDER-{index:05d}") for index in range(backlog_rows)])
    started = time.perf_counter()
    try:
        pipeline.run_once(Fault("after_publish"))
    except InjectedFailure:
        pass
    first_count = warehouse.counts()["record_versions"]
    assert warehouse.cursor(source.name) == 0
    reports = IncrementalETL(Source(source.path), Warehouse(warehouse.path), 1000).drain()
    elapsed = time.perf_counter() - started
    assert warehouse.cursor(source.name) == backlog_rows
    assert warehouse.counts()["record_versions"] == backlog_rows
    assert len(warehouse.current("CUSTOMER-A", "PROJECT-A")) == backlog_rows
    assert source.remaining(warehouse.cursor(source.name)) == 0
    results.append(
        {
            "experiment": "5. Restart and backlog recovery",
            "passed": True,
            "input_rows": backlog_rows,
            "rows_visible_before_checkpoint_recovery": first_count,
            "recovery_batches": len(reports),
            "remaining_changes": 0,
            "elapsed_seconds": round(elapsed, 4),
            "rows_per_second": round(backlog_rows / elapsed, 2),
            "measurement_scope": "Local synthetic SQLite run, including injected failure and recovery; not cloud capacity",
        }
    )
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--backlog-rows", type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.backlog_rows <= 100000:
        parser.error("backlog-rows must be in 1..100000")
    args.output.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="etl-demo-", dir=args.output))
    result = {
        "fixture_directory": str(workspace),
        "experiments": experiments(workspace, args.backlog_rows),
    }
    result["all_passed"] = all(case["passed"] for case in result["experiments"])
    (args.output / "fault-experiments.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
