"""Phone unlock protocol `nv1`, desktop side (ADR 0005; docs/architecture/vault-and-unlock.md).

The phone keeps its own keys; the desktop stores only their public halves.
An unlock releases a KEK that only the paired phone can recompute, encrypted
to a one-time session key and signed by the phone. An approval that does not
carry that KEK unlocks nothing.

Transport is out of scope here (QR codes and the local network come with the
Companion app, S11); messages are plain dicts of base64url strings.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import sodium
from .core import (
    PASSWORD_KDF,
    Envelope,
    Vault,
    VaultError,
    b64d,
    b64e,
    canonical,
    combined_kek,
    kdf,
    new_id,
    stretch,
    stretch_params,
)

CONTEXT = b"nulavio/nv1/"
PAIRING_TTL = 300
REQUEST_TTL = 60
CLOCK_SKEW = 120
# The phone refuses a request that claims to stay valid longer than one request's lifetime (plus clock
# skew): a request cannot be prepared long in advance and kept for later.
MAX_REQUEST_AHEAD = REQUEST_TTL + CLOCK_SKEW
REPLAY_CACHE = 1024
PHONE_REFUSALS = ("declined", "biometric-unavailable", "device-locked")

Clock = Callable[[], float]


class ProtocolError(VaultError):
    """A rejected nv1 message. `code` is stable for the UI and tests."""


def nkdf(key: bytes | bytearray, label: str, *parts: bytes | str) -> bytearray:
    return kdf(key, label, *parts, context=CONTEXT)


def transcript(*parts: bytes | str) -> bytes:
    """BLAKE2b-256 over length-prefixed parts (no ambiguity between fields)."""
    message = bytearray()
    for part in parts:
        data = part.encode() if isinstance(part, str) else bytes(part)
        message += len(data).to_bytes(4, "big") + data
    return sodium.hash32(bytes(message))


def seal(key: bytes | bytearray, plaintext: bytes | bytearray, ad: bytes) -> dict:
    nonce = bytes(sodium.random_bytes(sodium.NONCE_BYTES))
    return {"n": b64e(nonce), "c": b64e(sodium.aead_encrypt(key, nonce, plaintext, ad))}


def unseal(key: bytes | bytearray, box: dict, ad: bytes) -> bytearray:
    try:
        return sodium.aead_decrypt(key, b64d(box["n"]), b64d(box["c"]), ad)
    except (sodium.CryptoError, KeyError, TypeError, ValueError):
        raise ProtocolError("bad-message") from None


def seal_json(key: bytes | bytearray, obj: dict, ad: bytes) -> dict:
    return seal(key, canonical(obj), ad)


def unseal_json(key: bytes | bytearray, box: dict, ad: bytes) -> dict:
    plain = unseal(key, box, ad)
    try:
        return json.loads(bytes(plain))
    except ValueError:
        raise ProtocolError("bad-message") from None
    finally:
        sodium.memzero(plain)


def phone_id_for(psig_pk: bytes) -> str:
    return b64e(sodium.hash32(psig_pk)[:16])


def desktop_id_for(dsig_pk: bytes) -> str:
    return b64e(sodium.hash32(dsig_pk)[:16])


def sas_digits(shared: bytes | bytearray, t: bytes) -> str:
    raw = nkdf(shared, "pair/sas", t)
    try:
        return f"{int.from_bytes(raw[:4], 'big') % 1_000_000:06d}"
    finally:
        sodium.memzero(raw)


def phone_kek(z: bytes | bytearray, profile_id: str, envelope_id: str, phone_id: str, eph_pk: bytes, dsig_pk: bytes) -> bytearray:
    """The KEK a phone envelope opens with. It is bound to the desktop that made the envelope (its signing
    key): the phone derives it with the key of the desktop whose request it verified, so a request signed by
    any other paired desktop yields a key that opens nothing (audit V3, residual risk R59)."""
    return nkdf(z, "envelope/phone/desktop-bound", profile_id, envelope_id, phone_id, eph_pk, dsig_pk)


def response_key(shared: bytes | bytearray, request_hash: bytes) -> bytearray:
    return nkdf(shared, "unlock/response", request_hash)


def request_signing_input(request: dict) -> bytes:
    return b"nv1/unlock/request" + canonical(request)


def response_signing_input(request_hash: bytes, box: dict) -> bytes:
    return b"nv1/unlock/response" + request_hash + canonical(box)


# -- identities ------------------------------------------------------------------------


@dataclass
class DesktopIdentity:
    """Per-installation signing (Ed25519) and key-exchange (X25519) keys, stored 0600."""

    sig_sk: bytearray
    sig_pk: bytes
    kx_sk: bytearray
    kx_pk: bytes

    @property
    def desktop_id(self) -> str:
        return desktop_id_for(self.sig_pk)

    @classmethod
    def generate(cls) -> DesktopIdentity:
        sig_sk, sig_pk = sodium.ed25519_keypair()
        kx_sk, kx_pk = sodium.x25519_keypair()
        return cls(sig_sk, sig_pk, kx_sk, kx_pk)

    @classmethod
    def load_or_create(cls, path: Path) -> DesktopIdentity:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            return cls(bytearray(b64d(obj["sig_sk"])), b64d(obj["sig_pk"]), bytearray(b64d(obj["kx_sk"])), b64d(obj["kx_pk"]))
        identity = cls.generate()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = json.dumps(
            {
                "sig_sk": b64e(identity.sig_sk),
                "sig_pk": b64e(identity.sig_pk),
                "kx_sk": b64e(identity.kx_sk),
                "kx_pk": b64e(identity.kx_pk),
            }
        ).encode()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        return identity


@dataclass
class PairedPhone:
    phone_id: str
    psig_pk: bytes
    pkx_pk: bytes
    name: str
    dsig_pk: bytes = b""  # the signing key of the desktop this phone was paired with

    def fields(self) -> dict:
        return {
            "phone_id": self.phone_id,
            "psig_pk": b64e(self.psig_pk),
            "pkx_pk": b64e(self.pkx_pk),
            "name": self.name,
            "dsig_pk": b64e(self.dsig_pk),
        }

    @classmethod
    def from_fields(cls, obj: dict) -> PairedPhone:
        dsig = obj.get("dsig_pk")
        return cls(obj["phone_id"], b64d(obj["psig_pk"]), b64d(obj["pkx_pk"]), obj.get("name", ""), b64d(dsig) if dsig else b"")


# -- pairing ------------------------------------------------------------------------------


class Pairing:
    """One pairing attempt: QR invite → hello → accept (+ 6 digits) → confirm."""

    def __init__(self, identity: DesktopIdentity, desktop_name: str, address: str = "", clock: Clock = time.time):
        self.identity = identity
        self.desktop_name = desktop_name
        self.clock = clock
        self.invite_id = b64e(secrets.token_bytes(16))
        self.secret = sodium.random_bytes(32)
        self.de_sk, self.de_pk = sodium.x25519_keypair()
        self.expiry = int(clock()) + PAIRING_TTL
        self.address = address
        self.state = "invited"
        self.sas: str | None = None
        self._shared: bytearray | None = None
        self._t: bytes | None = None
        self._phone: PairedPhone | None = None

    def invite(self) -> dict:
        """The QR payload. It carries the pairing secret: show it only on this screen."""
        return {
            "v": 1,
            "i": self.invite_id,
            "k": b64e(self.de_pk),
            "s": b64e(self.secret),
            "d": b64e(self.identity.sig_pk),
            "a": self.address,
            "e": self.expiry,
        }

    def _check(self, msg: dict, state: str) -> None:
        if self.state != state:
            raise ProtocolError("bad-state")
        if self.clock() > self.expiry:
            self.cancel()
            raise ProtocolError("expired")
        if msg.get("i") != self.invite_id:
            raise ProtocolError("bad-message")

    def on_hello(self, msg: dict) -> dict:
        self._check(msg, "invited")
        try:
            pe_pk = b64d(msg["pe"])
            shared = sodium.x25519(self.de_sk, pe_pk)
        except (KeyError, TypeError, ValueError, sodium.CryptoError):
            raise ProtocolError("bad-message") from None
        k1 = nkdf(self.secret, "pair/k1", shared, self.invite_id, self.de_pk, pe_pk)
        try:
            body = unseal_json(k1, msg["box"], self.invite_id.encode())
        except ProtocolError:
            sodium.memzero(shared)
            self.cancel()  # someone without the QR secret: end this attempt
            raise
        finally:
            sodium.memzero(k1)
        psig_pk, pkx_pk, name = b64d(body["psig"]), b64d(body["pkx"]), str(body.get("name", ""))[:64]
        t = transcript(self.invite_id, self.de_pk, pe_pk, self.identity.sig_pk, psig_pk, pkx_pk, name)
        sig_d = sodium.sign(self.identity.sig_sk, b"nv1/pair/desktop" + t)
        k2 = nkdf(self.secret, "pair/k2", shared, t)
        try:
            box = seal_json(
                k2, {"dkx": b64e(self.identity.kx_pk), "name": self.desktop_name, "sig": b64e(sig_d)}, self.invite_id.encode()
            )
        finally:
            sodium.memzero(k2)
        self._shared, self._t = shared, t
        self._phone = PairedPhone(phone_id_for(psig_pk), psig_pk, pkx_pk, name, self.identity.sig_pk)
        self.sas = sas_digits(shared, t)
        self.state = "compare"
        return {"i": self.invite_id, "box": box}

    def complete(self, msg: dict, user_confirmed_sas: bool) -> PairedPhone:
        """The phone's confirmation plus the user's answer to "do the 6 digits match?"."""
        self._check(msg, "compare")
        if not user_confirmed_sas:
            self.cancel()
            raise ProtocolError("sas-mismatch")
        k3 = nkdf(self.secret, "pair/k3", self._shared, self._t)
        try:
            body = unseal_json(k3, msg["box"], self.invite_id.encode())
        finally:
            sodium.memzero(k3)
        if not sodium.verify(self._phone.psig_pk, b"nv1/pair/phone" + self._t, b64d(body.get("sig", ""))):
            self.cancel()
            raise ProtocolError("bad-signature")
        phone = self._phone
        self.cancel()
        self.state = "paired"
        return phone

    def cancel(self) -> None:
        for buf in (self.secret, self.de_sk, self._shared):
            sodium.memzero(buf)
        self._shared = None
        self.state = "cancelled"


# -- phone envelopes ----------------------------------------------------------------------


def _phone_fields(vault: Vault, phone: PairedPhone, envelope_id: str) -> tuple[dict, bytearray]:
    if len(phone.dsig_pk) != sodium.ED25519_PK_BYTES:
        raise ProtocolError("phone-needs-pairing")  # no desktop to bind the envelope to
    eph_sk, eph_pk = sodium.x25519_keypair()
    try:
        z = sodium.x25519(eph_sk, phone.pkx_pk)
    finally:
        sodium.memzero(eph_sk)
    try:
        kek = phone_kek(z, vault.profile_id, envelope_id, phone.phone_id, eph_pk, phone.dsig_pk)
    finally:
        sodium.memzero(z)
    return {**phone.fields(), "eph_pk": b64e(eph_pk)}, kek


def add_phone(vault: Vault, phone: PairedPhone, label: str = "") -> Envelope:
    envelope_id = new_id()
    fields, kek = _phone_fields(vault, phone, envelope_id)
    try:
        return vault.add_kek("phone", kek, fields, label or phone.name, envelope_id)
    finally:
        sodium.memzero(kek)


def add_password_and_phone(
    vault: Vault, password: str, phone: PairedPhone, params: dict | None = None, label: str = ""
) -> Envelope:
    """One envelope that needs both the password and the phone (no single-factor path)."""
    if len(password) < 8:
        raise VaultError("password-too-short")
    envelope_id = new_id()
    pw_fields = stretch_params(params or PASSWORD_KDF)
    kek_pw = stretch(password.encode(), pw_fields)
    phone_fields, kek_phone = _phone_fields(vault, phone, envelope_id)
    kek = combined_kek(kek_pw, kek_phone)
    try:
        return vault.add_kek("combined", kek, {"password": pw_fields, "phone": phone_fields}, label, envelope_id)
    finally:
        for buf in (kek_pw, kek_phone, kek):
            sodium.memzero(buf)


def phone_part(env: Envelope) -> dict | None:
    if env.method == "phone":
        return env.data
    if env.method == "combined":
        return env.data.get("phone")
    return None


def _phone_keys(part: dict) -> tuple[str, bytes, bytes, str, bytes]:
    """phone_id, Psig_pk, Pkx_pk, eph_pk and the binding desktop's Dsig_pk from an envelope; a damaged
    envelope is an error, not a crash. An envelope made before desktop binding has no Dsig_pk: the phone
    can no longer open it, so it needs pairing again."""
    if "dsig_pk" not in part:
        raise ProtocolError("phone-needs-pairing")
    try:
        keys = (part["phone_id"], b64d(part["psig_pk"]), b64d(part["pkx_pk"]), part["eph_pk"], b64d(part["dsig_pk"]))
        b64d(keys[3])
    except (KeyError, TypeError, ValueError):
        raise ProtocolError("damaged-envelope") from None
    if (
        not isinstance(keys[0], str)
        or len(keys[1]) != sodium.ED25519_PK_BYTES
        or len(keys[2]) != sodium.X25519_BYTES
        or len(keys[4]) != sodium.ED25519_PK_BYTES
    ):
        raise ProtocolError("damaged-envelope")
    return keys


def remove_phone(vault: Vault, phone_id: str) -> int:
    """Revoke a phone in this profile: delete every envelope it can open. Returns how many."""
    doomed = [e.id for e in vault.envelopes() if (phone_part(e) or {}).get("phone_id") == phone_id]
    for envelope_id in doomed:
        vault.remove(envelope_id)
    return len(doomed)


# -- unlock -------------------------------------------------------------------------------


@dataclass
class _Pending:
    request: dict
    request_hash: bytes
    session_sk: bytearray
    envelope: Envelope
    expiry: int
    profile_id: str


@dataclass
class PhoneUnlock:
    """Signed, expiring, one-shot unlock requests and their responses."""

    identity: DesktopIdentity
    desktop_name: str
    clock: Clock = time.time
    pending: dict[str, _Pending] = field(default_factory=dict)
    used: list[str] = field(default_factory=list)

    def request(self, vault: Vault, envelope_id: str, profile_name: str) -> dict:
        env = next((e for e in vault.envelopes() if e.id == envelope_id), None)
        part = phone_part(env) if env else None
        if part is None:
            raise ProtocolError("unpaired")
        phone_id, _, _, eph_pk, dsig_pk = _phone_keys(part)
        if dsig_pk != self.identity.sig_pk:
            raise ProtocolError("phone-needs-pairing")  # made by another desktop identity: the phone answers for ours
        for req_id in [r for r, p in self.pending.items() if p.profile_id == vault.profile_id]:
            self.cancel(req_id)  # one pending request per profile
        session_sk, session_pk = sodium.x25519_keypair()
        request = {
            "v": 1,
            "req_id": b64e(secrets.token_bytes(16)),
            "op": "unlock-profile",
            "profile_id": vault.profile_id,
            "profile_name": profile_name,
            "desktop_id": self.identity.desktop_id,
            "desktop_name": self.desktop_name,
            "envelope_id": env.id,
            "phone_id": phone_id,
            "eph_pk": eph_pk,
            "s_pk": b64e(session_pk),
            "expiry": int(self.clock()) + REQUEST_TTL,
        }
        signature = sodium.sign(self.identity.sig_sk, request_signing_input(request))
        self.pending[request["req_id"]] = _Pending(
            request, sodium.hash32(canonical(request)), session_sk, env, request["expiry"], vault.profile_id
        )
        return {"r": dict(request), "sig": b64e(signature)}

    def cancel(self, req_id: str | None = None) -> None:
        for key in [req_id] if req_id else list(self.pending):
            pending = self.pending.pop(key, None)
            if pending:
                sodium.memzero(pending.session_sk)
                self._remember(key)

    def _remember(self, req_id: str) -> None:
        self.used.append(req_id)
        del self.used[:-REPLAY_CACHE]

    def accept(self, response: dict, profile_id: str | None = None) -> tuple[Envelope, bytearray]:
        """Verify a response; return the envelope and the phone's KEK. One shot per request."""
        req_id = response.get("req_id")
        pending = self.pending.get(req_id) if isinstance(req_id, str) else None
        if pending is None:
            raise ProtocolError("replay" if req_id in self.used else "unknown-request")
        if profile_id is not None and pending.profile_id != profile_id:
            raise ProtocolError("wrong-profile")
        if self.clock() > pending.expiry:
            self.cancel(req_id)
            raise ProtocolError("expired")
        phone_id, psig_pk, pkx_pk, _, _ = _phone_keys(phone_part(pending.envelope))
        if response.get("phone_id") != phone_id:
            raise ProtocolError("unpaired")
        refused = "error" in response
        payload = {"error": str(response["error"])} if refused else response.get("box")
        try:
            signature = b64d(response.get("sig", ""))
        except (TypeError, ValueError):
            raise ProtocolError("bad-signature") from None
        if not isinstance(payload, dict) or not sodium.verify(
            psig_pk, response_signing_input(pending.request_hash, payload), signature
        ):
            raise ProtocolError("bad-signature")  # not from the phone: keep waiting for the real answer
        if refused:
            self.cancel(req_id)
            code = payload["error"]
            raise ProtocolError(code if code in PHONE_REFUSALS else "phone-error")
        box = payload
        try:
            shared = sodium.x25519(pending.session_sk, pkx_pk)
        except sodium.CryptoError:
            self.cancel(req_id)
            raise ProtocolError("damaged-envelope") from None
        rk = response_key(shared, pending.request_hash)
        sodium.memzero(shared)
        try:
            kek = unseal(rk, box, req_id.encode())
        finally:
            sodium.memzero(rk)
            self.cancel(req_id)
        if len(kek) != sodium.KEY_BYTES:
            sodium.memzero(kek)
            raise ProtocolError("bad-message")
        return pending.envelope, kek
