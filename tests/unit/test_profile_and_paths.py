"""Profiles, private filesystem handling, logging and redaction."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import cli, confine, doctor, extensions, guard, log, paths, prefs, profile  # noqa: E402
from nulavio_launcher import engine as engine_mod  # noqa: E402


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

    def test_files_the_browser_writes_are_never_read_through_a_link_or_a_fifo(self):
        # The launcher prepares a profile before the engine starts, outside any confinement of the browser, so
        # what it reads there must be the profile's own regular files (I9).
        prof = self.make()
        outside = self.home / "outside.txt"
        outside.write_text("not the profile's\n")
        settings = prof.load_settings()
        settings["pending_prefs"] = {"x.y": 1}
        prof.save_settings(settings)
        prefs_js = prof.path / "prefs.js"
        prefs_js.unlink(missing_ok=True)
        prefs_js.symlink_to(outside)
        with self.assertRaises(paths.UnsafePathError):
            profile.prepare_for_launch(prof, {"engine": "Engine 1", "filter": ""})
        self.assertTrue(prefs_js.is_symlink(), "left as it was")
        self.assertEqual(outside.read_text(), "not the profile's\n")
        with self.assertRaises(paths.UnsafePathError):
            prefs.read_user_prefs(prefs_js)
        prefs_js.unlink()
        os.mkfifo(prefs_js)  # a FIFO would block the start
        with self.assertRaises(paths.UnsafePathError):
            prefs.read_user_prefs(prefs_js)
        prefs_js.unlink()
        settings_link = prof.settings_path
        real = settings_link.with_name("real.json")
        settings_link.rename(real)
        settings_link.symlink_to(real)
        with self.assertRaises(paths.UnsafePathError):
            prof.load_settings()

    def test_the_settings_folder_is_never_another_profiles_through_a_link(self):
        # A link in place of the profile's own nulavio/ folder: its settings are neither read nor rewritten (I9).
        prof, other = self.make(), self.make("other")
        other_settings = other.settings_path.read_bytes()
        shutil.rmtree(prof.meta_dir)
        prof.meta_dir.symlink_to(other.meta_dir)
        with self.assertRaises(paths.UnsafePathError):
            prof.load_settings()
        with self.assertRaises(paths.UnsafePathError):
            profile.prepare_for_launch(prof, {"engine": "Engine 1", "filter": ""})
        self.assertEqual(other.settings_path.read_bytes(), other_settings)
        self.assertEqual(doctor.check_seeds(prof), [], "doctor goes on; its profile check reports the profile")

    def test_the_preview_theme_is_removed_only_from_the_profiles_own_chrome_folder(self):
        prof, other = self.make(), self.make("other")
        css = other.path / "chrome" / "userChrome.css"
        css.parent.mkdir()
        css.write_text(f"/* {profile.PREVIEW_THEME_MARKER} */\n")
        (prof.path / "chrome").symlink_to(css.parent)
        profile._remove_preview_theme(prof)
        self.assertTrue(css.exists())

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
        enforced = {p.name for p in profile.baseline_prefs() if p.mode == "enforce"}
        self.assertEqual(set(user_js), enforced)
        self.assertFalse((prof.path / "chrome").exists(), "the preview's chrome theme is gone (#464)")

    # -- a seeded value follows the baseline; a value the person chose stays (#384) --------------------

    OVERRIDES = "privacy.fingerprintingProtection.overrides"
    CHOICE = "browser.newtabpage.enabled"  # a true/false seed pref that is no protection; the baseline seeds false

    def set_pref(self, prof: profile.Profile, name: str, value) -> None:
        """As the engine saves a change made in Settings or about:config: one more line, the last one wins."""
        with open(prof.path / "prefs.js", "a") as handle:
            handle.write(prefs.format_pref(name, value) + "\n")

    def value(self, prof: profile.Profile, name: str):
        return prefs.read_user_prefs(prof.path / "prefs.js").get(name)

    def seeded_before_384(self, value, name: str = "work") -> profile.Profile:
        """A profile the launcher seeded before it recorded what it wrote, with `value` as the set of protections."""
        prof = self.make(name)
        profile.prepare_for_launch(prof, {})
        settings = prof.load_settings()
        del settings["seeded_values"]
        prof.save_settings(settings)
        self.set_pref(prof, self.OVERRIDES, value)
        return prof

    def test_the_history_is_the_baselines(self):
        data = json.loads((paths.config_dir() / "prefs" / "seed-history.json").read_text(encoding="utf-8"))
        now = {p.name: p.value for p in profile.baseline_prefs() if p.mode == "seed"}
        lines = "\n".join(f"{name}={prefs.format_value(value)}" for name, value in sorted(now.items()))
        self.assertEqual(
            data["baseline"],
            hashlib.sha256(lines.encode()).hexdigest(),
            "a seed pref was added, removed or changed. If a value changed, add its old value to `earlier` in"
            " browser/config/prefs/seed-history.json, so that profiles seeded with it follow; then update `baseline`.",
        )
        for name, earlier in data["earlier"].items():
            with self.subTest(pref=name):
                self.assertIn(name, now)
                self.assertNotIn(now[name], earlier, "the current value is not an earlier one")
                self.assertEqual(len(earlier), len(set(earlier)))
        # The preference this was made for, with every set that was shipped before the current one: before #375,
        # after #375, after #379, and after #380 (the set until engine patch 0012 added its two targets).
        self.assertEqual(len(data["earlier"][self.OVERRIDES]), 4)

    def test_a_profile_seeded_with_each_earlier_value_gets_the_current_one_at_its_next_launch(self):
        current = next(p.value for p in profile.baseline_prefs() if p.name == self.OVERRIDES)
        for number, earlier in enumerate(profile.seed_history()[self.OVERRIDES]):
            with self.subTest(earlier=earlier):
                prof = self.seeded_before_384(earlier, f"shipped-{number}")
                self.assertEqual(profile.seed_states(prof, prof.load_settings())[self.OVERRIDES][0], "follows")
                self.assertEqual(profile.prepare_for_launch(prof, {}), [self.OVERRIDES])
                self.assertEqual(self.value(prof, self.OVERRIDES), current)
                self.assertEqual(profile.prepare_for_launch(prof, {}), [])  # written once

    def test_a_value_the_person_changed_is_kept_and_doctor_says_so(self):
        own = "+WebGLRendererConstant,+ScreenOrientation"
        current = next(p.value for p in profile.baseline_prefs() if p.name == self.OVERRIDES)
        new = self.make("new")
        profile.prepare_for_launch(new, {})
        self.set_pref(new, self.OVERRIDES, own)
        old = self.seeded_before_384(own, "old")
        self.set_pref(old, self.CHOICE, True)  # a choice whose default never changed
        for prof in (old, new):
            with self.subTest(profile=prof.name):
                for _launch in range(2):  # at the next launch, and at every later one
                    self.assertEqual(profile.prepare_for_launch(prof, {}), [])
                    self.assertEqual(self.value(prof, self.OVERRIDES), own)
        # The profile from before #384: when its set was written is not known, and the baseline's set has changed
        # three times. Doctor says so before its next launch and after it, with the value to set.
        for _launch in range(2):
            (check,) = doctor.check_seeds(old)
            self.assertEqual((check.name, check.status), (f"old: {self.OVERRIDES}", "warn"))
            self.assertIn("keeps it", check.detail)
            self.assertIn(prefs.format_value(current), check.detail)
            profile.prepare_for_launch(old, {})
        # A choice about a preference whose default did not move after it is only a choice: nothing to say.
        self.set_pref(new, self.CHOICE, True)
        profile.prepare_for_launch(new, {})
        self.assertEqual(doctor.check_seeds(new), [])

    def test_doctor_names_a_choice_only_when_the_default_moved_after_it(self):
        # The profile is seeded with today's set; the person then writes their own (as the Shell does for them
        # when they let sites see their motion and contrast preferences). Nothing moved since: nothing to say.
        prof = self.make()
        profile.prepare_for_launch(prof, {})
        self.set_pref(prof, self.OVERRIDES, "+WebGLRendererConstant")
        self.assertEqual(doctor.check_seeds(prof), [])
        profile.prepare_for_launch(prof, {})
        self.assertEqual(doctor.check_seeds(prof), [])
        # The baseline's set gains an entry: now the person's set is behind it, and doctor says so, at every
        # launch from then on, with the value to set.
        real = profile.baseline_prefs
        newer = next(p.value for p in real() if p.name == self.OVERRIDES) + ",+SomethingNew"

        def gained():
            return [prefs.Pref(p.name, newer, p.mode) if p.name == self.OVERRIDES else p for p in real()]

        with mock.patch.object(profile, "baseline_prefs", gained):
            for _launch in range(2):
                self.assertEqual(profile.prepare_for_launch(prof, {}), [])
                (check,) = doctor.check_seeds(prof)
                self.assertEqual((check.name, check.status), (f"work: {self.OVERRIDES}", "warn"))
                self.assertIn(prefs.format_value(newer), check.detail)
            # They take it: nothing to say again.
            self.set_pref(prof, self.OVERRIDES, newer)
            self.assertEqual(doctor.check_seeds(prof), [])

    def test_a_value_the_shell_wrote_for_the_persons_setting_is_left_to_the_shell(self):
        # Review of #400. In the Nulavio build, "let sites see my motion and contrast preferences" makes the Shell
        # write the set without three entries, which is exactly a set the baseline shipped earlier. It is not an
        # old seed: the launcher must not put the three entries back, in an old profile or a new one.
        shell = (ROOT / "browser" / "shell" / "modules" / "NulavioFingerprinting.sys.mjs").read_text(encoding="utf-8")
        marker = profile.SHELL_WRITTEN[self.OVERRIDES]
        self.assertIn(f'const WRITTEN = "{marker}";', shell)
        self.assertIn(f'const OVERRIDES = "{self.OVERRIDES}";', shell)
        # The case that was found: with the set as it was after #380, the Shell's value (that set without the three
        # accessibility entries) is the set as it was after #379, an earlier seed.
        after_379, after_380 = profile.seed_history()[self.OVERRIDES][2:4]
        accessibility = ("+CSSPrefersReducedMotion", "+CSSPrefersContrast", "+CSSPrefersReducedTransparency")
        written = ",".join(item for item in after_380.split(",") if item not in accessibility)
        self.assertEqual(written, after_379)
        new = self.make("new")
        profile.prepare_for_launch(new, {})
        self.set_pref(new, self.OVERRIDES, written)
        for prof in (self.seeded_before_384(written, "old"), new):
            with self.subTest(profile=prof.name):
                self.set_pref(prof, marker, written)
                self.assertEqual(profile.seed_states(prof, prof.load_settings())[self.OVERRIDES][0], "managed")
                for _launch in range(2):
                    self.assertEqual(profile.prepare_for_launch(prof, {}), [])
                    self.assertEqual(self.value(prof, self.OVERRIDES), written)
                self.assertEqual(doctor.check_seeds(prof), [])
        # Without the Shell's record the same value in a profile from before #384 is an earlier seed, and follows.
        plain = self.seeded_before_384(written, "plain")
        self.assertEqual(profile.prepare_for_launch(plain, {}), [self.OVERRIDES])
        # The Shell's record of an older value does not cover a set the person wrote since.
        self.set_pref(new, self.OVERRIDES, "+WebGLRendererConstant")
        self.assertEqual(profile.seed_states(new, new.load_settings())[self.OVERRIDES][0], "kept")

    def test_doctor_names_a_moved_default_before_the_next_launch_too(self):
        # Review of #400 (CodeRabbit): a launch records the seed; the person saves their own value; the baseline
        # moves with no launch in between. Doctor says so at once, not only after the next launch.
        prof = self.make()
        profile.prepare_for_launch(prof, {})
        self.set_pref(prof, self.OVERRIDES, "+WebGLRendererConstant")
        real = profile.baseline_prefs
        newer = next(p.value for p in real() if p.name == self.OVERRIDES) + ",+SomethingNew"

        def gained():
            return [prefs.Pref(p.name, newer, p.mode) if p.name == self.OVERRIDES else p for p in real()]

        self.assertEqual(doctor.check_seeds(prof), [])  # nothing moved yet
        with mock.patch.object(profile, "baseline_prefs", gained):
            (check,) = doctor.check_seeds(prof)
            self.assertEqual((check.name, check.status), (f"work: {self.OVERRIDES}", "warn"))

    def test_doctor_says_when_the_next_start_brings_the_current_default(self):
        prof = self.seeded_before_384(profile.seed_history()[self.OVERRIDES][0])
        check = next(c for c in doctor.check_seeds(prof))
        self.assertEqual((check.name, check.status), (f"work: {self.OVERRIDES}", "info"))
        profile.prepare_for_launch(prof, {})
        self.assertEqual(doctor.check_seeds(prof), [])

    def test_a_later_change_of_the_baseline_is_followed_by_the_recorded_value_alone(self):
        # From now on the launcher records what it wrote: no list of earlier values is needed.
        prof = self.make()
        profile.prepare_for_launch(prof, {})
        seeded = self.value(prof, self.CHOICE)
        self.assertIs(seeded, False)
        real = profile.baseline_prefs

        def flipped():
            return [prefs.Pref(p.name, True, p.mode) if p.name == self.CHOICE else p for p in real()]

        with mock.patch.object(profile, "baseline_prefs", flipped):
            self.assertEqual(profile.prepare_for_launch(prof, {}), [self.CHOICE])
            self.assertIs(self.value(prof, self.CHOICE), True)
            # The person turns it off again: theirs now, and the launcher does not turn it back on.
            self.set_pref(prof, self.CHOICE, False)
            self.assertEqual(profile.prepare_for_launch(prof, {}), [])
            self.assertIs(self.value(prof, self.CHOICE), False)
        # Back to the real baseline (false): the value is the baseline's again, by the person's hand.
        self.assertEqual(profile.prepare_for_launch(prof, {}), [])
        self.assertEqual(profile.seed_states(prof, prof.load_settings())[self.CHOICE][0], "current")

    def test_a_missing_value_is_the_engines_default_and_stays_unless_a_true_false_default_changed(self):
        prof = self.make()
        profile.prepare_for_launch(prof, {})
        # The engine does not save a value equal to its own default: the lines are gone after a session.
        kept = [
            line
            for line in (prof.path / "prefs.js").read_text(encoding="utf-8").splitlines()
            if self.OVERRIDES not in line and self.CHOICE not in line
        ]
        (prof.path / "prefs.js").write_text("\n".join(kept) + "\n", encoding="utf-8")
        self.assertEqual(profile.prepare_for_launch(prof, {}), [])
        real = profile.baseline_prefs

        def changed():
            new = {self.OVERRIDES: "+WebGLRendererConstant", self.CHOICE: True}
            return [prefs.Pref(p.name, new[p.name], p.mode) if p.name in new else p for p in real()]

        with mock.patch.object(profile, "baseline_prefs", changed):
            # The true/false one is written: missing, it was what the launcher seeded or the value now asked for.
            # The text one is not: missing, it may be the person's reset.
            self.assertEqual(profile.prepare_for_launch(prof, {}), [self.CHOICE])
            self.assertIsNone(self.value(prof, self.OVERRIDES))

    def test_true_and_one_are_two_values(self):
        prof = self.make()
        profile.prepare_for_launch(prof, {})
        self.set_pref(prof, self.CHOICE, 0)
        self.assertEqual(profile.seed_states(prof, prof.load_settings())[self.CHOICE][0], "kept")

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

    def test_preview_theme_removed_and_users_css_kept(self):
        # The preview's userChrome.css is no longer installed (#464); a copy an earlier launcher wrote would override
        # the Nulavio build's window theme, so it is removed. A file the person wrote stays.
        prof = self.make()
        css = prof.path / "chrome" / "userChrome.css"
        css.parent.mkdir(mode=0o700)
        css.write_text(f"/* {profile.PREVIEW_THEME_MARKER} */\n#nav-bar {{ background: none; }}\n")
        profile.prepare_for_launch(prof, {})
        self.assertFalse(css.exists())
        self.assertNotIn("toolkit.legacyUserProfileCustomizations.stylesheets", prefs.read_user_prefs(prof.path / "user.js"))
        css.write_text("/* my own chrome tweaks */\n#nav-bar { opacity: 1; }\n")
        profile.prepare_for_launch(prof, {})
        self.assertEqual(css.read_text(), "/* my own chrome tweaks */\n#nav-bar { opacity: 1; }\n", "user's file touched")

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
        # A real engine makes its lock after it has started, so its command line is there by then. This
        # stand-in is still in the middle of exec when Popen returns: for a moment /proc shows an empty
        # command line, which running_pid rightly takes for another process (#280, about 1 run in 100 under
        # load). Wait for the state the test is about.
        cmdline = Path(f"/proc/{engine.pid}/cmdline")
        deadline = time.monotonic() + 10
        while str(prof.path) not in cmdline.read_bytes().decode(errors="replace").split("\0"):
            self.assertLess(time.monotonic(), deadline, "the stand-in engine never showed its command line")
            time.sleep(0.01)
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
                                     ("Mozilla Firefox 159.0", False, "F"), ("unknown engine", False, "A"),
                                     # A version that does not end in a digit: a nightly, an ESR, a package release.
                                     ("Nulavio 160.0a1", True, "F"), ("Mozilla Firefox 159.0esr", False, "F"),
                                     ("Mozilla Firefox 140.5.0esr", False, "A"), ("Nulavio 160.0-0.3", True, "F")):  # fmt: skip
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


class GuardAtLaunchTest(TempHome):
    """#704: `nulavio run` audits the prefs the engine loads, after the launcher has written prefs.js and user.js."""

    WEAK = 'user_pref("security.sandbox.content.level", 0);\n'  # critical for the Guard; no baseline pref
    PROTECTIVE = 'user_pref("security.sandbox.content.level", 4);\n'

    def setUp(self):
        super().setUp()
        self.prof = profile.create("work")
        self.prof.path.joinpath("prefs.js").write_text(self.WEAK)
        self.prof.path.joinpath("user.js").write_text(self.PROTECTIVE)

    def run_cli(self, *extra: str) -> tuple[int, str]:
        eng = engine_mod.Engine(path=self.home / "engine" / "nulavio", version="160.0.1", vendor="Nulavio")
        err = io.StringIO()
        with (
            mock.patch.object(engine_mod, "find_engine", return_value=eng),
            mock.patch.object(engine_mod, "check_supported"),
            redirect_stdout(io.StringIO()),
            redirect_stderr(err),
        ):
            code = cli.main(["run", "--dry-run", "--profile", "work", *extra])
        return code, err.getvalue()

    def test_a_protective_user_js_line_the_launcher_replaces_does_not_hide_a_weakened_value(self):
        code, said = self.run_cli()
        self.assertEqual(code, 3, said)
        self.assertIn("guard [critical] security.sandbox.content.level=0", said)
        self.assertIn("refusing to start", said)
        # The line the audit would have counted is gone: the engine is given the value from prefs.js.
        self.assertNotIn("security.sandbox.content.level", prefs.read_user_prefs(self.prof.path / "user.js"))

    def test_the_audited_value_is_the_one_the_engine_is_given(self):
        code, said = self.run_cli("--allow-weakened")
        self.assertEqual(code, 0, said)
        loaded = prefs.effective_user_prefs(self.prof.path)  # prefs.js with user.js over it, as the engine reads them
        self.assertEqual(loaded["security.sandbox.content.level"], 0)
        self.assertIn(f"security.sandbox.content.level={loaded['security.sandbox.content.level']!r}", said)
        self.assertEqual(
            [(f.pref, f.actual) for f in guard.audit(self.prof.path) if f.severity == "critical"],
            [("security.sandbox.content.level", 0)],
        )

    def test_a_pref_the_launcher_appends_to_prefs_js_is_audited(self):
        self.prof.path.joinpath("prefs.js").write_text("")
        settings = self.prof.load_settings()
        settings["pending_prefs"] = {"xpinstall.signatures.required": False}
        self.prof.save_settings(settings)
        code, said = self.run_cli()
        self.assertEqual(code, 3, said)
        self.assertIn("guard [critical] xpinstall.signatures.required=False", said)

    def test_a_user_js_the_audit_refused_still_stops_the_start(self):
        # The launcher replaces user.js before the audit: one that is not the person's own regular file is refused
        # first, as the audit refused it before the order changed, and is left as it was.
        elsewhere = self.home / "elsewhere.js"
        elsewhere.write_text(self.PROTECTIVE)
        self.prof.path.joinpath("prefs.js").write_text("")
        user_js = self.prof.path / "user.js"
        for make, reason in ((lambda: os.symlink(elsewhere, user_js), "symlink"), (lambda: os.mkfifo(user_js), "regular")):
            with self.subTest(reason):
                user_js.unlink()
                make()
                code, said = self.run_cli()
                self.assertEqual(code, 1, said)
                self.assertIn(reason, said)
                self.assertFalse(user_js.is_file() and not user_js.is_symlink(), "user.js was replaced")
        self.assertEqual(elsewhere.read_text(), self.PROTECTIVE)

    def test_a_malformed_profile_file_is_reported_not_a_traceback(self):
        # Preparing now comes before the audit: a file it cannot read ends the start with a message, not a crash.
        settings = self.prof.load_settings()
        settings["pending_prefs"] = {"browser.startup.page": 1}
        self.prof.save_settings(settings)
        self.prof.path.joinpath("prefs.js").write_bytes(b'user_pref("a", "\xff");\n' + self.WEAK.encode())
        code, said = self.run_cli()
        self.assertEqual(code, 1, said)
        self.assertIn("prefs.js", said)
        for broken in ('{"schema": ', "null", "[]", '"settings"'):
            with self.subTest(broken):
                paths.write_private_file(self.prof.settings_path, broken)
                code, said = self.run_cli()
                self.assertEqual(code, 1, said)
                self.assertIn("settings", said)

    def test_an_extension_registry_of_the_wrong_shape_does_not_stop_the_audit(self):
        for registry in (
            "[]",
            '{"addons": null}',
            '{"addons": {"id": "x"}}',
            '{"addons": [null, 3, "x"]}',
            '{"addons": [{"type": "extension", "location": "app-profile"}]}',
            '{"addons": [{"id": 7, "type": "extension", "location": "app-profile"}]}',
            '{"addons": [{"id": "x@y", "type": "extension", "location": "app-profile", "defaultLocale": "x"}]}',
        ):
            with self.subTest(registry):
                self.prof.path.joinpath("extensions.json").write_text(registry)
                code, said = self.run_cli()
                self.assertEqual(code, 3, said)
                self.assertIn("guard [critical] security.sandbox.content.level=0", said)

    def test_a_profile_that_closes_during_the_open_profile_audit_is_prepared_and_audited(self):
        # The engine exits while its profile is being audited: the start is a fresh one, not a forward.
        calls = iter([os.getpid()])
        with mock.patch.object(profile.Profile, "running_pid", lambda _self: next(calls, None)):
            code, said = self.run_cli()
        self.assertEqual(code, 3, said)  # prepared: the protective user.js line is gone, the weakened value counts
        self.assertIn("guard [critical] security.sandbox.content.level=0", said)

    def test_confinement_is_set_up_only_after_the_guard_allows_the_start(self):
        for effect in (lambda command, **_: command, confine.ConfineError("not starting: no bubblewrap")):
            with self.subTest(effect), mock.patch.object(confine, "wrap", side_effect=effect) as wrap:
                code, said = self.run_cli("--confined")
                self.assertEqual(code, 3, said)
                self.assertIn("refusing to start", said)
                wrap.assert_not_called()
        with mock.patch.object(confine, "wrap", side_effect=lambda command, **_: command) as wrap:
            code, said = self.run_cli("--confined", "--allow-weakened")
        self.assertEqual(code, 0, said)
        wrap.assert_called_once()
        self.prof.path.joinpath("user.js").write_text(self.PROTECTIVE)
        os.symlink(f"127.0.0.1:+{os.getpid()}", self.prof.path / "lock")
        with mock.patch.object(confine, "wrap") as wrap:
            code, said = self.run_cli("--confined")
        self.assertEqual(code, 1, said)  # an open profile: audited, then refused as already open
        self.assertIn("already open", said)
        wrap.assert_not_called()

    def test_a_profile_opened_while_the_start_is_checked_is_not_started_again(self):
        # Preparing checked the lock; the audit and the confinement come after it. A profile another start opened
        # meanwhile is refused as in use, as preparing refused it when it came last.
        self.prof.path.joinpath("prefs.js").write_text("")

        def open_it(command, **_):
            os.symlink(f"127.0.0.1:+{os.getpid()}", self.prof.path / "lock")
            return command

        for extra, patch in ((("--confined",), mock.patch.object(confine, "wrap", side_effect=open_it)),
                             ((), mock.patch.object(cli, "_guard_allows", side_effect=lambda *_: open_it(True)))):  # fmt: skip
            with self.subTest(extra), patch:
                try:
                    code, said = self.run_cli(*extra)
                finally:
                    (self.prof.path / "lock").unlink(missing_ok=True)
                self.assertEqual(code, 1, said)  # with --dry-run, 0 is the command printed for a start
                self.assertIn("is open", said)

    def test_an_open_profile_is_audited_as_it_is_and_not_prepared(self):
        os.symlink(f"127.0.0.1:+{os.getpid()}", self.prof.path / "lock")
        code, said = self.run_cli()
        self.assertEqual(code, 0, said)  # the running engine loaded user.js as it is
        self.assertEqual(self.prof.path.joinpath("user.js").read_text(), self.PROTECTIVE)
        self.prof.path.joinpath("user.js").write_text('user_pref("marionette.port", 2828);\n')
        code, said = self.run_cli()
        self.assertEqual(code, 3, said)
        self.assertIn("marionette.port", said)


class MalformedInputTest(TempHome):
    """#675: a malformed URL, settings.json, extensions.json or native-messaging manifest gives a message, not a
    traceback."""

    # Nested values of the wrong type in a settings object that is otherwise valid, with the field the message names.
    BAD_SETTINGS = (
        ("pending_prefs", None),
        ("pending_prefs", {"browser.startup.page": 1.5}),
        ("locale", 5),
        ("provider", 5),
        ("baseline_version", ["x"]),
        ("seeded", []),
        ("seeded_values", {"browser.startup.page": 1}),
        # A lone surrogate: JSON allows it, but it cannot be printed or written as UTF-8.
        ("provider", "\ud800"),
        ("baseline_version", "\udcff"),
        ("pending_prefs", {"browser.startup.page": "\ud800"}),
        ("pending_prefs", {"\ud800": 1}),
        ("seeded_values", {"browser.startup.page": "\ud800"}),
    )

    def setUp(self):
        super().setUp()
        self.prof = profile.create("work")
        self.prof.path.joinpath("prefs.js").write_text("")

    def cli(self, *argv: str) -> tuple[int, str, str]:
        eng = engine_mod.Engine(path=self.home / "engine" / "nulavio", version="160.0.1", vendor="Nulavio")
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(engine_mod, "find_engine", return_value=eng),
            mock.patch.object(engine_mod, "check_supported"),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def assertOneLineError(self, said: str, *parts: str) -> None:
        self.assertEqual(len(said.splitlines()), 1, said)
        self.assertTrue(said.startswith("nulavio: "), said)
        for part in parts:
            self.assertIn(part, said)

    def test_a_malformed_url_is_refused_with_a_message(self):
        for url in ("http://[x", "https://ex／ample.com/"):  # an unclosed IPv6 host; a "/" after NFKC
            with self.subTest(url):
                with self.assertRaisesRegex(engine_mod.EngineError, "malformed"):
                    engine_mod.validate_url(url)
                code, out, said = self.cli("run", "--dry-run", "--profile", "work", url)
                self.assertEqual(code, 1, said)
                self.assertEqual(out, "")
                self.assertOneLineError(said, "URL is malformed")

    def test_a_settings_field_of_another_type_is_reported_by_name(self):
        good = self.prof.settings_path.read_text()
        weak = 'user_pref("security.sandbox.content.level", 0);\n'  # the Guard's refusal came first before #781
        for field, value in self.BAD_SETTINGS:
            for prefs_js in ("", weak):
                with self.subTest(field=field, value=value, critical=bool(prefs_js)):
                    self.prof.path.joinpath("prefs.js").write_text(prefs_js)
                    settings = json.loads(good)
                    settings[field] = value
                    paths.write_private_file(self.prof.settings_path, json.dumps(settings))
                    for argv in (("run", "--dry-run", "--profile", "work"), ("provider", "show", "--profile", "work")):
                        code, _out, said = self.cli(*argv)
                        self.assertEqual(code, 1, said)
                        self.assertOneLineError(said, "unreadable Nulavio settings", f"'{field}'")
        paths.write_private_file(self.prof.settings_path, good)
        self.prof.path.joinpath("prefs.js").write_text("")
        self.assertEqual(self.cli("run", "--dry-run", "--profile", "work")[0], 0)

    def test_profile_list_lists_the_others_when_one_settings_file_is_damaged(self):
        profile.create("other")
        profile.create("third")
        paths.write_private_file(profile.get("other").settings_path, '{"schema": ')
        code, out, said = self.cli("profile", "list")
        self.assertEqual(code, 1, said)
        self.assertOneLineError(said, "unreadable Nulavio settings", "other")
        listed = [line.split()[0] for line in out.splitlines()]
        self.assertEqual(listed, ["other", "third", "work"])
        self.assertIn("provider=?", out.splitlines()[0])
        self.assertIn("provider=builtin", out.splitlines()[2])

    def test_a_native_messaging_manifest_of_another_shape_is_reported_and_doctor_goes_on(self):
        hosts = self.home / "native-messaging-hosts"
        hosts.mkdir(parents=True)
        manifests = {
            "a-list.json": "[]",
            "b-path.json": '{"name": "b", "path": 5}',
            "c-allowed.json": '{"name": "c", "path": "/bin/sh", "allowed_extensions": [1]}',
            "d-name.json": '{"name": 3, "path": "/nonexistent/host"}',
            "e-name.json": '{"name": "\\ud800", "path": "/nonexistent/host"}',
            "f-path.json": '{"name": "f", "path": "/bin/\\ud800"}',
            "g-allowed.json": '{"name": "g", "path": "/bin/sh", "allowed_extensions": ["\\ud800"]}',
            "h-nul.json": '{"name": "h", "path": "/usr/bin/a\\u0000b"}',
        }
        for name, text in manifests.items():
            hosts.joinpath(name).write_text(text)
        with mock.patch.object(doctor, "NATIVE_MANIFEST_DIRS", [hosts]):
            checks = {c.name: c for c in doctor.check_native_messaging() if c.area == "native-messaging"}
        self.assertEqual(checks["a-list.json"].detail, "unreadable manifest: not a JSON object")
        self.assertEqual(checks["b"].detail, "unreadable manifest: 'path' is not a string")
        self.assertIn("'allowed_extensions'", checks["c"].detail)
        self.assertIn("host binary missing", checks["d-name"].detail)  # a name of another type: the file's own
        self.assertIn("host binary missing", checks["e-name"].detail)  # a name that cannot be printed: the same
        self.assertEqual(checks["f"].detail, "unreadable manifest: 'path' is not a string")
        self.assertIn("'allowed_extensions'", checks["g"].detail)
        self.assertIn("host binary missing", checks["h"].detail)  # a path os.stat refuses (NUL): not a traceback
        for name in ("a-list.json", "b", "c", "d-name", "e-name", "f", "g", "h"):
            self.assertEqual(checks[name].status, "warn", checks[name])
            self.assertEqual(len(checks[name].detail.splitlines()), 1)
            f"{checks[name].name} {checks[name].detail}".encode()  # what doctor prints

    def test_a_malformed_extension_list_never_hides_a_writable_host(self):
        hosts = self.home / "native-messaging-hosts"
        hosts.mkdir(parents=True)
        host = self.home / "host"
        host.write_text("#!/bin/sh\n")
        os.chmod(host, 0o777)
        for listed in ('"abc"', "[1]", '["\\ud800"]'):
            with self.subTest(listed=listed):
                manifest = hosts / "h.json"
                manifest.write_text(f'{{"name": "h", "path": "{host}", "allowed_extensions": {listed}}}')
                check = doctor._check_manifest(manifest)
                self.assertEqual((check.status, check.detail), ("fail", f"host {host} is group/world-writable"))

    def test_a_host_removed_during_doctor_is_reported_as_missing(self):
        manifest = self.home / "h.json"
        manifest.write_text('{"name": "h", "path": "/usr/lib/h/host"}')
        # The host was there when its existence was checked and is gone when its mode is read.
        with (
            mock.patch.object(Path, "exists", return_value=True),
            mock.patch.object(doctor.os, "stat", side_effect=FileNotFoundError(2, "gone")),
        ):
            check = doctor._check_manifest(manifest)
        self.assertEqual((check.status, check.detail), ("warn", "host binary missing: /usr/lib/h/host"))

    def test_provider_set_repairs_a_provider_of_another_type_and_checks_the_rest(self):
        good = json.loads(self.prof.settings_path.read_text())
        for provider in (5, "\ud800"):
            with self.subTest(provider=provider):
                paths.write_private_file(self.prof.settings_path, json.dumps({**good, "provider": provider}))
                code, _out, said = self.cli("provider", "set", "builtin", "--profile", "work")
                self.assertEqual(code, 0, said)
                self.assertEqual(self.prof.load_settings()["provider"], "builtin")
        paths.write_private_file(self.prof.settings_path, json.dumps({**good, "provider": 5, "pending_prefs": None}))
        code, _out, said = self.cli("provider", "set", "builtin", "--profile", "work")
        self.assertEqual(code, 1, said)
        self.assertOneLineError(said, "unreadable Nulavio settings", "'pending_prefs'")

    def test_profile_list_reports_a_settings_link_that_leads_nowhere(self):
        profile.create("other")
        settings = profile.get("other").settings_path
        settings.unlink()
        settings.symlink_to(self.home / "nowhere.json")
        code, out, said = self.cli("profile", "list")
        self.assertEqual(code, 1, said)
        self.assertOneLineError(said, "symlink", str(settings))
        self.assertEqual([line.split()[0] for line in out.splitlines()], ["other", "work"])

    def test_a_lock_with_a_pid_no_process_can_have_is_not_running(self):
        os.symlink("127.0.0.1:+99999999999999999999", self.prof.path / "lock")
        self.assertIsNone(self.prof.running_pid())
        profile.create("other")
        paths.write_private_file(self.prof.settings_path, '{"schema": ')
        code, out, said = self.cli("profile", "list")
        self.assertEqual(code, 1, said)
        self.assertEqual([line.split()[0] for line in out.splitlines()], ["other", "work"])
        self.assertIn("stopped", out.splitlines()[1])

    def test_an_extension_version_of_another_type_is_listed_as_unknown(self):
        registry = {
            "addons": [
                {"id": "x@y", "type": "extension", "location": "app-profile", "version": {"a": 1}, "active": True,
                 "defaultLocale": {"name": ["not", "a", "name"]}},
            ]
        }  # fmt: skip
        self.prof.path.joinpath("extensions.json").write_text(json.dumps(registry))
        code, out, said = self.cli("extensions", "list", "--profile", "work")
        self.assertEqual(code, 0, said)
        unpinned = [line for line in out.splitlines() if line.startswith("(unpinned)")]
        self.assertEqual(len(unpinned), 1, out)
        self.assertEqual(unpinned[0].split(), ["(unpinned)", "?", "x@y"])

    def test_extension_text_that_cannot_be_printed_is_listed_as_unknown(self):
        registry = {
            "addons": [
                {"id": "x@y", "type": "extension", "location": "app-profile", "version": "\ud800", "active": True,
                 "defaultLocale": {"name": "\udcff"}},
                {"id": "\ud800@y", "type": "extension", "location": "app-profile", "version": "1", "active": True},
            ]
        }  # fmt: skip
        self.prof.path.joinpath("extensions.json").write_text(json.dumps(registry))
        code, out, said = self.cli("extensions", "list", "--profile", "work")
        self.assertEqual(code, 0, said)
        out.encode()  # what a UTF-8 terminal gets
        unpinned = [line for line in out.splitlines() if line.startswith("(unpinned)")]
        self.assertEqual([line.split() for line in unpinned], [["(unpinned)", "?", "x@y"]])

    def test_the_start_page_never_shows_the_pinned_filter_version_for_an_unknown_registered_one(self):
        ublock = extensions.load_lock()["ublock-origin"]
        registry = {"addons": [{"id": ublock.id, "type": "extension", "location": "app-profile", "version": 3, "active": True}]}
        self.prof.path.joinpath("extensions.json").write_text(json.dumps(registry))
        self.assertEqual(cli._filter_context(self.prof)["filter"], ublock.name)
        self.prof.path.joinpath("extensions.json").unlink()
        self.prof.path.joinpath("extensions").mkdir()
        self.prof.path.joinpath("extensions", f"{ublock.id}.xpi").write_bytes(b"")
        self.assertEqual(cli._filter_context(self.prof)["filter"], f"{ublock.name} {ublock.version}")  # not registered yet


class OnePasswordDoctorTest(unittest.TestCase):
    """#81: doctor says how the 1Password desktop app learns the Nulavio build, and never writes its file."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = self.tmp / "opt" / "1password"
        self.allowed = self.tmp / "etc" / "1password" / "custom_allowed_browsers"
        for name, value in (("ONEPASSWORD_APP", (self.app,)), ("ONEPASSWORD_ALLOWED", self.allowed)):
            patcher = mock.patch.object(doctor, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root_owned = mock.patch.object(doctor, "_root_owned", return_value=True)
        self.root_owned.start()
        self.addCleanup(self.root_owned.stop)

    def test_nothing_without_the_desktop_app(self):
        self.assertEqual(doctor.check_1password(Path("/usr/lib64/nulavio/nulavio")), [])

    def test_a_name_that_is_not_plain_gets_no_command(self):
        # The command is pasted into a root shell: a file name with shell characters never goes into it.
        self.app.parent.mkdir(parents=True)
        self.app.touch()
        (check,) = doctor.check_1password(Path("/opt/x/nulavio;rm -rf ~"))
        self.assertEqual(check.status, "warn")
        self.assertNotIn("sudo", check.detail)

    def test_firefox_needs_no_step(self):
        self.app.parent.mkdir(parents=True)
        self.app.touch()
        (check,) = doctor.check_1password(Path("/usr/lib64/firefox/firefox"))
        self.assertEqual(check.status, "ok")

    def test_the_nulavio_build_gets_the_exact_command_and_the_file_is_never_written(self):
        self.app.parent.mkdir(parents=True)
        self.app.touch()
        (check,) = doctor.check_1password(Path("/usr/lib64/nulavio/nulavio"))
        self.assertEqual(check.status, "info")
        self.assertIn(f"sudo install -d -m 0755 {self.allowed.parent} && echo nulavio | sudo tee -a {self.allowed}", check.detail)
        self.assertFalse(self.allowed.exists(), "doctor wrote 1Password's file")
        self.allowed.parent.mkdir(parents=True)
        self.allowed.write_text("librewolf\n", encoding="utf-8")
        (check,) = doctor.check_1password(Path("/usr/lib64/nulavio/nulavio"))
        self.assertIn(f"`echo nulavio | sudo tee -a {self.allowed}`", check.detail)
        self.allowed.write_text("librewolf\nnulavio\n", encoding="utf-8")
        (check,) = doctor.check_1password(Path("/usr/lib64/nulavio/nulavio"))
        self.assertEqual(check.status, "ok")
        self.assertEqual(self.allowed.read_text(encoding="utf-8"), "librewolf\nnulavio\n")

    def test_a_list_without_a_final_line_break_and_one_that_is_not_utf8(self):
        """CodeRabbit on #478: the command keeps the names apart; a file that is not UTF-8 is a warning, not a crash."""
        self.app.parent.mkdir(parents=True)
        self.app.touch()
        self.allowed.parent.mkdir(parents=True)
        self.allowed.write_text("librewolf", encoding="utf-8")
        (check,) = doctor.check_1password(Path("/usr/lib64/nulavio/nulavio"))
        self.assertIn(f"`printf '\\n%s\\n' nulavio | sudo tee -a {self.allowed}`", check.detail)
        self.allowed.write_bytes(b"librewolf\n\xff\n")
        (check,) = doctor.check_1password(Path("/usr/lib64/nulavio/nulavio"))
        self.assertEqual(check.status, "warn")
        self.assertIn("cannot read", check.detail)

    def test_an_engine_the_user_can_replace_gets_no_command(self):
        """Review of #478: the line trusts a name; it is not offered for a tarball or a home-folder engine."""
        self.app.parent.mkdir(parents=True)
        self.app.touch()
        engine = self.tmp / "nulavio" / "nulavio"
        self.root_owned.stop()
        self.addCleanup(self.root_owned.start)
        # The user's own files, whoever runs the test.
        users = mock.Mock(st_uid=1000, st_mode=0o100755)
        with (
            mock.patch.object(doctor.os, "stat", return_value=users),
            mock.patch.object(Path, "resolve", lambda p, strict=False: p),
        ):
            (check,) = doctor.check_1password(engine)
            self.assertEqual(check.status, "warn")
            self.assertNotIn("sudo", check.detail)
            self.assertIn("can be changed without root", check.detail)
            # Already in 1Password's list: still said, not "ok".
            self.allowed.parent.mkdir(parents=True)
            self.allowed.write_text("nulavio\n", encoding="utf-8")
            (check,) = doctor.check_1password(engine)
            self.assertEqual(check.status, "warn")
            self.assertIn("is in", check.detail)

    def test_root_owned_needs_root_and_no_group_or_other_write_up_to_the_root(self):
        engine = self.tmp / "nulavio"
        engine.touch()
        # Resolved before os.stat is replaced: resolving calls it (on some Python versions), and the fake must not.
        real, tmp = engine.resolve(), self.tmp.resolve()

        def fake(owner_of, mode_of):
            def stat_of(path):
                return mock.Mock(st_uid=owner_of(Path(path)), st_mode=mode_of(Path(path)))

            return stat_of

        self.root_owned.stop()
        self.addCleanup(self.root_owned.start)
        with mock.patch.object(doctor.os, "stat", fake(lambda p: 0, lambda p: 0o100755)):
            self.assertTrue(doctor._root_owned(engine))
        with mock.patch.object(doctor.os, "stat", fake(lambda p: 1000 if p == real else 0, lambda p: 0o100755)):
            self.assertFalse(doctor._root_owned(engine), "the engine is the user's")
        with mock.patch.object(doctor.os, "stat", fake(lambda p: 0, lambda p: 0o40777 if p == tmp else 0o40755)):
            self.assertFalse(doctor._root_owned(engine), "a folder above it anyone can write")
        with mock.patch.object(doctor.os, "stat", fake(lambda p: 0, lambda p: 0o42775 if p == tmp else 0o40755)):
            self.assertFalse(doctor._root_owned(engine), "a folder above it a group can write")
        link = self.tmp / "link"
        link.symlink_to(engine)
        with mock.patch.object(doctor.os, "stat", fake(lambda p: 0 if p != real else 1000, lambda p: 0o100755)):
            self.assertFalse(doctor._root_owned(link), "a link to the user's file is judged by the file")
        self.assertFalse(doctor._root_owned(self.tmp / "missing"))


if __name__ == "__main__":
    unittest.main()
