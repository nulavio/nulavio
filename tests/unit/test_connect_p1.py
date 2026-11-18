"""Nulavio Connect P1/P2: security keys and KDE Connect links (docs/adr/0004); the KRunner plugin is gone (#461)."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from nulavio_launcher import connect_p1  # noqa: E402

FIDO_DESCRIPTOR = bytes([0x06, 0xD0, 0xF1, 0x09, 0x01, 0xA1, 0x01])  # Usage Page (FIDO), Usage (CTAPHID), Collection
KEYBOARD_DESCRIPTOR = bytes([0x05, 0x01, 0x09, 0x06, 0xA1, 0x01])
FAKE_KDECONNECT = """#!/bin/sh
echo "$@" >> "{log}"
case "$1" in
  --list-available) echo "abc123_def Pixel do Caio"; echo "zzz999 Tablet" ;;
  --device) exit 0 ;;
esac
"""


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

    def test_devices_for_the_status_row_and_no_link_is_sent(self):
        # The KDE Connect status row still lists the reachable devices; sending a link to one was removed (#462).
        self.assertEqual(
            connect_p1.devices(), [{"id": "abc123_def", "name": "Pixel do Caio"}, {"id": "zzz999", "name": "Tablet"}]
        )
        self.assertFalse(hasattr(connect_p1, "send_link"))
        for op in ("send-link", "devices"):
            with self.subTest(op=op), self.assertRaises(connect_p1.ConnectP1Error):
                connect_p1.api_request({"op": op, "url": "https://example.org/a", "device": "abc123_def"})
        self.assertNotIn("--share", self.log.read_text())


class KrunnerRemovedTest(unittest.TestCase):
    def test_the_krunner_plugin_is_gone(self):
        # #461: KDE's own runners open an address or a web-search keyword in the default browser.
        from nulavio_launcher import cli

        self.assertFalse((ROOT / "launcher" / "nulavio_launcher" / "krunner.py").exists())
        self.assertNotIn("krunner", connect_p1.PROBES)
        with self.assertRaises(connect_p1.ConnectP1Error):
            connect_p1.api_request({"op": "krunner-enable"})
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["integrations", "krunner-serve"])


if __name__ == "__main__":
    unittest.main()
