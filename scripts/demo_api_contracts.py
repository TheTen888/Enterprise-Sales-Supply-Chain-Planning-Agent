import argparse
import base64
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from integrations.gmail import GmailReader
from integrations.settings import SnowflakeSettings
from integrations.snowflake import FACT_COLUMNS, CortexRanker, SnowflakeOrderReader
from rag.documents import chunk_document
from rag.retrieval import EvidenceService, lexical_rank
from scripts.run_rag import DEFAULT_QUERY, RAG_FIXTURES, prepare_demo


def demo_contracts(root: Path) -> dict:
    local, as_of = prepare_demo(root / "local")
    arguments = dict(
        actor="demo-manager-a",
        customer="CUSTOMER-A",
        project="PROJECT-A",
        entity="ORDER-A001-L1",
        query=DEFAULT_QUERY,
        as_of=as_of,
        k=2,
    )
    expected = local.retrieve(**arguments)
    facts = expected["facts"]
    candidates = local.store.candidates("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1", "D2", as_of)
    ranked = lexical_rank(DEFAULT_QUERY, candidates)
    settings = SnowflakeSettings(
        "example-account",
        "example-user",
        "RAG_READER",
        "RAG_WH",
        "SALES",
        "CURATED",
        "CURRENT_ORDER_FACTS",
        "DOCUMENT_SEARCH",
        "offline-placeholder-not-a-credential",
    )
    connection, root_client, gmail_client = MagicMock(), MagicMock(), MagicMock()
    connection.cursor.return_value.fetchmany.return_value = [
        tuple(facts[name] for name in FACT_COLUMNS)
    ]
    search = (
        root_client.databases[settings.database]
        .schemas[settings.schema]
        .cortex_search_services[settings.search_service]
        .search
    )
    columns = (
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
    search.return_value = SimpleNamespace(
        results=[
            {name.upper(): row[name] for name in columns}
            for row in ranked
            if row["chunk_id"] in {match["chunk_id"] for match in expected["retrieval_matches"]}
        ]
    )
    cloud_contract = EvidenceService(
        local.store,
        local.warehouse,
        facts_reader=SnowflakeOrderReader(connection, settings),
        ranker=CortexRanker(root_client, settings),
    )
    actual = cloud_contract.retrieve(**arguments)
    message_id = "synthetic-mail-a"
    text = (RAG_FIXTURES / "documents/mail-a-v2.md").read_text()
    gmail_client.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": message_id,
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()},
        },
    }
    mail = GmailReader(
        gmail_client, {message_id: ("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1")}
    ).fetch_document(message_id, version=1, design="D2", effective_on=as_of, observed_on=as_of)
    local.store.put_documents([mail])
    local.store.refresh_index()
    email_in_index = any(
        row["document_id"] == mail.document_id
        for row in local.store.candidates("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1", "D2", as_of)
    )
    same = {row["chunk_id"] for row in actual["citations"]} == {
        row["chunk_id"] for row in expected["citations"]
    }
    execute = connection.cursor.return_value.execute.call_args
    return {
        "passed": actual["status"] == "ready"
        and actual["facts"] == facts
        and same
        and email_in_index,
        "mode": "mocked_sdk_contracts",
        "network_calls": 0,
        "live_integration_verified": False,
        "snowflake_sql": {
            "template": execute.args[0],
            "parameters": list(execute.args[1]),
            "timeout_seconds": execute.kwargs["timeout"],
            "read_count": connection.cursor.return_value.execute.call_count,
        },
        "cortex_search": search.call_args.kwargs,
        "gmail": {
            "get": gmail_client.users.return_value.messages.return_value.get.call_args.kwargs,
            "execute": gmail_client.users.return_value.messages.return_value.get.return_value.execute.call_args.kwargs,
            "chunks": len(chunk_document(mail.body)),
            "indexed_with_trusted_scope": email_in_index,
        },
        "evidence": {
            "status": actual["status"],
            "order_version": facts["business_version"],
            "citations": [row["chunk_id"] for row in actual["citations"]],
            "returned_document_count": actual["returned_document_count"],
            "returned_chunk_count": actual["returned_chunk_count"],
            "context_complete": actual["context"]["complete"],
        },
        "limitations": "Injected fake SDK clients exercise real adapter methods. No SDK installation, authentication, remote service, semantic ranking or cloud synchronization is verified.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise API adapters with fake SDK clients and synthetic records"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="api-contracts-", dir=args.output))
    result = demo_contracts(root)
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({**result, "report": str(root / "report.json")}, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
