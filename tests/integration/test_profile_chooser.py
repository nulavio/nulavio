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

    def assert_locks_again(self, path: Path, timeout: float = 90) -> None:
        """After its engine is gone, the profile's watcher locks it; a failure says what the watcher would see."""
        if harness.wait_until(lambda: not storage.Container(path).mounted(), timeout=timeout):
            return
        lock = path / "lock"
        target = os.readlink(lock) if lock.is_symlink() else None
        pid = profile.Profile(name=path.name, path=path).running_pid()
        state = Path(f"/proc/{pid}/stat").read_text().split()[2] if pid and Path(f"/proc/{pid}/stat").exists() else None
        watchers = [
            entry.name
            for entry in Path("/proc").iterdir()
            if entry.name.isdigit() and (entry / "cmdline").exists() and b"autolock" in (entry / "cmdline").read_bytes()
            and str(path).encode() in (entry / "cmdline").read_bytes()
        ]  # fmt: skip
        self.fail(f"it did not lock again: lock -> {target}, running_pid {pid} (state {state}), watchers {watchers}")

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
            " focused: D().activeElement?.id ?? null, submit: d.querySelector('#nulavio-unlock-submit')?.textContent ?? null};"
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
                "ctx.drawWindow(w, w.scrollX, w.scrollY, w.innerWidth, w.innerHeight, 'white'); return c.toDataURL('image/png');"
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
        # The engine took the profile; stopped at once, the watcher still sees it came and locks again (#277).
        self.assertTrue(
            harness.wait_until(lambda: (path / "lock").is_symlink(), timeout=60), "the engine did not take the profile"
        )
        self.stop_instance(path)
        self.assert_locks_again(path)

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

    def test_02b_one_step_at_a_time_and_ordinary_profiles_need_no_vault_tools(self):
        """Review of #267. Two activations at once gave two unlock steps, one under the other. And on a computer
        without gocryptfs, FUSE or libsodium (they are optional) every profile was refused, the ones without a
        password too: whether a profile is protected is now read from its files, not asked of the tools."""
        profile_id = self.create_protected("Cofre")
        path = self.profile_path(profile_id)
        here = self.call("return SPS.currentProfile.id;")
        self.open_chooser()
        # Two activations before the first has read anything: one step, and going back leaves none.
        self.call("card(args[0]).click(); card(args[0]).click(); return true;", profile_id)
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20))
        time.sleep(1)
        self.assertEqual(self.call("return D().querySelectorAll('dialog').length;"), 1)
        self.call("D().getElementById('nulavio-unlock-cancel').click(); return true;")
        self.assertTrue(harness.wait_until(lambda: self.dialog() is None, timeout=5))
        self.assertEqual(self.call("return D().querySelectorAll('dialog').length;"), 0)
        # Without the Vault's tools: a profile without a password is launched as ever; a locked one says why not.
        allowed = "return S().nulavio.beforeLaunch(D(), await SPS.getProfile(args[0]));"
        tools = Path(self.session.engine.path).parent / "nulavio-tools"
        hidden = tools.with_name("nulavio-tools.hidden-by-test")
        os.rename(tools, hidden)
        try:
            self.assertIs(self.call(allowed, here), True)
            self.assertIsNone(self.dialog())
            self.assertEqual(self.cards()[str(profile_id)]["lock"], self.word("locked"))  # the lock needs no tools either
            self.call("card(args[0]).click(); return true;", profile_id)
            self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20))
            notice = self.dialog()
            self.assertEqual(notice["headline"], self.word("unavailable-headline"))
            self.assertEqual(notice["status"], self.word("storage-missing"))
            self.assertFalse(notice["password"] or notice["recovery"], "a field for a secret that nothing can check")
            self.shoot("05-tools-missing")
            self.call("D().getElementById('nulavio-unlock-cancel').click(); return true;")
            self.assertTrue(harness.wait_until(lambda: self.dialog() is None, timeout=5))
        finally:
            os.rename(hidden, tools)
        self.assertEqual(self.instances(path), [])
        self.assertFalse(storage.Container(path).mounted())
        # A profile that got a password while the chooser stayed open: what the window read when it opened is not
        # what decides. Its card, drawn without a lock, now leads to the unlock step.
        plain_id = self.call("return P.create({name: 'Depois'});")
        plain = self.profile_path(plain_id)
        self.close_chooser()
        self.open_chooser()
        self.assertIsNone(self.cards()[str(plain_id)]["lock"])
        self.call(
            "const { helper } = ChromeUtils.importESModule(args[0] + '/NulavioVault.sys.mjs');"
            "await helper({op: 'encrypt', path: args[1], password: args[2]}); return true;",
            SHELL,
            str(plain),
            PASSWORD,
        )
        self.call("card(args[0]).click(); return true;", plain_id)
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20), "started without its password")
        self.assertEqual(self.dialog()["headline"], self.word("headline"))
        self.call("D().getElementById('nulavio-unlock-cancel').click(); return true;")
        self.assertEqual(self.instances(plain), [])
        # Review, round 2. The volume's own record, planted in the bare folder of the locked profile (its owner can
        # do that): the folder is not a mounted volume, so it is not "unlocked", and nothing starts without the
        # unlock step. A container whose key file is gone is not a profile without a password either.
        box = storage.Container(path)
        os.chmod(path, 0o700)
        (path / storage.STATE_DIR).mkdir()
        (path / storage.STATE_DIR / "state.json").write_text("{}")
        try:
            self.call("card(args[0]).click(); return true;", profile_id)
            self.assertTrue(
                harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20), "started on the bare folder"
            )
            self.assertEqual(self.dialog()["headline"], self.word("headline"))
            self.call("D().getElementById('nulavio-unlock-cancel').click(); return true;")
        finally:
            os.chmod(path, 0o700)  # the tools made the folder read-only again when they were asked about it
            shutil.rmtree(path / storage.STATE_DIR)
            os.chmod(path, storage.LOCKED_MODE)
        moved = box.vault_path.with_name("vault.json.moved-by-test")
        os.rename(box.vault_path, moved)
        try:
            self.call("card(args[0]).click(); return true;", profile_id)
            self.assertTrue(
                harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20), "started without its key file"
            )
            self.assertEqual(self.dialog()["headline"], self.word("unread-headline"))
            self.call("D().getElementById('nulavio-unlock-cancel').click(); return true;")
        finally:
            os.rename(moved, box.vault_path)
        self.assertEqual(self.instances(path), [])
        self.close_chooser()

    def test_02d_with_every_profile_behind_a_password_the_chooser_is_not_a_choice(self):
        """#43, slice 2: with no profile that opens without a password, the chooser is the only way in. Its
        "show at start-up" checkbox is then ticked, cannot be changed, and says why."""
        self.open_chooser()
        answers = self.call(
            "const m = S().nulavio; const two = [{id: 1}, {id: 2}]; const is = v => ({protected: v});"
            "return [m.mustChoose(two, new Map([[1, is(true)], [2, is(true)]])),"
            " m.mustChoose(two, new Map([[1, is(true)], [2, is(false)]])),"
            # One whose state is not known, beside a protected one: it is not a profile a plain start could open,
            # so the chooser stays the only way in (NulavioProfiles goes by the same rule and keeps it on).
            " m.mustChoose(two, new Map([[1, is(true)]])),"
            " m.mustChoose(two, new Map()), m.mustChoose(two, null),"  # nothing known: nothing decided
            " m.mustChoose([], new Map())];"
        )
        note = self.word("must-choose")
        self.assertEqual(answers, [note, None, note, None, None, None])
        box = (
            "await S().updateComplete; const c = S().checkbox;"
            "return {checked: c.checked, disabled: c.disabled, says: c.querySelector('[slot=description]').textContent.trim()};"
        )
        self.assertFalse(self.call(box)["disabled"])  # this session's profile has no password
        self.call("S().nulavioMustChoose = args[0]; return true;", note)
        self.assertEqual(self.call(box), {"checked": True, "disabled": True, "says": note})
        # A click that got through changes nothing: the setting is off in this session (Nulavio's default, and this
        # session's profile has no password), and the box, drawn ticked, would have switched it on.
        stored = "return SPS.groupToolkitProfile.showProfileSelector;"
        self.assertFalse(self.call(stored))
        self.call("S().handleCheckboxToggle(); return true;")
        self.assertFalse(self.call(stored))
        # The same click with the box a choice again does switch it on: the guard is what held it.
        self.call("S().nulavioMustChoose = null; await S().updateComplete; S().checkbox.checked = true; return true;")
        self.call("S().handleCheckboxToggle(); return true;")
        self.assertTrue(harness.wait_until(lambda: self.call(stored), timeout=10))
        self.call("await SPS.setShowProfileSelectorWindow(false); S().nulavioMustChoose = args[0]; return true;", note)
        self.call("await S().updateComplete; return true;")
        self.assertFalse(self.call(stored))
        # The engine greys the label of a control that cannot be changed. The words that say why are its description,
        # and keep a description's colour: 69% of the page's text colour, where the greyed label keeps 40%.
        share = lambda: self.call(  # noqa: E731
            "const note = S().checkbox.querySelector('[slot=description]');"
            "const parts = note.ownerDocument.defaultView.getComputedStyle(note).color.match(/[\\d.]+/g).map(Number);"
            "return parts.length > 3 ? parts.at(-1) : 1;"
        )
        self.assertTrue(harness.wait_until(lambda: share() >= 0.69, timeout=10), f"the reason is too faint to read: {share()}")
        self.call("S().checkbox.scrollIntoView({block: 'center'}); return true;")
        self.shoot("07-must-choose")
        self.close_chooser()

    def test_02c_a_profile_that_locked_again_while_a_note_was_read_is_unlocked_again(self):
        """Review of #267. An unlock that settles a recovery code replacement (#187) says so and waits for
        "Abrir". The profile's watcher locks it again when nothing opens it for two minutes; opened then, the
        engine got the locked folder, which is the failure this chooser removes."""
        profile_id = self.create_protected("Aviso")
        path = self.profile_path(profile_id)
        self.call("return V.change(args[0], 'new-recovery-code', {current: args[1]}).then(() => true);", profile_id, PASSWORD)
        self.open_chooser()
        self.call("card(args[0]).click(); return true;", profile_id)
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("open"), timeout=20))
        self.type_secret("nulavio-unlock-password", PASSWORD)
        undone = self.word("recovery-undone")
        self.assertTrue(
            harness.wait_until(lambda: (self.dialog() or {}).get("status", "").startswith(undone), timeout=90), self.dialog()
        )
        note = self.dialog()
        self.assertEqual((note["level"], note["submit"], note["password"]), ("warn", self.word("open", "Aviso"), False))
        self.assertTrue(storage.Container(path).mounted())
        self.assertEqual(self.instances(path), [], "started before the note was acknowledged")
        self.shoot("06-settled-note")
        # As its watcher does after two minutes with no engine: locked again while the note is on screen.
        self.call(
            "const { helper } = ChromeUtils.importESModule(args[0] + '/NulavioVault.sys.mjs');"
            "await helper({op: 'lock', path: args[1]}); return true;",
            SHELL,
            str(path),
        )
        self.assertFalse(storage.Container(path).mounted())
        self.call("D().getElementById('nulavio-unlock-submit').click(); return true;")
        again = self.word("locked-again")
        self.assertTrue(harness.wait_until(lambda: (self.dialog() or {}).get("status") == again, timeout=20), self.dialog())
        step = self.dialog()
        self.assertTrue(step["password"])
        self.assertEqual(step["submit"], self.word("unlock"))
        self.assertTrue(self.call("return Boolean(W());"), "the chooser went away with the profile locked")
        self.assertEqual(self.instances(path), [], "the engine was started on a locked folder")
        # Unlocked again (nothing left to settle now): it starts.
        self.type_secret("nulavio-unlock-password", PASSWORD)
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=90), "the profile did not start")
        self.assertTrue(
            harness.wait_until(lambda: (path / "lock").is_symlink(), timeout=60), "the engine did not take the profile"
        )
        self.stop_instance(path)
        self.assert_locks_again(path)

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


class _XImage(ctypes.Structure):
    """The head of Xlib's XImage: enough to read the pixels of a picture of the display."""

    _fields_ = [
        ("width", ctypes.c_int), ("height", ctypes.c_int), ("xoffset", ctypes.c_int), ("format", ctypes.c_int),
        ("data", ctypes.POINTER(ctypes.c_char)), ("byte_order", ctypes.c_int), ("bitmap_unit", ctypes.c_int),
        ("bitmap_bit_order", ctypes.c_int), ("bitmap_pad", ctypes.c_int), ("depth", ctypes.c_int),
        ("bytes_per_line", ctypes.c_int), ("bits_per_pixel", ctypes.c_int),
    ]  # fmt: skip


class Keyboard:
    """Keys typed into a private X display through XTest, as a person's keyboard; and what that display shows,
    which is all there is to wait on where no engine can be asked (the chooser before any profile has started)."""

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
        self.x.XDisplayWidth.argtypes = self.x.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.x.XGetImage.restype = ctypes.POINTER(_XImage)
        integer, cardinal = ctypes.c_int, ctypes.c_uint
        self.x.XGetImage.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            integer,
            integer,
            cardinal,
            cardinal,
            ctypes.c_ulong,
            integer,
        ]
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

    def picture(self) -> bytes | None:
        """The display's pixels as they are now, or None when it could not be read."""
        width, height = self.x.XDisplayWidth(self.display, 0), self.x.XDisplayHeight(self.display, 0)
        image = self.x.XGetImage(self.display, self.x.XDefaultRootWindow(self.display), 0, 0, width, height, 0xFFFFFFFF, 2)
        if not image:
            return None
        try:
            return ctypes.string_at(image.contents.data, image.contents.bytes_per_line * image.contents.height)
        finally:
            self.x.XFree(image.contents.data)
            self.x.XFree(image)

    def drawn(self, after: bytes | None = None, apart: float = 0.5, times: int = 3, timeout: float = 90) -> bytes | None:
        """Wait until the display shows a page and has stopped changing: `times` pictures `apart` seconds from
        each other are the same, they are not a bare window (a page has text and pictures: many colours), and
        they are not `after`, the picture from before the step waited on. Answers that picture, or None when
        the time is up. With a text cursor blinking in the picture, ask for two pictures a fifth of a second apart."""
        end = time.monotonic() + timeout
        seen: list[bytes | None] = []
        while time.monotonic() < end:
            seen = [*seen[-(times - 1) :], self.picture()] if times > 1 else [self.picture()]
            now = seen[-1]
            if now and len(seen) == times and all(each == now for each in seen) and now != after:
                colours = {now[at : at + 4] for at in range(0, len(now), 4 * 97)}  # one pixel in 97
                if len(colours) > 32:
                    return now
            time.sleep(apart)
        return None

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

    def plain_start(self, env: dict, *addresses: str) -> subprocess.Popen:
        """As the desktop entry starts it: no flags, no profile named; with an address, as a link opened by
        another program starts it."""
        engine = subprocess.Popen(
            [str(self.session.engine.path), *addresses],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.engines.append(engine)
        return engine

    def chrome(self, m, body: str, *args):
        """Run `body` in an instance's chrome, with the Shell's modules at hand; an error comes back as its code."""
        script = (
            "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
            f"(async () => {{ {PRELUDE} {body} }})()"
            ".then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
        )
        m.set_context("chrome")
        try:
            return m.execute_async(script, list(args))
        finally:
            m.set_context("content")

    def private_display(self) -> tuple[str, Keyboard]:
        read, write = os.pipe()
        self.xvfb = subprocess.Popen(
            ["Xvfb", "-displayfd", str(write), "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
            pass_fds=[write], stderr=subprocess.DEVNULL,
        )  # fmt: skip
        os.close(write)
        display = ":" + os.read(read, 16).decode().strip()
        os.close(read)
        return display, Keyboard(display)

    @staticmethod
    def capture(display: str, name: str) -> None:
        """The private display as a picture, for design review (where ImageMagick is installed). Nothing is asserted on it."""
        tool = shutil.which("import")
        if tool:
            shots = harness.artifacts_dir() / "profile-chooser"
            shots.mkdir(parents=True, exist_ok=True)
            subprocess.run([tool, "-display", display, "-window", "root", str(shots / f"{name}.png")], check=False, timeout=30)

    def test_with_every_profile_behind_a_password_a_plain_start_asks_which_one_and_its_password(self):
        """#43, slice 2. The last profile without a password is deleted from a window of a protected one, after
        the person was told what follows. From then on a plain start shows the chooser, the profile chosen is
        unlocked there and started, and no new, empty profile is made outside the group (what the engine did when
        it was started straight on a locked folder, #68)."""
        helper = f"const {{ helper }} = ChromeUtils.importESModule('{SHELL}/NulavioVault.sys.mjs');"
        m = self.session.start()
        details = {"name": "Banco", "templateId": "banking", "keyring": False, "password": PASSWORD}
        made = self.chrome(
            m,
            "const made = await V.createProtected(args[0]);"
            "return {id: made.id, path: (await SPS.getProfile(made.id)).path, here: SPS.currentProfile.id};",
            details,
        )["ok"]
        path = Path(made["path"])
        protected = profile.Profile(name=path.name, path=path)
        ini = next(Path(self.session.env["HOME"]).rglob("profiles.ini"))
        # As on a person's computer, where the first start made this the installation's default (the harness starts
        # the profile by name, which does not): one plain start, then back to the session.
        self.session.stop()
        plain = {name: value for name, value in self.session.env.items() if name != "MOZ_MARIONETTE"}
        first = self.plain_start(plain)
        self.assertTrue(harness.wait_until(lambda: "Default=1" in ini.read_text(), timeout=60), ini.read_text())
        time.sleep(3)
        os.killpg(first.pid, 15)
        first.wait(30)
        m = self.session.restart()
        # The protected profile's own window, driven too: its test prefs are written while it is unlocked.
        opened = self.chrome(
            m,
            helper + "return helper({op: 'unlock', path: args[0], method: 'password', secret: args[1], autolock: false});",
            str(path),
            PASSWORD,
        )
        self.assertEqual(opened.get("ok", {}).get("unlocked"), True, opened)
        harness.GeckoProfileSession.enable_marionette(path)
        self.assertEqual(
            self.chrome(m, helper + "return helper({op: 'lock', path: args[0]});", str(path)).get("ok"), {"locked": True}
        )
        self.assertEqual(
            self.chrome(m, "return V.unlock(args[0], 'password', args[1]);", made["id"], PASSWORD).get("ok"),
            {"opened": "launched"},
        )
        self.assertTrue(
            harness.wait_until(lambda: self.session.processes_for(path), timeout=60), "the protected profile did not start"
        )
        banco = harness.GeckoProfileSession.connect(path, timeout=90)
        # While the profile without a password is still running it cannot be deleted. The chooser, switched on
        # for the deletion, goes back to what it was: it is not left on for a profile that is still there.
        self.assertNotIn("ShowSelector=1", ini.read_text())
        self.assertEqual(
            self.chrome(banco, "return P.remove(args[0], {lastUnprotected: true});", made["here"]).get("error"), "in-use"
        )
        # (What shows the going back is the value the instance holds; the file is read too, once it has settled.)
        self.assertFalse(self.chrome(banco, "return SPS.groupToolkitProfile.showProfileSelector;").get("ok"))
        self.assertTrue(harness.wait_until(lambda: "ShowSelector=1" not in ini.read_text(), timeout=20), ini.read_text())
        self.session.stop()  # the profile without a password is closed: only the protected one runs
        # Without the person's word it stays; with it, the chooser is switched on and the profile goes.
        self.assertEqual(self.chrome(banco, "return P.remove(args[0]);", made["here"]).get("error"), "last-unprotected")
        self.assertNotIn("ShowSelector=1", ini.read_text())
        # When profiles.ini cannot be written, the chooser cannot be relied on at the next start: nothing is
        # deleted, and the setting is as it was. (The folder of profiles.ini is made read-only for the call: the
        # engine writes that file by putting a new one in its place.)
        names = "return (await P.list()).profiles.map(p => p.name).sort();"
        listed = self.chrome(banco, names).get("ok")
        self.assertEqual(len(listed), 2, listed)
        mode = ini.parent.stat().st_mode
        ini.parent.chmod(0o500)
        try:
            refused = self.chrome(banco, "return P.remove(args[0], {lastUnprotected: true});", made["here"])
        finally:
            ini.parent.chmod(mode)
        self.assertEqual(refused.get("error"), "chooser-not-set", refused)
        self.assertEqual(self.chrome(banco, names).get("ok"), listed)
        self.assertTrue(Path(self.session.profile_dir).is_dir(), "the profile's folder went although nothing was written")
        self.assertFalse(self.chrome(banco, "return SPS.groupToolkitProfile.showProfileSelector;").get("ok"))
        self.assertNotIn("ShowSelector=1", ini.read_text())
        self.assertEqual(
            self.chrome(banco, "return P.remove(args[0], {lastUnprotected: true});", made["here"]).get("ok"),
            {"lastUnprotected": True},
        )
        self.assertIn("ShowSelector=1", ini.read_text())  # in the file by the time the answer is back
        self.assertEqual(
            self.chrome(banco, "return (await P.list()).profiles.map(p => [p.name, p.encrypted]);").get("ok"), [["Banco", True]]
        )
        # Nothing in this instance switches it off again while every profile is protected.
        self.chrome(banco, "await SPS.setShowProfileSelectorWindow(false); return true;")
        self.assertTrue(self.chrome(banco, "return SPS.groupToolkitProfile.showProfileSelector;").get("ok"))
        # The chooser as this group gets it, read where it can be read (this instance's own): the checkbox is
        # worked out from the profiles' locks, ticked and fixed, with the reason. And a setting found off (put so
        # here behind the service's back, as a lost write would leave it) is switched on by the chooser itself.
        self.chrome(banco, "SPS.groupToolkitProfile.showProfileSelector = false; await P.openManager(); return true;")
        box = (
            "const s = S(); if (!s?.initialized) return null; await s.updateComplete; const c = s.checkbox;"
            "return {must: s.nulavioMustChoose, checked: c.checked, disabled: c.disabled,"
            " says: c.querySelector('[slot=description]').textContent.trim(),"
            " stored: SPS.groupToolkitProfile.showProfileSelector};"
        )
        self.assertTrue(harness.wait_until(lambda: self.chrome(banco, box).get("ok"), timeout=30), "the chooser did not open")
        shown = self.chrome(banco, box)["ok"]
        self.assertTrue(shown["must"], shown)
        self.assertEqual(shown, {"must": shown["must"], "checked": True, "disabled": True, "says": shown["must"], "stored": True})
        self.chrome(banco, "W()?.close(); return true;")
        time.sleep(7)  # the engine's own late write of the start-up entry (five seconds) is over
        banco.quit()
        self.assertTrue(harness.wait_until(lambda: not self.session.processes_for(path), timeout=60), "it did not close")
        self.assertTrue(harness.wait_until(lambda: not storage.Container(path).mounted(), timeout=90), "it did not lock")
        self.assertIn("ShowSelector=1", ini.read_text())
        # The start-up entry is the protected profile, not the folder of the one that was deleted.
        sections = lambda: sorted(line for line in ini.read_text().splitlines() if line.startswith(("[Profile", "Path=")))  # noqa: E731
        self.assertEqual(sections(), [f"Path={path.name}", "[Profile0]"])
        gone = Path(self.session.profile_dir)
        self.assertFalse(gone.exists())
        folders = sorted(entry.name for entry in path.parent.iterdir())

        display, keyboard = self.private_display()
        headful = {k: v for k, v in plain.items() if k != "MOZ_HEADLESS"} | {"DISPLAY": display, "GDK_BACKEND": "x11"}
        # A link opened by another program while Nulavio is closed is a start too: there as well a window asks
        # first, nothing is started on the locked folder and no profile is made. (Nothing is chosen: closed again.)
        linked = self.plain_start(headful, "http://127.0.0.1:9/a-link-from-another-program")
        self.assertTrue(harness.wait_until(lambda: keyboard.windows() > 0, timeout=60), "no window at a start with a link")
        self.assertIsNotNone(keyboard.drawn(), "the window of a start with a link stayed bare")
        self.capture(display, "startup-every-profile-protected-link")
        time.sleep(3)  # nothing is asked of it: time for a profile to be started or made, if one were going to be
        self.assertIsNone(protected.running_pid(), "a link started the engine straight on the locked profile")
        self.assertFalse(storage.Container(path).mounted())
        self.assertEqual(sections(), [f"Path={path.name}", "[Profile0]"], "a link made a profile outside the group")
        self.assertEqual(sorted(entry.name for entry in path.parent.iterdir()), folders, "a link made a new profile folder")
        os.killpg(linked.pid, 15)
        linked.wait(30)
        self.assertTrue(harness.wait_until(lambda: keyboard.windows() == 0, timeout=30), "the window of that start stayed")
        self.plain_start(headful)
        self.assertTrue(harness.wait_until(lambda: keyboard.windows() > 0, timeout=60), "no window at the plain start")
        # No engine can be asked when the chooser's cards are drawn, so the display is: a page, no longer changing.
        cards = keyboard.drawn()
        self.assertIsNotNone(cards, "the chooser's window stayed bare")
        self.assertIsNone(protected.running_pid(), "started straight on the locked profile")
        self.assertFalse(storage.Container(path).mounted())
        self.capture(display, "startup-every-profile-protected")
        keyboard.key("Tab")  # the only card
        focused = keyboard.drawn(after=cards)
        self.assertIsNotNone(focused, "Tab did not put the keyboard on the card")
        keyboard.key("Return")
        # The unlock step is on the display (its field has a blinking cursor: two pictures close together).
        self.assertIsNotNone(keyboard.drawn(after=focused, apart=0.2, times=2), "the unlock step did not open")
        self.capture(display, "startup-every-profile-protected-unlock")
        keyboard.type(PASSWORD)
        keyboard.key("Return")
        self.assertTrue(
            harness.wait_until(lambda: storage.Container(path).mounted(), timeout=90), "the password did not unlock it"
        )
        self.assertTrue(
            harness.wait_until(lambda: protected.running_pid(), timeout=90), "the engine did not start in the profile"
        )
        time.sleep(3)
        self.assertEqual(sections(), [f"Path={path.name}", "[Profile0]"], "a profile was made outside the group")
        self.assertEqual(sorted(entry.name for entry in path.parent.iterdir()), folders, "a new profile folder was made")
        self.assertFalse(gone.exists(), "the deleted profile's folder was made again")

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

        display, keyboard = self.private_display()
        headful = {k: v for k, v in plain.items() if k != "MOZ_HEADLESS"} | {"DISPLAY": display, "GDK_BACKEND": "x11"}
        self.plain_start(headful)
        self.assertTrue(harness.wait_until(lambda: keyboard.windows() > 0, timeout=60), "no window at the plain start")
        # No engine can be asked when the chooser's cards are drawn, so the display is: a page, no longer changing.
        cards = keyboard.drawn()
        self.assertIsNotNone(cards, "the chooser's window stayed bare")
        self.assertIsNone(protected.running_pid())
        self.assertFalse(storage.Container(path).mounted(), "unlocked before anything was typed")
        keyboard.key("Tab")  # the first card: the locked profile
        focused = keyboard.drawn(after=cards)
        self.assertIsNotNone(focused, "Tab did not put the keyboard on the card")
        keyboard.key("Return")
        # The unlock step is on the display, its password field focused (a blinking cursor: two pictures close together).
        self.assertIsNotNone(keyboard.drawn(after=focused, apart=0.2, times=2), "the unlock step did not open")
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
