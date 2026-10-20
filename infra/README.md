# Pilot handoff, disabled by default

No cloud resource, container service or real model is deployed by this repository. The source implements the boundaries needed to prepare a later pilot:

| Boundary | Code / configuration |
|---|---|
| Real services disabled | `.env.example` and `integrations.settings.require_model_live` |
| Model qualification | `agents.model_evaluation.release_gate`, `data/llm-eval/gate.json` |
| Local health | `GET /health` |
| Read-only session metrics | `GET /api/monitor` |
| Auditable decisions | Persisted per-draft events, source fingerprints and manager feedback |
| Baseline recovery | Default deterministic provider; no automatic fallback that hides a model failure |

The model gate currently remains closed: real model quality has not been measured and provisional synthetic labels await independent human review. Contract tests passing does not override those requirements. The operational limits below are a handoff template, not an executed deployment.

```text
Mode: shadow
Live model calls: disabled
Default provider: deterministic
Local bind: 127.0.0.1
Worker concurrency: 1
Session draft ceiling: 20
Customer dispatch: disabled
Rollback target: deterministic baseline
```

A future approved pilot would additionally need enterprise identity, worker leases/fencing, model/provider compatibility validation, operational budgets, observed SLOs and a tested rollout/rollback mechanism. None is inferred from this template. The default application stays local and lightweight.
