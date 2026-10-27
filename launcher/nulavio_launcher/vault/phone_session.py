"""Phone pairing and "Unlock with phone" sessions (ADR 0005, S11).

Each operation runs in a short-lived helper process (`nulavio vault
phone-session`, request on stdin): it holds the operation's secrets in memory
only, shows nothing itself, and is driven by the browser through a private
UNIX socket in the runtime folder (status, the user's answer to "do the 6
digits match?", cancel). The helper's first line on stdout is what the
browser shows: the QR payload, or an error. Nothing secret is written to disk;
the pairing QR carries the invite's secret and is meant for that screen only.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

from .. import paths, profile
from ..log import event as log_event
from . import link, profiles
from .coordinator import Coordinator, State, Transport
from .core import VaultError, b64e, canonical
from .phone import DesktopIdentity, Pairing, PhoneUnlock, ProtocolError, add_phone, phone_part

REQUEST_LIMIT = 8192
LINGER = 30  # seconds the final state stays readable
CONTROL_LIMIT = 1024


def sessions_dir() -> Path:
    base = paths.runtime_home() or paths.cache_home() / "run"
    return paths.ensure_private_dir(base / "phone")


def identity_path() -> Path:
    return paths.data_home() / "vault" / "desktop-identity.json"


def desktop_name() -> str:
    return (socket.gethostname().split(".")[0] or "Nulavio")[:40]


class _Shown(Transport):
    """The request reaches the phone as a QR on the desktop's screen; the phone answers over the link."""

    def send(self, request: dict) -> None:
        return None


class Session:
    def __init__(self, kind: str):
        self.kind = kind
        self.id = b64e(secrets.token_bytes(16))
        self.state = "waiting-for-phone"
        self.error: str | None = None
        self.sas: str | None = None
        self.phone_name: str | None = None
        self.decision: bool | None = None
        self.decided = threading.Event()
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.done = threading.Event()

    def set(self, state: str, **fields) -> None:
        with self.lock:
            self.state = state
            for key, value in fields.items():
                setattr(self, key, value)

    def status(self) -> dict:
        with self.lock:
            out = {"session": self.id, "kind": self.kind, "state": self.state}
            if self.error:
                out["error"] = self.error
            if self.sas and self.state in ("compare", "waiting-for-you"):
                out["sas"] = self.sas
            if self.phone_name:
                out["phone"] = self.phone_name
            return out

    def handle(self, request: dict) -> dict:
        action = request.get("action")
        if action == "status":
            return self.status()
        if action == "confirm" and self.kind == "pair":
            if self.state not in ("compare", "waiting-for-you"):
                return {"error": "bad-state"}
            self.decision = bool(request.get("match"))
            self.decided.set()
            return self.status()
        if action == "cancel":
            self.cancelled.set()
            self.decided.set()
            return {"cancelled": True}
        return {"error": "bad-request"}


def socket_path(session_id: str) -> Path:
    if not session_id or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in session_id):
        raise VaultError("bad-request", "session")
    return sessions_dir() / f"{session_id}.sock"


def _serve(session: Session, path: Path) -> socket.socket:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        server.bind(str(path))
    finally:
        os.umask(old)
    server.listen(4)

    def loop() -> None:
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                try:
                    raw = conn.recv(CONTROL_LIMIT)
                    reply = session.handle(json.loads(raw)) if raw else {"error": "bad-request"}
                except (OSError, ValueError, TypeError, AttributeError):
                    reply = {"error": "bad-request"}
                try:
                    conn.sendall(json.dumps(reply).encode() + b"\n")
                except OSError:
                    pass

    threading.Thread(target=loop, daemon=True).start()
    return server


def control(session_id: str, request: dict, timeout: float = 5.0) -> dict:
    """The browser's side: one request to a running session."""
    path = socket_path(session_id)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect(str(path))
            conn.sendall(json.dumps(request).encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
    except OSError:
        return {"session": session_id, "state": "gone"}
    try:
        return json.loads(data)
    except ValueError:
        return {"error": "failed"}


# -- the two operations ------------------------------------------------------------------


def _deadline_for(expiry: int) -> float:
    return time.monotonic() + max(0.0, expiry - time.time())


def _send_quietly(channel: link.Channel | None, message: dict) -> None:
    if channel is not None:
        try:
            channel.send(message)
        except OSError:
            pass


def _answer(channel: link.Channel, session: Session, deadline: float) -> dict:
    """The phone's next message; ends early when the user answers "no" or cancels on the desktop."""
    while True:
        if session.cancelled.is_set():
            raise link.LinkError("cancelled")
        if session.decided.is_set() and not session.decision:
            raise ProtocolError("sas-mismatch")
        try:
            return channel.recv(min(deadline, time.monotonic() + 0.5))
        except link.LinkError as exc:
            if exc.code != "timeout" or time.monotonic() >= deadline:
                raise


def pair(session: Session, request: dict, emit, resolver: link.Resolver = link.avahi_resolve) -> None:
    """Pair a phone with a protected profile (needs the profile's current secret: adding a method needs its key)."""
    from .cli import _reauth  # the same re-authentication as every other protection change

    prof = profile.Profile(name=Path(request["path"]).name, path=Path(request["path"]))
    box = profiles.container(prof)
    vault = box.load_vault()
    channel = None
    pairing = None
    try:
        _reauth(vault, str(request.get("current") or ""))
        methods = {e.method for e in vault.envelopes()}
        if "recovery-code" not in methods or not methods & {"password", "os-keyring", "phone", "combined"}:
            # ADR 0005: phone unlock only next to a recovery code and one other method.
            raise VaultError("needs-two-methods")
        pairing = Pairing(DesktopIdentity.load_or_create(identity_path()), desktop_name())
        emit({"session": session.id, "qr": canonical(pairing.invite()).decode(), "expiry": pairing.expiry})
        deadline = _deadline_for(pairing.expiry)
        channel = link.connect(link.instance_name("p", pairing.invite_id), deadline, resolver, session.cancelled.is_set)
        hello = channel.recv(deadline)
        if hello.get("t") != "hello":
            raise ProtocolError("bad-message")
        accept = pairing.on_hello({k: v for k, v in hello.items() if k != "t"})
        channel.send({"t": "accept", **accept})
        session.set("compare", sas=pairing.sas)
        answer = _answer(channel, session, deadline)
        if answer.get("t") == "cancel":
            raise ProtocolError("sas-mismatch")  # the user said on the phone that the digits differ
        if answer.get("t") != "confirm":
            raise ProtocolError("bad-message")
        session.set("waiting-for-you")
        if not session.decided.wait(max(0.0, deadline - time.monotonic())):
            raise ProtocolError("expired")
        if session.cancelled.is_set():
            raise link.LinkError("cancelled")
        phone = pairing.complete({k: v for k, v in answer.items() if k != "t"}, bool(session.decision))
        add_phone(vault, phone)
        vault.save()
        box.record_generation(vault)
        _send_quietly(channel, {"t": "paired"})
        session.set("paired", phone_name=phone.name)
        log_event("vault.phone.paired", profile=prof.name)
    except (VaultError, link.LinkError) as exc:
        code = exc.code
        if session.cancelled.is_set():
            code = "cancelled"
        _send_quietly(channel, {"t": "error", "code": code})
        session.set("cancelled" if code == "cancelled" else "failed", error=None if code == "cancelled" else code)
        if session.state == "failed":
            log_event("vault.phone.pair-failed", profile=prof.name, code=code)
        if pairing is None:
            emit({"error": code})
    finally:
        if pairing is not None:
            pairing.cancel()
        vault.lock()
        if channel is not None:
            channel.close()


def unlock(session: Session, request: dict, emit, resolver: link.Resolver = link.avahi_resolve) -> None:
    """Unlock a protected profile with its phone and mount it, like any other method."""
    prof = profile.Profile(name=Path(request["path"]).name, path=Path(request["path"]))
    box = profiles.container(prof)
    vault = box.load_vault()
    path = identity_path()
    if not path.exists():
        emit({"error": "unpaired"})
        return
    coordinator = Coordinator(vault, phone=PhoneUnlock(DesktopIdentity.load_or_create(path), desktop_name()),
                              transport=_Shown())  # fmt: skip
    envelope = request.get("envelope") or next((e.id for e in vault.envelopes() if phone_part(e) is not None), None)
    signed = coordinator.start_phone(str(envelope or ""), prof.name, password=request.get("password"))
    if signed is None:
        emit({"error": coordinator.error or "failed"})
        return
    req_id, expiry = signed["r"]["req_id"], signed["r"]["expiry"]
    emit({"session": session.id, "qr": canonical(signed).decode(), "expiry": expiry})
    deadline = _deadline_for(expiry)
    name = link.instance_name("u", req_id)
    outcome = None
    try:
        while coordinator.state in (State.WAITING_FOR_PHONE, State.WAITING_FOR_BIOMETRIC):
            try:
                channel = link.connect(name, deadline, resolver, session.cancelled.is_set)
            except link.LinkError as exc:
                outcome = exc.code  # "cancelled" or "unreachable"
                coordinator.cancel()
                break
            try:
                coordinator.phone_acknowledged()
                session.set("approve-on-phone")  # the phone has the request; the user decides there
                message = channel.recv(deadline)
                if message.get("t") != "response":
                    raise link.LinkError("bad-message")
                state = coordinator.receive({k: v for k, v in message.items() if k != "t"})
                if state is State.UNLOCKED:
                    box.mount(vault, request.get("idle_minutes"))
                    _send_quietly(channel, {"t": "ok"})
                elif state in (State.WAITING_FOR_PHONE, State.WAITING_FOR_BIOMETRIC):
                    _send_quietly(channel, {"t": "error", "code": "bad-signature"})  # not the paired phone: keep waiting
                    session.set("waiting-for-phone")
                else:
                    _send_quietly(channel, {"t": "error", "code": coordinator.error or "failed"})
            except link.LinkError:
                pass  # a stranger or a dropped connection: keep waiting for the phone
            finally:
                channel.close()
    except Exception:
        vault.lock()
        raise
    if coordinator.state is not State.UNLOCKED and outcome == "unreachable":
        session.set("unreachable")
        vault.lock()
        return
    if coordinator.state is State.UNLOCKED:
        vault.lock()  # the volume stays mounted; the key is not needed in this process any more
        if request.get("autolock", True):
            from .cli import spawn_autolock

            spawn_autolock(prof)
        session.set("unlocked")
        log_event("vault.unlock", profile=prof.name, method="phone")
    else:
        code = coordinator.error or "failed"
        state = {State.CANCELLED: "declined" if code == "declined" else "cancelled", State.TIMEOUT: "expired"}.get(
            coordinator.state, "failed"
        )
        session.set(state, error=code if state == "failed" else None)
        vault.lock()


# -- the helper process --------------------------------------------------------------------


def main() -> int:
    """`nulavio vault phone-session`: one request on stdin; first stdout line for the browser; then serve."""
    raw = sys.stdin.read(REQUEST_LIMIT + 1)
    out = sys.stdout

    def emit(message: dict) -> None:
        nonlocal out
        if out is not None:
            out.write(json.dumps(message) + "\n")
            out.flush()
            out.close()
            out = None

    try:
        request = json.loads(raw) if len(raw) <= REQUEST_LIMIT else None
        if not isinstance(request, dict) or request.get("kind") not in ("pair", "unlock"):
            raise VaultError("bad-request")
        target = request.get("path")
        if not isinstance(target, str) or not target.startswith("/"):
            raise VaultError("bad-request", "path")
        session = Session(request["kind"])
        sock = socket_path(session.id)
        server = _serve(session, sock)
    except (VaultError, OSError, ValueError) as exc:
        emit({"error": getattr(exc, "code", "failed")})
        return 1
    try:
        (pair if session.kind == "pair" else unlock)(session, request, emit)
    except (VaultError, OSError) as exc:
        session.set("failed", error=getattr(exc, "code", "failed"))
        emit({"error": getattr(exc, "code", "failed")})
    finally:
        request.pop("current", None)
        request.pop("password", None)
        emit({"error": "failed"})  # no-op when the browser already has its answer
        time.sleep(LINGER)
        server.close()
        sock.unlink(missing_ok=True)
    return 0
