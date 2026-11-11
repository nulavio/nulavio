#!/usr/bin/env python3
"""Import the release key into AWS KMS (run once, by the maintainer, on their machine).

    AWS_PROFILE=lombello-dev AWS_REGION=us-east-1 \\
        python3 -I scripts/release/kms_import_key.py --gnupghome ~/.local/share/nulavio-release-key \\
            --fingerprint 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1 --kms-key-id alias/nulavio-release

The KMS key must already exist, empty: RSA_4096, SIGN_VERIFY, origin EXTERNAL
(docs/architecture/build.md, "Signing in CI through AWS KMS").

What it does:

1. Asks for the key's passphrase on the terminal and has gpg export the secret key
   with it (the passphrase goes to gpg on standard input). The key's home is only
   read; its passphrase does not change.
2. Decrypts the exported key's OpenPGP protection (S2K, AES-CFB, SHA-1 check), checks
   the RSA numbers against the public key, and builds the PKCS#8 key material KMS
   expects.
3. Wraps it for KMS (RSA_AES_KEY_WRAP_SHA_256 with a fresh wrapping key and import
   token from GetParametersForImport) and imports it with no expiry.
4. Checks that KMS now holds the release key: same modulus, and a signature made by
   KMS verifies with the public key.

AES (the key's protection and the KMS wrap) comes from the `cryptography` package
(python3-cryptography on Fedora), because the standard library has none. The key and
its passphrase never reach a command line, a log or the disk; the wrapped material
and the import token are written to a private directory in memory and deleted.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpgp_sign as ops

FIELDS = ("n", "e", "d", "p", "q")


class KeyImportError(Exception):
    """The key cannot be imported safely."""


CIPHER_KEY_SIZES = {7: 16, 8: 24, 9: 32}  # AES-128, AES-192, AES-256 (RFC 9580, 9.3)
S2K_HASHES = {2: "sha1", 8: "sha256", 9: "sha384", 10: "sha512", 11: "sha224"}


def _aes_cfb_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES in CFB mode, which OpenPGP uses to protect version 4 secret keys."""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    except ModuleNotFoundError as error:
        raise KeyImportError("needs python3-cryptography (sudo dnf install python3-cryptography)") from error
    try:  # cryptography 44 and later keep CFB with the legacy modes
        from cryptography.hazmat.decrepit.ciphers.modes import CFB
    except ModuleNotFoundError:
        from cryptography.hazmat.primitives.ciphers.modes import CFB
    decryptor = Cipher(algorithms.AES(key), CFB(iv)).decryptor()
    return decryptor.update(data) + decryptor.finalize()


def s2k_key(passphrase: bytes, spec: bytes, size: int) -> tuple[bytes, int]:
    """(key, bytes of `spec` used): OpenPGP string-to-key, simple, salted or iterated and salted."""
    kind = spec[0]
    if kind not in (0, 1, 3) or spec[1] not in S2K_HASHES:
        raise KeyImportError(f"unsupported S2K (type {kind}, hash {spec[1]})")
    salt = spec[2:10] if kind in (1, 3) else b""
    used = {0: 2, 1: 10, 3: 11}[kind]
    data = salt + passphrase
    count = len(data)
    if kind == 3:
        c = spec[10]
        count = max(count, (16 + (c & 15)) << ((c >> 4) + 6))
    out = b""
    preload = 0
    while len(out) < size:
        h = hashlib.new(S2K_HASHES[spec[1]], b"\0" * preload)
        full, rest = divmod(count, len(data))
        for _ in range(full):
            h.update(data)
        h.update(data[:rest])
        out += h.digest()
        preload += 1
    return out[:size], used


def secret_numbers(export: bytes, passphrase: bytes) -> dict[str, int]:
    """n, e, d, p, q of the primary key in `gpg --export-secret-keys` output (version 4, RSA)."""
    for tag, body in ops.packets(export):
        if tag != 5:
            continue
        if body[0] != 4 or body[5] != ops.RSA:
            raise KeyImportError("only version 4 RSA keys are supported")
        n, offset = ops.read_mpi(body, 6)
        e, offset = ops.read_mpi(body, offset)
        usage = body[offset]
        offset += 1
        if usage == 0:
            secret, check = body[offset:-2], body[-2:]
            if sum(secret) % 65536 != int.from_bytes(check, "big"):
                raise KeyImportError("damaged secret key (checksum)")
        elif usage == 254:
            cipher = body[offset]
            if cipher not in CIPHER_KEY_SIZES:
                raise KeyImportError(f"unsupported cipher {cipher} protecting the key")
            key, used = s2k_key(passphrase, body[offset + 1 :], CIPHER_KEY_SIZES[cipher])
            offset += 1 + used
            iv, encrypted = body[offset : offset + 16], body[offset + 16 :]
            plain = _aes_cfb_decrypt(key, iv, encrypted)
            secret, digest = plain[:-20], plain[-20:]
            # SHA-1 is the format's own check of the decrypted numbers (S2K usage 254); it only tells a
            # wrong passphrase. The numbers are then checked against the public key (p * q = n, d, n, e).
            if hashlib.sha1(secret, usedforsecurity=False).digest() != digest:
                raise KeyImportError("wrong passphrase")
        else:
            raise KeyImportError(f"unsupported key protection (S2K usage {usage})")
        d, offset = ops.read_mpi(secret, 0)
        p, offset = ops.read_mpi(secret, offset)
        q, _ = ops.read_mpi(secret, offset)
        if p * q != n:
            raise KeyImportError("p * q is not n")
        if pow(pow(2, e, n), d, n) != 2:
            raise KeyImportError("d does not invert e")
        return {"n": n, "e": e, "d": d, "p": p, "q": q}
    raise KeyImportError("no secret key packet in the export")


def _der(tag: int, body: bytes) -> bytes:
    n = len(body)
    if n < 128:
        return bytes([tag, n]) + body
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(raw)]) + raw + body


def _der_int(value: int) -> bytes:
    return _der(0x02, value.to_bytes(value.bit_length() // 8 + 1, "big"))


def pkcs8(numbers: dict[str, int]) -> bytes:
    """PKCS#8 PrivateKeyInfo (DER) holding the RSAPrivateKey (RFC 5208, RFC 8017 A.1.2)."""
    n, e, d, p, q = (numbers[k] for k in FIELDS[:5])
    rsa_private_key = _der(
        0x30,
        b"".join(_der_int(v) for v in (0, n, e, d, p, q, d % (p - 1), d % (q - 1), pow(q, -1, p))),
    )
    rsa_encryption = _der(0x30, bytes.fromhex("06092a864886f70d0101010500"))
    return _der(0x30, _der_int(0) + rsa_encryption + _der(0x04, rsa_private_key))


def wrap_for_kms(material: bytes, wrapping_public_key_der: bytes) -> bytes:
    """RSA_AES_KEY_WRAP_SHA_256: OAEP-SHA256(aes_key) || AES-KWP(aes_key, material)."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.keywrap import aes_key_wrap_with_padding
    except ModuleNotFoundError as error:
        raise KeyImportError("needs python3-cryptography (sudo dnf install python3-cryptography)") from error
    aes_key = os.urandom(32)
    wrapping_key = serialization.load_der_public_key(wrapping_public_key_der)
    oaep = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    return wrapping_key.encrypt(aes_key, oaep) + aes_key_wrap_with_padding(aes_key, material)


def _run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), check=True, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gnupghome", required=True, type=Path, help="GNUPGHOME that holds the release key")
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--kms-key-id", required=True, help="the empty KMS key (ID, ARN or alias)")
    args = parser.parse_args(argv)

    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime or not Path(runtime).is_dir():
        print("kms_import_key: XDG_RUNTIME_DIR (an in-memory directory) is needed", file=sys.stderr)
        return 1
    work = Path(tempfile.mkdtemp(prefix="nulavio-kms-import-", dir=runtime))
    home = str(args.gnupghome)
    try:
        cert = _run("gpg", "--homedir", home, "--batch", "--armor", "--export", args.fingerprint, capture_output=True).stdout
        key = ops.primary_key(cert)
        if key.hex != args.fingerprint.replace(" ", "").upper():
            raise KeyImportError(f"{args.fingerprint} is not the primary key of the exported certificate")
        meta = json.loads(
            _run(
                "aws", "kms", "describe-key", "--key-id", args.kms_key_id, "--output", "json", capture_output=True, text=True
            ).stdout
        )["KeyMetadata"]
        if (meta.get("Origin"), meta.get("KeySpec"), meta.get("KeyUsage")) != ("EXTERNAL", "RSA_4096", "SIGN_VERIFY"):
            raise KeyImportError("the KMS key must be RSA_4096, SIGN_VERIFY, with origin EXTERNAL")
        if meta.get("KeyState") != "PendingImport":
            raise KeyImportError("the KMS key already has key material (KeyState is not PendingImport)")
        key_arn = meta["Arn"]  # GetParametersForImport and ImportKeyMaterial take no alias

        passphrase = getpass.getpass(f"Passphrase of the release key {key.hex[-16:]}: ").encode()
        export = _run(
            "gpg", "--homedir", home, "--batch", "--pinentry-mode", "loopback", "--passphrase-fd", "0",
            "--export-secret-keys", key.hex, input=passphrase, capture_output=True,
        ).stdout  # fmt: skip
        numbers = secret_numbers(export, passphrase)
        if (numbers["n"], numbers["e"]) != (key.modulus, key.exponent):
            raise KeyImportError("the private key does not match the public key")
        material = pkcs8(numbers)

        params = _run(
            "aws", "kms", "get-parameters-for-import", "--key-id", key_arn,
            "--wrapping-algorithm", "RSA_AES_KEY_WRAP_SHA_256", "--wrapping-key-spec", "RSA_4096",
            "--query", "[PublicKey, ImportToken]", "--output", "text", capture_output=True, text=True,
        ).stdout.split()  # fmt: skip
        wrapped = work / "material.bin"
        token = work / "token.bin"
        wrapped.write_bytes(wrap_for_kms(material, base64.b64decode(params[0])))
        token.write_bytes(base64.b64decode(params[1]))
        _run(
            "aws", "kms", "import-key-material", "--key-id", key_arn,
            "--encrypted-key-material", f"fileb://{wrapped}", "--import-token", f"fileb://{token}",
            "--expiration-model", "KEY_MATERIAL_DOES_NOT_EXPIRE", capture_output=True,
        )  # fmt: skip

        ops.signature_packet(b"nulavio kms import check\n", key, ops.kms_signer(args.kms_key_id, key))
        print(f"KMS key {args.kms_key_id} now signs as {key.hex}.")
    except (KeyImportError, ops.SignError, subprocess.CalledProcessError, OSError, StopIteration) as error:
        detail = getattr(error, "stderr", None)
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", "replace")
        if isinstance(error, subprocess.CalledProcessError):
            error = f"{error.cmd[0]} {error.cmd[1]} {error.cmd[2]} failed (exit {error.returncode})"
        print(f"kms_import_key: {error}{(': ' + detail.strip()) if detail else ''}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
