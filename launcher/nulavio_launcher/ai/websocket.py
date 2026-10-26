"""Minimal WebSocket client (RFC 6455) for the engine's local WebDriver BiDi endpoint.

Standard library only (NFR-03). Client frames are masked, text messages only,
fragmented messages are reassembled, pings are answered, and every message has
a size limit. It talks to 127.0.0.1 only; there is no TLS because the endpoint
never leaves the machine.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE = 64 * 1024 * 1024  # screenshots are the largest messages


class WebSocketError(RuntimeError):
    pass


class ConnectionClosed(WebSocketError):
    pass


class WebSocket:
    def __init__(self, host: str, port: int, path: str = "/session", timeout: float = 10.0, max_message: int = MAX_MESSAGE):
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise WebSocketError("only local endpoints are allowed")
        self.max_message = max_message
        self._send_lock = threading.Lock()
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._buffer = b""
        try:
            self._handshake(host, port, path)
        except Exception:
            self.sock.close()
            raise
        self.sock.settimeout(None)

    def _handshake(self, host: str, port: int, path: str) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        while b"\r\n\r\n" not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk or len(self._buffer) > 16384:
                raise WebSocketError("bad handshake response")
            self._buffer += chunk
        head, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if not lines[0].startswith("HTTP/1.1 101"):
            raise WebSocketError(f"upgrade refused: {lines[0][:80]}")
        headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:])}
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()  # noqa: S324 - RFC 6455
        if headers.get("sec-websocket-accept") != expected:
            raise WebSocketError("bad Sec-WebSocket-Accept")

    def _read(self, n: int) -> bytes:
        while len(self._buffer) < n:
            chunk = self.sock.recv(max(65536, n - len(self._buffer)))
            if not chunk:
                raise ConnectionClosed("connection closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:n], self._buffer[n:]
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload)) if length < 4096 else _mask_fast(payload, mask)
        with self._send_lock:
            self.sock.sendall(bytes(header) + mask + masked)

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode())

    def recv_text(self) -> str:
        """Block until a complete text message arrives (answers pings meanwhile)."""
        parts: list[bytes] = []
        size = 0
        while True:
            b1, b2 = self._read(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            if b2 & 0x80:
                raise WebSocketError("server frames must not be masked")
            if size + length > self.max_message:
                self.close()
                raise WebSocketError("message too large")
            payload = self._read(length)
            if opcode == 0x8:
                raise ConnectionClosed("closed by peer")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2, 0x0):
                parts.append(payload)
                size += length
                if fin:
                    return b"".join(parts).decode("utf-8")
                continue
            raise WebSocketError(f"unexpected opcode {opcode}")

    def close(self) -> None:
        try:
            self._send_frame(0x8, struct.pack(">H", 1000))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def _mask_fast(payload: bytes, mask: bytes) -> bytes:
    """XOR with the 4-byte mask using big-integer arithmetic (fast for large payloads)."""
    n = len(payload)
    repeated = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(repeated, "big")).to_bytes(n, "big")
