# Memory, live inference and deployment qualification

## Run the offline acceptance

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.qualify --root runtime/studio --review-labels --http --container
```

This runs 23 business cases, Memory Eval and the actual AgentCore SDK on a temporary loopback port. Without an API key, label review stays pending and inference uses the mock workflow. Without Docker, container qualification records a missing prerequisite. Neither condition is reported as a real-model or production pass.

## Memory architecture

- **Working Memory:** LangGraph checkpoints use SQLite by default. `REDIS_URL` selects `RedisSaver` and runs `setup()`; connection failure is a visible local fallback. `ContextEditor` removes application-supplied thinking/reasoning blocks, bounds tool outputs, and drops orphan tool results. It never asks a model to expose hidden reasoning. Truncated tool results are marked for refetch before use. The confirmed facts and source documents remain outside the working prompt.
- **Episodic Memory:** SQLite stores scoped event records with occurrence and received timestamps, text and vectors. Retrieval supports time-window filters plus vector/BM25 ranking. Successful runs append the inquiry and response. This is a local vector record store, not a claim of a live Redis vector deployment.
- **Semantic Memory:** named confirmed facts have versions, sources, validity intervals and vectors. Current and point-in-time reads respect customer/project scope before ranking. Real mode uses the supplied Sentence-Transformers backend for memory search as well as document retrieval.
- **Procedural Memory:** each run loads `memory/skills/pricing.md` and `capacity.md`. These are trusted application instructions, not customer-provided documents. A changed skill invalidates previously bound approval inputs.
- **Consolidator:** each new event triggers confirmed-field extraction. Unconfirmed facts remain pending. ECN facts require engineering authority. Cosine similarity identifies repeat candidates; only the same named fact with an equivalent value is deduplicated. Different amounts or dates create a newer version, close the old validity interval, and preserve history. An out-of-order conflicting update waits for review rather than overwriting the current fact. Current engineering source data always outranks conversational memory.

The consolidator processes trusted structured event fields. It does not infer confirmation from natural-language guesses. Extending automatic text extraction requires a separate extraction schema and review policy.

Memory Eval separately measures temporal recall, contradiction resolution, and abstention on unanswerable queries. An answerable-query check prevents a system that always abstains from scoring as successful. Every rate includes a denominator. The suite covers customer preferences and engineering fact versions; it is not a long-conversation model benchmark.

## Enable real inference

Set the variables in `.env.example` in the process environment. The example file is not automatically sourced, and keys must not be committed or pasted into an issue.

Real inference requires `OPENAI_API_KEY`, an explicit `OPENAI_MODEL`, installed runtime dependencies, and existing local `EMBEDDING_MODEL_PATH` and `RERANKER_MODEL_PATH`. Install the optional `semantic` extra in a suitable environment. Model loading uses CPU, `local_files_only=True` and `trust_remote_code=False`; it does not silently download weights or start a local generative model.

The live LangGraph flow is router → QuoteAgent tool loop → CapacityAgent tool loop → structured proposal → deterministic verification. Authorized scope is injected by the service, never supplied by a model. The model cannot change the requested part, quantity or quarter in tool arguments. Dates, prices and capacity choices are checked against source facts. Lookup requests use current evidence; direct knowledge answers use no tools. Calls and fallback reasons are recorded in the report.

Without a key, `auto` chooses mock. A missing local model package/weight or failed model contract returns a visibly marked fallback. Fallback success never counts as real-model qualification. `AGENT_MODE=mock` explicitly prevents model initialization.

## Independent label review

Set `JUDGE_MODEL` to a different configured model from `OPENAI_MODEL`, then run:

```bash
.venv/bin/python -m scripts.qualify --root runtime/studio --review-labels --live
```

The judge checks each case against the controlled source facts, produces a structured verdict, and runs alongside independent arithmetic/consistency assertions. All 23 cases must pass. Review reports are bound to the dataset digest. Injected test judges, absent keys, exceptions, contradictory labels and same-model reviews cannot open the independent-model review gate.

This is an independent **model consistency review**, not independent human domain validation. A judge can still be wrong or share biases with the agent. Real business acceptance still needs expert ownership and broader unseen cases.

Set `LANGCHAIN_TRACING_V2=true` and `LANGSMITH_API_KEY` only when authorized to upload the synthetic data. Real qualification checks that the root and child runs actually exist in LangSmith; setting an environment flag alone cannot satisfy the tracing requirement. Calls may incur provider costs only in explicitly configured live mode.

## AgentCore transport and checks

`deployment/agentcore_app.py` uses the actual `BedrockAgentCoreApp` and `@app.entrypoint`. The SDK serves POST `/invocations` and GET `/ping`. Payloads pass `QuoteRequest`; malformed quantities/quarters and caller-supplied customer identifiers are rejected. Bearer credentials map to a server-side principal, followed by customer/project authorization. Local unauthenticated mode exists only for development. Production startup requires identity configuration and a real-model graph.

Responses contain `task_id`, `status`, `messages`, `artifacts` and an `a2a_task` validated by the installed A2A SDK types. This validates task data objects; it is not a full A2A JSON-RPC server or agent-card discovery endpoint. A quote awaiting manager review has `input-required` status rather than falsely claiming final approval.

The native self-check launches a real subprocess and tests the HTTP port, health response, successful invocation, invalid schema, unauthorized request and customer-scope injection. `--container` additionally builds and tests a Linux ARM64 image when Docker is available. The image's default production environment refuses an unconfigured mock runtime. Container contract checks explicitly run in local mode.

The local SQLite-backed service serializes HTTP requests. It does not provide distributed reservations or concurrent production scheduling. A live Redis deployment and distributed load tests are separate from the passing local transport test.

To verify an already deployed, authorized AWS runtime, use `--aws-runtime-arn` with an existing runtime ARN and configured AWS credentials. This makes a real cloud invocation. The response must validate as an A2A task, report live inference without fallback, and match the local implementation digest. This command does not create a runtime or deploy infrastructure.

## Gate semantics

**Local Acceptance Gate:** all local business contracts and Memory Eval pass.

**Production Gate:** local acceptance + real independent-model label review + real inference/semantic retrieval with verified traces + native HTTP/container/identity/AWS runtime evidence. Reports must match the current code and dataset digests. Missing, stale or mock evidence fails closed. A green local gate never changes the production gate into a pass.

The 23 cases are a small synthetic acceptance set. Even a fully passing qualification is limited to this tested release scope; it does not prove production business impact, calibrated recommendation quality, or safety on arbitrary customer documents.
