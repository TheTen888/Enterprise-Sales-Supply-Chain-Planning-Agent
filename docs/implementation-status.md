# Implementation status

Phase 1 is a local incremental ETL. Phase 2 adds minimal scoped keyword retrieval and a deterministic evidence report. Their default runtime uses only the Python standard library; optional cloud SDK dependencies are separate. The sample data and documents are invented. This document separates runnable behavior from the target architecture.

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

## v0.1 release preparation

A minimal GitHub Actions definition runs pinned Ruff, the local verification command and explicit candidate-file checks on Python 3.11. `release-files.txt` defines the first-commit scope. The release checker reviews candidate content, `.env.example`, local links and indexed blobs when Git is available. No hosted workflow or remote publication is claimed; see [first-commit review](first-commit.md).

## Planned business and ML work

- Fulfillment/cancellation quantities, promised delivery dates, usable capacity, historical yield, allocation and time-phased pickup forecasts.
- Authoritative effective-date joins and point-in-time features using both effective and observed time.
- Agreed delivery labels, temporal train/validation/holdout splits, training, calibration and risk-model evaluation.
- Approved-model registration and daily batch scoring.
- Real-mail/attachment ingestion, richer document parsing, semantic retrieval, production authorization, complete privacy erasure and historical cross-system snapshots.
- Business/engineering agents, deterministic pricing tools, scenario recalculation and version-bound approval.

Local version and ownership tests are not evidence that these future features or model metrics have been implemented.

## Optional adapter code, not live integration

Snowflake SQL and Cortex Search adapters plug into the same EvidenceService facts and ranking boundaries. A bounded read-only Gmail helper maps trusted message ownership into the existing Document contract. `.env.example`, lazy SDK initialization, explicit live-access opt-ins, parameter binding, scoped filters and sanitized errors are implemented. Fake-client tests exercise call contracts and denial/update/delete/revoke boundaries. No SDK installation, real credential, remote service or cloud provisioning has been verified. See [API setup and limits](api-adapters.md).

The canonical document/policy store remains local; synchronizing it with cloud sources is not implemented. Gmail history cursors, retries, OAuth lifecycle and thread supersession also remain future work.

## Planned integrations

S3 raw storage; real internal database/Gmail ingestion; Airflow scheduling; Snowflake/dbt business tables; Cortex Search; AWS SageMaker training; Snowflake Model Registry and scoring; FastAPI/Streamlit; AgentCore; managed tracing, monitoring and release pipelines. Local retrieval is not an implementation of these services.

These are target services. Only the read-adapter code described above is implemented; all live deployments remain unverified. No credentials or paid services are needed by the present code. There is no configured Git remote, GitHub publication or cloud deployment supplied by this phase.

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

Review the ETL fixture, RAG evidence report and the recorded lifecycle experiments. ML, agent behavior, UI, containers and real cloud integration remain separate changes with their own tests and acceptance criteria. Explanations remain in documentation; Python source contains no comments or docstrings.
