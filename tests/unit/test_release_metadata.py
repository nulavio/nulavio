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
        self.readmes = {
            "README.md": "Now <!--release-->[v160.0-0.1](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.1)<!--/release-->.\n",
            "README.pt-BR.md": "Agora na <!--release-->[v160.0-0.0](old)<!--/release-->, [v160.0-0.1](keep).\n",
        }
        for name, text in self.readmes.items():
            (self.repo / name).write_text(text)
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

    def test_the_readmes_status_names_the_published_release_between_its_markers(self):
        # #857: the release step keeps the READMEs' status on the latest release, even one that drifted.
        link = "<!--release-->[v160.0-0.2](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.2)<!--/release-->"
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.repo / "README.md").read_text(), f"Now {link}.\n")
        self.assertEqual((self.repo / "README.pt-BR.md").read_text(), f"Agora na {link}, [v160.0-0.1](keep).\n")
        # An older release leaves them as they are.
        (self.repo / "README.md").write_text(self.readmes["README.md"])
        self.metadata.write_text(json.dumps({"version": "160.0-0.10", "channel": "alpha"}))
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.repo / "README.md").read_text(), self.readmes["README.md"])

    def test_a_readme_only_repair_writes_only_the_readme_and_keeps_its_line_endings(self):
        # OCR on #878: a drifted README link for the current release rewrites neither the metadata nor the changelog,
        # and the README keeps its bytes outside the markers.
        link = "<!--release-->[v160.0-0.2](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.2)<!--/release-->"
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        readme = self.repo / "README.md"
        readme.write_bytes(b"# Nulavio\r\n\r\nNow <!--release-->[v160.0-0.1](drifted)<!--/release-->.\r\n")
        for path in (self.metadata, self.repo / "CHANGELOG.md"):
            path.chmod(0o444)
            self.addCleanup(path.chmod, 0o644)
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(readme.read_bytes(), f"# Nulavio\r\n\r\nNow {link}.\r\n".encode())

    def test_the_first_release_with_the_companion_apk_names_it_for_the_download_pages(self):
        # ADR 0014: the pages offer the Companion once a published release carries its APK.
        self.release["assets"] = [{"name": "nulavio-160.0-0.2.fc44.x86_64.rpm"}, {"name": "SHA256SUMS"}]
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("companion_apk", json.loads(self.metadata.read_text()))
        self.metadata.write_text(json.dumps({"version": "160.0-0.1", "channel": "alpha", "key_fingerprint": "KEEP"}))
        self.release["assets"] += [{"name": "nulavio-companion-0.1.0.apk"}, {"name": "nulavio-companion-0.1.0.apk.cdx.json"},
                                   {"name": "nulavio-companion-evil.apk"}]  # fmt: skip
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.metadata.read_text())["companion_apk"], "nulavio-companion-0.1.0.apk")

    def test_the_first_release_with_its_deb_shows_ubuntu_on_the_download_pages(self):
        self.manifest["packages"].append({"file": "packages/nulavio_160.0-0.2_amd64.deb"})
        # Every rehearsal lists its .deb, also those of releases published before the APT repository
        # existed: without the .deb among the release's assets, nothing says the repository has it.
        self.release["assets"] = [{"name": "nulavio-160.0-0.2.fc44.x86_64.rpm"}, {"name": "SHA256SUMS"}]
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("apt_sources", json.loads(self.metadata.read_text()))
        self.metadata.write_text(json.dumps({"version": "160.0-0.1", "channel": "alpha", "key_fingerprint": "KEEP"}))
        self.release["assets"].append({"name": "nulavio_160.0-0.2_amd64.deb"})
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        metadata = json.loads(self.metadata.read_text())
        self.assertEqual(metadata["apt_sources"], "https://nulavio.net/apt/nulavio.sources")
        self.assertEqual(metadata["version"], "160.0-0.2")
        # A .deb of another version is not this release's: nothing changes.
        self.metadata.write_text(json.dumps({"version": "160.0-0.1", "channel": "alpha", "key_fingerprint": "KEEP"}))
        self.manifest["packages"][-1] = {"file": "packages/nulavio_160.0-0.9_amd64.deb"}
        result = self.run_metadata()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("apt_sources", json.loads(self.metadata.read_text()))

    def test_no_flatpak_bundle_is_recorded_until_flathub(self):
        # #467: the pages offer no bundle until Flathub, even for a release whose assets still carry one.
        self.release["assets"] = [{"name": "nulavio-160.0-0.2.fc44.x86_64.rpm"}, {"name": "nulavio-160.0-0.2.x86_64.flatpak"}]
        metadata = {"version": "160.0-0.1", "channel": "alpha", "key_fingerprint": "KEEP"}
        self.metadata.write_text(json.dumps({**metadata, "flatpak_bundle": "nulavio-160.0-0.1.x86_64.flatpak"}))
        result = self.run_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("flatpak_bundle", json.loads(self.metadata.read_text()))

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
