import json
import math
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from integrations.settings import require_model_live


class ModelCallError(ValueError):
    def __init__(self, message, events=()):
        super().__init__(message)
        self.events = list(events)


class OllamaClient:
    def __init__(
        self,
        model="qwen2.5:7b",
        endpoint="http://127.0.0.1:11434",
        transport=None,
        allow_live=False,
    ):
        if transport is None:
            require_model_live(allow_live)
        url = urlsplit(endpoint)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.port is None
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ValueError("Ollama must use an explicit loopback HTTP endpoint")
        if not isinstance(model, str) or not model or len(model) > 100:
            raise ValueError("invalid local model name")
        self.endpoint, self.model = endpoint.rstrip("/"), model
        self.transport = transport or self._http
        self.simulated = transport is not None
        self.lock = threading.Lock()
        self.records = []
        self.options = {"temperature": 0, "seed": 17, "num_ctx": 4096, "num_predict": 512}
        tags = self.transport("/api/tags", None)
        local = next((row for row in tags.get("models", []) if row.get("name") == model), None)
        if (
            not local
            or local.get("remote_host")
            or local.get("remote_model")
            or local.get("size", 0) <= 0
            or local.get("details", {}).get("format") != "gguf"
            or len(local.get("digest", "")) != 64
        ):
            raise ValueError("an installed local GGUF model is required; no pull or cloud fallback")
        info = self.transport("/api/show", {"model": model})
        if (
            info.get("remote_host")
            or info.get("remote_model")
            or "tools" not in info.get("capabilities", [])
        ):
            raise ValueError("a local tool-capable model is required")
        self.identity = {
            "provider": "ollama_local",
            "model": model,
            "model_digest": local["digest"],
            "ollama_version": self.transport("/api/version", None).get("version"),
            "options": dict(self.options),
            "simulated": self.simulated,
        }

    def _http(self, route, payload):
        if route not in {"/api/tags", "/api/show", "/api/version", "/api/chat"}:
            raise ValueError("unsupported local model route")
        request = Request(
            self.endpoint + route,
            json.dumps(payload, allow_nan=False).encode() if payload is not None else None,
            {"Content-Type": "application/json"},
        )
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=60) as response:
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ModelCallError("local model response exceeded the limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("invalid model response")
            return result
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise ModelCallError("local model unavailable or returned an invalid response") from exc

    def chat(self, messages, *, tools=None, schema=None):
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": 0,
            "options": dict(self.options),
        }
        if tools is not None:
            body["tools"] = tools
        if schema is not None:
            body["format"] = schema
        if len(json.dumps(body).encode()) > 65536:
            raise ModelCallError("model request exceeded the context budget")
        started = time.monotonic()
        event = {
            "model": self.model,
            "model_digest": self.identity["model_digest"],
            "status": "error",
            "simulated": self.simulated,
        }
        try:
            response = self.transport("/api/chat", body)
            for key in ("prompt_eval_count", "eval_count", "load_duration", "eval_duration"):
                value = response.get(key)
                event[key] = value if type(value) is int and value >= 0 else None
            if (
                not isinstance(response.get("message"), dict)
                or response.get("done_reason") == "length"
            ):
                raise ModelCallError("model response incomplete")
            event["status"] = "ok"
            return response["message"], event
        except Exception as exc:
            event["error_type"] = type(exc).__name__
            raise ModelCallError(
                "local model call failed; no deterministic fallback", [event]
            ) from exc
        finally:
            event["wall_ms"] = round((time.monotonic() - started) * 1000, 3)
            with self.lock:
                self.records.append(dict(event))

    def metrics(self):
        with self.lock:
            rows = list(self.records)
        durations = sorted(row["wall_ms"] for row in rows)
        return {
            "model_calls": len(rows),
            "model_errors": sum(row["status"] != "ok" for row in rows),
            "prompt_tokens": sum(row.get("prompt_eval_count") or 0 for row in rows),
            "completion_tokens": sum(row.get("eval_count") or 0 for row in rows),
            "token_measurement_complete": bool(rows)
            and all(
                row.get("prompt_eval_count") is not None and row.get("eval_count") is not None
                for row in rows
            ),
            "call_p95_ms": durations[math.ceil(len(durations) * 0.95) - 1] if durations else None,
            "external_billed_api_calls": 0,
            "simulated": self.simulated,
        }
