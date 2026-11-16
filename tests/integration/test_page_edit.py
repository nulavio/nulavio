"""#161: "Editar o texto da página". The page menu item and Ctrl+Alt+E make the text of the tab's page editable in
place and turn it off; a bar of the tab says the page is editable and that nothing is saved. Reloading discards the
changes and ends it, frames from other sites are left as they are, and the browser's own pages are not offered."""

from __future__ import annotations

import unittest

import harness

EDIT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPageEdit.sys.mjs").NulavioPageEdit'
# The tab's bar, as the engine draws it: its words and its button.
BAR = """
const n = gBrowser.getNotificationBox(gBrowser.selectedBrowser).getNotificationWithValue("nulavio-page-edit");
return n && { label: n.messageText?.textContent ?? String(n.label),
              buttons: [...n.buttonContainer.querySelectorAll("button")].map(b => b.label) };
"""
KEY = """
const key = [...document.querySelectorAll('#ext-keyset-id-shell_nulavio_net key')]
  .find(k => (k.getAttribute('key') || '').toUpperCase() === 'E'
    && /alt/.test(k.getAttribute('modifiers')) && /accel|control/.test(k.getAttribute('modifiers')));
key.doCommand();
return true;
"""
ITEM = (
    "const i = document.getElementById('context-nulavio-edit-page');"
    "return i && { hidden: i.hidden, checked: i.getAttribute('checked') };"
)
MENU_ITEM = "document.getElementById('context-nulavio-edit-page')"


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class PageEditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()
        cls.page = cls.server.url("/edit-page")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def setUp(self):
        self.m.navigate(self.page)
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.readyState") == "complete", 10))

    def design(self) -> str:
        return self.m.execute("return document.designMode;")

    def bar(self):
        return self.m.chrome(BAR)

    def frame_design(self) -> list:
        frame = self.m.find_element("#frame")
        self.m.send("WebDriver:SwitchToFrame", {"element": frame})
        try:
            return self.m.execute("return [document.designMode, location.host];")
        finally:
            self.m.send("WebDriver:SwitchToParentFrame")

    def test_01_the_key_makes_the_page_editable_with_the_bar_and_a_reload_discards_it(self):
        self.m.chrome(KEY)
        self.assertTrue(harness.wait_until(lambda: self.design() == "on", 10), self.design())
        bar = harness.wait_until(self.bar, 10)
        self.assertTrue(bar, "no bar on the tab")
        self.assertRegex(bar["label"], r"(Nada é salvo|Nothing is saved)")
        self.assertRegex(bar["label"], r"(recarregar|reloading)")
        self.assertEqual(len(bar["buttons"]), 1, bar)
        # The text can be changed as a person types it, which the page could not before.
        changed = self.m.execute(
            "const p = document.getElementById('text'); getSelection().selectAllChildren(p);"
            "document.execCommand('insertText', false, 'Texto mudado.'); return p.textContent;"
        )
        self.assertEqual(changed, "Texto mudado.")
        # The frame from another site keeps what it was.
        design, host = self.frame_design()
        self.assertEqual(design, "off")
        self.assertTrue(host.startswith("localhost:"), host)
        # Reloading brings the page back as it was, not editable, and the bar goes with it.
        self.m.execute("location.reload();")
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.execute("return document.getElementById('text')?.textContent") == "Texto original.", 10
            )
        )
        self.assertTrue(harness.wait_until(lambda: self.bar() is None, 10), self.bar())
        self.assertEqual(self.design(), "off")

    def test_02_the_key_again_and_the_bars_button_turn_it_off(self):
        self.m.chrome(KEY)
        self.assertTrue(harness.wait_until(lambda: self.design() == "on", 10))
        self.m.chrome(KEY)
        self.assertTrue(harness.wait_until(lambda: self.design() == "off", 10))
        self.assertTrue(harness.wait_until(lambda: self.bar() is None, 10))
        self.m.chrome(KEY)
        self.assertTrue(harness.wait_until(lambda: self.bar() is not None, 10))
        self.m.chrome(
            'gBrowser.getNotificationBox(gBrowser.selectedBrowser).getNotificationWithValue("nulavio-page-edit")'
            '.querySelector(".notification-button").doCommand();'
        )
        self.assertTrue(harness.wait_until(lambda: self.design() == "off", 10))
        self.assertTrue(harness.wait_until(lambda: self.bar() is None, 10))

    def test_03_a_page_left_and_shown_again_from_the_cache_is_not_editable(self):
        self.m.chrome(KEY)
        self.assertTrue(harness.wait_until(lambda: self.design() == "on", 10))
        self.m.navigate(self.server.url("/page/other"))
        self.assertTrue(harness.wait_until(lambda: self.bar() is None, 10))
        self.m.execute("history.back();")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.title") == "edit-page", 10))
        self.assertEqual(self.design(), "off")
        self.assertIsNone(self.bar())

    def test_04_the_page_menu_offers_it_and_shows_its_state(self):
        self.m.context_click("#text")
        try:
            item = harness.wait_until(lambda: (lambda i: i if i and not i["hidden"] else None)(self.m.chrome(ITEM)), 10)
            self.assertTrue(item, self.m.chrome(ITEM))
            self.assertNotEqual(item["checked"], "true")
            self.m.chrome(f"document.getElementById('contentAreaContextMenu').activateItem({MENU_ITEM});")
        finally:
            self.m.chrome("document.getElementById('contentAreaContextMenu').hidePopup();")
        self.assertTrue(harness.wait_until(lambda: self.design() == "on", 10))
        self.m.context_click("#text")
        try:
            checked = harness.wait_until(lambda: (self.m.chrome(ITEM) or {}).get("checked") == "true", 10)
            self.assertTrue(checked, self.m.chrome(ITEM))
        finally:
            self.m.chrome("document.getElementById('contentAreaContextMenu').hidePopup();")
        self.m.chrome(KEY)
        self.assertTrue(harness.wait_until(lambda: self.design() == "off", 10))
        # Next to the engine's "View Page Source".
        self.assertEqual(self.m.chrome(f"return {MENU_ITEM}.nextElementSibling.id;"), "context-viewsource")

    def test_06_closing_the_bar_ends_editing(self):
        # Review of #385 (CodeRabbit): the bar closed with its own button takes editing with it.
        self.m.chrome(KEY)
        self.assertTrue(harness.wait_until(lambda: self.bar() is not None, 10))
        self.m.chrome(
            'gBrowser.getNotificationBox(gBrowser.selectedBrowser).getNotificationWithValue("nulavio-page-edit").dismiss();'
        )
        self.assertTrue(harness.wait_until(lambda: self.design() == "off", 10), self.design())
        self.assertIsNone(self.bar())

    def test_05_the_browsers_own_pages_are_not_offered(self):
        base = self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        self.m.navigate(base + "newtab/newtab.html")
        self.m.set_context("chrome")
        try:
            refused = self.m.execute_async(
                "const resolve = arguments[arguments.length - 1];"
                f"{EDIT}.set(gBrowser.selectedBrowser, true).then(() => resolve('changed'), e => resolve(e.code));"
            )
        finally:
            self.m.set_context("content")
        self.assertEqual(refused, "page-edit-unavailable")
        self.assertIsNone(self.bar())
        self.assertFalse(self.m.chrome(f"return {EDIT}.state(gBrowser.selectedBrowser).available;"))


if __name__ == "__main__":
    unittest.main()
