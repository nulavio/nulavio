"""Nulavio Connect P1/P2: security keys, KDE Connect links, the KRunner plugin (docs/adr/0004)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from nulavio_launcher import connect_p1, krunner  # noqa: E402

FIDO_DESCRIPTOR = bytes([0x06, 0xD0, 0xF1, 0x09, 0x01, 0xA1, 0x01])  # Usage Page (FIDO), Usage (CTAPHID), Collection
KEYBOARD_DESCRIPTOR = bytes([0x05, 0x01, 0x09, 0x06, 0xA1, 0x01])
FAKE_KDECONNECT = """#!/bin/sh
echo "$@" >> "{log}"
case "$1" in
  --list-available) echo "abc123_def Pixel do Caio"; echo "zzz999 Tablet" ;;
  --device) exit 0 ;;
esac
"""


def gi_available() -> bool:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        return True
    except (ImportError, ValueError):
        return False


class SecurityKeysTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-hid-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sysfs, self.dev = self.tmp / "sys", self.tmp / "dev"
        self.dev.mkdir()

    def node(self, name: str, descriptor: bytes, mode: int) -> None:
        (self.sysfs / name / "device").mkdir(parents=True)
        (self.sysfs / name / "device" / "report_descriptor").write_bytes(descriptor)
        (self.dev / name).write_bytes(b"")
        os.chmod(self.dev / name, mode)

    def test_no_key_keyboard_only(self):
        self.node("hidraw0", KEYBOARD_DESCRIPTOR, 0o600)
        status = connect_p1.security_keys({"id": "security-keys", "priority": "P1"}, self.sysfs, self.dev)
        self.assertEqual(status.state, "unavailable")

    def test_usable_key(self):
        self.node("hidraw0", KEYBOARD_DESCRIPTOR, 0o600)
        self.node("hidraw3", FIDO_DESCRIPTOR, 0o600)
        status = connect_p1.security_keys({"id": "security-keys", "priority": "P1"}, self.sysfs, self.dev)
        self.assertEqual(status.state, "available")
        self.assertEqual(status.evidence, ["hidraw3: FIDO usage page, readable"])

    @unittest.skipIf(os.geteuid() == 0, "root can open any device")
    def test_key_without_permission(self):
        self.node("hidraw3", FIDO_DESCRIPTOR, 0o000)
        status = connect_p1.security_keys({"id": "security-keys", "priority": "P1"}, self.sysfs, self.dev)
        self.assertEqual(status.state, "error")
        self.assertIn("udev", status.detail)


class KdeConnectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-kdec-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = self.tmp / "calls.log"
        tool = self.tmp / "bin" / "kdeconnect-cli"
        tool.parent.mkdir()
        tool.write_text(FAKE_KDECONNECT.format(log=self.log))
        tool.chmod(0o700)
        patcher = mock.patch.dict(os.environ, {"PATH": f"{tool.parent}:/usr/bin:/bin"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_devices_and_one_link_to_one_device(self):
        self.assertEqual(
            connect_p1.devices(), [{"id": "abc123_def", "name": "Pixel do Caio"}, {"id": "zzz999", "name": "Tablet"}]
        )
        self.assertEqual(connect_p1.send_link("https://example.org/a?b=1", "abc123_def"), {"sent": True, "device": "abc123_def"})
        calls = self.log.read_text().splitlines()
        self.assertEqual(calls[-1], "--device abc123_def --share https://example.org/a?b=1")

    def test_refusals(self):
        for url, device, code in (
            ("file:///etc/passwd", "abc123_def", "bad-url"),
            ("javascript:alert(1)", "abc123_def", "bad-url"),
            ("https://example.org", "../x", "bad-device"),
            ("https://example.org", "not_paired", "device-unreachable"),
        ):
            with self.subTest(url=url, device=device), self.assertRaises(connect_p1.ConnectP1Error) as caught:
                connect_p1.send_link(url, device)
            self.assertEqual(caught.exception.code, code)
        self.assertNotIn("--share", self.log.read_text())  # nothing was sent


class KrunnerTest(unittest.TestCase):
    def test_matches(self):
        self.assertEqual(krunner.matches("https://example.org/x")[0][0], "open:https://example.org/x")
        self.assertEqual(krunner.matches("example.org")[0][0], "open:https://example.org")
        self.assertEqual(krunner.matches("nulavio privacy news")[0][0], "search:privacy news")
        for nothing in ("hello", "rm -rf /", "file:///etc", "javascript:alert(1)", "two words.com x"):
            with self.subTest(nothing):
                self.assertEqual(krunner.matches(nothing), [])

    def test_commands_are_argument_lists_for_web_addresses_only(self):
        with mock.patch.dict(os.environ, {"NULAVIO_KRUNNER_COMMAND": "/opt/nulavio/nulavio"}):
            self.assertEqual(krunner.command("open:https://example.org"), ["/opt/nulavio/nulavio", "https://example.org"])
            self.assertEqual(krunner.command("search:a b"), ["/opt/nulavio/nulavio", "--search", "a b"])
            for bad in ("open:file:///etc/passwd", "open:javascript:x", "open:https://a b", "exec:ls", "search:"):
                with self.subTest(bad):
                    self.assertIsNone(krunner.command(bad))

    def test_plugin_files_are_user_level_and_removable(self):
        tmp = Path(tempfile.mkdtemp(prefix="nv-krunner-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        with (
            mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(tmp)}),
            mock.patch.object(connect_p1, "_gi_available", return_value=True),
        ):
            written = connect_p1.krunner_enable()
            plugin, service = connect_p1.krunner_files()
            self.assertEqual(sorted(written), sorted([str(plugin), str(service)]))
            self.assertTrue(str(plugin).startswith(str(tmp)))
            self.assertIn("X-Plasma-DBusRunner-Service=net.nulavio.krunner", plugin.read_text())
            self.assertIn("integrations krunner-serve", service.read_text())
            self.assertEqual(connect_p1.krunner({"id": "krunner", "priority": "P1"}).state, "enabled")
            self.assertEqual(sorted(connect_p1.krunner_disable()), sorted(written))
            self.assertFalse(plugin.exists() or service.exists())

    @unittest.skipUnless(
        gi_available() and shutil.which("dbus-daemon") and shutil.which("gdbus"), "needs GLib bindings, dbus-daemon, gdbus"
    )
    def test_runner_answers_krunner_on_the_session_bus(self):
        from harness import private_bus_config

        tmp = Path(tempfile.mkdtemp(prefix="nv-krunner-bus-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "run").mkdir(mode=0o700)
        (tmp / "dbus.conf").write_text(private_bus_config(tmp / "run" / "bus"))
        record = tmp / "opened.json"
        opener = tmp / "nulavio"
        opener.write_text(
            f"#!{sys.executable} -I\nimport json, sys\nopen({str(record)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        )
        opener.chmod(0o700)
        env = {
            **os.environ,
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={tmp / 'run' / 'bus'}",
            "NULAVIO_KRUNNER_COMMAND": str(opener),
        }
        bus = subprocess.Popen(["dbus-daemon", f"--config-file={tmp / 'dbus.conf'}", "--nofork", "--nopidfile"],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        self.addCleanup(lambda: (bus.kill(), bus.wait()))
        deadline = time.monotonic() + 10
        while not (tmp / "run" / "bus").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        runner = subprocess.Popen([str(ROOT / "bin" / "nulavio"), "integrations", "krunner-serve"], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
        self.addCleanup(lambda: (runner.kill(), runner.wait()))

        def call(method: str, *args: str) -> str:
            return subprocess.run(
                ["gdbus", "call", "--session", "--dest", "net.nulavio.krunner", "--object-path", "/runner",
                 "--method", f"org.kde.krunner1.{method}", *args],
                env=env, capture_output=True, text=True, timeout=10, check=False,
            ).stdout  # fmt: skip

        deadline = time.monotonic() + 15
        answer = ""
        while time.monotonic() < deadline and "open:" not in answer:
            answer = call("Match", "example.org")
            time.sleep(0.2)
        self.assertIn("open:https://example.org", answer)
        self.assertIn("Open https://example.org in Nulavio", answer)
        self.assertIn("@a(sssida{sv}) []", call("Match", "just words"))
        call("Run", "open:https://example.org", "")
        deadline = time.monotonic() + 10
        while not record.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(json.loads(record.read_text()), ["https://example.org"])


if __name__ == "__main__":
    unittest.main()
