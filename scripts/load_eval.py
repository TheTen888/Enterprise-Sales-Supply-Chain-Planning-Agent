import argparse
import json
import math
import tempfile
import time
from pathlib import Path

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.models import Fault, InjectedFailure, canonical
from pipelines.etl.pipeline import IncrementalETL
from pipelines.etl.policy import BatchPolicy
from scripts.fixtures import order_event


def workload(entities: int) -> list[dict]:
    changes = []
    for index in range(entities):
        entity = f"ORDER-{index:05d}"
        quantity = index % 10 + 1
        first = order_event(entity, quantity=quantity, unit_cost="1.10", unit_price="2.30")
        changes.append(first)
        if index % 10 == 0:
            changes.append(
                order_event(
                    entity,
                    3,
                    quantity=quantity + 5,
                    unit_cost="1.40",
                    unit_price="2.70",
                    design_version="D2",
                )
            )
            changes.append(
                order_event(entity, 2, quantity=quantity + 2, unit_cost="1.10", unit_price="2.30")
            )
        if index % 20 == 0:
            changes.append(order_event(entity, 4, operation="delete"))
        if index % 25 == 0:
            changes.append(first.copy())
    return changes


def full_recompute(changes: list[dict]) -> dict:
    latest = {}
    for change in changes:
        key = change["entity_id"]
        if key not in latest or change["version"] > latest[key]["version"]:
            latest[key] = change
    result = {}
    for key, row in latest.items():
        if row["operation"] == "delete":
            continue
        cost, price = (140, 270) if row["design_version"] == "D2" else (110, 230)
        result[key] = [
            row["version"],
            row["quantity"],
            cost * row["quantity"],
            price * row["quantity"],
            row["design_version"],
        ]
    return result


def evaluate_case(root: Path, label: str, entities: int, restart: bool, max_p95: float) -> dict:
    source = Source(root / label / "source.db")
    warehouse = Warehouse(root / label / "warehouse.db")
    warehouse.authorize_many(
        source.name,
        [(f"ORDER-{index:05d}", "CUSTOMER-A", "PROJECT-A") for index in range(entities)],
    )
    changes = workload(entities)
    source.append(changes)
    policy = BatchPolicy()
    pipeline = IncrementalETL(source, warehouse, policy=policy)
    failures, curve = [], [len(changes)]
    started = time.perf_counter()
    if restart:
        for phase in ["during_publish", "after_publish"]:
            try:
                pipeline.run_once(Fault(phase))
            except InjectedFailure:
                failures.append(phase)
            else:
                raise RuntimeError("configured fault did not fire")
            curve.append(source.remaining(warehouse.cursor(source.name)))
        pipeline = IncrementalETL(Source(source.path), Warehouse(warehouse.path), policy=policy)
    reports = pipeline.drain()
    elapsed = time.perf_counter() - started
    curve.extend(report["remaining_changes"] for report in reports)
    expected = full_recompute(changes)
    actual = {
        record["event"]["entity_id"]: [
            record["event"]["version"],
            record["event"]["quantity"],
            record["extended_cost_cents"],
            record["extended_price_cents"],
            record["event"]["design_version"],
        ]
        for record in warehouse.current("CUSTOMER-A", "PROJECT-A")
    }
    mismatches = [
        key for key in expected.keys() | actual.keys() if expected.get(key) != actual.get(key)
    ]
    timings = sorted(report["elapsed_seconds"] for report in reports)
    p95 = timings[math.ceil(len(timings) * 0.95) - 1] if timings else 0
    with warehouse.connect() as connection:
        actual_event_ids = {
            row[0]
            for row in connection.execute(
                "SELECT event_id FROM processed_events WHERE source=?", (source.name,)
            )
        }
        offset_counts = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT r.offset, COUNT(*) FROM raw_changes r JOIN batches b USING(batch_id) WHERE b.source=? GROUP BY r.offset",
                (source.name,),
            )
        }
    expected_event_ids = {row["event_id"] for row in changes}
    expected_offsets = set(range(1, len(changes) + 1))
    checks = {
        "matches_independent_full_recompute": not mismatches,
        "logical_event_ids_match_source": actual_event_ids == expected_event_ids,
        "source_offsets_covered_once": set(offset_counts) == expected_offsets
        and all(count == 1 for count in offset_counts.values()),
        "all_offsets_acknowledged": warehouse.cursor(source.name) == len(changes),
        "no_pending_changes": source.remaining(warehouse.cursor(source.name)) == 0,
        "logical_event_count_correct": warehouse.counts()["processed_events"]
        == len({row["event_id"] for row in changes}),
        "batch_size_bounded": all(
            report["metrics"]["input_rows"] <= policy.burst_size for report in reports
        ),
        "no_quarantine_for_valid_inputs": all(
            report["status"] == "completed" for report in reports
        ),
        "local_batch_p95_within_budget": p95 <= max_p95,
    }
    return {
        "scenario": label,
        "input_changes": len(changes),
        "expected_current_entities": len(expected),
        "actual_current_entities": len(actual),
        "mismatched_entities": mismatches,
        "event_reconciliation": {
            "expected_unique_events": len(expected_event_ids),
            "actual_unique_events": len(actual_event_ids),
            "missing_events": len(expected_event_ids - actual_event_ids),
            "unexpected_events": len(actual_event_ids - expected_event_ids),
            "missing_offsets": len(expected_offsets - offset_counts.keys()),
            "unexpected_offsets": len(offset_counts.keys() - expected_offsets),
            "offsets_stored_more_than_once": sum(count > 1 for count in offset_counts.values()),
        },
        "checks": checks,
        "passed": all(checks.values()),
        "injected_failures": failures,
        "backlog_curve": curve,
        "selected_batch_sizes": [report["batch_policy"]["selected_size"] for report in reports],
        "batch_modes": [report["batch_policy"]["mode"] for report in reports],
        "batch_count": len(reports),
        "batch_processing_p95_seconds": round(p95, 6),
        "end_to_end_drain_seconds": round(elapsed, 6),
        "input_changes_per_second": round(len(changes) / elapsed, 2),
        "average_source_payload_bytes": round(
            sum(len(canonical(row).encode()) for row in changes) / max(1, len(changes)), 2
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--max-p95-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.max_p95_seconds <= 0:
        parser.error("max-p95-seconds must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="load-eval-", dir=args.output))
    results = [
        evaluate_case(root, label, entities, restart, args.max_p95_seconds)
        for label, entities, restart in [
            ("quiet", 50, False),
            ("steady", 1500, False),
            ("burst", 10000, False),
            ("burst-restart", 5000, True),
        ]
    ]
    evidence = {
        "fixture_directory": str(root),
        "scenarios": results,
        "all_passed": all(result["passed"] for result in results),
        "local_batch_p95_budget_seconds": args.max_p95_seconds,
        "measurement_scope": "Single local SQLite worker; pre-generated small synthetic records. Fault recovery included in drain time. No network, attachments, cloud services or parallel concurrency benchmark.",
    }
    (args.output / "load-evaluation.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
