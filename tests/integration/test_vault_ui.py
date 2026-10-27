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
        self.assertTrue(ok, f"{attribute} is {self.state(attribute)!r}, expected {expected!r}; status: {self.status_text()}")

    def status_text(self) -> str:
        return self.m.execute("return document.getElementById('status')?.textContent ?? '';")

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
        self.shoot("create-1-profile")
        self.type_into("name", "Cofre UI")
        self.click("#step-profile button[type=submit]")
        self.wait_state("protection", "step")
        self.assertEqual(self.m.execute("return document.activeElement.type;"), "radio")
        self.type_into("password", PASSWORD)
        self.type_into("password2", PASSWORD + "x")
        self.click("#step-protection button[type=submit]")
        self.assertTrue(self.m.execute("return document.getElementById('protection-error').textContent.length > 0;"))
        self.type_into("password2", PASSWORD)
        self.shoot("create-2-protection")
        self.click("#step-protection button[type=submit]")
        self.wait_state("recovery", "step", timeout=90)
        code = self.m.execute("return document.getElementById('code').textContent;")
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
        self.type_into("password", "not the password")
        self.click("#password-form button[type=submit]")
        self.wait_state("error")
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "password")
        self.shoot("unlock-error")
        self.click("#use-recovery")
        self.type_into("recovery", "1234")
        self.click("#recovery-form button[type=submit]")
        self.wait_state("error")
        self.click("#recovery-back")
        self.assertEqual(self.server.requests_to("/page/vault-opened"), [])  # nothing loaded while locked
        self.type_into("password", PASSWORD)
        self.click("#password-form button[type=submit]")
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=60), "the profile did not start")
        self.assertTrue(harness.wait_until(lambda: self.server.requests_to("/page/vault-opened"), timeout=60))
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
        self.assertEqual(self.m.execute("return document.activeElement.id;"), "password")
        # The pointer is still on the button: hover feedback is visible (state tokens are opacities).
        self.assertNotEqual(self.m.execute("return getComputedStyle(document.getElementById('use-keyring')).boxShadow;"), "none")
        self.shoot("unlock-device-unavailable")

    def test_04_only_the_recovery_code_left(self):
        profile_id, code = self.create_via_api("SoLogin", password=None, keyring=True)
        self.keyring_store.write_text("[]")
        self.open_page(f"vault/unlock.html?p={profile_id}")
        self.wait_state("idle")  # computer login is still offered first
        self.click("#use-keyring")
        self.wait_state("device-unavailable")
        self.click("#use-recovery")
        self.type_into("recovery", code.lower().replace("-", " "))
        self.click("#recovery-form button[type=submit]")
        self.wait_state("unlocked", timeout=60)
        path = self.profile_path(profile_id)
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=60))
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
        self.shoot("phone-idle")
        self.type_into("current", "not the password")
        self.click("#start-form button[type=submit]")
        self.wait_state("error")
        self.type_into("current", PASSWORD)
        self.click("#start-form button[type=submit]")
        self.wait_state("waiting")
        code = self.qr_code("#qr")
        self.shoot("phone-qr")
        linked = LinkedPhone(ReferencePhone("Pixel de teste"), registry=self.avahi)
        self.addClassCleanup(linked.close)
        linked.pair(code)
        self.wait_state("compare")
        digits = self.m.execute("return document.getElementById('digits').textContent;")
        self.assertEqual(digits.replace(" ", ""), linked.sas)  # the same 6 digits on both screens
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
        self.shoot("unlock-phone")
        self.assertEqual(self.server.requests_to("/page/phone-opened"), [])
        self.linked.unlock(code)
        self.assertTrue(harness.wait_until(lambda: self.instances(path), timeout=60), "the profile did not start")
        self.assertTrue(harness.wait_until(lambda: self.server.requests_to("/page/phone-opened"), timeout=60))
        self.stop_instance(path)
        box = storage.Container(path)
        self.assertTrue(harness.wait_until(lambda: not box.mounted(), timeout=30), "not locked after the window closed")


if __name__ == "__main__":
    unittest.main()
