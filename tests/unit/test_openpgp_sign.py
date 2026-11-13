"""Signatures from scripts/release/openpgp_sign.py verify with gpg, and the KMS path refuses a wrong key.

A throwaway RSA key is made with gpg for the run. The tests sign with its private
exponent directly (the role KMS plays in a release), through a fake `aws` command
for the command-line path, and check every signature with `gpg --verify`.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import openpgp_sign as ops  # noqa: E402

SCRIPT = ROOT / "scripts" / "release" / "openpgp_sign.py"


def secret_numbers(data: bytes) -> tuple[int, int, int]:
    """(n, e, d) from an unprotected version 4 RSA secret key packet."""
    for tag, body in ops.packets(data):
        if tag != 5:
            continue
        n, offset = ops.read_mpi(body, 6)
        e, offset = ops.read_mpi(body, offset)
        if body[offset] != 0:
            raise AssertionError("test key is protected")
        d, _ = ops.read_mpi(body, offset + 1)
        return n, e, d
    raise AssertionError("no secret key packet")


def der(tag: int, body: bytes) -> bytes:
    n = len(body)
    if n < 128:
        return bytes([tag, n]) + body
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(raw)]) + raw + body


def der_int(value: int) -> bytes:
    raw = value.to_bytes(value.bit_length() // 8 + 1, "big")  # leading zero keeps it positive
    return der(0x02, raw)


def spki(n: int, e: int) -> bytes:
    rsa_oid = der(0x30, bytes.fromhex("06092a864886f70d0101010500"))
    return der(0x30, rsa_oid + der(0x03, b"\x00" + der(0x30, der_int(n) + der_int(e))))


FAKE_AWS = r"""#!/usr/bin/env python3
import base64, json, os, sys
key = json.load(open(os.environ["FAKE_KMS_KEY"]))
args = sys.argv[1:]
with open(os.environ["FAKE_KMS_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["kms", "get-public-key"]:
    print(json.dumps({"KeyUsage": "SIGN_VERIFY", "SigningAlgorithms": ["RSASSA_PKCS1_V1_5_SHA_256"],
                      "PublicKey": key["spki"]}))
elif args[:2] == ["kms", "sign"]:
    path = args[args.index("--message") + 1].removeprefix("fileb://")
    digest = open(path, "rb").read()
    n, d = key["n"], key["d"]
    size = (n.bit_length() + 7) // 8
    t = bytes.fromhex("3031300d060960864801650304020105000420") + digest
    em = b"\x00\x01" + b"\xff" * (size - len(t) - 3) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(size, "big")
    print(json.dumps({"Signature": base64.b64encode(sig).decode()}))
else:
    sys.exit(2)
"""


@unittest.skipUnless(shutil.which("gpg"), "needs gpg")
class OpenPgpSignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nulavio-ops-"))
        cls.home = cls.tmp / "gnupg"
        cls.home.mkdir(mode=0o700)
        cls.gpg(
            "--passphrase", "", "--quick-gen-key", "Throwaway release key <release@example.invalid>",
            "rsa2048", "sign", "never",
        )  # fmt: skip
        cls.cert = cls.gpg("--armor", "--export").stdout
        cls.key = ops.primary_key(cls.cert)
        cls.n, cls.e, cls.d = secret_numbers(cls.gpg("--passphrase", "", "--export-secret-keys").stdout)
        (cls.tmp / "key.asc").write_bytes(cls.cert)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--homedir", str(cls.home), "--kill", "gpg-agent"], capture_output=True, check=False)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def gpg(cls, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["gpg", "--homedir", str(cls.home), "--batch", "--pinentry-mode", "loopback", *args],
            capture_output=True, check=check,
        )  # fmt: skip

    def local_signer(self, digest: bytes) -> bytes:
        size = (self.n.bit_length() + 7) // 8
        em = ops.emsa_pkcs1_v15(digest, size)
        return pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(size, "big")

    def verify(self, signature: bytes, data: bytes) -> subprocess.CompletedProcess:
        sig = self.tmp / "data.sig"
        doc = self.tmp / "data"
        sig.write_bytes(signature)
        doc.write_bytes(data)
        return self.gpg("--status-fd", "1", "--verify", str(sig), str(doc), check=False)

    def test_fingerprint_matches_gpg(self):
        listing = self.gpg("--with-colons", "--list-keys").stdout.decode()
        fpr = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
        self.assertEqual(self.key.hex, fpr)

    def test_binary_and_armored_signatures_verify_with_gpg(self):
        data = b"<repomd>example</repomd>\n"
        packet = ops.signature_packet(data, self.key, self.local_signer)
        for form in (packet, ops.armor(packet)):
            with self.subTest(armored=form is not packet):
                result = self.verify(form, data)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertIn(f"VALIDSIG {self.key.hex}", result.stdout.decode())

    def test_large_input_and_creation_time(self):
        data = os.urandom(300_000)
        created = int(time.time()) + 5  # after the key's creation, or gpg refuses it
        packet = ops.signature_packet(data, self.key, self.local_signer, created=created)
        result = self.verify(packet, data)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(f" {created} ", result.stdout.decode())  # VALIDSIG carries the creation time

    def test_changed_data_does_not_verify(self):
        packet = ops.signature_packet(b"SHA256SUMS\n", self.key, self.local_signer)
        result = self.verify(packet, b"SHA256SUMS changed\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BADSIG", result.stdout.decode())

    def test_signature_from_another_key_is_refused(self):
        other = ops.PublicKey(self.key.fingerprint, self.key.modulus - 2, self.key.exponent)
        with self.assertRaisesRegex(ops.SignError, "does not verify|returned"):
            ops.signature_packet(b"x", other, self.local_signer)

    def test_der_public_key_round_trip(self):
        self.assertEqual(ops.der_rsa_public_key(spki(self.n, self.e)), (self.n, self.e))

    def test_armor_round_trip(self):
        packet = ops.signature_packet(b"x", self.key, self.local_signer)
        self.assertEqual(ops.dearmor(ops.armor(packet)), packet)
        self.assertEqual(ops.dearmor(packet), packet)

    def test_cleartext_signature_verifies_with_gpg_and_gpgv(self):
        # An APT repository's InRelease: what apt checks before it trusts any index.
        text = b"Origin: Nulavio\nSuite: stable\n-Dash: escaped\nSHA256:\n abc 12 main/binary-amd64/Packages\n"
        signed = ops.cleartext_signed(text, self.key, self.local_signer)
        self.assertTrue(signed.startswith(b"-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\nOrigin: Nulavio\n"))
        # A canonical-text signature (0x01): gpgv also accepts a binary one here, apt's sqv refuses it.
        packet = ops.dearmor(signed[signed.index(b"-----BEGIN PGP SIGNATURE-----") :])
        ((tag, body),) = list(ops.packets(packet))
        self.assertEqual((tag, body[0], body[1]), (ops.SIGNATURE_TAG, 4, ops.CANONICAL_TEXT))
        self.assertIn(b"\n- -Dash: escaped\n", signed)
        path = self.tmp / "InRelease"
        path.write_bytes(signed)
        result = self.gpg(
            "--status-fd", "1", "--output", str(self.tmp / "InRelease.out"), "--yes", "--verify", str(path), check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn(f"VALIDSIG {self.key.hex}", result.stdout.decode())
        # What gpg hands back is the text as given, last newline included.
        self.gpg("--output", str(self.tmp / "InRelease.txt"), "--yes", "--decrypt", str(path))
        self.assertEqual((self.tmp / "InRelease.txt").read_bytes(), text)
        if shutil.which("gpgv"):  # what apt calls (or sqv, which reads the same format)
            keyring = self.tmp / "keyring.gpg"
            keyring.write_bytes(ops.dearmor(self.cert))
            gpgv = subprocess.run(["gpgv", "--keyring", str(keyring), str(path)], capture_output=True, check=False)
            self.assertEqual(gpgv.returncode, 0, gpgv.stderr.decode())

    def test_cleartext_signature_covers_every_line(self):
        signed = ops.cleartext_signed(b"Suite: stable\nCodename: stable\n", self.key, self.local_signer)
        for tampered in (
            signed.replace(b"Suite: stable", b"Suite: stablX"),
            signed.replace(b"Codename: stable\n", b"Codename: stable\nValid-Until: never\n"),
            signed.replace(b"Codename: stable\n", b""),
        ):
            path = self.tmp / "tampered"
            path.write_bytes(tampered)
            result = self.gpg("--status-fd", "1", "--verify", str(path), check=False)
            self.assertNotEqual(result.returncode, 0)

    def test_cleartext_refuses_text_it_would_have_to_change(self):
        for text in (b"", b"a \n", b"a\t\nb\n", b"a\r\nb\n", b"\xff\xfe\n"):
            with self.subTest(text=text), self.assertRaises(ops.SignError):
                ops.cleartext_signed(text, self.key, self.local_signer)

    def run_cli(self, kms_key: dict, *args: str) -> subprocess.CompletedProcess:
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        aws = bin_dir / "aws"
        aws.write_text(FAKE_AWS)
        aws.chmod(0o700)
        key_file = self.tmp / "kms.json"
        key_file.write_text(json.dumps(kms_key))
        log = self.tmp / "aws.log"
        log.write_text("")
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_KMS_KEY": str(key_file), "FAKE_KMS_LOG": str(log),
        }  # fmt: skip
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--public-key", str(self.tmp / "key.asc"), "--kms-key-id", "alias/test", *args],
            capture_output=True, text=True, env=env, check=False,
        )  # fmt: skip

    def test_command_line_signs_through_kms(self):
        doc = self.tmp / "SHA256SUMS"
        doc.write_bytes(b"abc  nulavio.rpm\n")
        out = self.tmp / "SHA256SUMS.asc"
        kms_key = {"n": self.n, "d": self.d, "spki": base64.b64encode(spki(self.n, self.e)).decode()}
        proc = self.run_cli(kms_key, "--armor", "-o", str(out), str(doc))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out.read_bytes().startswith(b"-----BEGIN PGP SIGNATURE-----"))
        result = self.gpg("--status-fd", "1", "--verify", str(out), str(doc), check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        calls = [json.loads(line) for line in (self.tmp / "aws.log").read_text().splitlines()]
        self.assertEqual([c[:2] for c in calls], [["kms", "get-public-key"], ["kms", "sign"]])
        sign = calls[1]
        self.assertEqual(sign[sign.index("--message-type") + 1], "DIGEST")
        self.assertEqual(sign[sign.index("--signing-algorithm") + 1], "RSASSA_PKCS1_V1_5_SHA_256")

    def test_command_line_clearsigns_through_kms(self):
        doc = self.tmp / "Release"
        doc.write_bytes(b"Origin: Nulavio\nSuite: stable\n")
        out = self.tmp / "InRelease.kms"
        kms_key = {"n": self.n, "d": self.d, "spki": base64.b64encode(spki(self.n, self.e)).decode()}
        proc = self.run_cli(kms_key, "--clearsign", "-o", str(out), str(doc))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = self.gpg("--status-fd", "1", "--verify", str(out), check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        doc.write_bytes(b"Origin: Nulavio \n")
        refused = self.run_cli(kms_key, "--clearsign", "-o", str(self.tmp / "InRelease.refused"), str(doc))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("ends in a space", refused.stderr)
        self.assertFalse((self.tmp / "InRelease.refused").exists())

    def test_command_line_refuses_a_kms_key_that_is_not_the_release_key(self):
        doc = self.tmp / "repomd.xml"
        doc.write_bytes(b"<repomd/>")
        out = self.tmp / "repomd.xml.asc"
        out.unlink(missing_ok=True)
        wrong = {"n": self.n, "d": self.d, "spki": base64.b64encode(spki(self.n + 2, self.e)).decode()}
        proc = self.run_cli(wrong, "-o", str(out), str(doc))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("is not the release key", proc.stderr)
        self.assertFalse(out.exists())
        calls = (self.tmp / "aws.log").read_text().splitlines()
        self.assertEqual(len(calls), 1, "no Sign call once the key does not match")


if __name__ == "__main__":
    unittest.main()
