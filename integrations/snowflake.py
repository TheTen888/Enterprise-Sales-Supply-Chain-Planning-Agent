from contextlib import contextmanager, suppress

from integrations.settings import SnowflakeSettings, require_live

FACT_COLUMNS = (
    "source",
    "entity_id",
    "customer_id",
    "project_id",
    "business_version",
    "publication_id",
    "design_version",
    "quantity",
    "currency",
    "unit_cost_cents",
    "unit_price_cents",
    "extended_cost_cents",
    "extended_price_cents",
)
SEARCH_COLUMNS = (
    "CHUNK_ID",
    "DOCUMENT_ID",
    "VERSION",
    "CUSTOMER_ID",
    "PROJECT_ID",
    "ENTITY_ID",
    "DESIGN_VERSION",
    "SOURCE_HASH",
    "TEXT",
)


class ProviderError(RuntimeError):
    pass


class SnowflakeOrderReader:
    def __init__(self, connection, settings: SnowflakeSettings):
        self.connection = connection
        self.settings = settings

    def read(self, customer: str, project: str, entity: str) -> dict:
        table = ".".join((self.settings.database, self.settings.schema, self.settings.order_view))
        sql = (
            f"SELECT {', '.join(name.upper() for name in FACT_COLUMNS)} FROM {table} "
            "WHERE CUSTOMER_ID=%s AND PROJECT_ID=%s AND ENTITY_ID=%s LIMIT 2"
        )
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, (customer, project, entity), timeout=10)
            rows = cursor.fetchmany(2)
        except Exception:
            raise ProviderError("Snowflake order read failed; no local fallback") from None
        finally:
            if cursor is not None:
                with suppress(Exception):
                    cursor.close()
        if not rows:
            raise LookupError("no current order in authorized scope")
        if len(rows) != 1 or len(rows[0]) != len(FACT_COLUMNS):
            raise ProviderError("current-order view violated the unique-row contract")
        facts = dict(zip(FACT_COLUMNS, rows[0], strict=True))
        if (facts["customer_id"], facts["project_id"], facts["entity_id"]) != (
            customer,
            project,
            entity,
        ):
            raise ProviderError("current-order view returned a different scope")
        positive = ("quantity", "business_version", "publication_id")
        amounts = (
            "unit_cost_cents",
            "unit_price_cents",
            "extended_cost_cents",
            "extended_price_cents",
        )
        if any(type(facts[name]) is not int or facts[name] < 1 for name in positive):
            raise ProviderError("invalid integer quantity or version")
        if any(type(facts[name]) is not int or facts[name] < 0 for name in amounts):
            raise ProviderError("invalid integer-cent amount")
        if (
            facts["currency"] != "USD"
            or not isinstance(facts["design_version"], str)
            or not facts["design_version"]
        ):
            raise ProviderError("unsupported currency or design version")
        for prefix in ("cost", "price"):
            if (
                facts[f"extended_{prefix}_cents"]
                != facts["quantity"] * facts[f"unit_{prefix}_cents"]
            ):
                raise ProviderError("current-order amounts failed reconciliation")
        return facts


class CortexRanker:
    def __init__(self, root, settings: SnowflakeSettings):
        self.service = (
            root.databases[settings.database]
            .schemas[settings.schema]
            .cortex_search_services[settings.search_service]
        )

    def rank(self, query: str, candidates: list[dict], context: dict) -> list[dict]:
        if not candidates:
            return []
        filters = [
            {"@eq": {name.upper(): context[name]}}
            for name in ("customer_id", "project_id", "entity_id")
        ]
        filters.extend(
            [
                {
                    "@or": [
                        {"@eq": {"DESIGN_VERSION": context["design_version"]}},
                        {"@eq": {"DESIGN_VERSION": ""}},
                    ]
                },
                {"@lte": {"EFFECTIVE_FROM": context["as_of"]}},
                {"@lte": {"OBSERVED_ON": context["as_of"]}},
                {"@or": [{"@eq": {"STATUS": "approved"}}, {"@eq": {"STATUS": "request"}}]},
            ]
        )
        try:
            response = self.service.search(
                query=query, columns=list(SEARCH_COLUMNS), filter={"@and": filters}, limit=40
            )
            rows = response.results
        except Exception:
            raise ProviderError("Cortex Search failed; no local fallback") from None
        if not isinstance(rows, list) or len(rows) > 40:
            raise ProviderError("Cortex Search returned an invalid result envelope")
        canonical = {row["chunk_id"]: row for row in candidates}
        ranked, seen = [], set()
        for remote in rows:
            if not isinstance(remote, dict):
                raise ProviderError("Cortex Search returned an invalid row")
            row = canonical.get(remote.get("CHUNK_ID"))
            if row is None or row["chunk_id"] in seen:
                continue
            names = (
                "chunk_id",
                "document_id",
                "version",
                "customer_id",
                "project_id",
                "entity_id",
                "design_version",
                "source_hash",
                "text",
            )
            if any(remote.get(name.upper()) != row[name] for name in names):
                continue
            seen.add(row["chunk_id"])
            ranked.append({**row, "score": None})
        return ranked


@contextmanager
def open_snowflake(settings: SnowflakeSettings, *, allow_live: bool = False):
    require_live(allow_live)
    connection = None
    try:
        from snowflake.connector import connect
        from snowflake.core import Root

        connection = connect(
            account=settings.account,
            user=settings.user,
            role=settings.role,
            warehouse=settings.warehouse,
            database=settings.database,
            schema=settings.schema,
            authenticator="oauth",
            token=settings.oauth_token,
            paramstyle="format",
            login_timeout=10,
            network_timeout=15,
            session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": 10, "QUERY_TAG": "scoped_rag_read"},
        )
        root = Root(connection)
        reader, ranker = SnowflakeOrderReader(connection, settings), CortexRanker(root, settings)
    except ImportError:
        if connection is not None:
            with suppress(Exception):
                connection.close()
        raise ProviderError("install the optional snowflake dependencies first") from None
    except Exception:
        if connection is not None:
            with suppress(Exception):
                connection.close()
        raise ProviderError("Snowflake connection failed; credentials omitted") from None
    try:
        yield reader, ranker
    finally:
        with suppress(Exception):
            connection.close()
