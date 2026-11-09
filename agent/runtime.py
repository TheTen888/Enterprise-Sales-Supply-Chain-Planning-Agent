import os
import time
from dataclasses import dataclass

from config.environment import ROOT, load_environment


@dataclass
class RuntimeConfig:
    mode: str = "auto"
    model: str | None = None
    judge_model: str | None = None
    redis_url: str | None = None
    embedding_path: str | None = None
    reranker_path: str | None = None

    @classmethod
    def from_env(cls):
        load_environment()
        return cls(
            mode=os.getenv("AGENT_MODE", "auto"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            judge_model=os.getenv("JUDGE_MODEL", "gpt-4.1-mini"),
            redis_url=os.getenv("REDIS_URL"),
            embedding_path=os.getenv(
                "EMBEDDING_MODEL_PATH", str(ROOT / "runtime/models/embedding")
            ),
            reranker_path=os.getenv("RERANKER_MODEL_PATH", str(ROOT / "runtime/models/reranker")),
        )

    @property
    def wants_llm(self):
        return self.mode != "mock" and bool(os.getenv("OPENAI_API_KEY"))


def create_model(name):
    if not name:
        raise ValueError("Set OPENAI_MODEL explicitly for real inference")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=name, use_responses_api=True, timeout=45, max_retries=1, temperature=0)


class CountingModel:
    def __init__(self, client, counter=None):
        self.client = client
        self.counter = (
            counter
            if counter is not None
            else {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "elapsed_ms": 0.0,
            }
        )

    def with_structured_output(self, schema):
        try:
            client = self.client.with_structured_output(schema, include_raw=True)
        except TypeError:
            client = self.client.with_structured_output(schema)
        return CountingModel(client, self.counter)

    def bind_tools(self, tools, **kwargs):
        try:
            client = self.client.bind_tools(tools, **kwargs)
        except TypeError:
            client = self.client.bind_tools(tools)
        return CountingModel(client, self.counter)

    def invoke(self, messages):
        self.counter["calls"] += 1
        started = time.perf_counter()
        try:
            response = self.client.invoke(messages)
            raw = (
                response.get("raw")
                if isinstance(response, dict) and "parsed" in response
                else response
            )
            usage = getattr(raw, "usage_metadata", None) or {}
            for name in ["input_tokens", "output_tokens", "total_tokens"]:
                self.counter[name] += usage.get(name, 0)
            if isinstance(response, dict) and "parsed" in response:
                if response.get("parsing_error") or response["parsed"] is None:
                    raise ValueError("Structured model output failed validation")
                return response["parsed"]
            return response
        finally:
            self.counter["elapsed_ms"] += (time.perf_counter() - started) * 1000
