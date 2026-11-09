import json
import os
import sqlite3
import time
import uuid
from contextlib import ExitStack, nullcontext
from pathlib import Path
from threading import RLock

from langgraph.checkpoint.sqlite import SqliteSaver

from agent.runtime import CountingModel, RuntimeConfig, create_model
from agent.tools import Tools
from agent.workflow import build_workflow
from config.contracts import QuoteRequest, fingerprint
from data_pipeline.ingestion import LocalIngestion
from memory.architecture import MemorySystem
from rag.hybrid_rag import HybridRAG
from rag.semantic import SemanticBackend


class Service:
    def __init__(self, root, grants=None, config=None, model=None, semantic_backend=None):
        self.root = Path(root)
        self.source = self.root / "source"
        self.root.mkdir(parents=True, exist_ok=True)
        self.ingestion = LocalIngestion(self.root / "knowledge.sqlite")
        self.config = config or RuntimeConfig.from_env()
        self.memory = MemorySystem(self.root / "memory.sqlite")
        self.resources = ExitStack()
        self.lock = RLock()
        self.fallback_reason = None
        self.model = None
        self.injected_model = model is not None
        self.checkpointer_backend = "sqlite"
        self.checkpoint_db = sqlite3.connect(
            self.root / "checkpoints.sqlite", check_same_thread=False
        )
        checkpointer = SqliteSaver(self.checkpoint_db)
        if self.config.redis_url:
            try:
                from langgraph.checkpoint.redis import RedisSaver

                checkpointer = self.resources.enter_context(
                    RedisSaver.from_conn_string(self.config.redis_url)
                )
                checkpointer.setup()
                self.checkpointer_backend = "redis"
            except Exception as exc:
                checkpointer = SqliteSaver(self.checkpoint_db)
                self.fallback_reason = f"Redis unavailable: {type(exc).__name__}"
        self.semantic_backend = semantic_backend
        live_requested = self.config.wants_llm or model is not None
        if live_requested:
            try:
                self.semantic_backend = semantic_backend or SemanticBackend(
                    self.config.embedding_path, self.config.reranker_path
                )
                self.model = CountingModel(model or create_model(self.config.model))
            except Exception as exc:
                self.fallback_reason = f"Live dependencies unavailable: {type(exc).__name__}"
        elif self.config.mode != "mock":
            self.fallback_reason = "OPENAI_API_KEY not configured"
        self.memory.semantic_backend = self.semantic_backend
        self.tools = Tools(
            self.ingestion,
            HybridRAG(self.ingestion, semantic_backend=self.semantic_backend),
            self.memory,
            self.source,
        )
        self.graph = build_workflow(self.tools, checkpointer)
        self.live_graph = None
        if self.model:
            from agent.llm_workflow import build_llm_workflow

            self.live_graph = build_llm_workflow(self.tools, checkpointer, self.model)
        self.tracing_enabled = os.getenv(
            "LANGCHAIN_TRACING_V2", "false"
        ).lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY"))
        self.grants = (
            grants if grants is not None else {"demo-manager": {("CUSTOMER-A", "PROJECT-A")}}
        )
        self.checkpoint_db.execute(
            "CREATE TABLE IF NOT EXISTS proposal_bindings (revision TEXT PRIMARY KEY, actor TEXT, scope TEXT, request TEXT, artifact_hash TEXT, inputs_hash TEXT)"
        )
        self.checkpoint_db.commit()
        self.last_result = None

    def authorize(self, actor, scope):
        if (scope.customer_id, scope.project_id) not in self.grants.get(actor, set()):
            raise PermissionError("Customer/project access denied")

    def ingest_all(self):
        manifest = json.loads((self.source / "manifest.json").read_text())
        return [self.ingestion.ingest(self.source, metadata) for metadata in manifest]

    def run(self, actor, scope, request, thread_id=None):
        started = time.perf_counter()
        self.authorize(actor, scope)
        request = QuoteRequest.model_validate(request)
        thread = fingerprint([actor, scope.key, thread_id or str(uuid.uuid4())])
        inputs = {
            "request": request.model_dump(),
            "scope": scope.model_dump(),
            "facts": {},
            "capacity": {},
            "artifact": {},
            "answer": "",
        }
        configuration = {"configurable": {"thread_id": thread}, "recursion_limit": 12}
        from langsmith import trace, tracing_context

        run_context = (
            trace(
                "sales-request",
                inputs={"request": request.model_dump()},
                metadata={"thread_id": thread},
            )
            if self.tracing_enabled
            else nullcontext(None)
        )
        with tracing_context(enabled=self.tracing_enabled), run_context as trace_run:
            mode = "mock"
            before = self.model.counter["calls"] if self.model else 0
            usage_before = dict(self.model.counter) if self.model else {}
            fallback = self.fallback_reason
            if self.live_graph:
                try:
                    context = {
                        "working": self.memory.context(scope, thread),
                        "skills": self.memory.load_skills(),
                        "facts": self.memory.retrieve_facts(scope, request.prompt),
                        "events": self.memory.recall_events(scope, request.prompt),
                    }
                    live = self.live_graph.invoke(
                        {
                            **inputs,
                            "context": context,
                            "checked": {},
                            "proposal": {},
                            "trajectory": [],
                        },
                        configuration,
                    )
                    result = live.get("checked") or {
                        "route": live["route"],
                        "answer": live["answer"],
                        "events": live["trajectory"],
                    }
                    mode = "llm" if self.config.wants_llm else "injected_test_model"
                except Exception as exc:
                    fallback = f"Live run failed: {type(exc).__name__}"
                    result = self.graph.invoke(
                        inputs,
                        {**configuration, "configurable": {"thread_id": thread + "-fallback"}},
                    )
                    mode = "mock_fallback"
            else:
                result = self.graph.invoke(inputs, configuration)
            if trace_run:
                trace_run.end(
                    outputs={
                        "route": result.get("route"),
                        "artifact": result.get("artifact"),
                        "answer": result.get("answer"),
                        "mode": mode,
                    }
                )
        result["runtime"] = {
            "mode": mode,
            "model": self.config.model if self.model else None,
            "fallback_reason": fallback,
            "logical_model_calls": (self.model.counter["calls"] - before) if self.model else 0,
            "provider_backed": self.model is not None and not self.injected_model,
            "semantic_backend": "sentence-transformers"
            if self.semantic_backend
            else "lexical-hash",
            "tracing_enabled": self.tracing_enabled,
            "trace_id": str(trace_run.id) if trace_run else None,
            "checkpointer": self.checkpointer_backend,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "usage": {
                name: self.model.counter[name] - usage_before[name]
                for name in ["input_tokens", "output_tokens", "total_tokens"]
            }
            if self.model
            else {},
        }
        if trace_run:
            trace_run.client.flush()
        artifact = result.get("artifact")
        if artifact:
            with self.checkpoint_db:
                self.checkpoint_db.execute(
                    "INSERT OR REPLACE INTO proposal_bindings VALUES (?,?,?,?,?,?)",
                    (
                        artifact["revision"],
                        actor,
                        scope.key,
                        fingerprint(request.model_dump()),
                        fingerprint(artifact),
                        self.input_fingerprint(scope),
                    ),
                )
        self.memory.add_turn(
            scope,
            thread,
            {
                "prompt": request.prompt,
                "quantity": request.quantity,
                "artifact_revision": result.get("artifact", {}).get("revision"),
                "response": result.get("answer") or result.get("artifact", {}).get("result"),
            },
        )
        self.last_result = result
        return result

    def approve(self, actor, scope, artifact, request):
        self.authorize(actor, scope)
        request = QuoteRequest.model_validate(request)
        binding = self.checkpoint_db.execute(
            "SELECT actor,scope,request,artifact_hash,inputs_hash FROM proposal_bindings WHERE revision=?",
            (artifact.get("revision"),),
        ).fetchone()
        if (
            not binding
            or artifact.get("status") != "needs_review"
            or tuple(binding)
            != (
                actor,
                scope.key,
                fingerprint(request.model_dump()),
                fingerprint(artifact),
                self.input_fingerprint(scope),
            )
        ):
            raise ValueError("Stale, blocked or altered proposal; regenerate and review")
        return {
            **artifact,
            "status": "approved",
            "approved_by": actor,
            "scope": scope.model_dump(),
            "approval_scope": "internal proposal only; no customer send or capacity reservation",
        }

    def input_fingerprint(self, scope):
        return fingerprint(
            {
                "documents": self.ingestion.current(scope),
                "capacity": json.loads((self.source / "factory_capacity.json").read_text()),
                "skills": self.memory.load_skills(),
            }
        )
