# Changelog

## 0.2.0

- Add synthetic delivery-risk training on the existing incremental ETL, with shared-line capacity and planning snapshots.
- Freeze quantity and delivery promises at prediction time; enforce effective, observed and availability dates and purge immature labels at temporal boundaries.
- Compare train-only logistic regression with fixed rules under the same weekly alert budget. Select alerts across all eligible orders before matching outcomes; report pending labels separately.
- Export a numeric JSON model and label-free batch inputs; verify scoring independently without installed ML packages.
- Extend regression tests, input contracts, verification evidence and GitHub Actions. Retain rules as baseline; synthetic results do not justify production promotion.

## 0.1.0

- Local incremental ETL, atomic publication, replay and fault recovery.
- Scoped lexical RAG with version/deletion/access checks and bounded document context.
- Synthetic order/email/engineering examples, fake-client Snowflake/Gmail contracts and minimal CI.
