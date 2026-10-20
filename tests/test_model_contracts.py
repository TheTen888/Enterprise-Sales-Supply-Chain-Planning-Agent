import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.assessment import AssessmentError, ModelAssessor, RulesAssessor, ToolContext
from agents.llm_roles import ModelBusinessAgent, ModelEngineeringAgent
from agents.model_evaluation import evaluate_contracts, load_cases, release_gate, score_case
from app.monitoring import session_metrics
from integrations.bedrock import BedrockClient
from integrations.model_mock import ScriptedBedrock
from integrations.ollama import OllamaClient
from risk_model.dataset import FEATURES
from scripts.release_check import example_findings
from scripts.run_agents import prepare


class ModelContractTests(unittest.TestCase):
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

    def workflow(self, sdk=None):
        workflow, config = prepare(self.root / "flow", self.model)
        sdk = sdk or ScriptedBedrock()
        client = BedrockClient("offline-contract-model", sdk_client=sdk)
        workflow.engineering, workflow.business = (
            ModelEngineeringAgent(client),
            ModelBusinessAgent(client),
        )
        return workflow, config, sdk

    def submit(self, workflow, config):
        return workflow.submit(
            *[config[key] for key in ("actor", "customer_id", "project_id", "entity_id")]
        )

    def test_default_adapters_cannot_connect_or_initialize_cloud_credentials(self):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("socket.create_connection", side_effect=AssertionError("network forbidden")),
        ):
            with self.assertRaises(PermissionError):
                OllamaClient()
            with self.assertRaises(PermissionError):
                BedrockClient("explicit-model")

    def test_environment_flags_alone_do_not_enable_a_model(self):
        with patch.dict(
            "os.environ", {"ALLOW_LIVE_SERVICES": "true", "ALLOW_LIVE_MODEL_CALLS": "true"}
        ):
            with self.assertRaises(PermissionError):
                BedrockClient("explicit-model")

    def test_release_template_must_keep_model_calls_disabled(self):
        findings = example_findings("ALLOW_LIVE_SERVICES=false\nALLOW_LIVE_MODEL_CALLS=true\n")
        self.assertIn("live_model_calls_not_disabled", {row["rule"] for row in findings})

    def test_explicit_flag_still_requires_both_environment_gates(self):
        with patch.dict(
            "os.environ", {"ALLOW_LIVE_SERVICES": "true", "ALLOW_LIVE_MODEL_CALLS": "false"}
        ):
            with self.assertRaises(PermissionError):
                OllamaClient(allow_live=True)
            with self.assertRaises(PermissionError):
                BedrockClient("explicit-model", allow_live=True)

    def test_fake_bedrock_round_trip_preserves_tools_and_never_counts_as_inference(self):
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            workflow, config, sdk = self.workflow()
            job_id = self.submit(workflow, config)
            result = workflow.run(config["actor"], job_id)
        self.assertEqual(result["draft"]["mode"], "mock_guarded_two_role_workflow")
        self.assertEqual(result["draft"]["llm_calls"], 0)
        self.assertEqual(result["draft"]["mock_model_calls"], 4)
        self.assertEqual(len(sdk.requests), 4)
        self.assertEqual(sdk.requests[0]["modelId"], "offline-contract-model")
        self.assertEqual(
            sdk.requests[0]["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"][
                "properties"
            ],
            {},
        )
        final = sdk.requests[1]
        self.assertEqual([row["role"] for row in final["messages"]], ["user", "assistant", "user"])
        tool_uses = {
            row["toolUse"]["toolUseId"]
            for row in final["messages"][1]["content"]
            if "toolUse" in row
        }
        results = {
            row["toolResult"]["toolUseId"]
            for row in final["messages"][2]["content"]
            if "toolResult" in row
        }
        self.assertEqual(tool_uses, results)

    def test_contract_suite_and_quality_report_keep_model_quality_unmeasured(self):
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            result = evaluate_contracts(self.root / "suite", self.model)
        self.assertTrue(result["passed"])
        self.assertEqual(result["mock_sdk_calls"], 8)
        self.assertEqual(result["real_inference_calls"], 0)
        self.assertIsNone(result["splits"]["holdout"]["model_task_success"])
        self.assertFalse(result["release_gate"]["deployment_allowed"])

    def test_missing_condition_blocks_publication_and_business_handoff(self):
        sdk = ScriptedBedrock()
        sdk.fixture["condition_evidence"].pop()
        workflow, config, _ = self.workflow(sdk)
        job_id = self.submit(workflow, config)
        with self.assertRaises(AssessmentError):
            workflow.run(config["actor"], job_id)
        self.assertIsNone(workflow.store.get(job_id)["payload"])
        events = [row["event"] for row in workflow.store.trace(job_id)]
        self.assertNotIn("business.complete", events)
        self.assertEqual(events.count("model.call"), 2)

    def test_unknown_tool_is_denied_before_execution(self):
        sdk = ScriptedBedrock()
        sdk.fixture["tools"]["engineering"][0] = "send_customer_quote"
        workflow, config, _ = self.workflow(sdk)
        job_id = self.submit(workflow, config)
        with self.assertRaises(AssessmentError):
            workflow.run(config["actor"], job_id)
        self.assertEqual(workflow.store.get(job_id)["status"], "failed")
        self.assertEqual(len(sdk.requests), 1)

    def test_wrong_customer_citation_cannot_reach_a_draft(self):
        sdk = ScriptedBedrock()
        sdk.fixture["condition_evidence"][0]["citation_id"] = "CUSTOMER-B:private"
        workflow, config, _ = self.workflow(sdk)
        with self.assertRaises(AssessmentError):
            workflow.run(config["actor"], self.submit(workflow, config))

    def test_provider_failure_does_not_fall_back_to_success(self):
        sdk = ScriptedBedrock()
        workflow, config, _ = self.workflow(sdk)
        job_id = self.submit(workflow, config)
        with patch.object(sdk, "converse", side_effect=TimeoutError):
            with self.assertRaises(AssessmentError):
                workflow.run(config["actor"], job_id)
        job = workflow.store.get(job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIsNone(job["payload"])

    def test_out_of_scope_request_is_denied_before_model_access(self):
        case = next(
            row
            for row in load_cases("holdout")["cases"]
            if row["category"] == "cross_customer_preflight"
        )
        sdk = ScriptedBedrock()
        result = ModelAssessor(BedrockClient("offline-contract-model", sdk_client=sdk)).assess(
            case["input"]
        )
        self.assertEqual(result["decision"]["status"], "refuse")
        self.assertEqual(sdk.requests, [])

    def test_another_project_is_denied_before_model_access(self):
        task = copy.deepcopy(load_cases("development")["cases"][0]["input"])
        task["requested_project_id"] = "ANOTHER-PROJECT"
        sdk = ScriptedBedrock()
        result = ModelAssessor(BedrockClient("offline-contract-model", sdk_client=sdk)).assess(task)
        self.assertEqual(result["decision"]["status"], "refuse")
        self.assertEqual(sdk.requests, [])

    def test_deleted_latest_version_and_other_customer_are_not_tool_visible(self):
        cases = load_cases("holdout")["cases"]
        deleted = next(row for row in cases if row["category"] == "deleted_latest")
        self.assertNotIn(
            "DOC-3", {row["document_id"] for row in ToolContext(deleted["input"]).documents}
        )
        other = next(row for row in cases if row["category"] == "distractor_customer")
        self.assertNotIn(
            "OTHER", {row["document_id"] for row in ToolContext(other["input"]).documents}
        )

    def test_gold_annotations_are_not_passed_to_the_assessor(self):
        case = load_cases("development")["cases"][0]
        seen = []

        class Spy(RulesAssessor):
            def assess(self, task, overrides=None):
                seen.append(copy.deepcopy(task))
                return super().assess(task, overrides)

        self.assertTrue(score_case(Spy(), case)["passed"])
        self.assertNotIn("expected", seen[0])
        self.assertNotIn("case_id", seen[0])
        self.assertNotIn("split", seen[0])

    def test_development_and_holdout_ids_do_not_overlap(self):
        development, holdout = load_cases("development"), load_cases("holdout")
        self.assertEqual((len(development["cases"]), len(holdout["cases"])), (4, 16))
        self.assertFalse(
            {row["case_id"] for row in development["cases"]}
            & {row["case_id"] for row in holdout["cases"]}
        )
        self.assertEqual(holdout["annotation"]["human_review_status"], "pending")

    def test_passing_mock_contracts_cannot_open_the_release_gate(self):
        result = release_gate(True, "pending")
        self.assertFalse(result["deployment_allowed"])
        self.assertFalse(result["checks"]["real_model_evaluation_available"])
        self.assertFalse(result["checks"]["independent_human_labels_reviewed"])

    def test_nan_and_impossible_quality_values_cannot_qualify(self):
        for value in (float("nan"), float("inf"), 1.5, True):
            report = {"real_inference": True, "model_calls": 4, "task_success": value}
            self.assertFalse(release_gate(True, "approved", report)["checks"]["task_success"])

    def test_runtime_model_change_invalidates_an_existing_approval(self):
        workflow, config, _ = self.workflow()
        actor = config["actor"]
        job_id = self.submit(workflow, config)
        workflow.run(actor, job_id)
        workflow.approve(actor, job_id, "counteroffer")
        workflow.engineering.identity = {
            **workflow.engineering.identity,
            "model": "different-model",
        }
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            workflow.read(actor, job_id)

    def test_monitor_counts_mock_events_without_fake_latency_or_tokens(self):
        workflow, config, _ = self.workflow()
        job_id = self.submit(workflow, config)
        workflow.run(config["actor"], job_id)
        metrics = session_metrics(workflow, config["actor"])
        self.assertEqual(metrics["mock_response_events"], 4)
        self.assertEqual(metrics["real_model_calls"], 0)
        self.assertIsNone(metrics["inference_call_p95_ms"])
        self.assertIsNone(metrics["completion_tokens"])
        self.assertIsNone(metrics["billed_cost"])

    def test_tool_arguments_cannot_override_the_authorized_scope(self):
        task = load_cases("development")["cases"][0]["input"]
        context = ToolContext(task)
        with self.assertRaises(AssessmentError):
            context.call("engineering", "read_order_facts", {"customer_id": "CUSTOMER-B"})
        self.assertFalse(context.events[0]["executed"])

    def test_ollama_transport_is_injected_without_server_or_model_loading(self):
        requests = []

        def transport(route, payload):
            requests.append((route, payload))
            if route == "/api/tags":
                return {
                    "models": [
                        {
                            "name": "offline-fixture",
                            "size": 1,
                            "digest": "0" * 64,
                            "details": {"format": "gguf"},
                        }
                    ]
                }
            if route == "/api/show":
                return {"capabilities": ["tools"]}
            if route == "/api/version":
                return {"version": "offline-fixture"}
            return {"message": {"role": "assistant", "content": "{}"}, "done_reason": "stop"}

        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            client = OllamaClient("offline-fixture", transport=transport)
            _, event = client.chat(
                [{"role": "user", "content": "fixture"}], schema={"type": "object"}
            )
        self.assertTrue(event["simulated"])
        self.assertEqual(requests[-1][1]["keep_alive"], 0)
        self.assertEqual(requests[-1][1]["format"], {"type": "object"})

    def test_ollama_cloud_or_remote_endpoint_is_rejected(self):
        with self.assertRaises(ValueError):
            OllamaClient("fixture", endpoint="https://outside.invalid", transport=lambda *_: {})
        with self.assertRaises(ValueError):
            OllamaClient("fixture", transport=lambda *_: {"models": []})
