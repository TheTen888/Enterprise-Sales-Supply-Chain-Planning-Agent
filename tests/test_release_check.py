import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.release_check import example_findings, inspect_release, load_manifest


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / ".env.example").write_text(
            "ALLOW_LIVE_SERVICES=false\nSNOWFLAKE_OAUTH_TOKEN=\n"
        )
        (self.root / "README.md").write_text("# Synthetic local prototype\n")
        self.write_manifest([".env.example", "README.md", "release-files.txt"])

    def write_manifest(self, names):
        (self.root / "release-files.txt").write_text("\n".join(sorted(names)) + "\n")

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments], capture_output=True, check=True
        )

    def test_clean_manifest_produces_hashes_without_git(self):
        result = inspect_release(self.root)
        self.assertTrue(result["passed"])
        self.assertEqual(3, result["file_count"])
        self.assertFalse(result["git_index_checked"])
        self.assertTrue(all(len(row["sha256"]) == 64 for row in result["files"]))

    def test_provider_secret_is_rejected_without_printing_the_value(self):
        token = "sk-" + "a" * 48
        (self.root / "README.md").write_text(token)
        result = inspect_release(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual("provider_token", result["findings"][0]["rule"])
        self.assertNotIn(token, json.dumps(result))

    def test_private_names_paths_and_duplicate_manifest_entries_are_rejected(self):
        for name in (".env", "token.json", "data/orders.db", "../outside.txt", "/absolute.txt"):
            with self.subTest(name=name):
                self.write_manifest([name, "release-files.txt"])
                with self.assertRaises(ValueError):
                    load_manifest(self.root)
        self.write_manifest(["release-files.txt", "release-files.txt"])
        with self.assertRaises(ValueError):
            load_manifest(self.root)

    def test_symlink_and_binary_cannot_enter_the_candidate(self):
        (self.root / "alias.md").symlink_to(self.root / "README.md")
        self.write_manifest(["alias.md", "release-files.txt"])
        self.assertEqual(
            "missing_or_symlinked_file", inspect_release(self.root)["findings"][0]["rule"]
        )
        (self.root / "binary.txt").write_bytes(b"not-text\x00")
        self.write_manifest(["binary.txt", "release-files.txt"])
        self.assertEqual("non_text_file", inspect_release(self.root)["findings"][0]["rule"])

    def test_environment_example_requires_empty_credentials_and_disabled_services(self):
        for text in (
            "ALLOW_LIVE_SERVICES=true\n",
            "ALLOW_LIVE_SERVICES=false\nSNOWFLAKE_OAUTH_TOKEN=filled\n",
            "ALLOW_LIVE_SERVICES=false\nSNOWFLAKE_ACCOUNT=real-account\n",
        ):
            with self.subTest(text=text):
                self.assertTrue(example_findings(text))

    def test_private_deny_terms_and_home_paths_are_redacted(self):
        (self.root / "README.md").write_text(
            "PrivateSupplier can access /" + "Users/example-user/private"
        )
        result = inspect_release(self.root, ["PrivateSupplier"])
        self.assertFalse(result["passed"])
        self.assertEqual(
            {"restricted_term", "private_home_path"}, {row["rule"] for row in result["findings"]}
        )
        self.assertNotIn("PrivateSupplier", json.dumps(result))

    def test_markdown_links_must_resolve_inside_the_release(self):
        (self.root / "README.md").write_text("[Not included](local-notes.md)\n")
        self.assertEqual("link_outside_release", inspect_release(self.root)["findings"][0]["rule"])

    @unittest.skipUnless(shutil.which("git"), "Git is required for index checks")
    def test_staged_secret_is_detected_even_after_working_file_is_cleaned(self):
        self.git("init", "-q")
        token = "sk-" + "b" * 48
        (self.root / "README.md").write_text(token)
        self.git("add", "--all")
        (self.root / "README.md").write_text("Clean working file")
        result = inspect_release(self.root)
        self.assertFalse(result["passed"])
        self.assertTrue(result["git_index_checked"])
        self.assertTrue(any(row["rule"] == "provider_token" for row in result["findings"]))
        self.assertNotIn(token, json.dumps(result))

    @unittest.skipUnless(shutil.which("git"), "Git is required for index checks")
    def test_unexpected_staged_file_is_rejected(self):
        self.git("init", "-q")
        (self.root / "extra.txt").write_text("Not reviewed")
        self.git("add", "--all")
        result = inspect_release(self.root)
        self.assertFalse(result["passed"])
        self.assertIn(
            {"file": "extra.txt", "rule": "git_index_differs_from_manifest"}, result["findings"]
        )


if __name__ == "__main__":
    unittest.main()
