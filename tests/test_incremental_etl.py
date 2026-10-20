import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.models import Fault, InjectedFailure, Record
from pipelines.etl.pipeline import IncrementalETL
from pipelines.etl.transform import transform_event
from scripts.fixtures import order_event


class IncrementalETLTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = Source(self.root / "source.db")
        self.warehouse = Warehouse(self.root / "warehouse.db")
        self.warehouse.authorize(self.source.name, "ORDER-001-L1", "CUSTOMER-A", "PROJECT-A")
        self.pipeline = IncrementalETL(self.source, self.warehouse, batch_size=2)

    def current(self):
        return self.warehouse.current("CUSTOMER-A", "PROJECT-A")

    def test_replaying_completed_batch_does_not_change_state(self):
        self.source.append([order_event()])
        report = self.pipeline.run_once()
        before = self.warehouse.counts()
        replay = self.pipeline.process_batch(report["batch_id"])
        self.assertTrue(replay["replay"])
        self.assertEqual(before, self.warehouse.counts())
        self.assertEqual("idle", self.pipeline.run_once()["status"])

    def test_duplicate_event_delivery_and_business_version(self):
        self.source.append([order_event(), order_event()])
        report = self.pipeline.run_once()
        self.assertEqual(1, report["metrics"]["duplicate_events"])
        self.source.append([order_event(event_id="different-delivery")])
        report = self.pipeline.run_once()
        self.assertEqual(1, report["metrics"]["same_versions"])
        self.assertEqual(1, self.warehouse.counts()["record_versions"])

    def test_old_version_cannot_overwrite_newer_data(self):
        self.source.append([order_event(version=3, quantity=300)])
        self.pipeline.run_once()
        self.source.append([order_event(version=2, quantity=200)])
        report = self.pipeline.run_once()
        self.assertEqual(1, report["metrics"]["stale_versions"])
        self.assertEqual(300, self.current()[0]["event"]["quantity"])

    def test_tombstone_prevents_late_resurrection(self):
        self.source.append([order_event(), order_event(version=3, operation="delete")])
        initial = self.pipeline.run_once()
        self.assertEqual([], self.current())
        self.source.append([order_event(version=2)])
        self.pipeline.run_once()
        self.assertEqual([], self.current())
        self.assertEqual(
            [], self.warehouse.current("CUSTOMER-A", "PROJECT-A", initial["publication_id"])
        )

    def test_missing_and_forged_scope_are_quarantined(self):
        for override in [
            {"project_id": None},
            {"customer_id": "CUSTOMER-B"},
            {"entity_id": "UNREGISTERED"},
        ]:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as root:
                source = Source(Path(root) / "s.db")
                warehouse = Warehouse(Path(root) / "w.db")
                warehouse.authorize(source.name, "ORDER-001-L1", "CUSTOMER-A", "PROJECT-A")
                source.append([order_event(**override)])
                result = IncrementalETL(source, warehouse).run_once()
                self.assertEqual("quarantined", result["status"])
                self.assertEqual(0, warehouse.cursor(source.name))
                self.assertEqual(0, warehouse.counts()["publications"])

    def test_one_invalid_row_blocks_the_whole_batch(self):
        self.source.append([order_event(), order_event(version=2, project_id=None)])
        self.assertEqual("quarantined", self.pipeline.run_once()["status"])
        self.assertEqual([], self.current())
        self.assertEqual(0, self.warehouse.counts()["processed_events"])

    def test_permission_change_between_validation_and_publication(self):
        self.source.append([order_event()])
        original = self.warehouse.publish

        def revoke_before_publish(batch_id, fault):
            self.warehouse.revoke(self.source.name, "ORDER-001-L1")
            return original(batch_id, fault)

        with patch.object(self.warehouse, "publish", side_effect=revoke_before_publish):
            self.assertEqual("quarantined", self.pipeline.run_once()["status"])
        self.assertEqual([], self.current())
        self.assertEqual(0, self.warehouse.cursor(self.source.name))
        self.warehouse.authorize(self.source.name, "ORDER-001-L1", "CUSTOMER-A", "PROJECT-A")
        self.assertEqual("quarantined", self.pipeline.run_once()["status"])
        self.assertEqual("completed", self.pipeline.run_once(retry_quarantined=True)["status"])

    def test_failure_inside_publish_keeps_entire_old_view(self):
        second = "ORDER-002-L1"
        self.warehouse.authorize(self.source.name, second, "CUSTOMER-A", "PROJECT-A")
        self.source.append([order_event(), order_event(second)])
        baseline = self.pipeline.run_once()
        old = self.current()
        self.source.append(
            [order_event(version=2, quantity=200), order_event(second, 2, quantity=300)]
        )
        with self.assertRaises(InjectedFailure):
            self.pipeline.run_once(Fault("during_publish"))
        self.assertEqual(old, self.current())
        self.assertEqual(2, self.warehouse.cursor(self.source.name))
        self.assertEqual(2, self.warehouse.counts()["record_versions"])
        self.pipeline.run_once()
        self.assertTrue(all(record["event"]["version"] == 2 for record in self.current()))
        self.assertEqual(
            old, self.warehouse.current("CUSTOMER-A", "PROJECT-A", baseline["publication_id"])
        )

    def test_worker_process_exit_after_publish_recovers_without_duplicate_commit(self):
        self.source.append([order_event()])
        command = [
            sys.executable,
            "-m",
            "scripts.run_batch",
            "--source",
            str(self.source.path),
            "--warehouse",
            str(self.warehouse.path),
        ]
        failed = subprocess.run(
            command + ["--fault-after", "after_publish"], capture_output=True, text=True
        )
        self.assertEqual(70, failed.returncode, failed.stderr)
        self.assertEqual(0, self.warehouse.cursor(self.source.name))
        self.assertEqual(1, self.warehouse.counts()["publications"])
        recovered = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, recovered.returncode, recovered.stderr)
        self.assertEqual("completed", json.loads(recovered.stdout)["status"])
        self.assertEqual(1, self.warehouse.counts()["publications"])
        self.assertEqual(1, self.warehouse.cursor(self.source.name))

    def test_after_stage_restart_uses_pinned_input_while_source_grows(self):
        self.source.append([order_event()])
        with self.assertRaises(InjectedFailure):
            self.pipeline.run_once(Fault("after_stage"))
        self.source.append([order_event(version=2)])
        restarted = IncrementalETL(Source(self.source.path), Warehouse(self.warehouse.path), 100)
        first = restarted.run_once()
        self.assertEqual(1, first["upper_cursor"])
        self.assertEqual(1, self.current()[0]["event"]["version"])
        restarted.run_once()
        self.assertEqual(2, self.current()[0]["event"]["version"])

    def test_invalid_numbers_are_rejected_before_publication(self):
        overrides = [
            {"quantity": True},
            {"quantity": 0.5},
            {"unit_cost": "NaN"},
            {"unit_price": "1.001"},
            {"currency": "EUR"},
        ]
        for override in overrides:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as root:
                source = Source(Path(root) / "s.db")
                warehouse = Warehouse(Path(root) / "w.db")
                warehouse.authorize(source.name, "ORDER-001-L1", "CUSTOMER-A", "PROJECT-A")
                source.append([order_event(**override)])
                self.assertEqual(
                    "quarantined", IncrementalETL(source, warehouse).run_once()["status"]
                )

    def test_corrupt_derived_amount_is_rejected(self):
        self.source.append([order_event()])

        def wrong_transform(event):
            good = transform_event(event)
            return Record(event, good.extended_cost_cents + 1, good.extended_price_cents)

        with patch("pipelines.etl.pipeline.transform_event", side_effect=wrong_transform):
            self.assertEqual("quarantined", self.pipeline.run_once()["status"])
        self.assertEqual([], self.current())

    def test_conflicting_version_rolls_back_other_new_rows(self):
        self.source.append([order_event()])
        self.pipeline.run_once()
        self.source.append([order_event(version=2), order_event(event_id="conflict", quantity=900)])
        self.assertEqual("quarantined", self.pipeline.run_once()["status"])
        self.assertEqual(1, self.warehouse.counts()["record_versions"])
        self.assertEqual(1, self.warehouse.cursor(self.source.name))

    def test_same_event_id_cannot_mean_different_changes(self):
        original = order_event()
        self.source.append([original])
        self.pipeline.run_once()
        self.source.append([order_event(version=2, event_id=original["event_id"])])
        self.assertEqual("quarantined", self.pipeline.run_once()["status"])
        self.assertEqual(1, self.warehouse.cursor(self.source.name))

    def test_multiple_sources_and_projects_are_independent(self):
        other = Source(self.root / "other.db", "other-db")
        self.warehouse.authorize(other.name, "ORDER-001-L1", "CUSTOMER-B", "PROJECT-B")
        other.append([order_event(customer_id="CUSTOMER-B", project_id="PROJECT-B")])
        IncrementalETL(other, self.warehouse).run_once()
        self.assertEqual([], self.current())
        self.assertEqual(1, len(self.warehouse.current("CUSTOMER-B", "PROJECT-B")))
        self.assertEqual(0, self.warehouse.cursor(self.source.name))

    def test_money_is_exact_integer_cents(self):
        self.source.append([order_event(quantity=3, unit_cost="0.10", unit_price="0.30")])
        self.pipeline.run_once()
        self.assertEqual(30, self.current()[0]["extended_cost_cents"])
        self.assertEqual(90, self.current()[0]["extended_price_cents"])

    def test_entity_cannot_move_to_another_customer_after_revocation(self):
        self.source.append([order_event()])
        self.pipeline.run_once()
        self.warehouse.revoke(self.source.name, "ORDER-001-L1")
        with self.assertRaises(ValueError):
            self.warehouse.authorize(self.source.name, "ORDER-001-L1", "CUSTOMER-B", "PROJECT-B")

    def test_invalid_batch_size(self):
        self.source.append([order_event()])
        with self.assertRaises(ValueError):
            IncrementalETL(self.source, self.warehouse, 0).run_once()

    def test_non_object_source_payload_is_quarantined(self):
        self.source.append([["not", "an", "event"]])
        self.assertEqual("quarantined", self.pipeline.run_once()["status"])


if __name__ == "__main__":
    unittest.main()
