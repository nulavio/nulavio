"""Minimal ctypes binding to the system libsodium (decision D1, ADR 0006).

Only standard, reviewed constructions are exposed; nothing here invents
cryptography. Secrets are passed and returned as ``bytearray`` so callers can
wipe them with :func:`memzero`; Python may still keep copies, so wiping is
best effort and documented as such.
"""

from __future__ import annotations

import ctypes
import ctypes.util

KEY_BYTES = 32
NONCE_BYTES = 24  # XChaCha20-Poly1305-IETF
TAG_BYTES = 16
SALT_BYTES = 16  # crypto_pwhash
X25519_BYTES = 32
ED25519_PK_BYTES = 32
ED25519_SK_BYTES = 64
ED25519_SIG_BYTES = 64


class SodiumUnavailable(RuntimeError):
    """libsodium is not installed or could not be initialised."""


class CryptoError(ValueError):
    """Authentication failed (wrong key, tampered data) or invalid input."""


_lib = None


def lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        names = [ctypes.util.find_library("sodium"), "libsodium.so.26", "libsodium.so.23", "libsodium.so"]
        last: Exception | None = None
        for name in [n for n in names if n]:
            try:
                candidate = ctypes.CDLL(name)
                break
            except OSError as exc:
                last = exc
        else:
            raise SodiumUnavailable(f"libsodium not found: {last}")
        if candidate.sodium_init() < 0:
            raise SodiumUnavailable("sodium_init failed")
        _configure(candidate)
        _lib = candidate
    return _lib


def available() -> bool:
    try:
        lib()
        return True
    except SodiumUnavailable:
        return False


def _configure(s: ctypes.CDLL) -> None:
    c_ull = ctypes.c_ulonglong
    s.crypto_pwhash_alg_argon2id13.restype = ctypes.c_int
    s.crypto_pwhash.argtypes = [
        ctypes.c_void_p,
        c_ull,
        ctypes.c_void_p,
        c_ull,
        ctypes.c_void_p,
        c_ull,
        ctypes.c_size_t,
        ctypes.c_int,
    ]
    s.crypto_aead_xchacha20poly1305_ietf_encrypt.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(c_ull),
        ctypes.c_void_p,
        c_ull,
        ctypes.c_void_p,
        c_ull,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    s.crypto_aead_xchacha20poly1305_ietf_decrypt.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(c_ull),
        ctypes.c_void_p,
        ctypes.c_void_p,
        c_ull,
        ctypes.c_void_p,
        c_ull,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    s.crypto_generichash.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        c_ull,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    s.crypto_scalarmult.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    s.crypto_scalarmult_base.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    s.crypto_sign_keypair.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    s.crypto_sign_detached.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(c_ull),
        ctypes.c_void_p,
        c_ull,
        ctypes.c_void_p,
    ]
    s.crypto_sign_verify_detached.argtypes = [ctypes.c_void_p, ctypes.c_void_p, c_ull, ctypes.c_void_p]
    s.randombytes_buf.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    s.randombytes_buf.restype = None
    s.sodium_memzero.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    s.sodium_memzero.restype = None
    s.sodium_memcmp.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]


def _ptr(buf: bytes | bytearray | None) -> ctypes.c_void_p | None:
    """A pointer to the buffer's own memory (no copy for bytearray)."""
    if buf is None or len(buf) == 0:
        return None
    if isinstance(buf, bytearray):
        return ctypes.cast((ctypes.c_char * len(buf)).from_buffer(buf), ctypes.c_void_p)
    return ctypes.cast(ctypes.c_char_p(bytes(buf)), ctypes.c_void_p)


def memzero(buf: bytearray | None) -> None:
    if buf:
        lib().sodium_memzero(_ptr(buf), len(buf))


def random_bytes(n: int) -> bytearray:
    out = bytearray(n)
    lib().randombytes_buf(_ptr(out), n)
    return out


def equal(a: bytes | bytearray, b: bytes | bytearray) -> bool:
    """Constant-time comparison of equal-length values."""
    if len(a) != len(b):
        return False
    return lib().sodium_memcmp(_ptr(bytearray(a)), _ptr(bytearray(b)), len(a)) == 0


def aead_encrypt(key: bytes | bytearray, nonce: bytes, plaintext: bytes | bytearray, ad: bytes) -> bytes:
    if len(key) != KEY_BYTES or len(nonce) != NONCE_BYTES:
        raise CryptoError("bad key or nonce length")
    out = bytearray(len(plaintext) + TAG_BYTES)
    out_len = ctypes.c_ulonglong(0)
    rc = lib().crypto_aead_xchacha20poly1305_ietf_encrypt(
        _ptr(out), ctypes.byref(out_len), _ptr(plaintext), len(plaintext), _ptr(ad), len(ad), None, _ptr(nonce), _ptr(key)
    )
    if rc != 0:
        raise CryptoError("encryption failed")
    return bytes(out[: out_len.value])


def aead_decrypt(key: bytes | bytearray, nonce: bytes, ciphertext: bytes, ad: bytes) -> bytearray:
    if len(key) != KEY_BYTES or len(nonce) != NONCE_BYTES or len(ciphertext) < TAG_BYTES:
        raise CryptoError("bad key, nonce or ciphertext length")
    out = bytearray(len(ciphertext) - TAG_BYTES)
    out_len = ctypes.c_ulonglong(0)
    rc = lib().crypto_aead_xchacha20poly1305_ietf_decrypt(
        _ptr(out) if out else ctypes.c_void_p(0),
        ctypes.byref(out_len),
        None,
        _ptr(ciphertext),
        len(ciphertext),
        _ptr(ad),
        len(ad),
        _ptr(nonce),
        _ptr(key),
    )
    if rc != 0:
        memzero(out)
        raise CryptoError("authentication failed")
    return out


def argon2id(password: bytes | bytearray, salt: bytes, ops: int, mem: int, length: int = KEY_BYTES) -> bytearray:
    if len(salt) != SALT_BYTES:
        raise CryptoError("bad salt length")
    s = lib()
    out = bytearray(length)
    rc = s.crypto_pwhash(_ptr(out), length, _ptr(password), len(password), _ptr(salt), ops, mem, s.crypto_pwhash_alg_argon2id13())
    if rc != 0:
        raise CryptoError("argon2id failed (out of memory?)")
    return out


def blake2b(key: bytes | bytearray, message: bytes, length: int = KEY_BYTES) -> bytearray:
    """Keyed BLAKE2b (crypto_generichash): the domain-separated KDF and MAC."""
    if not 16 <= len(key) <= 64:
        raise CryptoError("BLAKE2b key must be 16-64 bytes")
    out = bytearray(length)
    rc = lib().crypto_generichash(_ptr(out), length, _ptr(message), len(message), _ptr(key), len(key))
    if rc != 0:
        raise CryptoError("BLAKE2b failed")
    return out


def hash32(message: bytes) -> bytes:
    """Unkeyed BLAKE2b-256 (transcripts, identifiers)."""
    out = bytearray(32)
    lib().crypto_generichash(_ptr(out), 32, _ptr(message), len(message), None, 0)
    return bytes(out)


def x25519_keypair() -> tuple[bytearray, bytes]:
    sk = random_bytes(X25519_BYTES)
    pk = bytearray(X25519_BYTES)
    lib().crypto_scalarmult_base(_ptr(pk), _ptr(sk))
    return sk, bytes(pk)


def x25519(sk: bytes | bytearray, pk: bytes) -> bytearray:
    if len(sk) != X25519_BYTES or len(pk) != X25519_BYTES:
        raise CryptoError("bad X25519 key length")
    out = bytearray(X25519_BYTES)
    if lib().crypto_scalarmult(_ptr(out), _ptr(sk), _ptr(pk)) != 0:
        raise CryptoError("invalid public key")
    return out


def ed25519_keypair() -> tuple[bytearray, bytes]:
    pk = bytearray(ED25519_PK_BYTES)
    sk = bytearray(ED25519_SK_BYTES)
    lib().crypto_sign_keypair(_ptr(pk), _ptr(sk))
    return sk, bytes(pk)


def sign(sk: bytes | bytearray, message: bytes) -> bytes:
    sig = bytearray(ED25519_SIG_BYTES)
    lib().crypto_sign_detached(_ptr(sig), None, _ptr(message), len(message), _ptr(sk))
    return bytes(sig)


def verify(pk: bytes, message: bytes, signature: bytes) -> bool:
    if len(pk) != ED25519_PK_BYTES or len(signature) != ED25519_SIG_BYTES:
        return False
    return lib().crypto_sign_verify_detached(_ptr(signature), _ptr(message), len(message), _ptr(pk)) == 0
