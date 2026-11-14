"""The "what's new" records (#198): what a release must carry, and what the site and the browser show."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import whats_new  # noqa: E402

TEXT = {"summary": "A security update.", "new": ["One thing."], "fixed": ["Another thing."]}
RECORD = {"version": "160.0-0.5", "date": "2026-11-20", "channel": "alpha", "firefox": "160.0",
          "pt-BR": {"summary": "Uma atualização.", "new": ["Uma coisa."], "fixed": ["Outra coisa."]},
          "en-US": TEXT, "security": ["GHSA-j8cq-r5j6-q2x3"]}  # fmt: skip


def changed(**edits) -> dict:
    data = copy.deepcopy(RECORD)
    names = {"pt_BR": "pt-BR", "en_US": "en-US"}
    for path, value in edits.items():
        *parents, key = (names.get(part, part) for part in path.split("__"))
        target = data
        for parent in parents:
            target = target[parent]
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value
    return data


class WhatsNewTest(unittest.TestCase):
    def test_a_valid_record(self):
        self.assertEqual(whats_new.validate(copy.deepcopy(RECORD), "160.0-0.5.json")["version"], "160.0-0.5")

    def test_what_is_refused(self):
        cases = {
            "file name": (RECORD, "160.0-0.4.json"),
            "version": (changed(version="160.0"), None),
            "firefox": (changed(firefox="161.0"), None),
            "date": (changed(date="20/11/2026"), None),
            "channel": (changed(channel="nightly"), None),
            "a language missing": (changed(pt_BR=None), None),
            "an unknown key": (changed(notes="x"), None),
            "an unknown list": (changed(en_US__extra=["x"]), None),
            "no summary": (changed(en_US__summary=None), None),
            "markup": (changed(en_US__summary="See <b>this</b>."), None),
            "a link": (changed(en_US__new=["See [here](x)."]), None),
            "an address": (changed(en_US__new=["Go to https://example.com now."]), None),
            "a mention": (changed(en_US__new=["Thanks @someone."]), None),
            "two lines": (changed(en_US__summary="One.\nTwo."), None),
            "double spaces": (changed(en_US__summary="One  two."), None),
            "too long": (changed(en_US__summary="x" * 501), None),
            "too many items": (changed(en_US__new=["x"] * 21, pt_BR__new=["x"] * 21), None),
            "languages that differ": (changed(en_US__fixed=[]), None),
            "an advisory that is not a GHSA id": (changed(security=["CVE-2026-1"]), None),
            "an address in capitals": (changed(en_US__new=["See HTTPS://evil.example/x."]), None),
            "another scheme": (changed(en_US__new=["Get ftp://files.example/x."]), None),
            "www in capitals": (changed(en_US__new=["Visit WWW.example.com."]), None),
            "a bidirectional override": (changed(en_US__summary="Fixed \u202eevil."), None),
            "a line separator": (changed(en_US__summary="One\u2028two."), None),
        }
        for name, (data, file_name) in cases.items():
            with self.subTest(name), self.assertRaises(whats_new.RecordError):
                whats_new.validate(data, file_name)

    def test_only_published_versions_are_shown_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            directory = repo / whats_new.DIRECTORY
            directory.mkdir(parents=True)
            for version in ("160.0-0.4", "160.0-0.5", "161.0-0.1"):
                data = {**copy.deepcopy(RECORD), "version": version, "firefox": version.split("-")[0]}
                (directory / f"{version}.json").write_text(json.dumps(data))
            data = {**copy.deepcopy(RECORD), "version": "160.0-0.3", "firefox": "160.0"}  # a revision never published
            (directory / "160.0-0.3.json").write_text(json.dumps(data))
            self.assertEqual(whats_new.published(repo), [])  # no packaging/release.json: nothing is published
            (repo / "packaging" / "release.json").write_text(json.dumps({"version": "160.0-0.5"}))
            # Published: the version release.json names, and those CHANGELOG.md records as published.
            self.assertEqual([r["version"] for r in whats_new.published(repo)], ["160.0-0.5"])
            (repo / "CHANGELOG.md").write_text("# Changelog\n\n<!-- release:v160.0-0.4 -->\n## 160.0-0.4\n")
            self.assertEqual([r["version"] for r in whats_new.published(repo)], ["160.0-0.5", "160.0-0.4"])
            self.assertEqual(whats_new.published(repo, "161.0-0.1")[0]["version"], "161.0-0.1")

    def test_require_reads_the_record_at_the_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git = ["git", "-C", tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
            subprocess.run([*git, "init", "-q"], check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "before"], check=True)
            before = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            (repo / whats_new.DIRECTORY).mkdir(parents=True)
            (repo / whats_new.DIRECTORY / "160.0-0.5.json").write_text(json.dumps(RECORD))
            subprocess.run([*git, "add", "-A"], check=True)
            subprocess.run([*git, "commit", "-q", "-m", "record"], check=True)
            after = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(whats_new.require("160.0-0.5", repo, at=after)["version"], "160.0-0.5")
            self.assertEqual(whats_new.require("160.0-0.5", repo)["version"], "160.0-0.5")
            with self.assertRaisesRegex(whats_new.RecordError, "no packaging/whats-new/160.0-0.5.json at"):
                whats_new.require("160.0-0.5", repo, at=before)

    def test_the_records_in_the_tree_are_valid_and_the_published_version_has_one(self):
        found = whats_new.records()
        self.assertTrue(found)
        release = json.loads((ROOT / "packaging" / "release.json").read_text(encoding="utf-8")).get("version")
        if release:
            self.assertEqual(whats_new.published()[0]["version"], release)
        run = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/release/whats_new.py"), "check"],
                             capture_output=True, text=True, check=False)  # fmt: skip
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_pages_and_notes_escape_what_plain_text_may_hold(self):
        sys.path.insert(0, str(ROOT / "scripts" / "site"))
        import whats_new_pages

        text = {"summary": 'Tom\'s "quote" & more *stars* and _under_.', "new": ["A & B's <thing>"[:-8]]}
        record = {**copy.deepcopy(RECORD), "pt-BR": text, "en-US": text, "security": []}
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / whats_new.DIRECTORY).mkdir(parents=True)
            (repo / whats_new.DIRECTORY / "160.0-0.5.json").write_text(json.dumps(record))
            pages = whats_new_pages.pages(repo, "160.0-0.5", {"pt-BR": "20/11/2026", "en-US": "2026-11-20"})
        page = pages["en/whats-new/160.0-0.5/index.html"]
        self.assertIn("Tom&#x27;s &quot;quote&quot; &amp; more", page)
        self.assertNotIn("Tom's", page)
        self.assertIn("A &amp; B&#x27;s", page)
        index = pages["en/whats-new/index.html"]
        self.assertIn("Tom&#x27;s &quot;quote&quot;", index)


class PackedNotesTest(unittest.TestCase):
    """The browser's copy (phase 2): make_distribution.py packs the record of the version it packages."""

    def run_make(self, out: Path, release: str | None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "NULAVIO_RELEASE"}
        if release is not None:
            env["NULAVIO_RELEASE"] = release
        return subprocess.run([sys.executable, "-I", str(ROOT / "scripts/build/make_distribution.py"), "--out", str(out)],
                              capture_output=True, text=True, env=env)  # fmt: skip

    def test_a_release_packs_its_record_and_a_development_build_none(self):
        firefox = json.loads((ROOT / "browser/build/engine.json").read_text(encoding="utf-8"))["firefox"]
        published = next(r for r in whats_new.records() if r["firefox"] == firefox)
        release = published["version"].split("-", 1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run = self.run_make(out, release)
            self.assertEqual(run.returncode, 0, run.stderr)
            packed = json.loads((out / "whats-new.json").read_text(encoding="utf-8"))
            self.assertEqual(packed, published, "the reviewed record, unchanged")
            # A development build (no NULAVIO_RELEASE) has none, and a stale copy goes.
            run = self.run_make(out, None)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertFalse((out / "whats-new.json").exists())
            # A release whose record is missing stops: it would otherwise ship without notes.
            run = self.run_make(out, "999")
            self.assertNotEqual(run.returncode, 0)
            self.assertIn(f"{firefox}-999", run.stderr)
            self.assertFalse((out / "whats-new.json").exists())


if __name__ == "__main__":
    unittest.main()
