"""Platform key providers for the Vault (ADR 0006).

OS keyring: a random KEK kept in the Secret Service (KWallet or GNOME Keyring)
through `secret-tool` (libsecret). The KEK goes over stdin, never argv; the
lookup attributes identify the profile and envelope. Same-user processes can
read an unlocked keyring, so this method is shown as `os_user_protected`.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess

from . import sodium
from .core import Envelope, Vault, VaultError, new_id

SERVICE = "secret-service"
TIMEOUT = 20  # the keyring may show its own unlock prompt


class Keyring:
    """`secret-tool` wrapper. `executable` and `env` are injectable for tests."""

    def __init__(self, executable: str | None = None, env: dict | None = None):
        self.executable = executable or shutil.which("secret-tool")
        self.env = env

    def available(self) -> bool:
        return bool(self.executable) and os.access(self.executable, os.X_OK)

    def _run(self, args: list[str], data: bytes | None = None) -> subprocess.CompletedProcess:
        if not self.available():
            raise VaultError("keyring-unavailable")
        try:
            return subprocess.run(
                [self.executable, *args], input=data, capture_output=True, timeout=TIMEOUT, env=self.env, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VaultError("keyring-unavailable", type(exc).__name__) from None

    @staticmethod
    def _attrs(attributes: dict[str, str]) -> list[str]:
        out: list[str] = []
        for key, value in sorted(attributes.items()):
            out += [key, value]
        return out

    def store(self, label: str, attributes: dict[str, str], secret: bytes | bytearray) -> None:
        encoded = base64.b64encode(bytes(secret))
        result = self._run(["store", f"--label={label}", *self._attrs(attributes)], encoded)
        if result.returncode != 0:
            raise VaultError("keyring-store-failed", result.stderr.decode(errors="replace")[:200])

    def lookup(self, attributes: dict[str, str]) -> bytearray | None:
        result = self._run(["lookup", *self._attrs(attributes)])
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            return bytearray(base64.b64decode(result.stdout.strip(), validate=True))
        except ValueError:
            return None

    def clear(self, attributes: dict[str, str]) -> None:
        self._run(["clear", *self._attrs(attributes)])


def keyring_attributes(profile_id: str, envelope_id: str) -> dict[str, str]:
    return {"application": "nulavio", "nulavio-profile": profile_id, "nulavio-envelope": envelope_id}


def add_os_keyring(vault: Vault, keyring: Keyring, label: str = "") -> Envelope:
    """Create a random KEK, store it in the keyring, then write its envelope."""
    envelope_id = new_id()
    attributes = keyring_attributes(vault.profile_id, envelope_id)
    kek = sodium.random_bytes(sodium.KEY_BYTES)
    try:
        keyring.store("Nulavio profile key", attributes, kek)
        stored = keyring.lookup(attributes)
        if stored is None or not sodium.equal(stored, kek):
            keyring.clear(attributes)
            raise VaultError("keyring-store-failed", "read-back mismatch")
        sodium.memzero(stored)
        return vault.add_kek("os-keyring", kek, {"service": SERVICE, "attributes": attributes}, label, envelope_id)
    finally:
        sodium.memzero(kek)


def unlock_os_keyring(vault: Vault, keyring: Keyring) -> None:
    candidates = vault.envelopes("os-keyring")
    if not candidates:
        raise VaultError("no-such-method")
    if not keyring.available():
        raise VaultError("keyring-unavailable")
    for env in candidates:
        attributes = env.data.get("attributes")
        kek = keyring.lookup(attributes) if isinstance(attributes, dict) else None
        if kek is None:
            continue
        try:
            vault.unlock_kek(env.id, kek)
            return
        except VaultError:
            continue
        finally:
            sodium.memzero(kek)
    raise VaultError("keyring-missing")


def remove_os_keyring(vault: Vault, keyring: Keyring, envelope_id: str) -> None:
    env = next((e for e in vault.envelopes("os-keyring") if e.id == envelope_id), None)
    if env is None:
        raise VaultError("not-found")
    vault.remove(envelope_id)
    keyring.clear(env.data["attributes"])
