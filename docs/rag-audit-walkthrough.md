# RAG review: a customer asks for a discount

## Run the review

```bash
.venv/bin/python -m scripts.review_rag
.venv/bin/python -m scripts.eval_rag
.venv/bin/python -m scripts.demo_api_contracts
.venv/bin/python -m scripts.verify
```

Each review creates a fresh directory and prints its report path. `scripts.review_rag` saves separate readable reports for initial retrieval, a source update while the index is stale, a refreshed index, deletion and old-version replay. It also checks revocation after caching, includes a reference single-passage baseline and demonstrates explicit context-budget rejection. The API contract demo is separate and offline.

## One order, end to end

| Step | Concrete example | Why it exists |
|---|---|---|
| Source facts | Published A001 v3: D2, 12,000 units, USD 13.00 unit cost and USD 15.00 unit price | Exact numbers come from ETL, not an LLM or an email estimate |
| Customer request | MAIL-A-001 v2 asks for 5% off; possible future volume is not signed | A request is not an approved commercial commitment |
| Engineering evidence | ENG-A-001 v2 requires revised material and extra inspection | A cheaper proposal must not silently remove an engineering requirement |
| Chunking | Heading/paragraph chunks of at most 700 characters; quoted old 3% request and signature removed | Keep source sections understandable and avoid quoting old conversation as the current request |
| Provenance | Each indexed chunk retains document ID, version, section, source hash and trusted scope | The report can be checked against the exact source version |
| Authorization | Manager A has A/project-A access; B documents contain similar vocabulary but are out of scope | Relevance is never permission |
| Eligibility | Current effective/observed version and D2 only; drafts, deleted records and stale D1 evidence excluded | A plausible old answer is still wrong for today's design |
| Retrieval | Local English lexical ranking, two distinct documents by default | Find relevant sources without increasing document k |
| Context expansion | Hydrate all normalized chunks of those exact source versions; default 6,000 characters / 16 passages | Include caveats even when they do not match the search terms |
| Report | Current order facts plus MAIL-A-001 v2 and ENG-A-001 v2 passages | Separate numeric facts, customer request and engineering evidence |
| Final checks | Recheck access and revisions before returning | Reject detected mid-request changes instead of mixing snapshots |

The current report is an **evidence pack**, not an Agent-generated pricing recommendation or customer message. `ready` means the configured request and engineering evidence types were retrieved with complete normalized context for the selected documents within budget. No quote is approved, sent or automatically recalculated.

The default report now returns four passages from two documents, totaling 744 section/text characters in this fixed corpus. It includes the email's `Volume expectation` and the engineering document's `Limits` section. Expansion reads canonical source chunks rather than relying on a sibling being present in the search index. It cannot introduce a different source version or another customer's context.

If a selected document does not fit in the character or chunk budget, it is omitted as a whole and the report becomes `incomplete_context`. The report names the omitted document and reason. It never returns only the convenient first paragraph and labels that document complete. Completeness here covers selected normalized documents, not every potentially relevant document, attachments or arbitrary business conditions.

For discussion, 5% below USD 15.00 is USD 14.25. With the unchanged USD 13.00 cost, gross margin would be about 8.77%, versus 13.33% at USD 15.00. That arithmetic is an illustrative scenario, not a measured business outcome, implemented pricing tool or approved discount. The evidence says there is no approved volume-based cost reduction; the manager still needs a commercial decision.

## Conditions to review

| Condition and exact source | Single-passage baseline | Expanded report |
|---|---|---|
| Future volume is unsigned — MAIL-A-001 v2 c2 | Missing | Present |
| Material and inspection requirements must remain — ENG-A-001 v2 c1 | Present | Present |
| No approved volume cost reduction — ENG-A-001 v2 c2 | Missing | Present |
| Simplification requires engineering review — ENG-A-001 v2 c2 | Missing | Present |

Coverage is 1/4 versus 4/4 for these four manually annotated conditions, with the same documents, versions, query and k=2. This does not measure production accuracy or claim an approved discount.

## Lifecycle demonstration

| Experiment | What is changed | Required outcome |
|---|---|---|
| Update before index refresh | Write approved engineering v3 after caching v2 | Cache invalidates; v2 is excluded; quote context is incomplete |
| Index refresh | Index v3 | The report cites v3, never the superseded v2 |
| Delete before index refresh | Write an engineering tombstone while old chunks exist | No engineering citation, even from the old cache or index |
| Old-event replay | Re-ingest identical v2 after deletion | Tombstone still wins; no resurrection |
| Historical request | Ask for an earlier date after deletion | Current deletion policy still blocks retrieval |
| Index cleanup | Refresh after deletion | Zero indexed chunks remain for that document |
| Permission revocation | Revoke manager A after a cached request | Access denied before SQL/search; no facts or citations returned |

Deletion here means logical exclusion plus index cleanup. Canonical history and already exported reports are retained. Full privacy erasure, backups and distributed policy propagation are not implemented. Demo actor selection is not real authentication.

## How evaluation proves the boundaries

The checked-in query set has nine manually reviewed cases: six positives, one no-answer and two denials. Relevant IDs, exact versions, selected SQL facts and expected status are fixed independently of the search output.

For a positive query with two required documents, retrieving only one gives Recall@2 = 1/2. Retrieving both at k=2 gives Recall@2 = 1 and Precision@2 = 1. Denials and no-answer cases are tested separately. Evaluation also rejects a result with the correct document ID but the wrong version.

Five existing lifecycle experiments cover update, deletion, revocation, conflicting ownership/version writes and an actual new local ETL publication invalidating cached facts. The walkthrough adds an inspectable sequence of thirteen assertions. Adapter tests pass deliberately foreign, stale and forged remote rows through the actual adapter methods; only canonically matching rows survive. They also test SQL arithmetic, denial before network calls, sanitized failures and no silent fallback.

Perfect fixture retrieval is not production accuracy. There are only six positive English queries. Condition coverage checks exact reviewed source spans and their IDs/versions; they are not a semantic judge or a guarantee that every possible business condition was found. Semantic paraphrases, multilingual documents, real Gmail changes, remote index refresh, large-corpus latency and LLM faithfulness remain unverified. No online CloudWatch or Agent monitoring is claimed.

## Interview answer

“Like, say a customer asks for five percent off. I pull the current order numbers from the published ETL data, then retrieve their latest request and the approved engineering explanation. I filter by customer, project and design before ranking. Then I pull in the rest of each selected document, within a fixed budget. Like, the customer may mention more volume, but the next paragraph says nothing is signed. I need that caveat too. Each passage has a source ID and version, so the manager can check it.

The tricky part is stale evidence. If engineering updates the document but the index hasn't caught up, I block the old version rather than give a confident answer. I also test deletion and permission changes after the cache is populated.

For eval, I check the documents, versions, order numbers and specific conditions—not just whether the right file showed up. I deliberately remove the unsigned-volume condition and make sure eval fails. I also check budget limits, denial and no-answer cases. That's implemented locally. The Snowflake and Gmail adapters have offline contract tests; I haven't claimed a live cloud rollout.”

中文要点：订单事实走 SQL，降价要求和工程依据走检索。先判断是否有权、是否有效，再比较相关性。更新、删除和撤权都要在缓存存在时测试。当前已完成本地机制验证，API 调用路径用模拟客户端测试，尚无真实云端质量结论。
