"""PrivacyTests.org's probe pages are the ones copied from their repository, unchanged, and the watcher that
compares the copy with their repository reads what it should (#79)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "privacytests"
PINNED = json.loads((FIXTURES / "pinned.json").read_text(encoding="utf-8"))
SPEC = importlib.util.spec_from_file_location("watch_privacytests", ROOT / "scripts" / "research" / "watch_privacytests.py")
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)
OURS = {"README.md", "pinned.json"}  # written here; everything else in the folder is theirs


class PrivacyTestsFixtureTest(unittest.TestCase):
    def test_the_files_are_the_pinned_ones_and_nothing_else(self):
        found = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in FIXTURES.iterdir() if path.name not in OURS}
        # Their files are pinned by their path in their repository; the copies here are flat.
        copied = {Path(path).name: digest for path, digest in PINNED["files"].items() if not path.startswith("scripts/")}
        self.assertEqual(found, copied)
        self.assertRegex(PINNED["commit"], r"^[0-9a-f]{40}$")

    def test_the_readme_names_the_commit_and_the_license(self):
        readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
        self.assertIn(PINNED["commit"], readme)
        self.assertIn("MIT", readme)
        self.assertIn("MIT license", (FIXTURES / "LICENSE").read_text(encoding="utf-8"))

    def test_nothing_the_pages_post_can_leave_this_machine(self):
        # The pages post only with a sessionId, and the integration test never gives one.
        post = (FIXTURES / "post_data.js").read_text(encoding="utf-8")
        self.assertIn("if (!urlParams.has('sessionId')) {\n      return;\n    }", post)
        test = (ROOT / "tests" / "integration" / "test_privacytests.py").read_text(encoding="utf-8")
        self.assertNotIn("sessionId=", test)
        # The Device page's watchdog does not ask for one. Every address a page can post to is in these files,
        # and the test resolves each of them to this machine.
        hosts = set()
        for path in FIXTURES.glob("*.js"):
            hosts |= set(re.findall(r"https://([a-z0-9.-]+)/post", path.read_text(encoding="utf-8")))
        self.assertEqual(hosts, {"results.privacytests.org", "results.pto2.example"})
        local = re.search(r"^LOCAL_ONLY = \(\*SITES, (.*)\)$", test, re.M).group(1)
        self.assertEqual({name.strip(' "') for name in local.split(",")}, hosts)
        self.assertIn('Services.prefs.setStringPref("network.dns.localDomains", arguments[0].join(","));', test)
        self.assertIn("m.chrome(PREPARE, [list(LOCAL_ONLY),", test)


HARNESS = """const port = 1;
const { runScreenFingerprintTests } = require('./screen-fingerprint-test');
  if (categories.includes('screenFingerprint')) {
"""


class WatchTest(unittest.TestCase):
    """scripts/research/watch_privacytests.py, with their repository stood in for by the files here."""

    def setUp(self):
        self.theirs = {
            path: (FIXTURES / Path(path).name).read_bytes() for path in PINNED["files"] if not path.startswith("scripts/")
        }

    def read(self, path: str) -> bytes | None:
        return self.theirs.get(path)

    def pins(self) -> dict:
        # Only what this test can stand in for: the copied files, and one function written here.
        body = "const scoreIt = (results) => {\n  return results;\n};"
        self.theirs["scripts/render.js"] = f"const other = 1;\n\n{body}\n\nconst more = 2;\n".encode()
        self.theirs["scripts/test.js"] = HARNESS.encode()
        return {
            "commit": PINNED["commit"],
            "files": {path: digest for path, digest in PINNED["files"].items() if path in self.theirs},
            "functions": {"scripts/render.js": {"scoreIt": watch.digest(body.encode())}},
            "mentions": {"scripts/test.js": watch.digest(watch.mentions(HARNESS).encode())},
        }

    def test_the_same_files_are_no_change(self):
        self.assertEqual(watch.compare(self.pins(), self.read), [])

    def test_a_changed_file_a_missing_file_and_a_changed_function_are_named(self):
        pins = self.pins()
        self.theirs["static/settingsFingerprinting.js"] += b"\n// a new probe\n"
        del self.theirs["static/screenFingerprinting.js"]
        self.theirs["scripts/render.js"] = self.theirs["scripts/render.js"].replace(b"return results;", b"return null;")
        self.assertEqual(
            watch.compare(pins, self.read),
            [
                "`static/screenFingerprinting.js` is gone",
                "`static/settingsFingerprinting.js` changed",
                "`scoreIt` in `scripts/render.js` changed",
            ],
        )
        # A function that was renamed or removed is a change too; the rest of its file may change freely.
        self.theirs["scripts/render.js"] = b"const somethingElse = () => {\n};\n"
        self.assertIn("`scoreIt` is no longer in `scripts/render.js`", watch.compare(pins, self.read))

    def test_a_new_group_of_probes_in_their_harness_is_a_change(self):
        pins = self.pins()
        # Their harness changes for other reasons all the time: that is no change here.
        self.theirs["scripts/test.js"] = HARNESS.replace("const port = 1;", "const port = 2;").encode()
        self.assertEqual(watch.compare(pins, self.read), [])
        self.theirs["scripts/test.js"] = (HARNESS + "  if (categories.includes('fontFingerprint')) {\n").encode()
        self.assertEqual(
            watch.compare(pins, self.read),
            ['the lines of `scripts/test.js` that say "fingerprint" changed (a new group of probes?)'],
        )
        del self.theirs["scripts/test.js"]
        self.assertEqual(watch.compare(pins, self.read), ["`scripts/test.js` is gone"])

    def test_the_pins_name_their_scoring_too(self):
        self.assertEqual(
            {path: sorted(names) for path, names in PINNED["functions"].items()},
            {
                "scripts/render.js": ["scoreDeviceFingerprintingConsistency"],
                "scripts/test.js": ["mergeDeviceFingerprintDomainResults"],
            },
        )
        for path in ("scripts/settings-fingerprint-test.js", "scripts/screen-fingerprint-test.js"):
            self.assertIn(path, PINNED["files"])
        self.assertEqual(sorted(PINNED["mentions"]), ["scripts/render.js", "scripts/test.js"])

    def test_a_ref_is_a_plain_name(self):
        for ref in ("../etc", "a b", "x" * 81, "main;rm"):
            with self.subTest(ref=ref), self.assertRaises(SystemExit):
                watch.main(["--ref", ref])


if __name__ == "__main__":
    unittest.main()
