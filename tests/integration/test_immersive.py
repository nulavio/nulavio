"""ADR 0009: Immersive. The toolbar and the tab list leave the view; the band stays, with the site.

The window decides where the mode applies: never where the band cannot name the page, never in a
pop-up, never while a device is shared; and a panel anchored on the toolbar keeps it shown."""

from __future__ import annotations

import unittest

import harness
import settings_page

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

# The engine's security cues of the address bar (the list of test_horizon 07, with the identity box): how each is
# drawn, and where. Immersive must change none of them; it only takes the toolbar they sit in out of view.
CUES = """
const view = document.documentElement.getBoundingClientRect();
return ["identity-box", "trust-icon-container", "tracking-protection-icon-container", "identity-permission-box",
        "remote-control-box", "notification-popup-box"].map(id => {
  const e = document.getElementById(id);
  if (!e) return { id, missing: true };
  const style = getComputedStyle(e), box = e.getBoundingClientRect();
  return { id, display: style.display, visibility: style.visibility, opacity: style.opacity,
           width: Math.round(box.width), height: Math.round(box.height),
           inside: box.width > 0 && box.top >= view.top && box.bottom <= view.bottom };
});
"""
# What the band says while the toolbar is away: who, how protected, which site, and what the engine thinks of the
# connection (its own verdict: the identity box's classes).
BAND = """
const band = document.getElementById("nulavio-band");
const text = name => {
  const e = band.querySelector(`.nv-band-${name}`);
  return e && e.checkVisibility() ? e.textContent.trim() : null;
};
const origin = band.querySelector(".nv-band-origin");
return { name: text("name"), protection: text("protection"), host: text("origin-host"), state: text("origin-state"),
         secure: origin.getAttribute("data-secure"), label: origin.getAttribute("aria-label"),
         engine: [...document.getElementById("identity-box").classList] };
"""

# Hold the request for one address before it leaves, as a site that is slow to answer does; and let it go.
HOLD = """
const held = (window.nvHeld = { address: arguments[0], channel: null });
window.nvHold = { observe(subject) {
  const channel = subject.QueryInterface(Ci.nsIHttpChannel);
  if (channel.URI.spec === held.address && !held.channel) { channel.suspend(); held.channel = channel; }
} };
Services.obs.addObserver(window.nvHold, "http-on-modify-request");
"""
RELEASE = """
if (window.nvHold) { Services.obs.removeObserver(window.nvHold, "http-on-modify-request"); delete window.nvHold; }
if (window.nvHeld?.channel) { window.nvHeld.channel.resume(); }
delete window.nvHeld;
"""
# The selected tab: the address the engine shows for it, and the document that is really in it.
DOCUMENT = """
const browser = gBrowser.selectedBrowser;
return { shown: browser.currentURI.spec, there: browser.browsingContext.currentWindowGlobal?.documentURI?.spec ?? null };
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
        for address in ("about:blank", "about:blank#x", "about:blank?x", "data:text/html,<h1>x</h1>", f"view-source:{self.page}"):
            with self.subTest(address=address):
                self.m.chrome(
                    "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
                    " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
                    [address],
                )
                self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "page", 10), self.window())
                state = self.settled(True)
                self.assertEqual((state["on"], state["toolbar"]), (False, True), state)
        # Back to a site, loaded as the addresses above were: the remote's own "navigate" now and then leaves the
        # tab on the page's source (same address, another kind of document), and the mode is then rightly off.
        self.m.chrome(
            "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
            " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
            [self.page],
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(DOCUMENT)["there"] == self.page, 15), self.m.chrome(DOCUMENT))
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), (self.window(), self.m.chrome(DOCUMENT)))

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
        # A capture that is paused is still a capture: the tab's mark may go, the browser's state stays.
        self.m.chrome(
            "const first = gBrowser.tabs[0];"
            "gBrowser.updateBrowserSharing(first.linkedBrowser, {webRTC: {sharing: 'microphone', paused: true}});"
            "first.removeAttribute('sharing'); gBrowser._tabAttrModified(first, ['sharing']);"
        )
        self.assertEqual(self.window()["off"], "sharing", self.window())
        self.m.chrome("gBrowser.updateBrowserSharing(gBrowser.tabs[0].linkedBrowser, {webRTC: null});")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 15), self.window())

    def test_06b_a_prompt_on_the_tab_brings_the_full_window_back(self):
        """Independent review (2026-11-11): the engine's tab prompts are not panels. For a cross-site HTTP
        authentication request it rewrites the address bar to the site that asks; that must be in view."""
        self.assertFalse(self.settled(False)["toolbar"])
        # A dialog in the engine's tab dialog box, where its prompts live. (Not an alert: the test driver
        # dismisses those by itself.)
        self.m.chrome(
            "gBrowser.getTabDialogBox(gBrowser.selectedBrowser).open('chrome://global/content/aboutAbout.html',"
            " {features: 'resizable=no', modalType: Services.prompt.MODAL_TYPE_TAB});"
        )
        self.assertTrue(harness.wait_until(lambda: self.window()["off"] == "prompt", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"], "the toolbar is not shown under a tab prompt")
        self.m.chrome("gBrowser.selectedBrowser.tabDialogBox.getTabDialogManager().abortDialogs();")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        # The state the engine sets for a cross-site authentication request, before its dialog opens.
        mark = "gBrowser.selectedBrowser.currentAuthPromptURI = arguments[0] ? Services.io.newURI(arguments[0]) : null;"
        refresh = "gBrowser.tabContainer.dispatchEvent(new CustomEvent('TabSelect', {bubbles: true}));"
        self.m.chrome(mark + refresh, ["https://other.example/"])
        self.addCleanup(self.m.chrome, mark + refresh, [None])
        self.assertEqual(self.window()["off"], "prompt", self.window())
        self.m.chrome(mark + refresh, [None])
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())

    def test_06c_a_download_that_needs_attention_keeps_the_toolbar(self):
        self.assertFalse(self.settled(False)["toolbar"])
        button = "document.getElementById('downloads-button')"
        self.m.chrome(f"{button}.setAttribute('attention', 'severe');")
        self.addCleanup(self.m.chrome, f"{button}.removeAttribute('attention');")
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] == "toolbar", 10), self.window())
        self.assertTrue(self.settled(True)["toolbar"])
        self.m.chrome(f"{button}.setAttribute('attention', 'success');")  # a finished download is no warning
        self.assertTrue(harness.wait_until(lambda: self.window()["hold"] is None, 10), self.window())

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
        # The switch is in the settings page's Aparência pane, under the arrangement (ADR 0009, ADR 0011).
        settings_page.open_pane(self.m, "appearance")
        off = lambda now: now["shown"] and not now["pressed"] and not now["disabled"]  # noqa: E731
        settings_page.wait_control(self.m, "nulavio-immersive", off, timeout=15)
        marked = settings_page.DOC + 'return d.getElementById("nulavio-immersive").dataset.option;'
        self.assertEqual(self.m.chrome(marked), "immersive")
        settings_page.click(self.m, "#nulavio-immersive")
        pref = "return Services.prefs.getBoolPref('nulavio.layout.immersive', false);"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(pref), 10))
        # The settings page is the browser's own page: the mode applies while it is in front, as on any page.
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        settings_page.click(self.m, "#nulavio-immersive")
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(pref), 10))
        self.assertTrue(self.settled(True)["toolbar"])

    def test_09_the_security_cues_are_the_engines_with_the_mode_on(self):
        """The security-visibility matrix with Immersive on (ADR 0009's accepted exception, issue #118). Out of view,
        no cue is restyled and the band says who, how protected, which site and what the engine thinks of the
        connection; back in view, every cue is drawn exactly as with the mode off."""

        def cues() -> dict:
            return {cue["id"]: cue for cue in self.m.chrome(CUES)}

        def drawn(now: dict) -> dict:
            return {name: (cue.get("display"), cue.get("visibility"), cue.get("opacity")) for name, cue in now.items()}

        def sized(now: dict) -> dict:
            return {name: (cue.get("width"), cue.get("height"), cue.get("inside")) for name, cue in now.items()}

        # Off: the engine's own drawing, the reference.
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.assertTrue(self.settled(True)["toolbar"])
        reference = cues()
        self.assertTrue(reference["trust-icon-container"]["inside"], reference)
        # On, the toolbar away: nothing about a cue changed (the toolbar is moved and made transparent as a whole),
        # and the band carries what the address bar said.
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', true); gBrowser.selectedBrowser.focus();")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        self.assertEqual(drawn(cues()), drawn(reference))
        band = self.m.chrome(BAND)
        self.assertEqual(band["name"], "Imersivo", band)  # the profile
        self.assertTrue(band["protection"], band)  # its protection, in words
        self.assertEqual(band["host"], f"127.0.0.1:{self.server.port}", band)
        self.assertIn("localResource", band["engine"], band)  # the engine's verdict for this page...
        self.assertEqual((band["state"] or "", band["secure"]), ("", "true"), band)  # ...and the band's: no warning
        # On, the toolbar back by the keyboard: every cue as with the mode off, same place and size.
        self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
        self.assertTrue(self.settled(True)["toolbar"])
        back = cues()
        self.assertEqual(drawn(back), drawn(reference))
        self.assertEqual(sized(back), sized(reference))
        self.m.chrome("gBrowser.selectedBrowser.focus();")
        self.assertFalse(self.settled(False)["toolbar"])
        # A connection the engine calls not secure (plain http to a name that is not this computer): with the
        # toolbar away, the band says so in words, before the site's name.
        host = "nulavio-plain.test"
        self.m.chrome(
            "Services.prefs.setStringPref('network.dns.localDomains', arguments[0]);"
            "Services.prefs.setBoolPref('dom.security.https_only_mode', false);",
            [host],
        )
        self.addCleanup(
            self.m.chrome,
            "for (const n of ['network.dns.localDomains', 'dom.security.https_only_mode']) Services.prefs.clearUserPref(n);",
        )
        self.m.navigate(f"http://{host}:{self.server.port}/page/Imersivo")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(BAND)["host"] == f"{host}:{self.server.port}", 10))
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())
        self.assertFalse(self.settled(False)["toolbar"])
        plain = self.m.chrome(BAND)
        self.assertIn("notSecure", plain["engine"], plain)
        self.assertEqual(plain["secure"], "false", plain)
        words = "return WebExtensionPolicy.getByID('shell@nulavio.net').extension.localizeMessage(...arguments);"
        self.assertEqual(plain["state"], self.m.chrome(words, ["bandOriginNotSecure"]), plain)
        self.assertIn(self.m.chrome(words, ["bandOriginNamedNotSecure", [plain["host"]]]), plain["label"], plain)
        # The band follows the engine's verdict, read from the identity box: "verified" is fine, and "verified" by
        # an exception the person added is not (the engine draws a warning on that padlock). No test server has a
        # certificate, so the verdict is put on the box as the engine would write it.
        verdict = "document.getElementById('identity-box').className = arguments[0];"
        self.m.chrome(verdict, ["verifiedDomain"])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(BAND)["secure"] == "true", 6), self.m.chrome(BAND))
        self.assertFalse(self.m.chrome(BAND)["state"], "a verified site carries no warning in words")
        self.m.chrome(verdict, ["verifiedDomain mixedActiveBlocked"])
        self.assertEqual(self.m.chrome(BAND)["secure"], "true")
        self.m.chrome(verdict, ["verifiedDomain certUserOverridden"])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(BAND)["secure"] == "false", 6), self.m.chrome(BAND))
        self.assertEqual(self.m.chrome(BAND)["state"], plain["state"])
        self.m.chrome(verdict, [" ".join(plain["engine"])])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(BAND)["state"] == plain["state"], 6))
        away = cues()
        # And its warning in the address bar is the engine's, untouched, once the toolbar is back.
        self.m.chrome("document.getElementById('Browser:OpenLocation').doCommand();")
        self.assertTrue(self.settled(True)["toolbar"])
        warned = cues()
        self.assertTrue(warned["trust-icon-container"]["inside"], warned)
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.assertTrue(self.settled(True)["toolbar"])
        off = cues()
        self.assertEqual(drawn(away), drawn(off))
        self.assertEqual(drawn(warned), drawn(off))
        self.assertEqual(sized(warned), sized(off))

    def test_10_a_tab_being_restored_keeps_the_toolbar_until_its_document_is_there(self):
        """ADR 0009, decision 6: a restored preference alone hides nothing. A tab that session restore left unloaded
        shows its address as soon as it is selected, and its document only when the site answers: until then the
        page is still about:blank, and the band would name a site that is not there. The toolbar stays."""
        address = self.server.url("/page/Restaurada")
        self.m.chrome(HOLD, [address])
        self.addCleanup(self.m.chrome, RELEASE)
        self.addCleanup(
            self.m.chrome,
            "gBrowser.selectedTab = gBrowser.tabs[0];"
            " if (window.nvLazy) { gBrowser.removeTab(window.nvLazy); delete window.nvLazy; }",
        )
        self.m.chrome("window.nvLazy = gBrowser.addTrustedTab(arguments[0], { createLazyBrowser: true });", [address])
        self.assertTrue(self.window()["on"], "an unloaded tab in the background changes nothing")
        self.m.chrome("gBrowser.selectedTab = window.nvLazy;")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return Boolean(window.nvHeld.channel);"), 15), "not asked for")
        self.assertEqual(self.m.chrome(DOCUMENT), {"shown": address, "there": "about:blank"})
        waiting = self.settled(True)
        self.assertEqual((waiting["on"], waiting["off"], waiting["toolbar"]), (False, "page", True), waiting)
        # The site answers: its document is there, the band names it, and the mode applies.
        self.m.chrome("window.nvHeld.channel.resume(); window.nvHeld.channel = null;")
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 15), self.window())
        self.assertEqual(self.m.chrome(DOCUMENT), {"shown": address, "there": address})
        self.assertEqual(self.m.chrome(BAND)["host"], f"127.0.0.1:{self.server.port}")

    def test_11_an_error_page_keeps_the_full_window(self):
        """An error page keeps the address of what failed, and the document is the engine's own page about it: the
        band cannot say that site is what is on screen, so the toolbar stays."""
        refused = "http://127.0.0.1:1/"  # nothing listens there
        self.m.chrome(
            "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
            " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
            [refused],
        )
        failed = lambda: (self.m.chrome(DOCUMENT)["there"] or "").startswith("about:neterror")  # noqa: E731
        self.assertTrue(harness.wait_until(failed, 15), self.m.chrome(DOCUMENT))
        self.assertEqual(self.m.chrome(DOCUMENT)["shown"], refused)
        state = self.settled(True)
        self.assertEqual((state["on"], state["off"], state["toolbar"]), (False, "page", True), state)
        # The band's name for an IPv6 address has its brackets: without them its last group and a port read as one.
        self.m.chrome(
            "gBrowser.selectedBrowser.fixupAndLoadURIString(arguments[0],"
            " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
            ["http://[::1]:1/"],
        )
        named = "return document.querySelector('#nulavio-band .nv-band-origin-host').textContent;"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(named) == "[::1]:1", 15), self.m.chrome(named))
        self.m.navigate(self.page)
        self.assertTrue(harness.wait_until(lambda: self.window()["on"], 10), self.window())

    def test_12_a_notification_bar_keeps_the_toolbar_and_is_seen(self):
        """The engine's notification bars (a blocked pop-up, a page opened past a Safe Browsing warning) and the
        Guard's sit in a toolbar of their own under the address bar. Immersive takes the toolbars out of view: while
        one of those bars is shown, in the window or on the selected tab, they stay, and so does the bar."""
        seen = """
        const bar = document.getElementById("notifications-toolbar");
        const note = (arguments[0] === "window" ? gNotificationBox : gBrowser.getNotificationBox())
          .getNotificationWithValue("nulavio-test");
        const style = getComputedStyle(bar), box = note?.getBoundingClientRect();
        return { there: Boolean(note), opacity: style.opacity, events: style.pointerEvents,
                 inside: Boolean(box) && box.height > 0 && box.top >= 0 && box.bottom <= window.innerHeight };
        """
        show = """
        const box = arguments[0] === "window" ? gNotificationBox : gBrowser.getNotificationBox();
        box.appendNotification("nulavio-test", { label: "Nulavio test", priority: box.PRIORITY_WARNING_MEDIUM }, []);
        """
        close = """
        (arguments[0] === "window" ? gNotificationBox : gBrowser.getNotificationBox())
          .getNotificationWithValue("nulavio-test")?.close();
        """
        in_view = lambda bar: bar["inside"] and bar["opacity"] == "1"  # noqa: E731
        self.assertFalse(self.settled(False)["toolbar"])
        for where in ("window", "tab"):
            with self.subTest(where=where):
                self.addCleanup(self.m.chrome, close, [where])
                self.m.chrome(show, [where])
                state = self.settled(True)
                self.assertEqual((state["on"], state["toolbar"]), (True, True), state)
                self.assertTrue(harness.wait_until(lambda where=where: in_view(self.m.chrome(seen, [where])), 6))
                self.assertEqual(self.m.chrome(seen, [where])["events"], "auto")
                if where == "tab":
                    # A bar on a tab in the background holds nothing; back on its tab, it does again.
                    first = self.m.chrome("return gBrowser.tabs.indexOf(gBrowser.selectedTab);")
                    self.addCleanup(
                        self.m.chrome,
                        "if (window.nvOther) { gBrowser.removeTab(window.nvOther); delete window.nvOther; }",
                    )
                    self.m.chrome(
                        "window.nvOther = gBrowser.addTrustedTab(arguments[0]); gBrowser.selectedTab = window.nvOther;",
                        [self.server.url("/page/Outra")],
                    )
                    self.assertTrue(harness.wait_until(lambda: self.window()["on"], 15), self.window())
                    self.m.chrome("gBrowser.selectedBrowser.focus();")
                    self.assertFalse(self.settled(False)["toolbar"], "a bar on another tab kept this one's toolbar")
                    self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[arguments[0]];", [first])
                    self.assertTrue(self.settled(True)["toolbar"])
                self.m.chrome(close, [where])
                self.m.chrome("gBrowser.selectedBrowser.focus();")
                self.assertFalse(self.settled(False)["toolbar"], "the bar is gone and the toolbar stayed")


if __name__ == "__main__":
    unittest.main()
