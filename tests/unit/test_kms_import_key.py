"""scripts/release/kms_import_key.py: reading the key, the PKCS#8 material, and the KMS wrapping.

Uses a throwaway gpg key without a passphrase, whose agent key file has the same
format as the release key's after `gpg --passwd` with an empty passphrase.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


@unittest.skipUnless(shutil.which("gpg"), "needs gpg")
class KmsImportKeyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nulavio-kik-"))
        home = cls.tmp / "gnupg"
        home.mkdir(mode=0o700)
        cls.home = home

        def gpg(*args: str) -> bytes:
            return subprocess.run(
                ["gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback", "--passphrase", "", *args],
                capture_output=True, check=True,
            ).stdout  # fmt: skip

        gpg("--quick-gen-key", "Throwaway <t@example.invalid>", "rsa2048", "sign", "1d")
        cls.key = ops.primary_key(gpg("--export"))
        grips = gpg("--with-colons", "--with-keygrip", "--list-secret-keys").decode()
        grip = next(line.split(":")[9] for line in grips.splitlines() if line.startswith("grp:"))
        cls.key_file = (home / "private-keys-v1.d" / f"{grip}.key").read_text(encoding="ascii")

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["gpgconf", "--homedir", str(cls.home), "--kill", "gpg-agent"], capture_output=True, check=False)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_reads_the_numbers_of_the_matching_key(self):
        numbers = kik.rsa_numbers(self.key_file)
        self.assertEqual((numbers["n"], numbers["e"]), (self.key.modulus, self.key.exponent))

    def test_refuses_a_protected_or_damaged_key_file(self):
        with self.assertRaisesRegex(kik.KeyImportError, "still protected"):
            kik.rsa_numbers("Key: (protected-private-key (rsa (n #00AB#)))")
        damaged = self.key_file.replace("(p #", "(p #0F", 1)
        with self.assertRaises(kik.KeyImportError):
            kik.rsa_numbers(damaged)

    @unittest.skipUnless(shutil.which("openssl"), "needs openssl")
    def test_pkcs8_is_a_valid_rsa_key_with_the_same_modulus(self):
        der = self.tmp / "key.der"
        der.write_bytes(kik.pkcs8(kik.rsa_numbers(self.key_file)))
        check = subprocess.run(
            ["openssl", "pkey", "-inform", "DER", "-in", str(der), "-noout", "-check"], capture_output=True, text=True
        )
        self.assertEqual(check.returncode, 0, check.stderr)
        modulus = subprocess.run(
            ["openssl", "rsa", "-inform", "DER", "-in", str(der), "-noout", "-modulus"], capture_output=True, text=True
        ).stdout
        self.assertEqual(int(modulus.strip().split("=")[1], 16), self.key.modulus)

    @unittest.skipIf(rsa is None, "needs python3-cryptography")
    def test_wrapping_unwraps_to_the_key_material(self):
        wrapping = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        public_der = wrapping.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        material = kik.pkcs8(kik.rsa_numbers(self.key_file))
        blob = kik.wrap_for_kms(material, public_der)
        oaep = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
        aes_key = wrapping.decrypt(blob[:512], oaep)
        self.assertEqual(aes_key_unwrap_with_padding(aes_key, blob[512:]), material)


if __name__ == "__main__":
    unittest.main()
