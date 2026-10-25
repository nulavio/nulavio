"""Minimal Marionette client (stdlib only) for Nulavio test automation.

Marionette is Gecko's built-in remote protocol. Nulavio only enables it for
*disposable test profiles*: the launcher refuses to start a user profile with
remote control flags (see launcher/nulavio_launcher/engine.py).

Wire format: every packet is ``<length>:<json>``. Commands are
``[0, id, name, params]`` and responses are ``[1, id, error, result]``.
"""

from __future__ import annotations

import base64
import json
import socket
import time
from typing import Any


class MarionetteError(RuntimeError):
    """Raised when Marionette returns an error object."""

    def __init__(self, error: dict[str, Any]):
        self.error = error
        super().__init__(f"{error.get('error')}: {error.get('message')}")


class Marionette:
    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = 60.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._next_id = 0
        self._buffer = b""
        self.handshake: dict[str, Any] = {}

    # -- transport -------------------------------------------------------
    def connect(self, retries: int = 60, delay: float = 0.5) -> Marionette:
        last: Exception | None = None
        for _ in range(retries):
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                self.handshake = self._read_packet()
                return self
            except OSError as exc:  # server not up yet
                last = exc
                time.sleep(delay)
        raise ConnectionError(f"Marionette not reachable on {self.host}:{self.port}: {last}")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _read_packet(self) -> Any:
        assert self._sock is not None
        while b":" not in self._buffer:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Marionette closed the connection")
            self._buffer += chunk
        length_raw, rest = self._buffer.split(b":", 1)
        length = int(length_raw)
        while len(rest) < length:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("Marionette closed the connection")
            rest += chunk
        payload, self._buffer = rest[:length], rest[length:]
        return json.loads(payload)

    def send(self, name: str, params: dict[str, Any] | None = None) -> Any:
        assert self._sock is not None, "call connect() first"
        self._next_id += 1
        msg_id = self._next_id
        data = json.dumps([0, msg_id, name, params or {}]).encode()
        self._sock.sendall(str(len(data)).encode() + b":" + data)
        while True:
            packet = self._read_packet()
            if isinstance(packet, list) and packet[0] == 1 and packet[1] == msg_id:
                _, _, error, result = packet
                if error:
                    raise MarionetteError(error)
                return result

    # -- convenience -----------------------------------------------------
    def new_session(self, capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.send("WebDriver:NewSession", {"capabilities": capabilities or {}})

    def navigate(self, url: str) -> None:
        self.send("WebDriver:Navigate", {"url": url})

    def title(self) -> str:
        return self.send("WebDriver:GetTitle")["value"]

    def current_url(self) -> str:
        return self.send("WebDriver:GetCurrentURL")["value"]

    def set_context(self, context: str) -> None:
        self.send("Marionette:SetContext", {"value": context})

    def execute(self, script: str, args: list[Any] | None = None, sandbox: str | None = None) -> Any:
        params: dict[str, Any] = {"script": script, "args": args or []}
        if sandbox:
            params["sandbox"] = sandbox
        return self.send("WebDriver:ExecuteScript", params)["value"]

    def execute_async(self, script: str, args: list[Any] | None = None) -> Any:
        return self.send("WebDriver:ExecuteAsyncScript", {"script": script, "args": args or []})["value"]

    def chrome(self, script: str, args: list[Any] | None = None) -> Any:
        """Run privileged JS (needs --remote-allow-system-access, test-only)."""
        self.set_context("chrome")
        try:
            return self.execute(script, args)
        finally:
            self.set_context("content")

    def new_tab(self) -> str:
        # Identify the new tab by diffing handles: Mozilla's official 158 build
        # was observed returning the *current* handle from NewWindow, and the
        # handle list can lag briefly behind the response.
        before = set(self.window_handles())
        reported = self.send("WebDriver:NewWindow", {"type": "tab", "focus": True}).get("handle")
        deadline = time.monotonic() + 10
        created: list[str] = []
        while time.monotonic() < deadline:
            created = [h for h in self.window_handles() if h not in before]
            if reported in created or len(created) == 1:
                break
            if len(created) > 1:
                break  # an extension opened its own tab at the same time
            time.sleep(0.2)
        if reported in created:
            return reported
        if len(created) == 1:
            return created[0]
        for handle in created:  # several new tabs: ours is the blank one
            self.switch_to(handle)
            if self.current_url() == "about:blank":
                return handle
        raise MarionetteError({"error": "no such window", "message": "could not identify the new tab"})

    def window_handles(self) -> list[str]:
        return self.send("WebDriver:GetWindowHandles")

    def switch_to(self, handle: str) -> None:
        # focus=False: Mozilla's official headless build was observed hanging on focus.
        self.send("WebDriver:SwitchToWindow", {"handle": handle, "focus": False})

    def install_addon(self, path: str, temporary: bool = False) -> str:
        return self.send("Addon:Install", {"path": path, "temporary": temporary})["value"]

    def screenshot_png(self) -> bytes:
        return base64.b64decode(self.send("WebDriver:TakeScreenshot", {"full": False})["value"])

    def quit(self) -> None:
        try:
            self.send("Marionette:Quit", {"flags": ["eForceQuit"]})
        except (ConnectionError, OSError, MarionetteError):
            pass
        finally:
            self.close()
