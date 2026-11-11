#!/usr/bin/env python3
"""Import the release key into AWS KMS (run once, by the maintainer, on their machine).

    AWS_PROFILE=lombello-dev AWS_REGION=us-east-1 \\
        python3 -I scripts/release/kms_import_key.py --gnupghome ~/.local/share/nulavio-release-key \\
            --fingerprint 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1 --kms-key-id alias/nulavio-release

The KMS key must already exist, empty: RSA_4096, SIGN_VERIFY, origin EXTERNAL
(docs/architecture/build.md, "Signing in CI through AWS KMS").

What it does:

1. Copies the key's home to a private directory in memory ($XDG_RUNTIME_DIR, tmpfs)
   and runs `gpg --passwd` there: type the current passphrase, then leave the new one
   empty and confirm. Only the copy loses its passphrase; the original is not touched.
2. Reads the RSA numbers from the copy, checks them against the public key, and
   builds the PKCS#8 key material KMS expects.
3. Wraps it for KMS (RSA_AES_KEY_WRAP_SHA_256 with a fresh wrapping key and import
   token from GetParametersForImport) and imports it with no expiry.
4. Checks that KMS now holds the release key: same modulus, and a signature made by
   KMS verifies with the public key.
5. Deletes the copy, whatever happened.

The AES key wrap uses the `cryptography` package (python3-cryptography on Fedora),
because the standard library has no AES; nothing else here leaves it. The key never
reaches a command line, a log or the disk outside the in-memory directory.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpgp_sign as ops

FIELDS = ("n", "e", "d", "p", "q", "u")


class KeyImportError(Exception):
    """The key cannot be imported safely."""


def rsa_numbers(key_file_text: str) -> dict[str, int]:
    """n, e, d, p, q from an unprotected gpg-agent key file (extended format)."""
    if "protected-private-key" in key_file_text or "shadowed-private-key" in key_file_text:
        raise KeyImportError("the key file is still protected (did gpg --passwd set an empty passphrase?)")
    flat = re.sub(r"\s+", "", key_file_text)
    if "(private-key(rsa" not in flat:
        raise KeyImportError("not an RSA private key file")
    numbers = {name: int(value, 16) for name, value in re.findall(r"\((n|e|d|p|q|u)#([0-9A-Fa-f]+)#\)", flat)}
    missing = [name for name in FIELDS[:5] if name not in numbers]
    if missing:
        raise KeyImportError(f"key file lacks {', '.join(missing)}")
    if numbers["p"] * numbers["q"] != numbers["n"]:
        raise KeyImportError("p * q is not n")
    if pow(pow(2, numbers["e"], numbers["n"]), numbers["d"], numbers["n"]) != 2:
        raise KeyImportError("d does not invert e")
    return numbers


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
    home = work / "gnupg"
    try:
        shutil.copytree(args.gnupghome, home, ignore=shutil.ignore_patterns("S.*", "*.lock", "random_seed"))
        home.chmod(0o700)
        cert = _run("gpg", "--homedir", str(home), "--batch", "--armor", "--export", args.fingerprint, capture_output=True).stdout
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

        print("In the dialog: type the current passphrase, then leave the new one EMPTY and confirm.")
        print(f"Only the copy in {work} changes; the original key keeps its passphrase.")
        _run("gpg", "--homedir", str(home), "--pinentry-mode", "ask", "--passwd", key.hex)
        _run("gpgconf", "--homedir", str(home), "--kill", "gpg-agent")
        grip_line = _run(
            "gpg", "--homedir", str(home), "--batch", "--with-colons", "--with-keygrip", "--list-secret-keys", key.hex,
            capture_output=True, text=True,
        ).stdout  # fmt: skip
        keygrip = next(line.split(":")[9] for line in grip_line.splitlines() if line.startswith("grp:"))
        numbers = rsa_numbers((home / "private-keys-v1.d" / f"{keygrip}.key").read_text(encoding="ascii"))
        if (numbers["n"], numbers["e"]) != (key.modulus, key.exponent):
            raise KeyImportError("the private key does not match the public key")
        material = pkcs8(numbers)

        params = _run(
            "aws", "kms", "get-parameters-for-import", "--key-id", args.kms_key_id,
            "--wrapping-algorithm", "RSA_AES_KEY_WRAP_SHA_256", "--wrapping-key-spec", "RSA_4096",
            "--query", "[PublicKey, ImportToken]", "--output", "text", capture_output=True, text=True,
        ).stdout.split()  # fmt: skip
        wrapped = work / "material.bin"
        token = work / "token.bin"
        wrapped.write_bytes(wrap_for_kms(material, base64.b64decode(params[0])))
        token.write_bytes(base64.b64decode(params[1]))
        _run(
            "aws", "kms", "import-key-material", "--key-id", args.kms_key_id,
            "--encrypted-key-material", f"fileb://{wrapped}", "--import-token", f"fileb://{token}",
            "--expiration-model", "KEY_MATERIAL_DOES_NOT_EXPIRE", capture_output=True,
        )  # fmt: skip

        ops.signature_packet(b"nulavio kms import check\n", key, ops.kms_signer(args.kms_key_id, key))
        print(f"KMS key {args.kms_key_id} now signs as {key.hex}.")
    except (KeyImportError, ops.SignError, subprocess.CalledProcessError, OSError, StopIteration) as error:
        detail = getattr(error, "stderr", None)
        print(f"kms_import_key: {error}{(': ' + detail.strip()) if isinstance(detail, str) and detail else ''}", file=sys.stderr)
        return 1
    finally:
        subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"], capture_output=True, check=False)
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
