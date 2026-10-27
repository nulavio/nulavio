"""A local DNS-over-HTTPS resolver for tests (RFC 8484), with a throwaway certificate authority.

It answers A queries for the names it was given with 127.0.0.1 and everything
else with an empty NOERROR, and records each query name, so a test can tell
whether the browser used it. The CA and its key exist only in a temporary
directory for the test; the browser trusts the CA only in the test profile.
"""

from __future__ import annotations

import base64
import http.server
import ssl
import struct
import subprocess
import threading
from pathlib import Path

HOST = "doh.nulavio-test"


def make_ca(directory: Path) -> tuple[Path, Path, Path]:
    """CA certificate, server certificate and server key for HOST (P-256, 2 days)."""
    run = lambda *a: subprocess.run(a, check=True, capture_output=True)  # noqa: E731
    ca_key, ca_pem = directory / "ca.key", directory / "ca.pem"
    key, csr, pem, ext = directory / "server.key", directory / "server.csr", directory / "server.pem", directory / "ext.cnf"
    run("openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "2",
        "-subj", "/CN=Nulavio DoH Test CA", "-keyout", str(ca_key), "-out", str(ca_pem))  # fmt: skip
    run("openssl", "req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
        "-subj", f"/CN={HOST}", "-keyout", str(key), "-out", str(csr))  # fmt: skip
    ext.write_text(f"subjectAltName=DNS:{HOST}\nextendedKeyUsage=serverAuth\n")
    run("openssl", "x509", "-req", "-in", str(csr), "-CA", str(ca_pem), "-CAkey", str(ca_key), "-CAcreateserial",
        "-days", "2", "-extfile", str(ext), "-out", str(pem))  # fmt: skip
    ca_key.unlink()
    return ca_pem, pem, key


def _qname(message: bytes, offset: int) -> tuple[str, int]:
    labels = []
    while True:
        length = message[offset]
        offset += 1
        if length == 0:
            return ".".join(labels), offset
        labels.append(message[offset : offset + length].decode("ascii", "replace"))
        offset += length


def answer(query: bytes, names: set[str]) -> tuple[bytes, str]:
    """A DNS response to `query`, and the name asked for."""
    ident, _flags, qdcount = struct.unpack("!HHH", query[:6])
    name, end = _qname(query, 12)
    qtype, _qclass = struct.unpack("!HH", query[end : end + 4])
    question = query[12 : end + 4]
    records = b""
    count = 0
    if qtype == 1 and name.lower() in names:  # A
        records = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + bytes([127, 0, 0, 1])
        count = 1
    header = struct.pack("!HHHHHH", ident, 0x8180, qdcount, count, 0, 0)  # response, RD, RA, NOERROR
    return header + question + records, name


class DohServer:
    def __init__(self, directory: Path, names: set[str]):
        self.names = {n.lower() for n in names}
        self.queries: list[str] = []
        self.ca, cert, key = make_ca(directory)
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _respond(self, query: bytes) -> None:
                body, name = answer(query, outer.names)
                outer.queries.append(name)
                self.send_response(200)
                self.send_header("Content-Type", "application/dns-message")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self._respond(self.rfile.read(int(self.headers.get("Content-Length", "0"))))

            def do_GET(self):
                raw = self.path.partition("dns=")[2].split("&")[0]
                self._respond(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        context.set_alpn_protocols(["http/1.1"])
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.uri = f"https://{HOST}:{self.port}/dns-query"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def ca_base64(self) -> str:
        lines = self.ca.read_text().strip().splitlines()
        return "".join(line for line in lines if not line.startswith("-----"))

    def start(self) -> DohServer:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
