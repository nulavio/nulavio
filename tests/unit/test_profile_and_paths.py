"""Profiles, private filesystem handling, logging and redaction."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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

from nulavio_launcher import doctor, log, paths, prefs, profile  # noqa: E402


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
