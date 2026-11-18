"""Engine command construction and extension integrity."""

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

from nulavio_launcher import doctor, engine, extensions  # noqa: E402

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
        hostile = {  # nosemgrep: nulavio-py-engine-sandbox-env -- the input launch_env() must strip
            "MOZ_DISABLE_CONTENT_SANDBOX": "1",
            "MOZ_DISABLE_RDD_SANDBOX": "1",
            "MOZ_SANDBOX_LOGGING": "1",
            "MOZ_ASSUME_USER_NS": "0",  # #312: content processes without their own namespaces
            "MOZ_FORCE_DISABLE_E10S": "160.0",  # pages in the parent process, no content sandbox
            "MOZ_FORCE_DISABLE_FISSION": "1",  # one process for several sites
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

    def test_doctor_says_when_the_codec_library_is_missing_and_what_to_install(self):
        # #377: without libavcodec the engine cannot play AAC, nor Opus and FLAC in MP4.
        with mock.patch.object(doctor.ctypes.util, "find_library", return_value="libavcodec.so.62"):
            (check,) = doctor.check_media()
        self.assertEqual((check.area, check.name, check.status), ("media", "codec library", "ok"))
        self.assertIn("libavcodec.so.62", check.detail)
        cases = {
            "ID=fedora\n": "sudo dnf install libavcodec-free",
            "ID=ubuntu\nID_LIKE=debian\n": "sudo apt install libavcodec-extra",
            'ID="linuxmint"\nID_LIKE="ubuntu debian"\n': "sudo apt install libavcodec-extra",
            'ID=nobara\nID_LIKE="rhel centos fedora"\n': "sudo dnf install libavcodec-free",
            "ID=arch\n": "your distribution's FFmpeg libraries (libavcodec)",
        }
        for release, said in cases.items():
            with self.subTest(release=release), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "os-release").write_text(release, encoding="utf-8")
                with (
                    mock.patch.object(doctor.ctypes.util, "find_library", return_value=None),
                    mock.patch.object(doctor, "CODEC_DIRS", (tmp,)),
                    mock.patch.object(doctor, "OS_RELEASE", Path(tmp) / "os-release"),
                ):
                    (check,) = doctor.check_media()
                self.assertEqual(check.status, "warn")
                self.assertIn(said, check.detail)
                self.assertIn("does not play", check.detail)
        # A library the linker's cache does not list is still found in the usual directories.
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "libavcodec.so.61").write_bytes(b"")
            with (
                mock.patch.object(doctor.ctypes.util, "find_library", return_value=None),
                mock.patch.object(doctor, "CODEC_DIRS", (tmp,)),
            ):
                self.assertEqual(doctor.codec_library(), "libavcodec.so.61")
        self.assertIn("media", {check.area for check in doctor.check_media()})

    def test_doctor_reports_a_variable_that_weakens_the_sandbox(self):
        # #312: removed before the engine starts, and said, since other programs started from here keep it.
        def environment():
            return next(c for c in doctor.check_platform() if c.area == "sandbox" and c.name == "environment")

        hostile = {"MOZ_ASSUME_USER_NS": "0"}  # nosemgrep: nulavio-py-engine-sandbox-env -- the input doctor reports
        with mock.patch.dict(os.environ, hostile):
            check = environment()
        self.assertEqual(check.status, "warn")
        self.assertIn("MOZ_ASSUME_USER_NS", check.detail)
        clean = {k: v for k, v in os.environ.items() if k not in engine.sandbox_overrides()}
        with mock.patch.dict(os.environ, clean, clear=True):
            self.assertEqual(environment().status, "ok")

    def test_only_the_nulavio_build_ships_the_window_theme(self):
        self.assertFalse(FAKE_ENGINE.builtin_theme)
        nulavio = engine.Engine(path=Path("/opt/nulavio/nulavio"), version="158.0.1", vendor="Nulavio")
        self.assertTrue(nulavio.builtin_theme)

    def test_setup_and_run_refuse_the_distribution_firefox(self):
        # The preview is no longer offered (#464): only the test harness, which says so, runs Firefox.
        nulavio = replace(FAKE_ENGINE, vendor="Nulavio")
        engine.require_nulavio(nulavio, {})
        engine.require_nulavio(FAKE_ENGINE, {engine.HARNESS_FIREFOX_ENV: "1"})
        for environ in ({}, {engine.HARNESS_FIREFOX_ENV: "0"}, {engine.HARNESS_FIREFOX_ENV: ""}):
            with self.subTest(environ=environ), self.assertRaisesRegex(engine.EngineError, "no longer offered"):
                engine.require_nulavio(FAKE_ENGINE, environ)
        from nulavio_launcher import cli

        clean = {k: v for k, v in os.environ.items() if k != engine.HARNESS_FIREFOX_ENV}
        for command in (["setup", "--yes"], ["run", "--dry-run"]):
            with (
                self.subTest(command=command),
                tempfile.TemporaryDirectory() as home,
                mock.patch.dict(os.environ, {**clean, "NULAVIO_HOME": home}, clear=True),
                mock.patch.object(engine, "find_engine", return_value=FAKE_ENGINE),
                mock.patch("sys.stderr") as stderr,
            ):
                self.assertEqual(cli.main(command), 1)
                said = "".join(call.args[0] for call in stderr.write.call_args_list)
                self.assertIn("install the Nulavio package", said)
                self.assertEqual(list(Path(home).rglob("*")), [], "nothing is written before the refusal")

    def test_package_of_asks_rpm_then_dpkg_by_exit_status(self):
        # #470: the .deb's engine has no rpm database to ask, so the doctor's "updates" check asks dpkg too. An answer
        # counts only with exit status 0: rpm says "not owned" in the person's language, on stdout (review of #507).
        def which(name, rpm=True, dpkg=True):
            return f"/usr/bin/{name}" if (name == "rpm" and rpm) or (name == "dpkg-query" and dpkg) else None

        path = Path("/usr/lib/nulavio/nulavio")
        rpm_q = ("rpm", "-qf", "--queryformat", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\\n", str(path))
        rpm_owned = {rpm_q: (0, "nulavio-160.0-0.7.fc44.x86_64")}
        rpm_none = {rpm_q: (1, "o arquivo /usr/lib/nulavio/nulavio não pertence a nenhum pacote")}
        version = {("dpkg-query", "-W", "-f=${Version}", "nulavio"): (0, "160.0-0.7")}
        dpkg = {("dpkg-query", "-S", str(path)): (0, "nulavio: /usr/lib/nulavio/nulavio"), **version}
        dpkg_arch = {("dpkg-query", "-S", str(path)): (0, "nulavio:amd64: /usr/lib/nulavio/nulavio"), **version}
        diverted = {("dpkg-query", "-S", str(path)): (0, "diversion by other from: /usr/lib/nulavio/nulavio\n"
                                                         "diversion by other to: /usr/lib/nulavio/nulavio.real")}  # fmt: skip
        dpkg_none = {("dpkg-query", "-S", str(path)): (1, "")}
        cases = (
            (rpm_owned, {}, "nulavio-160.0-0.7.fc44.x86_64"),
            (rpm_none, {"dpkg": False}, ""),
            ({**rpm_none, **dpkg}, {}, "nulavio 160.0-0.7"),
            (dpkg, {"rpm": False}, "nulavio 160.0-0.7"),
            (dpkg_arch, {"rpm": False}, "nulavio 160.0-0.7"),
            (diverted, {"rpm": False}, ""),
            (dpkg_none, {"rpm": False}, ""),
            ({}, {"rpm": False, "dpkg": False}, ""),
        )

        def answer(cmd, answers, **_kwargs):
            code, out = answers.get(tuple(cmd), (1, ""))
            return mock.Mock(returncode=code, stdout=out)

        for answers, tools, owner in cases:
            with (
                self.subTest(answers=answers, tools=tools),
                mock.patch.object(doctor.shutil, "which", side_effect=lambda n, t=tools: which(n, **t)),
                mock.patch.object(doctor.subprocess, "run", side_effect=lambda cmd, a=answers, **k: answer(cmd, a, **k)) as run,
            ):
                self.assertEqual(doctor.package_of(path), owner)
                for call in run.call_args_list:
                    self.assertEqual(call.kwargs["env"]["LC_ALL"], "C")

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

    def test_installed_tools_use_the_engine_beside_them(self):
        # The browser runs its tools (and an agent's configuration runs `ai serve`) with no NULAVIO_ENGINE: they
        # must find the engine of their own install, not a Firefox the system also has (known paths or PATH).
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            def program(path: Path, output: str) -> Path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"#!/bin/sh\necho '{output}'\n")
                path.chmod(0o755)
                return path

            install = tmp / "usr" / "lib64" / "nulavio"
            nulavio = program(install / "nulavio", "Nulavio Nulavio 160.0.1")
            (install / "application.ini").write_text("[App]\nVersion=160.0.1\n")
            (install / "nulavio-tools").mkdir()
            firefox = program(tmp / "firefox" / "firefox", "Mozilla Firefox 160.0")
            program(tmp / "bin" / "firefox", "Mozilla Firefox 160.0")
            not_a_checkout = tmp / "src" / "nulavio"  # a source checkout cloned as "nulavio"
            (not_a_checkout / "bin").mkdir(parents=True)
            no_ini = tmp / "other"
            program(no_ini / "nulavio", "Nulavio Nulavio 160.0.1")
            (no_ini / "nulavio-tools").mkdir()
            clean = {k: v for k, v in os.environ.items() if k != "NULAVIO_ENGINE"}

            def lookup(root: Path, **extra) -> engine.Engine:
                with (
                    mock.patch.dict(os.environ, {**clean, "PATH": str(tmp / "bin"), **extra}, clear=True),
                    mock.patch.object(engine, "KNOWN_BINARIES", (firefox,)),
                    mock.patch("nulavio_launcher.paths.repo_root", return_value=root),
                ):
                    return engine.find_engine()

            found = lookup(install / "nulavio-tools")
            self.assertEqual((found.path, found.vendor), (nulavio.resolve(), "Nulavio"))
            explicit = lookup(install / "nulavio-tools", NULAVIO_ENGINE=str(firefox))
            self.assertEqual(explicit.path, firefox.resolve(), "an explicit NULAVIO_ENGINE still wins")
            for root in (not_a_checkout, tmp / "src" / "nulavio-tools", no_ini / "nulavio-tools"):
                with self.subTest(root=root):
                    with mock.patch("nulavio_launcher.paths.repo_root", return_value=root):
                        self.assertIsNone(engine.bundled_engine())
                    self.assertEqual(lookup(root).vendor, "Mozilla Firefox")

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
    def test_the_preview_desktop_command_is_gone(self):
        # #465: the packages install the menu entry; the preview's own `nulavio desktop` left with the preview.
        from nulavio_launcher import cli

        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["desktop", "install"])
        self.assertFalse((ROOT / "launcher" / "nulavio_launcher" / "desktop.py").exists())
        self.assertFalse((ROOT / "packaging" / "linux" / "nulavio-preview.desktop.in").exists())


if __name__ == "__main__":
    unittest.main()
