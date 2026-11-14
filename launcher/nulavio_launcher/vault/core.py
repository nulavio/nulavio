"""Nulavio Vault core (ADR 0006): profile DEK, one AEAD envelope per unlock method.

The DEK is random, lives only in memory while a profile is unlocked, and is
stored only inside envelopes. Each envelope is XChaCha20-Poly1305 under a key
(KEK) that a method can recompute: a password (Argon2id), a recovery code, a
key in the OS keyring, or a paired phone (protocol nv1, phone.py). Envelope
headers are the AEAD associated data; every derivation is domain-separated;
`dek_check` proves an unlock recovered the right DEK; a MAC over the metadata
(keyed from the DEK) detects tampering after unlock. Writes are atomic.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import sodium

FORMAT = "nulavio-vault"
VERSION = 1
SUITE = "nv1"
CONTEXT = b"nulavio/vault/v1/"

# Argon2id parameters (libsodium "moderate" for passwords; recovery codes are
# high-entropy, so "interactive" suffices). Stored per envelope.
PASSWORD_KDF = {"ops": 3, "mem": 256 * 1024 * 1024}
RECOVERY_KDF = {"ops": 2, "mem": 64 * 1024 * 1024}

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
RECOVERY_GROUPS, RECOVERY_GROUP_LEN = 7, 4  # 28 symbols x 5 bits = 140 bits

METHOD_STATES = {
    "password": ("password_protected",),
    "recovery-code": ("password_protected",),
    "os-keyring": ("os_user_protected",),
    "phone": ("phone_key_release_verified",),
    "combined": ("password_protected", "phone_key_release_verified"),
}


class VaultError(RuntimeError):
    """A stable error code for the UI (`code`), plus a message for logs (never a secret)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def b64e(data: bytes | bytearray) -> str:
    return base64.urlsafe_b64encode(bytes(data)).rstrip(b"=").decode()


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def kdf(key: bytes | bytearray, label: str, *parts: bytes | str, context: bytes = CONTEXT) -> bytearray:
    """BLAKE2b keyed with `key`, over a labelled, length-prefixed encoding of `parts`."""
    message = bytearray(context + label.encode() + b"\x00")
    for part in parts:
        data = part.encode() if isinstance(part, str) else bytes(part)
        message += len(data).to_bytes(4, "big") + data
    return sodium.blake2b(key, bytes(message))


# -- recovery codes -----------------------------------------------------------------


def new_recovery_code() -> str:
    symbols = "".join(secrets.choice(CROCKFORD) for _ in range(RECOVERY_GROUPS * RECOVERY_GROUP_LEN))
    return "-".join(symbols[i : i + RECOVERY_GROUP_LEN] for i in range(0, len(symbols), RECOVERY_GROUP_LEN))


def normalize_recovery_code(text: str) -> bytes:
    """Accept lower case, spaces and the usual look-alikes (O→0, I/L→1)."""
    cleaned = text.upper().replace("-", "").replace(" ", "").replace("O", "0").replace("I", "1").replace("L", "1")
    if len(cleaned) != RECOVERY_GROUPS * RECOVERY_GROUP_LEN or any(c not in CROCKFORD for c in cleaned):
        raise VaultError("recovery-code-malformed")
    return cleaned.encode()


# -- metadata ---------------------------------------------------------------------------


@dataclass
class Envelope:
    id: str
    method: str
    data: dict  # method-specific fields (kdf params, phone id, keyring ref, ...)
    nonce: str
    ct: str
    created: str
    label: str = ""

    def header(self, profile_id: str) -> bytes:
        """AEAD associated data: binds the envelope to its profile, method and fields."""
        return canonical(
            {
                "format": FORMAT,
                "version": VERSION,
                "suite": SUITE,
                "profile": profile_id,
                "envelope": self.id,
                "method": self.method,
                "data": self.data,
            }
        )

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "method": self.method,
            "data": self.data,
            "nonce": self.nonce,
            "ct": self.ct,
            "created": self.created,
            "label": self.label,
        }

    @classmethod
    def from_json(cls, obj: dict) -> Envelope:
        return cls(obj["id"], obj["method"], obj.get("data", {}), obj["nonce"], obj["ct"], obj["created"], obj.get("label", ""))


def new_id() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _well_formed(meta: dict) -> bool:
    try:
        return (
            isinstance(meta["profile_id"], str)
            and isinstance(meta["dek_check"], str)
            and isinstance(meta.get("policy", {}), dict)
            and isinstance(meta["envelopes"], list)
            and all(isinstance(e, dict) and {"id", "method", "nonce", "ct", "created"} <= e.keys() for e in meta["envelopes"])
        )
    except (KeyError, TypeError):
        return False


def _drop_stale_backup(path: Path, meta: dict) -> None:
    """Remove a .bak older than vault.json: versions up to 160.0-0.1 kept the previous
    file there, with envelopes that had been removed or replaced (audit V2)."""
    backup = path.with_suffix(path.suffix + ".bak")
    try:
        old = json.loads(backup.read_text(encoding="utf-8"))
        if int(old.get("generation", 0)) < int(meta.get("generation", 0)):
            backup.unlink()
    except (OSError, ValueError, TypeError, AttributeError):
        pass


class Vault:
    """One profile's key material. Load it locked; unlock with any envelope's method."""

    def __init__(self, path: Path, meta: dict):
        self.path = path
        self.meta = meta
        self.dek: bytearray | None = None
        self.tampered = False
        self.from_backup = False
        self.opened_with: str | None = None  # the envelope the last unlock opened
        # What the last mount did with a recovery code replacement left unfinished: "finished", "undone", or
        # "unsettled" (it could not save: both codes still open the profile), "unknown" (it cannot tell whether it
        # saved: the profile's unlock methods say which code opens it); and "not-recorded" when it saved
        # but could not record that inside the volume (#187).
        self.settled: str | None = None
        self.settle_warning: str | None = None

    # -- persistence ---------------------------------------------------------------

    @classmethod
    def create(cls, path: Path, profile_id: str | None = None) -> Vault:
        """A new vault, unlocked, with no envelope yet (add one before saving)."""
        if path.exists():
            raise VaultError("exists", str(path))
        dek = sodium.random_bytes(sodium.KEY_BYTES)
        meta = {
            "format": FORMAT,
            "version": VERSION,
            "suite": SUITE,
            "profile_id": profile_id or uuid.uuid4().hex,
            "created": _now(),
            "dek_check": b64e(kdf(dek, "dek-check")),
            "policy": {},
            "envelopes": [],
        }
        vault = cls(path, meta)
        vault.dek = dek
        return vault

    @classmethod
    def load(cls, path: Path) -> Vault:
        """Read vault.json, falling back to vault.json.bak if the main file is damaged.

        A newer format is refused, never "downgraded" to the backup.
        """
        for candidate in (path, path.with_suffix(path.suffix + ".bak")):
            try:
                meta = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict) or meta.get("format") != FORMAT:
                continue
            if meta.get("version") != VERSION or meta.get("suite") != SUITE:
                raise VaultError("unsupported-version", f"{meta.get('version')}/{meta.get('suite')}")
            if not _well_formed(meta):
                continue
            vault = cls(path, meta)
            vault.from_backup = candidate != path
            if not vault.from_backup:
                _drop_stale_backup(path, meta)
            return vault
        raise VaultError("unreadable", str(path))

    def save(self, *, accept_changes: bool = False) -> None:
        """Atomic replace of vault.json and of its .bak copy. Requires the DEK (refreshes the MAC).

        A vault whose MAC did not match at unlock is refused unless the person reviewed
        its methods and accepted them (accept_changes): signing it again as a side effect
        of another change would make an injected envelope legitimate (audit V4).

        The .bak holds the same new content, never the previous file: a removed or
        replaced envelope must not stay on disk where its old secret still opens it.
        The copy is written first, so a crash in between leaves the previous
        vault.json (the change did not happen) next to a valid new copy.
        """
        self._require_unlocked()
        if self.tampered and not accept_changes:
            raise VaultError("metadata-tampered", "the profile's key file was changed outside Nulavio")
        if not self.meta["envelopes"]:
            raise VaultError("no-method")
        # A counter the encrypted storage will mirror (S5), so a rolled-back
        # vault.json (e.g. a revoked phone restored) can be detected.
        self.meta["generation"] = int(self.meta.get("generation", 0)) + 1
        self.meta["mac"] = b64e(self._mac())
        data = json.dumps(self.meta, indent=1, sort_keys=True).encode()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for target in (self.path.with_suffix(self.path.suffix + ".bak"), self.path):
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, target)
        dir_fd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _mac(self) -> bytearray:
        body = {k: v for k, v in self.meta.items() if k != "mac"}
        key = kdf(self.dek, "metadata-mac", self.meta["profile_id"])
        try:
            return sodium.blake2b(key, canonical(body))
        finally:
            sodium.memzero(key)

    # -- state ---------------------------------------------------------------------

    @property
    def profile_id(self) -> str:
        return self.meta["profile_id"]

    @property
    def unlocked(self) -> bool:
        return self.dek is not None

    def envelopes(self, method: str | None = None) -> list[Envelope]:
        items = [Envelope.from_json(e) for e in self.meta["envelopes"]]
        return [e for e in items if method is None or e.method == method]

    def protection_states(self) -> list[str]:
        return sorted({state for e in self.envelopes() for state in METHOD_STATES[e.method]})

    def lock(self) -> None:
        """Drop the DEK (wiped). The storage layer unmounts separately (S5)."""
        sodium.memzero(self.dek)
        self.dek = None
        self.opened_with = None

    def _require_unlocked(self) -> None:
        if self.dek is None:
            raise VaultError("locked")

    # -- envelopes -----------------------------------------------------------------

    def _add(self, method: str, kek: bytes | bytearray, data: dict, label: str = "", envelope_id: str | None = None) -> Envelope:
        self._require_unlocked()
        env = Envelope(envelope_id or new_id(), method, data, "", "", _now(), label)
        nonce = bytes(sodium.random_bytes(sodium.NONCE_BYTES))
        env.nonce = b64e(nonce)
        env.ct = b64e(sodium.aead_encrypt(self._wrap_key(kek, env), nonce, self.dek, env.header(self.profile_id)))
        self.meta["envelopes"].append(env.to_json())
        return env

    def _wrap_key(self, kek: bytes | bytearray, env: Envelope) -> bytearray:
        return kdf(kek, "envelope-key", self.profile_id, env.id, env.method)

    def _open(self, env: Envelope, kek: bytes | bytearray) -> bytearray:
        try:
            nonce, ct, check = b64d(env.nonce), b64d(env.ct), b64d(self.meta["dek_check"])
        except (TypeError, ValueError):
            raise VaultError("damaged-envelope") from None
        wrap = self._wrap_key(kek, env)
        try:
            dek = sodium.aead_decrypt(wrap, nonce, ct, env.header(self.profile_id))
        except sodium.CryptoError:
            raise VaultError("wrong-secret") from None
        finally:
            sodium.memzero(wrap)
        # Key commitment: the right DEK, not just a decryptable blob.
        if not sodium.equal(kdf(dek, "dek-check"), check):
            sodium.memzero(dek)
            raise VaultError("wrong-secret")
        return dek

    def _accept(self, dek: bytearray, env: Envelope) -> None:
        self.dek = dek
        self.opened_with = env.id
        mac = self.meta.get("mac")
        self.tampered = mac is None or not sodium.equal(self._mac(), b64d(mac))

    def remove(self, envelope_id: str) -> None:
        self._require_unlocked()
        pending = self.pending_recovery_code()
        if pending and envelope_id in pending["old"]:
            # #187 review: removing the code being replaced would leave the new one, which nobody has typed
            # back and maybe nobody saw, in its place. Replace it again, or let an unlock settle it, first.
            raise VaultError("replacement-pending")
        remaining = [e for e in self.meta["envelopes"] if e["id"] != envelope_id]
        if len(remaining) == len(self.meta["envelopes"]):
            raise VaultError("not-found")
        if not [e for e in remaining if not pending or e["id"] != pending["new"]]:
            raise VaultError("last-method")  # a code not typed back is not a way in anyone is known to have
        self.meta["envelopes"] = remaining
        if pending and envelope_id == pending["new"]:
            del self.meta["pending_recovery"]  # the new code withdrawn: the old one stays as it was

    # Password -----------------------------------------------------------------------

    def add_password(self, password: str, params: dict | None = None, label: str = "") -> Envelope:
        if len(password) < 8:
            raise VaultError("password-too-short")
        data = stretch_params(params or PASSWORD_KDF)
        kek = stretch(password.encode(), data)
        try:
            return self._add("password", kek, data, label)
        finally:
            sodium.memzero(kek)

    def unlock_password(self, password: str) -> None:
        self._unlock_with_secret("password", password.encode())

    # Recovery code ------------------------------------------------------------------

    def add_recovery_code(self, params: dict | None = None) -> str:
        """Create a recovery code (returned once, never stored) and its envelope."""
        return self._new_recovery_code(params)[0]

    def _new_recovery_code(self, params: dict | None) -> tuple[str, Envelope]:
        code = new_recovery_code()
        data = stretch_params(params or RECOVERY_KDF)
        kek = stretch(normalize_recovery_code(code), data)
        try:
            env = self._add("recovery-code", kek, data)
        finally:
            sodium.memzero(kek)
        return code, env

    # A replacement in two phases (#187). The new code exists only in the answer that shows it, so
    # the old code's envelope stays until the person has typed the new code back
    # (`confirm_recovery_code`); until then both open the profile. A replacement that was never
    # confirmed (the program killed, the page left) is settled at the next unlock from locked:
    # finished if that unlock used the new code, undone otherwise (`settle_recovery_code`).

    def pending_recovery_code(self) -> dict | None:
        """{"new": id, "old": [ids]} while a replacement waits for its new code to be confirmed."""
        pending = self.meta.get("pending_recovery")
        ids = {e["id"] for e in self.meta["envelopes"]}
        if isinstance(pending, dict) and pending.get("new") in ids and isinstance(pending.get("old"), list):
            return pending
        return None

    def replace_recovery_code(self, params: dict | None = None) -> str:
        """A new recovery code; the old one keeps opening the profile until the new one is confirmed."""
        pending = self.pending_recovery_code()
        if pending:  # an earlier replacement nobody confirmed: its code goes, the confirmed one stays
            self.meta["envelopes"] = [e for e in self.meta["envelopes"] if e["id"] != pending["new"]]
        self.meta.pop("pending_recovery", None)
        old = [e.id for e in self.envelopes("recovery-code")]
        code, env = self._new_recovery_code(params)
        if old:
            self.meta["pending_recovery"] = {"new": env.id, "old": old}
        return code

    def confirm_recovery_code(self) -> None:
        """Finish a replacement: this vault was opened with the new code, so the old one goes."""
        self._require_unlocked()
        pending = self.pending_recovery_code()
        if pending is None:
            # A first recovery code (the profile had none left to replace) is not held back: typed back, it
            # is confirmed by opening the profile. Anything else is not a code waiting to be confirmed.
            if any(e.id == self.opened_with for e in self.envelopes("recovery-code")):
                return
            raise VaultError("not-found", "no recovery code waits to be confirmed")
        if self.opened_with != pending["new"]:
            raise VaultError("wrong-secret", "confirmed with something other than the new recovery code")
        self.meta["envelopes"] = [e for e in self.meta["envelopes"] if e["id"] not in pending["old"]]
        del self.meta["pending_recovery"]

    def settle_recovery_code(self) -> str | None:
        """At an unlock: "finished" when it used the new code, "undone" (the new code goes) otherwise."""
        self._require_unlocked()
        pending = self.pending_recovery_code()
        if pending is None:
            self.meta.pop("pending_recovery", None)  # one whose new envelope is gone: nothing to settle
            return None
        if self.opened_with == pending["new"]:
            self.confirm_recovery_code()
            return "finished"
        self.meta["envelopes"] = [e for e in self.meta["envelopes"] if e["id"] != pending["new"]]
        del self.meta["pending_recovery"]
        return "undone"

    def unlock_recovery_code(self, code: str) -> None:
        self._unlock_with_secret("recovery-code", normalize_recovery_code(code))

    def _unlock_with_secret(self, method: str, secret: bytes) -> None:
        candidates = self.envelopes(method)
        if not candidates:
            raise VaultError("no-such-method")
        for env in candidates:
            kek = stretch(secret, env.data)
            try:
                self._accept(self._open(env, kek), env)
                return
            except VaultError:
                continue
            finally:
                sodium.memzero(kek)
        raise VaultError("wrong-secret")

    # Raw KEK methods (OS keyring, phone, combined) -------------------------------------

    def add_kek(
        self, method: str, kek: bytes | bytearray, data: dict, label: str = "", envelope_id: str | None = None
    ) -> Envelope:
        if method not in ("os-keyring", "phone", "combined"):
            raise VaultError("bad-method")
        return self._add(method, kek, data, label, envelope_id)

    def unlock_kek(self, envelope_id: str, kek: bytes | bytearray) -> None:
        env = next((e for e in self.envelopes() if e.id == envelope_id), None)
        if env is None:
            raise VaultError("not-found")
        self._accept(self._open(env, kek), env)


def stretch_params(params: dict) -> dict:
    """Envelope fields for an Argon2id-derived KEK: parameters plus a fresh salt."""
    return {"kdf": "argon2id13", "ops": params["ops"], "mem": params["mem"], "salt": b64e(sodium.random_bytes(sodium.SALT_BYTES))}


# Bounds for parameters read from disk: an edited file must not make an unlock
# allocate gigabytes or run for hours. (libsodium minimum memory is 8 KiB.)
KDF_LIMITS = {"ops": (1, 10), "mem": (8 * 1024, 1024 * 1024 * 1024)}


def stretch(secret: bytes, fields: dict) -> bytearray:
    try:
        if fields.get("kdf") != "argon2id13":
            raise VaultError("unsupported-kdf")
        ops, mem, salt = fields["ops"], fields["mem"], b64d(fields["salt"])
        for name, value in (("ops", ops), ("mem", mem)):
            low, high = KDF_LIMITS[name]
            if type(value) is not int or not low <= value <= high:
                raise VaultError("damaged-envelope", f"{name} out of range")
        return sodium.argon2id(secret, salt, ops, mem)
    except (AttributeError, KeyError, TypeError, ValueError, sodium.CryptoError):
        raise VaultError("damaged-envelope") from None


def combined_kek(*keks: bytes | bytearray) -> bytearray:
    """One KEK that needs every input (e.g. password + phone): a policy enforced by cryptography."""
    return kdf(sodium.hash32(CONTEXT + b"combined"), "combined-kek", *keks)
