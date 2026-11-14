"""APKs signed by scripts/release/apk_sign.py verify with apksigner, and the KMS path refuses a wrong key.

Throwaway RSA keys are made with openssl for the run. The tests sign with the private
exponent directly (the role KMS plays in a release), or through a fake `aws` command
for the command-line path, and check every APK with Android's own `apksigner verify`
(build-tools, found through ANDROID_HOME or ~/Android/Sdk). CI sets
NULAVIO_REQUIRE_APKSIGNER=1, so a runner without it fails instead of skipping.
The APKs are small ZIPs with a minimal compiled AndroidManifest.xml (apksigner reads
it) and more than 1 MiB of content, so the chunked digest spans several chunks.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import apk_sign  # noqa: E402
import openpgp_sign as ops  # noqa: E402
from test_openpgp_sign import FAKE_AWS  # noqa: E402

SCRIPT = ROOT / "scripts" / "release" / "apk_sign.py"
NOT_BEFORE = datetime.date(2026, 11, 14)


def find_apksigner() -> str | None:
    homes = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), str(Path.home() / "Android" / "Sdk")]
    for home in filter(None, homes):
        tools = sorted(
            (Path(home) / "build-tools").glob("*/apksigner"),
            key=lambda p: [int(x) for x in p.parent.name.split(".") if x.isdigit()],
        )
        if tools:
            return str(tools[-1])
    return shutil.which("apksigner")


APKSIGNER = find_apksigner()
if os.environ.get("NULAVIO_REQUIRE_APKSIGNER") == "1" and not APKSIGNER:
    raise RuntimeError("NULAVIO_REQUIRE_APKSIGNER=1 but no apksigner was found (ANDROID_HOME/build-tools)")


def rsa_key(bits: int = 2048) -> tuple[int, int, int]:
    """(n, e, d) of a new throwaway key, from openssl's PKCS#1 DER."""
    pem = subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", f"rsa_keygen_bits:{bits}"],
                         capture_output=True, check=True).stdout  # fmt: skip
    der = subprocess.run(["openssl", "rsa", "-traditional", "-outform", "DER"], input=pem, capture_output=True, check=True).stdout
    fields = [body for _, body, _ in apk_sign.der_children(apk_sign.der_read(der)[1])]
    n, e, d = (int.from_bytes(value, "big") for value in fields[1:4])
    return n, e, d


def local_signer(n: int, d: int):
    size = (n.bit_length() + 7) // 8
    return lambda digest: pow(int.from_bytes(ops.emsa_pkcs1_v15(digest, size), "big"), d, n).to_bytes(size, "big")


def minimal_manifest(package: str = "net.nulavio.signingtest") -> bytes:
    """A compiled AndroidManifest.xml holding only <manifest package="..."/>: what apksigner reads."""
    strings = ["package", "manifest", package]
    data = b"".join(bytes([len(s), len(s)]) + s.encode() + b"\0" for s in strings)  # UTF-8 pool entries
    data += b"\0" * (-len(data) % 4)
    offsets = [sum(len(s) + 3 for s in strings[:i]) for i in range(len(strings))]
    header = 28 + 4 * len(strings)
    pool = struct.pack("<HHIIIIII", 0x0001, 28, header + len(data), len(strings), 0, 0x100, header, 0)
    pool += b"".join(struct.pack("<I", offset) for offset in offsets) + data
    attribute = struct.pack("<iiiHBBI", -1, 0, 2, 8, 0, 0x03, 2)  # package = string 2
    start = struct.pack("<HHIIi", 0x0102, 16, 36 + len(attribute), 1, -1)
    start += struct.pack("<iiHHHHHH", -1, 1, 20, 20, 1, 0, 0, 0) + attribute
    end = struct.pack("<HHIIiii", 0x0103, 16, 24, 1, -1, -1, 1)
    body = pool + start + end
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def unsigned_apk(path: Path) -> bytes:
    content = os.urandom(2_500_000)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AndroidManifest.xml", minimal_manifest())
        archive.writestr(zipfile.ZipInfo("assets/data.bin"), content)  # stored: 2.5 MB, three chunks
        archive.writestr("classes.dex", b"dex\n" * 1000, compress_type=zipfile.ZIP_DEFLATED)
    return path.read_bytes()


@unittest.skipUnless(shutil.which("openssl"), "needs openssl")
class ApkSignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nulavio-apk-"))
        cls.n, cls.e, cls.d = rsa_key()
        cls.signer = staticmethod(local_signer(cls.n, cls.d))
        cls.cert = apk_sign.certificate(cls.n, cls.e, cls.signer, NOT_BEFORE)
        cls.unsigned = unsigned_apk(cls.tmp / "unsigned.apk")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def apksigner(self, apk: bytes, name: str = "signed.apk") -> subprocess.CompletedProcess:
        if not APKSIGNER:
            self.skipTest("needs apksigner (Android build-tools)")
        path = self.tmp / name
        path.write_bytes(apk)
        # minSdk 24 makes apksigner check the v2 signer too, not only v3 (Android 9 and later).
        return subprocess.run([APKSIGNER, "verify", "-v", "--print-certs", "--min-sdk-version", "24", str(path)],
                              capture_output=True, text=True, check=False)  # fmt: skip

    def test_certificate_holds_the_key_and_its_own_valid_signature(self):
        spki, n, e = apk_sign.certificate_key(self.cert)
        self.assertEqual((n, e), (self.n, self.e))
        self.assertEqual(spki, apk_sign.rsa_spki(self.n, self.e))
        _, body, _, _ = apk_sign.der_read(self.cert)
        tbs, _, signature = apk_sign.der_children(body)
        size = (self.n.bit_length() + 7) // 8
        expected = int.from_bytes(ops.emsa_pkcs1_v15(hashlib.sha256(tbs[2]).digest(), size), "big")
        self.assertEqual(pow(int.from_bytes(signature[1][1:], "big"), self.e, self.n), expected)
        if shutil.which("openssl"):
            text = subprocess.run(["openssl", "x509", "-inform", "DER", "-noout", "-subject", "-enddate"],
                                  input=self.cert, capture_output=True, check=True).stdout.decode()  # fmt: skip
            self.assertIn("CN=Nulavio Companion", text.replace(" = ", "="))
            self.assertIn("9999", text)

    def test_signed_apk_verifies_with_v2_and_v3_and_names_the_certificate(self):
        result = self.apksigner(apk_sign.sign_apk(self.unsigned, self.cert, self.signer))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Verified using v2 scheme (APK Signature Scheme v2): true", result.stdout)
        self.assertIn("Verified using v3 scheme (APK Signature Scheme v3): true", result.stdout)
        self.assertIn(f"certificate SHA-256 digest: {hashlib.sha256(self.cert).hexdigest()}", result.stdout)

    def test_only_the_signing_block_is_added(self):
        # F-Droid's apksigcopier copies a developer's signature onto its own build of the same
        # source: that works when the signed APK is the unsigned one plus the block.
        signed = apk_sign.sign_apk(self.unsigned, self.cert, self.signer)
        cd_offset, _ = apk_sign.zip_layout(self.unsigned)
        self.assertEqual(signed[:cd_offset], self.unsigned[:cd_offset])
        self.assertEqual(signed[-len(self.unsigned) + cd_offset : -22], self.unsigned[cd_offset:-22])
        with zipfile.ZipFile(self.tmp / "unsigned.apk") as before, zipfile.ZipFile(io.BytesIO(signed)) as after:
            self.assertEqual([i.filename for i in before.infolist()], [i.filename for i in after.infolist()])
            self.assertEqual(after.read("assets/data.bin"), before.read("assets/data.bin"))

    def test_a_changed_byte_anywhere_fails_verification(self):
        signed = apk_sign.sign_apk(self.unsigned, self.cert, self.signer)
        cd_offset, _ = apk_sign.zip_layout(self.unsigned)
        block = len(signed) - len(self.unsigned)
        for where, offset in (("entries", 1_200_000), ("central directory", cd_offset + block + 10),
                              ("v2 signed data", cd_offset + 60)):  # fmt: skip
            with self.subTest(where):
                broken = bytearray(signed)
                broken[offset] ^= 0x01
                result = self.apksigner(bytes(broken), "broken.apk")
                self.assertNotEqual(result.returncode, 0, f"{where}: {result.stdout}")

    def test_signing_is_deterministic(self):
        first = apk_sign.sign_apk(self.unsigned, self.cert, self.signer)
        self.assertEqual(first, apk_sign.sign_apk(self.unsigned, self.cert, self.signer))
        self.assertEqual(self.cert, apk_sign.certificate(self.n, self.e, self.signer, NOT_BEFORE))

    def test_refuses_an_apk_that_is_already_signed_or_not_a_zip(self):
        signed = apk_sign.sign_apk(self.unsigned, self.cert, self.signer)
        with self.assertRaisesRegex(apk_sign.SignError, "already signed"):
            apk_sign.sign_apk(signed, self.cert, self.signer)
        with self.assertRaisesRegex(apk_sign.SignError, "not a ZIP"):
            apk_sign.sign_apk(b"not an apk" * 10, self.cert, self.signer)

    def test_a_signature_at_or_above_the_modulus_is_refused(self):
        # RFC 8017, 5.2.2: pow() alone would reduce s + n to s and accept what apksigner refuses.
        size = (self.n.bit_length() + 7) // 8
        for attempt in range(256):
            digest = hashlib.sha256(attempt.to_bytes(2, "big")).digest()
            raised = int.from_bytes(self.signer(digest), "big") + self.n
            if raised < 1 << (8 * size):
                break
        else:
            self.skipTest("no signature of this key leaves room for s + n in its length")
        checked = apk_sign.checked_signer(self.n, self.e, lambda _digest: raised.to_bytes(size, "big"))
        with self.assertRaisesRegex(apk_sign.SignError, "does not verify"):
            checked(digest)

    def test_a_zip_that_could_be_read_two_ways_is_refused(self):
        apk = self.unsigned
        _, eocd = apk_sign.zip_layout(apk)

        def edited(offset: int, fmt: str, *values: int) -> bytes:
            data = bytearray(apk)
            struct.pack_into(fmt, data, offset, *values)
            return bytes(data)

        # The end record's comment holds a second end record that also fits the file's end.
        fake = struct.pack("<4sHHHHIIH", b"PK\x05\x06", 0, 0, 0, 0, 0, len(apk), 0)
        cases = {
            "an end record inside the comment": (apk[:-2] + struct.pack("<H", len(fake)) + fake, "more than one end"),
            "ZIP64 entry counts": (edited(eocd + 8, "<HH", 0xFFFF, 0xFFFF), "ZIP64"),
            "a ZIP64 size": (edited(eocd + 12, "<I", 0xFFFFFFFF), "ZIP64"),
            "a ZIP64 offset": (edited(eocd + 16, "<I", 0xFFFFFFFF), "ZIP64"),
            "a ZIP64 locator": (apk[:eocd] + struct.pack("<4sIQI", b"PK\x06\x07", 0, 0, 1) + apk[eocd:], "ZIP64|does not end"),
            "fewer entries than records": (edited(eocd + 8, "<HH", 2, 2), "do not fill exactly"),
            "more entries than records": (edited(eocd + 8, "<HH", 4, 4), "fewer records"),
            "a size that leaves a gap": (
                edited(eocd + 12, "<I", struct.unpack_from("<I", apk, eocd + 12)[0] - 1),
                "does not end",
            ),
        }
        for name, (data, message) in cases.items():
            with self.subTest(name), self.assertRaisesRegex(apk_sign.SignError, message):
                apk_sign.sign_apk(data, self.cert, self.signer)

    def test_the_v2_signer_says_v3_is_there_so_v3_cannot_be_stripped(self):
        # The stripping-protection attribute: an APK whose v3 block was removed fails verification
        # even for a device that reads v2 only, instead of passing as v2-signed.
        signed = apk_sign.sign_apk(self.unsigned, self.cert, self.signer)
        cd_offset, eocd = apk_sign.zip_layout(self.unsigned)
        block = signed[cd_offset : cd_offset + len(signed) - len(self.unsigned)]
        pairs, position = [], 8
        while position < len(block) - 24:
            length, block_id = struct.unpack_from("<QI", block, position)
            pairs.append((block_id, block[position + 12 : position + 8 + length]))
            position += 8 + length
        self.assertEqual([block_id for block_id, _ in pairs], [apk_sign.V2_BLOCK_ID, apk_sign.V3_BLOCK_ID])
        only_v2 = b"".join(struct.pack("<QI", len(v) + 4, i) + v for i, v in pairs if i == apk_sign.V2_BLOCK_ID)
        size = struct.pack("<Q", len(only_v2) + 24)
        stripped_block = size + only_v2 + size + apk_sign.MAGIC
        end = bytearray(self.unsigned[eocd:])
        struct.pack_into("<I", end, 16, cd_offset + len(stripped_block))
        stripped = self.unsigned[:cd_offset] + stripped_block + self.unsigned[cd_offset:eocd] + bytes(end)
        result = self.apksigner(stripped, "stripped.apk")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("v3", (result.stdout + result.stderr).lower())

    def test_a_signer_with_another_key_is_refused_before_anything_is_written(self):
        n, _, d = rsa_key()
        with self.assertRaisesRegex(apk_sign.SignError, "does not verify"):
            apk_sign.sign_apk(self.unsigned, self.cert, local_signer(n, d))


@unittest.skipUnless(shutil.which("openssl"), "needs openssl")
class ApkSignCommandLineTest(unittest.TestCase):
    """The commands the release runs, with a stand-in `aws` holding the key the way KMS does."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nulavio-apk-cli-"))
        (cls.tmp / "bin").mkdir()
        fake = cls.tmp / "bin" / "aws"
        fake.write_text(FAKE_AWS)
        fake.chmod(0o755)
        cls.n, cls.e, cls.d = rsa_key()
        cls.key = cls.tmp / "kms.json"
        spki = apk_sign.rsa_spki(cls.n, cls.e)
        cls.key.write_text(json.dumps({"n": cls.n, "d": cls.d, "spki": base64.b64encode(spki).decode()}))
        unsigned_apk(cls.tmp / "unsigned.apk")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_script(self, *args: str, key: Path | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ, PATH=f"{self.tmp / 'bin'}:{os.environ['PATH']}", FAKE_KMS_KEY=str(key or self.key),
                   FAKE_KMS_LOG=str(self.tmp / "kms.log"))  # fmt: skip
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, env=env, check=False)

    def test_certificate_then_sign_through_kms(self):
        cert = self.tmp / "companion.der"
        made = self.run_script("certificate", "--kms-key-id", "alias/test", "--not-before", "2026-11-14", "-o", str(cert))
        self.assertEqual(made.returncode, 0, made.stderr)
        fingerprint = hashlib.sha256(cert.read_bytes()).hexdigest()
        self.assertEqual(made.stdout.strip(), fingerprint)
        self.assertEqual(self.run_script("fingerprint", str(cert)).stdout.strip(), fingerprint)
        out = self.tmp / "signed.apk"
        signed = self.run_script("sign", "--certificate", str(cert), "--kms-key-id", "alias/test", "-o", str(out),
                                 str(self.tmp / "unsigned.apk"))  # fmt: skip
        self.assertEqual(signed.returncode, 0, signed.stderr)
        calls = [json.loads(line) for line in (self.tmp / "kms.log").read_text().splitlines()]
        self.assertTrue(all("RSASSA_PKCS1_V1_5_SHA_256" in call and "DIGEST" in call for call in calls if call[1] == "sign"))
        if APKSIGNER:
            result = subprocess.run(
                [APKSIGNER, "verify", "--print-certs", "--min-sdk-version", "24", str(out)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(fingerprint, result.stdout)

    def test_a_kms_key_that_is_not_the_certificates_signs_nothing(self):
        other = self.tmp / "other.json"
        n, e, d = rsa_key()
        other.write_text(json.dumps({"n": n, "d": d, "spki": base64.b64encode(apk_sign.rsa_spki(n, e)).decode()}))
        cert = self.tmp / "mine.der"
        self.assertEqual(
            self.run_script("certificate", "--kms-key-id", "k", "--not-before", "2026-11-14", "-o", str(cert)).returncode, 0
        )
        out = self.tmp / "never.apk"
        result = self.run_script("sign", "--certificate", str(cert), "--kms-key-id", "other", "-o", str(out),
                                 str(self.tmp / "unsigned.apk"), key=other)  # fmt: skip
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not the key of certificate", result.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
