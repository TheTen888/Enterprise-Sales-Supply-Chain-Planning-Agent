import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from agents.evaluation import evaluate_feedback
from app.eval_dashboard import make_server
from risk_model.dataset import FEATURES
from scripts.serve_showcase import open_showcase


class ShowcaseTests(unittest.TestCase):
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
        self.showcase = open_showcase(self.root / "session", self.model)
        self.addCleanup(self.showcase.close)
        self.server = make_server(self.root, port=0, showcase=self.showcase)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()

    def post(self, command, origin=None, content_type="application/json"):
        request = Request(
            self.url + "/api/showcase/actions",
            json.dumps(command).encode(),
            {"Origin": origin or self.url, "Content-Type": content_type},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def generate(self, request_id=None):
        result = self.post({"action": "generate", "request_id": request_id or uuid4().hex})
        self.showcase.worker.submit(lambda: None).result(timeout=5)
        return result["job_id"]

    def job(self, job_id):
        return next(row for row in self.showcase.state()["jobs"] if row["job_id"] == job_id)

    def test_live_session_generates_real_quote_options(self):
        job = self.job(self.generate())
        self.assertEqual(job["status"], "needs_review")
        self.assertEqual(job["draft"]["engineering"]["costing"]["total_cost_cents"], 15600000)
        self.assertEqual(job["draft"]["business"]["options"][2]["unit_price_cents"], 1445)
        self.assertFalse(self.showcase.state()["customer_send_enabled"])

    def test_duplicate_request_reuses_one_job_and_one_analysis(self):
        key = uuid4().hex
        first = self.generate(key)
        self.assertEqual(self.generate(key), first)
        self.assertEqual(len(self.showcase.state()["jobs"]), 1)
        self.assertEqual(
            [row["event"] for row in self.job(first)["trace"]].count("engineering.complete"), 1
        )

    def test_quantity_change_invalidates_approval_and_recalculates(self):
        job_id = self.generate()
        self.post({"action": "approve", "job_id": job_id, "option_id": "counteroffer"})
        revised = self.post(
            {"action": "revise", "request_id": uuid4().hex, "job_id": job_id, "quantity": 18000}
        )["job_id"]
        self.showcase.worker.submit(lambda: None).result(timeout=5)
        self.assertFalse(self.job(job_id)["approval_valid"])
        self.assertEqual(self.job(job_id)["status"], "superseded")
        self.assertEqual(self.job(revised)["status"], "needs_capacity_review")
        self.assertEqual(
            self.job(revised)["draft"]["engineering"]["risk"]["capacity_shortfall_units"], 4000
        )
        self.assertEqual(self.showcase.state()["facts"]["quantity"], 12000)
        with self.assertRaises(HTTPError) as caught:
            self.post({"action": "approve", "job_id": revised, "option_id": "counteroffer"})
        self.assertEqual(caught.exception.code, 409)

    def test_manager_feedback_and_follow_up_use_the_current_draft(self):
        job_id = self.generate()
        question = self.post({"action": "explain", "job_id": job_id, "topic": "discount_limit"})
        self.assertEqual(question["answer"]["counteroffer"]["unit_price_cents"], 1445)
        self.post(
            {
                "action": "reject",
                "job_id": job_id,
                "request_id": uuid4().hex,
                "reason_code": "commercial_context",
                "note": "Future customer volume is not signed.",
            }
        )
        job = self.job(job_id)
        self.assertEqual(job["status"], "rejected")
        self.assertEqual(job["feedback"][0]["review_status"], "pending_review")
        events = [row["event"] for row in job["trace"]]
        self.assertEqual(events.count("engineering.complete"), 1)
        self.assertEqual(events.count("manager.rejected"), 1)

    def test_actor_override_is_rejected_before_work(self):
        with self.assertRaises(HTTPError) as caught:
            self.post({"action": "generate", "request_id": uuid4().hex, "actor": "another-manager"})
        self.assertEqual(caught.exception.code, 409)
        self.assertEqual(self.showcase.state()["jobs"], [])

    def test_cross_origin_and_non_json_mutations_are_denied(self):
        command = {"action": "generate", "request_id": uuid4().hex}
        for origin, content_type in (
            ("https://outside.invalid", "application/json"),
            (self.url, "text/plain"),
        ):
            with self.subTest(origin=origin), self.assertRaises(HTTPError) as caught:
                self.post(command, origin, content_type)
            self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.showcase.state()["jobs"], [])

    def test_missing_origin_is_denied(self):
        request = Request(
            self.url + "/api/showcase/actions", b"{}", {"Content-Type": "application/json"}
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 403)

    def test_oversized_body_is_denied(self):
        request = Request(
            self.url + "/api/showcase/actions",
            b"x" * 4097,
            {"Content-Type": "application/json", "Origin": self.url},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 413)

    def test_export_contains_actual_feedback_but_no_local_paths(self):
        job_id = self.generate()
        self.post(
            {
                "action": "reject",
                "job_id": job_id,
                "request_id": uuid4().hex,
                "reason_code": "missing_evidence",
                "note": "Please verify the source conditions.",
            }
        )
        with urlopen(self.url + "/api/showcase/export", timeout=3) as response:
            result = json.load(response)
        self.assertEqual(result["jobs"][0]["feedback"][0]["reason_code"], "missing_evidence")
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(result["llm_calls"], 0)

    def test_monitor_api_has_real_session_counts_and_unmeasured_inference(self):
        self.generate()
        with urlopen(self.url + "/api/monitor", timeout=3) as response:
            result = json.load(response)
        self.assertEqual(result["jobs"], 1)
        self.assertEqual(result["real_model_calls"], 0)
        self.assertFalse(result["live_model_enabled"])
        self.assertIsNone(result["inference_call_p95_ms"])
        self.assertIsNone(result["billed_cost"])

    def test_completed_session_can_be_reopened(self):
        job_id = self.generate()
        restored = open_showcase(self.root / "session", resume=True)
        try:
            self.assertEqual(restored.state()["jobs"][0]["job_id"], job_id)
            self.assertEqual(restored.state()["jobs"][0]["draft"], self.job(job_id)["draft"])
        finally:
            restored.close()

    def test_interrupted_session_is_not_silently_replayed(self):
        config = self.showcase.workflow.config
        job_id = self.showcase.workflow.submit(
            config["actor"], config["customer_id"], config["project_id"], config["entity_id"]
        )
        self.showcase.workflow.store.claim(job_id)
        with self.assertRaisesRegex(ValueError, "unfinished worker"):
            open_showcase(self.root / "session", resume=True)

    def test_feedback_evaluation_replays_rejection_and_capacity_revision(self):
        result = evaluate_feedback(self.root / "feedback-eval", self.model)
        self.assertTrue(result["passed"])
        self.assertEqual(result["capacity_shortfall_units"], 4000)
        self.assertEqual(result["feedback"]["review_status"], "pending_review")
