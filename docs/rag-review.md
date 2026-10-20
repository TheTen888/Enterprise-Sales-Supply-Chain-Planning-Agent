# Minimal local RAG review

This is an executable local evidence layer, not an LLM-powered quotation system. It reuses the existing ETL without changing its source, transformation, version or recovery code.

## Run

```bash
.venv/bin/python -m scripts.run_rag
.venv/bin/python -m scripts.eval_rag
.venv/bin/python -m scripts.verify
```

The first command creates a fresh ETL warehouse using `scripts.run_local`, builds a separate knowledge database and returns an evidence pack. An optional `--warehouse` argument reads an existing published ETL database without modifying it. New RAG runs use new directories, never reset old runs.

## One customer request

Customer A asks for a five-percent price discount on ORDER-A001-L1. The existing ETL fixture has published v3, design D2, 12,000 units, unit cost USD 13.00 and unit selling price USD 15.00. This module does not use the USD 13.80 cost from earlier discussion examples.

1. The application supplies the simulated backend identity `demo-manager-a`. A separate grant allows only CUSTOMER-A / PROJECT-A. Unknown or wrong-scope principals are denied before the order query.
2. A fixed parameterized SQL query opens the ETL warehouse read-only, pins its published manifest and selects the latest non-deleted order in that scope. Source name and SQL shape are controlled by code. There is no arbitrary SQL execution.
3. Source Markdown fixtures represent customer emails and engineering records. A trusted manifest binds document IDs to customer/project/entity, version, status, design and dates. Content cannot grant access or approve a design.
4. Chunking follows headings and paragraphs, removes quoted email-history lines and signatures, and bounds each passage to 700 characters. It is not a PDF parser or a complete email-thread parser.
5. The index includes historical passages deliberately. Before ranking, the reader selects only currently eligible document versions in the requested scope and matching design. Source hash and exact canonical section/text must match the index entry. Drafts and deleted documents cannot supply approved engineering evidence.
6. A small lexical scorer ranks eligible passages by query-term frequency and inverse document frequency. It selects one seed from each of up to k distinct documents (1..10), then loads every normalized chunk from those exact canonical versions. Expansion is not limited to adjacent chunks or keyword matches. Each added passage preserves its source ID/version/hash and is marked `document_context`; seeds are marked `retrieval_match`.
7. Context is bounded separately from document k: by default 6,000 section/text characters and 16 chunks in total. A document either fits in full or is omitted, with `incomplete_context` and an explicit reason. There is no partially returned document hiding a missing tail. These are character/chunk limits, not tokenizer or full serialized-request limits. The permitted maxima are 20,000 characters and 32 chunks.
8. The evidence report combines the read-only order facts with source excerpts and citation IDs. For the default request it returns MAIL-A-001 v2 and ENG-A-001 v2. The old D1 cost, old three-percent request, unapproved engineering proposal and similar B documents are not used as current A evidence.
9. Before return, access and source/index/policy revisions are checked again. A detected change fails the request for retry rather than silently returning mixed results.

`ready` means the quote-context request retrieved both configured evidence kinds with complete normalized context for the selected documents within budget. It does not certify all business assumptions, calculate an approved quote or authorize sending. `insufficient_evidence` retains known order facts but explicitly blocks a complete pricing justification. No model generates conclusions or prices.

## Version and deletion behavior

Document writes are atomic. Re-ingesting identical versions is a no-op; a conflicting same version or changed ownership is rejected. Higher eligible versions supersede older ones. A new eligible draft or mismatched design blocks silent fallback to an older approved explanation.

The index refresh is a separate operation. If engineering v3 has reached source storage but the index still contains v2, v2 is rejected at read time. The quote remains incomplete until v3 is indexed. The result identifies index freshness.

Deletion creates a canonical tombstone. Readers block the document immediately, including requests for an earlier date. An index refresh removes all its indexed chunks. An old write arriving again does not remove the tombstone or resurrect evidence.

This is **logical retrieval deletion**, not complete privacy erasure. Canonical source history, saved evidence packs and generated reports remain. There is no backup erasure or retention implementation. Historical replay cannot bypass current access revocations or deletions.

Dates are fixed, canonical YYYY-MM-DD values at day granularity. Eligible document revisions must have been observed and effective by the requested date. ETL facts are still the current publication; this is not a complete historical point-in-time join across the order and document systems.

## Cache behavior

An in-memory cache holds at most 64 evidence packs. The key contains actor, scope, entity, query, date, k, task, context budgets, ETL publication and knowledge/index/policy revisions. Relevant revision changes clear the per-service cache; authorization is checked even before a cached response can be used. A newer ETL publication causes fresh facts to be read.

The cache is local to one process. This code does not implement production sessions, distributed cache invalidation or an atomic distributed snapshot. Previously exported reports are historical artifacts and must not be reused as current authorization.

## Evaluation and acceptance

Nine manually reviewed cases use fixed documents and queries:

- Six positive cases: two A quote queries, B quote evidence, two A engineering queries and A packaging lookup.
- One no-evidence case, which must remain incomplete.
- Two access-denial cases, which must not return facts or citations.

For positive cases, Recall@k is the fraction of reviewed relevant document IDs retrieved. Precision@k is the relevant count divided by the configured k. The k unit remains distinct documents even when expansion returns multiple passages. No-answer and denial cases are reported separately, not folded into the positive retrieval average. Exact expected source versions and selected SQL values are also checked.

The lexical implementation is the initial baseline. There is no separate semantic candidate yet. A perfect score on these six positive queries is only a fixture result; it does not demonstrate production search quality, natural-language paraphrase robustness, multilingual performance or LLM faithfulness. Recorded request durations are single local observations, not a production latency percentile.

Four cases also carry human-reviewed condition annotations bound to exact document ID, version and chunk ID. Coverage requires the expected text span, including negation. The default discount case contains four conditions: unsigned future volume; mandatory material/inspection; no approved volume cost reduction; and required engineering review. Its single-passage baseline covers 1/4; bounded canonical expansion covers 4/4. A negative test drops the context passages while keeping the right document IDs: document recall still passes but condition coverage fails. Another removes the word `no` and must also fail. This is fixture-span coverage, not semantic understanding or LLM faithfulness.

Five executable lifecycle experiments test:

1. Cache population, a source update before index refresh, rejection of v2, and retrieval of v3 after refresh.
2. Logical deletion while stale index/cache content exists, historical-query exclusion, index cleanup and old-event replay.
3. Revocation after cache population.
4. Conflicting document versions and ownership reassignment, with prior state preserved.
5. A real ETL v4 update to 20,000 units and USD 13.50 cost invalidating previous order facts. This is a synthetic data update experiment, not an implemented manager scenario or cost forecast.

Unit tests also validate query bounds, read-only warehouse reuse, missing warehouse behavior, path traversal, canonical dates, future/late-observed revisions, design mismatch, corrupted index text, mid-request access revocation, deleted orders and multi-customer cache separation. A negative evaluator test changes the returned version while retaining the right document ID and confirms that evaluation fails.

A synthetic document containing an instruction cannot grant tool permissions in this deterministic system. Since no LLM is present, this is not evidence of general prompt-injection resistance for a future model integration.

## Code map

| File | Responsibility |
|---|---|
| `rag/documents.py` | Source contract, fixture ownership validation and chunking |
| `rag/store.py` | Document versions, grants, canonical state and index refresh |
| `rag/retrieval.py` | Authorized order facts, lexical retrieval, bounded cache and evidence report |
| `rag/evaluation.py` | Reviewed cases, metrics and lifecycle experiments |
| `scripts/run_rag.py` | Local demo and optional reuse of a published ETL warehouse |
| `scripts/eval_rag.py` | Reproducible RAG evaluation reports |
| `tests/test_rag.py` | Retrieval, access, version, cache and negative-evaluation checks |
| `tests/test_rag_context.py` | Condition coverage, canonical context expansion, budget and mutation tests |

## Review priorities and future work

Check the cited email and engineering source against the printed USD 13.00 order fact, then read the lifecycle report. Distinguish source facts, customer requests and approved engineering evidence.

Future work includes complete live connectors, production identity and fine-grained roles, token-aware/table-aware parsing, semantic retrieval, model generation, source freshness targets, distributed concurrency, complete deletion/retention and operational telemetry. An optional Cortex Search adapter and Snowflake SQL/Gmail read helpers now have fake-client contract tests; live integration, synchronization and cloud LLMs remain planned. See [API setup](api-adapters.md) and the [guided discount review](rag-audit-walkthrough.md). No diagram, original reference project or GitHub publication is changed by this module.
