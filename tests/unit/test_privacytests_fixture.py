"""PrivacyTests.org's probe pages are the ones copied from their repository, unchanged (#79)."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "privacytests"
COMMIT = "12e48c75ec5dbbd127478166b26009f95cbd8918"  # privacytests/privacytests
SHA256 = {
    "LICENSE": "55a79a94fc748ef8a3fe746a126345735f2df49e0a362adb777356001c320a1a",
    "deviceFingerprinting.html": "ccb48c0b8fd245007c65cf4e1dc874bd8aea5ad2e8209ea9bc439bc24597f0cc",
    "deviceFingerprinting.js": "b0fda0738133b9c58fe71cc7dc01b3d0252eeaea41d456d99870724fc697728d",
    "post_data.js": "dddf8b3e1e3d15a500a6dc7f6e1495b0fbb215fe110130621e8df8dc91b1e5a4",
    "screenFingerprinting.html": "9490ba8237d851870dda73b422134c8e23302d3287a014b4c36819d25c67f787",
    "screenFingerprinting.js": "94f09d07201eb4aa88d7d8fe75bb9be634d40359dabd745b0b9b70cf754ee7a5",
    "settingsFingerprinting.html": "17d32567328848ef5e4e26146fd66ab91bb31a365da04c03b6d4f86668b46e56",
    "settingsFingerprinting.js": "3d793302d64d27875d2eb1e4474fc2053303018645b7959f4016732020c6382d",
}


class PrivacyTestsFixtureTest(unittest.TestCase):
    def test_the_files_are_the_pinned_ones_and_nothing_else(self):
        found = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in FIXTURES.iterdir() if path.name != "README.md"
        }
        self.assertEqual(found, SHA256)

    def test_the_readme_names_the_commit_and_the_license(self):
        readme = (FIXTURES / "README.md").read_text(encoding="utf-8")
        self.assertIn(COMMIT, readme)
        self.assertIn("MIT", readme)
        self.assertIn("MIT license", (FIXTURES / "LICENSE").read_text(encoding="utf-8"))

    def test_the_pages_post_only_with_a_session_id(self):
        # The integration test never gives one; this is the line that keeps the results on this machine.
        post = (FIXTURES / "post_data.js").read_text(encoding="utf-8")
        self.assertIn("if (!urlParams.has('sessionId')) {\n      return;\n    }", post)
        test = (ROOT / "tests" / "integration" / "test_privacytests.py").read_text(encoding="utf-8")
        self.assertNotIn("sessionId=", test)


if __name__ == "__main__":
    unittest.main()
