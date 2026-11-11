"""ADR 0009: Immersive. The toolbar and the tab list leave the view; the band stays, with the site.

The window decides where the mode applies: never where the band cannot name the page, never in a
pop-up, never while a device is shared; and a panel anchored on the toolbar keeps it shown."""

from __future__ import annotations

import unittest

import harness

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
# The window: whether Immersive is drawn, why not, what holds the chrome, and what is really in view.
WINDOW = """
const root = document.documentElement;
const bar = getComputedStyle(document.getElementById("nav-bar"));
const origin = document.querySelector("#nulavio-band .nv-band-origin");
return {
  on: root.hasAttribute("nulavio-immersive"),
  off: root.getAttribute("nulavio-immersive-off"),
  hold: root.getAttribute("nulavio-immersive-hold"),
  toolbar: bar.opacity === "1" && bar.pointerEvents !== "none",
  band: document.getElementById("nulavio-band").getBoundingClientRect().height > 0,
  origin: origin && origin.checkVisibility() ? origin.textContent : null,
};
"""


@unittest.skipUnless(harness.nulavio_engine(), "Immersive needs the built-in Shell on the engine")
class ImmersiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Imersivo")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()
        cls.page = cls.server.url("/page/Imersivo")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def setUp(self):
        self.m.navigate(self.page)
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', true); gBrowser.selectedBrowser.focus();")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())

    def window(self):
        return self.m.chrome(WINDOW)

    def settled(self, want: bool) -> dict:
        """The toolbar in (or out of) view, after its transition and its hold time."""
        harness.wait_until(lambda: self.window()["toolbar"] is want, 6)
        return self.window()

    def test_01_off_unless_the_person_turns_it_on(self):
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        state = self.settled(True)
        self.assertEqual((state["on"], state["off"], state["toolbar"]), (False, None, True), state)

    def test_02_the_band_stays_with_the_site_and_its_port(self):
        state = self.settled(False)
        self.assertTrue(state["band"], state)
        self.assertFalse(state["toolbar"], state)
        self.assertIn(f"127.0.0.1:{self.server.port}", state["origin"], "the site, with its port, is in the band")
        # One key brings the address back with the keyboard in it; leaving it lets the toolbar go.
        self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
        self.assertTrue(self.settled(True)["toolbar"])
        self.m.chrome("gBrowser.selectedBrowser.focus();")
        self.assertFalse(self.settled(False)["toolbar"])

    def test_03_a_page_the_band_cannot_name_keeps_the_full_window(self):
        for address in ("about:blank", "data:text/html,<h1>x</h1>", f"view-source:{self.page}"):
            with self.subTest(address=address):
                self.m.chrome(
                    "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
                    " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
                    [address],
                )
                self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "page", 10), self.window())
                state = self.settled(True)
                self.assertEqual((state["on"], state["toolbar"]), (False, True), state)
        self.m.navigate(self.page)
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())

    def test_04_a_panel_on_the_toolbar_holds_it_and_a_menu_on_the_page_does_not(self):
        self.assertFalse(self.settled(False)["toolbar"])
        # A permission request: the browser shows the toolbar itself, for as long as its panel is open.
        self.m.execute("navigator.geolocation.getCurrentPosition(() => {}, () => {});")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "toolbar", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"], "the toolbar is not shown under the permission request")
        self.m.chrome("PopupNotifications.remove(PopupNotifications.getNotification('geolocation', gBrowser.selectedBrowser));")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        # The application menu, anchored on its button.
        self.m.chrome("PanelUI.show();")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "toolbar", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"])
        self.m.chrome("PanelUI.hide();")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 10), self.window())
        # A menu opened on the page is the page's business: nothing comes into view.
        self.m.chrome(
            "const menu = document.getElementById('contentAreaContextMenu');"
            "menu.openPopupAtScreen(window.screenX + 400, window.screenY + 400, true);"
        )
        self.assertTrue(
            harness.wait_until(
                lambda: self.m.chrome("return document.getElementById('contentAreaContextMenu').state;") == "open", 10
            )
        )
        state = self.window()
        self.m.chrome("document.getElementById('contentAreaContextMenu').hidePopup();")
        self.assertEqual((state["hold"], state["toolbar"]), (None, False), state)

    def test_05_a_window_without_the_full_toolbar_is_never_immersive(self):
        before = set(self.m.window_handles())
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.m.chrome(
            "window.openDialog(AppConstants.BROWSER_CHROME_URL, '_blank', 'chrome,dialog=no,location,width=480,height=360',"
            " arguments[0]);",
            [self.page],
        )
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - before, 20))
        self.m.switch_to((set(self.m.window_handles()) - before).pop())
        try:
            self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "popup", 15), self.window())
            self.assertFalse(self.window()["on"])
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)

    def test_06_while_a_device_is_shared_the_toolbar_stays(self):
        # The engine's test mode for capture (fake devices, no prompt) bypasses its own sharing indicators, so the
        # state is set where the engine sets it for a real capture: the tab's sharing state (updateBrowserSharing).
        share = "gBrowser.updateBrowserSharing(gBrowser.selectedBrowser, {webRTC: arguments[0]});"
        self.m.chrome(share, [{"sharing": "microphone", "microphone": 1, "camera": 0, "screen": "", "paused": False}])
        self.addCleanup(self.m.chrome, share, [None])
        self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "sharing", 15), self.window())
        state = self.settled(True)
        self.assertEqual((state["on"], state["toolbar"]), (False, True), state)
        # A tab in the background that shares keeps the toolbar too.
        self.m.chrome("gBrowser.selectedTab = gBrowser.addTrustedTab(arguments[0]);", [self.page])
        self.addCleanup(self.m.chrome, "while (gBrowser.tabs.length > 1) gBrowser.removeTab(gBrowser.tabs.at(-1));")
        harness.wait_until(lambda: self.m.chrome("return !gBrowser.selectedBrowser.webProgress.isLoadingDocument;"), 15)
        self.assertEqual(self.window()["off"], "sharing", self.window())
        self.m.chrome("gBrowser.updateBrowserSharing(gBrowser.tabs[0].linkedBrowser, {webRTC: null});")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 15), self.window())

    def test_07_the_switch_and_the_key_write_one_pref_and_say_so(self):
        pref = "return Services.prefs.getBoolPref('nulavio.layout.immersive', false);"
        said = self.m.chrome(
            f"const said = []; const L = {LAYOUT};"
            "const off = L.setImmersive(false, key => said.push(key)); const on = L.setImmersive(true, key => said.push(key));"
            "return [off, on, said];"
        )
        self.assertEqual(
            said, [{"on": False, "locked": False}, {"on": True, "locked": False}, ["layoutImmersiveOff", "layoutImmersiveOn"]]
        )
        self.assertTrue(self.m.chrome(pref))
        # Locked by an administrator: nothing changes, and the reason is said.
        refused = self.m.chrome(
            f"const L = {LAYOUT}; Services.prefs.lockPref('nulavio.layout.immersive'); const said = [];"
            "try { L.setImmersive(false, key => said.push(key)); return 'changed'; } catch (e) { return [e.code, said]; }"
            "finally { Services.prefs.unlockPref('nulavio.layout.immersive'); }"
        )
        self.assertEqual(refused, ["layout-locked", ["layoutLocked"]])
        self.assertTrue(self.m.chrome(pref))

    def test_08_the_switch_in_settings_turns_it_on_and_off(self):
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        settings = self.m.chrome(
            "return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('settings/settings.html#layout');"
        )
        self.m.navigate(settings)
        switch = (
            "return (e => [e.checked, e.disabled, e.closest('[data-option]')?.dataset.option])"
            "(document.getElementById('immersive'));"
        )
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute(switch) == [False, False, "immersive"], 15), self.m.execute(switch)
        )
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#immersive")})
        pref = "return Services.prefs.getBoolPref('nulavio.layout.immersive', false);"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(pref), 10))
        # Settings is one of Nulavio's named pages: the band vouches for it, so the mode applies here too.
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#immersive")})
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(pref), 10))
        self.assertTrue(self.settled(True)["toolbar"])


if __name__ == "__main__":
    unittest.main()
