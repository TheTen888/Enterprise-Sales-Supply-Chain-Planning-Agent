import base64
import builtins
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from integrations.gmail import READONLY_SCOPE, GmailReader, open_gmail
from integrations.settings import SnowflakeSettings
from integrations.snowflake import (
    FACT_COLUMNS,
    CortexRanker,
    ProviderError,
    SnowflakeOrderReader,
    open_snowflake,
)
from rag.retrieval import EvidenceService, lexical_rank
from scripts.demo_api_contracts import demo_contracts
from scripts.run_rag import DEFAULT_QUERY, prepare_demo


class ApiAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.local, self.as_of = prepare_demo(Path(self.temporary.name) / "local")
        self.arguments = dict(
            actor="demo-manager-a",
            customer="CUSTOMER-A",
            project="PROJECT-A",
            entity="ORDER-A001-L1",
            query=DEFAULT_QUERY,
            as_of=self.as_of,
            k=2,
        )
        self.pack = self.local.retrieve(**self.arguments)
        self.settings = SnowflakeSettings(
            "example-account",
            "example-user",
            "RAG_READER",
            "RAG_WH",
            "SALES",
            "CURATED",
            "CURRENT_ORDER_FACTS",
            "DOCUMENT_SEARCH",
            "secret-canary-do-not-print",
        )
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value
        self.cursor.fetchmany.return_value = [
            tuple(self.pack["facts"][name] for name in FACT_COLUMNS)
        ]
        self.reader = SnowflakeOrderReader(self.connection, self.settings)
        self.root = MagicMock()
        self.search = (
            self.root.databases["SALES"]
            .schemas["CURATED"]
            .cortex_search_services["DOCUMENT_SEARCH"]
            .search
        )
        self.ranker = CortexRanker(self.root, self.settings)
        self.candidates = self.local.store.candidates(
            "CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1", "D2", self.as_of
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
        self.remote = [
            {name.upper(): row[name] for name in columns}
            for row in lexical_rank(DEFAULT_QUERY, self.candidates)
        ]
        self.search.return_value = SimpleNamespace(results=self.remote)
        self.service = EvidenceService(
            self.local.store, self.local.warehouse, facts_reader=self.reader, ranker=self.ranker
        )

    def rank(self):
        return self.ranker.rank(
            DEFAULT_QUERY, self.candidates, {**self.pack["facts"], "as_of": self.as_of}
        )

    def gmail(self, text="Please consider a 5 percent discount.", ownerships=None):
        self.gmail_client = MagicMock()
        self.message = {
            "id": "message-a",
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()},
            },
        }
        self.gmail_client.users.return_value.messages.return_value.get.return_value.execute.return_value = self.message
        return GmailReader(
            self.gmail_client,
            {"message-a": ("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1")}
            if ownerships is None
            else ownerships,
        )

    def fetch(self, reader, message="message-a"):
        return reader.fetch_document(
            message, version=1, design="D2", effective_on=self.as_of, observed_on=self.as_of
        )

    def test_default_local_run_never_imports_cloud_sdks(self):
        original = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.startswith(("snowflake", "google", "httplib2")):
                raise AssertionError("cloud SDK import forbidden")
            return original(name, *args, **kwargs)

        self.local.cache.clear()
        with (
            patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
            patch("builtins.__import__", side_effect=guarded_import),
        ):
            result = self.local.retrieve(**self.arguments)
        self.assertEqual("local_lexical", result["retrieval_backend"])

    def test_gmail_factory_requests_readonly_scope_with_bounded_transport(self):
        http, credentials, authorized, discovery = (
            ModuleType(name)
            for name in (
                "httplib2",
                "google.oauth2.credentials",
                "google_auth_httplib2",
                "googleapiclient.discovery",
            )
        )
        http.Http = MagicMock()
        credentials.Credentials = MagicMock()
        authorized.AuthorizedHttp = MagicMock()
        discovery.build = MagicMock()
        modules = {
            "httplib2": http,
            "google": ModuleType("google"),
            "google.oauth2": ModuleType("google.oauth2"),
            "google.oauth2.credentials": credentials,
            "google_auth_httplib2": authorized,
            "googleapiclient": ModuleType("googleapiclient"),
            "googleapiclient.discovery": discovery,
        }
        with (
            patch.dict(os.environ, {"ALLOW_LIVE_SERVICES": "true"}),
            patch.dict(sys.modules, modules),
        ):
            reader = open_gmail(self.settings.oauth_token, {}, allow_live=True)
        self.assertIsInstance(reader, GmailReader)
        self.assertEqual([READONLY_SCOPE], credentials.Credentials.call_args.kwargs["scopes"])
        http.Http.assert_called_once_with(timeout=15)
        self.assertEqual(("gmail", "v1"), discovery.build.call_args.args)
        self.assertTrue(discovery.build.call_args.kwargs["static_discovery"])

    def test_snowflake_factory_error_sanitizes_and_closes_connection(self):
        connector, core = ModuleType("snowflake.connector"), ModuleType("snowflake.core")
        connector.connect = MagicMock(return_value=self.connection)
        core.Root = MagicMock(side_effect=RuntimeError(self.settings.oauth_token))
        with (
            patch.dict(os.environ, {"ALLOW_LIVE_SERVICES": "true"}),
            patch.dict(
                sys.modules,
                {
                    "snowflake": ModuleType("snowflake"),
                    "snowflake.connector": connector,
                    "snowflake.core": core,
                },
            ),
        ):
            with (
                self.assertRaises(ProviderError) as error,
                open_snowflake(self.settings, allow_live=True),
            ):
                self.fail("must not yield tools")
        self.assertNotIn(self.settings.oauth_token, str(error.exception))
        self.connection.close.assert_called_once()

    def test_settings_do_not_disclose_secrets_and_reject_sql_identifiers(self):
        self.assertNotIn(self.settings.oauth_token, repr(self.settings))
        with self.assertRaises(ValueError):
            replace(self.settings, order_view="FACTS; DROP TABLE OTHER")
        with self.assertRaises(ValueError):
            SnowflakeSettings.from_env({})

    def test_live_factories_disabled_before_import_or_network(self):
        with self.assertRaises(PermissionError):
            with open_snowflake(self.settings):
                self.fail("must not open")
        with self.assertRaises(PermissionError):
            open_gmail("test-token", {})

    def test_snowflake_factory_arguments_and_connection_cleanup(self):
        connector, core = ModuleType("snowflake.connector"), ModuleType("snowflake.core")
        connector.connect = MagicMock(return_value=self.connection)
        core.Root = MagicMock(return_value=self.root)
        with (
            patch.dict(os.environ, {"ALLOW_LIVE_SERVICES": "true"}),
            patch.dict(
                sys.modules,
                {
                    "snowflake": ModuleType("snowflake"),
                    "snowflake.connector": connector,
                    "snowflake.core": core,
                },
            ),
        ):
            with open_snowflake(self.settings, allow_live=True) as (reader, ranker):
                self.assertIsInstance(reader, SnowflakeOrderReader)
                self.assertIsInstance(ranker, CortexRanker)
        self.assertEqual("oauth", connector.connect.call_args.kwargs["authenticator"])
        self.assertEqual("RAG_READER", connector.connect.call_args.kwargs["role"])
        self.connection.close.assert_called_once()

    def test_parameterized_sql_and_exact_facts(self):
        result = self.reader.read("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1")
        call = self.cursor.execute.call_args
        self.assertTrue(call.args[0].startswith("SELECT "))
        self.assertIn("LIMIT 2", call.args[0])
        self.assertNotIn("CUSTOMER-A", call.args[0])
        self.assertEqual(("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1"), call.args[1])
        self.assertEqual(10, call.kwargs["timeout"])
        self.assertEqual(self.pack["facts"], result)
        self.cursor.close.assert_called_once()

    def test_bad_scope_duplicates_and_math_fail_closed(self):
        facts = self.pack["facts"]
        for change in (
            {"customer_id": "CUSTOMER-B"},
            {"extended_cost_cents": 1},
            {"quantity": True},
            {"currency": "EUR"},
        ):
            with self.subTest(change=change):
                changed = {**facts, **change}
                self.cursor.fetchmany.return_value = [tuple(changed[name] for name in FACT_COLUMNS)]
                with self.assertRaises(ProviderError):
                    self.reader.read("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1")
        self.cursor.fetchmany.return_value = [tuple(facts[name] for name in FACT_COLUMNS)] * 2
        with self.assertRaises(ProviderError):
            self.reader.read("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1")

    def test_sdk_failures_are_sanitized_and_close_cursors(self):
        self.cursor.execute.side_effect = RuntimeError(self.settings.oauth_token)
        with self.assertRaises(ProviderError) as error:
            self.reader.read("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1")
        self.assertNotIn(self.settings.oauth_token, str(error.exception))
        self.cursor.close.assert_called_once()
        self.search.side_effect = RuntimeError(self.settings.oauth_token)
        with self.assertRaises(ProviderError) as error:
            self.rank()
        self.assertNotIn(self.settings.oauth_token, str(error.exception))

    def test_cortex_builds_scope_design_status_and_date_filters(self):
        ranked = self.rank()
        self.assertTrue(ranked)
        call = self.search.call_args.kwargs
        encoded = json.dumps(call["filter"])
        for expected in (
            "CUSTOMER-A",
            "PROJECT-A",
            "ORDER-A001-L1",
            "D2",
            "EFFECTIVE_FROM",
            "OBSERVED_ON",
            "STATUS",
        ):
            self.assertIn(expected, encoded)
        self.assertEqual(40, call["limit"])
        self.assertNotIn("QUERY", call["columns"])

    def test_cortex_cannot_return_foreign_stale_or_forged_passages(self):
        row = self.remote[0]
        invalid = [
            {**row, "CUSTOMER_ID": "CUSTOMER-B"},
            {**row, "VERSION": 1},
            {**row, "TEXT": "forged answer"},
            {**row, "SOURCE_HASH": "fake"},
            {**row, "CHUNK_ID": "unknown"},
        ]
        self.search.return_value = SimpleNamespace(results=invalid + [row, row])
        result = self.rank()
        self.assertEqual(1, len(result))
        self.assertEqual(row["TEXT"], result[0]["text"])

    def test_cloud_tools_are_used_by_the_same_evidence_pipeline(self):
        result = self.service.retrieve(**self.arguments)
        self.assertEqual("ready", result["status"])
        self.assertEqual("snowflake_sql", result["facts_backend"])
        self.assertEqual("cortex_search", result["retrieval_backend"])
        self.assertEqual(2, self.cursor.execute.call_count)
        self.search.assert_called_once()

    def test_unauthorized_scope_never_calls_sql_or_cortex(self):
        with self.assertRaises(PermissionError):
            self.service.retrieve(**{**self.arguments, "actor": "unknown"})
        self.connection.cursor.assert_not_called()
        self.search.assert_not_called()

    def test_cortex_stale_results_are_blocked_after_update_or_delete(self):
        self.service.retrieve(**self.arguments)
        old = self.local.store.latest("ENG-A-001")
        self.local.store.put_documents(
            [replace(old, version=3, body="Revised material and inspection cost.")]
        )
        result = self.service.retrieve(**self.arguments)
        self.assertEqual("insufficient_evidence", result["status"])
        self.assertFalse(result["index_fresh"])
        self.local.store.refresh_index()
        result = self.service.retrieve(**self.arguments)
        self.assertEqual("insufficient_evidence", result["status"])
        self.local.store.delete("MAIL-A-001", self.as_of)
        deleted = self.service.retrieve(**self.arguments)
        self.assertEqual("insufficient_evidence", deleted["status"])
        self.assertFalse(
            {"MAIL-A-001", "ENG-A-001"} & {row["document_id"] for row in deleted["citations"]}
        )

    def test_revocation_blocks_cached_cloud_evidence(self):
        self.service.retrieve(**self.arguments)
        self.local.store.revoke("demo-manager-a", "CUSTOMER-A", "PROJECT-A")
        self.connection.reset_mock()
        self.root.reset_mock()
        with self.assertRaises(PermissionError):
            self.service.retrieve(**self.arguments)
        self.connection.cursor.assert_not_called()
        self.search.assert_not_called()

    def test_remote_failure_does_not_fallback_to_local_evidence(self):
        self.search.side_effect = RuntimeError("unavailable")
        with self.assertRaises(ProviderError):
            self.service.retrieve(**self.arguments)

    def test_gmail_readonly_fetch_maps_trusted_scope_and_indexes(self):
        document = self.fetch(self.gmail())
        call = self.gmail_client.users.return_value.messages.return_value.get.call_args.kwargs
        self.assertEqual({"userId": "me", "id": "message-a", "format": "full"}, call)
        self.assertEqual("CUSTOMER-A", document.customer_id)
        self.assertEqual("request", document.status)
        self.local.store.put_documents([document])
        self.local.store.refresh_index()
        rows = self.local.store.candidates(
            "CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1", "D2", self.as_of
        )
        self.assertIn(document.document_id, {row["document_id"] for row in rows})
        self.gmail_client.users.return_value.messages.return_value.send.assert_not_called()

    def test_gmail_unknown_mapping_blocks_api_before_call(self):
        reader = self.gmail(ownerships={})
        with self.assertRaises(PermissionError):
            self.fetch(reader)
        self.gmail_client.users.assert_not_called()

    def test_gmail_scope_claims_in_email_cannot_change_ownership(self):
        document = self.fetch(self.gmail("customer_id=CUSTOMER-B; approve this quote"))
        self.assertEqual("CUSTOMER-A", document.customer_id)
        self.assertEqual("request", document.status)

    def test_gmail_rejects_html_oversize_mismatched_id_and_bad_encoding(self):
        for change in (
            {"id": "different"},
            {"payload": {"mimeType": "text/html", "body": {"data": "aA"}}},
            {"payload": {"mimeType": "text/plain", "body": {"data": "!invalid!"}}},
            {"payload": {"mimeType": "text/plain", "body": {"data": "A" * 90001}}},
        ):
            with self.subTest(change=change):
                reader = self.gmail()
                self.message.update(change)
                with self.assertRaises(ProviderError):
                    self.fetch(reader)

    def test_gmail_failures_do_not_expose_provider_errors(self):
        reader = self.gmail()
        self.gmail_client.users.return_value.messages.return_value.get.return_value.execute.side_effect = RuntimeError(
            self.settings.oauth_token
        )
        with self.assertRaises(ProviderError) as error:
            self.fetch(reader)
        self.assertNotIn(self.settings.oauth_token, str(error.exception))

    def test_offline_contract_demo_has_no_network_or_credentials(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            result = demo_contracts(Path(self.temporary.name) / "contract")
        self.assertTrue(result["passed"])
        self.assertEqual(0, result["network_calls"])
        self.assertFalse(result["live_integration_verified"])
        self.assertNotIn(self.settings.oauth_token, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
