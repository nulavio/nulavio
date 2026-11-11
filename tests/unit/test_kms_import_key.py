"""scripts/release/kms_import_key.py: decrypting the exported key, the PKCS#8 material, and the KMS wrapping.

Uses a throwaway gpg key with a passphrase, exported the way the import exports
the release key (gpg --export-secret-keys, passphrase on standard input).
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import kms_import_key as kik  # noqa: E402
import openpgp_sign as ops  # noqa: E402

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.keywrap import aes_key_unwrap_with_padding
except ModuleNotFoundError:
    rsa = None


FAKE_KMS = r"""#!/usr/bin/env python3
import base64, json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.keywrap import aes_key_unwrap_with_padding

state = Path(os.environ["FAKE_KMS_STATE"])
args = sys.argv[1:]
(state / "calls").open("a").write(" ".join(args[:2]) + "\n")
def arg(name):
    return args[args.index(name) + 1]
def out(obj):
    print(json.dumps(obj) if "--query" not in args else obj)
material = state / "material.der"
ARN = "arn:aws:kms:us-east-1:111122223333:key/test"
if args[1] in ("get-parameters-for-import", "import-key-material") and arg("--key-id") != ARN:
    sys.stderr.write("InvalidArnException: Key Aliases are not supported for this operation.\n")
    sys.exit(254)
if args[:2] == ["kms", "describe-key"]:
    out({"KeyMetadata": {"Arn": ARN, "Origin": "EXTERNAL", "KeySpec": "RSA_4096", "KeyUsage": "SIGN_VERIFY",
                         "KeyState": "Enabled" if material.exists() else "PendingImport"}})
elif args[:2] == ["kms", "get-parameters-for-import"]:
    assert arg("--wrapping-algorithm") == "RSA_AES_KEY_WRAP_SHA_256"
    wrapping = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    (state / "wrapping.pem").write_bytes(wrapping.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public = wrapping.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    print(base64.b64encode(public).decode() + "\t" + base64.b64encode(b"token").decode())
elif args[:2] == ["kms", "import-key-material"]:
    wrapping = serialization.load_pem_private_key((state / "wrapping.pem").read_bytes(), None)
    blob = Path(arg("--encrypted-key-material").removeprefix("fileb://")).read_bytes()
    assert Path(arg("--import-token").removeprefix("fileb://")).read_bytes() == b"token"
    oaep = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    aes_key = wrapping.decrypt(blob[:512], oaep)
    material.write_bytes(aes_key_unwrap_with_padding(aes_key, blob[512:]))
    print("{}")
elif args[:2] in (["kms", "get-public-key"], ["kms", "sign"]):
    key = serialization.load_der_private_key(material.read_bytes(), None)
    if args[1] == "get-public-key":
        public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        print(json.dumps({"KeyUsage": "SIGN_VERIFY", "SigningAlgorithms": ["RSASSA_PKCS1_V1_5_SHA_256"],
                          "PublicKey": base64.b64encode(public).decode()}))
    else:
        from cryptography.hazmat.primitives.asymmetric import utils
        digest = Path(arg("--message").removeprefix("fileb://")).read_bytes()
        sig = key.sign(digest, padding.PKCS1v15(), utils.Prehashed(hashes.SHA256()))
        print(json.dumps({"Signature": base64.b64encode(sig).decode()}))
else:
    sys.exit(2)
"""


PASSPHRASE = b"throwaway passphrase, 2026"


@unittest.skipUnless(shutil.which("gpg"), "needs gpg")
@unittest.skipIf(rsa is None, "needs python3-cryptography")
class KmsImportKeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nulavio-kik-"))
        home = cls.tmp / "gnupg"
        home.mkdir(mode=0o700)
        cls.home = home

        def gpg(*args: str, passphrase: bytes = PASSPHRASE) -> bytes:
            return subprocess.run(
                ["gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback", "--passphrase-fd", "0", *args],
                input=passphrase, capture_output=True, check=True,
            ).stdout  # fmt: skip

        gpg("--quick-gen-key", "Throwaway <t@example.invalid>", "rsa2048", "sign", "1d")
        cls.key = ops.primary_key(gpg("--export"))
        cls.export = gpg("--export-secret-keys")  # protected with PASSPHRASE, as the release key's export is

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--homedir", str(cls.home), "--kill", "gpg-agent"], capture_output=True, check=False)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_decrypts_the_export_to_the_matching_key(self):
        numbers = kik.secret_numbers(self.export, PASSPHRASE)
        self.assertEqual((numbers["n"], numbers["e"]), (self.key.modulus, self.key.exponent))
        self.assertEqual(numbers["p"] * numbers["q"], numbers["n"])

    def test_refuses_a_wrong_passphrase(self):
        with self.assertRaisesRegex(kik.KeyImportError, "wrong passphrase"):
            kik.secret_numbers(self.export, b"not the passphrase")

    def test_refuses_an_export_without_a_secret_key(self):
        with self.assertRaisesRegex(kik.KeyImportError, "no secret key"):
            kik.secret_numbers(ops.dearmor(ops.armor(ops.new_packet(6, b"\x04" + bytes(5)))), PASSPHRASE)

    def test_s2k_matches_the_rfc_count_encoding(self):
        # Iterated and salted, SHA-256, count byte 0x60 = (16 + 0) << (6 + 6) = 65536 bytes hashed.
        spec = bytes([3, 8]) + b"saltsalt" + bytes([0x60])
        key, used = kik.s2k_key(b"pw", spec, 32)
        data = b"saltsaltpw"
        expected = hashlib.sha256((data * (65536 // len(data) + 1))[:65536]).digest()
        self.assertEqual((key, used), (expected, 11))

    @unittest.skipUnless(shutil.which("openssl"), "needs openssl")
    def test_pkcs8_is_a_valid_rsa_key_with_the_same_modulus(self):
        der = self.tmp / "key.der"
        der.write_bytes(kik.pkcs8(kik.secret_numbers(self.export, PASSPHRASE)))
        check = subprocess.run(
            ["openssl", "pkey", "-inform", "DER", "-in", str(der), "-noout", "-check"], capture_output=True, text=True
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        modulus = subprocess.run(
            ["openssl", "rsa", "-inform", "DER", "-in", str(der), "-noout", "-modulus"], capture_output=True, text=True
        ).stdout
        self.assertEqual(int(modulus.strip().split("=")[1], 16), self.key.modulus)

    def test_wrapping_unwraps_to_the_key_material(self):
        wrapping = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        public_der = wrapping.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        material = kik.pkcs8(kik.secret_numbers(self.export, PASSPHRASE))
        blob = kik.wrap_for_kms(material, public_der)
        oaep = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
        aes_key = wrapping.decrypt(blob[:512], oaep)
        self.assertEqual(aes_key_unwrap_with_padding(aes_key, blob[512:]), material)

    def test_whole_import_against_a_stand_in_kms(self):
        state = self.tmp / "kms"
        state.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "aws").write_text(FAKE_KMS.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        (bin_dir / "aws").chmod(0o700)
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_KMS_STATE": str(state)}
        argv = ["--gnupghome", str(self.home), "--fingerprint", self.key.hex, "--kms-key-id", "alias/test"]
        with mock.patch.dict(os.environ, env):
            # A wrong passphrase stops before anything is imported, and says why (gpg's error, or ours
            # when gpg-agent still caches the right one).
            stderr = io.StringIO()
            with mock.patch.object(kik.getpass, "getpass", return_value="wrong"), redirect_stderr(stderr):
                self.assertEqual(kik.main(argv), 1)
            self.assertRegex(stderr.getvalue(), r"gpg --homedir|wrong passphrase")
            self.assertNotIn("import-key-material", (state / "calls").read_text())
            with mock.patch.object(kik.getpass, "getpass", return_value=PASSPHRASE.decode()):
                self.assertEqual(kik.main(argv), 0)
                # A second run finds the key material already there and changes nothing.
                self.assertEqual(kik.main(argv), 1)
        calls = (state / "calls").read_text().split("\n")
        self.assertIn("kms import-key-material", calls)
        self.assertEqual(calls.count("kms import-key-material"), 1)
        self.assertIn("kms sign", calls)  # the check after the import


if __name__ == "__main__":
    unittest.main()
