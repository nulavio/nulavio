"""Protected profiles in the browser UI (S6): create in three decisions, then every state of the
locked-profile page. Nulavio build only; needs gocryptfs, FUSE and libsodium.

The pages talk to the Nulavio tools installed next to the engine (nulavio-tools/), which do
the cryptography in a separate process. The system keyring is a stand-in `secret-tool`
(NULAVIO_SECRET_TOOL) inside the throwaway home; passwords are artificial. Screenshots of
each state go to tests/artifacts/ (light and dark) for design review.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from fake_avahi import FAKE_BUSCTL
from phone_link_ref import LinkedPhone
from phone_reference import ReferencePhone

from nulavio_launcher.vault import sodium, storage

PASSWORD = "artificial pass 11"
READY = sodium.available() and storage.tools_available()
SHELL = "resource://builtin-addons/nulavio-shell/modules"
PRELUDE = (
    f'const V = ChromeUtils.importESModule("{SHELL}/NulavioVault.sys.mjs").NulavioVault;'
    f'const P = ChromeUtils.importESModule("{SHELL}/NulavioProfiles.sys.mjs").NulavioProfiles;'
    'const SPS = ChromeUtils.importESModule("resource:///modules/profiles/SelectableProfileService.sys.mjs")'
    ".SelectableProfileService;"
)
FAKE_SECRET_TOOL = """#!/usr/bin/python3 -I
import json, os, sys
store = os.environ["NV_FAKE_KEYRING"]
items = json.load(open(store)) if os.path.exists(store) else []
cmd, rest = sys.argv[1], sys.argv[2:]
if cmd == "store":
    rest = rest[1:]
attrs = dict(zip(rest[::2], rest[1::2]))
if cmd == "store":
    items = [i for i in items if i["attrs"] != attrs] + [{"attrs": attrs, "secret": sys.stdin.read()}]
elif cmd == "lookup":
    match = [i for i in items if i["attrs"] == attrs]
    if not match:
        sys.exit(1)
    sys.stdout.write(match[0]["secret"])
elif cmd == "clear":
    items = [i for i in items if i["attrs"] != attrs]
open(store, "w").write(json.dumps(items))
"""


@unittest.skipUnless(READY and harness.nulavio_engine(), "needs the Nulavio build, gocryptfs, FUSE and libsodium")
class VaultUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        tool = cls.session.tmp / "secret-tool"
        tool.write_text(FAKE_SECRET_TOOL)
        tool.chmod(0o700)
        cls.keyring_store = cls.session.tmp / "keyring.json"
        cls.session.env["NULAVIO_SECRET_TOOL"] = str(tool)
        cls.session.env["NV_FAKE_KEYRING"] = str(cls.keyring_store)
        # The phone is found through a stand-in for Avahi: nothing is announced on the real network.
        busctl = cls.session.tmp / "busctl"
        busctl.write_text(FAKE_BUSCTL.format(python=sys.executable))
        busctl.chmod(0o700)
        cls.avahi = cls.session.tmp / "avahi.json"
        cls.session.env["NULAVIO_BUSCTL"] = str(busctl)
        cls.session.env["NV_FAKE_AVAHI"] = str(cls.avahi)
        cls.m = cls.session.start()
        # Connecting a phone is offered by default (D10 revised 2026-11-10); test 13 turns it off.
        cls.m.chrome('Services.prefs.setBoolPref("nulavio.vault.phone.pairing", true);')
        cls.base = cls.m.chrome('return WebExtensionPolicy.getByID("shell@nulavio.net").getURL("");')
        cls.shots = harness.artifacts_dir() / "vault-ui"
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
        finally:
            cls.server.__exit__(None, None, None)

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

    def open_page(self, page: str) -> None:
        # A new tab, as the browser opens these pages (the unlock page closes its tab after success).
        self.m.switch_to(self.m.window_handles()[0])
        handle = self.m.send("WebDriver:NewWindow", {"type": "tab"})["handle"]
        self.m.switch_to(handle)
        self.m.navigate(self.base + page)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), timeout=30)
        )

    def state(self, attribute: str = "state") -> str:
        return self.m.execute(f"return document.body.dataset.{attribute};")

    def wait_state(self, expected: str, attribute: str = "state", timeout: float = 60) -> None:
        ok = harness.wait_until(lambda: self.state(attribute) == expected, timeout=timeout)
        if not ok:
            errors = self.m.execute(
                "return ['protection-error','recovery-error'].map(id=>document.getElementById(id)?.textContent ?? '');"
            )
            self.fail(
                f"{attribute} is {self.state(attribute)!r}, expected {expected!r}; "
                f"status: {self.status_text()}; inline errors: {errors}"
            )

    def status_text(self) -> str:
        return self.m.execute("return document.getElementById('status')?.textContent ?? '';")

    def status_line(self) -> dict:
        """The status line as drawn: its level, the mark before the words, and whether errors use the critical colour."""
        return self.m.execute(
            "const s = document.getElementById('status'); const before = getComputedStyle(s, '::before');"
            "const probe = v => { const e = document.createElement('i'); e.style.color = v; document.body.append(e);"
            " const out = getComputedStyle(e).color; e.remove(); return out; };"
            "return {level: s.dataset.level, text: s.textContent, mark: before.content, mask: before.maskImage,"
            " color: getComputedStyle(s).color, critical: probe('var(--nv-color-status-criticalText)'),"
            " warning: probe('var(--nv-color-status-warning)'), state: document.body.dataset.state};"
        )

    def assert_status(self, level: str) -> dict:
        line = self.status_line()
        self.assertEqual(line["level"], level, line)
        # Marks are SVG masks now (Calmaria): the check only for a result that happened.
        self.assertEqual("icon-check.svg" in line["mask"], level == "ok", f"✓ only for a result that happened: {line}")
        if level == "error":
            self.assertEqual(line["color"], line["critical"], "errors use the critical style")
            self.assertIn("icon-critical.svg", line["mask"], "errors carry the critical icon")
        if level == "warn":
            self.assertEqual(line["color"], line["warning"])
            self.assertIn("icon-warning.svg", line["mask"], "a warning carries the warning icon")
        return line

    def type_into(self, element_id: str, text: str) -> None:
        self.m.execute(
            "const el = document.getElementById(arguments[0]); el.focus(); el.value = arguments[1];"
            "el.dispatchEvent(new Event('input', {bubbles: true}));",
            [element_id, text],
        )

    def click(self, selector: str) -> None:
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(selector)})

    def shoot(self, name: str, element: str | None = None) -> None:
        """Light and dark captures through the tokens' own data-theme switch (as the design screenshots)."""
        for scheme in ("light", "dark"):
            # Re-render the whole page in that scheme (headless captures can reuse stale pixels otherwise).
            self.m.execute(
                "document.documentElement.dataset.theme = arguments[0]; document.body.style.display = 'none';"
                "document.body.offsetHeight; document.body.style.display = ''; return document.body.offsetHeight;",
                [scheme],
            )
            time.sleep(0.3)
            if element:  # only the section that holds it (long pages)
                self.m.execute(
                    "const keep = document.querySelector(arguments[0]).closest('section');"
                    "for (const s of document.querySelectorAll('section.section')) { s.hidden = s !== keep; }",
                    [element],
                )
                time.sleep(0.2)
            (self.shots / f"{name}-{scheme}.png").write_bytes(self.m.screenshot_png(full=True))
        self.m.execute("delete document.documentElement.dataset.theme;")

    def password_prompt(self, wait: float = 3) -> bool:
        """Whether the engine's password manager offers to save a login, in any tab (these pages open in the background)."""
        script = (
            "for (const w of Services.wm.getEnumerator('navigator:browser')) {"
            " if (w.gBrowser.browsers.some(b => w.PopupNotifications.getNotification('password', b))) { return true; } }"
            "return false;"
        )
        return harness.wait_until(lambda: self.m.chrome(script), timeout=wait, interval=0.25)

    def profile_path(self, profile_id: int) -> Path:
        return Path(self.call("return (await SPS.getProfile(args[0])).path;", profile_id))

    def create_via_api(self, name: str, *, password: str | None, keyring: bool) -> tuple[int, str]:
        details = {"name": name, "templateId": "banking", "keyring": keyring}
        if password:
            details["password"] = password
        created = self.call("return V.createProtected(args[0]);", details)
        return created["id"], created["recoveryCode"]

    def instances(self, path: Path) -> list[int]:
        """Engine instances of a profile (not the Vault's watcher, which also names the path)."""
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

    # -- tests ---------------------------------------------------------------------

    def test_01_create_a_protected_profile_in_three_decisions(self):
        self.open_page("vault/create.html")
        self.wait_state("profile", "step")
        # "Tentar de novo" belongs to a failed state the page lists, never to a page that just opened.
        self.assertIsNone(self.m.execute("return document.querySelector('.moment__retry');"))
        # The pressed template looks pressed (DS-05): another surface and edge, and a ✓, not only aria-pressed.
        templates = self.m.execute(
            "return [...document.querySelectorAll('#templates button')].map(b => ({pressed: b.getAttribute('aria-pressed'),"
            " bg: getComputedStyle(b).backgroundColor, border: getComputedStyle(b).borderTopColor,"
            " mark: getComputedStyle(b, '::before').content, mask: getComputedStyle(b, '::before').maskImage}));"
        )
        pressed = [b for b in templates if b["pressed"] == "true"]
        others = [b for b in templates if b["pressed"] == "false"]
        self.assertEqual(len(pressed), 1, templates)
        self.assertTrue(others)
        for other in others:
            self.assertNotEqual((pressed[0]["bg"], pressed[0]["border"]), (other["bg"], other["border"]))
            self.assertEqual(other["mark"], "none")
        self.assertEqual(pressed[0]["mark"], '""')  # a check drawn by an SVG mask, not a font glyph
        self.assertIn("icon-check.svg", pressed[0]["mask"])
        # Native radios and checkboxes take the brand accent, not the toolkit's blue (DS-11).
        accent = self.m.execute(
            "const probe = document.createElement('i'); probe.style.color = 'var(--nv-color-accent-default)';"
            "document.body.append(probe); const want = getComputedStyle(probe).color; probe.remove();"
            "return [getComputedStyle(document.querySelector('input[name=method]')).accentColor, want];"
        )
        self.assertEqual(accent[0], accent[1])
        self.shoot("create-1-profile")
        self.type_into("name", "Cofre UI")
        self.click("#step-profile button[type=submit]")
        self.wait_state("protection", "step")
        self.assertEqual(self.m.execute("return document.activeElement.type;"), "radio")
        # The password protects the files while the profile is locked, not while it is open (SB-14).
        hint = self.m.execute("return document.querySelector('[data-i18n=vaultChoosePasswordHint]').textContent;")
        self.assertIn("bloqueado", hint)
        self.assertIn("aberto", hint)
        self.type_into("password", PASSWORD)
        self.type_into("password2", PASSWORD + "x")
        self.click("#step-protection button[type=submit]")
        self.assertTrue(self.m.execute("return document.getElementById('protection-error').textContent.length > 0;"))
        self.type_into("password2", PASSWORD)
        self.shoot("create-2-protection")
        self.click("#step-protection button[type=submit]")
        self.wait_state("recovery", "step", timeout=90)
        code = self.m.execute("return document.getElementById('code').dataset.code;")
        # UX4 (SB-08): 7 numbered groups, and the heading (not a field below the code) has the keyboard.
        self.assertEqual(self.m.execute("return document.querySelectorAll('#code > li').length;"), 7)
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "headline")
        self.assertRegex(code, r"^([0-9A-HJKMNP-TV-Z]{4}-){6}[0-9A-HJKMNP-TV-Z]{4}$")
        self.shoot("create-3-recovery")
        groups = code.split("-")
        index = lambda label: int(self.m.execute(f"return document.getElementById('{label}').textContent.match(/\\d+/)[0];")) - 1  # noqa: E731
        self.type_into("group-a", "ZZZZ")
        self.type_into("group-b", groups[index("group-b-label")])
        self.click("#step-recovery button[type=submit]")
        self.assertEqual(self.state("step"), "recovery")  # a wrong group is caught
        self.type_into("group-a", groups[index("group-a-label")].lower())
        self.click("#step-recovery button[type=submit]")
        self.wait_state("done", "step")
        self.assertEqual(self.m.execute("return document.getElementById('code').textContent;"), "")  # no longer on screen
        self.assertIsNone(self.m.execute("return document.getElementById('code').dataset.code ?? null;"))
        self.shoot("create-4-done")
        profile = next(p for p in self.call("return (await P.list()).profiles;") if p["name"] == "Cofre UI")
        self.assertEqual((profile["encrypted"], profile["locked"]), (True, True))
        path = self.profile_path(profile["id"])
        self.assertEqual(list(path.iterdir()), [])
        self.assertTrue((path.parent / f"{path.name}.vault" / "vault.json").exists())
        type(self).created_id = profile["id"]

    def test_02_unlock_page_wrong_then_right_password_opens_the_profile_and_relocks(self):
        profile_id = self.created_id
        path = self.profile_path(profile_id)
        url = self.server.url("/page/vault-opened")
        self.open_page(f"vault/unlock.html?p={profile_id}&u={url}")
        self.wait_state("idle")
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "password")  # keyboard first
        self.assertEqual(self.m.execute("return document.getElementById('url').textContent;"), url)
        self.shoot("unlock-idle")
        # Typed with real keys: the engine's password manager only captures what a person typed.
        self.m.send("WebDriver:ElementSendKeys", {"id": self.m.find_element("#password"), "text": "not the password"})
        self.click("#password-form button[type=submit]")
        self.wait_state("error")
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "password")
        self.assert_status("error")  # critical colour and icon, no ✓ and no amber (SB-12)
        # The refused field is marked and the message is its description; neither outlives the attempt.
        marked = (
            "const f = document.getElementById(arguments[0]);"
            "return [f.getAttribute('aria-invalid'), f.getAttribute('aria-describedby')];"
        )
        self.assertEqual(self.m.execute(marked, ["password"]), ["true", "status"])
        self.shoot("unlock-error")
        # The profile's password is never offered to this profile's password manager, which may be unprotected.
        origin = self.base.rstrip("/")
        self.assertFalse(self.m.chrome("return Services.logins.getLoginSavingEnabled(arguments[0]);", [origin]))
        self.assertFalse(self.password_prompt(), "the engine offered to save the profile's password")
        self.click("#use-recovery")
        self.assertEqual((self.state(), self.status_text()), ("idle", ""), "the password's error stayed over the other form")
        self.assertIsNone(self.m.execute(marked, ["password"])[0])
        self.type_into("recovery", "1234")
        self.click("#recovery-form button[type=submit]")
        self.wait_state("error")
        self.assertEqual(self.m.execute(marked, ["recovery"]), ["true", "status"])
        self.click("#recovery-back")
        self.assertEqual((self.state(), self.m.execute(marked, ["recovery"])[0]), ("idle", None))
        self.assertEqual(self.server.requests_to("/page/vault-opened"), [])  # nothing loaded while locked
        self.type_into("password", PASSWORD)
        self.click("#password-form button[type=submit]")
        # Progress is not a result: no ✓ while unlocking; then the result says when it locks again (SB-12, SB-14).
        seen: dict[str, dict] = {}

        def watch():
            line = self.status_line()
            seen.setdefault(line["state"], line)
            return line["state"] == "unlocked"

        self.assertTrue(harness.wait_until(watch, timeout=60, interval=0.1), f"never showed unlocked: {seen}")
        if "unlocking" in seen:  # usually caught; the unlock can be faster than one poll
            self.assertEqual((seen["unlocking"]["level"], "icon-check.svg" in seen["unlocking"]["mask"]), ("progress", False))
        self.assertEqual(seen["unlocked"]["level"], "ok")
        self.assertIn("última janela", seen["unlocked"]["text"])
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=60), "the profile did not start")
        self.assertTrue(harness.wait_until(lambda: self.server.requests_to("/page/vault-opened"), timeout=60))
        # While it is open, Settings says when it locks again, next to "Lock now" (SB-14).
        self.m.switch_to(self.m.window_handles()[0])
        self.m.navigate(self.base + "settings/settings.html#profiles")
        note = harness.wait_until(
            lambda: self.m.execute(
                "return document.querySelector(`[data-profile-id='${arguments[0]}'] [data-relock]`)?.textContent ?? null;",
                [profile_id],
            ),
            timeout=20,
        )
        self.assertIn("última janela", note or "")
        self.stop_instance(path)
        box = storage.Container(path)
        self.assertTrue(harness.wait_until(lambda: not box.mounted(), timeout=30), "not locked after the window closed")
        self.assertEqual(list(path.iterdir()), [])

    def test_03_computer_login_unavailable_offers_the_password(self):
        profile_id, _ = self.create_via_api("Login", password=PASSWORD, keyring=True)
        self.keyring_store.write_text("[]")  # e.g. the keyring was reset
        self.open_page(f"vault/unlock.html?p={profile_id}")
        self.wait_state("idle")
        self.click("#use-keyring")
        self.wait_state("device-unavailable")
        self.assert_status("error")
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "password")
        # The pointer is still on the button: hover feedback is visible (state tokens are opacities).
        self.assertNotEqual(self.m.execute("return getComputedStyle(document.getElementById('use-keyring')).boxShadow;"), "none")
        self.shoot("unlock-device-unavailable")

    def test_04_only_the_recovery_code_left(self):
        profile_id, code = self.create_via_api("SoLogin", password=None, keyring=True)
        self.keyring_store.write_text("[]")
        url = self.server.url("/page/recovery-opened")
        self.open_page(f"vault/unlock.html?p={profile_id}&u={url}")
        self.wait_state("idle")  # computer login is still offered first
        self.click("#use-keyring")
        self.wait_state("device-unavailable")
        self.click("#use-recovery")
        self.type_into("recovery", code.lower().replace("-", " "))
        self.click("#recovery-form button[type=submit]")
        self.wait_state("unlocked", timeout=60)
        path = self.profile_path(profile_id)
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=60))
        # Stop it once it is really up, as tests 02 and 09 do. The watcher polls for the engine that took
        # the profile: one ended in its first half second is never seen, and the watcher then waits out
        # its two-minute grace period before locking (this test failed that way about one run in four).
        self.assertTrue(harness.wait_until(lambda: self.server.requests_to("/page/recovery-opened"), timeout=60))
        self.stop_instance(path)
        self.assertTrue(harness.wait_until(lambda: not storage.Container(path).mounted(), timeout=30))

    def test_05_recovery_required_and_not_locked_states(self):
        # A profile whose only everyday method is gone shows the recovery form directly.
        profile_id, _ = self.create_via_api("Recovery", password="temporary pass 1", keyring=False)
        path = self.profile_path(profile_id)
        vault_file = path.parent / f"{path.name}.vault" / "vault.json"
        from nulavio_launcher.vault.core import Vault

        vault = Vault.load(vault_file)
        vault.unlock_password("temporary pass 1")
        vault.remove(next(e.id for e in vault.envelopes("password")))
        vault.save()
        vault.lock()
        self.open_page(f"vault/unlock.html?p={profile_id}")
        self.wait_state("recovery-required")
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "recovery")
        line = self.assert_status("warn")  # a degraded state with its reason and next step, never a ✓ (SB-12)
        self.assertIn("código de recuperação", line["text"])
        self.shoot("unlock-recovery-required")
        # The current profile is not locked: the page says so instead of asking.
        current = self.call("return (await P.current()).id;")
        self.open_page(f"vault/unlock.html?p={current}")
        self.wait_state("not-locked")

    def test_06_tools_missing(self):
        tools = Path(self.session.engine.path).parent / "nulavio-tools"
        hidden = tools.with_name("nulavio-tools.hidden-by-test")
        os.rename(tools, hidden)
        try:
            self.open_page(f"vault/unlock.html?p={self.created_id}")
            self.wait_state("storage-unavailable")
            # SB-19: the state says what to do next; "Tentar de novo" reads it again.
            retry = self.m.execute("return document.querySelector('.moment__retry button')?.textContent ?? null;")
            self.assertEqual(retry, self.m.execute("return browser.i18n.getMessage('momentRetry');"))
            self.shoot("unlock-storage-unavailable")
        finally:
            os.rename(hidden, tools)

    def test_07_selector_and_settings_lead_to_the_unlock_page(self):
        locked = next(p for p in self.call("return (await P.list()).profiles;") if p["name"] == "Cofre UI")
        self.assertTrue(locked["locked"])
        self.assertEqual(
            self.call("try { await P.switchTo(args[0]); return 'opened'; } catch (e) { return e.code; }", locked["id"]), "locked"
        )
        self.call("await V.openUnlockPage(args[0]);", locked["id"])
        tabs = lambda: self.m.chrome("return gBrowser.browsers.map(b => b.currentURI.spec);")  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: any(f"vault/unlock.html?p={locked['id']}" in u for u in tabs()), timeout=20))
        self.assertEqual(self.instances(self.profile_path(locked["id"])), [])
        self.assertTrue(shutil.which("gocryptfs"))  # sanity: the environment still has the tools
        # Settings: the locked profile offers "Unlock…" instead of "Open".
        self.m.switch_to(self.m.window_handles()[0])
        self.m.navigate(self.base + "settings/settings.html#profiles")
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.execute(
                    "return !!document.querySelector(`[data-focus-key='open-${arguments[0]}']`);", [locked["id"]]
                ),
                timeout=20,
            )
        )
        label = self.m.execute(
            "return document.querySelector(`[data-focus-key='open-${arguments[0]}']`).textContent;", [locked["id"]]
        )
        expected = self.m.execute("return browser.i18n?.getMessage?.('vaultUnlockButton') ?? null;")
        self.assertTrue(label.endswith("…"), label)
        if expected:
            self.assertEqual(label, expected)
        # The accessible name says the state and the action shown, not "Abrir" (SPA-10, SB-17).
        name = self.m.execute(
            "return document.querySelector(`[data-focus-key='open-${arguments[0]}']`).getAttribute('aria-label');", [locked["id"]]
        )
        self.assertEqual(name, "Cofre UI, bloqueado, desbloquear…")
        self.assertIn(label.lower(), name.lower(), "WCAG 2.5.3: the visible label is in the name")
        # The same in the toolbar's profile selector, whose rows are buttons named by aria-label.
        self.m.navigate(self.base + "profiles/popup.html")
        popup = harness.wait_until(
            lambda: self.m.execute(
                "const b = document.querySelector(`.popup__item[data-profile-id='${arguments[0]}']`);"
                "return b ? [b.getAttribute('aria-label'), b.textContent] : null;",
                [locked["id"]],
            ),
            timeout=20,
        )
        self.assertTrue(popup, "locked profile missing from the selector")
        self.assertEqual(popup[0], "Cofre UI, bloqueado, desbloquear…")
        self.assertIn("Bloqueado", popup[1])  # the visible badge, now also in the name
        self.m.navigate(self.base + "settings/settings.html#profiles")
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.execute(
                    "return !!document.querySelector(`[data-focus-key='open-${arguments[0]}']`);", [locked["id"]]
                ),
                timeout=20,
            )
        )
        self.shoot("settings-locked-profile", "#profiles-card")
        # Deleting a locked protected profile drops its keys, then the profile.
        path = self.profile_path(locked["id"])
        self.call("await P.remove(args[0]);", locked["id"])
        self.assertFalse((path.parent / f"{path.name}.vault").exists())
        self.assertFalse(path.exists())

    # -- phone (Nulavio Companion, S11) ---------------------------------------------------------

    def qr_code(self, selector: str) -> str:
        script = f"return document.querySelector('{selector} svg')?.dataset.code ?? null;"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(script), timeout=30), "no code shown")
        return self.m.execute(script)

    def test_08_connect_a_phone_with_the_six_digits(self):
        profile_id, _code = self.create_via_api("Celular", password=PASSWORD, keyring=False)
        type(self).phone_profile = profile_id
        self.open_page(f"vault/phone.html?p={profile_id}")
        self.wait_state("idle")
        # Honest copy (SB-13): one more way to unlock, the others keep working; the button shows a QR, not the
        # recovery code; the "no master key" footer names no method, so it is true for every profile.
        copy = self.m.execute(
            "return {explain: document.getElementById('explain').textContent,"
            " cta: document.querySelector('#start-form button[type=submit]').textContent,"
            " footer: document.querySelector('[data-i18n=vaultNoMasterKey]').textContent};"
        )
        self.assertIn("mais um jeito de desbloquear", copy["explain"])
        self.assertIn("continuam valendo", copy["explain"])
        self.assertEqual(copy["cta"], "Mostrar QR para o celular")
        self.assertIn("um dos jeitos de desbloquear deste perfil", copy["footer"])
        self.shoot("phone-idle")
        self.type_into("current", "not the password")
        self.click("#start-form button[type=submit]")
        self.wait_state("error")
        self.assert_status("error")
        self.type_into("current", PASSWORD)
        self.click("#start-form button[type=submit]")
        self.wait_state("waiting")
        code = self.qr_code("#qr")
        line = self.assert_status("progress")  # waiting is not a result (SB-12)
        self.assertNotEqual(line["text"], self.m.execute("return document.getElementById('pair-hint').textContent;"))
        self.shoot("phone-qr")
        linked = LinkedPhone(ReferencePhone("Pixel de teste"), registry=self.avahi)
        self.addClassCleanup(linked.close)
        linked.pair(code)
        self.wait_state("compare")
        compare = self.m.execute(
            "const d = document.getElementById('digits');"
            "const weight = b => [...b.classList].filter(c => c.startsWith('button--')).join();"
            "return {shown: d.querySelector('[aria-hidden=true]').textContent,"
            " spoken: d.querySelector('.visually-hidden').textContent,"
            " focused: document.activeElement.id,"
            " question: document.getElementById(d.getAttribute('aria-describedby')).textContent,"
            " match: weight(document.getElementById('match')), differ: weight(document.getElementById('differ')),"
            " status: document.getElementById('status').textContent};"
        )
        self.assertEqual(compare["shown"].replace(" ", ""), linked.sas)  # the same 6 digits on both screens
        # Neither answer is the default (SB-07): the focus is on the digits, both answers weigh the same,
        # the digits are read one by one, and nothing else is announced over them.
        self.assertEqual(compare["focused"], "digits")
        self.assertEqual(compare["match"], compare["differ"])
        self.assertNotIn("primary", compare["match"])
        self.assertTrue(compare["spoken"].endswith(" ".join(linked.sas)), compare)
        self.assertIn("6 dígitos", compare["question"])
        self.assertEqual(compare["status"], "")
        self.shoot("phone-compare")
        self.click("#match")
        self.wait_state("paired")
        phones = self.m.execute("return document.getElementById('phones').textContent;")
        self.assertIn("Pixel de teste", phones)
        type(self).linked = linked

    def test_09_unlock_with_the_phone_opens_the_profile(self):
        profile_id = self.phone_profile
        path = self.profile_path(profile_id)
        url = self.server.url("/page/phone-opened")
        self.open_page(f"vault/unlock.html?p={profile_id}&u={url}")
        self.wait_state("idle")
        self.click("#use-phone")
        self.wait_state("waiting")
        code = self.qr_code("#phone-qr")
        line = self.assert_status("progress")
        hint = self.m.execute("return document.getElementById('phone-hint').textContent;")
        self.assertNotEqual(line["text"], hint, "the instruction is shown once, not repeated in the status line")
        self.shoot("unlock-phone")
        self.assertEqual(self.server.requests_to("/page/phone-opened"), [])
        self.linked.unlock(code)
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=60), "the profile did not start")
        self.assertTrue(harness.wait_until(lambda: self.server.requests_to("/page/phone-opened"), timeout=60))
        self.stop_instance(path)
        box = storage.Container(path)
        self.assertTrue(harness.wait_until(lambda: not box.mounted(), timeout=30), "not locked after the window closed")

    def test_10_unlock_methods_page(self):
        """UX4 (audit SB-09, SB-16): every method by kind; each change confirmed with a current secret."""
        profile_id, code = self.create_via_api("Metodos", password=PASSWORD, keyring=False)
        self.open_page(f"vault/methods.html?p={profile_id}")
        self.wait_state("idle")
        rows = self.m.execute("return [...document.querySelectorAll('#methods > li')].map(li => li.dataset.method);")
        self.assertEqual(sorted(rows), ["password", "recovery-code"])
        self.assertTrue(self.m.execute("return document.getElementById('few').hidden;"))  # two methods: no warning
        self.shoot("methods-idle")
        # A change without the current secret is refused next to the field, and nothing changes.
        self.click("#add-password")
        self.type_into("new-password", "second pass 22")
        self.type_into("new-password2", "second pass 22")
        self.click("#password-form button[type=submit]")
        self.assertTrue(self.m.execute("return document.getElementById('current-error').textContent.length > 0;"))
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "current")
        # With the wrong secret: refused, the field is cleared and marked.
        self.type_into("new-password", "second pass 22")
        self.type_into("new-password2", "second pass 22")
        self.type_into("current", "not the password")
        self.click("#password-form button[type=submit]")
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.execute("return document.getElementById('current').getAttribute('aria-invalid');") == "true", 30
            )
        )
        self.assertEqual(self.m.execute("return document.getElementById('current').value;"), "")
        # With the password: a second password is added.
        self.type_into("new-password", "second pass 22")
        self.type_into("new-password2", "second pass 22")
        self.type_into("current", PASSWORD)
        self.click("#password-form button[type=submit]")
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.execute("return document.querySelectorAll('#methods > li[data-method=password]').length;") == 2, 30
            )
        )
        # A new recovery code: confirmed, shown once as 7 groups, two typed back; the old one stops working.
        self.type_into("current", "second pass 22")
        self.click("#new-code")
        self.click("dialog[open] button[value=confirm]")
        self.wait_state("code")
        new_code = self.m.execute("return document.getElementById('code').dataset.code;")
        self.assertNotEqual(new_code, code)
        self.assertEqual(self.m.execute("return document.querySelectorAll('#code > li').length;"), 7)
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "code-heading")
        self.shoot("methods-new-code")
        groups = new_code.split("-")
        index = lambda label: int(self.m.execute(f"return document.getElementById('{label}').textContent.match(/\\d+/)[0];")) - 1  # noqa: E731
        self.type_into("group-a", groups[index("group-a-label")])
        self.type_into("group-b", groups[index("group-b-label")])
        self.click("#code-step button[type=submit]")
        self.wait_state("idle")
        self.assertEqual(self.m.execute("return document.getElementById('code').textContent;"), "")
        # Removing a method asks first; the old code no longer confirms anything.
        self.type_into("current", code)
        first = self.m.execute("return document.querySelector('#methods > li[data-method=password]').dataset.envelope;")
        self.click(f"#methods > li[data-envelope='{first}'] button")
        self.click("dialog[open] button[value=confirm]")
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.execute("return document.getElementById('current-error').textContent.length > 0;"), 30
            )
        )
        self.assertEqual(self.m.execute("return document.querySelectorAll('#methods > li[data-method=password]').length;"), 2)
        self.type_into("current", new_code)
        self.click(f"#methods > li[data-envelope='{first}'] button")
        self.click("dialog[open] button[value=confirm]")
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.execute("return document.querySelectorAll('#methods > li[data-method=password]').length;") == 1, 30
            )
        )
        # Down to one method: the page says what that means, and the last one cannot be removed.
        self.type_into("current", new_code)
        self.click("#methods > li[data-method=password] button")
        self.click("dialog[open] button[value=confirm]")
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.querySelectorAll('#methods > li').length;") == 1, 30)
        )
        last = self.m.execute(
            "const b = document.querySelector('#methods > li button');"
            "return {disabled: b.disabled, why: document.querySelector('#methods [id^=keep-]')?.textContent ?? null,"
            " few: !document.getElementById('few').hidden, kind: document.querySelector('#methods > li').dataset.method};"
        )
        self.assertEqual((last["disabled"], last["few"], last["kind"]), (True, True, "recovery-code"))
        self.assertTrue(last["why"])
        self.shoot("methods-last")

    def test_11_lock_now_for_the_profile_in_this_window(self):
        """UX4: "Bloquear agora" for this window's protected profile asks first and only then calls the Vault.
        The Vault call quits the browser, so here it is replaced by a recorder (the tools part is a unit test)."""
        self.call(
            "const real = await P.list(); const me = real.profiles.find(p => p.isCurrent);"
            "P.nvRealList = P.list; P.nvLockCalls = 0;"
            "const shown = real.profiles.map(p => (p.isCurrent ? {...p, encrypted: true, locked: false} : p));"
            "P.list = async () => ({...real, profiles: shown});"
            "V.lockCurrent = async () => { P.nvLockCalls++; return {quit: false}; };"
            "return me.name;"
        )
        try:
            self.open_page("profiles/popup.html")
            name = self.call("return (await P.nvRealList.call(P)).profiles.find(p => p.isCurrent).name;")
            self.assertEqual(
                self.m.execute("return document.getElementById('lock-current')?.textContent;"),
                self.m.execute("return browser.i18n.getMessage('vaultLockCurrent', [arguments[0]]);", [name]),
            )
            self.click("#lock-current")
            dialog = self.m.execute(
                "const d = document.querySelector('dialog[open]');"
                "return d && {focused: document.activeElement.value, primary: d.querySelector('.button--primary').value};"
            )
            self.assertEqual(dialog, {"focused": "cancel", "primary": "cancel"})  # closing windows: Cancel first
            self.click("dialog[open] button[value=cancel]")
            time.sleep(0.5)
            self.assertEqual(self.call("return P.nvLockCalls;"), 0)
            self.click("#lock-current")
            self.click("dialog[open] button[value=confirm]")
            self.assertTrue(harness.wait_until(lambda: self.call("return P.nvLockCalls;") == 1, 10))
            self.assertTrue(
                harness.wait_until(
                    lambda: self.status_text() == self.m.execute("return browser.i18n.getMessage('vaultLockCurrentKept');"), 10
                )
            )
        finally:
            self.call("delete P.list; delete P.nvRealList; delete P.nvLockCalls; delete V.lockCurrent;")

    def test_12_the_last_password_or_recovery_code_stays(self):
        """Review F1: changes are confirmed with a password or the recovery code; with the computer login and
        the code, the code cannot be removed (nothing could confirm a change after it)."""
        profile_id, _ = self.create_via_api("SoChave", password=None, keyring=True)
        self.open_page(f"vault/methods.html?p={profile_id}")
        self.wait_state("idle")
        rows = self.m.execute(
            "return Object.fromEntries([...document.querySelectorAll('#methods > li')].map(li => [li.dataset.method,"
            " {disabled: li.querySelector('button').disabled, note: li.querySelector('[id^=keep-]')?.textContent ?? null,"
            " label: [...li.querySelectorAll('.row__note')].map(n => n.textContent)}]));"
        )
        self.assertEqual(sorted(rows), ["os-keyring", "recovery-code"])
        self.assertTrue(rows["recovery-code"]["disabled"])
        self.assertEqual(rows["recovery-code"]["note"], self.m.execute("return browser.i18n.getMessage('methodsLastConfirmer');"))
        self.assertFalse(rows["os-keyring"]["disabled"])
        self.assertEqual(rows["os-keyring"]["label"], [])  # the tools' own "computer login" label is not shown
        self.shoot("methods-keyring")

    def test_13_connecting_a_phone_is_not_offered_yet(self):
        """With the pref off (the build offers it since D10 was revised) no page offers to connect a phone
        and the Shell refuses to start one; a phone connected before keeps working."""
        pref = "nulavio.vault.phone.pairing"
        self.m.chrome("Services.prefs.clearUserPref(arguments[0]);", [pref])
        try:
            self.assertTrue(self.m.chrome("return Services.prefs.getBoolPref(arguments[0], false);", [pref]), "the build default")
            self.m.chrome("Services.prefs.setBoolPref(arguments[0], false);", [pref])
            profile_id, _ = self.create_via_api("SemCelular", password=PASSWORD, keyring=False)
            # The unlock-methods page: no link to the phones, and it says what is not available yet.
            self.open_page(f"vault/methods.html?p={profile_id}")
            self.wait_state("idle")
            page = self.m.execute(
                "return {link: document.getElementById('phones').getClientRects().length,"
                " note: document.getElementById('not-yet').textContent};"
            )
            self.assertEqual(page["link"], 0, "the link to connect a phone is shown")
            for words in ("celular", "chave de segurança", "ainda não disponíveis"):
                self.assertIn(words, page["note"])
            self.shoot("methods-not-yet")
            # The phone page, opened by its address: it says so, offers no code and nothing to try again.
            self.open_page(f"vault/phone.html?p={profile_id}")
            self.wait_state("not-yet")
            page = self.m.execute(
                "return {explain: document.getElementById('explain').textContent,"
                " form: document.getElementById('start-form').getClientRects().length,"
                " retry: document.querySelector('.moment__retry') !== null};"
            )
            not_yet = self.m.execute("return browser.i18n.getMessage('phoneNotYet');")
            self.assertEqual(page, {"explain": not_yet, "form": 0, "retry": False})
            self.shoot("phone-not-yet")
            # A page or anything else that calls the Shell directly is refused the same way.
            with self.assertRaises(AssertionError) as refused:
                self.call("return V.phoneStart(args[0], 'pair', {current: args[1]});", profile_id, PASSWORD)
            self.assertEqual(str(refused.exception), "phone-not-yet")
            # The phone connected in test 08 is still listed and can be removed, but no new one is offered.
            self.open_page(f"vault/methods.html?p={self.phone_profile}")
            self.wait_state("idle")
            self.assertGreater(self.m.execute("return document.getElementById('phones').getClientRects().length;"), 0)
            self.open_page(f"vault/phone.html?p={self.phone_profile}")
            self.wait_state("idle")
            page = self.m.execute(
                "const form = document.getElementById('start-form');"
                "return {phones: document.getElementById('phones').textContent,"
                " remove: document.querySelectorAll('#phones button').length,"
                " field: document.getElementById('current').getClientRects().length > 0,"
                " connect: form.querySelector('button[type=submit]').getClientRects().length};"
            )
            self.assertIn("Pixel de teste", page["phones"])
            self.assertEqual((page["remove"], page["field"], page["connect"]), (1, True, 0))
            # ... and it still unlocks that profile.
            self.open_page(f"vault/unlock.html?p={self.phone_profile}")
            self.wait_state("idle")
            self.assertIsNotNone(self.m.execute("return document.getElementById('use-phone');"))
        finally:
            self.m.chrome("Services.prefs.setBoolPref(arguments[0], true);", [pref])


if __name__ == "__main__":
    unittest.main()
