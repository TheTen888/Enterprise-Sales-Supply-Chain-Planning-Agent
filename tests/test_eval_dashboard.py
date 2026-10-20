import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.evaluation import CASES, evaluate, evaluate_case
from app.eval_dashboard import make_server, snapshot
from risk_model.dataset import FEATURES


class AgentEvalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "model.json"
        self.model.write_text(
            json.dumps(
                {
                    "format": "standardized-logistic-v1",
                    "features": list(FEATURES),
                    "mean": [0] * 7,
                    "scale": [10000, 1, 1, 1, 1, 1, 1],
                    "coefficients": [0.1, 1, -0.2, 0, 0, 0, 0],
                    "intercept": -1,
                    "cutoffs": {"evaluation_as_of": "2026-02-01"},
                }
            )
        )

    def test_controlled_fault_suite_rejects_all_nine_unsafe_actions(self):
        result = evaluate(self.root / "eval", self.model)
        self.assertTrue(result["passed"])
        self.assertEqual(result["passed_count"], 9)
        self.assertTrue(all(row["observed"] == "rejected" for row in result["cases"]))
        self.assertEqual(
            {row["category"] for row in result["cases"]},
            {"Pricing", "Evidence", "Recalculation", "Access", "Approval"},
        )

    def test_disabled_guard_is_detected_as_eval_failure(self):
        with patch("agents.workflow.validate_business", return_value=None):
            result = evaluate_case(self.root / "disabled", CASES[1], self.model)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["invalid_payload_not_published"])

    def test_unrelated_exception_does_not_count_as_expected_rejection(self):
        with patch(
            "agents.workflow.validate_engineering", side_effect=ValueError("unrelated error")
        ):
            result = evaluate_case(self.root / "unrelated", CASES[0], self.model)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["expected_rejection"])

    def test_setup_error_is_reported_as_failure(self):
        result = evaluate(self.root / "missing", self.root / "missing-model.json")
        self.assertFalse(result["passed"])
        self.assertTrue(all(row["observed"] == "setup_failed" for row in result["cases"]))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "app/eval_ui").mkdir(parents=True)
        (self.root / "docs/evidence").mkdir(parents=True)
        self.source = self.root / "app/example.py"
        self.source.write_text("value = 1\n")
        (self.root / "app/eval_ui/index.html").write_text("<html lang='en'>Evaluation</html>")
        self.record = {
            "passed": True,
            "verified_at_utc": "2026-10-20T00:00:00+00:00",
            "unit_tests": {"passed": True, "count": 1, "skipped": 0},
            "source_sha256": {
                str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (self.source, self.root / "app/eval_ui/index.html")
            },
        }
        self.evidence = self.root / "docs/evidence/verification.json"
        self.evidence.write_text(json.dumps(self.record))
        self.server = make_server(self.root, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def test_snapshot_uses_one_recorded_verification(self):
        result = snapshot(self.root)
        self.assertTrue(result["freshness"]["current"])
        self.assertEqual(result["evidence"]["unit_tests"]["count"], 1)
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_source_change_invalidates_freshness(self):
        self.source.write_text("value = 2\n")
        result = snapshot(self.root)
        self.assertFalse(result["freshness"]["current"])
        self.assertIn("app/example.py", result["freshness"]["mismatched_files"])

    def test_new_source_file_is_not_hidden_from_integrity_check(self):
        (self.root / "app/new.py").write_text("value = 2\n")
        self.assertFalse(snapshot(self.root)["freshness"]["current"])

    def test_asset_change_also_invalidates_freshness(self):
        (self.root / "app/eval_ui/index.html").write_text("changed")
        self.assertFalse(snapshot(self.root)["freshness"]["current"])

    def test_fixture_change_is_not_hidden_from_integrity_check(self):
        (self.root / "data").mkdir()
        (self.root / "data/policy.json").write_text('{"minimum_margin_bps":2000}')
        result = snapshot(self.root)
        self.assertFalse(result["freshness"]["current"])
        self.assertIn("data/policy.json", result["freshness"]["mismatched_files"])

    def test_get_returns_real_evidence_and_no_cache_headers(self):
        with urlopen(self.url + "/api/evaluation", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(json.load(response)["evidence"]["unit_tests"]["count"], 1)

    def test_browser_mutations_are_not_supported(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.url + "/api/evaluation", data=b"{}", method="POST"), timeout=3)
        self.assertEqual(caught.exception.code, 405)

    def test_private_file_paths_and_traversal_are_not_served(self):
        for path in ("/.env", "/docs/evidence/verification.json", "/../model.json"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                urlopen(self.url + path, timeout=3)
            self.assertEqual(caught.exception.code, 404)

    def test_unexpected_host_header_is_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(
                Request(self.url + "/api/evaluation", headers={"Host": "outside.invalid"}),
                timeout=3,
            )
        self.assertEqual(caught.exception.code, 403)

    def test_missing_evidence_returns_unavailable_not_a_fake_pass(self):
        self.evidence.unlink()
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + "/api/evaluation", timeout=3)
        self.assertEqual(caught.exception.code, 503)

    def test_wrong_evidence_shape_returns_unavailable(self):
        self.evidence.write_text("[]")
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + "/api/evaluation", timeout=3)
        self.assertEqual(caught.exception.code, 503)

    def test_string_pass_status_cannot_be_treated_as_true(self):
        self.record["passed"] = "false"
        self.evidence.write_text(json.dumps(self.record))
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + "/api/evaluation", timeout=3)
        self.assertEqual(caught.exception.code, 503)

    def test_nonlocal_bind_is_rejected(self):
        with self.assertRaises(ValueError):
            make_server(self.root, port=0, host="0.0.0.0")
