# Implementation status

Phase 1 is a local incremental ETL. Phase 2 adds minimal scoped keyword retrieval and a deterministic evidence report. Their default runtime uses only the Python standard library; optional cloud SDK dependencies are separate. The sample data and documents are invented. This document separates runnable behavior from the target architecture.

v0.2 adds a minimal delivery-risk model with optional scikit-learn. It reuses the unmodified ETL, reconstructs synthetic historical features, trains a logistic model and compares it with fixed rules on a temporal holdout. Alerts are selected across all eligible orders before matching mature labels; unknown outcomes are reported separately. See [Risk Model review](risk-model-review.md). Source publication does not constitute cloud deployment or approval to use the model in production.

v0.3 adds a deterministic business/engineering workflow, cent-based quote options, a durable local Draft queue, manager follow-up, revision-bound internal approval and quantity what-if recomputation. See [Multi-Agent review](multi-agent-review.md). It reuses local ETL/RAG/risk outputs; source publication does not call an LLM or deploy cloud agents.

The same version includes nine controlled Agent Eval fault experiments and a read-only [Evaluation Studio](eval-ui.md). Its six views display actual recorded ETL/RAG/risk/agent results, expandable traces, revision comparisons and separate release/approval states. Source, fixture and UI hashes flag stale evidence. No live telemetry, customer sender or production authentication is implied.

A live local [Decision Workspace](showcase.md) now reuses the same workflow for queued generation, internal approval, structured rejection, quantity revision and three guided follow-ups. Feedback is revision/source-bound and waits for independent review. The Agent Eval report adds a seven-check rejection/recalculation experiment. Same-quantity what-ifs stay hypothetical, and approval/feedback retries do not duplicate their audit records. Real LLM behavior and business-impact claims are not added.

This version also includes [offline model adapters](model-adapters.md), guarded model-role code, eight fake SDK calls through the real workflow, 4 development and 16 acceptance cases, a model qualification gate and a read-only session metrics API. Live inference is disabled by default and is not used by demos or CI. The cases have provisional synthetic expectations pending independent human review; no real model quality or performance improvement is measured. Production rollout remains blocked.

## Implemented and locally verifiable

| Capability | Evidence |
|---|---|
| Two-customer source fixture and reviewed expected output | `scripts.run_local`, `tests/test_local_demo.py` |
| Bounded incremental extraction and source checkpoints | `pipelines/etl/extract.py`, recovery tests |
| Durable pinned batch input and digest | Pipeline and warehouse tests |
| Separate trusted source/entity ownership mapping | Raw validation and publication rechecks |
| Exact USD transformation to integer-cent totals | Arithmetic contract and negative tests |
| Staging, atomic publication and historical publication reads | Warehouse transaction and serving tests |
| Logical event deduplication, stale-version handling and tombstones | Replay, conflict and deletion tests |
| Full-batch quarantine with no checkpoint advancement | Invalid-data and scope tests |
| Post-publication ACK recovery without duplicate publication | Fault experiments and subprocess restart test |
| Backlog-based batch-size adaptation | Policy tests and four finite-backlog scenarios |
| Independent fixture reconciliation | Exact event IDs, offset multiplicity and current-state comparison |
| One-command local review | `python3.11 -m scripts.verify` |
| Markdown/email section chunking with quoted-history removal | `rag/documents.py`, RAG unit tests |
| Static demo actor-to-customer/project grants | SQL-backed grant checks before facts, retrieval and return |
| Scoped, current-design keyword retrieval with citations | `rag/retrieval.py`, nine reviewed evaluation cases |
| Current published order facts through read-only parameterized SQL | RAG read-only reuse and publication-invalidation tests |
| Source version checks even while the index is stale | Version-update and future/observed-date tests |
| Logical deletion, index cleanup and stale-cache exclusion | Lifecycle experiments and late-replay tests |
| Bounded per-service evidence cache keyed by scope and revisions | Revocation, changed-order and multi-customer tests |
| Exact source-passage checks before citation | Corrupt-index negative test |
| Bounded parent-document context expansion with explicit incomplete status | `tests/test_rag_context.py`, budget and lifecycle tests |
| Source-bound coverage of unsigned volume and engineering conditions | Four labeled eval cases and negative tests that remove conditions or negation |

`docs/evidence/verification.json` contains the latest completed verification timestamp, Python version, code/fixture hashes and measurements. Consult its test count instead of assuming counts from an older interview example are current.

## Source verification and release

A minimal GitHub Actions definition runs pinned Ruff, full ETL/RAG/risk verification and release-file checks on Python 3.11. `release-files.txt` defines the source release. The release checker reviews candidate content, `.env.example`, local links and indexed blobs. Consult the repository's workflow runs for actual hosted status; no cloud integration or production deployment is implied.

## Planned business and ML work

- Implemented locally with invented inputs: partial delivery quantities, frozen promises, shared-line capacity, historical yield, allocation and pickup gaps; three-date historical joins; chronological splitting with label purging; train-only preprocessing; model selection; rules comparison and portable JSON scoring.
- Still planned: authoritative CDC/publication times, production label agreement and source watermarks, event-level manufacturing aggregation, real-data validation, calibration, multiple temporal windows and intervention-aware evaluation.
- Still planned: approved cloud model registration and Snowflake daily batch scoring; SageMaker training deployment.
- Real-mail/attachment ingestion, richer document parsing, semantic retrieval, production authorization, complete privacy erasure and historical cross-system snapshots.
- Implemented locally: deterministic business/engineering roles, pricing tools, scenario recalculation and version-bound internal approval. LLM generalization, production review/dispatch and distributed worker recovery remain planned.

Local synthetic model results verify the replay/training/evaluation mechanics. They are not production model metrics or evidence of business impact.

## Optional adapter code, not live integration

Snowflake SQL and Cortex Search adapters plug into the same EvidenceService facts and ranking boundaries. A bounded read-only Gmail helper maps trusted message ownership into the existing Document contract. `.env.example`, lazy SDK initialization, explicit live-access opt-ins, parameter binding, scoped filters and sanitized errors are implemented. Fake-client tests exercise call contracts and denial/update/delete/revoke boundaries. No SDK installation, real credential, remote service or cloud provisioning has been verified. See [API setup and limits](api-adapters.md).

The canonical document/policy store remains local; synchronizing it with cloud sources is not implemented. Gmail history cursors, retries, OAuth lifecycle and thread supersession also remain future work.

## Planned integrations

S3 raw storage; real internal database/Gmail ingestion; Airflow scheduling; Snowflake/dbt business tables; Cortex Search; AWS SageMaker training; Snowflake Model Registry and scoring; FastAPI/Streamlit; AgentCore; managed tracing, monitoring and release pipelines. Local retrieval is not an implementation of these services.

These are target services. Only the read-adapter code described above is implemented; all live deployments remain unverified. No credentials or paid services are needed by the present code. GitHub contains source and synthetic evidence, not a cloud deployment.

## Operational boundaries

- One SQLite worker draining a finite synthetic source. No sustained-arrival or distributed concurrency claim.
- Record-count limits do not bound arbitrarily large payloads or attachment memory usage.
- Source ownership mapping is not end-user login, RBAC or document authorization.
- A business tombstone hides a current record; it does not erase retained history, indexes, caches or backups.
- A publication identifies a local consistent view, not a global atomic snapshot of external systems.
- Whole-batch quarantine can block its source. Production remediation and source-reset handling remain deferred.
- Sparse daily updates are the business premise. Large-volume calculations are hypothetical sizing examples.
- Synthetic data can verify mechanics and failure cases, not real delivery-risk accuracy or business impact.
- Demo actor selection is not authentication. Grants currently cover both order facts and documents at customer/project scope; cost-specific field roles are not implemented.
- Document dates are day-granularity filters over this fixed synthetic corpus. Order facts remain the current ETL publication, not a historical point-in-time business snapshot.
- Logical deletion blocks retrieval and removes index chunks on refresh. Canonical versions, generated reports and backups are not physically erased by this prototype.
- No LLM is called. Returning relevant source excerpts is not proof of LLM answer correctness or prompt-injection resistance.

## Next review boundary

Review the deterministic agents, nine controlled faults and evaluation UI alongside existing ETL/RAG/risk regression evidence. Hosted CI, containers and real cloud integration remain separate verification boundaries. Explanations remain in documentation; Python source contains no comments or docstrings.
