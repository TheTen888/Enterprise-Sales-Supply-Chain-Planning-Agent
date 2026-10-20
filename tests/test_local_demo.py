import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.run_local import FIXTURES, load_fixture, run_demo


class LocalDemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture_copy(self):
        destination = self.root / "fixtures"
        shutil.copytree(FIXTURES, destination)
        return destination

    def test_reviewed_fixture_preserves_two_customers_and_exact_amounts(self):
        result = run_demo(self.root / "run")
        self.assertTrue(result["passed"])
        self.assertEqual(9, result["input_deliveries"])
        self.assertEqual(7, result["unique_events"])
        self.assertEqual(2, result["current_order_lines"])
        self.assertEqual(9, result["checkpoint"])
        self.assertEqual(15600000, result["current_records"][0]["extended_cost_cents"])
        self.assertEqual(4612500, result["current_records"][1]["extended_price_cents"])
        self.assertNotIn("ORDER-A002-L1", {row["entity_id"] for row in result["current_records"]})

    def test_fixture_matches_expected_state_across_batch_boundaries(self):
        for size in (1, 2, 20):
            with self.subTest(batch_size=size):
                result = run_demo(self.root / str(size), batch_size=size)
                self.assertTrue(result["passed"])
                self.assertEqual(9, result["checkpoint"])

    def test_reusing_workspace_does_not_append_or_reset_data(self):
        destination = self.root / "run"
        run_demo(destination)
        original = (destination / "report.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "fresh directory"):
            run_demo(destination)
        self.assertEqual(original, (destination / "report.json").read_bytes())

    def test_forged_customer_does_not_get_authorized_from_event(self):
        fixtures = self.fixture_copy()
        path = fixtures / "order-changes.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["customer_id"] = "CUSTOMER-B"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        result = run_demo(self.root / "run", fixtures)
        self.assertFalse(result["passed"])
        self.assertEqual(0, result["checkpoint"])
        self.assertEqual([], result["current_records"])
        self.assertTrue(result["quarantine"])

    def test_expected_output_detects_valid_but_unexpected_source_amount(self):
        fixtures = self.fixture_copy()
        path = fixtures / "order-changes.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[-1]["unit_price"] = "10.26"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        result = run_demo(self.root / "run", fixtures)
        self.assertFalse(result["passed"])
        self.assertTrue(result["checks"]["checkpoint_acknowledges_all_deliveries"])
        self.assertFalse(result["checks"]["matches_reviewed_expected_records"])

    def test_missing_fixture_or_non_synthetic_marker_fails_before_database_creation(self):
        with self.assertRaises(FileNotFoundError):
            run_demo(self.root / "run", self.root / "missing")
        self.assertFalse((self.root / "run").exists())
        fixtures = self.fixture_copy()
        path = fixtures / "scopes.json"
        value = json.loads(path.read_text())
        value["synthetic"] = False
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "synthetic"):
            run_demo(self.root / "run", fixtures)
        self.assertFalse((self.root / "run").exists())

    def test_fixture_requires_separate_unique_ownership_mapping(self):
        fixtures = self.fixture_copy()
        path = fixtures / "scopes.json"
        value = json.loads(path.read_text())
        value["ownerships"].append(value["ownerships"][0])
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "unique"):
            load_fixture(fixtures)

    def test_cli_runs_and_reports_from_directory_with_spaces(self):
        output = self.root / "demo outputs"
        result = subprocess.run(
            [sys.executable, "-m", "scripts.run_local", "--output", str(output), "--json"],
            cwd=FIXTURES.parent.parent,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertTrue((Path(report["workspace"]) / "current-records.json").is_file())

    def test_invalid_batch_size_does_not_create_output(self):
        output = self.root / "run"
        with self.assertRaisesRegex(ValueError, "positive"):
            run_demo(output, batch_size=0)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
