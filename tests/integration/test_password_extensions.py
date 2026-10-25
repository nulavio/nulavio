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

from nulavio_launcher import extensions

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
  permissions: [...ext.permissions].sort(),
  backgroundState: String(ext.backgroundState ?? "n/a"),
};
"""

PROVIDERS = ("proton-pass", "keepassxc-browser", "bitwarden")


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
        self.assertTrue(info["popup"], f"{key} declares no toolbar popup")
        handle = self.m.new_tab()
        self.m.switch_to(handle)
        self.m.navigate(info["popup"])
        time.sleep(4)  # let the popup's framework render
        text = self.m.execute("return (document.body && document.body.innerText || '').trim().slice(0, 240);")
        title = self.m.title()
        elements = self.m.execute("return document.querySelectorAll('body *').length;")
        (self.artifacts / f"popup-{key}.png").write_bytes(self.m.screenshot_png())
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(self.m.window_handles()[0])
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


if __name__ == "__main__":
    unittest.main()
