"""Local-network link to the Nulavio Companion (ADR 0005, transport amendment 2026-10-27).

The phone listens for one operation and announces itself over mDNS under a
name derived from that operation; the desktop resolves exactly that name
through Avahi and connects out, so the desktop never needs an incoming port.
The link adds no trust: everything the desktop accepts is authenticated by
protocol nv1 (vault/phone.py). Messages are canonical JSON, one per line.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Callable

from . import sodium
from .core import canonical

SERVICE_TYPE = "_nulavio-nv1._tcp"
MAX_LINE = 16 * 1024
CONNECT_TIMEOUT = 3.0
Resolver = Callable[[str], "tuple[str, int] | None"]


class LinkError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def instance_name(kind: str, operation_id: str) -> str:
    """mDNS instance name for one pairing ("p", invite id) or unlock ("u", request id)."""
    if kind not in ("p", "u"):
        raise ValueError(kind)
    digest = sodium.hash32(operation_id.encode())
    return f"nv1-{kind}-" + base64.b32encode(digest).decode().lower()[:16]


def _busctl() -> str | None:
    """systemd's busctl from the system directories; NULAVIO_BUSCTL names a stand-in (tests, like NULAVIO_SECRET_TOOL)."""
    return os.environ.get("NULAVIO_BUSCTL") or shutil.which("busctl", path="/usr/bin:/bin")


def avahi_available() -> bool:
    busctl = _busctl()
    if not busctl:
        return False
    probe = subprocess.run(
        [busctl, "--system", "--json=short", "call", "org.freedesktop.Avahi", "/",
         "org.freedesktop.Avahi.Server", "GetVersionString"],
        capture_output=True, text=True, timeout=5, check=False,
    )  # fmt: skip
    return probe.returncode == 0


def avahi_resolve(name: str) -> tuple[str, int] | None:
    """IPv4 address and port of `name` on the local network, through Avahi on the system bus."""
    busctl = _busctl()
    if not busctl:
        return None
    result = subprocess.run(
        # "--": the interface index -1 (any) would otherwise read as an option.
        [busctl, "--system", "--json=short", "--timeout=6", "--", "call", "org.freedesktop.Avahi", "/",
         "org.freedesktop.Avahi.Server", "ResolveService", "iisssiu",
         "-1", "0", name, SERVICE_TYPE, "local", "0", "0"],
        capture_output=True, text=True, timeout=10, check=False,
    )  # fmt: skip
    if result.returncode != 0:
        return None  # not announced (yet), or Avahi timed out
    try:
        data = json.loads(result.stdout)["data"]
        address, port = str(data[7]), int(data[8])
        socket.inet_aton(address)
    except (ValueError, KeyError, IndexError, TypeError, OSError):
        return None
    return address, port


class Channel:
    """One TCP connection carrying canonical JSON lines."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self._buffer = bytearray()

    def send(self, message: dict) -> None:
        self.sock.sendall(canonical(message) + b"\n")

    def recv(self, deadline: float) -> dict:
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LinkError("timeout")
            self.sock.settimeout(min(remaining, 1.0))
            try:
                chunk = self.sock.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                raise LinkError("closed") from None
            if not chunk:
                raise LinkError("closed")
            self._buffer += chunk
            if len(self._buffer) > MAX_LINE and b"\n" not in self._buffer:
                raise LinkError("too-large")
        line, _, rest = bytes(self._buffer).partition(b"\n")
        self._buffer = bytearray(rest)
        try:
            message = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            raise LinkError("bad-message") from None
        if not isinstance(message, dict) or not isinstance(message.get("t"), str):
            raise LinkError("bad-message")
        return message

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def connect(name: str, deadline: float, resolver: Resolver = avahi_resolve, cancelled: Callable[[], bool] = lambda: False,
            interval: float = 1.0) -> Channel:  # fmt: skip
    """Resolve the phone's announcement and connect, until the deadline (monotonic) or cancellation."""
    while time.monotonic() < deadline and not cancelled():
        found = resolver(name)
        if found:
            try:
                sock = socket.create_connection(found, timeout=CONNECT_TIMEOUT)
            except OSError:
                pass
            else:
                return Channel(sock)
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    raise LinkError("cancelled" if cancelled() else "unreachable")
