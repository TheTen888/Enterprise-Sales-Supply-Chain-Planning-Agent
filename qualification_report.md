# Live qualification report

Qualification scope: **local_release**

Production Gate: **Passed**

AWS cloud rollout and container execution are not certified by a local-release pass.

LangSmith project: `GTK-Agent-Production-V2`

Business cases: **23 / 23**. The malformed-quarter case is rejected before inference; the remaining cases must use the real model without fallback.

Agent logical model calls: 106. Token usage: {"input_tokens": 127235, "output_tokens": 4089, "total_tokens": 131324}.

Independent model judge: `gpt-4.1-mini`, 23 / 23 cases passed. Reference: user-approved project-authored rules; no independent expert sign-off claimed.

## Evaluation metrics

| Metric | Value |
|---|---|
| case_pass_rate | 1.0000 |
| capacity_overcommitment_rate | 0.0000 |
| delivery_constraint_pass_rate | 1.0000 |
| calculation_pass_rate | 1.0000 |
| critical_condition_pass_rate | 1.0000 |
| negative_control_pass_rate | 0.0870 |

## Memory Eval

```json
{
  "scope": "Synthetic memory lifecycle tests; not a real-model memory benchmark",
  "metrics": {
    "temporal_recall": 1.0,
    "temporal_consistency_pass_rate": 1.0,
    "contradiction_resolution": 1.0,
    "abstention_rate": 1.0,
    "answerable_query_success_rate": 1.0
  },
  "denominators": {
    "temporal_relevant_events": 1,
    "temporal_checks": 3,
    "conflict_checks": 2,
    "unanswerable_cases": 3,
    "answerable_cases": 1
  },
  "passed": true
}
```

## Gate evidence

| Requirement | Status |
|---|---|
| local_contracts_pass | Passed |
| independent_labels_reviewed | Passed |
| real_llm_evaluated | Passed |
| deployment_checks_pass | Passed |

## Local deployment checks

```json
{
  "http": {
    "ping": true,
    "invocation": true,
    "payload_validation": true,
    "customer_injection_rejected": true,
    "unauthorized_rejected": true
  },
  "dockerfile": {
    "passed": true,
    "checks": {
      "arm64_target": true,
      "nonroot_user": true,
      "port_8080": true,
      "healthcheck": true,
      "entrypoint": true,
      "secrets_excluded": true,
      "runtime_secrets_not_baked": true
    },
    "scope": "Static Dockerfile configuration; no image build or container execution claimed"
  },
  "container_executed": false,
  "aws_verified": false
}
```

## Case traces

| Case | LangSmith Run ID | Mode | Tokens | Elapsed ms |
|---|---|---|---|---|
| standard-quote | `01a1b9dc-f88d-71cc-852a-dba3438eceb0` | llm | 5730 | 8022.55 |
| conflicting-ecn | `01a1b9dd-17e3-71c2-adbc-014c93b914d6` | llm | 13121 | 7381.32 |
| capacity-exhausted | `01a1b9dd-34b9-726f-ade9-1c4ecc700ee4` | llm | 9149 | 8099.48 |
| invalid-quarter | `01a1b9dd-545c-75d3-9011-234acdab6bdf` | validation_error | 0 | 1.1 |
| direct-answer | `01a1b9dd-545e-776f-ad6d-fad6508f8278` | llm | 253 | 2809.25 |
| matrix-14-1000-PLANT-A | `01a1b9dd-5f57-75fd-92e0-e35978d31ff0` | llm | 5723 | 7707.13 |
| matrix-14-1000-PLANT-B | `01a1b9dd-7d72-7091-b465-2968f3add89b` | llm | 5723 | 7681.62 |
| matrix-14-12000-PLANT-A | `01a1b9dd-9b73-71d6-b940-6f894c06021e` | llm | 5730 | 10619.93 |
| matrix-14-12000-PLANT-B | `01a1b9dd-c4ef-7668-b1c8-996ab903a17c` | llm | 5730 | 10967.16 |
| matrix-14-50000-PLANT-A | `01a1b9dd-efc6-73a5-ab5a-b94c30a9439b` | llm | 5728 | 7768.7 |
| matrix-14-50000-PLANT-B | `01a1b9de-0e2b-76be-b3c1-15c43484edeb` | llm | 5724 | 8119.21 |
| matrix-28-1000-PLANT-A | `01a1b9de-2dd8-772d-ab66-5460a20138d1` | llm | 5723 | 7422.95 |
| matrix-28-1000-PLANT-B | `01a1b9de-4ad7-76c4-a63b-eb95ac9323fa` | llm | 5723 | 7729.43 |
| matrix-28-12000-PLANT-A | `01a1b9de-6908-7580-a98a-9efd16f37267` | llm | 5730 | 7385.23 |
| matrix-28-12000-PLANT-B | `01a1b9de-85e1-7663-beb4-442738fc1b33` | llm | 5730 | 11360.18 |
| matrix-28-50000-PLANT-A | `01a1b9de-b242-732b-a27f-d07ff3ef02f6` | llm | 5724 | 8673.97 |
| matrix-28-50000-PLANT-B | `01a1b9de-d423-74a3-b1c3-4bba25995314` | llm | 5723 | 7857.56 |
| matrix-35-1000-PLANT-A | `01a1b9de-f2d5-7512-97d9-95d3a2b5de00` | llm | 5723 | 8253.88 |
| matrix-35-1000-PLANT-B | `01a1b9df-1313-76a8-a806-2ad29d150e4e` | llm | 5723 | 8185.76 |
| matrix-35-12000-PLANT-A | `01a1b9df-330c-76a2-8d0a-589b239735cf` | llm | 5730 | 7824.96 |
| matrix-35-12000-PLANT-B | `01a1b9df-51fc-72ab-bd8c-81faa35cbe41` | llm | 5730 | 7707.25 |
| matrix-35-50000-PLANT-A | `01a1b9df-7017-7230-975e-07b072be6738` | llm | 5724 | 8539.08 |
| matrix-35-50000-PLANT-B | `01a1b9df-9173-744f-9d29-600966de3124` | llm | 5730 | 10078.42 |

## LangSmith access

[Open a verified run](https://smith.langchain.com/o/6dbd6ddc-ce1d-40cd-b8b7-4dbf5b058bb7/projects/p/4b0c159e-7143-47c5-bbe7-21d53d2f7a3a/r/01a1b9dc-f88d-71cc-852a-dba3438eceb0?poll=true)

Project ID: `4b0c159e-7143-47c5-bbe7-21d53d2f7a3a`.

## Security and models

The private .env is Git-ignored, excluded from Docker context, and restricted to file mode 0600. Project text scanning found no plaintext credential values. LangChain credential/project aliases are mapped in process without printing secrets.

Local encoder weights: sentence-transformers/all-MiniLM-L6-v2 and cross-encoder/ms-marco-TinyBERT-L-2-v2. Repository revisions and download sizes are recorded in runtime/models/manifest.json. CPU inference is limited to two Torch threads.

## Retained failure evidence

The earlier failed judge contract, agent-tool completion failures and the real-vector memory abstention failure remain in label-review-attempt1.json, evaluation-attempt1.json and evaluation-attempt2-memory-abstention.json. The fixes clarified expected-output contracts, required both current factory checks, moved numeric constraints to deterministic tools, removed vectors from prompts and rejected low-relevance memory after reranking. Business assertions were not weakened.

Token figures above describe the final acceptance batch; earlier diagnostics, retries and judge probes are separate provider usage. Passing this synthetic local release suite does not establish general production business accuracy.


## Documentation packaging

This is a frozen record of the completed local acceptance run. The interactive three-tier overview, ML design extension and four Evaluation drill-downs were packaged afterward. The qualified runtime hash remains unchanged; no new paid model evaluation was run for these presentation changes.

The diagrams show both implemented modules and target integrations. SageMaker/XGBoost/MLflow risk training, browser WASM, hosted Inngest, IntellAgent, LlamaFirewall, Docker execution and AWS rollout are not certified by this evidence. Recall 55% → 85%, five-day earlier warnings and 80% retry-cost reduction are design targets or illustrative estimates, not measured business impact.

Packaging checks: 79 offline software tests passed. Overview is exported at 3,960 pixels wide and detailed diagrams at 3,200 pixels wide. The Evaluation and local-release gate screenshots were captured from the current dashboard. The owner-supplied LangSmith screenshot spans a wider activity window than this acceptance run.

See [acceptance summary](docs/evidence/acceptance-summary.json), [release-file scan](docs/security_scan.json) and [staged-files/history audit](docs/git_security_audit.json). The final staged/history audit reports identifiers and file paths only, never credential values.
