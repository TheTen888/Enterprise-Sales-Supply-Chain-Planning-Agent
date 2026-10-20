# Interview showcase

## Start from a clean session

Run from the source checkout:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-ci.txt -r requirements-risk.txt
.venv/bin/python -m scripts.verify --agents
.venv/bin/python -m scripts.serve_showcase
```

Open [Decision Workspace](http://127.0.0.1:8769/workbench). The same server exposes [Evaluation Studio](http://127.0.0.1:8769/#agents). The first command to serve a fresh session trains the small synthetic model once; an existing local `--model RUN/model.json` avoids retraining. No cloud account, API key, LLM or model download is needed.

Model adapters and guarded role interfaces are now demonstrated through [offline SDK contracts](model-adapters.md). This does not require a local language model or a real API connection. The small numeric delivery-risk model above is separate from language-model inference.

Each launch creates an ignored `artifacts/showcase-*` workspace. Refreshing the browser preserves its jobs, notes and traces. After a clean stop, reopen a completed session with:

```bash
.venv/bin/python -m scripts.serve_showcase --resume artifacts/showcase-RUN
```

Only one server should own a session. Resume refuses unfinished queued/running work; it does not pretend to recover a crashed distributed worker. Start a fresh workspace for a new interview. A local session allows up to 20 draft jobs. Ctrl-C stops the server. The standalone Evaluation Studio remains read-only at port 8768 when started with `scripts.serve_eval`.

## Five-minute demonstration

| Time | Action | What the interviewer should learn |
|---|---|---|
| 0:00–0:30 | State the business problem | A sales manager needs a defensible response to a discount request while protecting margin and delivery capacity |
| 0:30–1:30 | Generate quote options; expand the mail and engineering evidence | Current order cost is authoritative; unsigned future volume and mandatory engineering conditions survive retrieval |
| 1:30–2:15 | Compare the three options; ask “Why this price?” | USD 14.25 fails the invented 10% floor; USD 14.45 passes pricing checks, without claiming it is the commercially optimal price |
| 2:15–3:00 | Reject with Customer context needs review; note that 18,000 units are not signed | Feedback binds to that exact draft and source versions, blocks approval and awaits independent review |
| 3:00–3:45 | Recalculate at 18,000 units; ask “Can we deliver?” | Cost rises to USD 234,000 and shared capacity has a 4,000-unit gap; a passing price cannot override delivery constraints |
| 3:45–4:15 | Optionally revise to 10,000 and approve the counteroffer internally | A feasible scenario can pass the local gate; what-if quantities never overwrite the 12,000-unit ETL order |
| 4:15–5:00 | Open Agent Eval, one controlled fault, manager-feedback checks and Risk Model | Show expected rejections, version binding and the honest decision to retain rules at the current alert budget |

Draft history lets the interviewer inspect superseded proposals and the original rejection note. Export session downloads the actual session's numeric drafts, source references, feedback and event sequence. It does not export a production approval or send anything to a customer. Evaluation Studio displays a separate completed regression run; it does not treat an unreviewed live note as ground truth.

## Show evidence when challenged

| Question | Concrete evidence |
|---|---|
| “Isn't this just another dashboard?” | Generate a draft, change the quantity and show a new persisted revision and different capacity result |
| “What if the agent invents a lower cost?” | Open the engineering one-cent fault: independent source/arithmetic checks stop the handoff before business analysis |
| “What if the supervisor disagrees?” | Show reason, note, payload hash, revision and input fingerprints, with `pending_review` status |
| “Can I click approve twice?” | An approval retry returns the same approval without an extra approval event; choosing a different option requires a new revision |
| “Why didn't you deploy the ML model?” | Both rules and model detect 25 of 46 known delays with 36 alerts. Better average precision alone does not justify promotion |
| “Where is the LLM?” | There is no LLM in this local version. The role/tool/state contracts are runnable; LLM-backed behavior and its quality evaluation are a separate next milestone |
| “Are AWS and Snowflake running here?” | Show the local/cloud mapping and fake-client adapter tests. Cloud deployment remains planned |
| “Does a green test mean no hallucinations?” | No. It means these specified contracts passed. General LLM grounding and adversarial prompt tests have not been measured |

## What to improve next

1. Keep the existing offline model adapters and deterministic default. Real inference is deferred; if later authorized on suitable approved infrastructure, measure response quality against the rules baseline before changing the default. No local language model is needed for this showcase.
2. Expand independently reviewed cases across customers, design revisions, missing evidence and ambiguous requests. Use separate development and held-out sets, with slice-level results and clearly defined expected behavior.
3. Validate risk labels on real approved data, across multiple temporal windows, then calibrate and evaluate planner interventions at shared-capacity cluster level. Synthetic accuracy is not business impact.
4. Add production identity, worker leases/fencing, operational spans and rollout/rollback when an internal pilot justifies the cost. These are operational requirements, not extra logos for the interview diagram.

Use [architecture contracts](../architecture/README.md), [Multi-Agent review](multi-agent-review.md), [Risk Model review](risk-model-review.md) and [Evaluation Studio](eval-ui.md) for deeper follow-ups. Current counts and timestamps live in [verification evidence](evidence/verification.json); avoid memorizing an outdated test count.
