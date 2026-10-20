# Local Evaluation Studio

v0.3 adds a read-only browser UI over actual verification evidence. It uses English labels, translucent panels, responsive navigation and expandable evidence. It makes no remote requests and does not start paid services.

## Run

From the repository root, with the existing local test and risk dependencies installed:

```bash
.venv/bin/python -m scripts.verify --agents
.venv/bin/python -m scripts.serve_eval --port 8768
```

Open [Evaluation Studio](http://127.0.0.1:8768/#overview). The server binds only to loopback. Stop it with Ctrl-C. Refresh reloads recorded results; it does not rerun evaluation. Export downloads the same evaluation snapshot as JSON.

To repeat only the controlled Agent Eval suite, reuse the model path printed by the Risk Model or Multi-Agent demo:

```bash
.venv/bin/python -m scripts.eval_agents --model RUN/model.json
```

This produces a separate runtime report. Run full verification to refresh the dashboard's central snapshot.

## Six review views

| View | What it demonstrates |
|---|---|
| Overview | Actual test counts and the original versus revised quote, cost and shared-capacity checks |
| Agent Eval | Five business-focused categories, nine controlled failures and a compact manager-feedback result; assertions and model-contract details expand on demand |
| Data & RAG | ETL recovery and independent reconciliation, document-level precision/recall, source-condition coverage and lifecycle checks |
| Risk Model | Chronological holdout, equal alert budgets, pending labels, leakage audits and the honest rules comparison |
| Run Traces | Workflow event sequence beside a readable order/revision summary; input checksums and raw JSON are collapsed technical details |
| Release Gates | Separate local verification, business approval and production-model decisions |

All metrics come from the central `docs/evidence/verification.json`, including its embedded subreports. The verification writer replaces that file atomically after the complete run succeeds. The UI does not mix reports from different verification runs. Source, UI asset and fixture hashes identify changed or added inputs; stale evidence gets an explicit warning. This is a freshness check, not a cryptographic attestation or CI signature.

## What Agent Eval checks

The evaluator deliberately changes engineering cost, quote revenue or a required condition; updates a document or published order after drafting; attempts approval despite a capacity gap; revokes access; changes customer scope; and tampers with the saved proposal. Each experiment starts in its own fresh local workspace and reuses a frozen numeric model.

A separate manager-feedback experiment rejects the initial draft with a reason, verifies the immutable draft/source binding, blocks approval and recomputes an 18,000-unit revision with a 4,000-unit capacity gap. Its seven checks are available under the feedback disclosure in Agent Eval. The note stays pending independent review; this is feedback-lifecycle correctness, not proof that the manager's claim is true.

An expected rejection counts as a guard passing only when its reason, draft state and publication/approval checks match. An unrelated exception is not a successful rejection. A negative test disables a guard and proves that the evaluator then fails. These nine cases supplement the 14 runnable Multi-Agent scenario invariants and workflow unit tests.

For the quantity change from 12,000 to 18,000, the original approval becomes superseded, quote totals are recomputed and a 4,000-unit shared-line capacity gap blocks approval. The ETL order stays at 12,000; a manager what-if does not create a customer commitment.

## Presentation hierarchy

Each view leads with the question, key result and business consequence. Detailed assertions, ranking metrics, case evidence and model-contract checks expand only when needed. Failures remain visible in category counts and result badges even when their details are closed.

Run Traces preserves the workflow event sequence and shows the customer/project, quantity, source versions, retrieved passages, counteroffer, capacity gap and review status. Selecting a step opens a readable event result. Fingerprints remain available under Technical details; complete JSON stays collapsed in the evidence drawer. The stored evidence, export and checks are unchanged.

## Boundaries

- These are deterministic fixture evaluations, not measured LLM hallucination rates or general chatbot quality. No LLM or external API is called; the local ML scorer does run.
- The model remains unpromoted because observed recall does not beat rules at the same alert budget. Higher ranking metrics alone do not change that decision.
- Stored sequence IDs are not span durations. Fault-case durations include local setup; they are not production request latency. There is no live token billing, distributed tracing or CloudWatch integration.
- The UI cannot approve, send, rerun tests, deploy, commit or push. It serves only explicit assets and the evaluation API; private files and arbitrary paths are unavailable. Loopback binding and Host checks do not replace production authentication.
- Recorded evidence and exported snapshots contain invented data. Generated databases, model artifacts and screenshots remain outside the release manifest.
- Local green checks do not establish that the current commit passed hosted GitHub CI. Production authorization, LLM evaluation, live telemetry, rollout and rollback remain planned.

Inspect [verification evidence](evidence/verification.json) for the latest actual test count, timestamp and source fingerprints. Review [Multi-Agent behavior](multi-agent-review.md) for the quoting and approval contracts.

For live manager actions, start [Decision Workspace](showcase.md) with `scripts.serve_showcase`. It exposes a separate `/workbench` view and tightly bounded local action API. Evaluation Studio on that server still reads a completed regression snapshot; live notes are not silently merged into the verified dataset. The standalone `scripts.serve_eval` exposes no action API.
