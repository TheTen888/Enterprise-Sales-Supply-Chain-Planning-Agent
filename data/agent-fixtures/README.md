# Synthetic quote scenario

`scenario.json` supplies trusted planning inputs and an explicitly invented pricing policy for the existing Customer A / Project A discount example. It is not customer data, a production approval rule or an industry margin benchmark.

Order numbers and approved unit cost come from the existing ETL. Email and engineering passages come from the existing scoped RAG fixture. The four reviewed conditions pin specific source passages and versions; a changed or missing condition blocks generation until reviewed extraction rules are updated. This is a narrow deterministic extractor, not a general language-understanding model. Quoted email history does not become a new request.

The demo policy requires at least 10% gross margin, using `(price - cost) / price`. Published unit cost is USD 13.00 and current price is USD 15.00. A 5% discount requests USD 14.25, below the invented policy floor. The lowest cent price meeting that floor is USD 14.45. That is a policy-constrained draft option, not an optimized negotiation strategy or an approved customer price.

The continuous-line planning example has ten production slots before the due date, 2,000 gross units per slot and 90% historical yield. There are 18,000 usable units, including work for another project. Other commitments consume 4,000 units. A 12,000-unit order needs nine slots in the aggregate calculation; an 18,000-unit what-if needs thirteen and creates a 4,000-unit shortfall. This ignores setup, priorities, calendars and product-specific work content; it must not promise a feasible detailed production schedule.

Manager revisions are hypotheses. They do not write back to ETL or imply signed customer volume, confirmed pickup or approved volume discounts. Unit cost remains unchanged until new authoritative evidence justifies a change. The synthetic risk model is reused without retraining; inferred scores are advisory and unpromoted. An 18,000-unit scenario exceeds the training quantity range and is labeled accordingly.
