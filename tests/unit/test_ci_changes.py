"""The integration gate in ci.yml (scripts/ci/needs_integration.py)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import needs_integration as gate  # noqa: E402

REPO = "nulavio/nulavio"


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}  # fmt: skip
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


def runs(*entries: dict) -> object:
    def gh(_args):
        return json.dumps({"workflow_runs": list(entries)})

    return gh


def run(sha: str, event: str = "push", repo: str = REPO, branch: str = "main") -> dict:
    return {"head_sha": sha, "event": event, "head_branch": branch, "head_repository": {"full_name": repo}}


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

    def test_last_green_is_the_newest_successful_main_run_of_this_repository(self):
        a, b, c = "a" * 40, "b" * 40, "c" * 40
        listing = runs(run(a, repo="someone/fork"), run(b, branch="feature"), run(c, event="pull_request"),
                       run(a, event="schedule"), run(b))  # fmt: skip
        self.assertEqual(gate.last_green(REPO, listing), a)
        self.assertIsNone(gate.last_green(REPO, runs()))
        self.assertIsNone(gate.last_green(REPO, lambda _args: None))  # API down
        self.assertIsNone(gate.last_green(REPO, lambda _args: "<html>"))
        self.assertIsNone(gate.last_green(REPO, runs(run("not-a-sha"))))
        self.assertIsNone(gate.last_green("../evil", runs(run(a))))

    def test_bad_bases_run_everything(self):
        for event, base, gh in (("push", "", runs(run("0" * 40))), ("schedule", "a" * 40, runs()),
                                ("pull_request", "--output=/tmp/x", runs()), ("workflow_dispatch", "", runs())):  # fmt: skip
            self.assertIsNone(gate.base_for(event, base, REPO, gh), event)


@unittest.skipUnless(shutil.which("git"), "needs git")
class GitTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="nv-ci-changes-"))
        self.cwd = os.getcwd()
        os.chdir(self.repo)
        git(self.repo, "init", "-q")
        self.tested = self.commit("a.py", "x = 1\n")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.repo, ignore_errors=True)

    def commit(self, name: str, text: str) -> str:
        (self.repo / name).write_text(text)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", name)
        return git(self.repo, "rev-parse", "HEAD")

    def decide(self, event: str, last_green: str) -> tuple[bool, str | None]:
        base = gate.base_for(event, last_green, REPO, runs(run(last_green)))
        return gate.needs_integration(gate.changed_files(base)), base

    def test_a_cancelled_code_push_followed_by_a_docs_push_still_runs(self):
        self.commit("b.py", "y = 2\n")  # push 1: its run was cancelled by push 2
        self.commit("notes.md", "hi\n")  # push 2: Markdown only
        self.assertEqual(self.decide("push", self.tested), (True, self.tested))

    def test_markdown_since_the_last_green_run_skips(self):
        self.commit("notes.md", "hi\n")
        self.assertEqual(self.decide("push", self.tested), (False, self.tested))
        self.assertEqual(self.decide("pull_request", self.tested), (False, self.tested))

    def test_a_base_missing_from_the_clone_runs_everything(self):
        self.assertEqual(self.decide("push", "b" * 40), (True, None))

    def test_the_output_names_the_base(self):
        self.commit("notes.md", "hi\n")
        env = {**os.environ, "EVENT": "pull_request", "BASE": self.tested, "GITHUB_REPOSITORY": REPO}
        out = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "ci" / "needs_integration.py")],
                             cwd=self.repo, env=env, capture_output=True, text=True, check=True).stdout  # fmt: skip
        self.assertEqual(out.splitlines(), ["integration=false", f"base={self.tested}"])


class WorkflowTest(unittest.TestCase):
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    def test_pushes_and_the_weekly_run_never_share_a_cancelling_group(self):
        group = re.search(r"(?m)^concurrency:\n\s+group: (.+)\n", self.text).group(1)
        self.assertIn("github.event_name", group)  # schedule, push and pull_request each get their own group

    def test_integration_waits_for_the_gate(self):
        self.assertIn("if: ${{ needs.changes.outputs.integration == 'true' }}", self.text)
        self.assertRegex(self.text, r"actions: read # the last successful ci run on main")


if __name__ == "__main__":
    unittest.main()
