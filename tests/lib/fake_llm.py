"""A stand-in model provider for tests: OpenAI- and Anthropic-compatible, on 127.0.0.1.

It replays scripted replies and records every request (path, headers in lower case, body), so a
test can check what was sent and to whom. No real model, no network beyond loopback.

- `replies`: plain dicts are sent as JSON with status 200; a `Reply` sets the status, headers
  (Retry-After), streamed pieces, the stop reason, a stream that breaks with an error, or a hang.
- A request with `"stream": true` gets Server-Sent Events in the provider's own format (OpenAI
  `choices[].delta`, `finish_reason`, `data: [DONE]`; Anthropic `content_block_delta`,
  `message_delta.stop_reason`, `event: error`), unless `ignore_stream` is set: then it answers
  JSON, as some local servers do.
- `delay` holds each reply back; `chunk_delay` spaces the streamed pieces.
- `chars` has, per request, the code points of the system prompt and every message's text: what
  the assistant says it sends. `pieces_sent` counts the pieces of the last stream already written.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
import time
from dataclasses import dataclass, field


@dataclass
class Reply:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: dict | None = None  # the JSON reply (also what a JSON request gets for `chunks`, joined)
    chunks: list[str] | None = None  # the text, piece by piece, for a streamed reply
    stop: str | None = None  # finish_reason (OpenAI) or stop_reason (Anthropic)
    chunk_delay: float | None = None
    hang: bool = False  # read the request and never answer (until the provider closes)
    error: str | None = None  # a stream that breaks with this provider error after its pieces


def _anthropic(path: str) -> bool:
    return path.rstrip("/").endswith("/messages")


def _text_of(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    out = []
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict):
            for key in ("text", "content"):
                out += _text_of(block.get(key))
    return out


def sent_chars(body: dict) -> int:
    """Code points of the system prompt and of every message's text in one request."""
    texts = _text_of(body.get("system"))
    for message in body.get("messages") or []:
        texts += _text_of(message.get("content"))
    return sum(len(t) for t in texts)


def _reply_text(path: str, reply: dict) -> tuple[str, str | None]:
    """The text and stop reason of a plain JSON reply, to stream it."""
    if _anthropic(path):
        blocks = reply.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text"), reply.get("stop_reason")
    choice = (reply.get("choices") or [{}])[0]
    return (choice.get("message") or {}).get("content") or "", choice.get("finish_reason")


def _json_body(path: str, text: str, stop: str | None) -> dict:
    if _anthropic(path):
        return {"content": [{"type": "text", "text": text}], "stop_reason": stop or "end_turn"}
    return {"choices": [{"message": {"content": text}, "finish_reason": stop or "stop"}]}


def _error_body(path: str, status: int) -> dict:
    if _anthropic(path):
        return {"type": "error", "error": {"type": "api_error", "message": f"HTTP {status}"}}
    return {"error": {"message": f"HTTP {status}", "type": "api_error"}}


class FakeProvider:
    """An OpenAI- and Anthropic-compatible endpoint on 127.0.0.1 that replays scripted replies."""

    def __init__(self):
        self.requests: list[tuple[str, dict, dict]] = []
        self.chars: list[int] = []
        self.replies: list[dict | Reply] = []
        self.delay = 0.0
        self.chunk_delay = 0.0
        self.ignore_stream = False
        self.split_lines = False  # write each streamed event in two parts, as TCP may deliver it
        self.pieces_sent = 0
        self._closed = threading.Event()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                outer.chars.append(sent_chars(body))
                time.sleep(outer.delay)
                reply = outer.replies.pop(0) if outer.replies else _json_body(self.path, "ok", None)
                if not isinstance(reply, Reply):
                    reply = Reply(body=reply)
                    if body.get("stream") and not outer.ignore_stream:
                        text, reply.stop = _reply_text(self.path, reply.body)  # streamed word by word
                        reply.chunks = re.findall(r"\S+\s*|\s+", text) or [""]
                if reply.hang:
                    outer._closed.wait()
                    return
                if reply.status != 200:
                    self.send(reply.status, reply.body or _error_body(self.path, reply.status), reply.headers)
                elif body.get("stream") and not outer.ignore_stream:
                    try:
                        self.stream(reply)
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # the client stopped reading (a cancel): nothing more to send
                else:
                    text = "".join(reply.chunks or [])
                    self.send(200, reply.body or _json_body(self.path, text, reply.stop), reply.headers)

            def send(self, status: int, payload: dict, headers: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for name, value in headers.items():
                    self.send_header(name, str(value))
                self.end_headers()
                self.wfile.write(data)

            def stream(self, reply: Reply) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                for name, value in reply.headers.items():
                    self.send_header(name, str(value))
                self.end_headers()
                outer.pieces_sent = 0
                pause = outer.chunk_delay if reply.chunk_delay is None else reply.chunk_delay
                anthropic = _anthropic(self.path)

                def event(name: str | None, data) -> None:
                    line = data if isinstance(data, str) else json.dumps(data)
                    raw = ((f"event: {name}\n" if name else "") + f"data: {line}\n\n").encode()
                    if outer.split_lines:
                        half = len(raw) // 2
                        self.wfile.write(raw[:half])
                        self.wfile.flush()
                        time.sleep(0.02)
                        raw = raw[half:]
                    self.wfile.write(raw)
                    self.wfile.flush()

                if anthropic:
                    event("message_start", {"type": "message_start", "message": {"role": "assistant", "content": []}})
                    event("content_block_start", {"type": "content_block_start", "index": 0,
                                                  "content_block": {"type": "text", "text": ""}})  # fmt: skip
                for piece in reply.chunks or []:
                    if anthropic:
                        event("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                      "delta": {"type": "text_delta", "text": piece}})  # fmt: skip
                    else:
                        event(None, {"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
                    outer.pieces_sent += 1
                    time.sleep(pause)
                if reply.error:
                    if anthropic:
                        event("error", {"type": "error", "error": {"type": reply.error, "message": reply.error}})
                    else:
                        event(None, {"error": {"message": reply.error, "type": reply.error}})
                    return
                if anthropic:
                    event("content_block_stop", {"type": "content_block_stop", "index": 0})
                    event("message_delta", {"type": "message_delta", "delta": {"stop_reason": reply.stop or "end_turn"}})
                    event("message_stop", {"type": "message_stop"})
                else:
                    event(None, {"choices": [{"index": 0, "delta": {}, "finish_reason": reply.stop or "stop"}]})
                    event(None, "[DONE]")

            def log_message(self, *_a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def count(self) -> int:
        return len(self.requests)

    def close(self):
        self._closed.set()
        self.server.shutdown()
        self.server.server_close()
