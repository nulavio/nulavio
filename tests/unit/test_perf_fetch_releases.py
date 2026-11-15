"""scripts/perf/fetch_releases.py: which two releases perf.yml compares, and what it requires of their files (#80)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("fetch_releases", ROOT / "scripts" / "perf" / "fetch_releases.py")
fetch_releases = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch_releases)

RELEASES = [  # gh release list --json tagName,isDraft: newest first
    {"tagName": "v160.0-0.6", "isDraft": True},
    {"tagName": "v160.0-0.5", "isDraft": False},
    {"tagName": "v160.0-0.4", "isDraft": False},
]


class PairTest(unittest.TestCase):
    def test_the_latest_published_release_and_the_one_before_it_never_a_draft(self):
        self.assertEqual(fetch_releases.pair(RELEASES, None), ("v160.0-0.5", "v160.0-0.4"))
        self.assertEqual(fetch_releases.pair(RELEASES, "v160.0-0.5"), ("v160.0-0.5", "v160.0-0.4"))
        for tag in ("v160.0-0.6", "v160.0-0.4", "v9"):  # a draft, the oldest, an unknown tag
            with self.subTest(tag=tag), self.assertRaises(fetch_releases.FetchError):
                fetch_releases.pair(RELEASES, tag)


class SignatureTest(unittest.TestCase):
    def test_only_a_good_signature_names_its_primary_key(self):
        good = (
            "[GNUPG:] NEWSIG\n[GNUPG:] GOODSIG BF47E5FA9EDB8DB1 Nulavio\n"
            "[GNUPG:] VALIDSIG 827E658608679618CD349F93678E455D76767AA3 2026-11-14 1794700000 0 4 0 1 10 00 "
            "298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1\n"
        )
        self.assertEqual(fetch_releases.signer(good), fetch_releases.FINGERPRINT)
        self.assertIsNone(fetch_releases.signer("[GNUPG:] BADSIG BF47E5FA9EDB8DB1 Nulavio\n"))
        self.assertIsNone(fetch_releases.signer(""))

    def test_the_fingerprint_is_the_published_release_keys(self):
        site = (ROOT / "site" / "keys").glob("*.asc")
        self.assertTrue(any(path.name == "nulavio-packages.asc" for path in site))
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn(f"FINGERPRINT: {fetch_releases.FINGERPRINT}", release)


class SumsTest(unittest.TestCase):
    def test_the_archive_line_is_found_exactly(self):
        sums = "aaa  nulavio-160.0-0.5.linux-x86_64.tar.xz\nbbb  nulavio-160.0-0.5.linux-x86_64.tar.xz.cdx.json\n"
        self.assertEqual(fetch_releases.listed(sums, "nulavio-160.0-0.5.linux-x86_64.tar.xz"), "aaa")
        self.assertIsNone(fetch_releases.listed(sums, "nulavio-160.0-0.4.linux-x86_64.tar.xz"))


if __name__ == "__main__":
    unittest.main()
