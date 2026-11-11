"""The Flatpak (net.nulavio.Nulavio): what the manifest builds from, and what the sandbox may reach."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
import flatpak_manifest  # noqa: E402

APP = "net.nulavio.Nulavio"
# Permissions that would undo the sandbox: the whole home or host, any D-Bus name, or
# the Flatpak service itself (it can start commands outside the sandbox).
ESCAPES = ("--filesystem=home", "--filesystem=host", "--socket=session-bus", "--socket=system-bus",
           "--talk-name=org.freedesktop.Flatpak", "--filesystem=xdg-config", "--filesystem=~/.nulavio")  # fmt: skip


class FlatpakManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.archive = self.tmp / "nulavio-160.0-0.3.linux-x86_64.tar.xz"
        self.archive.write_bytes(b"tree")
        self.digest = hashlib.sha256(b"tree").hexdigest()

    def render(self, *extra):
        out = self.tmp / "out"
        code = flatpak_manifest.main(["--archive", str(self.archive), "--out", str(out), "--date", "2026-11-11", *extra])
        self.assertEqual(code, 0)
        return out, json.loads((out / f"{APP}.json").read_text(encoding="utf-8"))

    def source(self, manifest):
        return manifest["modules"][0]["sources"][0]

    def test_a_test_build_uses_the_local_archive_with_its_digest(self):
        out, manifest = self.render()
        self.assertEqual(
            self.source(manifest), {"type": "archive", "path": self.archive.name, "sha256": self.digest, "dest": "nulavio"}
        )
        self.assertTrue((out / self.archive.name).is_file())

    def test_the_flathub_manifest_downloads_the_release_asset(self):
        _, manifest = self.render("--url")
        self.assertEqual(
            self.source(manifest)["url"],
            "https://github.com/nulavio/nulavio/releases/download/v160.0-0.3/nulavio-160.0-0.3.linux-x86_64.tar.xz",
        )
        self.assertEqual(self.source(manifest)["sha256"], self.digest)

    def test_sandbox_permissions_never_include_an_escape(self):
        _, manifest = self.render()
        args = manifest["finish-args"]
        for escape in ESCAPES:
            self.assertNotIn(escape, args)
        self.assertFalse([a for a in args if a.startswith("--talk-name=") and a.endswith(".*")])
        self.assertIn("--talk-name=org.freedesktop.NativeMessagingProxy", args)
        self.assertEqual((manifest["id"], manifest["runtime"]), (APP, "org.freedesktop.Platform"))

    def test_desktop_entry_and_metadata_carry_the_app_id_and_this_release(self):
        out, _ = self.render()
        desktop = (out / f"{APP}.desktop").read_text(encoding="utf-8")
        self.assertIn(f"\nIcon={APP}\n", desktop)
        self.assertIn("\nStartupWMClass=nulavio\n", desktop)  # the engine's Wayland app_id
        root = ET.fromstring((out / f"{APP}.metainfo.xml").read_bytes())
        self.assertEqual(root.findtext("id"), APP)
        self.assertEqual(root.findtext("launchable"), f"{APP}.desktop")
        release = root.find("releases/release")
        self.assertEqual((release.get("version"), release.get("date")), ("160.0-0.3", "2026-11-11"))
        for image in root.iter("image"):
            name = image.text.rsplit("/", 1)[1]
            self.assertTrue((ROOT / "site" / "assets" / "flathub" / name).is_file(), name)
        prefs = (out / "flatpak-prefs.js").read_text(encoding="utf-8")
        self.assertIn('pref("widget.use-xdg-desktop-portal.native-messaging-proxy", 1);', prefs)

    def test_refuses_a_file_that_is_not_a_portable_archive(self):
        other = self.tmp / "nulavio-160.0-0.3.fc44.x86_64.rpm"
        other.write_bytes(b"rpm")
        self.assertEqual(flatpak_manifest.main(["--archive", str(other), "--out", str(self.tmp / "o")]), 2)


if __name__ == "__main__":
    unittest.main()
