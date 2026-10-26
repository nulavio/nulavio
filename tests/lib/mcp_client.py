"""A small MCP stdio client for tests: starts `nulavio ai serve` and speaks JSON-RPC lines."""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "nulavio-tests", "version": "1"},
}


class McpClient:
    def __init__(self, env: dict[str, str], args: tuple[str, ...] = ("--headless",), modern: bool = False):
        self.modern = modern
        self.process = subprocess.Popen(
            [str(ROOT / "bin" / "nulavio"), "ai", "serve", *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), **env},
        )  # fmt: skip
        self._ids = itertools.count(1)
        self.stderr: list[str] = []
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        with self.process.stderr:
            for line in self.process.stderr:
                self.stderr.append(line.decode(errors="replace"))

    def send(self, message: dict) -> None:
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()

    def read(self) -> dict:
        line = self.process.stdout.readline()
        if not line:
            raise EOFError("".join(self.stderr)[-2000:])
        return json.loads(line)

    def request(self, method: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        if self.modern:
            params["_meta"] = MODERN_META
        request_id = next(self._ids)
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            message = self.read()
            if message.get("id") == request_id:
                return message

    def initialize(self, version: str = "2025-06-18") -> dict:
        response = self.request("initialize", {"protocolVersion": version, "capabilities": {},
                                               "clientInfo": {"name": "nulavio-tests", "version": "1"}})  # fmt: skip
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response

    def call(self, name: str, **arguments) -> dict:
        response = self.request("tools/call", {"name": name, "arguments": arguments})
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    def close(self, timeout: float = 30) -> int:
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            code = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            code = self.process.wait()
        self.process.stdout.close()
        return code
