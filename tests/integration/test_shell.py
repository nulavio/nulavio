"""Nulavio Shell (browser/shell/): new tab (FR-08) and dangerous-download warning (flow E).

Against a Nulavio build the Shell is built in. Against a distribution Firefox
(Track A, CI) the same files are loaded as a temporary add-on: that tests the
behaviour, not the packaging (`test_01` tells which case ran).
"""

from __future__ import annotations

import shutil
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "build"))
import harness
import make_shell

from marionette import MarionetteError

SHELL_ID = "shell@nulavio.net"

ADDON = """
const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
const a = await AddonManager.getAddonByID(arguments[0]);
return a ? {active: a.isActive, builtin: a.isBuiltin, system: a.isSystem, hidden: a.hidden,
            temporary: a.temporarilyInstalled, version: a.version} : null;
"""
NEW_TAB_URL = """
const {AboutNewTab} = ChromeUtils.importESModule("resource:///modules/AboutNewTab.sys.mjs");
return AboutNewTab.newTabURL;
"""


@unittest.skipUnless(harness.engine_available(), "no supported Gecko engine installed")
class ShellTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.Session(profile="shell")
        cls.m = cls.session.start()
        cls.artifacts = harness.artifacts_dir()
        cls.tmp = Path(tempfile.mkdtemp(prefix="nulavio-shell-"))
        cls.main_tab = cls.m.window_handles()[0]
        cls.state = cls.addon_state()
        if cls.state is None:  # distribution Firefox: load the same files temporarily
            shell_dir = cls.tmp / "shell"
            make_shell.assemble(shell_dir, privileged=False)
            cls.m.install_addon(str(shell_dir), temporary=True)
            cls.state = harness.wait_until(lambda: (lambda s: s if s and s.get("active") else None)(cls.addon_state()))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)
            shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def addon_state(cls):
        cls.m.set_context("chrome")
        try:
            return cls.m.execute_async(
                "const [id, done] = arguments; (async () => {" + ADDON.replace("arguments[0]", "id") + "})().then(done);",
                [SHELL_ID],
            )
        finally:
            cls.m.set_context("content")

    def root_data(self, name: str):
        """data-* attribute of the current page's root, or None while the document is not there yet."""
        try:
            return self.m.execute("return document.documentElement && document.documentElement.dataset[arguments[0]];", [name])
        except MarionetteError:
            return None  # navigation in progress: the document can be briefly missing

    def panel_item(self, name: str) -> dict:
        """The engine's downloads panel entry for a file (flow E in the panel, patch 0007)."""
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(
                """
                const [name, done] = arguments;
                (async () => {
                  const { Downloads } = ChromeUtils.importESModule("resource://gre/modules/Downloads.sys.mjs");
                  const list = await Downloads.getList(Downloads.ALL);
                  const download = (await list.getAll()).find(d => d.target.path.endsWith("/" + name));
                  DownloadsPanel.showPanel();
                  let item = null;
                  for (let i = 0; i < 100 && !(item = DownloadsView._visibleViewItems.get(download)); i++) {
                    await new Promise(r => setTimeout(r, 100));
                  }
                  const out = {
                    defaultCommand: item.currentDefaultCommandName,
                    canOpen: item.isCommandEnabled("downloadsCmd_open"),
                    canAlwaysOpen: item.isCommandEnabled("downloadsCmd_alwaysOpenSimilarFiles"),
                    canShow: item.isCommandEnabled("downloadsCmd_show"),
                    canDelete: item.isCommandEnabled("downloadsCmd_deleteFile"),
                    program: item.element.hasAttribute("nulavio-program"),
                    status: item._downloadDetailsNormal.getAttribute("value") ?? "",
                  };
                  DownloadsPanel.hidePanel();
                  return out;
                })().then(done, e => done({ error: String(e) }));
                """,
                [name],
            )
        finally:
            self.m.set_context("content")

    def new_handles(self, before: set[str]) -> list[str]:
        return [h for h in self.m.window_handles() if h not in before]

    def tearDown(self):
        # Back to the first tab; close anything a test opened.
        for handle in self.m.window_handles():
            if handle != self.main_tab:
                self.m.switch_to(handle)
                self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(self.main_tab)
        self.m.navigate("about:blank")

    # -- tests ------------------------------------------------------------
    def test_01_shell_is_active(self):
        self.assertTrue(self.state and self.state.get("active"), f"Nulavio Shell not active: {self.state}")
        if self.state.get("temporary"):
            return  # distribution Firefox: behaviour tests only
        self.assertTrue(self.state["builtin"], "Shell must ship inside the build, not as a profile extension")
        self.assertTrue(self.state["system"])
        self.assertTrue(self.state["hidden"], "built-in components stay out of the user's extension list")

    def test_02_new_tab_is_nulavio_with_live_status(self):
        url = self.m.chrome(NEW_TAB_URL)
        self.assertTrue(url.startswith("moz-extension://") and url.endswith("/newtab/newtab.html"), url)
        before = set(self.m.window_handles())
        self.m.chrome("window.BrowserCommands.openTab();")
        created = harness.wait_until(lambda: self.new_handles(before), timeout=10)
        self.assertTrue(created, "Ctrl+T did not open a tab")
        self.m.switch_to(created[0])
        ready = harness.wait_until(lambda: self.root_data("ready"), timeout=15)
        self.assertEqual(ready, "true")
        self.assertEqual(self.m.current_url(), url)
        status = dict(
            (key, (level, text))
            for key, level, text in self.m.execute(
                "return [...document.querySelectorAll('[data-status]')].filter(e => !e.closest('[hidden]'))"
                ".map(e => [e.dataset.status, e.dataset.level, e.textContent]);"
            )
        )
        expected = {"tracking", "https", "gpc", "filter", "passwords"}
        if harness.nulavio_engine():
            expected.add("dns")  # the build's privileged Shell reads the DNS mode too
        self.assertEqual(set(status), expected)
        for key in ("tracking", "https", "gpc"):  # Nulavio defaults: ETP Strict, HTTPS-Only, GPC
            self.assertEqual(status[key][0], "ok", f"{key}: {status[key]}")
        for key, (level, text) in status.items():
            self.assertIn(level, ("ok", "warn"), f"{key} could not be read: {text}")
            self.assertTrue(text.strip() and text != "…", key)
        labelled = self.m.execute(
            "const i = document.getElementById('search-input');"
            "return Boolean(document.querySelector(`label[for='${i.id}']`)?.textContent.trim()) && Boolean(i.placeholder);"
        )
        self.assertTrue(labelled, "search box needs a label and a placeholder")
        (self.artifacts / "shell-newtab.png").write_bytes(self.m.screenshot_png())

    def test_03_executable_download_opens_warning_without_open(self):
        target = self.session.downloads / "nulavio-setup.AppImage"
        self.m.navigate(self.server.url("/page/download-exe-start"))
        before = set(self.m.window_handles())
        self.m.execute("location.href = arguments[0];", [self.server.url("/download-exe")])
        created = harness.wait_until(lambda: self.new_handles(before), timeout=20)
        self.assertTrue(created, "no warning page after an executable download")
        self.assertTrue(target.exists())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode) & 0o111, 0, "download saved with execute permission")
        self.m.switch_to(created[0])
        state = harness.wait_until(lambda: self.root_data("state"), timeout=15)
        self.assertEqual(state, "ready")
        self.assertIn("/warning/warning.html?id=", self.m.current_url())
        text = self.m.execute("return document.body.innerText;")
        self.assertIn("nulavio-setup.AppImage", text)
        self.assertIn("127.0.0.1", text)
        buttons = self.m.execute(
            "return [...document.querySelectorAll('button')].filter(b => !b.closest('[hidden]'))"
            ".map(b => [b.id, b.textContent.trim()]);"
        )
        self.assertEqual([b[0] for b in buttons], ["show", "delete"], buttons)
        self.assertFalse(any(label.lower() in ("abrir", "open") for _, label in buttons), "flow E must not offer Open")
        (self.artifacts / "shell-download-warning.png").write_bytes(self.m.screenshot_png())
        if harness.nulavio_engine():
            # The engine's own downloads panel (patch 0007): shown in its folder, never opened from there.
            panel = self.panel_item("nulavio-setup.AppImage")
            self.assertEqual(panel["defaultCommand"], "downloadsCmd_show", panel)
            self.assertEqual((panel["canOpen"], panel["canAlwaysOpen"]), (False, False), panel)
            self.assertEqual((panel["canShow"], panel["canDelete"], panel["program"]), (True, True, True), panel)
            self.assertIn("program", panel["status"].lower())
        self.m.execute("document.getElementById('delete').click();")
        deleted = harness.wait_until(lambda: self.root_data("state") == "deleted")
        self.assertTrue(deleted, "Delete did not report success")
        self.assertFalse(target.exists(), "Delete left the file on disk")

    def test_04_regular_download_does_not_warn(self):
        target = self.session.downloads / "nulavio-fixture.bin"
        self.m.navigate(self.server.url("/page/download-start"))
        before = set(self.m.window_handles())
        self.m.execute("location.href = arguments[0];", [self.server.url("/download")])
        self.assertTrue(harness.wait_until(target.exists, timeout=20), "download did not complete")
        time.sleep(2)  # the warning, if any, opens right after completion
        self.assertEqual(self.new_handles(before), [], "a non-executable download must not trigger flow E")
        if harness.nulavio_engine():
            panel = self.panel_item("nulavio-fixture.bin")
            self.assertEqual((panel["defaultCommand"], panel["canOpen"], panel["program"]), ("downloadsCmd_open", True, False))

    def test_05_warning_page_handles_unknown_download(self):
        url = self.m.chrome(NEW_TAB_URL).replace("/newtab/newtab.html", "/warning/warning.html?id=999999")
        try:
            self.m.navigate(url)
        except MarionetteError:
            pass
        state = harness.wait_until(lambda: self.root_data("state"), timeout=10)
        self.assertEqual(state, "error")
        buttons = self.m.execute("return [...document.querySelectorAll('button')].filter(b => !b.closest('[hidden]')).length;")
        self.assertEqual(buttons, 0, "no actions for a download that does not exist")

    def test_06_private_download_warns_in_a_private_window(self):
        if self.state.get("temporary"):
            self.skipTest("temporary add-ons do not run in private windows without the user's permission")
        before = set(self.m.window_handles())
        self.m.chrome("OpenBrowserWindow({private: true});")
        private_tab = harness.wait_until(lambda: self.new_handles(before), timeout=15)
        self.assertTrue(private_tab, "private window did not open")
        self.m.switch_to(private_tab[0])
        self.m.navigate(self.server.url("/page/private-download-start"))
        target = self.session.downloads / "nulavio-setup.AppImage"
        target.unlink(missing_ok=True)
        before = set(self.m.window_handles())
        self.m.execute("location.href = arguments[0];", [self.server.url("/download-exe")])
        created = harness.wait_until(lambda: self.new_handles(before), timeout=20)
        self.assertTrue(created, "no warning page for a private download")
        warnings = self.m.chrome(
            "const {PrivateBrowsingUtils} = ChromeUtils.importESModule("
            "'resource://gre/modules/PrivateBrowsingUtils.sys.mjs');"
            "const out = [];"
            "for (const win of Services.wm.getEnumerator('navigator:browser')) {"
            "  for (const b of win.gBrowser.browsers) {"
            "    if (b.currentURI.spec.includes('/warning/warning.html')) out.push(PrivateBrowsingUtils.isWindowPrivate(win));"
            "  }"
            "}"
            "return out;"
        )
        self.assertIn(True, warnings, "no warning in the private window")
        self.assertNotIn(False, warnings, "a private download's warning leaked into a normal window")
        target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
