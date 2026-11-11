#!/usr/bin/env python3
"""Detached OpenPGP signatures made by a key held in AWS KMS.

The release key (an RSA OpenPGP key) is imported into AWS KMS, where it cannot be
exported. This script builds the OpenPGP signature packet itself and asks KMS only
for the RSA operation over its SHA-256 digest, so CI can sign packages without ever
holding the key. The result is what `gpg --detach-sign` makes: a version 4 signature
of a binary document, SHA-256, verifiable with gpg, rpm and dnf against the key users
already have.

    openpgp_sign.py --public-key nulavio-packages.asc --kms-key-id <arn> [--armor] -o FILE.sig FILE

As rpmsign's signer (it calls the command with the output and input files):

    rpmsign --define "_openpgp_sign kms" --define "_openpgp_sign_id <fingerprint>" \\
        --define "__kms_sign_cmd() /usr/bin/python3 -I .../openpgp_sign.py --public-key ... --kms-key-id ... \\
                  -o %{shescape:%{2}} -- %{shescape:%{1}}" --addsign *.rpm

rpm 6 passes the data on standard input ("-"); rpm runs the command without a PATH
search, so python3 needs its full path.

Before signing, the RSA modulus that KMS reports is compared with the one in
--public-key, so a wrong key ID fails instead of producing signatures nobody can
verify. The `aws` command (AWS CLI v2) must be on PATH with credentials for KMS
Sign and GetPublicKey on that key; nothing else outside the standard library is used.

Format: RFC 9580 (and RFC 4880) version 4 signatures; RSA PKCS#1 v1.5 with SHA-256.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

PUBLIC_KEY_TAG = 6
PUBLIC_SUBKEY_TAG = 14
SIGNATURE_TAG = 2
RSA = 1
SHA256 = 8
BINARY_DOCUMENT = 0x00
SUBPACKET_CREATION_TIME = 2
SUBPACKET_ISSUER_KEY_ID = 16
SUBPACKET_ISSUER_FINGERPRINT = 33

# A signer takes the SHA-256 digest of the signed data and returns the RSA signature
# (PKCS#1 v1.5, DigestInfo for SHA-256), as big-endian bytes.
Signer = Callable[[bytes], bytes]


class SignError(Exception):
    """The key, the input or the signing service is not usable."""


# --- OpenPGP encoding --------------------------------------------------------


def dearmor(data: bytes) -> bytes:
    """Binary OpenPGP data from ASCII armor (binary input is returned as it is)."""
    text = data.decode("ascii", "replace")
    if "-----BEGIN PGP" not in text:
        return data
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("-----BEGIN PGP"))
    body: list[str] = []
    in_headers = True
    for line in lines[start + 1 :]:
        if line.startswith("-----END PGP"):
            break
        if in_headers:
            if not line.strip():
                in_headers = False
            elif ":" not in line:  # armor without headers or blank line
                in_headers = False
                body.append(line)
            continue
        if line.startswith("="):  # CRC-24 checksum
            continue
        body.append(line.strip())
    return base64.b64decode("".join(body))


def crc24(data: bytes) -> int:
    crc = 0xB704CE
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def armor(data: bytes, kind: str = "SIGNATURE") -> bytes:
    encoded = base64.b64encode(data).decode("ascii")
    lines = [encoded[i : i + 64] for i in range(0, len(encoded), 64)]
    checksum = base64.b64encode(crc24(data).to_bytes(3, "big")).decode("ascii")
    return (f"-----BEGIN PGP {kind}-----\n\n" + "\n".join(lines) + f"\n={checksum}\n-----END PGP {kind}-----\n").encode("ascii")


def packets(data: bytes) -> Iterator[tuple[int, bytes]]:
    """(tag, body) for each packet; old and new formats, no partial lengths."""
    i = 0
    while i < len(data):
        header = data[i]
        if not header & 0x80:
            raise SignError("not OpenPGP data")
        if header & 0x40:  # new format
            tag = header & 0x3F
            first = data[i + 1]
            if first < 192:
                length, i = first, i + 2
            elif first < 224:
                length, i = ((first - 192) << 8) + data[i + 2] + 192, i + 3
            elif first == 255:
                length, i = int.from_bytes(data[i + 2 : i + 6], "big"), i + 6
            else:
                raise SignError("partial body lengths are not supported")
        else:  # old format
            tag = (header >> 2) & 0x0F
            kind = header & 0x03
            if kind == 3:
                raise SignError("indeterminate packet lengths are not supported")
            size = 1 << kind
            length, i = int.from_bytes(data[i + 1 : i + 1 + size], "big"), i + 1 + size
        if i + length > len(data):
            raise SignError("truncated OpenPGP packet")
        yield tag, data[i : i + length]
        i += length


def new_packet(tag: int, body: bytes) -> bytes:
    n = len(body)
    if n < 192:
        length = bytes([n])
    elif n < 8384:
        n -= 192
        length = bytes([(n >> 8) + 192, n & 0xFF])
    else:
        length = b"\xff" + n.to_bytes(4, "big")
    return bytes([0xC0 | tag]) + length + body


def read_mpi(data: bytes, offset: int) -> tuple[int, int]:
    bits = int.from_bytes(data[offset : offset + 2], "big")
    size = (bits + 7) // 8
    end = offset + 2 + size
    if end > len(data):
        raise SignError("truncated MPI")
    return int.from_bytes(data[offset + 2 : end], "big"), end


def mpi(value: int) -> bytes:
    raw = value.to_bytes(max(1, (value.bit_length() + 7) // 8), "big")
    return value.bit_length().to_bytes(2, "big") + raw


def subpacket(kind: int, body: bytes) -> bytes:
    """A signature subpacket; its length counts the type octet (RFC 9580, 5.2.3.7)."""
    n = len(body) + 1
    if n < 192:
        length = bytes([n])
    elif n < 8384:
        length = bytes([((n - 192) >> 8) + 192, (n - 192) & 0xFF])
    else:
        length = b"\xff" + n.to_bytes(4, "big")
    return length + bytes([kind]) + body


# --- the release key ---------------------------------------------------------


@dataclass(frozen=True)
class PublicKey:
    fingerprint: bytes  # 20 bytes, version 4
    modulus: int
    exponent: int

    @property
    def key_id(self) -> bytes:
        return self.fingerprint[-8:]

    @property
    def hex(self) -> str:
        return self.fingerprint.hex().upper()


def primary_key(data: bytes) -> PublicKey:
    """The primary key of an OpenPGP certificate (armored or binary); version 4 RSA only."""
    for tag, body in packets(dearmor(data)):
        if tag != PUBLIC_KEY_TAG:
            continue
        if body[0] != 4:
            raise SignError(f"only version 4 keys are supported, not version {body[0]}")
        if body[5] != RSA:
            raise SignError("the release key must be an RSA key (algorithm 1)")
        n, offset = read_mpi(body, 6)
        e, _ = read_mpi(body, offset)
        fingerprint = hashlib.sha1(b"\x99" + len(body).to_bytes(2, "big") + body, usedforsecurity=False).digest()
        return PublicKey(fingerprint, n, e)
    raise SignError("no public key packet in the certificate")


# --- signatures --------------------------------------------------------------


def signature_packet(data: bytes, key: PublicKey, signer: Signer, created: int | None = None) -> bytes:
    """A detached version 4 signature packet over `data` (binary document, SHA-256)."""
    created = int(time.time()) if created is None else created
    hashed_subpackets = subpacket(SUBPACKET_CREATION_TIME, created.to_bytes(4, "big")) + subpacket(
        SUBPACKET_ISSUER_FINGERPRINT, b"\x04" + key.fingerprint
    )
    hashed_part = bytes([4, BINARY_DOCUMENT, RSA, SHA256]) + len(hashed_subpackets).to_bytes(2, "big") + hashed_subpackets
    trailer = b"\x04\xff" + len(hashed_part).to_bytes(4, "big")
    digest = hashlib.sha256(data + hashed_part + trailer).digest()
    raw = signer(digest)
    size = (key.modulus.bit_length() + 7) // 8
    if len(raw) != size:
        raise SignError(f"the signer returned {len(raw)} bytes, the key needs {size}")
    value = int.from_bytes(raw, "big")
    if pow(value, key.exponent, key.modulus) != int.from_bytes(emsa_pkcs1_v15(digest, size), "big"):
        raise SignError("the signature does not verify with the public key: wrong KMS key?")
    unhashed = subpacket(SUBPACKET_ISSUER_KEY_ID, key.key_id)
    body = hashed_part + len(unhashed).to_bytes(2, "big") + unhashed + digest[:2] + mpi(value)
    return new_packet(SIGNATURE_TAG, body)


SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def emsa_pkcs1_v15(digest: bytes, size: int) -> bytes:
    """EMSA-PKCS1-v1_5 encoding of a SHA-256 digest (RFC 8017, 9.2)."""
    t = SHA256_DIGEST_INFO + digest
    if size < len(t) + 11:
        raise SignError("RSA key too small")
    return b"\x00\x01" + b"\xff" * (size - len(t) - 3) + b"\x00" + t


# --- AWS KMS -----------------------------------------------------------------


def _aws(*args: str) -> dict:
    proc = subprocess.run(["aws", *args, "--output", "json"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SignError(f"aws {args[0]} {args[1]} failed: {proc.stderr.strip()[:400]}")
    return json.loads(proc.stdout)


def der_rsa_public_key(spki: bytes) -> tuple[int, int]:
    """(n, e) from a DER SubjectPublicKeyInfo holding an RSA key."""

    def read(data: bytes, offset: int) -> tuple[int, bytes, int]:
        tag, length = data[offset], data[offset + 1]
        offset += 2
        if length & 0x80:
            count = length & 0x7F
            length = int.from_bytes(data[offset : offset + count], "big")
            offset += count
        return tag, data[offset : offset + length], offset + length

    tag, spki_body, _ = read(spki, 0)
    if tag != 0x30:
        raise SignError("KMS public key is not a DER SEQUENCE")
    _, _, offset = read(spki_body, 0)  # AlgorithmIdentifier
    tag, bits, _ = read(spki_body, offset)
    if tag != 0x03 or bits[0] != 0:
        raise SignError("KMS public key has no BIT STRING")
    tag, rsa_key, _ = read(bits[1:], 0)
    n_tag, n, offset = read(rsa_key, 0)
    e_tag, e, _ = read(rsa_key, offset)
    if (tag, n_tag, e_tag) != (0x30, 0x02, 0x02):
        raise SignError("KMS public key is not an RSA key")
    return int.from_bytes(n, "big"), int.from_bytes(e, "big")


def kms_signer(key_id: str, key: PublicKey) -> Signer:
    """A signer backed by KMS Sign; checks first that the KMS key is `key`."""
    info = _aws("kms", "get-public-key", "--key-id", key_id)
    if info.get("KeyUsage") != "SIGN_VERIFY" or "RSASSA_PKCS1_V1_5_SHA_256" not in info.get("SigningAlgorithms", []):
        raise SignError("the KMS key is not an RSA signing key with RSASSA_PKCS1_V1_5_SHA_256")
    if der_rsa_public_key(base64.b64decode(info["PublicKey"])) != (key.modulus, key.exponent):
        raise SignError(f"the KMS key {key_id} is not the release key {key.hex}")

    def sign(digest: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="nulavio-kms-") as tmp:
            message = Path(tmp) / "digest"
            message.write_bytes(digest)
            reply = _aws(
                "kms", "sign", "--key-id", key_id, "--message", f"fileb://{message}",
                "--message-type", "DIGEST", "--signing-algorithm", "RSASSA_PKCS1_V1_5_SHA_256",
            )  # fmt: skip
        return base64.b64decode(reply["Signature"])

    return sign


# --- command line -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--public-key", required=True, type=Path, help="the release key's certificate (armored or binary)")
    parser.add_argument("--kms-key-id", required=True, help="KMS key ID, ARN or alias holding the same key")
    parser.add_argument("--armor", "-a", action="store_true", help="ASCII-armored output, like gpg --armor")
    parser.add_argument("--output", "-o", required=True, help="signature file, or - for standard output")
    parser.add_argument("input", help="file to sign, or - for standard input (rpm 6 passes the header this way)")
    args = parser.parse_args(argv)
    try:
        key = primary_key(args.public_key.read_bytes())
        data = sys.stdin.buffer.read() if args.input == "-" else Path(args.input).read_bytes()
        packet = signature_packet(data, key, kms_signer(args.kms_key_id, key))
        out = armor(packet) if args.armor else packet
        if args.output == "-":
            sys.stdout.buffer.write(out)
            sys.stdout.buffer.flush()
        else:
            target = Path(args.output)
            tmp = target.with_name(f".{target.name}.{os.getpid()}")
            tmp.write_bytes(out)
            tmp.replace(target)
    except (OSError, SignError) as error:
        print(f"openpgp_sign: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
