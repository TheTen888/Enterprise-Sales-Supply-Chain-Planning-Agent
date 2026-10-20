import json
import time

from integrations.ollama import ModelCallError
from integrations.settings import require_model_live


class BedrockClient:
    def __init__(self, model_id, region="us-east-1", sdk_client=None, allow_live=False):
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("an explicit Bedrock model ID is required")
        if sdk_client is None:
            require_model_live(allow_live)
        self.simulated = sdk_client is not None
        if sdk_client is None:
            import boto3

            sdk_client = boto3.client("bedrock-runtime", region_name=region)
        self.client, self.model = sdk_client, model_id
        self.identity = {
            "provider": "aws_bedrock",
            "model": model_id,
            "region": region,
            "simulated": self.simulated,
        }

    def chat(self, messages, *, tools=None, schema=None):
        system, converted = [], []
        for message in messages:
            if message["role"] == "system":
                system.append({"text": message["content"]})
            elif message["role"] == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": message["tool_call_id"],
                                    "content": [{"text": message["content"]}],
                                }
                            }
                        ],
                    }
                )
            else:
                blocks = [{"text": message["content"]}] if message.get("content") else []
                for call in message.get("tool_calls", []):
                    blocks.append(
                        {
                            "toolUse": {
                                "toolUseId": call["id"],
                                "name": call["function"]["name"],
                                "input": call["function"]["arguments"],
                            }
                        }
                    )
                converted.append({"role": message["role"], "content": blocks})
        merged = []
        for message in converted:
            if merged and merged[-1]["role"] == message["role"]:
                merged[-1]["content"].extend(message["content"])
            else:
                merged.append(message)
        if schema is not None:
            system.append(
                {"text": "Respond with only JSON matching this schema: " + json.dumps(schema)}
            )
        request = {
            "modelId": self.model,
            "system": system,
            "messages": merged,
            "inferenceConfig": {"temperature": 0, "maxTokens": 512},
        }
        if tools is not None:
            request["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": row["function"]["name"],
                            "description": row["function"]["description"],
                            "inputSchema": {"json": row["function"]["parameters"]},
                        }
                    }
                    for row in tools
                ]
            }
        if len(json.dumps(request).encode()) > 65536:
            raise ModelCallError("model request exceeded the context budget")
        event = {
            "model": self.model,
            "provider": "aws_bedrock",
            "simulated": self.simulated,
            "status": "error",
        }
        started = time.monotonic()
        try:
            response = self.client.converse(**request)
            if response.get("stopReason") == "max_tokens":
                raise ValueError("incomplete model response")
            blocks = response["output"]["message"]["content"]
            usage = response.get("usage", {})
            event.update(
                {
                    "status": "ok",
                    "prompt_eval_count": usage.get("inputTokens"),
                    "eval_count": usage.get("outputTokens"),
                }
            )
            return {
                "role": "assistant",
                "content": "".join(row.get("text", "") for row in blocks),
                "tool_calls": [
                    {
                        "id": row["toolUse"]["toolUseId"],
                        "function": {
                            "name": row["toolUse"]["name"],
                            "arguments": row["toolUse"]["input"],
                        },
                    }
                    for row in blocks
                    if "toolUse" in row
                ],
            }, event
        except Exception as exc:
            event["error_type"] = type(exc).__name__
            raise ModelCallError("Bedrock call failed; no silent fallback", [event]) from exc
        finally:
            event["wall_ms"] = round((time.monotonic() - started) * 1000, 3)
