# Offline model integration

The default application, demonstrations and CI do not load a language model or connect to any model API. `MODEL_PROVIDER=deterministic`, `ALLOW_LIVE_SERVICES=false` and `ALLOW_LIVE_MODEL_CALLS=false` express the current operating policy. There is no live-provider switch in the showcase CLI.

## Code path

```text
Scoped ETL/RAG snapshot
  -> ModelEngineeringAgent / ModelBusinessAgent
  -> bounded tool selection
  -> approved read-only tools and deterministic calculations
  -> structured decision and eligible citations
  -> independent source, arithmetic and action checks
  -> versioned internal draft
```

`integrations/bedrock.py` translates the shared message/tool contract into `boto3.client("bedrock-runtime").converse(...)`. It carries tool-use IDs through tool results, combines adjacent content blocks, adds a JSON schema instruction and parses the result back into the shared interface. Bedrock JSON is validated in application code; the adapter does not claim that a prompt alone guarantees schema compliance. See the official [Converse reference](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html).

`integrations/ollama.py` preserves an optional local adapter with JSON-schema and tool-call request fields. It rejects non-loopback endpoints and nonlocal model metadata. The default constructor cannot contact an Ollama server. It never pulls a model and uses `keep_alive=0` in its request definition. No local inference is required or run by these repository commands. See [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) and [tool calling](https://docs.ollama.com/capabilities/tool-calling).

Both adapters require an injected fake client/transport for current tests. Any future real connection requires an explicit constructor opt-in plus both live environment gates; changing an environment variable alone cannot enable it. The optional Bedrock SDK is lazy-imported only after those checks. No key is embedded, printed or stored; future AWS access would use the SDK credential chain and an approved IAM role. SDK installation, credentials, live model compatibility and cloud deployment have not been verified here.

## Run the offline example

```bash
.venv/bin/python -m scripts.demo_model_contracts
.venv/bin/python -m scripts.verify --agents
```

The first command uses authored SDK responses to run the actual guarded two-role workflow at 12,000 and 18,000 units. The existing small numeric risk model may train locally during setup; this is not a language model. `--model RUN/model.json` reuses an existing numeric artifact. The full verifier reuses its risk artifact automatically.

The report records eight mock SDK calls and zero real inference/network calls. Seven checks cover SDK requests, response validation, all source conditions, cent arithmetic, capacity recalculation, mock-versus-real accounting and no remote calls. Missing conditions, foreign citations, unauthorized tool names, timeouts and model identity changes have additional negative unit tests. Network-forbidden tests prevent an injected contract example from accidentally connecting to a service.

## Evaluation and release decisions

The [evaluation inputs](../data/llm-eval/README.md) separate development and acceptance cases. `score_case` passes only `input` to the assessor. It compares status/action, citation support, condition recall and tool selection against separately stored expected outcomes. Rules scores can be measured offline; real model scores, latency, costs and improvement remain unmeasured. The authored fake SDK is not a competitor in that quality comparison.

`release_gate` checks contracts, real model evidence, independent label review, task success, condition recall, citation precision, refusal accuracy, unauthorized execution and latency criteria. Current real-model evidence and label review are missing, so deployment remains locked even when contract tests pass. It is a future local shadow qualification rule, not approval for customer dispatch.

## Monitoring interface

The local showcase exposes read-only `GET /api/monitor`. It derives session job states and trace counts from persisted workflow events and separates `mock_response_events` from `real_model_calls`. With no real inference, model latency, token usage and billed cost remain unmeasured instead of receiving fabricated values. Logs/traces retain draft and source bindings; raw prompts, private credentials and hidden model reasoning are not stored in these call events.

This interface is local monitoring code. CloudWatch, AgentCore observability, alarms, distributed spans and a production rollout are still target integrations. See [pilot handoff](../infra/README.md).
