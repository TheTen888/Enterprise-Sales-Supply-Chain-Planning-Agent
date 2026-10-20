# Optional API adapters

## Status

The local ETL and RAG remain the default. Optional adapters now contain executable Snowflake SQL, Cortex Search and read-only Gmail SDK call paths. Tests inject fake clients into these same adapters. **No SDK has been installed for this change, and no remote authentication, mailbox, warehouse, index or paid API has been used or verified.**

This is a reviewable integration boundary, not a claim that the cloud architecture is deployed. `scripts.run_rag` remains fully local. S3 ingestion, Airflow/dbt execution, AWS model APIs and cloud synchronization are still planned.

## Review without credentials

```bash
.venv/bin/python -m scripts.demo_api_contracts
.venv/bin/python -m unittest discover -s tests -p test_api_adapters.py -v
```

The contract demo uses invented records and injected fake SDK clients. It calls the actual adapter methods, routes their results through `EvidenceService`, and records the SQL template, bound scope values, Cortex filter and Gmail get parameters. It labels its mode `mocked_sdk_contracts` and `live_integration_verified: false`. It does not authenticate or measure remote search quality.

## Configuration and credentials

`.env.example` contains empty account/token fields and generic object names. `.env` and credential/key files are ignored. Nothing automatically reads `.env`, prints environment variables or enables cloud access when a module is imported. Local commands need no configuration.

`SnowflakeSettings.from_env()` reads only the named Snowflake settings. Its token is excluded from its representation. Provider failures are converted to fixed error messages instead of echoing SDK errors. Tokens still exist in process memory if a future operator supplies them; this is not a secret manager. Do not enable SDK debug logs or publish real data and reports.

Both live factories require `allow_live=True` **and** `ALLOW_LIVE_SERVICES=true`. Neither is enabled by default. Use approved runtime secret injection for a future integration, not committed token files. Gmail token acquisition, refresh and expiry recovery are not implemented here.

The optional extras are declared in `pyproject.toml`. If a future authorized integration needs them, an editable install from the repository root is supported by the package configuration:

```bash
python -m pip install -e '.[snowflake,gmail]'
```

This command has not been run. The declared dependency ranges are not a tested lockfile.

## Snowflake SQL tool

`integrations/snowflake.py` uses `snowflake.connector.connect(...)`, OAuth and `snowflake.core.Root(connection)`. The SQL reader executes a fixed SELECT against a configured current-order view. Object names must match a restricted uppercase identifier grammar. Customer, project and order values are bound parameters, never generated SQL.

The reader limits the result to two rows to detect a broken uniqueness contract. It rejects the wrong scope, duplicate current rows, non-integer amounts, unsupported currency and totals that do not equal quantity times unit amount. Query execution has a ten-second timeout; cursors and connections are closed.

The configured view must supply exactly these columns, in this contract:

```text
SOURCE, ENTITY_ID, CUSTOMER_ID, PROJECT_ID, BUSINESS_VERSION, PUBLICATION_ID,
DESIGN_VERSION, QUANTITY, CURRENCY, UNIT_COST_CENTS, UNIT_PRICE_CENTS,
EXTENDED_COST_CENTS, EXTENDED_PRICE_CENTS
```

`BUSINESS_VERSION`, `PUBLICATION_ID` and `QUANTITY` must be positive integers. Monetary columns are nonnegative integer cents in USD. The view must exclude deleted/unpublished orders and expose one authoritative current version per customer/project/order. This repository does not provision that view, its publication protocol or the warehouse. The local ETL demonstrates the contract separately.

Use an administrator-approved role restricted to SELECT on the curated view, required database/schema/warehouse usage and search-service usage. Naming a role `RAG_READER` does not create or enforce those grants. Do not use an administrator role. Database row policies and a trusted authentication/authorization service are additional production requirements.

## Cortex Search tool

`CortexRanker` resolves a configured service through `Root.databases[...].schemas[...].cortex_search_services[...]`, then calls `.search(query=..., columns=..., filter=..., limit=40)`.

The service source must expose the requested columns and declare these filter fields as ATTRIBUTES:

```text
CUSTOMER_ID, PROJECT_ID, ENTITY_ID, DESIGN_VERSION, EFFECTIVE_FROM, OBSERVED_ON, STATUS
```

Requested result columns are `CHUNK_ID`, `DOCUMENT_ID`, `VERSION`, the scope/design fields, `SOURCE_HASH` and `TEXT`. Dates must use compatible DATE values. A document without a design constraint uses an empty design string, not NULL. Chunk IDs, normalized text and hashes must match the canonical document pipeline.

Filters constrain customer, project, order, design, effective/observed date and eligible status before results are returned. The adapter then intersects remote hits with locally authorized canonical candidates, comparing chunk ID, document ID, version, scope, design, text and hash. Remote hits cannot create grants or replace canonical text. The search results select up to k distinct documents. The common EvidenceService then hydrates their same-version canonical chunks under the local context budget. Only the seed passages need to be returned by Cortex; additional context is read from the trusted canonical store, not invented by the model. A cloud failure raises an error rather than silently using a different backend.

**Cortex Search runs with owner's rights. Source-table permissions do not automatically isolate each application user.** Only the trusted backend should hold the service credential. The application must authenticate users, derive scope from trusted policy, apply filters and recheck results. This demo still uses static principals and local grants; it is not production login.

The canonical store remains local in this optional adapter boundary. It must be synchronized with the future cloud document source and policy service before claiming production freshness or revocation guarantees. No synchronization, index upload, remote index refresh or distributed snapshot is implemented. Local update/delete/revoke tests validate the canonical checks against stale **mocked** remote results, not actual remote propagation.

The 40-hit pool is bounded. Invalid/stale hits may crowd out useful results; rejection remains safe but recall can fall. There is no automatic unbounded refill. Measure that trade-off on a reviewed semantic dataset before a rollout.

## Gmail source tool

`integrations/gmail.py` builds a Gmail v1 client with a requested `gmail.readonly` scope. `fetch_document` invokes `users().messages().get(userId='me', id=..., format='full').execute(num_retries=0)`. There is no sending method.

Only message IDs already mapped by separately trusted configuration to a customer/project/order may be fetched. Email text cannot assign its own ownership or approve a quote. A fetched message becomes a `customer_request` document and can enter the existing `put_documents → refresh_index → scoped retrieval` path.

The helper supports bounded UTF-8 plain-text MIME parts. It skips attachments, rejects HTML-only messages and limits MIME nodes and decoded text. A trusted caller supplies the monotonic business version, design and effective/observed dates. This helper does not infer those fields from untrusted email text.

The requested SDK scope does not downgrade an already overprivileged OAuth token. The real OAuth grant must itself be restricted to read-only access. There is no live scope verification in this phase. Mailbox discovery, Gmail history cursors, thread supersession, deletion notifications, backoff, token refresh and attachment parsing remain future connector work.

## Wiring for a future authorized integration

This is a composition example, not a command used by the local demo:

```python
from integrations.settings import SnowflakeSettings
from integrations.snowflake import open_snowflake
from rag.retrieval import EvidenceService

settings = SnowflakeSettings.from_env()
with open_snowflake(settings, allow_live=True) as (facts_reader, ranker):
    service = EvidenceService(store, warehouse_path, facts_reader=facts_reader, ranker=ranker)
    pack = service.retrieve(actor, customer, project, order, query, as_of, k=2)
```

`store` must already contain trusted, synchronized canonical documents and grants; `actor` must come from authenticated backend identity. This is not a public endpoint accepting arbitrary actor names. The same service checks access before facts/search and again before return. It rereads order facts to detect changes during the request. Those two reads cost extra SQL work and still do not constitute a distributed transaction.

## Official API references

- [Snowflake Cortex Search querying, filters and owner's-rights behavior](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/query-cortex-search-service)
- [Snowflake Connector query parameters, binding and timeouts](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-example)
- [Gmail message get and supported OAuth scopes](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get)
- [Gmail Python client setup](https://developers.google.com/workspace/gmail/api/quickstart/python)
