"""Pinned-key signature checks (scripts/upstream/signatures.py) and the keys kept in the repository."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))

import signatures  # noqa: E402
import verify_claude_code_release as verify_cc  # noqa: E402
import verify_firefox_release as verify_ff  # noqa: E402

P = "3D802B4BCE10F4BAF205DD4C2B18015146E64414"  # pinned primary (throwaway)
CUR = "DA08803AFFEAB887CF6D0706FF9C724CE57530D6"  # allowed signing subkey
EXP = "2E1BF41A6D84B1113370ADD8D93A7C78BE3E3DE5"  # expired subkey of P
REV = "E1EC4FF1EED11519755E43AD73195E7FABBC4045"  # revoked subkey of P
ATT = "CC1B3441DE633580A483F8425127A730D5C98B13"  # attacker's own key


def sig(kind: str, fpr: str, primary: str = P) -> str:
    """One signature's gpg status lines, shaped like gpg 2.4's output."""
    return (
        "[GNUPG:] NEWSIG\n"
        "[GNUPG:] KEYEXPIRED 1730097267\n"  # about another subkey in the key file: not a rejection
        f"[GNUPG:] KEY_CONSIDERED {primary} 0\n"
        f"[GNUPG:] {kind} {fpr[-16:]} Someone <s@example.invalid>\n"
        f"[GNUPG:] VALIDSIG {fpr} 2026-10-28 1793169267 0 4 0 22 10 00 {primary}\n"
    )


class StatusTest(unittest.TestCase):
    def check(self, status: str, signers=(CUR,)) -> str:
        return signatures.check_status(status + "[GNUPG:] TRUST_UNDEFINED 0 pgp\n", P, signers)

    def rejected(self, status: str, signers=(CUR,)) -> str:
        with self.assertRaises(signatures.SignatureError) as caught:
            self.check(status, signers)
        return str(caught.exception)

    def no_signature(self) -> str:
        for status in ("", "[GNUPG:] NEWSIG\n", "gpg: no valid OpenPGP data found.\n"):
            with self.assertRaises(signatures.SignatureError) as caught:
                signatures.check_status(status, P, (CUR,))
        return str(caught.exception)

    def test_a_good_signature_by_a_pinned_subkey(self):
        self.assertEqual(self.check(sig("GOODSIG", CUR)), CUR)
        self.assertEqual(self.check(sig("GOODSIG", CUR.lower())), CUR)

    def test_expired_or_revoked_signing_keys_are_refused(self):
        self.assertIn("EXPKEYSIG", self.rejected(sig("EXPKEYSIG", EXP), (CUR, EXP)))
        self.assertIn("REVKEYSIG", self.rejected(sig("REVKEYSIG", REV), (CUR, REV)))
        self.assertIn("BADSIG", self.rejected(sig("BADSIG", CUR)))
        self.assertIn("ERRSIG", self.rejected("[GNUPG:] NEWSIG\n[GNUPG:] ERRSIG 5127A730D5C98B13 22 10 00 1793169267 9 -\n"))

    def test_a_good_signature_cannot_vouch_for_a_bad_one_next_to_it(self):
        # The order that fooled the old parser: an expired pinned subkey first, the attacker's good signature second.
        self.assertIn("EXPKEYSIG", self.rejected(sig("EXPKEYSIG", EXP) + sig("GOODSIG", ATT, primary=ATT)))
        self.assertIn("REVKEYSIG", self.rejected(sig("REVKEYSIG", REV) + sig("GOODSIG", ATT, primary=ATT)))
        self.assertIn("unexpected primary", self.rejected(sig("GOODSIG", CUR) + sig("GOODSIG", ATT, primary=ATT)))

    def test_other_keys_and_unlisted_subkeys_are_refused(self):
        self.assertIn("unexpected primary", self.rejected(sig("GOODSIG", ATT, primary=ATT)))
        self.assertIn("not a pinned signing key", self.rejected(sig("GOODSIG", EXP)))
        self.assertIn("not a pinned signing key", self.rejected(sig("GOODSIG", P)))  # the primary itself

    def test_incomplete_or_inconsistent_output_is_refused(self):
        self.rejected("")  # only TRUST_UNDEFINED
        self.assertIn("no signature", self.no_signature())
        good, valid = sig("GOODSIG", CUR).splitlines()[3], sig("GOODSIG", CUR).splitlines()[4]
        self.assertIn("good and valid", self.rejected(f"[GNUPG:] NEWSIG\n{good}\n"))
        self.assertIn("good and valid", self.rejected(f"[GNUPG:] NEWSIG\n{valid}\n"))
        self.assertIn("good and valid", self.rejected(f"[GNUPG:] NEWSIG\n{good}\n{good}\n{valid}\n"))
        mismatch = sig("GOODSIG", CUR).replace(f"GOODSIG {CUR[-16:]}", f"GOODSIG {ATT[-16:]}")
        self.assertIn("different keys", self.rejected(mismatch))
        self.assertIn("good and valid", self.rejected("gpg: Good signature from ...\n[GNUPG:] GOODSIG\n"))

    def test_output_without_newsig_is_one_signature(self):
        self.assertEqual(self.check(sig("GOODSIG", CUR).replace("[GNUPG:] NEWSIG\n", "")), CUR)


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgconf"), "gpg not installed")
class RealGpgTest(unittest.TestCase):
    """Throwaway keys: a pinned primary with a current and an expired signing subkey, and an attacker's key."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nv-gpg-"))
        cls.home = cls.tmp / "gnupg"
        cls.home.mkdir(mode=0o700)
        past = int(time.time()) - 3 * 365 * 86400
        cls.gpg("--faked-system-time", f"{past}!", "--quick-gen-key", "Pinned <p@example.invalid>", "ed25519", "cert", "never")
        cls.primary = cls.fingerprints("p@example.invalid")[0]
        cls.gpg("--faked-system-time", f"{past}!", "--quick-add-key", cls.primary, "ed25519", "sign", "1y")
        cls.gpg("--quick-add-key", cls.primary, "ed25519", "sign", "2y")
        cls.gpg("--quick-gen-key", "Attacker <a@example.invalid>", "ed25519", "sign", "never")
        cls.expired, cls.current = cls.fingerprints("p@example.invalid")[1:]
        cls.attacker = cls.fingerprints("a@example.invalid")[0]
        cls.data = cls.tmp / "SHA256SUMS"
        cls.data.write_text(f"{'0' * 64}  source/firefox-999.0.source.tar.xz\n")
        for name, key, when in (("cur", cls.current + "!", None), ("exp", cls.expired + "!", past + 86400),
                                ("att", cls.attacker, None)):  # fmt: skip
            faked = ["--faked-system-time", f"{when}!"] if when else []
            cls.gpg(*faked, "-u", key, "--detach-sign", "-o", str(cls.tmp / f"sig_{name}"), str(cls.data))
        (cls.tmp / "key").write_bytes(cls.export(cls.primary))
        (cls.tmp / "key+att").write_bytes(cls.export(cls.primary) + cls.export(cls.attacker))

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=cls.env(), check=False, capture_output=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def env(cls) -> dict:
        return {**os.environ, "GNUPGHOME": str(cls.home), "LC_ALL": "C"}

    @classmethod
    def gpg(cls, *args: str) -> bytes:
        command = ["gpg", "--batch", "--pinentry-mode", "loopback", "--passphrase", "", *args]
        return subprocess.run(command, env=cls.env(), capture_output=True, check=True, timeout=60).stdout

    @classmethod
    def fingerprints(cls, uid: str) -> list[str]:
        out = cls.gpg("--with-colons", "--with-subkey-fingerprints", "--list-keys", uid).decode()
        return [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:")]

    @classmethod
    def export(cls, fpr: str) -> bytes:
        return cls.gpg("--export", "--armor", fpr)

    def verify(self, *signers_of: str, key: str = "key") -> str:
        signature = self.tmp / ("cmb_" + "_".join(signers_of))
        signature.write_bytes(b"".join((self.tmp / f"sig_{name}").read_bytes() for name in signers_of))
        return signatures.verify(self.data, signature, self.tmp / key, self.primary, {self.current})

    def test_the_current_subkey_passes(self):
        self.assertEqual(self.verify("cur"), self.current)

    def test_expired_attacker_and_mixed_signatures_fail(self):
        for names, key in ((("exp",), "key"), (("att",), "key+att"), (("exp", "att"), "key+att"), (("cur", "att"), "key+att")):
            with self.subTest(names=names), self.assertRaises(signatures.SignatureError):
                self.verify(*names, key=key)

    def test_a_tampered_file_fails(self):
        signature = self.tmp / "sig_cur"
        tampered = self.tmp / "tampered"
        tampered.write_text(self.data.read_text().replace("999.0", "998.0"))
        with self.assertRaisesRegex(signatures.SignatureError, "BADSIG"):
            signatures.verify(tampered, signature, self.tmp / "key", self.primary, {self.current})


@unittest.skipUnless(shutil.which("gpg"), "gpg not installed")
class PinnedKeysTest(unittest.TestCase):
    def keys_in(self, key: Path) -> dict[str, str]:
        """Fingerprint -> gpg validity letter ('r' revoked, 'e' expired, '-' fine) of each key in the file."""
        with tempfile.TemporaryDirectory(prefix="nv-gpg-") as tmp:
            env = {**os.environ, "GNUPGHOME": tmp, "LC_ALL": "C"}
            subprocess.run(["gpg", "--batch", "--quiet", "--import", str(key)], env=env, capture_output=True, check=True)
            out = subprocess.run(["gpg", "--with-colons", "--with-subkey-fingerprints", "--list-keys"],
                                 env=env, capture_output=True, text=True, check=True).stdout  # fmt: skip
            subprocess.run(["gpgconf", "--kill", "gpg-agent"], env=env, check=False, capture_output=True)
        found, validity = {}, "?"
        for line in out.splitlines():
            fields = line.split(":")
            if fields[0] in ("pub", "sub"):
                validity = fields[1]
            elif fields[0] == "fpr":
                found[fields[9]] = validity
        return found

    def test_mozilla_key_keeps_its_revocation_and_the_pinned_subkey_is_usable(self):
        keys = self.keys_in(verify_ff.KEY_FILE)
        self.assertEqual(next(iter(keys)), verify_ff.PINNED_PRIMARY)
        self.assertEqual(keys["09BEED63F3462A2DFFAB3B875ECB6497C1A20256"], "r")  # "We no longer trust this key" (2026-08-06)
        for subkey in verify_ff.SIGNING_SUBKEYS:
            self.assertEqual(
                keys[subkey], "-", "a pinned subkey that expired or was revoked: see scripts/upstream/keys/README.md"
            )

    def test_claude_code_key_is_the_published_one(self):
        keys = self.keys_in(verify_cc.KEY_FILE)
        self.assertEqual(next(iter(keys)), verify_cc.PINNED_PRIMARY)
        self.assertEqual(
            verify_cc.KEY_FILE.read_bytes(), (ROOT / "tests" / "fixtures" / "claude-code" / "claude-code.asc").read_bytes()
        )


if __name__ == "__main__":
    unittest.main()
