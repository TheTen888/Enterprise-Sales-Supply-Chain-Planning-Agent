# Invented RAG corpus and reviewed cases

All documents and identities are fictional. These are not sanitized copies of real mail or engineering files.

- `manifest.json`: trusted document ownership, versions, status, applicability and source paths.
- `access.json`: two static demo identities and their allowed customer/project scopes.
- `documents/`: eight Markdown source versions across six document IDs.
- `eval-cases.json`: manually reviewed question, source-version and SQL-fact expectations.

The fixed document date is 2026-10-19. The order source is the existing ETL fixture: A001 v3, D2, 12,000 units, USD 13.00 unit cost; B001 v2, D1, 4,500 units, USD 8.50 unit cost. Numeric order facts come from read-only ETL SQL, not document text.

| Document | Purpose |
|---|---|
| MAIL-A-001 v1/v2 | Superseded three-percent request versus current five-percent request |
| ENG-A-001 v1/v2 | Historical D1 explanation versus approved D2 material/inspection rationale |
| SHIP-A-001 | Irrelevant or separately relevant packaging evidence |
| ENG-A-DRAFT | Unapproved, keyword-rich proposal that must not support an approved explanation |
| MAIL-B-001 / ENG-B-001 | Similar content for another customer, to test isolation |

The old D1 cost is intentionally present as a distractor. The reader must not replace current D2 SQL facts with it. The newer A email includes quoted history and a signature to exercise simple chunk cleaning.

The nine evaluation cases cover six positive retrieval questions, one missing-evidence question and two authorization failures. Four cases additionally carry manually reviewed condition IDs, exact source/chunk versions and required text spans. This tests unsigned future volume, mandatory engineering requirements, no approved volume cost reduction and required engineering review. Expected document IDs and versions were written into the fixture independently of retrieval output. The lexical test queries intentionally use corpus vocabulary. These cases verify local contracts; they do not establish broader search accuracy or business impact.

`access.json` simulates backend authorization configuration. A local CLI actor flag is not proof of user identity. Production authentication and cost-specific field permissions remain unimplemented.
