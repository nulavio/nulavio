"""Unlock Coordinator: one state machine over every unlock method of a profile.

It never switches methods on its own: when the phone cannot answer it lists
the other configured methods and waits for the user. Logs carry states and
error codes only, never secrets. The UI comes in S6.
"""

from __future__ import annotations

import enum
import logging
import time
from collections.abc import Callable

from . import sodium
from .core import Vault, VaultError, combined_kek, stretch
from .phone import PhoneUnlock, phone_part
from .providers import Keyring, unlock_os_keyring

log = logging.getLogger("nulavio.vault")


class State(enum.StrEnum):
    IDLE = "idle"
    PAIRING = "pairing"
    WAITING_FOR_PHONE = "waiting_for_phone"
    WAITING_FOR_BIOMETRIC = "waiting_for_biometric"
    AUTHORIZED = "authorized"
    UNLOCKING = "unlocking"
    UNLOCKED = "unlocked"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEVICE_UNAVAILABLE = "device_unavailable"
    RECOVERY_REQUIRED = "recovery_required"
    ERROR = "error"


class DeviceUnavailable(Exception):
    """The transport could not reach the phone (no network, app closed, out of range)."""


class Transport:
    """Delivers a signed request to the phone. Real transports (QR, local network) arrive in S11."""

    def send(self, request: dict) -> None:
        raise DeviceUnavailable


class Coordinator:
    def __init__(
        self,
        vault: Vault,
        *,
        keyring: Keyring | None = None,
        phone: PhoneUnlock | None = None,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.time,
        repair_metadata: bool = False,
    ):
        self.vault = vault
        self.keyring = keyring
        self.phone = phone
        self.transport = transport or Transport()
        self.clock = clock
        self.repair_metadata = repair_metadata
        self.state = State.UNLOCKED if vault.unlocked else State.IDLE
        self.error: str | None = None
        self.alternatives: list[dict] = []
        self.history: list[State] = [self.state]
        self._req_id: str | None = None
        self._expiry = 0
        self._password_kek: bytearray | None = None

    # -- methods -----------------------------------------------------------------

    def methods(self) -> list[dict]:
        """Configured methods, each with whether it can be tried right now."""
        out = []
        for env in self.vault.envelopes():
            usable, reason = True, ""
            if env.method == "os-keyring" and not (self.keyring and self.keyring.available()):
                usable, reason = False, "keyring-unavailable"
            if phone_part(env) is not None and self.phone is None:
                usable, reason = False, "phone-unavailable"
            out.append({"envelope": env.id, "method": env.method, "label": env.label, "usable": usable, "reason": reason})
        return out

    def _offer_alternatives(self, failed_envelope: str | None, failed_method: str | None = None) -> None:
        self.alternatives = [
            m for m in self.methods() if m["usable"] and m["envelope"] != failed_envelope and m["method"] != failed_method
        ]

    def _unavailable_state(self) -> State:
        """Another everyday method left: device_unavailable. Only the recovery code (or nothing): recovery_required."""
        everyday = [m for m in self.alternatives if m["method"] != "recovery-code"]
        return State.DEVICE_UNAVAILABLE if everyday else State.RECOVERY_REQUIRED

    def _set(self, state: State, error: str | None = None) -> None:
        self.state, self.error = state, error
        self.history.append(state)
        log.info("unlock state=%s error=%s", state.value, error or "-")

    # -- local methods -------------------------------------------------------------

    def _local(self, method: str, attempt: Callable[[], None]) -> State:
        self._reset_pending()
        self._set(State.UNLOCKING)
        try:
            attempt()
        except VaultError as exc:
            self._fail(exc.code, None, method)
            return self.state
        return self._finish()

    def unlock_password(self, password: str) -> State:
        return self._local("password", lambda: self.vault.unlock_password(password))

    def unlock_recovery_code(self, code: str) -> State:
        return self._local("recovery-code", lambda: self.vault.unlock_recovery_code(code))

    def unlock_keyring(self) -> State:
        if self.keyring is None:
            self._fail("keyring-unavailable", None, "os-keyring")
            return self.state
        return self._local("os-keyring", lambda: unlock_os_keyring(self.vault, self.keyring))

    # -- phone ---------------------------------------------------------------------

    def start_phone(self, envelope_id: str, profile_name: str, password: str | None = None) -> dict | None:
        """Send a request to the phone. For a password + phone envelope, the password is stretched first."""
        self._reset_pending()
        if self.phone is None:
            self._fail("phone-unavailable", envelope_id)
            return None
        env = next((e for e in self.vault.envelopes() if e.id == envelope_id), None)
        if env is None or phone_part(env) is None:
            self._fail("unpaired", envelope_id)
            return None
        try:
            if env.method == "combined":
                if not password:
                    raise VaultError("password-required")
                self._password_kek = stretch(password.encode(), env.data.get("password") or {})
            request = self.phone.request(self.vault, envelope_id, profile_name)
        except VaultError as exc:
            self._reset_pending()
            self._fail(exc.code, envelope_id)
            return None
        self._req_id, self._expiry = request["r"]["req_id"], request["r"]["expiry"]
        self._set(State.WAITING_FOR_PHONE)
        try:
            self.transport.send(request)
        except DeviceUnavailable:
            self.phone.cancel(self._req_id)
            self._reset_pending()
            self._offer_alternatives(envelope_id)
            self._set(self._unavailable_state(), "device-unavailable")
            return None
        return request

    def phone_acknowledged(self) -> None:
        if self.state is State.WAITING_FOR_PHONE:
            self._set(State.WAITING_FOR_BIOMETRIC)

    def receive(self, response: dict) -> State:
        if self.state not in (State.WAITING_FOR_PHONE, State.WAITING_FOR_BIOMETRIC) or response.get("req_id") != self._req_id:
            log.info("unlock response ignored (state=%s)", self.state.value)
            return self.state
        try:
            env, kek = self.phone.accept(response, self.vault.profile_id)
        except VaultError as exc:
            if exc.code in ("bad-signature", "unpaired"):
                # Not from the paired phone: it must not cancel the user's request. Keep waiting.
                log.info("unlock response ignored (%s)", exc.code)
                return self.state
            self.phone.cancel(self._req_id)
            self._reset_pending()
            if exc.code in ("declined", "expired"):
                self._offer_alternatives(None)
                self._set(State.CANCELLED if exc.code == "declined" else State.TIMEOUT, exc.code)
            else:
                self._fail(exc.code, None)
            return self.state
        self._set(State.AUTHORIZED)
        self._set(State.UNLOCKING)
        try:
            if env.method == "combined":
                full = combined_kek(self._password_kek, kek)
                sodium.memzero(kek)
                kek = full
            self.vault.unlock_kek(env.id, kek)
        except VaultError as exc:
            self._fail(exc.code, env.id)
            return self.state
        finally:
            sodium.memzero(kek)
            self._reset_pending()
        return self._finish()

    def tick(self) -> State:
        """Call periodically: expires a request the phone never answered."""
        if self.state in (State.WAITING_FOR_PHONE, State.WAITING_FOR_BIOMETRIC) and self.clock() > self._expiry:
            self.phone.cancel(self._req_id)
            self._reset_pending()
            self._offer_alternatives(None)
            self._set(State.TIMEOUT, "expired")
        return self.state

    def cancel(self) -> State:
        if self.state in (State.WAITING_FOR_PHONE, State.WAITING_FOR_BIOMETRIC):
            self.phone.cancel(self._req_id)
            self._reset_pending()
            self._offer_alternatives(None)
            self._set(State.CANCELLED, "cancelled")
        return self.state

    # -- end states ----------------------------------------------------------------

    def _finish(self) -> State:
        if self.vault.tampered:
            if not self.repair_metadata:
                self.vault.lock()
                self._set(State.ERROR, "metadata-tampered")
                return self.state
            self.vault.save()  # the user reviewed the methods and accepted them: sign again
            self.vault.tampered = False
        self.alternatives = []
        self._set(State.UNLOCKED)
        return self.state

    def _fail(self, code: str, failed_envelope: str | None, failed_method: str | None = None) -> None:
        self._offer_alternatives(failed_envelope, failed_method)
        if code in ("keyring-unavailable", "keyring-missing", "phone-unavailable", "biometric-unavailable", "device-locked"):
            self._set(self._unavailable_state(), code)
        else:
            self._set(State.ERROR, code)

    def _reset_pending(self) -> None:
        sodium.memzero(self._password_kek)
        self._password_kek = None
        self._req_id = None

    def lock(self) -> State:
        self.cancel()
        self.vault.lock()
        self._set(State.IDLE)
        return self.state


__all__ = ["Coordinator", "DeviceUnavailable", "State", "Transport"]
