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
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fake_avahi import FAKE_BUSCTL
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

    def received(self, data: bytes, count: int = 1) -> list:
        """What recv makes of `data`, sent at once: each message or the LinkError's code, `count` times."""
        channel, peer = self.channel_pair()
        peer.sendall(data)
        results = []
        for _ in range(count):
            try:
                results.append(channel.recv(time.monotonic() + 2))
            except link.LinkError as exc:
                results.append(exc.code)
        return results

    def test_every_line_is_held_to_the_cap(self):
        # #687: the cap was checked only while no newline had arrived, so the chunk that ends a line could carry it
        # up to 4 KiB past MAX_LINE (a 19 400-byte line was accepted).
        def line(size: int) -> bytes:
            prefix = b'{"p":"'
            suffix = b'","t":"x"}'
            return prefix + b"x" * (size - len(prefix) - len(suffix)) + suffix + b"\n"

        self.assertEqual(len(line(link.MAX_LINE)), link.MAX_LINE + 1)
        self.assertEqual(self.received(line(link.MAX_LINE))[0]["t"], "x")
        self.assertEqual(self.received(line(link.MAX_LINE + 1)), ["too-large"])
        self.assertEqual(self.received(line(19_400)), ["too-large"])
        # A good message, then an oversized one behind it in the same stream.
        self.assertEqual(self.received(b'{"t":"ok"}\n' + line(19_400), 2), [{"t": "ok"}, "too-large"])

    def test_a_line_the_parser_chokes_on_is_a_bad_message(self):
        # #687: an error of the JSON decoder other than ValueError left recv and ended the unlock helper (U-T29).
        # Python 3.12 gives up at a depth of about 10 000 (a 20 000-byte line, which only the cap refuses now);
        # 3.14 parses it. A deep line under the cap is refused as a bad message on both.
        self.assertEqual(self.received(b"[" * 9_998 + b"]" * 9_998 + b"\n"), ["too-large"])
        self.assertEqual(self.received(b"[" * 8_000 + b"]" * 8_000 + b"\n"), ["bad-message"])
        with mock.patch.object(link.json, "loads", side_effect=RecursionError):
            self.assertEqual(self.received(b'{"t":"ok"}\n'), ["bad-message"])

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

    def test_01a_an_unlock_whose_lock_watcher_cannot_start_is_locked_again(self):
        # #325: the watcher that locks the profile when its browser closes could not be started (EMFILE, an
        # interpreter gone during an upgrade). The profile does not stay open while the session says it failed.
        self.pair()
        errors = []
        spawn = mock.patch("nulavio_launcher.vault.cli.spawn_autolock", side_effect=OSError(24, "Too many open files"))
        hook = mock.patch.object(threading, "excepthook", lambda args: errors.append(args.exc_type))
        with spawn, hook:
            session, first, thread = self.start("unlock", {})
            phone = self.phone.unlock(first["qr"])
            thread.join(20)
            phone.join(20)
        self.assertEqual(errors, [OSError])  # out of unlock(), to main(), which reports a session that failed
        self.assertNotEqual(session.state, "unlocked")
        self.assertFalse(profiles.container(self.prof).mounted())

    def test_01b_a_pairing_saved_but_not_recorded_says_so(self):
        # #177: the phone is paired (the key file is saved); the record inside the profile failed.
        with mock.patch("nulavio_launcher.vault.cli._record", return_value=True):
            session, first, thread = self.start("pair", {"current": PASSWORD})
            phone = self.phone.pair(first["qr"])
            self.assertEqual(self.wait_state(session, "waiting-for-you", "failed"), "waiting-for-you")
            session.handle({"action": "confirm", "match": True})
            thread.join(20)
            phone.join(20)
        self.assertEqual(session.status()["state"], "paired")
        self.assertEqual(session.status()["warning"], "not-recorded")
        self.assertEqual(self.phone_methods(), ["phone"])

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

    def test_02a_a_phone_of_another_pairing_version_is_told_so(self):
        class OtherVersion(ReferencePhone):
            def scan(self, qr):
                return dict(super().scan(qr), v=1)

        other = LinkedPhone(OtherVersion("Antigo"))
        self.addCleanup(other.close)
        session, first, thread = self.start("pair", {"current": PASSWORD}, other.resolver)
        phone = other.pair(first["qr"])
        thread.join(20)
        phone.join(20)
        self.assertEqual((session.state, session.error), ("failed", "unsupported-version"))
        self.assertNotIn("sas", session.status())
        self.assertEqual(other.result, {"t": "error", "code": "unsupported-version"})
        self.assertIsNone(other.sas)
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

    def test_04a_lines_past_the_cap_or_the_parser_are_skipped(self):
        # #687 (U-T29): a stranger's oversized answer, and a line the JSON decoder raises on, end that connection
        # only. The desktop answers neither and keeps resolving; the phone then unlocks in the same helper.
        self.pair()
        stranger = socket.socket()
        stranger.bind(("127.0.0.1", 0))
        stranger.listen(3)
        stranger.settimeout(10)  # a helper that died does not connect again
        self.addCleanup(stranger.close)
        answers = iter([("127.0.0.1", stranger.getsockname()[1])] * 3)
        real_loads = json.loads

        def loads(data, *args, **kwargs):
            if isinstance(data, bytes) and data.startswith(b"[[["):
                raise RecursionError("maximum recursion depth exceeded")  # what Python 3.12 does with a deep line
            return real_loads(data, *args, **kwargs)

        with mock.patch.object(link.json, "loads", side_effect=loads):
            session, first, thread = self.start("unlock", {"autolock": False},
                                                lambda name: next(answers, None) or self.phone.resolver(name))  # fmt: skip
            req = json.loads(first["qr"])["r"]
            oversized = {"t": "response", "req_id": req["req_id"], "phone_id": req["phone_id"], "sig": b64e(b"\0" * 64),
                         "box": {"n": b64e(b"\0" * 24), "c": b64e(b"\0" * 48)}, "pad": "x" * 19_400}  # fmt: skip
            for line in (json.dumps(oversized).encode(), b"[" * 9_998 + b"]" * 9_998, b"[" * 100 + b"]" * 100):
                conn, _ = stranger.accept()
                with conn:
                    conn.settimeout(10)
                    try:
                        conn.sendall(line + b"\n")
                        reply = conn.recv(200)
                    except ConnectionError:
                        # The desktop may close past the cap while the tail is still being written: a reset or
                        # a broken pipe on either call. A timeout still fails the test.
                        reply = b""
                with self.subTest(line=line[:12]):
                    self.assertEqual(reply, b"")  # no answer, not even "bad-signature": the line was never read
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

    def test_06a_a_cancel_while_the_approved_unlock_waits_for_the_state_lock_opens_nothing(self):
        # #783 review, round 3: the phone approves while the profile is open and its auto-lock watcher is closing
        # it under the state lock. The person cancels on the desktop while the helper waits for that lock: once the
        # watcher has unmounted, the helper opens nothing, says "cancelled", and tells the phone.
        self.pair()
        profiles.unlock(self.prof, password=PASSWORD).lock()
        box = profiles.container(self.prof)
        held, release, waiting = threading.Event(), threading.Event(), threading.Event()

        def watcher() -> None:
            with box._state_lock():
                held.set()
                release.wait(20)
                box.unmount()

        closing = threading.Thread(target=watcher, daemon=True)
        closing.start()
        self.assertTrue(held.wait(20))
        real_lock = storage.Container._state_lock

        def lock(container, *args, **kwargs):
            if threading.current_thread() is not closing:
                waiting.set()  # the helper's mount, at the state lock the watcher holds
            return real_lock(container, *args, **kwargs)

        with mock.patch.object(storage.Container, "_state_lock", lock):
            session, first, thread = self.start("unlock", {"autolock": False})
            phone = self.phone.unlock(first["qr"])
            self.assertTrue(waiting.wait(20))
            session.handle({"action": "cancel"})
            release.set()
            closing.join(30)
            thread.join(30)
            phone.join(20)
        self.assertFalse(thread.is_alive())
        self.assertEqual(session.state, "cancelled")
        self.assertEqual(self.phone.result, {"t": "error", "code": "cancelled"})
        self.assertFalse(profiles.container(self.prof).mounted())

    def test_07_a_second_unlock_request_leaves_the_first_unable_to_open_the_profile(self):
        # #669 (U-T19): one pending phone request per profile. These sessions serve no control socket, so the new
        # request cannot tell the first one to stop: only the profile's record of its pending request does. The
        # phone approves the first QR after the second was shown: the first helper opens nothing, says
        # "cancelled" and tells the phone; the second still unlocks.
        self.pair()
        first_session, first, first_thread = self.start("unlock", {"autolock": False})
        second_session, second, second_thread = self.start("unlock", {"autolock": False})
        self.assertNotEqual(json.loads(first["qr"])["r"]["req_id"], json.loads(second["qr"])["r"]["req_id"])
        phone = self.phone.unlock(first["qr"])
        first_thread.join(20)
        phone.join(20)
        self.assertFalse(first_thread.is_alive())
        self.assertEqual(first_session.state, "cancelled")
        self.assertEqual(self.phone.result, {"t": "error", "code": "cancelled"})
        self.assertFalse(profiles.container(self.prof).mounted())

        phone = self.phone.unlock(second["qr"])
        second_thread.join(20)
        phone.join(20)
        self.assertEqual(second_session.state, "unlocked")
        self.assertEqual(self.phone.result, {"t": "ok"})
        self.assertTrue(profiles.container(self.prof).mounted())
        profiles.lock(self.prof)

    def test_07a_only_the_helper_whose_own_record_was_replaced_stops(self):
        # #823 review: a copy of the profile's folder, taken while this request waits, carries the record naming
        # this session. A request started on that copy must not end this one: the helper stops only when its own
        # profile's record names another session.
        self.pair()
        session, _first, thread = self.start("unlock", {"autolock": False})
        server = phone_session._serve(session, phone_session.socket_path(session.id))
        self.addCleanup(phone_session.socket_path(session.id).unlink, missing_ok=True)
        self.addCleanup(server.close)
        phone_session._end_replaced(session.id, "the-copys-session")  # what the copy's helper does
        time.sleep(0.5)
        self.assertFalse(session.cancelled.is_set())
        self.assertEqual(session.state, "waiting-for-phone")

        phone_session.claim_request(profiles.container(self.prof), "a-later-session")  # now it was replaced
        phone_session._end_replaced(session.id, "a-later-session")
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(session.state, "cancelled")
        self.assertFalse(profiles.container(self.prof).mounted())

    def test_07b_a_cancel_during_the_last_record_check_opens_nothing(self):
        # #823 review: the cancel is asked after the record, so one that comes while the record is read still counts.
        self.pair()
        cancelled = []
        real = phone_session.is_current_request

        def current(box, session_id):
            answer = real(box, session_id)
            cancelled[0].set()  # the person presses Cancel while the record is being read
            return answer

        with mock.patch.object(phone_session, "is_current_request", current):
            session, first, thread = self.start("unlock", {"autolock": False})
            cancelled.append(session.cancelled)
            phone = self.phone.unlock(first["qr"])
            thread.join(20)
            phone.join(20)
        self.assertEqual(session.state, "cancelled")
        self.assertEqual(self.phone.result, {"t": "error", "code": "cancelled"})
        self.assertFalse(profiles.container(self.prof).mounted())

    def test_07c_a_record_that_cannot_be_written_wipes_the_pending_request(self):
        # #823 review: no QR, and the request's session key (and a combined unlock's password key) wiped (I8).
        self.pair()
        made = []
        real_init = phone_session.Coordinator.__init__

        def init(coordinator, *args, **kwargs):
            real_init(coordinator, *args, **kwargs)
            made.append(coordinator)

        answers = []
        failing = mock.patch.object(phone_session, "claim_request", side_effect=OSError(28, "No space left on device"))
        with mock.patch.object(phone_session.Coordinator, "__init__", init), failing:
            phone_session.unlock(phone_session.Session("unlock"), {"path": str(self.prof.path)}, answers.append,
                                 self.phone.resolver)  # fmt: skip
        self.assertEqual(answers, [{"error": "storage-failed"}])
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].phone.pending, {})
        self.assertIsNone(made[0]._password_kek)
        self.assertFalse(profiles.container(self.prof).mounted())

    def test_07d_a_request_lock_that_is_not_a_private_file_is_refused(self):
        # #823 review (I9): something other than this user's regular file at the lock's place is not used.
        box = profiles.container(self.prof)
        os.mkfifo(box.root / f"{phone_session.REQUEST_RECORD}.lock", 0o600)
        with self.assertRaises(phone_session.paths.UnsafePathError):
            phone_session.claim_request(box, "a-session")
        self.assertFalse(phone_session.is_current_request(box, "a-session"))
        self.assertFalse((box.root / phone_session.REQUEST_RECORD).exists())


@unittest.skipUnless(sodium.available() and storage.tools_available(), "needs gocryptfs, FUSE and libsodium")
class PhoneApiTest(unittest.TestCase):
    """What the browser calls: `nulavio vault api` (the helper is a separate process)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-phone-api-"))
        self.env = {**os.environ, "NULAVIO_HOME": str(self.tmp / "home")}
        patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.tmp / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        tool = shutil.which("fusermount3") or "fusermount"  # what storage.tools_available() accepts
        for mountpoint in sorted(storage.mounted_paths()):
            if mountpoint.startswith(str(self.tmp)):
                subprocess.run([tool, "-u", "-z", mountpoint], check=False, capture_output=True)
        for dirpath, _dirs, _files in os.walk(self.tmp):
            os.chmod(dirpath, 0o700)
        shutil.rmtree(self.tmp, ignore_errors=True)

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

    def status(self, session: str) -> dict:
        return self.api({"op": "phone-session", "session": session, "action": "status"})

    def wait_status(self, session: str, *states: str, timeout: float = 30) -> dict:
        deadline = time.monotonic() + timeout
        status = self.status(session)
        while status.get("state") not in states and time.monotonic() < deadline:
            time.sleep(0.2)
            status = self.status(session)
        return status

    def test_a_second_unlock_start_ends_the_first_helpers_request(self):
        # #669 (U-T19): each `phone-unlock-start` starts a helper process of its own. The second one ends the
        # first one's request for the same profile, and only the second QR can open the profile. The phone is found
        # through a stand-in for Avahi (tests/lib/fake_avahi.py), as in test_vault_ui, so nothing is announced.
        prof, _code = profiles.create("cofre", password=PASSWORD, kdf=FAST, recovery_kdf=FAST)
        busctl, registry = self.tmp / "busctl", self.tmp / "avahi.json"
        # Through /bin/sh, not a #! line naming Python: that line cannot hold a path with a space in it.
        (self.tmp / "busctl.py").write_text(FAKE_BUSCTL.format(python=sys.executable))
        busctl.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -I {shlex.quote(str(self.tmp / "busctl.py"))} "$@"\n')
        busctl.chmod(0o700)
        registry.write_text("{}")
        self.env.update({"NULAVIO_BUSCTL": str(busctl), "NV_FAKE_AVAHI": str(registry)})
        linked = LinkedPhone(ReferencePhone("Pixel de teste"), registry=registry)
        self.addCleanup(linked.close)
        started = self.api({"op": "phone-pair-start", "path": str(prof.path), "current": PASSWORD})
        linked.pair(started["qr"])
        self.assertEqual(self.wait_status(started["session"], "waiting-for-you", "failed")["sas"], linked.sas)
        self.api({"op": "phone-session", "session": started["session"], "action": "confirm", "match": True})
        self.assertEqual(self.wait_status(started["session"], "paired", "failed")["state"], "paired")

        first = self.api({"op": "phone-unlock-start", "path": str(prof.path), "autolock": False})
        self.assertEqual(self.status(first["session"])["state"], "waiting-for-phone")
        second = self.api({"op": "phone-unlock-start", "path": str(prof.path), "autolock": False})
        self.assertNotEqual(first["session"], second["session"])
        # The first helper is told at once: its page shows "cancelled" without anyone pressing Cancel there.
        self.assertEqual(self.wait_status(first["session"], "cancelled", "unlocked", "failed")["state"], "cancelled")
        self.assertEqual(self.status(second["session"])["state"], "waiting-for-phone")
        self.assertFalse(profiles.container(prof).mounted())

        phone = linked.unlock(second["qr"])
        self.assertEqual(self.wait_status(second["session"], "unlocked", "failed", "unreachable")["state"], "unlocked")
        phone.join(20)
        self.assertEqual(linked.result, {"t": "ok"})
        self.assertTrue(profiles.container(prof).mounted())
        profiles.lock(prof)

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
