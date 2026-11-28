"""Smoke tests: official password-manager extensions in a Nulavio profile.

What this proves: the pinned, hash-verified official XPI installs as a normal
(non-temporary) extension, the engine accepts its Mozilla signature, the
background starts, and the toolbar popup renders.

What this does NOT prove (manual, needs real accounts; see
docs/research/compatibility-matrix.md): login, unlock, autofill, autosave,
alias creation, passkeys, persistence after restart with a signed-in vault.
No credentials are ever used by automated tests.

Requires network (addons.mozilla.org) unless NULAVIO_TEST_XPI_CACHE holds the
pinned files. Enable with NULAVIO_NETWORK_TESTS=1.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from marionette import MarionetteError

from nulavio_launcher import extensions

BODY_COUNT = "return document.querySelectorAll('body *').length;"
POPUP_INFO = """
const {ExtensionParent} = ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs");
const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
const id = __args[0];
const addon = await AddonManager.getAddonByID(id);
const ext = ExtensionParent.GlobalManager.getExtension(id);
if (!addon || !ext) return {error: "not loaded"};
const m = ext.manifest;
const action = m.action || m.browser_action || {};
return {
  active: addon.isActive,
  signedState: addon.signedState,
  version: addon.version,
  manifestVersion: m.manifest_version,
  popup: action.default_popup ? ext.baseURI.resolve(action.default_popup) : null,
  base: ext.baseURI.spec,
  permissions: [...ext.permissions].sort(),
  backgroundState: String(ext.backgroundState ?? "n/a"),
};
"""

PROVIDERS = ("proton-pass", "keepassxc-browser", "bitwarden", "1password")
# Extensions that declare no popup in their manifest and set it when they run: the page they set, read from the
# pinned package (1Password 8.12.46.29: `browser_action` with no `default_popup`, its page `popup/index.html`).
RUNTIME_POPUP = {"1password": "popup/index.html"}


@unittest.skipUnless(harness.engine_available(), "no supported Gecko engine installed")
@unittest.skipUnless(
    os.environ.get("NULAVIO_NETWORK_TESTS") == "1", "set NULAVIO_NETWORK_TESTS=1 (downloads from addons.mozilla.org)"
)
class PasswordExtensionSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.Session(profile="pwtest")
        cls.m = cls.session.start()
        cls.artifacts = harness.artifacts_dir()
        cls.lock = extensions.load_lock()
        cls.evidence: dict[str, dict] = {}

    @classmethod
    def tearDownClass(cls):
        try:
            (cls.artifacts / "password-extensions.json").write_text(json.dumps(cls.evidence, indent=2, ensure_ascii=False))
        finally:
            cls.session.cleanup()

    def popup_info(self, ext_id: str) -> dict:
        self.m.set_context("chrome")
        try:
            script = (
                "const __args = arguments; const resolve = arguments[arguments.length - 1];"
                "(async () => {" + POPUP_INFO + "})().then(resolve, e => resolve({error: String(e)}));"
            )
            return self.m.execute_async(script, [ext_id])
        finally:
            self.m.set_context("content")

    def read_popup(self, popup: str) -> tuple[str, str, int, bytes]:
        """The popup page in a tab of its own: its text, title, element count and a capture, once its framework has
        drawn something. An extension can close or replace that tab (its own onboarding after installation), which
        discards the browsing context the test reads: that is retried once, and a second time fails with the reason
        (#503)."""
        discarded = []
        for _ in range(2):
            handle = self.m.new_tab()
            self.m.switch_to(handle)
            try:
                self.m.navigate(popup)
                harness.wait_until(lambda: (self.m.execute(BODY_COUNT) or 0) > 5, timeout=15)
                time.sleep(1)  # the framework's first paint is there; let it settle for the capture
                text = self.m.execute("return (document.body && document.body.innerText || '').trim().slice(0, 240);")
                return text, self.m.title(), self.m.execute(BODY_COUNT) or 0, self.m.screenshot_png()
            except MarionetteError as error:
                if "discarded" not in str(error):
                    raise
                discarded.append(str(error))
            finally:
                if handle in self.m.window_handles():
                    self.m.switch_to(handle)
                    self.m.send("WebDriver:CloseWindow")
                self.m.switch_to(self.m.window_handles()[0])
        self.fail(f"the popup's tab was discarded twice (the extension closed or replaced it): {discarded}")

    def check_provider(self, key: str) -> dict:
        entry = self.lock[key]
        os.environ["NULAVIO_HOME"] = str(self.session.home)  # fetch() caches inside the disposable home
        try:
            xpi = extensions.fetch(entry)
        finally:
            os.environ.pop("NULAVIO_HOME", None)
        installed_id = self.m.install_addon(str(xpi), temporary=False)
        self.assertEqual(installed_id, entry.id)
        info = harness.wait_until(lambda: (lambda i: i if i.get("active") else None)(self.popup_info(entry.id)), timeout=20)
        self.assertTrue(info, f"{key} did not become active")
        self.assertGreaterEqual(info["signedState"], 2, f"{key} is not Mozilla-signed")
        popup = info["popup"] or (info["base"] + RUNTIME_POPUP[key] if key in RUNTIME_POPUP else None)
        self.assertTrue(popup, f"{key} declares no toolbar popup")
        text, title, elements, shot = self.read_popup(popup)
        (self.artifacts / f"popup-{key}.png").write_bytes(shot)
        result = {
            "version": info["version"],
            "manifest_version": info["manifestVersion"],
            "signedState": info["signedState"],
            "backgroundState": info["backgroundState"],
            "popup_title": title,
            "popup_elements": elements,
            "popup_text_excerpt": text,
            "has_nativeMessaging": "nativeMessaging" in info["permissions"],
        }
        self.evidence[key] = result
        self.assertGreater(elements, 5, f"{key} popup rendered almost nothing")
        return result

    def test_proton_pass(self):
        self.check_provider("proton-pass")

    def test_keepassxc_browser(self):
        result = self.check_provider("keepassxc-browser")
        self.assertTrue(result["has_nativeMessaging"], "KeePassXC-Browser must hold nativeMessaging")

    def test_bitwarden(self):
        self.check_provider("bitwarden")

    def test_1password(self):
        # #81: installs, Mozilla's signature accepted, background running, popup renders; never with an account.
        self.check_provider("1password")


if __name__ == "__main__":
    unittest.main()
