"""Integration harness: a disposable Nulavio home + engine under Marionette.

Flow (mirrors what a user does, then adds test-only remote control):

1. ``NULAVIO_HOME`` points to a fresh temp dir, so nothing touches the real
   ~/.local/share/nulavio or any Firefox profile.
2. ``nulavio setup --yes`` and ``nulavio run --dry-run`` prepare the profile
   exactly as for a user (seed prefs, user.js, theme, start page, uBO).
3. Test-only prefs are appended to that disposable profile's user.js:
   Marionette on a random port, and ``remote.prefs.recommended=false`` so the
   remote agent does NOT silently disable Safe Browsing, tracking protection,
   the password manager or extension updates (which it does by default; see
   docs/research/compatibility-matrix.md).
4. The engine starts headless with the same umask as the launcher (0077).

Environment knobs:
  NULAVIO_TEST_HEADFUL=1   show the window (local debugging)
  NULAVIO_NETWORK_TESTS=1  allow tests that download from addons.mozilla.org
  NULAVIO_TEST_ARTIFACTS   directory for screenshots (default: tests/artifacts)
  NULAVIO_TEST_ENGINE_LOG  append engine stdout/stderr to this file (debugging)
"""

from __future__ import annotations

import http.server
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from marionette import Marionette  # noqa: E402

TEST_PREFS = {
    "marionette.port": 0,
    "remote.prefs.recommended": False,
    "browser.download.folderList": 2,
    "browser.download.useDownloadDir": True,
    "browser.download.alwaysOpenPanel": False,
    "browser.shell.checkDefaultBrowser": False,
}


def engine_available() -> bool:
    try:
        from nulavio_launcher import engine

        engine.find_engine()
        return True
    except Exception:
        return False


def artifacts_dir() -> Path:
    path = Path(os.environ.get("NULAVIO_TEST_ARTIFACTS", ROOT / "tests" / "artifacts"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _png_1px() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixel = zlib.compress(b"\x00\x6f\xe0\xc5\xff")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


class FixtureServer:
    """Local HTTP fixtures on 127.0.0.1 that record which paths were requested."""

    PNG_1PX = _png_1px()

    def __init__(self):
        self.hits: list[str] = []
        self._lock = threading.Lock()
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                with outer._lock:
                    outer.hits.append(self.path)
                body, ctype, extra = outer.route(self.path)
                self.send_response(200 if body is not None else 404)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                for key, value in extra.items():
                    self.send_header(key, value)
                self.end_headers()
                if body is not None:
                    self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def route(self, raw: str):
        path, _, qs = raw.partition("?")
        query = dict(part.split("=", 1) for part in qs.split("&") if "=" in part)
        html = "text/html; charset=utf-8"
        if path.startswith("/page/"):
            name = path.rsplit("/", 1)[-1]
            return f"<!doctype html><title>{name}</title><p id=name>{name}</p>".encode(), html, {}
        if path == "/login":
            # Fixture for password-manager certification. Throwaway credentials only.
            page = (
                "<!doctype html><title>login-fixture</title>"
                '<form id="login" action="/login-done" method="get">'
                '<label>User <input id="username" name="username" type="text" autocomplete="username"></label>'
                '<label>Password <input id="password" name="password" type="password" autocomplete="current-password"></label>'
                '<button type="submit">Sign in</button></form>'
            )
            return page.encode(), html, {}
        if path == "/ads-fixture":
            # Unique image URLs per load so the image cache cannot hide a request.
            n = query.get("n", "0")
            page = (
                "<!doctype html><title>ads-fixture</title>"
                f'<img id="control" src="/assets/control.png?n={n}">'
                f'<img id="ad" src="/adbanners/nulavio-test.png?n={n}">'
            )
            return page.encode(), html, {}
        if path.endswith(".png"):
            return self.PNG_1PX, "image/png", {}
        if path == "/download":
            return (
                b"nulavio download fixture\n",
                "application/octet-stream",
                {"Content-Disposition": 'attachment; filename="nulavio-fixture.bin"'},
            )
        return None, html, {}

    def count(self, path: str) -> int:
        """Number of requests whose path (including the query string) equals ``path``."""
        with self._lock:
            return sum(1 for hit in self.hits if hit == path)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


class Session:
    """Disposable Nulavio home + running engine + Marionette client."""

    def __init__(self, profile: str = "itest", setup_args: tuple[str, ...] = ()):
        self.tmp = Path(tempfile.mkdtemp(prefix="nulavio-itest-"))
        self.home = self.tmp / "home"
        self.downloads = self.tmp / "downloads"
        self.downloads.mkdir()
        self.profile_name = profile
        self.setup_args = setup_args
        self.process: subprocess.Popen | None = None
        self.client: Marionette | None = None
        self.env = {**os.environ, "NULAVIO_HOME": str(self.home)}
        seed_cache = os.environ.get("NULAVIO_TEST_XPI_CACHE")
        if seed_cache and Path(seed_cache).is_dir():
            # Files are still hash-verified by the launcher before use.
            target = self.home / "cache" / "xpi"
            target.mkdir(parents=True, mode=0o700)
            for xpi in Path(seed_cache).glob("*.xpi"):
                shutil.copy2(xpi, target / xpi.name)

    def nulavio(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / "bin" / "nulavio"), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=300,
            check=check,
        )

    @property
    def profile_dir(self) -> Path:
        return self.home / "data" / "profiles" / self.profile_name

    def prepare(self) -> list[str]:
        self.nulavio("setup", "--yes", "--profile", self.profile_name, *self.setup_args)
        dry = self.nulavio("run", "--dry-run", "--profile", self.profile_name)
        command = dry.stdout.strip().split()
        prefs = dict(TEST_PREFS)
        prefs["browser.download.dir"] = str(self.downloads)
        lines = [f'user_pref("{k}", {self._js(v)});' for k, v in prefs.items()]
        with open(self.profile_dir / "user.js", "a", encoding="utf-8") as handle:
            handle.write("// test harness overlay (disposable profile only)\n" + "\n".join(lines) + "\n")
        return command

    @staticmethod
    def _js(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def start(self) -> Marionette:
        command = self.prepare()
        command += ["--marionette", "--remote-allow-system-access", "--new-instance"]
        env = dict(self.env)
        if os.environ.get("NULAVIO_TEST_HEADFUL") != "1":
            command.append("--headless")
            env["MOZ_HEADLESS"] = "1"
        port_file = self.profile_dir / "MarionetteActivePort"
        engine_log = os.environ.get("NULAVIO_TEST_ENGINE_LOG")  # debugging aid; may contain page console output
        output = open(engine_log, "ab") if engine_log else subprocess.DEVNULL  # noqa: SIM115
        self.process = subprocess.Popen(
            command,
            env=env,
            stdout=output,
            stderr=output,
            preexec_fn=lambda: os.umask(0o077),
            start_new_session=True,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if port_file.exists() and port_file.read_text().strip():
                break
            if self.process.poll() is not None:
                raise RuntimeError(f"engine exited early with {self.process.returncode}")
            time.sleep(0.3)
        else:
            raise TimeoutError("Marionette port file did not appear")
        self.client = Marionette(int(port_file.read_text().strip())).connect()
        self.client.new_session()
        return self.client

    def stop(self) -> None:
        if self.client is not None:
            self.client.quit()
            self.client = None
        if self.process is not None:
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=10)
            self.process = None

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def engine_pid(self) -> int:
        return int(self.client.chrome("return Services.appinfo.processID;"))


def descendants(pid: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
        children.setdefault(ppid, []).append(int(entry.name))
    out, stack = [], [pid]
    while stack:
        for child in children.get(stack.pop(), []):
            out.append(child)
            stack.append(child)
    return out


def proc_info(pid: int) -> dict:
    base = Path("/proc") / str(pid)
    cmdline = (base / "cmdline").read_bytes().split(b"\0")
    seccomp = []
    for task in (base / "task").iterdir():
        for line in (task / "status").read_text().splitlines():
            if line.startswith("Seccomp:"):
                seccomp.append(int(line.split()[1]))
    # Processes spawned by the engine's fork server rewrite their argv into a
    # single space-separated string, so callers should match on "cmd".
    args = [a.decode(errors="replace") for a in cmdline if a]
    return {
        "pid": pid,
        "args": args,
        "cmd": " ".join(args),
        "seccomp": seccomp,
        "userns": os.readlink(base / "ns" / "user"),
    }


def wait_until(predicate, timeout: float = 15.0, interval: float = 0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()
