"""Fixed nv1 vectors from the desktop's own code (libsodium), for the Companion's Java implementation.

    python3 tests/lib/nv1_vectors.py > tests/fixtures/nv1-vectors.json

Inputs are fixed byte patterns, never real keys. tests/unit/test_companion_protocol.py checks
that the committed file is what this script writes; android/nv1 checks Java against it.
"""

from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "launcher"))

from nulavio_launcher.vault import link, sodium
from nulavio_launcher.vault.core import b64e, canonical
from nulavio_launcher.vault.phone import (
    nkdf,
    phone_id_for,
    phone_kek,
    response_key,
    sas_digits,
    transcript,
)


def pattern(start: int, n: int = 32) -> bytes:
    return bytes((start + i) % 256 for i in range(n))


def x25519_public(sk: bytes) -> bytes:
    out = ctypes.create_string_buffer(32)
    sodium.lib().crypto_scalarmult_base(out, sk)
    return out.raw


def ed25519_from_seed(seed: bytes) -> tuple[bytes, bytes]:
    pk, sk = ctypes.create_string_buffer(32), ctypes.create_string_buffer(64)
    sodium.lib().crypto_sign_seed_keypair(pk, sk, seed)
    return sk.raw, pk.raw


def build() -> dict:
    key, other = pattern(0), pattern(32)
    seed = pattern(64)
    sign_sk, sign_pk = ed25519_from_seed(seed)
    message = b"nv1/pair/phone" + pattern(100, 16)
    nonce = pattern(7, 24)
    shared = bytes(sodium.x25519(key, x25519_public(other)))
    t = transcript("invite-1", pattern(1, 32), b"", "Pixel é")
    obj = {
        "b": 1,
        "a": "é café",
        "c": {"z": [1, "x", True, None, -5], "y": {}},
        "d": '\x7f\n"\\ \U0001f600 tab\t',
        "expiry": 1793074275,
    }
    return {
        "_note": "Fixed byte patterns, never real keys. Regenerate with tests/lib/nv1_vectors.py.",
        "canonical": {"object": obj, "bytes": canonical(obj).decode("ascii")},
        "hash32": {"message": b64e(b"abc"), "out": b64e(sodium.hash32(b"abc"))},
        "kdf": {
            "key": b64e(key),
            "label": "pair/k1",
            "parts": [b64e(pattern(1, 5)), "invite-1", b64e(other)],
            "out": b64e(nkdf(key, "pair/k1", pattern(1, 5), "invite-1", other)),
        },
        "transcript": {"parts": ["invite-1", b64e(pattern(1, 32)), b64e(b""), "Pixel é"], "out": b64e(t)},
        "sas": {"shared": b64e(shared), "t": b64e(t), "digits": sas_digits(shared, t)},
        "x25519": {
            "sk": b64e(key),
            "pk": b64e(x25519_public(other)),
            "shared": b64e(shared),
            "public_of_sk": b64e(x25519_public(key)),
        },
        "ed25519": {
            "seed": b64e(seed),
            "pk": b64e(sign_pk),
            "message": b64e(message),
            "signature": b64e(sodium.sign(sign_sk, message)),
        },
        "aead": {
            "key": b64e(key),
            "nonce": b64e(nonce),
            "plaintext": b64e(b"plain text"),
            "ad": b64e(b"ad"),
            "ciphertext": b64e(sodium.aead_encrypt(key, nonce, b"plain text", b"ad")),
        },
        "ids": {"pk": b64e(sign_pk), "id": phone_id_for(sign_pk)},
        "instance_names": [
            ["p", "invite-1", link.instance_name("p", "invite-1")],
            ["u", "req-1", link.instance_name("u", "req-1")],
        ],
        "phone_kek": {
            "z": b64e(shared),
            "profile_id": "prof-1",
            "envelope_id": "env-1",
            "phone_id": "phone-1",
            "eph_pk": b64e(other),
            "dsig_pk": b64e(sign_pk),
            "out": b64e(phone_kek(shared, "prof-1", "env-1", "phone-1", other, sign_pk)),
        },
        "response_key": {"shared": b64e(shared), "request_hash": b64e(pattern(9)), "out": b64e(response_key(shared, pattern(9)))},
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=True))
