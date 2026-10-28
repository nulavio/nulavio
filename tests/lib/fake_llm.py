"""A stand-in model provider for tests: OpenAI- and Anthropic-compatible, on 127.0.0.1.

It replays scripted replies and records every request (path, headers in lower case, body), so a
test can check what was sent and to whom. No real model, no network beyond loopback. `delay`
(seconds) holds each reply back, for tests that look at the waiting state.
"""

from __future__ import annotations

import http.server
import json
import threading
import time


class FakeProvider:
    """An OpenAI- and Anthropic-compatible endpoint on 127.0.0.1 that replays scripted replies."""

    def __init__(self):
        self.requests: list[tuple[str, dict, dict]] = []
        self.replies: list[dict] = []
        self.delay = 0.0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                time.sleep(outer.delay)
                reply = outer.replies.pop(0) if outer.replies else {"choices": [{"message": {"content": "ok"}}]}
                data = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
