"""Mozilla's AI features, account and promos are off in the Nulavio build (decisions D-UX7, D-UX8; audit AI-07, WCS-10).

The Nulavio assistant (ADR 0007) is the one AI path: Mozilla's chatbot must not
appear in the sidebar launcher, the page context menu or over a selection, and
the window carries no Mozilla account button, Sync promo or Mozilla tiles. Runs
on a registered profile of the Nulavio build, with the build's own defaults
(firefox-branding.js and distribution.ini), as a person starts it.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

GENAI = 'ChromeUtils.importESModule("moz-src:///browser/components/genai/GenAI.sys.mjs").GenAI'

LAUNCHER = """
const done = arguments[arguments.length - 1];
(async () => {
  await SidebarController.promiseInitialized;
  // With tabs on top the launcher shows while a sidebar panel is open (sidebar.visibility "hide-on-close").
  await SidebarController.show("viewBookmarksSidebar");
  await new Promise(r => setTimeout(r, 500));
  const main = document.querySelector("sidebar-main");
  await main.updateComplete;
  const deep = (root, out = []) => {
    for (const el of root.querySelectorAll("*")) {
      if (el.localName === "moz-button" && el.getAttribute("view")) out.push(el);
      if (el.shadowRoot) deep(el.shadowRoot, out);
    }
    return out;
  };
  const shown = deep(main.shadowRoot).filter(b => !b.hidden && getComputedStyle(b).display !== "none");
  return {
    views: shown.map(b => b.getAttribute("view")),
    vertical: SidebarController.sidebarVerticalTabsEnabled,
    tools: Services.prefs.getStringPref("sidebar.main.tools", ""),
  };
})().finally(() => SidebarController.hide()).then(done, e => done({ error: String(e) }));
"""

CONTEXT_MENU = """
const menu = document.getElementById("contentAreaContextMenu");
const item = document.getElementById("context-ask-chat");
return { open: menu.state === "open", askChat: item ? !item.hidden : false,
         labels: [...menu.children].filter(e => !e.hidden && e.localName !== "menuseparator").map(e => e.id) };
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults (NULAVIO_ENGINE)")
class MozillaFeaturesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def chrome_async(self, script: str, args=()):
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(script, list(args))
        finally:
            self.m.set_context("content")

    def launcher(self) -> dict:
        result = self.chrome_async(LAUNCHER)
        self.assertNotIn("error", result, result)
        return result

    def test_01_ai_prefs_are_build_defaults_not_user_values(self):
        names = [
            "browser.ml.chat.enabled",
            "browser.ml.chat.menu",
            "browser.ml.chat.page",
            "browser.ml.chat.shortcuts",
            "browser.ai.control.sidebarChatbot",
            "browser.ai.control.smartTabGroups",
            "browser.ai.control.linkPreviewKeyPoints",
            "browser.ai.control.smartWindow",
            "browser.tabs.groups.smart.enabled",
            "browser.ml.linkPreview.enabled",
            "extensions.ml.enabled",
            "nimbus.rollouts.enabled",
            "identity.fxaccounts.enabled",
            "browser.aboutaddons.novaThemesPickerEnabled",
        ]
        state = self.m.chrome(
            "const out = {}; const d = Services.prefs.getDefaultBranch('');"
            "for (const n of arguments[0]) { const t = d.getPrefType(n);"
            " out[n] = {value: t === 128 ? d.getBoolPref(n) : t === 32 ? d.getStringPref(n) : null,"
            " user: Services.prefs.prefHasUserValue(n)}; } return out;",
            [names],
        )
        for name in names:
            with self.subTest(pref=name):
                expected = "blocked" if name.startswith("browser.ai.control.") else False
                self.assertEqual(state[name], {"value": expected, "user": False})
        # What Firefox's own AI controls read: every Mozilla AI feature reports itself blocked or off.
        features = self.m.chrome(
            f"const G = {GENAI};"
            "const {AIWindow} = ChromeUtils.importESModule('moz-src:///browser/components/aiwindow/ui/modules/AIWindow.sys.mjs');"
            "return {chatbot: G.isBlocked, smartWindow: AIWindow.isBlocked, smartWindowOn: AIWindow.isEnabled};"
        )
        self.assertEqual(features, {"chatbot": True, "smartWindow": True, "smartWindowOn": False})

    def test_02_no_chatbot_in_the_sidebar_launcher(self):
        for vertical in (False, True):
            with self.subTest(vertical_tabs=vertical):
                self.m.chrome("Services.prefs.setBoolPref('sidebar.verticalTabs', arguments[0]);", [vertical])
                self.assertTrue(harness.wait_until(lambda v=vertical: self.launcher()["vertical"] == v, 10))
                time.sleep(0.5)
                state = self.launcher()
                self.assertNotIn("viewGenaiChatSidebar", state["views"], state)
                self.assertNotIn("aichat", state["tools"].split(","))
                # "Tabs from other devices" needs a Mozilla account, which the build does not offer.
                self.assertNotIn("viewTabsSidebar", state["views"], state)
                self.assertIn("shell_nulavio_net-sidebar-action", state["views"], "the Nulavio assistant is the AI entry")
        self.m.chrome("Services.prefs.clearUserPref('sidebar.verticalTabs');")

    def test_03_no_chatbot_in_the_page_context_menu_or_over_a_selection(self):
        self.m.navigate(self.server.url("/page/context-menu"))
        self.m.execute(
            "const r = document.createRange(); r.selectNodeContents(document.getElementById('name'));"
            "getSelection().removeAllRanges(); getSelection().addRange(r);"
        )
        target = self.m.find_element("#name")
        self.m.send(
            "WebDriver:PerformActions",
            {
                "actions": [
                    {
                        "type": "pointer",
                        "id": "mouse",
                        "parameters": {"pointerType": "mouse"},
                        "actions": [
                            {"type": "pointerMove", "origin": {"element-6066-11e4-a52e-4f735466cecf": target}, "x": 0, "y": 0},
                            {"type": "pointerDown", "button": 2},
                            {"type": "pointerUp", "button": 2},
                        ],
                    }
                ]
            },
        )
        self.m.send("WebDriver:ReleaseActions")
        opened = harness.wait_until(lambda: self.m.chrome(CONTEXT_MENU)["open"], 10)
        try:
            self.assertTrue(opened, "the page context menu did not open")
            menu = self.m.chrome(CONTEXT_MENU)
            self.assertFalse(menu["askChat"], menu)
            self.assertIn("context-copy", menu["labels"])  # the selection menu, as a person sees it
        finally:
            self.m.chrome("document.getElementById('contentAreaContextMenu').hidePopup();")
        entry = self.m.chrome(
            f"const G = {GENAI}; const b = gBrowser.selectedBrowser;"
            "return {page: G.canShowAskChat(b, 'page', null, {text: 'context-menu'}),"
            " tab: G.canShowAskChat(b, 'tab', [gBrowser.selectedTab], null), selectionShortcut: G.canShowAIAction};"
        )
        self.assertEqual(entry, {"page": False, "tab": False, "selectionShortcut": False})

    def test_03b_no_region_lookup_at_mozilla(self):
        """The build asks no location service for the country: with no address to ask, the lookup ends without a request."""
        state = self.chrome_async(
            "const done = arguments[arguments.length - 1];"
            'const { Region } = ChromeUtils.importESModule("resource://gre/modules/Region.sys.mjs");'
            "const hosts = [];"
            "const watch = { observe(channel) { hosts.push(channel.QueryInterface(Ci.nsIHttpChannel).URI.host); } };"
            'Services.obs.addObserver(watch, "http-on-opening-request");'
            "(async () => { await Region._fetchRegion(); return {"
            ' url: Services.urlFormatter.formatURLPref("browser.region.network.url"),'
            ' update: Services.prefs.getBoolPref("browser.region.update.enabled"),'
            ' userSet: ["network.url", "update.enabled"].filter(n => Services.prefs.prefHasUserValue(`browser.region.${n}`)),'
            ' asked: hosts.filter(h => h.includes("location.services")),'
            " home: Region.home,"
            "}; })()"
            '.finally(() => Services.obs.removeObserver(watch, "http-on-opening-request"))'
            ".then(done, e => done({ error: String(e) }));"
        )
        self.assertEqual(state, {"url": "", "update": False, "userSet": [], "asked": [], "home": None})

    def test_03c_no_question_to_google_about_a_drm_module_that_is_off(self):
        """The media plugin check reads the list Mozilla serves and stops there: nothing is asked of Google's component
        update service about the Widevine module (issue #103). DRM stays the engine's switch, off in a new profile."""
        state = self.chrome_async(
            "const done = arguments[arguments.length - 1];"
            'const { GMPInstallManager } = ChromeUtils.importESModule("resource://gre/modules/GMPInstallManager.sys.mjs");'
            'const guid = Services.prefs.getStringPref("media.gmp-widevinecdm.chromium-guid", "");'
            "const asked = [];"
            "const watch = { observe(channel) { const uri = channel.QueryInterface(Ci.nsIHttpChannel).URI;"
            ' if (uri.host === "update.googleapis.com" || (guid && uri.spec.includes(guid))) asked.push(uri.host); } };'
            'Services.obs.addObserver(watch, "http-on-opening-request");'
            "(async () => { const { addons } = await new GMPInstallManager().checkForAddons(); return {"
            ' listed: addons.some(a => a.id === "gmp-widevinecdm"),'
            " asked,"
            ' allowed: Services.prefs.getBoolPref("media.gmp-widevinecdm.allow-chromium-update"),'
            ' userSet: Services.prefs.prefHasUserValue("media.gmp-widevinecdm.allow-chromium-update"),'
            ' drm: Services.prefs.getBoolPref("media.eme.enabled"),'
            ' installed: Services.prefs.getStringPref("media.gmp-widevinecdm.version", ""),'
            "}; })()"
            '.finally(() => Services.obs.removeObserver(watch, "http-on-opening-request"))'
            ".then(done, e => done({ error: String(e) }));"
        )
        if state.get("listed") is False:
            self.skipTest("the media plugin list did not name Widevine, so the check had nothing to ask about (network?)")
        self.assertEqual(state, {"listed": True, "asked": [], "allowed": False, "userSet": False, "drm": False, "installed": ""})

    def test_04_no_account_button_or_sync_promo(self):
        state = self.m.chrome(
            "const b = document.getElementById('fxa-toolbar-menu-button');"
            "return {button: b ? b.getBoundingClientRect().width : 0,"
            " disabled: document.documentElement.getAttribute('fxadisabled')};"
        )
        self.assertEqual(state, {"button": 0, "disabled": "true"})
        self.m.chrome("PanelUI.show();")
        try:
            self.assertTrue(harness.wait_until(lambda: self.m.chrome("return PanelUI.panel.state;") == "open", 10))
            promos = self.m.chrome(
                "return [...document.getElementById('appMenu-mainView').querySelectorAll('[id]')]"
                ".filter(e => /fxa|sync|signin/i.test(e.id) && e.getBoundingClientRect().height > 0).map(e => e.id);"
            )
            self.assertEqual(promos, [], "account or Sync entries in the app menu")
        finally:
            self.m.chrome("PanelUI.hide();")

    def test_05_engine_home_page_has_no_mozilla_tiles(self):
        self.m.navigate("about:home")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return !!document.querySelector('.top-sites-list');"), 30))
        time.sleep(2)  # the list fills in after the page appears
        tiles = self.m.execute(
            "return [...document.querySelectorAll('.top-site-outer:not(.add-button-tile) a')].map(a => a.href);"
        )
        self.assertEqual(tiles, [], "default shortcuts (Add-ons for Firefox and others) on the engine's home page")


if __name__ == "__main__":
    unittest.main()
