"""The Companion's Java nv1 (android/nv1) against the Python desktop, over a real socket (S11).

The vectors file must be what tests/lib/nv1_vectors.py writes (android/nv1's tests check Java
against it). When android/nv1 has been built (`gradle :nv1:test` writes its classpath), the Java
phone pairs with a real encrypted profile and unlocks it through the desktop's own session code;
refusals (declined, replayed, tampered, unknown desktop) are checked on the Java side.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import nv1_vectors
from nulavio_launcher.vault import link, phone_session, profiles, sodium, storage
from nulavio_launcher.vault.core import b64e
from nulavio_launcher.vault.phone import DesktopIdentity, request_signing_input

ROOT = Path(__file__).resolve().parents[2]
CLASSPATH = ROOT / "android" / "nv1" / "build" / "nv1-test-classpath.txt"
FAST = {"ops": 1, "mem": 8 * 1024 * 1024}
PASSWORD = "artificial password 8"


def java() -> str | None:
    home = os.environ.get("JAVA_HOME")
    candidates = [Path(home) / "bin" / "java"] if home else []
    candidates.append(Path.home() / ".local/share/nulavio-dev/jdk-21/bin/java")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("java")


class VectorsFileTest(unittest.TestCase):
    @unittest.skipUnless(sodium.available(), "needs libsodium")
    def test_the_committed_vectors_are_current(self):
        committed = json.loads((ROOT / "tests" / "fixtures" / "nv1-vectors.json").read_text(encoding="utf-8"))
        self.assertEqual(committed, json.loads(json.dumps(nv1_vectors.build())))


class JavaPhone:
    def __init__(self, state: Path):
        self.state = state
        self.cp = CLASSPATH.read_text(encoding="utf-8").strip()

    def run(self, *args: str) -> subprocess.Popen:
        return subprocess.Popen([java(), "-cp", self.cp, "net.nulavio.nv1.PhoneCli", *args, ], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # fmt: skip

    def new(self, name: str) -> None:
        self.finish(self.run("new", str(self.state), name))

    @staticmethod
    def finish(proc: subprocess.Popen) -> None:
        proc.wait(60)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()

    @staticmethod
    def line(proc: subprocess.Popen) -> dict:
        text = proc.stdout.readline()
        if not text:
            raise AssertionError(f"the Java phone said nothing: {proc.stderr.read()[-2000:]}")
        return json.loads(text)


@unittest.skipUnless(
    CLASSPATH.is_file() and java() and sodium.available() and storage.tools_available(),
    "build android/nv1 first (gradle :nv1:test); needs Java, gocryptfs, FUSE and libsodium",
)
class CompanionProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-companion-"))
        patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cleanup)
        self.prof, _code = profiles.create("cofre", password=PASSWORD, kdf=FAST, recovery_kdf=FAST)
        self.names: dict[str, tuple[str, int]] = {}
        self.phone = JavaPhone(self.tmp / "phone-state.json")
        self.phone.new("Pixel de teste é")

    def _cleanup(self):
        for mountpoint in sorted(storage.mounted_paths()):
            if mountpoint.startswith(str(self.tmp)):
                subprocess.run(["fusermount3", "-u", "-z", mountpoint], check=False, capture_output=True)
        for dirpath, _dirs, _files in os.walk(self.tmp):
            os.chmod(dirpath, 0o700)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, kind: str, request: dict):
        session = phone_session.Session(kind)
        first: dict = {}
        ready = threading.Event()

        def emit(message):
            if not ready.is_set():
                first.update(message)
                ready.set()

        operation = phone_session.pair if kind == "pair" else phone_session.unlock
        thread = threading.Thread(target=operation, daemon=True,
                                  args=(session, {"path": str(self.prof.path), **request}, emit, self.names.get))  # fmt: skip
        thread.start()
        self.assertTrue(ready.wait(30))
        return session, first, thread

    def wait_state(self, session, *states, timeout=30):
        deadline = time.monotonic() + timeout
        while session.state not in states and time.monotonic() < deadline:
            time.sleep(0.05)
        return session.state

    def pair(self) -> None:
        session, first, thread = self.start("pair", {"current": PASSWORD})
        invite = json.loads(first["qr"])
        proc = self.phone.run("pair", str(self.phone.state), first["qr"])
        self.names[link.instance_name("p", invite["i"])] = ("127.0.0.1", JavaPhone.line(proc)["port"])
        sas = JavaPhone.line(proc)["sas"]
        self.assertEqual(self.wait_state(session, "compare", "failed"), "compare")
        self.assertEqual(session.status()["sas"], sas)  # the same 6 digits on both screens
        session.handle({"action": "confirm", "match": True})
        proc.stdin.write("yes\n")
        proc.stdin.flush()
        self.assertEqual(JavaPhone.line(proc), {"result": {"t": "paired"}})
        JavaPhone.finish(proc)
        thread.join(30)
        self.assertEqual(session.state, "paired")
        self.assertEqual(session.phone_name, "Pixel de teste é")

    def unlock(self, answer: str = "APPROVE", qr: str | None = None):
        session, first, thread = (None, {"qr": qr}, None) if qr else self.start("unlock", {"autolock": False})
        signed = json.loads(first["qr"])
        proc = self.phone.run("unlock", str(self.phone.state), first["qr"], answer)
        said = JavaPhone.line(proc)
        if "port" in said:
            self.names[link.instance_name("u", signed["r"]["req_id"])] = ("127.0.0.1", said["port"])
            said = JavaPhone.line(proc)
        JavaPhone.finish(proc)
        if thread:
            thread.join(30)
        return session, said, first["qr"]

    def test_pair_unlock_and_refusals(self):
        self.pair()
        session, said, qr = self.unlock()
        self.assertEqual(said, {"result": {"t": "ok"}})
        self.assertEqual(session.state, "unlocked")
        self.assertTrue(profiles.container(self.prof).mounted())
        profiles.lock(self.prof)

        # The same request again: the phone remembers it answered (replay).
        _session, said, _qr = self.unlock(qr=qr)
        self.assertEqual(said, {"rejected": "replay"})

        session, said, _qr = self.unlock("DECLINE")
        self.assertEqual(said, {"result": {"t": "error", "code": "declined"}})
        self.assertEqual(session.state, "declined")
        self.assertFalse(profiles.container(self.prof).mounted())

    def test_requests_the_phone_must_refuse(self):
        self.pair()
        session, first, thread = self.start("unlock", {"autolock": False})
        signed = json.loads(first["qr"])
        tampered = {"r": {**signed["r"], "profile_name": "Outro"}, "sig": signed["sig"]}
        _s, said, _q = self.unlock(qr=json.dumps(tampered))
        self.assertEqual(said, {"rejected": "bad-signature"})
        stranger = DesktopIdentity.generate()
        foreign_r = {**signed["r"], "desktop_id": stranger.desktop_id}
        foreign = {"r": foreign_r, "sig": b64e(sodium.sign(stranger.sig_sk, request_signing_input(foreign_r)))}
        _s, said, _q = self.unlock(qr=json.dumps(foreign))
        self.assertEqual(said, {"rejected": "unpaired-desktop"})
        expired_r = {**signed["r"], "expiry": int(time.time()) - 600}
        identity = DesktopIdentity.load_or_create(phone_session.identity_path())
        expired = {"r": expired_r, "sig": b64e(sodium.sign(identity.sig_sk, request_signing_input(expired_r)))}
        _s, said, _q = self.unlock(qr=json.dumps(expired))
        self.assertEqual(said, {"rejected": "expired"})
        session.handle({"action": "cancel"})
        thread.join(30)
        self.assertEqual(session.state, "cancelled")


if __name__ == "__main__":
    unittest.main()
