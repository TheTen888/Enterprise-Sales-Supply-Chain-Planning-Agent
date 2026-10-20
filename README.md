# Enterprise Sales & Supply Chain Planning Agent

[![Local verification](https://github.com/TheTen888/Enterprise-Sales-Supply-Chain-Planning-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/TheTen888/Enterprise-Sales-Supply-Chain-Planning-Agent/actions/workflows/ci.yml)

**v0.2 — local incremental ETL, scoped RAG and delivery-risk modeling for manufacturing sales.**

A sales manager needs to know which orders may miss their delivery commitments and what evidence matters when a customer asks for a discount. This prototype provides two runnable workflows:

- Predict delivery risk from historical order, capacity and planning snapshots, then compare the model with fixed rules.
- Assemble current order facts, fictional customer emails and engineering constraints into a cited evidence report without mixing customers or silently dropping pricing conditions.

All data is invented. The default ETL/RAG runtime uses Python 3.11 and SQLite; optional local training adds scikit-learn. No API key, cloud account, model download or paid service is required. Quote generation, multi-agent drafting and production cloud deployment remain planned.

## Run locally

From the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m scripts.run_local
.venv/bin/python -m scripts.review_rag
```

These commands need no package installation. Each run creates a fresh workspace under ignored `artifacts/`; re-running does not reset previous demos.

For the delivery-risk model and full verification:

```bash
.venv/bin/python -m pip install -r requirements-ci.txt -r requirements-risk.txt
.venv/bin/python -m scripts.run_risk_model
.venv/bin/python -m scripts.verify --risk
```

Training prints its report path. Inspect `report.json`, `dataset.json`, `model.json`, `scoring-input.json` and `scores.json` in that workspace. To reproduce inference without installed ML packages, replace RUN with the printed workspace:

```bash
.venv/bin/python -S -m scripts.score_risk_model \
  --model RUN/model.json --input RUN/scoring-input.json --output RUN/rescored.json
```

## Data flow

```text
Synthetic order changes -> incremental ETL -> versioned published facts
Synthetic documents -> scoped retrieval + order facts -> cited evidence report
Historical facts + capacity/planning snapshots -> temporal training and evaluation
Numeric JSON model + label-free features -> local batch risk scores
```

| Module | Runnable behavior |
|---|---|
| Incremental ETL | Pin raw input, validate trusted ownership, calculate integer-cent amounts, stage, publish atomically and acknowledge progress |
| Recovery | Deduplicate events, reject conflicting versions, preserve newer state and resume after injected failures |
| Scoped RAG | Check demo grants before SQL/search and return; filter source version, design, status, deletion and access |
| Evidence context | Rank documents, then expand same-version canonical chunks under an explicit budget |
| Risk data | Reuse ETL order history; join shared-line planning/capacity using effective, observed and simulated availability dates |
| Model training | Train-only preprocessing, fixed chronological partitions, immature-label purging and validation-only model selection |
| Risk evaluation | Fixed rules versus logistic regression at the same alert budget, with pending outcomes accounted for |
| Optional adapters | Snowflake SQL, Cortex Search and read-only Gmail call paths verified with fake SDK clients |

## Review one delivery-risk prediction

The [synthetic scenario](data/risk-fixtures/README.md) generates 624 order lines and replays 1,248 changes through the existing ETL. Seven numeric features cover quantity, shared-line load, schedule slack, prior yield, design changes, quarterly allocation and pickup gaps.

For `ORDER-41-05`, the October 20 prediction freezes 12,000 units due November 3. The known plan finishes November 8, five days behind the promise. The order ultimately finishes November 4: label = 1. A later negotiated November 10 deadline cannot rewrite that historical label. A retroactive quantity change first received after prediction is also excluded from its features.

A small logistic model is selected on validation, then evaluated on later dates. The test period has 144 predictions: 138 mature labels, including 46 known late orders, and six pending outcomes. Both systems select their weekly top 25% before labels are matched.

| Synthetic holdout metric | Rules | Logistic model |
|---|---:|---:|
| Alerts | 36 | 36 |
| Alerts awaiting labels | 2 | 1 |
| Known late orders detected | 25 / 46 | 25 / 46 |
| Recall among known late orders | 54.3% | 54.3% |
| Precision on labeled alerts | 73.5% | 71.4% |
| Average precision on mature outcomes | 0.6611 | 0.7207 |

**The model has not beaten rules at the operating budget and is not promoted.** Unknown alerts are not counted as false positives or successes. Full reports include precision bounds and label coverage. These are one-seed simulator results, not production accuracy or business impact.

See [Risk Model review](docs/risk-model-review.md) for label/feature formulas, the complete order walkthrough, temporal boundaries, exclusions, leakage tests and limitations. Exported JSON inference is checked against the fitted pipeline; no live SageMaker, Snowflake scoring or Model Registry is claimed.

## Review the discount evidence

```bash
.venv/bin/python -m scripts.review_rag
.venv/bin/python -m scripts.eval_rag
.venv/bin/python -m scripts.demo_api_contracts
```

The customer requests 5% off. The evidence report returns two current documents and four passages showing that future volume is unsigned, required material and inspection cannot be removed, no volume-based cost reduction is approved, and simplification needs engineering review. The one-passage baseline covers one of four annotated conditions; bounded document expansion covers all four in this fixed example. This is fixture coverage, not an approved discount or LLM answer-quality score.

Default limits are 6,000 context characters and 16 passages. A selected document either fits in full or is omitted with `incomplete_context`. Running `scripts.run_rag --max-context-chunks 1` intentionally returns exit code 2 rather than silently truncating evidence. Updates, deletion and revoked access invalidate cached evidence. Retained canonical history and exported reports are not physically erased.

## Verification and CI

```bash
.venv/bin/python -m ruff check --no-cache app pipelines rag risk_model integrations scripts tests
.venv/bin/python -m scripts.verify --risk
.venv/bin/python -m scripts.release_check
```

Full verification covers unit tests, five ETL fault experiments, four finite-backlog scenarios, nine RAG query cases, five RAG lifecycle experiments, adapter contracts, the discount walkthrough, risk training and eight dataset audits. Model tests include late-arrival exclusion, frozen labels, temporal purging, holdout independence, pending-label alert accounting, invalid business inputs and inference without site packages. `--risk` requires zero skipped tests. Standard-library-only `scripts.verify` explicitly skips optional training tests when scikit-learn is absent.

[Recorded evidence](docs/evidence/verification.json) includes timestamps, source hashes and actual counts. The [workflow](.github/workflows/ci.yml) installs public test tooling, runs synthetic local checks and scans release files. It uses pinned Action commits, read-only repository permissions and no cloud secrets or deployment step. The status badge links to actual hosted runs; local evidence alone does not prove hosted CI or live integration has passed.

## Release scope and credentials

[release-files.txt](release-files.txt) is the exact release manifest. The release checker scans candidate text and Git-indexed blobs, checks local links and rejects private/generated files. Before a commit, stage only reviewed manifest files and rerun the checker. [v0.1 first-commit notes](docs/first-commit.md) remain as a historical preparation record; [Changelog](CHANGELOG.md) describes subsequent changes.

`.env.example` has empty credentials and disables live services. `.env`, OAuth tokens, keys, databases, caches, runtime artifacts and local interview notes are excluded. Known-pattern and private deny-term scans reduce exposure risk without guaranteeing detection of every secret or confidential fact.

Optional cloud factories require explicit opt-in and are never invoked by default demos or CI. Their SDKs are separate extras. See [API contracts and setup](docs/api-adapters.md).

## Implemented versus planned

Implemented: local ETL, scoped English keyword retrieval, deterministic evidence reports, synthetic risk training/scoring and offline API contracts. Demo actors are not production authentication; evidence readiness is not approval to send a proposal. Atomic publication and replay tests establish a local contract, not a universal exactly-once guarantee.

Planned: real CDC/Gmail/S3 ingestion, Airflow/dbt execution, semantic retrieval, production identity and retention controls, real-data model validation/calibration, cloud training/scoring, multi-agent drafting, version-bound manager approval, UI and operational monitoring. No revenue, deal-win, avoided-delay or cost-saving results are claimed.

The target architecture retains originals in S3 and existing CRM/business tables, RAG, daily scoring and dashboards in Snowflake, with SageMaker for training. Those services are target integrations, not the runtime of this local prototype.

```text
app/repositories/   Local source and warehouse persistence
pipelines/etl/     Extract, validate, transform, stage, publish and recover
rag/               Document lifecycle, scoped retrieval and evidence evaluation
risk_model/        Historical features, labels, temporal training and scoring
integrations/      Optional SDK adapters and fake-client contracts
scripts/           Demos, independent scoring, verification and release checks
data/              Invented fixtures and reproducible scenario configuration
tests/             Business boundaries, reconciliation and negative tests
docs/              Design, implementation boundaries and measured evidence
```

- [Implementation status](docs/implementation-status.md)
- [ETL design and trade-offs](docs/design.md)
- [RAG design and limits](docs/rag-review.md)
- [Discount and lifecycle walkthrough](docs/rag-audit-walkthrough.md)
- [Risk Model walkthrough and evaluation](docs/risk-model-review.md)

The ETL layering and local-first approach were inspired by John Data Lab's `enterprise-ai-agent`. The upstream [MIT notice](LICENSES/JohnDataLab-MIT.txt) is retained alongside this project's [license](LICENSE).
