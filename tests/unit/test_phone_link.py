"""Phone link and sessions (S11): nv1 over a real TCP connection, the phone listening, the desktop connecting out.

The reference phone (tests/lib/phone_reference.py) runs behind a socket
(tests/lib/phone_link_ref.py). Pairing and unlock run against real encrypted
profiles (gocryptfs) in a temporary NULAVIO_HOME, with artificial secrets.
With NULAVIO_LAN_TESTS=1 the last test announces the phone through the
machine's real Avahi and drives everything through `nulavio vault api`.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from nulavio_launcher.vault import link, phone, phone_session, profiles, sodium, storage
from nulavio_launcher.vault.core import b64e
from phone_link_ref import LinkedPhone
from phone_reference import ReferencePhone

ROOT = Path(__file__).resolve().parents[2]
FAST = {"ops": 1, "mem": 8 * 1024 * 1024}
PASSWORD = "artificial password 7"


class LinkTest(unittest.TestCase):
    def test_instance_names_are_per_operation_and_reveal_nothing_else(self):
        name = link.instance_name("u", "request-1")
        self.assertRegex(name, r"^nv1-u-[a-z2-7]{16}$")
        self.assertEqual(name, link.instance_name("u", "request-1"))
        self.assertNotEqual(name, link.instance_name("u", "request-2"))
        with self.assertRaises(ValueError):
            link.instance_name("x", "a")

    def channel_pair(self) -> tuple[link.Channel, socket.socket]:
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        return link.Channel(left), right

    def test_messages_are_canonical_json_lines(self):
        channel, peer = self.channel_pair()
        channel.send({"t": "hello", "b": 1, "a": "é"})
        self.assertEqual(peer.recv(100), b'{"a":"\\u00e9","b":1,"t":"hello"}\n')
        peer.sendall(b'{"t":"ok"}\n{"t":"second"}\n')
        deadline = time.monotonic() + 2
        self.assertEqual(channel.recv(deadline), {"t": "ok"})
        self.assertEqual(channel.recv(deadline), {"t": "second"})

    def test_bad_input_is_refused(self):
        for data, code in ((b"not json\n", "bad-message"), (b'{"no": "type"}\n', "bad-message"), (b"[1]\n", "bad-message"),
                           (b"x" * (link.MAX_LINE + 10), "too-large")):  # fmt: skip
            with self.subTest(code=code, data=data[:12]):
                channel, peer = self.channel_pair()
                peer.sendall(data)
                with self.assertRaises(link.LinkError) as caught:
                    channel.recv(time.monotonic() + 2)
                self.assertEqual(caught.exception.code, code)
        channel, _peer = self.channel_pair()
        with self.assertRaises(link.LinkError) as caught:
            channel.recv(time.monotonic() + 0.3)
        self.assertEqual(caught.exception.code, "timeout")

    def test_connect_waits_for_the_announcement_and_gives_up_at_the_deadline(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        self.addCleanup(server.close)
        calls = []

        def resolver(name):
            calls.append(name)
            return ("127.0.0.1", server.getsockname()[1]) if len(calls) >= 3 else None

        channel = link.connect("nv1-u-x", time.monotonic() + 10, resolver, interval=0.05)
        channel.close()
        self.assertEqual(len(calls), 3)
        with self.assertRaises(link.LinkError) as caught:
            link.connect("nv1-u-x", time.monotonic() + 0.3, lambda _n: None, interval=0.05)
        self.assertEqual(caught.exception.code, "unreachable")
        with self.assertRaises(link.LinkError) as caught:
            link.connect("nv1-u-x", time.monotonic() + 5, lambda _n: None, cancelled=lambda: True)
        self.assertEqual(caught.exception.code, "cancelled")

    def test_avahi_resolution_call_and_answer(self):
        tmp = Path(tempfile.mkdtemp(prefix="nv-busctl-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        log = tmp / "argv.json"
        fake = tmp / "busctl"
        fake.write_text(
            "#!/bin/sh\n"
            f'python3 -c \'import json,sys; json.dump(sys.argv[1:], open("{log}", "w"))\' "$@"\n'
            'echo \'{"type":"iissssisqaayu","data":[2,0,"n","_nulavio-nv1._tcp","local","phone.local",0,'
            '"192.168.1.23",40123,[],13]}\'\n'
        )
        fake.chmod(0o700)
        with mock.patch.dict(os.environ, {"NULAVIO_BUSCTL": str(fake)}):
            self.assertEqual(link.avahi_resolve("nv1-u-abc"), ("192.168.1.23", 40123))
        argv = json.loads(log.read_text())
        # "--" before the call: the interface index -1 must not be read as an option.
        self.assertLess(argv.index("--"), argv.index("call"))
        self.assertEqual(argv[argv.index("iisssiu") + 1 :], ["-1", "0", "nv1-u-abc", link.SERVICE_TYPE, "local", "0", "0"])
        fake.write_text('#!/bin/sh\necho \'{"data": [0,0,0,0,0,0,0,"not-an-ip",1]}\'\n')
        with mock.patch.dict(os.environ, {"NULAVIO_BUSCTL": str(fake)}):
            self.assertIsNone(link.avahi_resolve("nv1-u-abc"))


@unittest.skipUnless(sodium.available() and storage.tools_available(), "needs gocryptfs, FUSE and libsodium")
class PhoneSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-phone-"))
        patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cleanup)
        self.prof, self.code = profiles.create("cofre", password=PASSWORD, kdf=FAST, recovery_kdf=FAST)
        self.phone = LinkedPhone(ReferencePhone("Pixel de teste"))
        self.addCleanup(self.phone.close)

    def _cleanup(self):
        for mountpoint in sorted(storage.mounted_paths()):
            if mountpoint.startswith(str(self.tmp)):
                subprocess.run(["fusermount3", "-u", "-z", mountpoint], check=False, capture_output=True)
        for dirpath, _dirs, _files in os.walk(self.tmp):
            os.chmod(dirpath, 0o700)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, kind: str, request: dict, resolver=None) -> tuple[phone_session.Session, dict, threading.Thread]:
        session = phone_session.Session(kind)
        first: dict = {}
        ready = threading.Event()

        def emit(message):
            if not ready.is_set():
                first.update(message)
                ready.set()

        operation = phone_session.pair if kind == "pair" else phone_session.unlock
        args = (session, {"path": str(self.prof.path), **request}, emit, resolver or self.phone.resolver)
        thread = threading.Thread(target=operation, args=args, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(20), "no first answer")
        return session, first, thread

    def wait_state(self, session, *states, timeout=20):
        deadline = time.monotonic() + timeout
        while session.state not in states and time.monotonic() < deadline:
            time.sleep(0.05)
        return session.state

    def pair(self) -> None:
        session, first, thread = self.start("pair", {"current": PASSWORD})
        phone = self.phone.pair(first["qr"])
        self.assertEqual(self.wait_state(session, "waiting-for-you", "failed"), "waiting-for-you")
        self.assertEqual(session.status()["sas"], self.phone.sas)
        self.assertRegex(self.phone.sas, r"^\d{6}$")
        session.handle({"action": "confirm", "match": True})
        thread.join(20)
        # The phone records the desktop's last message on its own thread, which can still be reading it
        # when the desktop's thread has ended (failed in CI, runs 42867466404 and 42871213425).
        phone.join(20)
        self.assertEqual(session.status(), {"session": session.id, "kind": "pair", "state": "paired", "phone": "Pixel de teste"})
        self.assertEqual(self.phone.result, {"t": "paired"})

    def phone_methods(self) -> list[str]:
        return [m["method"] for m in profiles.status(self.prof)["methods"] if m["method"] == "phone"]

    def test_01_pairing_then_unlock_mounts_the_profile(self):
        self.pair()
        self.assertEqual(self.phone_methods(), ["phone"])
        self.assertEqual(len(self.phone.phone.desktops), 1)  # the phone remembers this desktop

        session, first, thread = self.start("unlock", {"autolock": False})
        signed = json.loads(first["qr"])
        self.assertEqual(signed["r"]["profile_name"], "cofre")
        phone = self.phone.unlock(first["qr"])
        thread.join(20)
        phone.join(20)
        self.assertEqual(session.state, "unlocked")
        self.assertEqual(self.phone.result, {"t": "ok"})
        self.assertTrue(profiles.container(self.prof).mounted())
        profiles.lock(self.prof)

    def test_02_digits_that_do_not_match_end_pairing_on_either_side(self):
        session, first, thread = self.start("pair", {"current": PASSWORD})
        phone = self.phone.pair(first["qr"])
        self.wait_state(session, "waiting-for-you")
        session.handle({"action": "confirm", "match": False})
        thread.join(20)
        phone.join(20)
        self.assertEqual((session.state, session.error), ("failed", "sas-mismatch"))
        self.assertEqual(self.phone.result, {"t": "error", "code": "sas-mismatch"})

        other = LinkedPhone(ReferencePhone("Outro"))
        self.addCleanup(other.close)
        session, first, thread = self.start("pair", {"current": PASSWORD}, other.resolver)
        other.pair(first["qr"], digits_match=False)
        thread.join(20)
        self.assertEqual((session.state, session.error), ("failed", "sas-mismatch"))
        self.assertEqual(self.phone_methods(), [])

    def test_03_pairing_needs_the_current_secret(self):
        _session, first, thread = self.start("pair", {"current": "wrong"})
        thread.join(20)
        self.assertEqual(first, {"error": "wrong-secret"})
        self.assertEqual(self.phone_methods(), [])

    def test_04_declined_and_strangers(self):
        self.pair()
        session, first, thread = self.start("unlock", {"autolock": False})
        self.phone.unlock(first["qr"], approve=False)
        thread.join(20)
        self.assertEqual(session.state, "declined")
        self.assertFalse(profiles.container(self.prof).mounted())

        # Someone on the network answers first with a response the phone did not sign: ignored, then the phone unlocks.
        stranger = socket.socket()
        stranger.bind(("127.0.0.1", 0))
        stranger.listen(1)
        self.addCleanup(stranger.close)
        answers = iter([("127.0.0.1", stranger.getsockname()[1])])
        session, first, thread = self.start("unlock", {"autolock": False},
                                            lambda name: next(answers, None) or self.phone.resolver(name))  # fmt: skip
        req = json.loads(first["qr"])["r"]
        conn, _ = stranger.accept()
        fake = {"t": "response", "req_id": req["req_id"], "phone_id": req["phone_id"], "sig": b64e(b"\0" * 64),
                "box": {"n": b64e(b"\0" * 24), "c": b64e(b"\0" * 48)}}  # fmt: skip
        conn.sendall(json.dumps(fake).encode() + b"\n")
        self.assertIn(b"bad-signature", conn.recv(200))
        conn.close()
        self.phone.unlock(first["qr"])
        thread.join(20)
        self.assertEqual(session.state, "unlocked")
        profiles.lock(self.prof)

    def test_05_a_phone_that_never_answers(self):
        self.pair()
        with mock.patch.object(phone, "REQUEST_TTL", 2):
            session, _first, thread = self.start("unlock", {"autolock": False})
            thread.join(20)
        self.assertEqual(session.state, "unreachable")
        self.assertFalse(profiles.container(self.prof).mounted())

    def test_06_cancel_on_the_desktop_while_the_phone_holds_the_request(self):
        # Found on the real phone (2026-11-10): the phone connects as soon as it shows the request; a cancel
        # on the desktop must end the session at once, so a later approval on the phone opens nothing.
        self.pair()
        holder = socket.socket()
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        self.addCleanup(holder.close)
        address = ("127.0.0.1", holder.getsockname()[1])
        session, _first, thread = self.start("unlock", {"autolock": False}, lambda name: address)
        conn, _ = holder.accept()  # connected, never answers
        self.addCleanup(conn.close)
        self.assertEqual(self.wait_state(session, "approve-on-phone"), "approve-on-phone")
        started = time.monotonic()
        session.handle({"action": "cancel"})
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(session.state, "cancelled")
        self.assertFalse(profiles.container(self.prof).mounted())


@unittest.skipUnless(sodium.available() and storage.tools_available(), "needs gocryptfs, FUSE and libsodium")
class PhoneApiTest(unittest.TestCase):
    """What the browser calls: `nulavio vault api` (the helper is a separate process)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-phone-api-"))
        self.env = {**os.environ, "NULAVIO_HOME": str(self.tmp / "home")}
        patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def api(self, request: dict) -> dict:
        result = subprocess.run([str(ROOT / "bin" / "nulavio"), "vault", "api"], input=json.dumps(request), env=self.env,
                                capture_output=True, text=True, timeout=60, check=True)  # fmt: skip
        return json.loads(result.stdout)

    def test_requests_are_checked(self):
        self.assertIn("phone", self.api({"op": "capabilities"}))
        self.assertEqual(self.api({"op": "phone-session", "session": "nope", "action": "status"}),
                         {"session": "nope", "state": "gone"})  # fmt: skip
        self.assertEqual(self.api({"op": "phone-session", "session": "a/b", "action": "status"}), {"error": "bad-request"})
        self.assertEqual(self.api({"op": "phone-session", "session": "x", "action": "steal"}), {"error": "bad-request"})
        prof, _code = profiles.create("cofre", password=PASSWORD, kdf=FAST, recovery_kdf=FAST)
        self.assertEqual(self.api({"op": "phone-pair-start", "path": str(prof.path), "current": "wrong"}),
                         {"error": "wrong-secret"})  # fmt: skip

    @unittest.skipUnless(
        os.environ.get("NULAVIO_LAN_TESTS") == "1" and shutil.which("avahi-publish") and link.avahi_available(),
        "NULAVIO_LAN_TESTS=1 with Avahi running and avahi-publish (announces on the local network)",
    )
    def test_through_the_real_avahi(self):
        prof, _code = profiles.create("cofre", password=PASSWORD, kdf=FAST, recovery_kdf=FAST)
        linked = LinkedPhone(ReferencePhone("Pixel de teste"), announce="avahi")
        self.addCleanup(linked.close)
        started = self.api({"op": "phone-pair-start", "path": str(prof.path), "current": PASSWORD})
        linked.pair(started["qr"])
        status = lambda: self.api({"op": "phone-session", "session": started["session"], "action": "status"})  # noqa: E731
        deadline = time.monotonic() + 40
        while status()["state"] != "waiting-for-you" and time.monotonic() < deadline:
            time.sleep(0.3)
        self.assertEqual(status()["sas"], linked.sas)
        self.api({"op": "phone-session", "session": started["session"], "action": "confirm", "match": True})
        while status()["state"] not in ("paired", "failed") and time.monotonic() < deadline:
            time.sleep(0.3)
        self.assertEqual(status()["state"], "paired")

        started = self.api({"op": "phone-unlock-start", "path": str(prof.path), "autolock": False})
        linked.unlock(started["qr"])
        while status()["state"] not in ("unlocked", "failed", "unreachable") and time.monotonic() < deadline:
            time.sleep(0.3)
        self.assertEqual(status()["state"], "unlocked")
        self.assertTrue(profiles.container(prof).mounted())
        profiles.lock(prof)
        for dirpath, _dirs, _files in os.walk(self.tmp):
            os.chmod(dirpath, 0o700)


if __name__ == "__main__":
    unittest.main()
