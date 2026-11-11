"""Profiles, private filesystem handling, logging and redaction."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import log, paths, prefs, profile  # noqa: E402


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


class TempHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self._env = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.home), "LANG": "pt_BR.UTF-8"})
        self._env.start()
        self.old_umask = os.umask(0o022)  # hostile default: code must not rely on umask

    def tearDown(self):
        os.umask(self.old_umask)
        self._env.stop()
        self._tmp.cleanup()


class PathsTest(TempHome):
    def test_private_dir_created_and_tightened(self):
        target = self.home / "a" / "b"
        paths.ensure_private_dir(target)
        self.assertEqual(mode(target), 0o700)
        self.assertEqual(mode(self.home / "a"), 0o700)
        os.chmod(target, 0o755)
        problems = paths.check_private(target, 0o700, fix=True)
        self.assertTrue(problems)
        self.assertEqual(mode(target), 0o700)

    def test_symlink_is_refused(self):
        real = self.home / "real"
        paths.ensure_private_dir(real)
        link = self.home / "link"
        link.symlink_to(real)
        with self.assertRaises(paths.UnsafePathError):
            paths.ensure_private_dir(link)

    def test_private_file_is_0600_and_atomic(self):
        paths.ensure_private_dir(self.home)
        target = self.home / "f.json"
        paths.write_private_file(target, "one")
        paths.write_private_file(target, "two")
        self.assertEqual(target.read_text(), "two")
        self.assertEqual(mode(target), 0o600)
        self.assertEqual([p.name for p in self.home.iterdir()], ["f.json"], "no temp files left behind")

    def test_xdg_layout_never_touches_mozilla_dirs(self):
        with mock.patch.dict(os.environ, {"NULAVIO_HOME": ""}):
            for directory in (paths.data_home(), paths.state_home(), paths.cache_home()):
                self.assertNotIn(".mozilla", directory.parts)
                self.assertNotIn("mozilla", directory.parts)
                self.assertEqual(directory.name, "nulavio")


class RedactionTest(TempHome):
    def test_urls_secrets_and_home_are_redacted(self):
        text = (
            "opened https://bank.example/login?session=abc123 and file:///home/x/secret.pdf "
            f"token=deadbeef password: hunter2 at {Path.home()}/notes"
        )
        out = log.redact(text)
        for leaked in ("bank.example", "abc123", "secret.pdf", "deadbeef", "hunter2", str(Path.home())):
            self.assertNotIn(leaked, out)
        self.assertIn("<url:https>", out)
        self.assertIn("<url:file>", out)
        self.assertIn("~/notes", out)

    def test_log_file_is_private_jsonl(self):
        log.event("unit", url="https://example.org/x", count=2)
        target = log.log_path()
        self.assertEqual(mode(target), 0o600)
        record = json.loads(target.read_text().splitlines()[-1])
        self.assertEqual(record["url"], "<url:https>")
        self.assertEqual(record["count"], 2)


class ProfileTest(TempHome):
    def make(self, name: str = "work", **kwargs) -> profile.Profile:
        return profile.create(name, **kwargs)

    def test_names_are_validated(self):
        for bad in ("", "-x", "UPPER", "a/b", "../etc", "x" * 40, "with space"):
            with self.subTest(name=bad), self.assertRaises(profile.ProfileError):
                profile.get(bad)

    def test_create_is_private_and_isolated(self):
        prof = self.make()
        self.assertEqual(mode(prof.path), 0o700)
        self.assertEqual(mode(prof.settings_path), 0o600)
        self.assertTrue(str(prof.path).startswith(str(self.home)))
        settings = prof.load_settings()
        self.assertEqual(settings["provider"], "builtin")
        self.assertEqual(settings["locale"], "pt-BR")
        with self.assertRaises(profile.ProfileError):
            self.make()

    def test_seeds_apply_once_and_user_js_holds_only_enforced(self):
        prof = self.make()
        first = profile.prepare_for_launch(prof, {"engine": "Engine 1", "filter": ""})
        self.assertIn("dom.security.https_only_mode", first)
        values = prefs.read_user_prefs(prof.path / "prefs.js")
        self.assertTrue(values["browser.startup.homepage"].startswith("file://"))
        self.assertIs(values["signon.rememberSignons"], True)
        # Simulate the user turning HTTPS-Only off in Settings: it must stick.
        with open(prof.path / "prefs.js", "a") as handle:
            handle.write('user_pref("dom.security.https_only_mode", false);\n')
        second = profile.prepare_for_launch(prof, {"engine": "Engine 1", "filter": ""})
        self.assertEqual(second, [])
        self.assertIs(prefs.read_user_prefs(prof.path / "prefs.js")["dom.security.https_only_mode"], False)
        user_js = prefs.read_user_prefs(prof.path / "user.js")
        enforced = {p.name for p in profile.baseline_prefs() + profile.theme_prefs() if p.mode == "enforce"}
        self.assertEqual(set(user_js), enforced)
        self.assertEqual(mode(prof.path / "chrome" / "userChrome.css"), 0o600)

    def test_provider_switch_is_reversible(self):
        prof = self.make()
        profile.prepare_for_launch(prof, {})
        profile.set_provider(prof, "proton-pass")
        profile.prepare_for_launch(prof, {})
        self.assertIs(prefs.read_user_prefs(prof.path / "prefs.js")["signon.rememberSignons"], False)
        profile.set_provider(prof, "builtin")
        profile.prepare_for_launch(prof, {})
        self.assertIs(prefs.read_user_prefs(prof.path / "prefs.js")["signon.rememberSignons"], True)
        with self.assertRaises(profile.ProfileError):
            profile.set_provider(prof, "made-up")

    def test_builtin_theme_replaces_only_the_launchers_css(self):
        # The Nulavio build ships its window theme: the preview userChrome.css would
        # override it, so the launcher removes its own copy and never installs it.
        prof = self.make()
        css = prof.path / "chrome" / "userChrome.css"
        profile.prepare_for_launch(prof, {})
        self.assertTrue(css.exists())
        profile.prepare_for_launch(prof, {}, builtin_theme=True)
        self.assertFalse(css.exists())
        self.assertNotIn("toolkit.legacyUserProfileCustomizations.stylesheets", prefs.read_user_prefs(prof.path / "user.js"))
        css.write_text("/* my own chrome tweaks */\n#nav-bar { opacity: 1; }\n")
        profile.prepare_for_launch(prof, {}, builtin_theme=True)
        self.assertEqual(css.read_text(), "/* my own chrome tweaks */\n#nav-bar { opacity: 1; }\n", "user's file touched")

    def test_theme_off_removes_css_and_pref(self):
        prof = self.make()
        profile.prepare_for_launch(prof, {})
        profile.set_theme(prof, False)
        profile.prepare_for_launch(prof, {})
        self.assertFalse((prof.path / "chrome" / "userChrome.css").exists())
        self.assertNotIn("toolkit.legacyUserProfileCustomizations.stylesheets", prefs.read_user_prefs(prof.path / "user.js"))

    def test_start_page_escapes_values_and_has_no_scripts(self):
        prof = self.make()
        profile.prepare_for_launch(prof, {"engine": "<script>alert(1)</script>", "filter": "uBlock Origin 1.75.0"})
        page = (prof.startpage_dir / "index.html").read_text()
        self.assertNotIn("<script", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("default-src 'none'", page)
        self.assertNotIn("{{", page)
        self.assertIn('lang="pt-BR"', page)
        for asset in ("tokens.css", "startpage.css", "nulavio-symbol.svg", "nulavio-symbol-dark-on-light.svg"):
            self.assertTrue((prof.startpage_dir / asset).is_file(), asset)

    def test_a_reused_pid_is_not_the_engine(self):
        # Audit V7: after a crash, another process got the engine's PID; the profile never locked
        # and `lock --force` would have sent SIGTERM to that unrelated process.
        prof = self.make()
        lock = prof.path / "lock"
        os.symlink(f"127.0.0.1:+{os.getpid()}", lock)
        made = time.time() - 3600  # the lock is older than this process
        os.utime(lock, (made, made), follow_symlinks=False)
        self.assertIsNone(prof.running_pid())

    def test_a_clock_step_does_not_make_a_live_engine_look_gone(self):
        # Review of #44: a wall-clock step moved the computed start time past the lock's
        # mtime, and autolock would have unmounted a profile in use.
        prof = self.make()
        engine = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--profile", str(prof.path)])
        self.addCleanup(engine.wait)
        self.addCleanup(engine.kill)
        lock = prof.path / "lock"
        os.symlink(f"127.0.0.1:+{engine.pid}", lock)
        made = time.time() - 3600  # as if the clock had stepped an hour forward since
        os.utime(lock, (made, made), follow_symlinks=False)
        self.assertEqual(prof.running_pid(), engine.pid)

    def test_start_page_says_what_is_true_of_the_engine_in_use(self):
        """Audit 2026-11 P-01: the page is static, so the launcher fills in what depends on the engine."""
        prof = self.make()
        unmodified = ("sem modificações", "unmodified")
        development = ("build de desenvolvimento", "development build")
        for engine, patched, key in (("Nulavio 160.0", True, "F"), ("Mozilla Firefox 152.0.1", False, "A"),
                                     ("Mozilla Firefox 159.0", False, "F"), ("unknown engine", False, "A")):  # fmt: skip
            with self.subTest(engine=engine):
                profile.prepare_for_launch(prof, {"engine": engine})
                page = (prof.startpage_dir / "index.html").read_text()
                # The Nulavio build carries patches: nothing on its page calls the engine unmodified, and a
                # release is not called a development build. Distribution Firefox is unmodified, and says so.
                self.assertEqual(any(word in page for word in unmodified), not patched, page)
                self.assertFalse(any(word in page for word in development), page)
                self.assertIn("Mozilla", page)  # the engine's origin and the "not affiliated" line stay
                # The add-ons shortcut is the engine's own (159 moved it from Ctrl+Shift+A to Ctrl+Shift+F).
                self.assertIn(f"<kbd>Ctrl</kbd> <kbd>Shift</kbd> <kbd>{key}</kbd></span></li>\n        </ul>", page)
                self.assertNotIn("{{", page)
        strings = json.loads((profile.paths.repo_root() / "browser" / "startpage" / "strings.json").read_text())
        for language, values in strings.items():
            with self.subTest(language=language):
                self.assertFalse(any(word in values["T_ENGINE_NOTE_NULAVIO"] for word in development))
                self.assertFalse(any(word in values["T_FOOTER_NULAVIO"] for word in unmodified))

    def test_running_profile_is_protected(self):
        prof = self.make()
        os.symlink(f"127.0.0.1:+{os.getpid()}", prof.path / "lock")
        self.assertEqual(prof.running_pid(), os.getpid())
        with self.assertRaises(profile.ProfileInUse):
            profile.prepare_for_launch(prof, {})
        with self.assertRaises(profile.ProfileInUse):
            profile.delete(prof)
        os.unlink(prof.path / "lock")
        os.symlink("127.0.0.1:+999999999", prof.path / "lock")
        self.assertIsNone(prof.running_pid(), "stale lock after a crash must not block")

    def test_delete_only_inside_profiles_root(self):
        prof = self.make("temp")
        profile.delete(prof)
        self.assertFalse(prof.path.exists())
        self.assertTrue(paths.profiles_root().exists())


if __name__ == "__main__":
    unittest.main()
