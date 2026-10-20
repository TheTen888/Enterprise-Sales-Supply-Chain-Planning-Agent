import copy
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "data/llm-eval/contract-responses.json"


class ScriptedBedrock:
    def __init__(self, fixture=None):
        self.fixture = (
            copy.deepcopy(fixture) if fixture is not None else json.loads(FIXTURE.read_text())
        )
        if self.fixture.get("not_real_model_output") is not True:
            raise ValueError("explicitly simulated responses required")
        self.requests = []

    def converse(self, **request):
        self.requests.append(copy.deepcopy(request))
        tools = request["toolConfig"]["tools"]
        role = "engineering" if tools[0]["toolSpec"]["name"] == "read_order_facts" else "business"
        final = any(
            row["text"].startswith("Respond with only JSON matching") for row in request["system"]
        )
        if not final:
            blocks = [
                {"toolUse": {"toolUseId": f"{role}-{index}", "name": name, "input": {}}}
                for index, name in enumerate(self.fixture["tools"][role])
            ]
            return {
                "output": {"message": {"role": "assistant", "content": blocks}},
                "stopReason": "tool_use",
            }
        capacity_review = False
        for message in request["messages"]:
            for block in message["content"]:
                if "toolResult" in block:
                    result = json.loads(block["toolResult"]["content"][0]["text"])
                    if isinstance(result, dict):
                        capacity_review |= result.get(
                            "requires_capacity_review", False
                        ) or result.get("capacity", {}).get("requires_capacity_review", False)
        decision = {
            "status": "ready",
            "condition_evidence": copy.deepcopy(self.fixture["condition_evidence"]),
            "next_action": "capacity_review"
            if capacity_review
            else "preserve_requirements"
            if role == "engineering"
            else "price_options",
        }
        return {
            "output": {
                "message": {"role": "assistant", "content": [{"text": json.dumps(decision)}]}
            },
            "stopReason": "end_turn",
        }
