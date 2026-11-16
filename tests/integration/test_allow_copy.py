"""#160: "Permitir copiar e colar neste site". A site that cancels copy, cut, paste, the page menu or selection, and
turns selection off, cannot do it once the switch in the shield's panel is on for its address; other sites, and frames
from other sites, keep their own rules, and a web editor elsewhere still handles paste itself. No pref changes."""

from __future__ import annotations

import unittest

import harness

COPY = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAllowCopy.sys.mjs").NulavioAllowCopy'
PANEL = """
const done = arguments[arguments.length - 1];
(async () => {
  const panel = () => document.getElementById("trustpanel-popup");
  if (panel()?.state !== "open") {
    await gTrustPanelHandler.showPopup();
    await new Promise(r => (panel().state === "open" ? r() : panel().addEventListener("popupshown", r, { once: true })));
  }
  const row = document.getElementById("nulavio-trustpanel-allow-copy");
  const toggle = row?.querySelector("moz-toggle");
  const state = row && { shown: !row.hidden && row.checkVisibility(), on: toggle.pressed,
    label: row.querySelector("label.trustpanel-header").textContent,
    description: document.getElementById("nulavio-trustpanel-allow-copy-description").textContent,
    tip: document.getElementById("nulavio-trustpanel-allow-copy-tip").textContent };
  if (arguments[0] === "press" && toggle) {
    toggle.click();
  } else {
    panel().hidePopup();
  }
  return state;
})().then(done, e => done({ error: String(e) }));
"""
CLIPBOARD = (
    "const t = Cc['@mozilla.org/widget/transferable;1'].createInstance(Ci.nsITransferable); t.init(null);"
    "t.addDataFlavor('text/plain'); Services.clipboard.getData(t, Ci.nsIClipboard.kGlobalClipboard);"
    "const out = {}; try { t.getTransferData('text/plain', out); } catch { return ''; }"
    "return out.value.QueryInterface(Ci.nsISupportsString).data;"
)
PUT = "Cc['@mozilla.org/widget/clipboardhelper;1'].getService(Ci.nsIClipboardHelper).copyString(arguments[0]);"
PREFS = "return ['dom.event.clipboardevents.enabled', 'dom.event.contextmenu.enabled'].map(p => Services.prefs.getBoolPref(p));"


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class AllowCopyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()
        cls.page = cls.server.url("/copy-blocked?frame=1")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def tearDown(self):
        self.m.chrome("Services.perms.removeByType('nulavio-allow-copy');")

    def panel(self, action: str = "") -> dict:
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(PANEL, [action])
        finally:
            self.m.set_context("content")

    def load(self, url: str) -> None:
        self.m.navigate(url)
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.readyState") == "complete", 10))

    def copy_text(self) -> str:
        """Select the number and copy it as the Edit menu does; what reached the clipboard."""
        self.m.chrome(PUT, ["antes"])
        self.m.execute("getSelection().selectAllChildren(document.getElementById('text'));")
        self.m.chrome("goDoCommand('cmd_copy');")
        harness.wait_until(lambda: self.m.chrome(CLIPBOARD) != "antes", 3)
        return self.m.chrome(CLIPBOARD)

    def paste_text(self, selector: str) -> str:
        self.m.chrome(PUT, ["s3nha"])
        self.m.execute(f"document.querySelector('{selector}').focus();")
        self.m.chrome("goDoCommand('cmd_paste');")
        harness.wait_until(lambda: self.m.execute(f"return document.querySelector('{selector}').value ?? '';"), 3)
        return self.m.execute(f"const e = document.querySelector('{selector}'); return e.value ?? e.textContent;")

    def menu_opens(self) -> tuple[bool, list]:
        self.m.context_click("#text")
        opened = harness.wait_until(self.m.menu_open, 5)
        if opened:
            self.m.close_menu()
        return bool(opened), self.m.execute("return window.seen;")

    def test_01_off_the_site_keeps_its_rules(self):
        self.load(self.page)
        self.assertEqual(self.copy_text(), "antes")
        self.assertEqual(self.paste_text("#field"), "")
        opened, seen = self.menu_opens()
        self.assertFalse(opened)
        self.assertIn("contextmenu", seen)
        self.assertEqual(self.m.execute("return getComputedStyle(document.body).userSelect;"), "none")

    def test_02_on_copy_paste_the_menu_and_selection_work_and_the_page_sees_none_of_them(self):
        self.load(self.page)
        row = self.panel()
        self.assertEqual((row["shown"], row["on"]), (True, False), row)
        self.assertRegex(row["label"], r"(copiar e colar|copy and paste)")
        self.assertRegex(row["tip"], r"Shift\+")
        self.panel("press")  # the switch reloads the page
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(f"return {COPY}.state(gBrowser.selectedBrowser).on;"), 10))
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.readyState") == "complete", 10))
        listed = "return Services.perms.getAllByTypes(['nulavio-allow-copy']).map(p => p.principal.origin);"
        self.assertEqual(self.m.chrome(listed), [f"http://127.0.0.1:{self.server.port}"])
        self.assertEqual(self.copy_text(), "Numero 1234-5678")
        self.assertEqual(self.paste_text("#field"), "s3nha")
        opened, seen = self.menu_opens()
        self.assertTrue(opened, "the browser's page menu did not open")
        self.assertEqual(seen, [], "the page's handlers saw the events")
        self.assertEqual(self.m.execute("return getComputedStyle(document.body).userSelect;"), "text")
        row = self.panel()
        self.assertTrue(row["on"])
        # The frame from another site keeps its own rules.
        frame = self.m.find_element("#frame")
        self.m.send("WebDriver:SwitchToFrame", {"element": frame})
        try:
            self.assertEqual(self.m.execute("return getComputedStyle(document.body).userSelect;"), "none")
            self.m.execute("document.dispatchEvent(new Event('copy', { bubbles: true }));")
            self.assertEqual(self.m.execute("return window.seen;"), ["copy", "copy"])
        finally:
            self.m.send("WebDriver:SwitchToParentFrame")
        # No global pref was touched for it.
        self.assertEqual(self.m.chrome(PREFS), [True, True])

    def test_03_another_site_keeps_its_rules_and_a_web_editor_still_handles_paste(self):
        self.load(self.page)
        self.m.chrome(f"{COPY}.set(gBrowser.selectedBrowser, true);")
        self.load(self.server.url("/copy-blocked").replace("127.0.0.1", "localhost"))
        self.assertEqual(self.copy_text(), "antes")
        self.load(self.server.url("/web-editor").replace("127.0.0.1", "localhost"))
        self.m.chrome(PUT, ["colado"])
        self.m.execute("const e = document.getElementById('editor'); e.focus(); getSelection().selectAllChildren(e);")
        self.m.chrome("goDoCommand('cmd_paste');")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return window.seen;") == ["paste"], 5))
        self.assertEqual(self.m.execute("return document.getElementById('editor').textContent;"), "editor:colado")

    def test_04_turned_off_the_site_has_its_rules_back(self):
        self.load(self.page)
        self.m.chrome(f"{COPY}.set(gBrowser.selectedBrowser, true);")
        self.load(self.page)
        self.assertEqual(self.copy_text(), "Numero 1234-5678")
        self.panel("press")
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(f"return {COPY}.state(gBrowser.selectedBrowser).on;"), 10))
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.readyState") == "complete", 10))
        self.assertEqual(self.copy_text(), "antes")
        self.assertEqual(self.m.chrome("return Services.perms.getAllByTypes(['nulavio-allow-copy']).length;"), 0)

    def test_05_not_offered_on_the_browsers_own_pages(self):
        self.m.navigate(self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('newtab/newtab.html');"))
        self.assertFalse(self.m.chrome(f"return {COPY}.state(gBrowser.selectedBrowser).offered;"))


if __name__ == "__main__":
    unittest.main()
