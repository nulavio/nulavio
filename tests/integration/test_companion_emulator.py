"""The Companion app on an Android emulator against the real desktop code (S11). Opt-in.

    NULAVIO_EMULATOR=1 python3 tests/integration/test_companion_emulator.py

Needs a running emulator (or device) visible to adb and the debug APK
(android/app/build/outputs/apk/debug/app-debug.apk). On an emulator the test
sets an artificial screen-lock PIN and types it into the system's credential
screen. On a real phone it never touches the lock settings: it asks the person
holding the phone to approve with their own fingerprint, face or PIN, and
waits. Either way it drives the app through adb (taps found in the UI dump)
and hands it the codes through the debug build's intent extra, because an
emulator cannot film the desktop's screen. The emulator is behind NAT, so its listening port is
forwarded with adb and the desktop's resolver points at the forward; on a real
phone the desktop finds it through Avahi instead. Desktop side: real encrypted
profiles (gocryptfs) in a temporary NULAVIO_HOME, artificial secrets.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from nulavio_launcher.vault import link, phone_session, profiles, sodium, storage  # noqa: E402

APK = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
PACKAGE = "net.nulavio.companion"
PIN = "4826"
FAST = {"ops": 1, "mem": 8 * 1024 * 1024}
PASSWORD = "artificial password 9"
ADB = shutil.which("adb") or str(Path.home() / "Android" / "Sdk" / "platform-tools" / "adb")


def adb(*args: str, check: bool = True, timeout: float = 60) -> str:
    result = subprocess.run([ADB, *args], capture_output=True, text=True, timeout=timeout, check=False)
    if check and result.returncode != 0:
        raise AssertionError(f"adb {' '.join(args[:3])}: {result.stderr.strip()[-300:]}")
    return result.stdout


def device_ready() -> bool:
    if os.environ.get("NULAVIO_EMULATOR") != "1" or not Path(ADB).exists() or not APK.is_file():
        return False
    try:
        return adb("get-state", check=False, timeout=10).strip() == "device"
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(
    device_ready() and sodium.available() and storage.tools_available(),
    "NULAVIO_EMULATOR=1, a device on adb, the debug APK, gocryptfs and libsodium",
)
class CompanionOnEmulatorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="nv-emulator-"))
        cls.env = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(cls.tmp / "home")})
        cls.env.start()
        cls.prof, _code = profiles.create("cofre", password=PASSWORD, kdf=FAST, recovery_kdf=FAST)
        cls.names: dict[str, tuple[str, int]] = {}
        cls.emulator = adb("shell", "getprop", "ro.kernel.qemu", check=False).strip() == "1"
        adb("install", "-r", "-t", str(APK), timeout=180)
        adb("shell", "pm", "clear", PACKAGE)  # this app's own data only
        adb("shell", "pm", "grant", PACKAGE, "android.permission.ACCESS_LOCAL_NETWORK", check=False)
        if cls.emulator:
            # A screen lock is what protects the keys; an artificial PIN, on the emulator only.
            adb("shell", "locksettings", "clear", "--old", PIN, check=False)
            adb("shell", "locksettings", "set-pin", PIN)
        adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")

    @classmethod
    def tearDownClass(cls):
        try:
            for mountpoint in sorted(storage.mounted_paths()):
                if mountpoint.startswith(str(cls.tmp)):
                    subprocess.run(["fusermount3", "-u", "-z", mountpoint], check=False, capture_output=True)
            adb("forward", "--remove-all", check=False)
            if cls.emulator:
                adb("shell", "locksettings", "clear", "--old", PIN, check=False)
        finally:
            cls.env.stop()
            for dirpath, _dirs, _files in os.walk(cls.tmp):
                os.chmod(dirpath, 0o700)
            shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- driving the phone -----------------------------------------------------------------

    def ui(self) -> list[dict]:
        adb("shell", "uiautomator", "dump", "/sdcard/nv1-ui.xml")
        tree = ET.fromstring(adb("exec-out", "cat", "/sdcard/nv1-ui.xml"))
        nodes = []
        for node in tree.iter("node"):
            x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds", "[0,0][0,0]")))
            nodes.append({"text": node.get("text", ""), "desc": node.get("content-desc", ""),
                          "x": (x1 + x2) // 2, "y": (y1 + y2) // 2})  # fmt: skip
        return nodes

    def wait_text(self, needle: str, timeout: float = 60) -> dict:
        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while time.monotonic() < deadline:
            nodes = self.ui()
            seen = [n["text"] for n in nodes if n["text"]]
            for node in nodes:
                if needle.lower() in node["text"].lower():
                    return node
            time.sleep(0.5)
        raise AssertionError(f"{needle!r} not on screen; saw {seen}")

    def tap(self, needle: str, timeout: float = 30) -> None:
        node = self.wait_text(needle, timeout)
        # A button whose label is exactly the needle wins over a title that only contains it
        # ("Unlock" vs "Unlock “cofre” on vaio?").
        exact = [n for n in self.ui() if n["text"].lower() == needle.lower()]
        node = exact[0] if exact else node
        adb("shell", "input", "tap", str(node["x"]), str(node["y"]))

    def enter_pin(self) -> None:
        if not self.emulator:
            print("\n>>> Approve on the phone with your fingerprint, face or screen lock.", flush=True)
            return  # the next wait gives the person time to answer
        time.sleep(2)  # the system's credential screen
        adb("shell", "input", "text", PIN)
        adb("shell", "input", "keyevent", "KEYCODE_ENTER")

    def hand_code(self, qr: str) -> None:
        adb("logcat", "-c")
        adb("shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity", "--es", "nv1.qr", shlex.quote(qr))

    def forward_listening_port(self, name: str, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for line in adb("logcat", "-d", "-s", "nv1:I").splitlines():
                match = re.search(r"listening (\d+) (\S+)", line)
                if match and match.group(2) == name:
                    host_port = int(adb("forward", "tcp:0", f"tcp:{match.group(1)}").strip())
                    self.names[name] = ("127.0.0.1", host_port)
                    return
            time.sleep(0.5)
        raise AssertionError(f"the app did not listen for {name}")

    # -- the desktop -----------------------------------------------------------------------

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

    def wait_state(self, session, *states, timeout=60):
        deadline = time.monotonic() + timeout
        while session.state not in states and time.monotonic() < deadline:
            time.sleep(0.2)
        return session.state

    # -- the steps --------------------------------------------------------------------------

    def test_01_set_up_creates_keys_behind_the_screen_lock(self):
        adb("shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")
        self.tap("Set up this phone")
        self.enter_pin()
        self.wait_text("Computers")
        level = self.wait_text("Keys protected")["text"]
        self.assertTrue(level)  # STRONGBOX, TEE or software: shown as the Keystore reports it

    def test_02_pairing_shows_the_same_digits_on_both_sides(self):
        session, first, thread = self.start("pair", {"current": PASSWORD})
        invite = json.loads(first["qr"])
        self.hand_code(first["qr"])
        self.forward_listening_port(link.instance_name("p", invite["i"]))
        self.assertEqual(self.wait_state(session, "compare", "failed"), "compare")
        digits = session.status()["sas"]
        self.wait_text(f"{digits[:3]} {digits[3:]}")  # the phone shows the same 6 digits
        session.handle({"action": "confirm", "match": True})
        self.tap("They match")
        self.enter_pin()
        self.wait_text("Paired with")
        thread.join(30)
        self.assertEqual(session.state, "paired")

    def test_03_unlock_with_the_phone_mounts_the_profile(self):
        session, first, thread = self.start("unlock", {"autolock": False})
        signed = json.loads(first["qr"])
        type(self).answered = first["qr"]
        self.hand_code(first["qr"])
        self.wait_text("cofre")
        self.forward_listening_port(link.instance_name("u", signed["r"]["req_id"]))
        self.tap("Unlock")
        self.enter_pin()
        self.wait_text("is unlocked")
        thread.join(30)
        self.assertEqual(session.state, "unlocked")
        self.assertTrue(profiles.container(self.prof).mounted())
        profiles.lock(self.prof)

    def test_04_an_answered_request_is_refused_again(self):
        self.hand_code(self.answered)
        self.wait_text("already answered")

    def test_05_not_now_sends_nothing(self):
        session, first, thread = self.start("unlock", {"autolock": False})
        self.hand_code(first["qr"])
        self.tap("Not now")
        time.sleep(3)
        # The phone connects as soon as it shows the request (emulator: not forwarded here), so the computer
        # may already show "approve on your phone"; either way nothing was sent.
        self.assertIn(session.state, ("waiting-for-phone", "approve-on-phone"))
        session.handle({"action": "cancel"})
        thread.join(30)
        self.assertEqual(session.state, "cancelled")
        self.assertFalse(profiles.container(self.prof).mounted())


if __name__ == "__main__":
    unittest.main()
