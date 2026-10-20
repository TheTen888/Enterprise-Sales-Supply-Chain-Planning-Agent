import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipelines.etl.pipeline import IncrementalETL
from scripts.load_eval import evaluate_case


class LoadEvaluationTests(unittest.TestCase):
    def test_mixed_changes_match_baseline_and_all_source_deliveries(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = evaluate_case(Path(temporary), "valid", 20, False, 30)
            self.assertTrue(result["passed"])
            self.assertEqual(0, result["event_reconciliation"]["missing_events"])
            self.assertEqual(0, result["event_reconciliation"]["missing_offsets"])

    def test_same_event_count_does_not_hide_missing_identity(self):
        original = IncrementalETL.drain

        def corrupt_event_identity(worker):
            reports = original(worker)
            with worker.warehouse.transaction() as connection:
                connection.execute(
                    "UPDATE processed_events SET event_id='UNEXPECTED' WHERE event_id='ORDER-00001-v1'"
                )
            return reports

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(IncrementalETL, "drain", corrupt_event_identity),
        ):
            result = evaluate_case(Path(temporary), "corrupt-event", 2, False, 30)
            self.assertTrue(result["checks"]["logical_event_count_correct"])
            self.assertTrue(result["checks"]["matches_independent_full_recompute"])
            self.assertFalse(result["checks"]["logical_event_ids_match_source"])
            self.assertFalse(result["passed"])
            self.assertEqual(1, result["event_reconciliation"]["missing_events"])
            self.assertEqual(1, result["event_reconciliation"]["unexpected_events"])

    def test_completed_checkpoint_does_not_hide_missing_raw_delivery(self):
        original = IncrementalETL.drain

        def remove_raw_delivery(worker):
            reports = original(worker)
            with worker.warehouse.transaction() as connection:
                connection.execute("DELETE FROM raw_changes WHERE offset=1")
            return reports

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(IncrementalETL, "drain", remove_raw_delivery),
        ):
            result = evaluate_case(Path(temporary), "corrupt-raw", 2, False, 30)
            self.assertTrue(result["checks"]["all_offsets_acknowledged"])
            self.assertFalse(result["checks"]["source_offsets_covered_once"])
            self.assertEqual(1, result["event_reconciliation"]["missing_offsets"])
            self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
