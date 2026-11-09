import json

from langchain_core.messages import AIMessage

from agent.runtime import RuntimeConfig
from agent.service import Service
from tests.test_live_mode import FakeModel, FakeSemantic


class SequentialCapacity:
    def invoke(self, messages):
        request = json.loads(messages[1].content)["request"]
        previous = {
            call["args"]["factory_id"]
            for message in messages
            if getattr(message, "tool_calls", None)
            for call in message.tool_calls
            if call["name"] == "check_factory_capacity"
        }
        factory = "PLANT-A" if "PLANT-B" in previous else "PLANT-B"
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "check_factory_capacity",
                    "args": {
                        "factory_id": factory,
                        "target_quarter": request["quarter"],
                        "required_units": request["quantity"],
                    },
                    "id": factory,
                    "type": "tool_call",
                }
            ],
        )


class SequentialModel(FakeModel):
    def bind_tools(self, tools, **kwargs):
        return (
            SequentialCapacity()
            if tools[0].name == "check_factory_capacity"
            else super().bind_tools(tools)
        )


def test_sequential_capacity_calls_cannot_stop_after_preferred_factory(service, scope):
    instance = Service(
        service.root,
        config=RuntimeConfig(mode="mock"),
        model=SequentialModel(),
        semantic_backend=FakeSemantic(),
    )
    result = instance.run(
        "demo-manager", scope, {"prompt": "Prepare quote", "preferred_factory": "PLANT-B"}
    )
    assert result["runtime"]["mode"] == "injected_test_model"
    assert {
        row["arguments"]["factory_id"]
        for row in result["llm_trajectory"]
        if row.get("tool") == "check_factory_capacity"
    } == {"PLANT-A", "PLANT-B"}
