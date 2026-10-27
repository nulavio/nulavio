"""The reference phone (phone_reference.py) behind a real TCP listener, as the Companion app works.

For each operation the phone listens on a socket and "announces" it under the
operation's mDNS name; here the announcement is a dictionary that the test
hands to the desktop as its resolver, or a real Avahi announcement
(`avahi-publish`) when `announce="avahi"`. The desktop connects and the phone
speaks first (ADR 0005, transport amendment).
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
from pathlib import Path

from nulavio_launcher.vault import link
from phone_reference import PhoneRejected, ReferencePhone


class LinkedPhone:
    def __init__(self, phone: ReferencePhone, announce: str = "local", registry: Path | None = None):
        self.phone = phone
        self.announce = announce
        self.registry = registry  # tests/lib/fake_avahi.py reads it
        self.names: dict[str, tuple[str, int]] = {}
        self.sas: str | None = None
        self.result: dict | None = None
        self.error: str | None = None
        self.threads: list[threading.Thread] = []
        self._publishers: list[subprocess.Popen] = []

    def resolver(self, name: str) -> tuple[str, int] | None:
        return self.names.get(name)

    def _listen(self, name: str) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # A real announcement points at the machine's network address, so listen there too (test only, seconds).
        server.bind(("0.0.0.0" if self.announce == "avahi" else "127.0.0.1", 0))  # noqa: S104
        server.listen(1)
        port = server.getsockname()[1]
        if self.announce == "avahi":
            command = [shutil.which("avahi-publish") or "avahi-publish", "-s", name, link.SERVICE_TYPE, str(port)]
            self._publishers.append(subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        else:
            self.names[name] = ("127.0.0.1", port)
            if self.registry is not None:
                self.registry.write_text(json.dumps(self.names))
        return server

    def _run(self, target) -> threading.Thread:
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self.threads.append(thread)
        return thread

    def pair(self, qr_text: str, digits_match: bool = True, timeout: float = 60) -> threading.Thread:
        qr = json.loads(qr_text)
        server = self._listen(link.instance_name("p", qr["i"]))

        def serve() -> None:
            server.settimeout(timeout)
            try:
                conn, _ = server.accept()
            finally:
                server.close()
            channel = link.Channel(conn)
            deadline = _deadline(timeout)
            try:
                channel.send({"t": "hello", **self.phone.scan(qr)})
                accept = channel.recv(deadline)
                if accept.get("t") != "accept":
                    self.result = accept
                    return
                self.sas = self.phone.on_accept(accept)
                channel.send({"t": "confirm", **self.phone.confirm()} if digits_match else {"t": "cancel"})
                self.result = channel.recv(deadline)
            except (PhoneRejected, link.LinkError) as exc:
                self.error = exc.code
            finally:
                channel.close()

        return self._run(serve)

    def unlock(self, qr_text: str, approve: bool = True, timeout: float = 60) -> threading.Thread:
        signed = json.loads(qr_text)
        server = self._listen(link.instance_name("u", signed["r"]["req_id"]))

        def serve() -> None:
            server.settimeout(timeout)
            try:
                conn, _ = server.accept()
            finally:
                server.close()
            channel = link.Channel(conn)
            try:
                response = self.phone.handle(signed, approve)
                channel.send({"t": "response", **response})
                self.result = channel.recv(_deadline(timeout))
            except (PhoneRejected, link.LinkError) as exc:
                self.error = exc.code
            finally:
                channel.close()

        return self._run(serve)

    def close(self) -> None:
        for publisher in self._publishers:
            publisher.terminate()
            publisher.wait(5)


def _deadline(timeout: float) -> float:
    import time

    return time.monotonic() + timeout
