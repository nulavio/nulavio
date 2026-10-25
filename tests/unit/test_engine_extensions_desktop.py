"""Engine command construction, extension integrity, desktop integration."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import desktop, engine, extensions  # noqa: E402

FAKE_ENGINE = engine.Engine(path=Path("/usr/lib64/firefox/firefox"), version="158.0.1", vendor="Mozilla Firefox")


class EngineCommandTest(unittest.TestCase):
    def test_command_has_identity_and_no_remote_control(self):
        cmd = engine.build_command(FAKE_ENGINE, Path("/p"), url="https://example.org/")
        self.assertEqual(cmd[:3], [str(FAKE_ENGINE.path), "--profile", "/p"])
        self.assertIn("--name", cmd)
        self.assertEqual(cmd[cmd.index("--name") + 1], engine.APP_ID)
        self.assertEqual(cmd[-1], "https://example.org/")
        self.assertFalse(engine.FORBIDDEN_FLAGS.intersection(cmd))

    def test_private_window(self):
        cmd = engine.build_command(FAKE_ENGINE, Path("/p"), private=True)
        self.assertIn("--private-window", cmd)

    def test_dangerous_urls_are_rejected(self):
        for url in (
            "--marionette",
            "-jsconsole",
            "javascript:alert(1)",
            "data:text/html,x",
            "about:config",
            "moz-extension://x/y",
            "https://",
            "https://a.b/\nx",
            "chrome://browser/content/browser.xhtml",
        ):
            with self.subTest(url=url), self.assertRaises(engine.EngineError):
                engine.build_command(FAKE_ENGINE, Path("/p"), url=url)

    def test_env_strips_sandbox_and_remote_knobs(self):
        hostile = {
            "MOZ_DISABLE_CONTENT_SANDBOX": "1",
            "MOZ_DISABLE_RDD_SANDBOX": "1",
            "MOZ_SANDBOX_LOGGING": "1",
            "MOZ_MARIONETTE": "1",
            "MOZ_REMOTE_SETTINGS_DEVTOOLS": "1",
            "MOZ_HEADLESS": "1",
            "MOZ_ALLOW_DOWNGRADE": "1",
            "WAYLAND_DISPLAY": "wayland-0",
        }
        with mock.patch.dict(os.environ, hostile):
            env = engine.launch_env()
        for key in hostile:
            if key != "WAYLAND_DISPLAY":
                self.assertNotIn(key, env)
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-0")
        self.assertEqual(env["MOZ_APP_REMOTINGNAME"], engine.APP_ID)

    def test_version_output_parsing(self):
        self.assertEqual(engine.parse_version_output("Mozilla Firefox 158.0.1\n"), ("Mozilla Firefox", "158.0.1"))
        self.assertEqual(engine.parse_version_output("Nulavio Nulavio 158.0.1\n"), ("Nulavio", "158.0.1"))
        self.assertEqual(engine.parse_version_output("Mozilla Firefox 140.4.0esr"), ("Mozilla Firefox", "140.4.0esr"))
        for bad in ("", "Chromium 140.0", "Mozilla Firefox", "evil 1.0\nMozilla Firefoxx 158"):
            with self.subTest(bad=bad), self.assertRaises(engine.EngineError):
                engine.parse_version_output(bad)

    def test_version_floor(self):
        engine.check_supported(FAKE_ENGINE)
        with self.assertRaises(engine.EngineError):
            engine.check_supported(replace(FAKE_ENGINE, version="115.0esr"))

    def test_snap_engine_is_refused(self):
        with (
            mock.patch.dict(os.environ, {"NULAVIO_ENGINE": "/snap/bin/firefox"}),
            mock.patch.object(Path, "resolve", lambda self: Path("/snap/firefox/current/usr/lib/firefox/firefox")),
            self.assertRaises(engine.EngineError),
        ):
            engine.find_engine()


class ExtensionLockTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(Path(self._tmp.name) / "home")})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_lock_is_well_formed(self):
        lock = extensions.load_lock()
        self.assertIn("ublock-origin", lock)
        self.assertTrue(lock["ublock-origin"].default_install)
        defaults = [e.key for e in lock.values() if e.default_install]
        self.assertEqual(defaults, ["ublock-origin"], "only the content filter may be installed by default")
        for entry in lock.values():
            self.assertTrue(entry.url.startswith("https://addons.mozilla.org/"))

    def test_validation_rejects_untrusted_sources(self):
        good = extensions.load_lock()["ublock-origin"]
        for bad in (
            replace(good, url="http://addons.mozilla.org/x.xpi"),
            replace(good, url="https://evil.example/x.xpi"),
            replace(good, sha256="00"),
            replace(good, size=0),
            replace(good, id="../escape"),
        ):
            with (
                self.subTest(bad=bad.url + bad.sha256[:4] + str(bad.size) + bad.id),
                self.assertRaises(extensions.IntegrityError),
            ):
                extensions.validate_entry(bad)

    def _seed_cache(self, payload: bytes) -> extensions.LockedExtension:
        digest = hashlib.sha256(payload).hexdigest()
        entry = replace(extensions.load_lock()["ublock-origin"], sha256=digest, size=len(payload))
        cached = extensions.cached_path(entry)
        cached.parent.mkdir(parents=True)
        cached.write_bytes(payload)
        return entry

    def test_install_uses_verified_cache_and_private_mode(self):
        entry = self._seed_cache(b"PK fake xpi payload")
        profile_dir = Path(self._tmp.name) / "profile"
        profile_dir.mkdir(mode=0o700)
        target = extensions.install(entry, profile_dir)
        self.assertEqual(target.name, "uBlock0@raymondhill.net.xpi")
        self.assertEqual(target.read_bytes(), b"PK fake xpi payload")
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)

    def test_tampered_cache_is_not_installed(self):
        entry = self._seed_cache(b"original")
        extensions.cached_path(entry).write_bytes(b"tampered")
        with (
            mock.patch("urllib.request.OpenerDirector.open", side_effect=OSError("network disabled in unit tests")),
            self.assertRaises(OSError),
        ):
            extensions.fetch(entry)
        self.assertFalse(extensions.cached_path(entry).exists(), "tampered cache entry must be discarded")


class DesktopTest(unittest.TestCase):
    def test_entry_never_registers_as_handler(self):
        text = desktop.render_entry(Path("/opt/nulavio/bin/nulavio"))
        self.assertNotIn("MimeType", text)
        self.assertIn("Exec=/opt/nulavio/bin/nulavio run %u", text)
        self.assertIn("StartupWMClass=nulavio-preview", text)
        self.assertIn("Icon=nulavio-preview", text)

    def test_exec_path_is_quoted(self):
        text = desktop.render_entry(Path("/home/a b/$x/bin/nulavio"))
        self.assertIn('Exec="/home/a b/\\$x/bin/nulavio" run %u', text)

    def test_install_and_uninstall_touch_only_own_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_home = Path(tmp) / "share"
            neighbour = data_home / "applications" / "other.desktop"
            neighbour.parent.mkdir(parents=True)
            neighbour.write_text("[Desktop Entry]\n")
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(data_home), "NULAVIO_HOME": str(Path(tmp) / "n")}):
                written = desktop.install(Path("/x/bin/nulavio"))
                self.assertTrue(any(p.name == "nulavio-preview.desktop" for p in written))
                self.assertTrue((data_home / "icons/hicolor/48x48/apps/nulavio-preview.png").exists())
                removed = desktop.uninstall()
            self.assertEqual(sorted(map(str, removed)), sorted(map(str, written)))
            self.assertTrue(neighbour.exists())


if __name__ == "__main__":
    unittest.main()
