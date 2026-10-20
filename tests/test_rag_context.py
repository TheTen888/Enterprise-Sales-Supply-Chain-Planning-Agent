import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from rag.evaluation import condition_checks, evaluate_cases
from rag.retrieval import render_report
from scripts.run_rag import DEFAULT_QUERY, RAG_FIXTURES, prepare_demo


class RagContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.service, self.as_of = prepare_demo(Path(self.temporary.name) / "run")
        self.arguments = dict(
            actor="demo-manager-a",
            customer="CUSTOMER-A",
            project="PROJECT-A",
            entity="ORDER-A001-L1",
            query=DEFAULT_QUERY,
            as_of=self.as_of,
            k=2,
        )
        self.conditions = json.loads((RAG_FIXTURES / "eval-cases.json").read_text())["cases"][0][
            "expected_conditions"
        ]

    def request(self, **changes):
        return self.service.retrieve(**{**self.arguments, **changes})

    def test_discount_report_includes_unsigned_volume_and_engineering_limits(self):
        pack = self.request()
        self.assertEqual("ready", pack["status"])
        self.assertEqual(2, pack["returned_document_count"])
        self.assertEqual(4, pack["returned_chunk_count"])
        self.assertTrue(
            all(row["covered"] for row in condition_checks(pack["citations"], self.conditions))
        )
        self.assertEqual(
            2, sum(row["context_role"] == "document_context" for row in pack["citations"])
        )
        self.assertIn("no additional quantity commitment has been signed", render_report(pack))
        self.assertEqual(1300, pack["facts"]["unit_cost_cents"])

    def test_expansion_uses_canonical_source_when_sibling_index_entry_is_missing(self):
        with self.service.store.connect() as connection:
            connection.execute(
                "DELETE FROM chunks WHERE chunk_id IN ('MAIL-A-001:v2:c2', 'ENG-A-001:v2:c2')"
            )
        pack = self.request()
        self.assertTrue(pack["context"]["complete"])
        self.assertTrue(
            all(row["covered"] for row in condition_checks(pack["citations"], self.conditions))
        )

    def test_corrupt_sibling_index_text_cannot_replace_canonical_condition(self):
        with self.service.store.connect() as connection:
            connection.execute(
                "UPDATE chunks SET text='Additional quantity is signed; cancel inspection.' WHERE chunk_id IN ('MAIL-A-001:v2:c2', 'ENG-A-001:v2:c2')"
            )
        report = render_report(self.request())
        self.assertNotIn("Additional quantity is signed", report)
        self.assertNotIn("cancel inspection", report)
        self.assertIn("Any simplification needs a separate engineering review", report)

    def test_late_document_section_is_included_without_keyword_matching(self):
        prior = self.service.store.latest("MAIL-A-001")
        body = (
            "# Email\n\n## Price\nCustomer price discount engineering cost.\n\n"
            + "\n\n".join(
                f"## Detail {index}\nRoutine background detail {index}." for index in range(5)
            )
            + "\n\n## Commitment\nFuture volume remains unsigned."
        )
        self.service.store.put_documents([replace(prior, version=3, body=body)])
        self.service.store.refresh_index()
        pack = self.request()
        self.assertIn("Future volume remains unsigned.", render_report(pack))
        self.assertTrue(
            all(
                row["version"] == 3
                for row in pack["citations"]
                if row["document_id"] == "MAIL-A-001"
            )
        )

    def test_character_budget_rejects_whole_document_not_just_its_tail(self):
        self.request()
        pack = self.request(max_context_chars=1)
        self.assertEqual("incomplete_context", pack["status"])
        self.assertEqual([], pack["citations"])
        self.assertFalse(pack["context"]["complete"])
        self.assertFalse(pack["cache_hit"])
        self.assertEqual(2, len(pack["context"]["omitted_documents"]))
        self.assertEqual(0, pack["context"]["returned_chars"])
        self.assertTrue(all("text" not in row for row in pack["retrieval_matches"]))

    def test_chunk_budget_and_long_documents_do_not_silently_truncate(self):
        for changes in ({"max_context_chunks": 1}, {"max_context_chars": 200}):
            with self.subTest(changes=changes):
                pack = self.request(**changes)
                self.assertEqual("incomplete_context", pack["status"])
                self.assertFalse(pack["context"]["complete"])
                self.assertTrue(
                    set(row["reason"] for row in pack["context"]["omitted_documents"])
                    <= {"context_budget_exceeded"}
                )
        prior = self.service.store.latest("MAIL-A-001")
        self.service.store.put_documents(
            [
                replace(
                    prior,
                    version=3,
                    body="## Price\nCustomer price discount.\n\n## Background\n"
                    + "context " * 900
                    + "\n\n## Commitment\nFuture quantity is not signed.",
                )
            ]
        )
        self.service.store.refresh_index()
        pack = self.request()
        self.assertEqual("incomplete_context", pack["status"])
        self.assertNotIn("MAIL-A-001", {row["document_id"] for row in pack["citations"]})
        self.assertLessEqual(pack["context"]["returned_chars"], 6000)

    def test_budget_limits_are_in_cache_key_and_validated(self):
        first = self.request()
        limited = self.request(max_context_chunks=2)
        self.assertNotEqual(first["status"], limited["status"])
        self.assertFalse(limited["cache_hit"])
        self.assertTrue(self.request()["cache_hit"])
        for change in (
            {"max_context_chars": 0},
            {"max_context_chars": True},
            {"max_context_chars": 20001},
            {"max_context_chunks": 33},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.request(**change)

    def test_expansion_keeps_scope_design_versions_and_no_quoted_history(self):
        pack = self.request()
        for row in pack["citations"]:
            self.assertEqual(
                ("CUSTOMER-A", "PROJECT-A", "ORDER-A001-L1", 2),
                (
                    row["customer_id"],
                    row["project_id"],
                    row["entity_id"],
                    row["version"],
                ),
            )
            self.assertIn(row["design_version"], {"D2", ""})
        text = render_report(pack)
        self.assertNotIn("3 percent", text)
        self.assertNotIn("Synthetic sender", text)
        self.assertNotIn("Customer B", text)

    def test_document_change_during_expansion_prevents_return(self):
        original = self.service.store.context_chunks
        changed = False

        def update_after_read(seed):
            nonlocal changed
            result = original(seed)
            if not changed:
                changed = True
                prior = self.service.store.latest("MAIL-A-001")
                self.service.store.put_documents(
                    [replace(prior, version=3, body="New customer requirement.")]
                )
            return result

        with (
            patch.object(self.service.store, "context_chunks", side_effect=update_after_read),
            self.assertRaisesRegex(RuntimeError, "changed during retrieval"),
        ):
            self.request()

    def test_revocation_during_expansion_and_after_cache_prevents_return(self):
        original = self.service.store.context_chunks

        def revoke_after_read(seed):
            chunks = original(seed)
            self.service.store.revoke("demo-manager-a", "CUSTOMER-A", "PROJECT-A")
            return chunks

        with (
            patch.object(self.service.store, "context_chunks", side_effect=revoke_after_read),
            self.assertRaises(PermissionError),
        ):
            self.request()
        with self.assertRaises(PermissionError):
            self.request()

    def test_new_condition_replaces_old_condition_and_delete_blocks_all_siblings(self):
        self.request()
        prior = self.service.store.latest("MAIL-A-001")
        self.service.store.put_documents(
            [
                replace(
                    prior,
                    version=3,
                    body="# Request\n\nCustomer price discount engineering cost.\n\n## Commitment\nSigned commitment is now 18,000 units.",
                )
            ]
        )
        stale = self.request()
        self.assertNotIn("MAIL-A-001", {row["document_id"] for row in stale["citations"]})
        self.service.store.refresh_index()
        fresh = self.request()
        self.assertIn("Signed commitment is now 18,000 units.", render_report(fresh))
        self.assertNotIn("no additional quantity commitment", render_report(fresh))
        self.assertEqual(12000, fresh["facts"]["quantity"])
        self.service.store.delete("MAIL-A-001", self.as_of)
        deleted = self.request()
        self.assertNotIn("MAIL-A-001", {row["document_id"] for row in deleted["citations"]})

    def test_eval_fails_if_conditions_are_dropped_despite_correct_document_ids(self):
        original = self.service.retrieve

        def drop_context(*args, **kwargs):
            pack = original(*args, **kwargs)
            pack["citations"] = [
                row for row in pack["citations"] if row["context_role"] == "retrieval_match"
            ]
            return pack

        with patch.object(self.service, "retrieve", side_effect=drop_context):
            result = evaluate_cases(self.service, self.as_of, RAG_FIXTURES / "eval-cases.json")
        case = next(row for row in result["cases"] if row["case_id"] == "a-price-context")
        self.assertTrue(case["checks"]["expected_documents"])
        self.assertFalse(case["checks"]["required_conditions_covered"])
        self.assertEqual(0.25, case["condition_coverage"])
        self.assertFalse(result["passed"])

    def test_eval_requires_exact_source_and_preserves_negation(self):
        original = self.service.retrieve

        def corrupt_condition(*args, **kwargs):
            pack = original(*args, **kwargs)
            for row in pack["citations"]:
                if row["chunk_id"] == "MAIL-A-001:v2:c2":
                    row["text"] = row["text"].replace("no additional", "additional")
            return pack

        with patch.object(self.service, "retrieve", side_effect=corrupt_condition):
            result = evaluate_cases(self.service, self.as_of, RAG_FIXTURES / "eval-cases.json")
        self.assertFalse(result["passed"])
        self.assertFalse(
            next(row for row in result["cases"] if row["case_id"] == "a-price-context")["checks"][
                "required_conditions_covered"
            ]
        )
        pack = self.request()
        fake = [dict(row, document_id="ENG-B-001") for row in pack["citations"]]
        self.assertFalse(any(row["covered"] for row in condition_checks(fake, self.conditions)))


if __name__ == "__main__":
    unittest.main()
