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

    def test_the_release_before_is_the_newest_older_one_with_a_portable_archive(self):
        releases = [*RELEASES, {"tagName": "v160.0-0.2", "isDraft": False}]
        archives = {"v160.0-0.5", "v160.0-0.2"}  # 0.4 as if it had RPMs only, as the first releases did
        self.assertEqual(fetch_releases.pair(releases, None, archives.__contains__), ("v160.0-0.5", "v160.0-0.2"))
        with self.assertRaises(fetch_releases.FetchError):  # none older has one
            fetch_releases.pair(releases, None, {"v160.0-0.5"}.__contains__)
        with self.assertRaises(fetch_releases.FetchError):  # the release to measure has none
            fetch_releases.pair(releases, None, {"v160.0-0.2"}.__contains__)


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


class FetchTest(unittest.TestCase):
    """fetch() with gh and gpg stood in for: it unpacks only an archive whose SHA256SUMS has a good signature by the
    release key and lists the archive's digest."""

    TAG = "v160.0-0.5"

    def setUp(self):
        import hashlib
        import io
        import tarfile
        import tempfile

        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.out)
        packed = io.BytesIO()
        with tarfile.open(fileobj=packed, mode="w:xz") as tar:
            info = tarfile.TarInfo("nulavio/nulavio")
            info.size = 2
            tar.addfile(info, io.BytesIO(b"#!"))
        self.archive = packed.getvalue()
        self.name = fetch_releases.archive_name(self.TAG)
        self.sums = f"{hashlib.sha256(self.archive).hexdigest()}  {self.name}\n"

    def run_fetch(self, status: str, returncode: int = 0, sums: str | None = None):
        from unittest import mock

        def gh(*args):
            folder = Path(args[args.index("--dir") + 1])
            name = args[args.index("--pattern") + 1]
            data = {self.name: self.archive, "SHA256SUMS": (sums or self.sums).encode(), "SHA256SUMS.asc": b"sig"}[name]
            (folder / name).write_bytes(data)
            return ""

        def gpg(command, **kwargs):
            return mock.Mock(
                returncode=returncode if "--verify" in command else 0, stdout=status if "--verify" in command else ""
            )

        with (
            mock.patch.object(fetch_releases, "gh", side_effect=gh),
            mock.patch.object(fetch_releases.subprocess, "run", side_effect=gpg),
        ):
            fetch_releases.fetch(self.TAG, self.out / "new")

    def good(self, primary: str = fetch_releases.FINGERPRINT) -> str:
        return f"[GNUPG:] VALIDSIG 827E658608679618CD349F93678E455D76767AA3 2026-11-14 1 0 4 0 1 10 00 {primary}\n"

    def test_a_good_signature_by_the_release_key_and_the_listed_digest_unpack(self):
        self.run_fetch(self.good())
        self.assertEqual((self.out / "new" / "nulavio" / "nulavio").read_bytes(), b"#!")

    def test_a_bad_signature_another_key_or_another_digest_unpack_nothing(self):
        cases = {
            "bad signature": dict(status="[GNUPG:] BADSIG BF47E5FA9EDB8DB1 x\n", returncode=1),
            "another key": dict(status=self.good("0" * 40)),
            "another digest": dict(status=self.good(), sums=f"{'0' * 64}  {self.name}\n"),
            "not listed": dict(status=self.good(), sums=f"{'0' * 64}  other.tar.xz\n"),
        }
        for label, case in cases.items():
            with self.subTest(label), self.assertRaises(fetch_releases.FetchError):
                self.run_fetch(**case)
            self.assertFalse((self.out / "new").exists(), label)


class SumsTest(unittest.TestCase):
    def test_the_archive_line_is_found_exactly(self):
        sums = "aaa  nulavio-160.0-0.5.linux-x86_64.tar.xz\nbbb  nulavio-160.0-0.5.linux-x86_64.tar.xz.cdx.json\n"
        self.assertEqual(fetch_releases.listed(sums, "nulavio-160.0-0.5.linux-x86_64.tar.xz"), "aaa")
        self.assertIsNone(fetch_releases.listed(sums, "nulavio-160.0-0.4.linux-x86_64.tar.xz"))


if __name__ == "__main__":
    unittest.main()
