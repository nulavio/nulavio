"""Published release bookkeeping is repeatable and cannot advertise drafts or downgrades."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/release_metadata.py"


class ReleaseMetadataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        (self.repo / "packaging").mkdir()
        self.metadata = self.repo / "packaging/release.json"
        self.metadata.write_text(json.dumps({"version": "160.0-0.1", "channel": "alpha", "key_fingerprint": "KEEP"}))
        (self.repo / "browser/build").mkdir(parents=True)
        (self.repo / "browser/build/engine.json").write_text(json.dumps({"firefox": "160.0"}))
        (self.repo / "CHANGELOG.md").write_text("# Changelog\n\nRelease history.\n\n<!-- releases -->\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.git("tag", "v160.0-0.2")
        self.manifest = {"firefox": "160.0", "packages": [{"file": "packages/x86_64/nulavio-160.0-0.2.fc44.x86_64.rpm"}]}
        self.release = {
            "tag_name": "v160.0-0.2",
            "draft": False,
            "published_at": "2026-11-13T12:00:00Z",
            "html_url": "https://github.com/nulavio/nulavio/releases/tag/v160.0-0.2",
            "body": "## Fixes\n\n- Keep profiles.\n",
            "prerelease": True,
        }

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True).stdout

    def run_metadata(self):
        event = self.repo / "event.json"
        event.write_text(json.dumps({"release": self.release}))
        manifest = self.repo / "manifest.json"
        manifest.write_text(json.dumps({**self.manifest, "nulavio_base_commit": self.sha}))
        return subprocess.run(
            [
                sys.executable,
                "-I",
                str(SCRIPT),
                "--repo",
                str(self.repo),
                "--event",
                str(event),
                "--repository",
                "nulavio/nulavio",
                "--manifest",
                str(manifest),
            ],
            capture_output=True,
            text=True,
        )

    def test_published_release_updates_only_version_and_records_notes_once(self):
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.metadata.read_text()), {"version": "160.0-0.2", "channel": "alpha", "key_fingerprint": "KEEP"}
        )
        changelog = (self.repo / "CHANGELOG.md").read_text()
        self.assertIn("2026-11-13", changelog)
        self.assertIn("Keep profiles.", changelog)
        before = self.metadata.read_bytes(), changelog
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.metadata.read_bytes(), (self.repo / "CHANGELOG.md").read_text()), before)

    def test_drafts_invalid_versions_wrong_urls_and_empty_notes_leave_files_untouched(self):
        for field, value in (
            ("draft", True),
            ("published_at", None),
            ("tag_name", "v160.0-0.2/../../main"),
            ("html_url", "https://example.invalid/release"),
            ("body", ""),
            ("prerelease", False),
        ):
            with self.subTest(field=field):
                before = self.metadata.read_bytes(), (self.repo / "CHANGELOG.md").read_bytes()
                original = self.release[field]
                self.release[field] = value
                result = self.run_metadata()
                self.release[field] = original
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.metadata.read_bytes(), (self.repo / "CHANGELOG.md").read_bytes()), before)

    def test_an_older_release_does_not_downgrade_the_site(self):
        self.metadata.write_text(json.dumps({"version": "160.0-0.10", "channel": "alpha"}))
        before = self.metadata.read_bytes(), (self.repo / "CHANGELOG.md").read_bytes()
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.metadata.read_bytes(), (self.repo / "CHANGELOG.md").read_bytes()), before)

    def test_attested_commit_must_match_the_tag_on_main(self):
        self.git("commit", "-q", "--allow-empty", "-m", "another commit")
        self.sha = self.git("rev-parse", "HEAD").strip()
        result = self.run_metadata()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("attested build commit", result.stderr)

    def test_off_main_release_and_mismatched_engine_are_refused(self):
        self.git("switch", "-qc", "topic")
        self.git("commit", "-q", "--allow-empty", "-m", "topic")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.git("tag", "v160.0-0.3")
        self.git("switch", "-q", "main")
        self.manifest["packages"] = [{"file": "packages/x86_64/nulavio-160.0-0.3.fc44.x86_64.rpm"}]
        self.release["tag_name"] = "v160.0-0.3"
        self.release["html_url"] = "https://github.com/nulavio/nulavio/releases/tag/v160.0-0.3"
        self.assertNotEqual(self.run_metadata().returncode, 0)
        self.git("tag", "v161.0-0.1")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.manifest = {"firefox": "161.0", "packages": [{"file": "packages/x86_64/nulavio-161.0-0.1.fc44.x86_64.rpm"}]}
        self.release["tag_name"] = "v161.0-0.1"
        self.release["html_url"] = "https://github.com/nulavio/nulavio/releases/tag/v161.0-0.1"
        result = self.run_metadata()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Firefox pin", result.stderr)

    def test_public_notes_are_literal_data_and_security_changelog_is_not_fabricated(self):
        self.release["body"] = "$(touch NEVER) `command` <script>not executable</script>"
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.release["body"], (self.repo / "CHANGELOG.md").read_text())
        self.assertFalse((self.repo / "NEVER").exists())
        self.assertFalse((self.repo / "docs/security/changelog.md").exists())


if __name__ == "__main__":
    unittest.main()
