"""The integration gate in ci.yml (scripts/ci/needs_integration.py)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import needs_integration as gate  # noqa: E402


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}  # fmt: skip
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


class DecisionTest(unittest.TestCase):
    def test_markdown_only_skips(self):
        self.assertFalse(gate.needs_integration(["README.md", "docs/security/code-scanning.md", "docs/X.MD"]))

    def test_anything_else_runs(self):
        for changed in (["docs/brand/tokens.json", "README.md"], ["launcher/nulavio_launcher/cli.py"],
                        [".github/workflows/ci.yml"], ["docs/brand/assets/logo.svg"]):  # fmt: skip
            self.assertTrue(gate.needs_integration(changed), changed)

    def test_unknown_or_empty_runs(self):
        self.assertTrue(gate.needs_integration(None))
        self.assertTrue(gate.needs_integration([]))

    def test_refs_that_are_not_a_full_sha_run_everything(self):
        for event, before, base in (("push", "0" * 40, ""), ("push", "HEAD~1", ""), ("schedule", "a" * 40, ""),
                                    ("pull_request", "", "--output=/tmp/x"), ("workflow_dispatch", "", "")):  # fmt: skip
            self.assertIsNone(gate.changed_files(event, before, base), (event, before, base))


class GitTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="nv-ci-changes-"))
        git(self.repo, "init", "-q")
        (self.repo / "a.py").write_text("x = 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "one")
        self.first = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.repo)], check=False)

    def run_gate(self, event: str, ref: str) -> list[str] | None:
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            with mock.patch.dict(os.environ, {"GIT_DIR": str(self.repo / ".git")}):
                return gate.changed_files(event, ref if event == "push" else "", ref)
        finally:
            os.chdir(cwd)

    def test_lists_what_changed_since_the_base(self):
        (self.repo / "notes.md").write_text("hi\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "two")
        self.assertEqual(self.run_gate("push", self.first), ["notes.md"])
        self.assertEqual(self.run_gate("pull_request", self.first), ["notes.md"])

    def test_a_base_missing_from_the_clone_runs_everything(self):
        self.assertIsNone(self.run_gate("push", "b" * 40))


if __name__ == "__main__":
    unittest.main()
