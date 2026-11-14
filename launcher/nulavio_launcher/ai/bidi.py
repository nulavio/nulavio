"""WebDriver BiDi client for the engine's remote agent (https://w3c.github.io/webdriver-bidi/).

One reader thread routes command results by id; callers block with a timeout
and an optional cancel event. Remote values are converted to plain Python
values, with DOM nodes kept as `{"sharedId": ...}` handles.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import queue
import threading
import time
from collections.abc import Callable

from .websocket import ConnectionClosed, WebSocket, WebSocketError


class BidiError(RuntimeError):
    def __init__(self, error: str, message: str = ""):
        super().__init__(f"{error}: {message}" if message else error)
        self.error = error


class Cancelled(BidiError):
    def __init__(self):
        super().__init__("cancelled")


class Bidi:
    def __init__(self, port: int, timeout: float = 10.0):
        self.ws = WebSocket("127.0.0.1", port, "/session", timeout=timeout)
        self._ids = itertools.count(1)
        self._lock = threading.Condition()
        self._results: dict[int, dict] = {}
        self._closed: str | None = None
        self._seq = 0
        self.events: list[tuple[int, dict]] = []
        # Events with a handler (on()) go to it, in order, on a thread of their own: a handler may send
        # commands, whose results this reader delivers. They are not kept in `events`.
        self._handlers: dict[str, Callable[[dict], None]] = {}
        self._handled: queue.SimpleQueue[tuple[Callable[[dict], None], dict] | None] = queue.SimpleQueue()
        self._reader = threading.Thread(target=self._read_loop, name="bidi-reader", daemon=True)
        self._reader.start()
        threading.Thread(target=self._handle_loop, name="bidi-handler", daemon=True).start()
        # Page dialogs (alert, confirm, prompt) stay open for the agent to read and answer
        # with the `dialog` tool; leaving a page is never held up by "are you sure?".
        prompts = {"default": "ignore", "beforeUnload": "accept"}
        self.session = self.command(
            "session.new", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": False, "unhandledPromptBehavior": prompts}}}
        )

    def _read_loop(self) -> None:
        try:
            while True:
                message = json.loads(self.ws.recv_text())
                with self._lock:
                    if "id" in message and message.get("type") in ("success", "error"):
                        self._results[message["id"]] = message
                    elif message.get("type") == "event":
                        handler = self._handlers.get(message.get("method", ""))
                        if handler is not None:
                            self._handled.put((handler, message.get("params", {})))
                        else:
                            self._seq += 1
                            self.events.append((self._seq, message))
                            del self.events[:-500]
                    self._lock.notify_all()
        except (ConnectionClosed, WebSocketError, OSError, ValueError) as exc:
            with self._lock:
                self._closed = str(exc) or "closed"
                self._lock.notify_all()
        self._handled.put(None)

    def _handle_loop(self) -> None:
        while (item := self._handled.get()) is not None:
            handler, params = item
            with contextlib.suppress(Exception):  # a handler's failure must not stop the ones after it
                handler(params)

    def on(self, method: str, handler: Callable[[dict], None]) -> None:
        """Call `handler(params)` for each `method` event from now on, instead of keeping it in `events`."""
        with self._lock:
            self._handlers[method] = handler

    def command(self, method: str, params: dict, timeout: float = 30.0, cancel: threading.Event | None = None,
                until: tuple[str, str, int] | None = None) -> dict | None:  # fmt: skip
        """Send a command and wait for its result. `until=(event, context, mark)`: stop waiting (return None)
        if that event arrives first, e.g. a page dialog that holds the command until it is answered."""
        command_id = next(self._ids)
        with self._lock:
            if self._closed:
                raise BidiError("disconnected", self._closed)
        self.ws.send_text(json.dumps({"id": command_id, "method": method, "params": params}))
        deadline = time.monotonic() + timeout
        with self._lock:
            while command_id not in self._results:
                if self._closed:
                    raise BidiError("disconnected", self._closed)
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if until is not None and any(
                    seq > until[2] and e.get("method") == until[0] and e.get("params", {}).get("context") == until[1]
                    for seq, e in self.events
                ):
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BidiError("timeout", f"{method} took longer than {timeout:.0f} s")
                self._lock.wait(min(remaining, 0.2))
            message = self._results.pop(command_id)
        if message["type"] == "error":
            raise BidiError(message.get("error", "unknown error"), message.get("message", "")[:300])
        return message.get("result", {})

    def mark(self) -> int:
        """A position in the event stream; wait_event only sees events after it."""
        with self._lock:
            return self._seq

    def wait_event(self, method: str, context: str, after: int, timeout: float,
                   cancel: threading.Event | None = None) -> dict | None:  # fmt: skip
        deadline = time.monotonic() + timeout
        with self._lock:
            while True:
                for seq, event in self.events:
                    if seq > after and event.get("method") == method and event.get("params", {}).get("context") == context:
                        return event
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._closed or (cancel is not None and cancel.is_set()):
                    return None
                self._lock.wait(min(remaining, 0.1))

    def close(self) -> None:
        try:
            self.command("session.end", {}, timeout=3)
        except BidiError:
            pass
        self.ws.close()


def deserialize(value: dict):
    """A BiDi RemoteValue as plain data; nodes become {"sharedId", "localName"} handles."""
    kind = value.get("type")
    if kind in ("string", "boolean"):
        return value["value"]
    if kind == "number":
        v = value["value"]
        return None if isinstance(v, str) else v  # NaN, Infinity, -0 arrive as strings
    if kind in ("undefined", "null"):
        return None
    if kind == "bigint":
        return int(value["value"])
    if kind in ("array", "set", "nodelist", "htmlcollection"):
        return [deserialize(v) for v in value.get("value", [])]
    if kind in ("object", "map"):
        out = {}
        for key, item in value.get("value", []):
            out[key if isinstance(key, str) else str(deserialize(key))] = deserialize(item)
        return out
    if kind == "node":
        return {"sharedId": value.get("sharedId"), "localName": value.get("value", {}).get("localName")}
    return {"type": kind}


def script_result(result: dict) -> object:
    if result.get("type") == "exception":
        details = result.get("exceptionDetails", {})
        raise BidiError("javascript error", str(details.get("text", ""))[:300])
    return deserialize(result.get("result", {}))
