"""The engine's profile chooser with protected profiles (#43): a locked one says so on its card, and
choosing it asks for its secret before it starts. Nulavio build only (patch 0011); needs gocryptfs,
FUSE and libsodium.

The chooser is the window a plain start shows when it is on, and the one "Gerenciar perfis" opens
from a running profile; both are about:profilemanager and run the same code. ProfileChooserTest drives
the second through the running profile's chrome (Marionette cannot reach a window shown before any
profile starts); screenshots go to tests/artifacts/profile-chooser/ for design review.
StartupChooserTest makes a real plain start on a private X display and types into the chooser with
the keyboard (XTest); it is skipped where Xvfb or libXtst is missing.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from nulavio_launcher import profile
from nulavio_launcher.vault import sodium, storage

PASSWORD = "artificial pass 43"
READY = sodium.available() and storage.tools_available()
SHELL = "resource://builtin-addons/nulavio-shell/modules"
PRELUDE = (
    f'const V = ChromeUtils.importESModule("{SHELL}/NulavioVault.sys.mjs").NulavioVault;'
    f'const P = ChromeUtils.importESModule("{SHELL}/NulavioProfiles.sys.mjs").NulavioProfiles;'
    'const SPS = ChromeUtils.importESModule("resource:///modules/profiles/SelectableProfileService.sys.mjs")'
    ".SelectableProfileService;"
    'const W = () => Services.wm.getMostRecentWindow("about:profilemanager");'
    "const D = () => W()?.document;"
    'const S = () => D()?.querySelector("profile-selector");'
    "const card = id => [...(S()?.profileCards ?? [])].find(c => c.profile.id === id);"
)


@unittest.skipUnless(READY and harness.nulavio_engine(), "needs the Nulavio build, gocryptfs, FUSE and libsodium")
class ProfileChooserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.shots = harness.artifacts_dir() / "profile-chooser"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        try:
            for path in cls.session.tmp.rglob("*.vault"):
                mountpoint = path.with_name(path.name[: -len(".vault")])
                box = storage.Container(mountpoint)
                if box.mounted():
                    box.unmount()
            for dirpath, _d, _f in os.walk(cls.session.tmp):
                os.chmod(dirpath, 0o700)
            cls.session.cleanup()
        except Exception:  # the mounts could not be cleared: the session still goes
            cls.session.cleanup()

    # -- helpers -------------------------------------------------------------------

    def call(self, body: str, *args):
        script = (
            "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
            f"(async () => {{ {PRELUDE} {body} }})()"
            ".then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
        )
        self.m.set_context("chrome")
        try:
            result = self.m.execute_async(script, list(args))
        finally:
            self.m.set_context("content")
        if "error" in result:
            raise AssertionError(result["error"])
        return result["ok"]

    def word(self, key: str, profile: str | None = None) -> str:
        """The chooser's message (l10n/<locale>/nulavio/chooser.ftl), in the app's language."""
        return self.call(
            "const l = new Localization(['nulavio/chooser.ftl']);"
            "return l.formatValue('nulavio-chooser-' + args[0], args[1] ? {profile: args[1]} : undefined);",
            key,
            profile,
        )

    def create_protected(self, name: str, *, keyring: bool = False) -> int:
        details = {"name": name, "templateId": "banking", "keyring": keyring, "password": PASSWORD}
        return self.call("return (await V.createProtected(args[0])).id;", details)

    def profile_path(self, profile_id: int) -> Path:
        return Path(self.call("return (await SPS.getProfile(args[0])).path;", profile_id))

    def instances(self, path: Path) -> list[int]:
        engine = str(self.session.engine.path)
        return [
            pid
            for pid in self.session.processes_for(path)
            if Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[0].decode() == engine
        ]

    def stop_instance(self, path: Path) -> None:
        for pid in self.instances(path):
            os.kill(pid, 15)
        self.assertTrue(harness.wait_until(lambda: not self.instances(path), timeout=30))

    def open_chooser(self) -> None:
        self.close_chooser()
        self.call("await P.openManager(); return true;")
        self.wait_chooser()

    def wait_chooser(self, startup: bool = False) -> None:
        ready = (
            "const s = S(); if (!s?.updateComplete) return false; await s.updateComplete;"
            f"return Boolean(s.profiles && s.initialized && s.isStartupUI === {str(startup).lower()});"
        )
        if not harness.wait_until(lambda: self.call(ready), timeout=30):
            seen = self.call(
                "const s = S(); return {window: Boolean(W()), closed: W()?.closed ?? null, url: D()?.documentURI ?? null,"
                " element: Boolean(s), profiles: s?.profiles?.length ?? null, initialized: s?.initialized ?? null,"
                " nulavio: s ? Boolean(s.nulavio) : null};"
            )
            self.fail(f"the chooser did not open: {seen}")

    def close_chooser(self) -> None:
        self.call("if (W()) { W().close(); } return true;")
        self.assertTrue(harness.wait_until(lambda: self.call("return !W();"), timeout=10), "the chooser did not close")

    def cards(self) -> dict:
        """Each card as drawn: its lock word (shown, in the corner) and what a screen reader hears."""
        script = (
            "await S().updateComplete;"
            "for (const c of S().profileCards) { await c.updateComplete; }"
            "return [...S().profileCards].map(c => {"
            " const lock = c.shadowRoot.querySelector('.nulavio-lock'); const box = lock?.getBoundingClientRect();"
            " const card = c.shadowRoot.querySelector('moz-card');"
            " const described = c.shadowRoot.getElementById(card.getAttribute('aria-describedby') || '-');"
            " return {id: c.profile.id, name: c.profile.name, lock: lock?.textContent.trim() ?? null,"
            "  shown: Boolean(box && box.width > 0 && box.height > 0), description: described?.textContent.trim() ?? null}; });"
        )
        return {str(item["id"]): item for item in self.call(script)}

    def dialog(self) -> dict | None:
        return self.call(
            "const d = D()?.getElementById('nulavio-unlock'); if (!d) return null;"
            "const shown = id => { const el = d.querySelector(id);"
            " return Boolean(el && !el.closest('[hidden]') && el.getBoundingClientRect().height > 0); };"
            "const status = d.querySelector('[role=status]');"
            "return {open: d.open, headline: d.querySelector('h2').textContent, status: status.textContent,"
            " level: status.dataset.level ?? null,"
            " password: shown('#nulavio-unlock-password'), recovery: shown('#nulavio-unlock-recovery'),"
            " keyring: shown('#nulavio-unlock-keyring'), invalid: d.querySelector('[aria-invalid=true]')?.id ?? null,"
            " focused: D().activeElement?.id ?? null, submit: d.querySelector('#nulavio-unlock-submit').textContent};"
        )

    def type_secret(self, field: str, secret: str) -> None:
        self.call(
            "const d = D(); const input = d.getElementById(args[0]); input.focus(); input.value = args[1];"
            "input.dispatchEvent(new (W().Event)('input', {bubbles: true})); input.form.requestSubmit(); return true;",
            field,
            secret,
        )

    def shoot(self, name: str) -> None:
        """The chooser window as drawn, light and dark (the engine's own colour scheme switch)."""
        for scheme, dark in (("light", 0), ("dark", 1)):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            time.sleep(0.6)
            data = self.call(
                "const w = W(); const c = w.document.createElementNS('http://www.w3.org/1999/xhtml', 'canvas');"
                "c.width = w.innerWidth; c.height = w.innerHeight; const ctx = c.getContext('2d');"
                "ctx.drawWindow(w, 0, 0, w.innerWidth, w.innerHeight, 'white'); return c.toDataURL('image/png');"
            )
            (self.shots / f"{name}-{scheme}.png").write_bytes(base64.b64decode(data.split(",", 1)[1]))
        self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")

    # -- tests ---------------------------------------------------------------------

    def test_01_a_locked_profile_says_so_and_asks_for_its_password_before_it_starts(self):
        profile_id = self.create_protected("Banco")
        path = self.profile_path(profile_id)
        self.assertFalse(storage.Container(path).mounted())
        here = self.call("return SPS.currentProfile.id;")
        self.open_chooser()
        cards = self.cards()
        locked = self.word("locked")
        self.assertEqual(cards[str(profile_id)]["lock"], locked, cards)
        self.assertTrue(cards[str(profile_id)]["shown"], cards)
        self.assertEqual(cards[str(profile_id)]["description"], locked)
        self.assertIsNone(cards[str(here)]["lock"], "an unprotected profile has no lock")
        self.shoot("01-cards")

        # Choosing it: the unlock step, in the chooser, with the password field ready.
        self.call("card(args[0]).click(); return true;", profile_id)
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20), "no unlock step")
        step = self.dialog()
        self.assertEqual(step["headline"], self.word("headline"))
        self.assertTrue(step["password"])
        self.assertFalse(step["recovery"])
        self.assertEqual(step["focused"], "nulavio-unlock-password")
        self.assertEqual(self.instances(path), [], "nothing started before the password")
        self.shoot("02-unlock")

        # A wrong password: said with the field, and nothing starts.
        self.type_secret("nulavio-unlock-password", "not the password")
        wrong = self.word("wrong-password")
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("status") == wrong, timeout=60), self.dialog())
        step = self.dialog()
        self.assertEqual(step["level"], "error")
        self.assertEqual(step["invalid"], "nulavio-unlock-password")
        self.assertEqual(self.instances(path), [])
        self.assertFalse(storage.Container(path).mounted())
        self.shoot("03-wrong")

        # The right one: unlocked, the chooser closes, and the profile starts.
        self.type_secret("nulavio-unlock-password", PASSWORD)
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=90), "the profile did not start")
        self.assertTrue(harness.wait_until(lambda: self.call("return !W();"), timeout=10), "the chooser stayed open")
        self.assertTrue(storage.Container(path).mounted())
        self.stop_instance(path)
        self.assertTrue(harness.wait_until(lambda: not storage.Container(path).mounted(), timeout=60), "it did not lock again")

    def test_02_going_back_starts_nothing_and_the_recovery_code_is_offered(self):
        profile_id = self.create_protected("Trabalho")
        path = self.profile_path(profile_id)
        self.open_chooser()
        self.call("card(args[0]).click(); return true;", profile_id)
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20))
        # The recovery code instead of the password, and back.
        self.call("D().getElementById('nulavio-unlock-use-recovery').click(); return true;")
        step = self.dialog()
        self.assertTrue(step["recovery"])
        self.assertFalse(step["password"])
        self.assertEqual(step["focused"], "nulavio-unlock-recovery")
        self.assertEqual(step["submit"], self.word("unlock-recovery"))
        self.type_secret("nulavio-unlock-recovery", "AAAA")
        malformed = self.word("recovery-malformed")
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("status") == malformed, timeout=60), self.dialog())
        self.shoot("04-recovery")
        self.call("D().getElementById('nulavio-unlock-cancel').click(); return true;")  # back to the password
        self.assertTrue(self.dialog()["password"])
        # Escape: the step goes, the chooser stays, nothing starts.
        escape = "D().getElementById('nulavio-unlock').dispatchEvent(new (W().Event)('cancel', {cancelable: true})); return true;"
        self.call(escape)
        self.assertTrue(harness.wait_until(lambda: self.dialog() is None, timeout=5))
        self.assertTrue(self.call("return Boolean(W());"))
        time.sleep(2)
        self.assertEqual(self.instances(path), [])
        self.assertFalse(storage.Container(path).mounted())
        # The edit and delete buttons of a locked card go through the same step.
        self.call("card(args[0]).editButton.click(); return true;", profile_id)
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20), "edit skipped the unlock step")
        self.call("D().getElementById('nulavio-unlock-cancel').click(); return true;")
        self.call("card(args[0]).deleteButton.click(); return true;", profile_id)
        self.assertTrue(
            harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20), "delete skipped the unlock step"
        )
        self.call("D().getElementById('nulavio-unlock-cancel').click(); return true;")
        self.assertEqual(self.instances(path), [])
        self.close_chooser()

    def test_03_at_start_up_the_unlocked_profile_is_the_one_handed_to_the_engine(self):
        """The start-up chooser is the same page with the engine's parameter block (window.arguments): on launch it
        writes the chosen profile's folders there and closes, and the engine then starts that profile. Marionette
        cannot reach the real one (it runs before any profile), so the page is opened here with a block of its own,
        and what it hands back is read: the protected profile, already unlocked. Last test of the module: as at start-up,
        the page stops this process's profile service."""
        profile_id = self.create_protected("Saúde")
        path = self.profile_path(profile_id)
        self.close_chooser()
        self.call(
            "const block = Cc['@mozilla.org/embedcomp/dialogparam;1'].createInstance(Ci.nsIDialogParamBlock);"
            "block.objects = Cc['@mozilla.org/array;1'].createInstance(Ci.nsIMutableArray);"
            "Services.wm.getMostRecentBrowserWindow().nulavioStartupBlock = block;"
            "Services.ww.openWindow(null, 'about:profilemanager', '_blank', 'chrome,centerscreen,resizable', block); return true;"
        )
        self.wait_chooser(startup=True)
        self.assertEqual(self.cards()[str(profile_id)]["lock"], self.word("locked"))
        self.call("card(args[0]).click(); return true;", profile_id)
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20), "no unlock step")
        self.assertEqual(
            self.call("return Services.wm.getMostRecentBrowserWindow().nulavioStartupBlock.objects.length;"),
            0,
            "handed over before the password",
        )
        self.type_secret("nulavio-unlock-password", PASSWORD)
        self.assertTrue(harness.wait_until(lambda: self.call("return !W();"), timeout=90), "the page did not close")
        handed = self.call(
            "const b = Services.wm.getMostRecentBrowserWindow().nulavioStartupBlock;"
            "return {action: b.GetInt(0), launch: Ci.nsIToolkitProfileService.launchWithProfile,"
            " root: b.objects.length ? b.objects.queryElementAt(0, Ci.nsIFile).path : null};"
        )
        self.assertEqual(handed["action"], handed["launch"], handed)
        self.assertEqual(Path(handed["root"]), path)
        self.assertTrue(storage.Container(path).mounted(), "handed over locked")
        self.assertEqual(self.instances(path), [], "the page starts nothing itself at start-up")
        # Nothing starts it here; the Vault's watcher would lock it again after its 120 s grace. Locked now instead.
        self.call(
            "const { helper } = ChromeUtils.importESModule(args[0] + '/NulavioVault.sys.mjs');"
            "await helper({op: 'lock', path: args[1]}); return true;",
            SHELL,
            str(path),
        )
        self.assertFalse(storage.Container(path).mounted())


class Keyboard:
    """Keys typed into a private X display through XTest, as a person's keyboard."""

    def __init__(self, display: str):
        self.x = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11"))
        self.xtst = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xtst"))
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XStringToKeysym.restype = ctypes.c_ulong
        self.x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self.x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self.x.XFlush.argtypes = [ctypes.c_void_p]
        self.x.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x.XQueryTree.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)), ctypes.POINTER(ctypes.c_uint),
        ]  # fmt: skip
        self.x.XFree.argtypes = [ctypes.c_void_p]
        self.xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.display = self.x.XOpenDisplay(display.encode())
        if not self.display:
            raise RuntimeError(f"no X display at {display}")

    def windows(self) -> int:
        """How many top-level windows the display has."""
        root, parent, count = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_uint()
        children = ctypes.POINTER(ctypes.c_ulong)()
        self.x.XQueryTree(self.display, self.x.XDefaultRootWindow(self.display), root, parent, children, count)
        if children:
            self.x.XFree(children)
        return count.value

    def key(self, name: str) -> None:
        code = self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(name.encode()))
        self.xtst.XTestFakeKeyEvent(self.display, code, 1, 0)
        self.xtst.XTestFakeKeyEvent(self.display, code, 0, 0)
        self.x.XFlush(self.display)
        time.sleep(0.15)

    def type(self, text: str) -> None:
        for character in text:
            self.key("space" if character == " " else character)


XTEST = bool(shutil.which("Xvfb") and ctypes.util.find_library("X11") and ctypes.util.find_library("Xtst"))


@unittest.skipUnless(
    READY and harness.nulavio_engine() and XTEST, "needs the Nulavio build, gocryptfs, FUSE, libsodium, Xvfb and libXtst"
)
class StartupChooserTest(unittest.TestCase):
    """The chooser a plain start shows, before any profile has started: no Shell, no Marionette. A person's
    keyboard on a private display: the locked profile chosen, its password typed, and the engine starts in it."""

    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.xvfb = None
        self.engines = []
        self.addCleanup(self.clean)

    def clean(self) -> None:
        for engine in self.engines:
            if engine.poll() is None:
                os.killpg(engine.pid, 15)
                try:
                    engine.wait(30)
                except subprocess.TimeoutExpired:
                    os.killpg(engine.pid, 9)
        try:
            for path in self.session.tmp.rglob("*.vault"):
                box = storage.Container(path.with_name(path.name[: -len(".vault")]))
                harness.wait_until(lambda box=box: not profile.Profile(name="x", path=box.mountpoint).running_pid(), timeout=30)
                if box.mounted():
                    box.unmount(wait=30, lazy_after=True)
            for dirpath, _d, _f in os.walk(self.session.tmp):
                os.chmod(dirpath, 0o700)
        finally:
            self.session.cleanup()
            if self.xvfb is not None:
                self.xvfb.terminate()
                self.xvfb.wait(10)

    def plain_start(self, env: dict) -> subprocess.Popen:
        """As the desktop entry starts it: no flags, no profile named."""
        engine = subprocess.Popen(
            [str(self.session.engine.path)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        self.engines.append(engine)
        return engine

    def test_a_locked_profile_chosen_at_start_up_is_unlocked_and_started(self):
        m = self.session.start()
        script = (
            "const done = arguments[arguments.length - 1];"
            f'(async () => {{ const V = ChromeUtils.importESModule("{SHELL}/NulavioVault.sys.mjs").NulavioVault;'
            'const SPS = ChromeUtils.importESModule("resource:///modules/profiles/SelectableProfileService.sys.mjs")'
            ".SelectableProfileService;"
            "const made = await V.createProtected(arguments[0]); await SPS.setShowProfileSelectorWindow(true);"
            "return (await SPS.getProfile(made.id)).path; })().then(v => done({ok: v}), e => done({error: String(e)}));"
        )
        m.set_context("chrome")
        # "Banco" sorts before "Pessoal": its card is the first stop of the keyboard.
        made = m.execute_async(script, [{"name": "Banco", "templateId": "banking", "keyring": False, "password": PASSWORD}])
        self.assertNotIn("error", made, made)
        path = Path(made["ok"])
        protected = profile.Profile(name=path.name, path=path)
        self.session.stop()
        ini = next(Path(self.session.env["HOME"]).rglob("profiles.ini"))
        self.assertIn("ShowSelector=1", ini.read_text())
        plain = {name: value for name, value in self.session.env.items() if name != "MOZ_MARIONETTE"}
        # The harness started the profile by name, so this installation has no default profile yet, and the
        # chooser is for a default start: a first plain start makes it the default, the second shows the chooser.
        first = self.plain_start(plain)
        self.assertTrue(harness.wait_until(lambda: "Default=1" in ini.read_text(), timeout=60), ini.read_text())
        time.sleep(3)
        os.killpg(first.pid, 15)
        first.wait(30)
        self.assertFalse(storage.Container(path).mounted())

        read, write = os.pipe()
        self.xvfb = subprocess.Popen(
            ["Xvfb", "-displayfd", str(write), "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
            pass_fds=[write], stderr=subprocess.DEVNULL,
        )  # fmt: skip
        os.close(write)
        display = ":" + os.read(read, 16).decode().strip()
        os.close(read)
        keyboard = Keyboard(display)
        headful = {k: v for k, v in plain.items() if k != "MOZ_HEADLESS"} | {"DISPLAY": display, "GDK_BACKEND": "x11"}
        self.plain_start(headful)
        self.assertTrue(harness.wait_until(lambda: keyboard.windows() > 0, timeout=60), "no window at the plain start")
        time.sleep(6)  # the chooser's cards: there is no engine to ask when they are drawn
        self.assertIsNone(protected.running_pid())
        self.assertFalse(storage.Container(path).mounted(), "unlocked before anything was typed")
        keyboard.key("Tab")  # the first card: the locked profile
        keyboard.key("Return")
        time.sleep(3)  # the unlock step, the password field focused
        self.assertFalse(storage.Container(path).mounted(), "unlocked before the password")
        keyboard.type(PASSWORD)
        keyboard.key("Return")
        self.assertTrue(
            harness.wait_until(lambda: storage.Container(path).mounted(), timeout=90), "the password did not unlock it"
        )
        self.assertTrue(
            harness.wait_until(lambda: protected.running_pid(), timeout=90), "the engine did not start in the profile"
        )
        self.assertTrue((path / "prefs.js").exists() or (path / "times.json").exists(), "an empty folder was started")


if __name__ == "__main__":
    unittest.main()
