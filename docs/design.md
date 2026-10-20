# Local incremental ETL design

## Business contract

The initial entity is an order line. A change contains `event_id`, `entity_id`, positive integer `version`, `operation`, `customer_id`, and `project_id`. An upsert also contains integer quantity, USD currency, decimal-string unit cost/price, and a design version. A delete is a versioned tombstone.

The trusted source name comes from the configured `Source` object, not the payload. An administrator seeds an entity-to-customer/project mapping separately. Event-provided IDs must match that mapping. Ownership transfer is intentionally unsupported, including after a mapping is revoked.

`event_id` is scoped by source. Identical re-deliveries have the same normalized content hash. Reusing an ID for a different semantic change is an error. Multiple event IDs may reference the same business version; identical content is acknowledged without another version. Conflicting content for an already known version blocks publication.

Amounts are converted with `Decimal` to integer cents. Inputs with unsupported currency, non-finite money, fractional quantity or more than two decimal places are rejected. The transformation multiplies integer cents by integer quantity. Derived values are checked before staging and again during publication.

## Step 1 — Select and pin a bounded page

`extract_changes()` reads changes after a committed source offset, ordered by offset and bounded by batch size. The selected raw rows and input digest are persisted before transformation. A restart resumes those rows even if the source grows or the worker's batch-size setting changes.

This preserves repeatability. A retry does not silently read a newer snapshot and produce a different result for the same batch.

An optional policy selects 100, 500 or 1,000 rows based on backlog. Within a worker, slow previous processing reduces the next limit, with a floor of 100. This is a deliberately small feedback policy; it does not measure memory or provision compute. Pending batches bypass selection and keep their original inputs. The previous-duration observation is in memory and resets at restart.

The local source provides ordered, append-only offsets. A real SQL polling connector would need a reliable composite cursor, overlap/reconciliation strategy and deletion handling. A CDC connector would need its own commit-position contract. Neither connector is implemented here.

## Step 2 — Validate and transform

Raw validation requires explicit identity and scope. Missing ownership is never inferred or filled with a default. Trusted scope mappings are fetched in bounded groups; transformed output is checked before it is persisted.

The worker does no model inference. No LLM can modify source facts, assign customer ownership or calculate authoritative amounts in this module.

## Step 3 — Persist candidates

Candidate records live in `staged_records` and are invisible to serving readers. The batch ID is deterministic from source identity, cursor range and raw digest. Re-running a staged batch replaces only its own candidate rows.

One bad record quarantines the entire page. This favors a coherent batch over partial availability. Quarantine records the reason, keeps the previous publication, and leaves the source checkpoint unchanged. Other source identities can continue independently.

## Step 4 — Publish atomically

A SQLite `BEGIN IMMEDIATE` transaction rechecks current source ownership, validates arithmetic, checks event/business-version conflicts, inserts changed record versions, records processed events, creates the publication and advances the serving manifest.

All of those writes commit together. An exception during the transaction rolls them back together. Readers select the latest business version for each source/entity within the chosen publication. Tombstones are filtered after version selection so an old upsert cannot resurrect a deleted record.

Versions are immutable. Publication IDs provide a reproducible local view. They do not establish an atomic snapshot of external systems that were sampled at different times.

Only changed record bodies are stored. There is no per-batch full-table clone. The local read query uses a window function over retained versions; history retention and indexing need further work for much larger datasets.

## Step 5 — Acknowledge progress

The checkpoint advances only after publication, using a conditional update from the expected lower offset to the batch upper offset. The batch then becomes completed.

There is an intentional recovery boundary between publication and checkpoint acknowledgement. If the worker exits there, the publication is already valid and visible. The next worker finds the published batch, acknowledges it, and proceeds. It does not publish again.

The prototype guarantees these effects only under its SQLite transaction and append-only source assumptions. It does not claim universally exactly-once transport.

## State transitions

```text
extracted -> staged -> published -> completed
    |          |
    +----------+-> quarantined
                     |
                     +-> explicit retry after repair -> staged
```

Transient failures leave the batch at its last durable state. Validation failures quarantine it. Quarantined inputs are not retried continuously. Raw rows remain pinned.

## Trade-offs

| Decision | Benefit | Cost or limitation |
|---|---|---|
| Incremental pages | Bounded memory and replayable work | Requires reliable source progress semantics |
| Separate offset and version | Handles late updates without confusing freshness with arrival order | Needs stable business versions |
| Full-batch quarantine | No partially valid batch publication | A poison record can block its source |
| Immutable versions plus manifest | Reproducible reads and atomic visibility | Retained history uses storage; reads need optimization at scale |
| Publish before checkpoint | Data is durable before progress is acknowledged | Requires explicit post-publication recovery |
| Integer cents | Exact supported-currency arithmetic | Additional currencies/rounding rules require a contract |
| Local SQLite | Offline, reproducible fault experiments | Serialized writes; no managed cloud scalability |

## Capacity assumptions and what was measured

The business scenario has sparse daily changes and larger updates around monthly pickups and quarterly allocation revisions. Illustrative sizing is 500 routine changes/day, a 5,000-change monthly import and a 20,000-change quarterly refresh; these are planning examples, not company measurements or tested cloud targets. Emails and attachments need separate size and parsing budgets. Allocation, deadlines, capacity, yield and forecast/pickup facts are proposed contract extensions, not current fields or learned model weights.

This implementation processes synthetic order-line changes only. Five fault experiments include a 5,000-change recovery case. Four load-Eval scenarios use 65, 1,935, 12,900 and 6,450 input changes. The input includes duplicate delivery, late versions and deletions. Every final entity is compared with an independent full recompute that does not call the production validator or transformation.

Load-Eval drain time includes extraction, persistence, processing, acknowledgement and injected recovery, after fixture creation. Per-batch processing duration starts after extraction and raw persistence; its P95 does not represent end-to-end freshness. The restart scenario excludes failed attempts from its successful-batch P95 but includes them in drain time. The two-second P95 budget is configurable and local only. Timings depend on hardware and disk cache; the small fixture produces few batches, so its P95 is descriptive rather than a statistically stable production estimate.

These tests exclude sustained arrivals, memory measurement, real concurrent writers, Gmail, attachment parsing, network transit, Snowflake loading and RAG indexing. The independent baseline is a synthetic-fixture oracle, not a generic production reconciliation engine.

Load Eval also compares exact unique event identities and retained source-offset multiplicities. Negative tests deliberately replace an event ID while retaining the same count, and delete a raw delivery after its checkpoint is acknowledged. These failures are detected even when the final current records still match. This proves fixture-to-warehouse completeness under the local source assumptions, not completeness of an unimplemented external connector.

One million changes over 16 hours averages about 17.4 changes/second. A tenfold burst averages about 174 changes/second during the burst. Those calculations are sizing assumptions, not proof that this worker or a cloud design meets those loads.

## High- and low-volume operation

The planned production approach combines event ingestion for mail with micro-batches for structured facts, plus daily reconciliation. Normal batches can flush every 15 minutes; a shorter window can be evaluated during busy periods. Flush deadlines and size thresholds should be chosen against measured freshness and cost.

Backlog age, queue depth, processing duration, source rate limits and failures should guide concurrency. Empty work should skip warehouse transforms. Increasing concurrency without considering source limits can worsen throttling.

The local worker implements bounded adaptive batches, backlog reporting and recovery. The policy responds to backlog rather than fixed clock periods: a quiet morning can still have a burst. It does not implement automatic scheduling, scaling, rate limiting or a broker. SQLite worker concurrency is not a substitute for a distributed warehouse. New source arrivals are not included in the current finite-backlog benchmark.

The count limit bounds records per batch, not arbitrary input bytes. A production connector also needs payload and attachment limits, a byte budget, bounded parsing and memory measurements. Reducing the limit for future batches cannot repair an already pinned batch that deterministically exhausts memory; audited subdivision or another operator recovery path remains deferred.

The interview playbook separates measured local behavior from proposed queue/concurrency controls and gives a recovery runbook. No cloud capacity target is inferred from local rows/second.

## Future RAG handoff

A minimal local implementation is now available in `rag/`. See [RAG review](rag-review.md) for its static demo grants, Markdown chunking, keyword retrieval, read-only ETL facts, lifecycle tests and limits. The cloud and production integrations below remain future work.

Structured order/cost facts remain queryable through controlled SQL. A later document pipeline should emit authorized text, source references, customer/project/document scope, source version, ACL, content hash and deletion state. A durable indexing outbox should track searchable completion independently from ETL progress.

Document chunking, Gmail access, Cortex Search, manager authentication, user/document authorization, token budgeting and model calls are not present in this ETL prototype. Customer/project ownership validation here must not be presented as a complete RAG access-control system.

## Production work deliberately deferred

Source identity/reset detection, CDC or timestamp-based extraction, operator-controlled malformed-input repair/skip, multi-user authorization, retention/compaction, concurrent-worker stress tests, storage failure testing, scheduler integration, operational alerts and cloud adapters remain separate work. A future Snowflake/S3 implementation requires its own transaction, checkpoint and integration tests rather than a claim that changing a connection string is sufficient.
