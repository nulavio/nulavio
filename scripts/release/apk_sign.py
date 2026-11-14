#!/usr/bin/env python3
"""Sign the Companion's APK with a key held in AWS KMS (APK Signature Scheme v2 and v3).

The Companion's signing key (RSA, its own key, not the package key) lives in AWS KMS,
where it cannot be exported. This script builds the APK Signing Block itself and asks
KMS only for the RSA operation over SHA-256 digests, the way openpgp_sign.py does for
the packages. What it writes is what `apksigner sign` writes for a key without
rotation: a v2 and a v3 signer, RSASSA-PKCS1-v1_5 with SHA-256 over the APK's content
in 1 MiB chunks, and no v1 (JAR) signature, which the app does not need (minSdk 30).
`apksigner verify` is the check; scripts/release/test_apk_signing.sh runs it in CI.

Once, by the maintainer, after the key exists: the key's self-signed certificate,
which is what Android compares on every update and what people check by its SHA-256:

    apk_sign.py certificate --kms-key-id <arn> --not-before 2026-11-14 -o nulavio-companion.der

Each release (the `publish` job of release.yml):

    apk_sign.py sign --certificate nulavio-companion.der --kms-key-id <arn> \\
        -o nulavio-companion-<version>.apk app-release-unsigned.apk

    apk_sign.py fingerprint nulavio-companion.der     # SHA-256 of the certificate

Before signing, the RSA key KMS reports is compared with the certificate's, so a wrong
key ID fails instead of producing an APK no installed copy accepts, and every signature
is checked against the certificate before anything is written. Signing is
deterministic: the same unsigned APK and certificate give the same bytes, so a second
build can be compared after signing as well as before. The `aws` command (AWS CLI v2)
must be on PATH with credentials for KMS Sign and GetPublicKey on that key; nothing
else outside the standard library is used.

Format: https://source.android.com/docs/security/features/apksigning/v2 and .../v3;
X.509 (RFC 5280) for the certificate.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import os
import struct
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpgp_sign as ops

SignError = ops.SignError
# A signer takes the SHA-256 digest of the signed data and returns the RSA signature
# (PKCS#1 v1.5, DigestInfo for SHA-256), as big-endian bytes.
Signer = Callable[[bytes], bytes]

RSA_PKCS1_SHA256 = 0x0103  # RSASSA-PKCS1-v1_5 with SHA2-256, content digested by chunked SHA2-256
V2_BLOCK_ID = 0x7109871A
V3_BLOCK_ID = 0xF05368C0
STRIPPING_PROTECTION = 0xBEEFF00D  # v2 attribute naming the newer scheme also present, so v3 cannot be stripped
V3_MIN_SDK = 28  # Android 9, the first to read v3; older versions use the v2 signer
V3_MAX_SDK = 0x7FFFFFFF
MAGIC = b"APK Sig Block 42"
CHUNK = 1024 * 1024
EOCD_SIGNATURE = b"PK\x05\x06"
EOCD_SIZE = 22

SUBJECT = (("2.5.4.3", "Nulavio Companion"), ("2.5.4.10", "Nulavio"))
SHA256_WITH_RSA = "1.2.840.113549.1.1.11"
SUBJECT_KEY_IDENTIFIER = "2.5.29.14"


# --- DER ---------------------------------------------------------------------


def der(tag: int, body: bytes) -> bytes:
    n = len(body)
    if n < 128:
        return bytes([tag, n]) + body
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(raw)]) + raw + body


def der_int(value: int) -> bytes:
    return der(0x02, value.to_bytes(value.bit_length() // 8 + 1, "big"))  # leading zero keeps it positive


def der_oid(dotted: str) -> bytes:
    first, second, *rest = (int(part) for part in dotted.split("."))
    body = bytearray([first * 40 + second])
    for value in rest:
        chunk = [value & 0x7F]
        while value := value >> 7:
            chunk.append(0x80 | (value & 0x7F))
        body += bytes(reversed(chunk))
    return der(0x06, bytes(body))


def der_read(data: bytes, offset: int = 0) -> tuple[int, bytes, int, int]:
    """(tag, body, start of the element, end of the element) of the element at `offset`."""
    if offset + 2 > len(data):
        raise SignError("truncated DER")
    tag, length = data[offset], data[offset + 1]
    start, offset = offset, offset + 2
    if length & 0x80:
        count = length & 0x7F
        if not 0 < count <= 4 or offset + count > len(data):
            raise SignError("bad DER length")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    if offset + length > len(data):
        raise SignError("truncated DER")
    return tag, data[offset : offset + length], start, offset + length


def der_children(body: bytes) -> list[tuple[int, bytes, bytes]]:
    """(tag, body, whole element) for each element of a constructed value."""
    children, offset = [], 0
    while offset < len(body):
        tag, inner, start, end = der_read(body, offset)
        children.append((tag, inner, body[start:end]))
        offset = end
    return children


def algorithm(oid: str) -> bytes:
    return der(0x30, der_oid(oid) + b"\x05\x00")


def name(attributes: tuple[tuple[str, str], ...]) -> bytes:
    return der(0x30, b"".join(der(0x31, der(0x30, der_oid(oid) + der(0x0C, value.encode()))) for oid, value in attributes))


def der_time(moment: datetime.datetime) -> bytes:
    if moment.year < 2050:
        return der(0x17, moment.strftime("%y%m%d%H%M%SZ").encode())  # UTCTime (RFC 5280, 4.1.2.5)
    return der(0x18, moment.strftime("%Y%m%d%H%M%SZ").encode())


def rsa_spki(modulus: int, exponent: int) -> bytes:
    rsa = der(0x30, der_oid("1.2.840.113549.1.1.1") + b"\x05\x00")
    return der(0x30, rsa + der(0x03, b"\x00" + der(0x30, der_int(modulus) + der_int(exponent))))


# --- the certificate ---------------------------------------------------------


def certificate(modulus: int, exponent: int, signer: Signer, not_before: datetime.date) -> bytes:
    """The key's self-signed X.509 v3 certificate. Android reads only the key and the bytes of
    the certificate (their SHA-256 is the app's signer identity); it ignores the dates, so the
    certificate does not expire (RFC 5280, 4.1.2.5: 99991231235959Z)."""
    spki = rsa_spki(modulus, exponent)
    key_bits = der_children(der_read(spki)[1])[1][1][1:]
    serial = int.from_bytes(hashlib.sha256(spki).digest()[:16], "big") >> 1 | 1  # positive, stable for one key
    extensions = der(0xA3, der(0x30, der(0x30, der_oid(SUBJECT_KEY_IDENTIFIER) + der(0x04, der(0x04,
        hashlib.sha1(key_bits, usedforsecurity=False).digest())))))  # fmt: skip
    start = datetime.datetime.combine(not_before, datetime.time(), datetime.UTC)
    tbs = der(0x30, der(0xA0, der_int(2)) + der_int(serial) + algorithm(SHA256_WITH_RSA) + name(SUBJECT)
              + der(0x30, der_time(start) + der(0x18, b"99991231235959Z")) + name(SUBJECT) + spki
              + extensions)  # fmt: skip
    signature = checked_signer(modulus, exponent, signer)(hashlib.sha256(tbs).digest())
    return der(0x30, tbs + algorithm(SHA256_WITH_RSA) + der(0x03, b"\x00" + signature))


def certificate_key(cert: bytes) -> tuple[bytes, int, int]:
    """(SubjectPublicKeyInfo, modulus, exponent) of an RSA certificate in DER."""
    tag, body, _, end = der_read(cert)
    if tag != 0x30 or end != len(cert):
        raise SignError("the certificate is not one DER SEQUENCE (PEM is not read; give the .der)")
    tbs = der_children(der_children(body)[0][1])
    fields = tbs[1:] if tbs[0][0] == 0xA0 else tbs  # skip the version
    spki = fields[5][2]
    modulus, exponent = ops.der_rsa_public_key(spki)
    return spki, modulus, exponent


def checked_signer(modulus: int, exponent: int, signer: Signer) -> Signer:
    """`signer`, with each signature checked against the public key before it is used."""
    size = (modulus.bit_length() + 7) // 8

    def sign(digest: bytes) -> bytes:
        raw = signer(digest)
        if len(raw) != size:
            raise SignError(f"the signer returned {len(raw)} bytes, the key needs {size}")
        expected = int.from_bytes(ops.emsa_pkcs1_v15(digest, size), "big")
        if pow(int.from_bytes(raw, "big"), exponent, modulus) != expected:
            raise SignError("the signature does not verify with the certificate's key: wrong KMS key?")
        return raw

    return sign


# --- the APK -----------------------------------------------------------------


def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def prefixed(data: bytes) -> bytes:
    return u32(len(data)) + data


def zip_layout(apk: bytes) -> tuple[int, int]:
    """(offset of the central directory, offset of the end of central directory record)."""
    lowest = max(0, len(apk) - EOCD_SIZE - 0xFFFF)
    for eocd in range(len(apk) - EOCD_SIZE, lowest - 1, -1):
        if apk[eocd : eocd + 4] == EOCD_SIGNATURE and eocd + EOCD_SIZE + struct.unpack_from("<H", apk, eocd + 20)[0] == len(apk):
            break
    else:
        raise SignError("not a ZIP file: no end of central directory record")
    disk, cd_disk, entries_here, entries, cd_size, cd_offset = struct.unpack_from("<HHHHII", apk, eocd + 4)
    if (disk, cd_disk) != (0, 0) or entries_here != entries or 0xFFFFFFFF in (cd_size, cd_offset):
        raise SignError("multi-disk and ZIP64 archives are not APKs this script signs")
    if cd_offset + cd_size != eocd:
        raise SignError("the central directory does not end where the end record starts")
    if cd_offset >= 32 and apk[cd_offset - 16 : cd_offset] == MAGIC:
        raise SignError("the APK is already signed (it has an APK Signing Block); give the unsigned build")
    return cd_offset, eocd


def content_digest(sections: list[bytes]) -> bytes:
    """Chunked SHA-256 of the APK's content: each 1 MiB chunk hashed with 0xa5 and its length,
    then the chunk digests hashed with 0x5a and their count (v2 scheme, "Integrity-protected contents")."""
    chunks = [
        hashlib.sha256(b"\xa5" + u32(len(part)) + part).digest()
        for section in sections
        for part in (section[i : i + CHUNK] for i in range(0, len(section), CHUNK))
    ]
    return hashlib.sha256(b"\x5a" + u32(len(chunks)) + b"".join(chunks)).digest()


def signer_block(signed_data: bytes, between: bytes, spki: bytes, sign: Signer) -> bytes:
    """One signer: its signed data, `between` (v3's SDK range, nothing for v2), its one
    signature over the signed data, and its public key; inside the sequence of signers."""
    signature = sign(hashlib.sha256(signed_data).digest())
    signatures = prefixed(prefixed(u32(RSA_PKCS1_SHA256) + prefixed(signature)))
    return prefixed(prefixed(prefixed(signed_data) + between + signatures + prefixed(spki)))


def signing_block(digest: bytes, cert: bytes, spki: bytes, sign: Signer) -> bytes:
    digests = prefixed(prefixed(u32(RSA_PKCS1_SHA256) + prefixed(digest)))
    certificates = prefixed(prefixed(cert))
    sdk_range = u32(V3_MIN_SDK) + u32(V3_MAX_SDK)
    v2 = signer_block(digests + certificates + prefixed(prefixed(u32(STRIPPING_PROTECTION) + u32(3))), b"", spki, sign)
    v3 = signer_block(digests + certificates + sdk_range + prefixed(b""), sdk_range, spki, sign)
    pairs = b"".join(
        struct.pack("<QI", len(value) + 4, block_id) + value for block_id, value in ((V2_BLOCK_ID, v2), (V3_BLOCK_ID, v3))
    )
    size = struct.pack("<Q", len(pairs) + 8 + len(MAGIC))
    return size + pairs + size + MAGIC


def sign_apk(apk: bytes, cert: bytes, signer: Signer) -> bytes:
    """The APK with an APK Signing Block (v2 and v3) inserted before its central directory."""
    cd_offset, eocd = zip_layout(apk)
    spki, modulus, exponent = certificate_key(cert)
    # The end record is digested as it stands: the block goes where the central directory starts now.
    digest = content_digest([apk[:cd_offset], apk[cd_offset:eocd], apk[eocd:]])
    block = signing_block(digest, cert, spki, checked_signer(modulus, exponent, signer))
    end = bytearray(apk[eocd:])
    struct.pack_into("<I", end, 16, cd_offset + len(block))
    return apk[:cd_offset] + block + apk[cd_offset:eocd] + bytes(end)


# --- command line -------------------------------------------------------------


def write(target: Path, data: bytes) -> None:
    tmp = target.with_name(f".{target.name}.{os.getpid()}")
    tmp.write_bytes(data)
    tmp.replace(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("certificate", help="the KMS key's self-signed certificate (once)")
    make.add_argument("--kms-key-id", required=True, help="KMS key ID, ARN or alias of the Companion's key")
    make.add_argument("--not-before", required=True, type=datetime.date.fromisoformat, help="YYYY-MM-DD")
    make.add_argument("--output", "-o", required=True, type=Path, help="certificate file (DER)")
    sign = commands.add_parser("sign", help="sign an unsigned APK")
    sign.add_argument("--certificate", required=True, type=Path, help="the key's certificate (DER)")
    sign.add_argument("--kms-key-id", required=True, help="KMS key ID, ARN or alias holding the same key")
    sign.add_argument("--output", "-o", required=True, type=Path, help="signed APK")
    sign.add_argument("input", type=Path, help="unsigned APK (Gradle's app-release-unsigned.apk)")
    show = commands.add_parser("fingerprint", help="SHA-256 of a certificate, as apksigner and F-Droid print it")
    show.add_argument("certificate", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "certificate":
            info = ops._aws("kms", "get-public-key", "--key-id", args.kms_key_id)
            modulus, exponent = ops.der_rsa_public_key(base64.b64decode(info["PublicKey"]))
            signer = ops.kms_rsa_signer(args.kms_key_id, modulus, exponent, "the key it reported a moment ago")
            write(args.output, certificate(modulus, exponent, signer, args.not_before))
            print(hashlib.sha256(args.output.read_bytes()).hexdigest())
        elif args.command == "sign":
            cert = args.certificate.read_bytes()
            _, modulus, exponent = certificate_key(cert)
            fingerprint = hashlib.sha256(cert).hexdigest()
            signer = ops.kms_rsa_signer(args.kms_key_id, modulus, exponent, f"the key of certificate {fingerprint}")
            write(args.output, sign_apk(args.input.read_bytes(), cert, signer))
        else:
            print(hashlib.sha256(args.certificate.read_bytes()).hexdigest())
    except (OSError, SignError, KeyError, ValueError) as error:
        print(f"apk_sign: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
