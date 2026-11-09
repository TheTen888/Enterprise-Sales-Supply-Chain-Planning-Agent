import json

from langchain_core.messages import AIMessage

from agent.llm_workflow import ProposalInput, RouteDecision
from agent.runtime import RuntimeConfig
from agent.service import Service
from evaluation.eval_pipeline import evaluate
from rag.hybrid_rag import vector


class FakeSemantic:
    def encode(self, texts):
        return [vector(text) for text in texts]

    def rerank(self, query, rows):
        return rows


class FakeModel:
    def __init__(self, kind=None, bad=False):
        self.kind = kind
        self.bad = bad

    def with_structured_output(self, schema):
        return FakeModel(schema, self.bad)

    def bind_tools(self, tools):
        return FakeModel([tool.name for tool in tools], self.bad)

    def invoke(self, messages):
        content = json.loads(messages[-1].content)
        if self.kind == RouteDecision:
            prompt = content["prompt"].lower()
            return RouteDecision(
                route="direct"
                if "fob" in prompt
                else "lookup"
                if prompt.startswith("lookup ecn")
                else "quote",
                answer="FOB is a shipping term.",
            )
        if self.kind == ProposalInput:
            request = content["request"]
            checks = [
                row["result"]
                for row in content["trajectory"]
                if row.get("tool") == "check_factory_capacity"
            ]
            chosen = next((row for row in checks if row["can_fit"]), checks[0])
            return ProposalInput(
                factory_id=chosen["factory_id"],
                lead_days=14 if self.bad else max(28, chosen["process_days"]),
                unit_price_cents=max(
                    1445,
                    (request["unit_price_cents"] * (10000 - request["discount_bps"]) + 9999)
                    // 10000,
                ),
            )
        request = json.loads(messages[1].content)["request"]
        if "check_factory_capacity" in self.kind:
            calls = [
                {
                    "name": "check_factory_capacity",
                    "args": {
                        "factory_id": factory,
                        "target_quarter": request["quarter"],
                        "required_units": request["quantity"],
                    },
                    "id": f"capacity-{factory}",
                    "type": "tool_call",
                }
                for factory in ["PLANT-A", "PLANT-B"]
            ]
        else:
            calls = [
                {
                    "name": "query_bom_and_ecn",
                    "args": {"part_id": request["part_id"]},
                    "id": "facts",
                    "type": "tool_call",
                },
                {"name": "recall_customer_memory", "args": {}, "id": "memory", "type": "tool_call"},
            ]
            if "calculate_quote_constraints" in self.kind:
                calls.append(
                    {
                        "name": "calculate_quote_constraints",
                        "args": {},
                        "id": "pricing",
                        "type": "tool_call",
                    }
                )
        return AIMessage(content="", tool_calls=calls)


def live_service(service, bad=False):
    return Service(
        service.root,
        config=RuntimeConfig(mode="mock", model="test-model"),
        model=FakeModel(bad=bad),
        semantic_backend=FakeSemantic(),
    )


def test_injected_model_calls_tools_through_langgraph(service, scope):
    instance = live_service(service)
    result = instance.run("demo-manager", scope, {"prompt": "Prepare quote"})
    assert result["runtime"]["mode"] == "injected_test_model"
    assert result["runtime"]["logical_model_calls"] >= 4
    assert result["runtime"]["fallback_reason"] is None
    assert {row.get("tool") for row in result["llm_trajectory"]}.issuperset(
        {"query_bom_and_ecn", "recall_customer_memory", "check_factory_capacity"}
    )
    assert result["artifact"]["result"]["lead_days"] == 28


def test_unsafe_model_output_falls_back_and_is_not_qualified(service, scope):
    result = live_service(service, True).run("demo-manager", scope, {"prompt": "Prepare quote"})
    assert result["runtime"]["mode"] == "mock_fallback"
    assert "ToolContractError" in result["runtime"]["fallback_reason"]
    assert result["artifact"]["result"]["lead_days"] == 28


def test_direct_answer_does_not_call_tools_in_live_graph(service, scope):
    result = live_service(service).run("demo-manager", scope, {"prompt": "What is FOB?"})
    assert result["runtime"]["mode"] == "injected_test_model"
    assert result["runtime"]["logical_model_calls"] == 1
    assert result["route"] == "direct"


def test_same_thread_does_not_return_old_quote_for_direct_answer(service, scope):
    instance = live_service(service)
    instance.run("demo-manager", scope, {"prompt": "Prepare quote"}, thread_id="same")
    result = instance.run("demo-manager", scope, {"prompt": "What is FOB?"}, thread_id="same")
    assert not result.get("artifact")
    assert result["route"] == "direct"


def test_llm_23_cases_contract_suite(service):
    report = evaluate(live_service(service))
    assert report["passed"] == report["cases"] == 23
    assert report["release"]["real_llm_evaluated"] is False
    assert report["external_api_calls"] == 0
    assert report["logical_model_calls"] > 0


def test_missing_key_selects_offline_without_loading_models(service, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    instance = Service(service.root, config=RuntimeConfig(mode="auto"))
    assert instance.live_graph is None
    assert "not configured" in instance.fallback_reason


def test_failed_dependencies_are_visible_fallback(service, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    instance = Service(service.root, config=RuntimeConfig(model="unused", embedding_path=None))
    assert instance.live_graph is None
    assert "dependencies unavailable" in instance.fallback_reason
