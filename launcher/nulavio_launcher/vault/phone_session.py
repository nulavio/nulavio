"""Phone pairing and "Unlock with phone" sessions (ADR 0005, S11).

Each operation runs in a short-lived helper process (`nulavio vault
phone-session`, request on stdin): it holds the operation's secrets in memory
only, shows nothing itself, and is driven by the browser through a private
UNIX socket in the runtime folder (status, the user's answer to "do the 6
digits match?", cancel). The helper's first line on stdout is what the
browser shows: the QR payload, or an error. Nothing secret is written to disk;
the pairing QR carries the invite's secret and is meant for that screen only.

A profile has one pending phone unlock at a time, across helper processes
(#669, U-T19): its folder of encrypted files (`P.vault/`) records the session id
of the latest request (`phone-request`, 0600). A new request replaces that
record and tells the earlier helper it was replaced, which stops once its own
record, read, names another session; a helper opens the profile only while the record still names its
own session, checked under the profile's state lock just before the volume is
mounted.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import secrets
import socket
import stat
import sys
import threading
import time
from pathlib import Path

from .. import paths, profile
from ..log import event as log_event
from . import link, profiles, storage
from .coordinator import Coordinator, State, Transport
from .core import VaultError, b64e, canonical
from .phone import DesktopIdentity, Pairing, PhoneUnlock, ProtocolError, add_phone, phone_part

REQUEST_LIMIT = 8192
LINGER = 30  # seconds the final state stays readable
CONTROL_LIMIT = 1024
REQUEST_RECORD = "phone-request"  # in P.vault/: the session id of the profile's one pending phone unlock (#669)
REQUEST_LOCK_WAIT = 5.0  # seconds to wait for the record's lock; it is held only to read or write that small file


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
        self.recovery_code: str | None = None
        self.settle_warning: str | None = None
        self.warning: str | None = None  # a change saved but not recorded inside the profile (#177)
        self.decision: bool | None = None
        self.decided = threading.Event()
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.superseded = None  # unlock: whether this profile's record now names another request (#669)

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
            if self.warning and self.state == "paired":
                out["warning"] = self.warning
            if self.recovery_code:
                out["recovery_code"] = self.recovery_code
            if self.settle_warning and self.state == "unlocked":
                out["warning"] = self.settle_warning  # what the unlock did with a replacement left unfinished
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
        if action == "replaced":
            # Believed only when this helper's own profile agrees: a copy of the profile's folder carries the record
            # naming this session, and a request on that copy must not end this one (#823 review). Agreeing means
            # a record read and naming another session: one missing or unreadable for a moment proves nothing.
            if self.superseded is None or not self.superseded():
                return {"error": "bad-state"}
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


# -- one pending phone request per profile (#669) -----------------------------------------


@contextlib.contextmanager
def _request_lock(box: storage.Container, wait: float | None = None):
    """A lock of its own for the record, never the state lock: a rekey or a mount holds that one for long, and a
    new request must show its QR before the browser gives up on the helper. Waited for `wait` seconds at most
    (REQUEST_LOCK_WAIT), then BlockingIOError: a helper stopped while holding it holds up no one for ever."""
    fd = os.open(box.root / f"{REQUEST_RECORD}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():  # I9: not a FIFO, not someone else's file
            raise paths.UnsafePathError(f"not a private regular file: {REQUEST_RECORD}.lock")
        if stat.S_IMODE(st.st_mode) & ~paths.PRIVATE_FILE_MODE:
            os.fchmod(fd, paths.PRIVATE_FILE_MODE)  # I9: one put back with a broader mode is made 0600
        deadline = time.monotonic() + (REQUEST_LOCK_WAIT if wait is None else wait)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # releases the lock


def _recorded(box: storage.Container) -> str:
    try:
        return paths.read_private_file(box.root / REQUEST_RECORD).decode("ascii").strip()
    except FileNotFoundError:
        return ""


def claim_request(box: storage.Container, session_id: str) -> str:
    """Record `session_id` as the profile's pending phone request; return the session it replaces ("" if none)."""
    with _request_lock(box):
        try:
            previous = _recorded(box)
        except (OSError, UnicodeDecodeError, paths.UnsafePathError):
            previous = ""  # a damaged record names no session; it is replaced below
        paths.write_private_file(box.root / REQUEST_RECORD, session_id)
    return previous


def is_replaced(box: storage.Container, session_id: str) -> bool:
    """Whether the profile's record, read, names another session: what a "replaced" notice needs to be believed.
    Briefly, for the helper's control loop; a record that cannot be read or the lock not had in time is "no"."""
    try:
        with _request_lock(box, wait=1.0):
            recorded = _recorded(box)
    except (OSError, UnicodeDecodeError, paths.UnsafePathError):
        return False
    return bool(recorded) and not secrets.compare_digest(recorded, session_id)


def is_current_request(box: storage.Container, session_id: str) -> bool:
    """Whether the profile's record still names this session. Anything else (another session, no record, one that
    cannot be read) means a later request took its place: the profile is not opened for this one."""
    try:
        with _request_lock(box):
            return secrets.compare_digest(_recorded(box), session_id)
    except (OSError, UnicodeDecodeError, paths.UnsafePathError):
        return False


def _end_replaced(previous: str, session_id: str) -> None:
    """Tell the helper of the replaced request, so it stops now and its page says so; it checks its own record
    first. Only a courtesy: that helper cannot open the profile any more anyway (is_current_request)."""
    if not previous or previous == session_id:
        return
    try:
        control(previous, {"action": "replaced"}, timeout=2.0)
    except (VaultError, OSError, paths.UnsafePathError):
        pass  # not a session id, or the runtime folder cannot be used: nothing to tell, the new request goes on


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
        from .cli import _record

        with box.recording(vault) as record:  # the volume first, locked or not (cli._change)
            add_phone(vault, phone)
            vault.save()
            unrecorded = _record(record)  # saved: the phone is paired, recorded or not
        _send_quietly(channel, {"t": "paired"})
        session.set("paired", phone_name=phone.name, warning="not-recorded" if unrecorded else None)
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
    session.superseded = lambda: is_replaced(box, session.id)  # before the claim: a later one may tell at once
    try:
        previous = claim_request(box, session.id)  # this request is now the profile's only pending one
    except (OSError, paths.UnsafePathError):
        coordinator.cancel()  # wipes the request's session key and a combined unlock's password key (I8)
        vault.lock()
        emit({"error": "storage-failed"})
        return
    emit({"session": session.id, "qr": canonical(signed).decode(), "expiry": expiry})
    _end_replaced(previous, session.id)
    deadline = _deadline_for(expiry)
    name = link.instance_name("u", req_id)

    def stopped() -> bool:
        # The record first, the cancel last: a cancel that comes while the record is read still counts.
        return not is_current_request(box, session.id) or session.cancelled.is_set()

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
                # Ends early on a cancel here: an approval on the phone after that must open nothing.
                message = _answer(channel, session, deadline)
                if session.cancelled.is_set():
                    raise link.LinkError("cancelled")
                if message.get("t") != "response":
                    raise link.LinkError("bad-message")
                state = coordinator.receive({k: v for k, v in message.items() if k != "t"})
                if state is State.UNLOCKED:
                    try:
                        # A cancel while the mount waits for the state lock (the auto-lock watcher closing the
                        # profile, another unlock) opens nothing either (#783 review, round 3). Nor does a request
                        # that a later one replaced (#669): asked under the state lock, right before the mount, so
                        # a request that starts after this check comes after an unlock that already happened.
                        box.mount(vault, request.get("idle_minutes"), cancelled=stopped)
                    except storage.StorageError as exc:
                        if exc.code != "cancelled":
                            raise
                        outcome = "cancelled"
                        _send_quietly(channel, {"t": "error", "code": "cancelled"})
                    else:
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
    if outcome == "cancelled" and coordinator.state is State.UNLOCKED:  # approved, then cancelled before the mount
        session.set("cancelled")
        vault.lock()
        return
    if coordinator.state is not State.UNLOCKED and outcome == "unreachable":
        session.set("unreachable")
        vault.lock()
        return
    if coordinator.state is State.UNLOCKED:
        vault.lock()  # the volume stays mounted; the key is not needed in this process any more
        if request.get("autolock", True):
            from .cli import spawn_autolock

            try:
                spawn_autolock(prof)
            except OSError:
                profiles.lock(prof)  # no watcher would lock it again: fail closed, as the helper's unlock does (audit V7)
                raise
        session.set("unlocked", recovery_code=vault.settled, settle_warning=vault.settle_warning)
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
