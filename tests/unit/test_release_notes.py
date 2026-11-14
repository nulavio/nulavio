"""Release notes use the exact public first-parent history, never commit bodies."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/release_notes.py"


class ReleaseNotesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        for version in ("160.0-0.2", "160.0-0.11"):  # what is new, committed before the releases (#198)
            self.record(version)
        self.git("add", "packaging")
        self.commit("feat: old feature")
        self.git("tag", "v160.0-0.1")
        self.commit("feat(shell): show tabs (#25)", "PRIVATE BODY MUST NOT APPEAR")
        self.commit("fix!: preserve profiles (#26)")
        self.target = self.git("rev-parse", "HEAD").strip()
        self.commit("feat: future change")

    def record(self, version, summary="A summary for people.", new=("A new thing.",)):
        directory = self.repo / "packaging" / "whats-new"
        directory.mkdir(parents=True, exist_ok=True)
        text = {"summary": summary, "new": list(new)}
        data = {"version": version, "date": "2026-11-20", "channel": "alpha", "firefox": "160.0", "pt-BR": text, "en-US": text}
        (directory / f"{version}.json").write_text(json.dumps(data))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True).stdout

    def commit(self, subject, body=None):
        args = ["commit", "-q", "--allow-empty", "-m", subject]
        if body:
            args += ["-m", body]
        self.git(*args)

    def notes(self, tag="v160.0-0.2", commit=None, debs=()):
        info = self.repo / "release.json"
        info.write_text(json.dumps({"tag": tag, "firefox": "160.0", "commit": commit or self.target, "debs": list(debs)}))
        return subprocess.run(
            [
                sys.executable,
                "-I",
                str(SCRIPT),
                "notes",
                "--repo",
                str(self.repo),
                "--release",
                str(info),
                "--repository",
                "nulavio/nulavio",
                "--fingerprint",
                "A" * 40,
                "--run-url",
                "https://github.com/nulavio/nulavio/actions/runs/1",
            ],
            capture_output=True,
            text=True,
        )

    def test_exact_commit_range_categorized_with_traceability(self):
        result = self.notes()
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in (
            "## Features",
            "## Breaking changes",
            "show tabs",
            "preserve profiles",
            self.target[:12],
            "compare/v160.0-0.1...",
            "SHA256SUMS.asc",
            "gh attestation verify",
        ):
            self.assertIn(text, result.stdout)
        for text in ("old feature", "future change", "PRIVATE BODY"):
            self.assertNotIn(text, result.stdout)

    def test_what_is_new_comes_first_from_the_record_committed_with_the_release(self):
        result = self.notes()
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertLess(out.index("## What's new\n\nA summary for people."), out.index("## Features"))
        self.assertIn("### What is new\n\n- A new thing.", out)
        self.assertIn("https://nulavio.net/en/whats-new/160.0-0.2/", out)
        # A record added after the release's commit does not count: the notes come from that commit.
        self.record("160.0-0.3")
        self.git("add", "packaging")
        self.commit("docs: what is new in 0.3, too late")
        missing = self.notes("v160.0-0.3", self.target)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no packaging/whats-new/160.0-0.3.json at", missing.stderr)
        self.assertFalse(missing.stdout)
        # And an invalid one is refused, not printed.
        self.record("160.0-0.12", summary="See <script>")
        self.git("add", "packaging")
        self.commit("docs: a bad record")
        bad = self.notes("v160.0-0.12", self.git("rev-parse", "HEAD").strip())
        self.assertEqual(bad.returncode, 1)
        self.assertIn("plain text only", bad.stderr)

    def test_ubuntu_is_named_when_the_release_has_its_deb(self):
        self.assertIn("Install or upgrade on Fedora: https://nulavio.net/en/download/", self.notes().stdout)
        (self.repo / "site" / "apt").mkdir(parents=True)
        (self.repo / "site" / "apt" / "nulavio.sources").write_text("Types: deb\n")
        self.git("add", "site")
        self.commit("feat: the APT source file")
        commit = self.git("rev-parse", "HEAD").strip()
        with_deb = self.notes(commit=commit, debs=["packages/nulavio_160.0-0.2_amd64.deb"])
        self.assertEqual(with_deb.returncode, 0, with_deb.stderr)
        self.assertIn("Install or upgrade on Fedora or Ubuntu: https://nulavio.net/en/download/", with_deb.stdout)
        # The hash the download page shows, in a second place outside the site.
        digest = hashlib.sha256(b"Types: deb\n").hexdigest()
        self.assertIn(f"`nulavio.sources` from the download page has the SHA-256 `{digest}`", with_deb.stdout)

    def test_initial_release_and_nonconventional_history_remain_visible(self):
        self.git("tag", "-d", "v160.0-0.1")
        self.commit("Legacy change <script> @someone `code`")
        result = self.notes(commit=self.git("rev-parse", "HEAD").strip())
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in ("Initial release history", "Other changes", "old feature", "&lt;script&gt;", "&#64;someone"):
            self.assertIn(text, result.stdout)
        self.assertNotIn("<script>", result.stdout)

    def test_annotated_numeric_boundary_and_side_branch_tag(self):
        self.git("tag", "-a", "v160.0-0.9", "-m", "release", self.target)
        self.commit("docs: after the previous release")
        target = self.git("rev-parse", "HEAD").strip()
        self.git("switch", "-qc", "topic", "v160.0-0.1")
        self.commit("feat: side branch only")
        self.git("tag", "v160.0-0.10")
        self.git("switch", "-q", "main")
        result = self.notes("v160.0-0.11", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("compare/v160.0-0.9...", result.stdout)
        self.assertIn("after the previous release", result.stdout)
        self.assertNotIn("show tabs", result.stdout)
        self.assertNotIn("side branch only", result.stdout)

    def test_invalid_release_and_ref_injection_fail_closed(self):
        for tag, commit in (("v160.0-0.2; touch /tmp/no", self.target), ("v160.0-0.2", "--all"), ("v161.0-0.2", self.target)):
            with self.subTest(tag=tag, commit=commit):
                result = self.notes(tag, commit)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(result.stdout)

    def test_pr_title_validation_uses_data_without_shell_evaluation(self):
        event = self.repo / "event.json"
        for title, accepted in (
            ("feat(shell): new tab", True),
            ("security: harden launcher", True),
            ("fix!: migration", True),
            ("Update stuff", False),
            ("fix: one\nrun: bad", False),
            ("fix: $(touch /tmp/not-executed)", True),
        ):
            with self.subTest(title=title):
                event.write_text(json.dumps({"pull_request": {"title": title}}))
                result = subprocess.run(
                    [sys.executable, "-I", str(SCRIPT), "check-title"],
                    env={**os.environ, "GITHUB_EVENT_PATH": str(event)},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode == 0, accepted, result.stderr)


if __name__ == "__main__":
    unittest.main()
