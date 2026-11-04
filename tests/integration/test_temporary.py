"""Temporary profiles (deleted on close) on the real engine.

1. From the browser (Nulavio build): the profile selector's "New temporary
   window" asks the Nulavio tools for a profile and starts a second engine
   instance with it; when that instance exits, the tools' watcher deletes the
   folder. The user's own profile is untouched.
2. Inside a temporary instance: the temporary identity (toolbar, dashed chip,
   a bar in the window), where it is kept, no profile switching, and the prefs
   that follow from "deleted on close". The test drives it with test-only
   Marionette prefs added to that disposable profile.
3. `nulavio run --temporary` (launcher, any supported engine): the dry run
   leaves nothing; the supervised run (opt-in, it opens a window) deletes the
   profile after the engine exits.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from test_window_band import BAND_PROBE, assert_band, assert_layout_matrix

from nulavio_launcher import temporary

ROOT = Path(__file__).resolve().parents[2]
MODULE = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles'
ROUTING = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs").NulavioRouting'
GUARD = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs").NulavioGuard'
ACTION_BUTTON = "shell_nulavio_net-BAP"


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise AssertionError(result["error"])
    return result["ok"]


def guard_is_held(path: Path) -> bool:
    fd = os.open(path / temporary.GUARD, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


@unittest.skipUnless(harness.nulavio_engine(), "the browser side needs the Nulavio build (NULAVIO_ENGINE)")
class TemporaryFromTheBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.shell_url = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        cls.root = cls.session.tmp / "run" / "nulavio" / "temporary"
        cls.shots = harness.artifacts_dir() / "temporary"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def temporaries(self) -> list[Path]:
        return sorted(self.root.glob("tmp-*")) if self.root.is_dir() else []

    def instances(self, path: Path) -> list[int]:
        engine = str(self.session.engine.path)
        return [
            pid
            for pid in self.session.processes_for(path)
            if Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[0].decode() == engine
        ]

    def ready(self, m) -> bool:
        try:
            return m.execute("return document.documentElement?.dataset.ready === 'true';")
        except Exception:
            return False

    def shoot(self, m, name: str) -> None:
        for scheme in ("light", "dark"):
            m.execute(
                "document.documentElement.dataset.theme = arguments[0]; document.body.style.display = 'none';"
                "document.body.offsetHeight; document.body.style.display = ''; return document.body.offsetHeight;",
                [scheme],
            )
            time.sleep(0.3)
            (self.shots / f"{name}-{scheme}.png").write_bytes(m.screenshot_png(full=True))
        m.execute("delete document.documentElement.dataset.theme;")

    def test_01_new_temporary_window_from_the_selector_is_deleted_when_it_closes(self):
        self.assertEqual(self.temporaries(), [])
        first = self.m.window_handles()[0]
        handle = self.m.send("WebDriver:NewWindow", {"type": "tab"})["handle"]
        self.m.switch_to(handle)
        self.m.navigate(self.shell_url + "profiles/popup.html")
        self.assertTrue(harness.wait_until(lambda: self.ready(self.m), timeout=15))
        self.assertTrue(self.m.execute("return !document.getElementById('new-temporary').hidden;"))
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#new-temporary")})
        self.assertTrue(harness.wait_until(lambda: self.temporaries(), timeout=30), "no temporary profile was created")
        [path] = self.temporaries()
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=60), "no engine started for it")
        self.m.switch_to(first)

        self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)
        marker = json.loads((path / temporary.MARKER).read_text())
        self.assertEqual(marker["in_memory"], temporary.storage(path)[0])
        self.assertIn('"nulavio.profile.temporary", true', (path / "prefs.js").read_text())
        self.assertTrue(guard_is_held(path), "the watcher that deletes it is not running")
        [pid] = self.instances(path)
        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        self.assertIn(str(path).encode(), args)
        self.assertNotIn(b"--marionette", args)  # an ordinary instance, nothing added for automation

        os.kill(pid, signal.SIGTERM)  # what closing its last window does: the engine exits
        self.assertTrue(harness.wait_until(lambda: not path.exists(), timeout=90), "not deleted after closing")
        self.assertTrue((self.session.profile_dir / "prefs.js").exists())  # the user's profile is untouched
        self.assertEqual(self.chrome_user_profile_temporary(), {"temporary": False, "inMemory": False, "swapOnDisk": False})

    def chrome_user_profile_temporary(self):
        return chrome_async(self.m, f"return await {MODULE}.temporaryState();")

    def test_02_inside_a_temporary_instance(self):
        made = subprocess.run(
            [str(ROOT / "bin" / "nulavio"), "temporary", "api"],
            input=json.dumps({"op": "create"}),
            env=self.session.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        answer = json.loads(made.stdout)
        path = Path(answer["path"])
        self.assertEqual(path.parent, self.root)
        harness.GeckoProfileSession.enable_marionette(path)  # test-only, this disposable profile
        engine = subprocess.Popen(
            [str(self.session.engine.path), "--profile", str(path)],
            env=self.session.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        m = harness.GeckoProfileSession.connect(path, engine)
        try:
            state = chrome_async(m, f"return await {MODULE}.list();")
            self.assertEqual(state["reason"], "temporary")
            self.assertFalse(state["available"])
            self.assertEqual(state["temporary"]["inMemory"], answer["inMemory"])
            prefs = m.chrome(
                "return [Services.prefs.getBoolPref('nulavio.profile.temporary', false),"
                " Services.prefs.getBoolPref('signon.rememberSignons'),"
                " Services.prefs.getBoolPref('browser.download.manager.addToRecentDocs')];"
            )
            self.assertEqual(prefs, [True, False, False])
            routing = chrome_async(m, f"return await {ROUTING}.state();")
            self.assertFalse(routing["available"])  # no rules move pages out of (or into) a temporary profile
            guard = chrome_async(m, f"return await {GUARD}.check();")
            self.assertEqual((guard["state"], guard["reason"]), ("skipped", "temporary"))  # nothing in it is kept
            self.assertFalse((path / "nulavio-guard.json").exists())

            # The identity: the toolbar button and a bar in every window.
            tooltip = lambda: m.chrome(f"return document.getElementById('{ACTION_BUTTON}')?.getAttribute('tooltiptext') ?? '';")  # noqa: E731
            self.assertTrue(harness.wait_until(lambda: "temporário" in tooltip(), timeout=20), tooltip())
            bar = lambda: m.chrome(  # noqa: E731
                "const n = gNotificationBox.getNotificationWithValue('nulavio-temporary');"
                "return n ? n.messageText.textContent : '';"
            )
            self.assertTrue(harness.wait_until(lambda: "nada aqui é guardado" in bar(), timeout=20), bar())
            self.assertIn("Apagado quando você fechar", bar())
            assert_band(self, m.chrome(f"return {BAND_PROBE};"))
            assert_layout_matrix(self, m, "temporary")
            for dark in (0, 1):
                m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                time.sleep(0.25)
                state = m.chrome(f"return {BAND_PROBE};")
                assert_band(self, state)
                self.assertIn("apagado ao fechar", state["text"])
                self.assertTrue(any(c["border"] == "dashed" for c in state["cues"]))
                m.set_context("chrome")
                try:
                    (self.shots / f"band-{'dark' if dark else 'light'}.png").write_bytes(m.screenshot_png())
                finally:
                    m.set_context("content")

            before = set(m.window_handles())
            m.chrome("OpenBrowserWindow({private: true});")
            self.assertTrue(harness.wait_until(lambda: set(m.window_handles()) - before, 15))
            private = (set(m.window_handles()) - before).pop()
            m.switch_to(private)
            self.assertTrue(
                harness.wait_until(lambda: m.chrome("return !!document.querySelector('#nulavio-band .nv-band-row');"), 15)
            )
            state = m.chrome(f"return {BAND_PROBE};")
            assert_band(self, state)
            self.assertIn("apagado ao fechar", state["text"])
            self.assertIn("Janela privativa", state["text"])
            self.assertTrue(any(c["border"] == "dashed" for c in state["cues"]))
            self.assertTrue(any(c["border"] == "dotted" for c in state["cues"]))
            m.chrome("window.fullScreen = true;")
            time.sleep(0.4)
            assert_band(self, m.chrome(f"return {BAND_PROBE};"))
            m.chrome("window.fullScreen = false; window.close();")
            m.switch_to(next(iter(before)))

            m.navigate(self.shell_url_of(m) + "profiles/popup.html")
            self.assertTrue(harness.wait_until(lambda: self.ready(m), timeout=15))
            page = m.execute(
                "return {name: document.querySelector('#current .popup__name')?.textContent,"
                " dashed: document.querySelector('#current .chip')?.classList.contains('chip--temporary'),"
                " note: document.getElementById('unavailable').textContent,"
                " others: document.getElementById('others-section').hidden,"
                " protected: document.getElementById('new-profile').hidden,"
                " temporary: document.getElementById('new-temporary').hidden};"
            )
            self.assertEqual(page["name"], "Perfil temporário")
            self.assertTrue(page["dashed"])
            self.assertIn("Apagado quando você fechar a última janela dele", page["note"])
            self.assertTrue(page["others"] and page["protected"])
            self.assertFalse(page["temporary"])
            self.shoot(m, "popup-temporary")

            m.navigate(self.shell_url_of(m) + "settings/settings.html#profiles")
            self.assertTrue(harness.wait_until(lambda: self.ready(m), timeout=15))
            notice = m.execute("return document.getElementById('profiles-unavailable').textContent;")
            self.assertIn("Perfil temporário", notice)
            self.assertTrue(m.execute("return !document.getElementById('profiles-temporary').hidden;"))
        finally:
            m.quit()
            engine.wait(timeout=60)
        self.assertTrue(harness.wait_until(lambda: not path.exists(), timeout=90), "not deleted after closing")

    @staticmethod
    def shell_url_of(m) -> str:
        return m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")

    def test_03_settings_offers_a_temporary_window(self):
        self.m.navigate(self.shell_url + "settings/settings.html#profiles")
        self.assertTrue(harness.wait_until(lambda: self.ready(self.m), timeout=15))
        card = self.m.execute(
            "const c = document.getElementById('profiles-temporary');"
            "return {hidden: c.hidden, text: c.textContent, button: document.getElementById('open-temporary').textContent};"
        )
        self.assertFalse(card["hidden"])
        self.assertIn("apagado quando você fecha a última janela", card["text"])
        self.assertEqual(card["button"], "Nova janela temporária")


@unittest.skipUnless(harness.engine_available(), "needs a Gecko engine")
class TemporaryFromTheLauncherTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.Session()
        self.addCleanup(self.session.cleanup)
        self.root = self.session.home / "runtime" / "temporary"

    def run_nulavio(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(ROOT / "bin" / "nulavio"), *args], env=self.session.env, capture_output=True, text=True, timeout=120, check=True
        )

    def test_dry_run_prepares_a_temporary_profile_and_leaves_nothing(self):
        dry = self.run_nulavio("run", "--temporary", "--no-ublock", "--dry-run")
        command = dry.stdout.strip().splitlines()[-1].split()
        profile_dir = Path(command[command.index("--profile") + 1])
        self.assertEqual(profile_dir.parent, self.root)
        self.assertIn("Temporary profile, kept", dry.stdout)
        self.assertEqual(list(self.root.glob("tmp-*")), [])  # even a dry run leaves nothing behind

    # The launcher never starts the engine headless (it drops MOZ_HEADLESS), so a
    # real run opens a window: only on request, on a desktop.
    @unittest.skipUnless(os.environ.get("NULAVIO_TEST_HEADFUL") == "1", "opens a visible window (NULAVIO_TEST_HEADFUL=1)")
    def test_run_temporary_deletes_the_profile_after_the_engine_exits(self):
        launcher = subprocess.Popen(
            [str(ROOT / "bin" / "nulavio"), "run", "--temporary", "--no-ublock"],
            env=self.session.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
        )  # fmt: skip
        self.addCleanup(lambda: launcher.poll() is None and os.killpg(launcher.pid, signal.SIGKILL))

        def running():
            return [p for p in self.root.glob("tmp-*") if (p / "lock").is_symlink()]

        self.assertTrue(harness.wait_until(running, timeout=90), "the engine did not start")
        [path] = running()
        self.assertTrue(guard_is_held(path))  # held by the supervising launcher
        self.assertTrue((path / "user.js").exists())  # the launcher's baseline, as for any profile
        launcher.send_signal(signal.SIGTERM)  # the launcher ends its engine, then deletes the profile
        out, err = launcher.communicate(timeout=120)
        self.assertEqual(launcher.returncode, 0, err)
        self.assertIn("Temporary profile, kept", out)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
