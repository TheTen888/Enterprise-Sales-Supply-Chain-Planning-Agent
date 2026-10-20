# Enterprise Sales & Supply Chain Planning Agent

**v0.1 — local incremental ETL and scoped RAG evidence for manufacturing sales.**

When a customer asks for a discount, a sales manager needs the current order numbers, the customer's actual commitments and the engineering constraints behind the cost. This prototype assembles that evidence without mixing customers, using stale document versions or treating possible future orders as signed volume.

The default runtime uses Python 3.11 and SQLite. It needs no API key, cloud account, model download or paid service. It does not yet generate or approve quotes, predict delivery risk or run multiple agents.

## Try it locally

Run from the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m scripts.run_local
.venv/bin/python -m scripts.run_rag
.venv/bin/python -m scripts.verify
.venv/bin/python -m scripts.release_check --output artifacts/release-check.json
```

No package installation is needed for these local commands. Each demo creates a fresh directory under `artifacts/` and prints its report paths. Verification writes fresh evidence under `docs/evidence/`. Re-running does not reset a previous demo.

The ETL fixture retains **9 deliveries**, reconciles **7 logical events** and publishes **2 current order lines**. Customer A's current order is v3, design D2, 12,000 units at USD 13.00 unit cost and USD 15.00 unit selling price. All identities, quantities, amounts, emails and engineering records are invented.

## What runs in v0.1

| Module | Implemented behavior |
|---|---|
| Incremental ETL | Pin raw inputs, validate trusted ownership, calculate integer-cent totals, stage, publish atomically and acknowledge progress |
| Recovery | Deduplicate logical events, reject conflicting versions, preserve newer state and resume after injected failures |
| Scoped retrieval | Check demo grants before SQL/search and return; filter current document versions, design, status and deletion state |
| Evidence context | Rank distinct documents, then expand their same-version canonical chunks under a bounded budget |
| RAG evaluation | Check expected documents, versions, SQL facts and source-bound business conditions; test update, deletion and revocation |
| Optional API adapters | Snowflake SQL, Cortex Search and read-only Gmail call paths tested with fake SDK clients; no live integration claim |

```text
Synthetic order changes -> incremental ETL -> published order facts
Synthetic documents -> versioned knowledge store -> scoped retrieval
Published facts + bounded document context -> cited evidence report
```

The raw-to-publish boundary keeps staged data invisible. A failure after publication but before checkpoint acknowledgement resumes by acknowledging the existing publication, without publishing it twice. This is a tested local contract, not a universal exactly-once guarantee.

## Review the discount example

```bash
.venv/bin/python -m scripts.review_rag
.venv/bin/python -m scripts.eval_rag
.venv/bin/python -m scripts.demo_api_contracts
```

The customer requests 5% off. The report returns two current documents and four passages, including these conditions:

- Future volume has not been signed or committed.
- Revised material and additional inspection remain required.
- No volume-based cost reduction has been approved.
- Any simplification requires separate engineering review.

The old one-passage baseline contains only one of these four reviewed conditions; context expansion contains all four in this fixed example. This is fixture coverage, not production accuracy or an approved discount.

Default context limits are 6,000 section/text characters and 16 passages. A selected document either fits in full or is omitted with `incomplete_context`. To inspect that boundary:

```bash
.venv/bin/python -m scripts.run_rag --max-context-chunks 1
```

This intentionally returns exit code 2 and an incomplete report. It does not silently truncate the document and claim completeness. Updates, deletes and revoked access invalidate cached evidence. Deletion is logical retrieval exclusion plus index cleanup; retained history and exported reports are not physically erased.

## Verification and CI

The [workflow](.github/workflows/ci.yml) runs the same local verification on Python 3.11:

```bash
.venv/bin/python -m pip install -r requirements-ci.txt
.venv/bin/python -m ruff check --no-cache app pipelines rag integrations scripts tests
.venv/bin/python -m scripts.verify
.venv/bin/python -m scripts.release_check
```

Only the pinned Ruff lint tool is installed. CI bootstrapping downloads public tooling; the ETL/RAG checks use synthetic local data and fake API clients. The workflow has read-only repository permissions, does not persist checkout credentials and references Actions by full commit SHA. It uses no cloud secrets or deployment step.

Verification covers unit tests, five ETL fault experiments, four finite-backlog scenarios, nine RAG query cases, five RAG lifecycle experiments and the discount walkthrough. Four query cases also check annotated conditions. Negative tests remove a required condition or its negation and must fail even when the document IDs are correct. Python source is checked for comments and docstrings.

See [recorded verification](docs/evidence/verification.json) for the latest timestamp, test count, source hashes and measured local results. Local execution does not establish that a GitHub-hosted runner or live cloud integration has passed.

## First-commit scope and credentials

[release-files.txt](release-files.txt) is the exact candidate file list. [First-commit review](docs/first-commit.md) explains the included files, exclusions and verification steps. The release checker scans those files and, when a repository exists, its indexed blobs. It reports locations and rule names, never matched secret values.

`.env.example` contains empty credential fields and disables live services. Local `.env` files, private keys, databases, runtime artifacts, caches, build outputs and local interview notes are excluded. A pattern scan reduces risk but cannot guarantee detection of every secret or confidential fact.

Optional cloud factories require explicit opt-in and are not invoked by local demos. Their SDK dependencies are separate extras and are not installed by CI. See [API contracts and setup](docs/api-adapters.md).

## Implemented versus planned

The executable scope is ETL, local English keyword retrieval, deterministic evidence reports and offline API contracts. Demo actors are not production authentication; `ready` is not approval to send a proposal.

Planned work includes real CDC/Gmail/S3 ingestion, Airflow/dbt execution, synchronized cloud document policies, semantic retrieval, production identity, complete retention/deletion, risk-model training/scoring, multi-agent drafting, manager approvals, UI and operational monitoring. No model accuracy, revenue, deal-win or cost-saving results are claimed by v0.1.

The target architecture retains originals in S3 and existing CRM/business tables, RAG, scoring and dashboards in Snowflake, with SageMaker for training. The target architecture and the implemented local prototype are different maturity levels.

## Code and design

```text
app/repositories/   Local source and warehouse persistence
pipelines/etl/     Extract, validate, transform, stage, publish and recover
rag/               Document lifecycle, scoped retrieval, context and evaluation
integrations/      Optional SDK adapters with fake-client contract tests
scripts/           Demos, verification and release-file checks
data/              Invented fixtures and independently reviewed expectations
tests/             Behavior, recovery, reconciliation and negative tests
docs/              Design, implementation boundaries and recorded evidence
```

- [Implementation status](docs/implementation-status.md)
- [ETL design and trade-offs](docs/design.md)
- [RAG design and limits](docs/rag-review.md)
- [Discount example and lifecycle walkthrough](docs/rag-audit-walkthrough.md)
- [Recorded RAG evaluation](docs/evidence/rag-evaluation.json)

The ETL layering and local-first approach were inspired by John Data Lab's `enterprise-ai-agent`. The upstream [MIT notice](LICENSES/JohnDataLab-MIT.txt) is retained alongside this project's [license](LICENSE).
