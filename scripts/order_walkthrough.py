import argparse
import json
import tempfile
from pathlib import Path

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.extract import extract_changes
from pipelines.etl.models import Fault, InjectedFailure
from pipelines.etl.pipeline import IncrementalETL
from pipelines.etl.policy import BatchPolicy
from scripts.fixtures import order_event


def snapshot(warehouse: Warehouse, source: Source, label: str) -> dict:
    current = warehouse.current("CUSTOMER-A", "PROJECT-A")
    record = current[0] if current else None
    pending = warehouse.pending(source.name)
    return {
        "step": label,
        "checkpoint": warehouse.cursor(source.name),
        "remaining_changes": source.remaining(warehouse.cursor(source.name)),
        "pending_state": pending["state"] if pending else None,
        "visible_order": {
            "version": record["event"]["version"],
            "quantity": record["event"]["quantity"],
            "design_version": record["event"]["design_version"],
            "extended_cost_cents": record["extended_cost_cents"],
            "extended_price_cents": record["extended_price_cents"],
        }
        if record
        else None,
        "counts": warehouse.counts(),
    }


def walkthrough(root: Path) -> dict:
    source = Source(root / "source.db")
    warehouse = Warehouse(root / "warehouse.db")
    warehouse.authorize(source.name, "ORDER-001-L1", "CUSTOMER-A", "PROJECT-A")
    pipeline = IncrementalETL(source, warehouse, policy=BatchPolicy())
    source.append([order_event(quantity=10000)])
    pipeline.run_once()
    steps = [snapshot(warehouse, source, "1. Initial order published")]
    change = order_event(version=2, quantity=12000, unit_cost="13.00", design_version="D2")
    source.append([change])
    steps.append(snapshot(warehouse, source, "2. Order change appended to source"))
    lower = warehouse.cursor(source.name)
    changes = extract_changes(source, lower, 100)
    batch_id = warehouse.save_batch(source.name, lower, changes)
    pinned = snapshot(warehouse, source, "3. Exact raw input pinned before transformation")
    pinned["raw_input"] = warehouse.raw(batch_id)[0].payload
    steps.append(pinned)
    for phase, label in [
        ("after_stage", "4. Validated and staged; injected failure before publication"),
        ("during_publish", "5. Publication transaction rolled back after injected failure"),
        ("after_publish", "6. Publication committed; injected failure before checkpoint ACK"),
    ]:
        try:
            pipeline.run_once(Fault(phase))
        except InjectedFailure:
            pass
        else:
            raise RuntimeError("expected fault did not fire")
        step = snapshot(warehouse, source, label)
        with warehouse.connect() as connection:
            step["staged_candidate"] = json.loads(
                connection.execute(
                    "SELECT body FROM staged_records WHERE batch_id=? ORDER BY position LIMIT 1",
                    (batch_id,),
                ).fetchone()[0]
            )
        steps.append(step)
    resumed = IncrementalETL(Source(source.path), Warehouse(warehouse.path), policy=BatchPolicy())
    recovery = resumed.run_once()
    steps.append(snapshot(warehouse, source, "7. Fresh worker acknowledges existing publication"))
    before_replay = warehouse.counts()
    resumed.process_batch(recovery["batch_id"])
    steps.append(snapshot(warehouse, source, "8. Completed batch replay makes no changes"))
    source.append([change.copy()])
    duplicate = resumed.run_once()
    steps.append(
        snapshot(warehouse, source, "9. Duplicate delivery acknowledged without new version")
    )
    checks = {
        "staged_change_not_visible": steps[3]["visible_order"]["version"] == 1,
        "failed_transaction_preserves_old_view": steps[4]["visible_order"]["version"] == 1
        and steps[4]["counts"]["publications"] == 1,
        "published_before_ack": steps[5]["visible_order"]["version"] == 2
        and steps[5]["checkpoint"] == 1,
        "recovery_does_not_republish": steps[6]["counts"]["publications"] == 2
        and steps[6]["checkpoint"] == 2,
        "completed_replay_unchanged": steps[7]["counts"] == before_replay,
        "duplicate_has_no_extra_version": duplicate["metrics"]["duplicate_events"] == 1
        and steps[8]["counts"]["record_versions"] == 2,
        "logical_events_accounted_for": steps[8]["counts"]["processed_events"] == 2,
        "all_deliveries_acknowledged": steps[8]["checkpoint"] == 3
        and steps[8]["remaining_changes"] == 0,
        "final_amounts_correct": steps[8]["visible_order"]["extended_cost_cents"] == 15600000
        and steps[8]["visible_order"]["extended_price_cents"] == 18000000,
    }
    policy = BatchPolicy()
    return {
        "fixture_directory": str(root),
        "steps": steps,
        "checks": checks,
        "all_passed": all(checks.values()),
        "batch_policy_examples": [
            {
                "backlog": backlog,
                "previous_processing_seconds": previous,
                "selected_size": policy.select(backlog, previous)[0],
                "mode": policy.select(backlog, previous)[1],
            }
            for backlog, previous in [(50, 0), (1500, 0), (10000, 0), (10000, 0.3)]
        ],
        "scope": "Synthetic order change; batch policy inputs are illustrative. No cloud scaling or risk prediction is performed.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="order-walkthrough-", dir=args.output))
    result = walkthrough(root)
    (args.output / "order-walkthrough.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
