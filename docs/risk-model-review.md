# Local Risk Model review

v0.2 adds a local delivery-risk prototype. Existing ETL and RAG behavior remains intact. Training uses an optional scikit-learn dependency; inference uses a numeric JSON model and Python's standard library. No model download, paid service or credential is needed. This is source-code publication, not a cloud deployment.

`release-files.txt` defines the exact release file set. The release checker scans working content and indexed blobs, checks local links and rejects private/generated files. GitHub Actions runs lint, full local verification and the release check without cloud secrets. Consult the workflow run for its actual hosted status; local evidence alone does not establish that status.

## Run and inspect

```bash
.venv/bin/python -m pip install -r requirements-risk.txt
.venv/bin/python -m scripts.run_risk_model
.venv/bin/python -m scripts.verify --risk
```

The training command prints a fresh workspace. It contains `synthetic-input.json`, local replay databases produced by the existing ETL, `dataset.json`, `model.json`, `report.json`, `scoring-input.json` and `scores.json`. The scoring files contain all 144 test-period predictions, including six with unavailable labels. `dataset.json` preserves exclusions, purged boundary rows and source lineage; `model.json` records feature order, training scaler, coefficients, selected C, library version, dataset hashes and cutoffs. These generated files stay outside Git. The compact reviewed result is also written to [risk-model evidence](evidence/risk-model.json) by verification.

To score the exported features independently, replace RUN with the printed workspace:

```bash
.venv/bin/python -m scripts.score_risk_model \
  --model RUN/model.json --input RUN/scoring-input.json --output RUN/rescored.json
```

That command needs no labels, outcomes, database or scikit-learn. It is a portable local scoring contract, not a Snowflake UDF or Model Registry deployment. The target remains SageMaker training with approved batch scoring in Snowflake.

## Label contract

The unit is one active order line at one weekly prediction date. Its frozen committed delivery date must fall within the next 30 days; this fixture uses a 14-day horizon. Freeze both promised quantity and due date at prediction time. Sum partial deliveries to determine the earliest date the frozen quantity was fulfilled:

- `1`: full committed quantity arrived after the frozen due date.
- `0`: full committed quantity arrived on or before that date; there is no grace period here.
- Exclude: open, cancelled, incomplete or not-yet-mature outcomes. Do not turn missing outcomes into on-time labels.

The source must be closed after the due date, all delivery observations must be present by closure, and the label must be available before the fitting/evaluation cutoff. This is deliberately a conservative completed-order cohort. It does not measure unresolved overdue orders; production needs an authoritative closed-through watermark and an agreed right-censoring policy for them. A later negotiated date does not rewrite this historical target. A separate operational metric may legitimately use the latest agreement; do not mix those definitions.

## Features available at prediction

| Feature | Definition | Business meaning |
|---|---|---|
| Order quantity | Published quantity at prediction | Size of the frozen commitment |
| Capacity load | All committed shared-line units / (gross capacity × historical yield), same window | Competition for usable capacity |
| Schedule slack | Frozen due date − planned finish, in days | Negative means the current plan already misses the promise |
| Recent yield | Historical good-unit ratio, measurement window ends before prediction | Recent usable output, never final future yield |
| Design changes | Known change count over the prior 30 days | Potential disruption and rework |
| Allocation utilization | Committed quarterly units / allocated quarterly units | Commitments above allocated share exceed 1 |
| Pickup forecast gap | max(0, forecast pickup − confirmed pickup) / forecast pickup | Unconfirmed volume relative to forecast; not automatically a delay |

IDs, actual delivery dates, final yield, label and later renegotiated deadlines are not model inputs. The prototype consumes trusted planning snapshots; deriving rolling yield/change counts from event-level manufacturing records is future work. Missing critical denominators, invalid yield, ownership mismatches and future measurement windows fail rather than receiving convenient defaults. These are candidate features, not established high-importance factors; real data and business review must establish predictive value.

## Order walkthrough

`ORDER-41-05`, a fictional Customer B order, is predicted on October 20, 2025:

1. The original ETL has published v1: 12,000 units. The model-side ledger shows it became available October 20. A retroactive v2 increases quantity to 14,000, but is not observed until October 23; it is excluded from this prediction.
2. The known plan promises November 3, while planned completion is November 8: slack = −5 days. The plan reports two recent design changes.
3. Shared-line gross capacity is 216,000 units. Prior yield is 89.9%, so usable capacity is 194,184. Total commitments are 134,099: load ≈ 69.1%. The line is not overloaded overall; this order still has a scheduling problem. Quarterly allocation is 66,000 against commitments of 78,023: utilization ≈ 118.2%. Pickup forecast is 15,000 against confirmed pickup of 12,055: gap ≈ 19.6%.
4. Training-standardized features enter logistic regression. The portable model returns a risk score of about 59.7 on a 0–100 scale. It is an uncalibrated synthetic probability estimate, not a guaranteed 59.7% real-world delay rate. The model does not calculate scores by asking an LLM or manually adding feature weights.
5. The order ships 4,000 units on October 28 and 8,000 on November 4. Full original quantity arrived one day late: label = 1. Source closure confirms the label on November 6.
6. A later plan revises the promise to November 10. Using that date would incorrectly make this historical label 0. A negative test demonstrates this exact failure mode. The correct historical features and label continue using November 3.

As a contrast, `ORDER-41-07` receives about 63.9 but actually finishes on time. A risk score is not a verdict. This fixture records no intervention, so we cannot explain the outcome as a successful human rescue.

## Temporal training and evaluation

The split is fixed by prediction date, not random rows. Labels must additionally be available strictly before each cutoff:

| Partition | Prediction window | Retained rows | Labels needed before |
|---|---|---:|---|
| Train | Jan 6–Jul 28, 2025 | 320 | Aug 4, 2025 |
| Validation | Aug 4–Oct 6, 2025 | 81 | Oct 13, 2025 |
| Test | Oct 13–Dec 29, 2025 | 138 | Feb 1, 2026 |

Of 624 orders, four open, four cancelled and six globally unmatured rows are excluded. Another 34 train and 37 validation rows are purged because their outcomes were not available at the relevant boundary. Retained train predictions end July 14 and validation predictions end September 22. All 624 inputs reconcile to retained, excluded or purged rows. Each order occurs only once, preventing the same order from crossing splits.

`StandardScaler` is fit only on train. Three predeclared logistic-regression C values (0.1, 1, 10) are compared using validation average precision. C=10 is selected in this fixed run. Test is used only after selection; no validation refit, threshold tuning or probability calibration is performed. This is one holdout, not repeated temporal cross-validation or evidence of generalization to unseen customers.

The fixed rule index is `0.45 × clip((load−0.8)/0.5) + 0.35 × clip((3−slack)/10) + 0.20 × clip((1−yield)/0.2)`, with clip bounded to 0–1. It is a ranking index, not a calibrated probability. Both systems alert on the top ceil(25%) of all point-in-time eligible orders in each weekly cohort. The alert list is selected before matching mature labels. Equal scores are broken by order ID, never by label. Orders without confirmed outcomes still consume alert budget.

| Holdout metric | Rules | Logistic model |
|---|---:|---:|
| Scored orders / labeled orders / known late orders | 144 / 138 / 46 | 144 / 138 / 46 |
| Alerts | 36 | 36 |
| Alerts awaiting labels | 2 | 1 |
| Known true positives / false positives / false negatives | 25 / 9 / 21 | 25 / 10 / 21 |
| Precision on labeled alerts | 73.5% | 71.4% |
| Precision bounds across all alerts | 69.4–75.0% | 69.4–72.2% |
| Recall among known late orders | 54.3% | 54.3% |
| Average precision | 0.6611 | 0.7207 |
| ROC-AUC | 0.7713 | 0.8396 |

Model Brier score is 0.1566 versus 0.2259 for the train-prevalence constant. The rule index is not treated as a probability for Brier comparison. Exported scoring agrees with scikit-learn within 2.23e-16 in this local run.

**Decision:** retain the rules baseline. The model ranks better across thresholds but does not improve observed recall at the actual alert budget. Do not promote it or claim a production uplift on this evidence. Unknown alerts are neither false positives nor successful predictions. The precision bounds show the extremes if every pending label were on time or late; they are not confidence intervals. AP, ROC-AUC and Brier use only mature outcomes and may have outcome-availability bias. Real evaluation needs multiple temporal windows, uncertainty and planner workload. Shared-capacity interventions require line-level or scheduling-cluster comparisons so improving one order does not hide damage to another.

The earlier review selected alerts only within 138 labeled orders and reported 26 detections / 56.5% recall. v0.2 corrects that procedure: all 144 predictions compete for the same budget before outcome matching, producing 25 known detections / 54.3% recall. The data seed, model selection and alert fraction were not changed to improve the result.

## Leakage and correctness evidence

The automated tests and the report audit cover:

- Historical joins require effective, observed and simulated availability dates at or before prediction. Current ETL v2 cannot replace the historical v1.
- Mutating future plans/capacity or all outcome records cannot change past features.
- Injected future evidence and unavailable training labels make the audit fail.
- Historical yield must end before prediction; zero allocation, invalid capacity and wrong ownership fail.
- Partial-shipment arithmetic, exact due-date boundary and frozen quantity are checked independently of model fitting.
- Later negotiated dates cannot relabel the original promise as on time.
- Open, cancelled, incomplete and immature cases are not labeled as safe.
- Train-only scaler means match independent arithmetic. Poisoning holdout labels and features cannot change selected C or fitted parameters.
- A hand-counted alert example validates precision/recall; exported JSON scoring is compared against the fitted pipeline.
- A high-scoring unlabeled order must consume an alert slot. Updating its outcome cannot change which order was selected.
- Invalid dates, duplicate outcome records, noninteger shipment quantities and impossible scoring features are rejected.
- A subprocess scores an exported model with site packages disabled, proving inference does not import scikit-learn or a cloud SDK.

These checks verify specified failure cases. They do not prove every possible source, target or statistical leakage is eliminated.

## Short interview answer

“I started with a simple question: based on what we knew that day, would this order miss its original delivery commitment? Like, if the customer later agreed to a new date, I wouldn't rewrite the old label. I reused our incremental ETL, then joined historical capacity and planning snapshots. The main signals were schedule slack, shared-line load, yield, allocation and pickup gaps.

“I trained a small logistic model and compared it with fixed rules on a later time period. Same alert budget for both. The local synthetic test gave them the same recall, even though the model's overall ranking was better. So I kept the rules baseline. The useful result here is a reproducible training and evaluation pipeline—not a claim that synthetic accuracy proves business impact.”

## Remaining work

Real CDC timestamps and complete history; authenticated permissions; real labels and source watermarks; calibration; multiple time-based folds; cost-sensitive alert policies; production monitoring; intervention-aware business evaluation; approved model registration; SageMaker training and Snowflake batch scoring. None of those services is called by this prototype.
