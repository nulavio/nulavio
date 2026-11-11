"""ADR 0008: one settings page. Nulavio's options are native groups inside the engine's about:preferences."""

from __future__ import annotations

import unittest

import harness

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
# The navigation as a person sees it, and whether Nulavio's part is in.
NAV = (
    DOC
    + """
return {
  extended: d.documentElement.getAttribute("nulavio-settings"),
  nav: [...d.querySelectorAll("#categories moz-page-nav-button[view]")]
    .filter(b => !b.classList.contains("hidden-category") && !b.hidden && b.getBoundingClientRect().height > 0)
    .map(b => b.id),
  general: d.getElementById("category-sync")?.getAttribute("data-l10n-id"),
};
"""
)
# The groups a pane shows, in order, after going to it the way a click on the navigation does.
GROUPS = (
    DOC
    + """
const [view] = arguments;
if (w.gLastCategory?.category !== view) { w.gotoPref(view); return null; }
const pane = [...d.querySelectorAll("setting-pane")].find(p => !p.hidden && p.getBoundingClientRect().height > 0);
const groups = pane ? [...pane.querySelectorAll("setting-group")].map(g => g.getAttribute("groupid")) : [];
return groups.length ? groups : null;
"""
)
# A control as the engine's widgets drew it: its words, value and state.
CONTROL = (
    DOC
    + """
const el = d.querySelector(arguments[0]);
if (!el) return null;
const holder = el.closest("setting-control");
return {
  label: el.label ?? null, description: el.description ?? null, message: el.message ?? null,
  value: el.value ?? null, pressed: el.pressed ?? null, disabled: Boolean(el.disabled),
  shown: !(holder?.hidden) && el.getBoundingClientRect().height > 0,
};
"""
)
RELATED = DOC + 'return [...d.querySelectorAll("#relatedSettingsBoxGroup moz-box-link")].map(link => link.href);'
ENGINE_APPEARANCE = ["appearance", "browserTheme", "windowDensity", "relatedSettings"]
# The engine's stock navigation, as the alpha shows it (accounts and Labs are off there).
ENGINE_NAV = [
    "category-sync",
    "category-home",
    "category-search",
    "category-privacy",
    "category-passwords-autofill",
    "category-appearance",
    "category-downloads",
    "category-tabs-browsing",
]
JOURNEY_NAV = [
    "category-sync",
    "category-appearance",
    "category-nulavio-profiles",
    "category-privacy",
    "category-passwords-autofill",
    "category-search",
    "category-nulavio-assistant",
    "category-ai-features",
    "category-tabs-browsing",
    "category-home",
    "category-downloads",
]
# Makes the page's group registry throw on one of Nulavio's groups, after several were added: the
# window's capture listener runs before the Shell's own DOMContentLoaded listener on the document.
BREAK_HALFWAY = """
const breaker = {
  observe(win) {
    let uri; try { uri = win.document.documentURIObject; } catch { return; }
    if (!uri?.schemeIs("about") || uri.filePath !== "preferences") return;
    win.addEventListener("DOMContentLoaded", () => {
      const { SettingGroupManager } = win.ChromeUtils.importESModule(
        "chrome://browser/content/preferences/config/SettingGroupManager.mjs", { global: "current" });
      const real = SettingGroupManager.registerGroup;
      SettingGroupManager.registerGroup = function (id, config) {
        if (id === "nulavioProtections") throw new Error("test: the registry broke halfway");
        return real.call(this, id, config);
      };
    }, { capture: true, once: true });
  },
};
Services.obs.addObserver(breaker, "chrome-document-global-created");
window.__nulavioBreaker = breaker;
"""
UNBREAK = (
    'Services.obs.removeObserver(window.__nulavioBreaker, "chrome-document-global-created"); delete window.__nulavioBreaker;'
)
LEFTOVERS = (
    DOC
    + """
const here = { global: "current" };
const config = "chrome://browser/content/preferences/config/";
const { SettingGroupManager } = w.ChromeUtils.importESModule(config + "SettingGroupManager.mjs", here);
const { SettingPaneManager } = w.ChromeUtils.importESModule(config + "SettingPaneManager.mjs", here);
const { Preferences } = w.ChromeUtils.importESModule("chrome://global/content/preferences/Preferences.mjs", here);
const ours = keys => [...keys].filter(k => /^nulavio/i.test(k));
return {
  groups: ours(SettingGroupManager._data.keys()), panes: ours(SettingPaneManager._data.keys()),
  settings: ours(Preferences._settings.keys()),
  nodes: [...d.querySelectorAll('[id^="category-nulavio"], setting-pane[data-category^="paneNulavio"]')].length,
};
"""
)


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class NativeSettingsTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="NativeSettings")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def open(self, address: str = "about:preferences#appearance"):
        self.m.chrome(f'gBrowser.selectedTab = gBrowser.addTrustedTab("{address}");')
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20), address)
        return self.m.chrome(NAV)

    def groups(self, view: str) -> list[str]:
        found = harness.wait_until(lambda: self.m.chrome(GROUPS, [view]), 20)
        self.assertTrue(found, view)
        return found

    def control(self, selector: str, wanted=lambda state: state["shown"]) -> dict:
        harness.wait_until(lambda: wanted(self.m.chrome(CONTROL, [selector]) or {"shown": False}), 15)
        state = self.m.chrome(CONTROL, [selector])
        self.assertIsNotNone(state, selector)
        return state

    def test_01_one_page_in_the_order_of_the_journey(self):
        page = self.open()
        self.assertEqual(page["extended"], "1")
        # The navigation: settle in, how it looks, who you are, what protects you, what helps, how you browse.
        self.assertEqual(page["nav"][: len(JOURNEY_NAV)], JOURNEY_NAV, page)
        self.assertLess(page["nav"].index("category-nulavio-integrations"), page["nav"].index("category-about-firefox"), page)
        # The seam (a pane edited as the page registers it): ours first, the engine's all still there, in their order.
        appearance = self.groups("paneAppearance")
        self.assertEqual(appearance[0], "nulavioLayout", appearance)
        self.assertEqual([g for g in appearance if g in ENGINE_APPEARANCE], ENGINE_APPEARANCE, appearance)
        self.assertLess(appearance.index("windowDensity"), appearance.index("nulavioLook"), appearance)
        items = self.m.chrome(
            DOC + 'return [...d.querySelectorAll("#nulavio-layout moz-visual-picker-item")].map(i => [i.value, i.label]);'
        )
        self.assertEqual(items, [["lateral", "Lateral"], ["top", "Abas no topo"], ["focus", "Foco"]])

    def test_01b_engine_panes_keep_their_groups_and_gain_nulavios_next_to_them(self):
        self.open()
        privacy = self.groups("panePrivacy")
        self.assertEqual(privacy[privacy.index("etpStatus") + 1], "nulavioProtections", privacy)
        # A protection pane loses nothing and keeps its order.
        engine_privacy = [g for g in privacy if not g.startswith("nulavio")]
        self.assertEqual(engine_privacy[:3], ["securityPrivacyStatus", "securityPrivacyWarnings", "etpStatus"], privacy)
        self.assertIn("dnsOverHttps", engine_privacy)
        self.assertIn("cookiesAndSiteData2", engine_privacy)
        passwords = self.groups("panePasswordsAutofill")
        self.assertEqual(passwords[:2], ["nulavioPasswordManager", "passwords"], passwords)
        search = self.groups("paneSearch")
        self.assertEqual(search[:2], ["defaultEngine", "nulavioSearch"], search)
        # One arrangement control: the engine's two-way picker gives way to a pointer to Aparência; its other groups stay.
        tabs = self.groups("paneTabsBrowsing")
        self.assertEqual(tabs[0], "nulavioLayoutMoved", tabs)
        self.assertNotIn("browserLayout", tabs)
        self.assertEqual(tabs[tabs.index("keyboardShortcuts") + 1], "nulavioShortcuts", tabs)
        for group in ("tabs", "pageNavigation", "media", "performance"):
            self.assertIn(group, tabs)
        self.m.chrome(DOC + 'd.querySelector("#nulavio-layout-moved").click();')
        self.assertEqual(self.groups("paneAppearance")[0], "nulavioLayout")
        # ...and Aparência no longer sends people to that pane "for the layout": the two would point at each other.
        self.assertEqual(self.m.chrome(RELATED), ["about:preferences#accessibility", "about:preferences#home"])
        # The engine's first pane: its own "Perfis" entry gives way to the profiles pane.
        general = self.groups("paneSync")
        self.assertNotIn("profiles", general)
        self.assertIn("defaultBrowserSync", general)
        self.assertEqual(self.groups("paneNulavioProfiles"), ["nulavioHere", "nulavioProfilesManage"])

    def test_02_the_card_changes_the_real_layout(self):
        self.open()
        self.assertEqual(self.control("#nulavio-layout", lambda s: s.get("value") == "lateral")["value"], "lateral")
        self.assertTrue(self.m.chrome('return Services.prefs.getBoolPref("sidebar.verticalTabs");'))
        self.m.chrome(
            DOC + '[...d.querySelectorAll("#nulavio-layout moz-visual-picker-item")].find(item => item.value === "top").click();'
        )
        harness.wait_until(lambda: not self.m.chrome('return Services.prefs.getBoolPref("sidebar.verticalTabs");'), 10)
        self.assertEqual(self.control("#nulavio-layout", lambda s: s.get("value") == "top")["value"], "top")

    def test_02b_the_immersive_switch_sits_under_the_layout_and_writes_through_the_layout_module(self):
        self.open()
        pref = 'return Services.prefs.getBoolPref("nulavio.layout.immersive", false);'
        self.addCleanup(self.m.chrome, 'Services.prefs.clearUserPref("nulavio.layout.immersive");')
        switch = self.control("#nulavio-immersive")
        self.assertEqual((switch["label"], switch["pressed"], switch["disabled"]), ("Imersivo", False, False), switch)
        self.assertEqual(
            self.m.chrome(DOC + 'return d.querySelector("#nulavio-immersive").closest("setting-group").getAttribute("groupid");'),
            "nulavioLayout",
        )
        self.m.chrome(DOC + 'd.querySelector("#nulavio-immersive").click();')
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(pref), 10))
        # Changed from elsewhere (the key): the switch follows.
        self.m.chrome('Services.prefs.setBoolPref("nulavio.layout.immersive", false);')
        self.assertFalse(self.control("#nulavio-immersive", lambda s: s.get("pressed") is False)["pressed"])

    def test_03_words_come_in_english_too(self):
        self.m.chrome('Services.locale.requestedLocales = ["en-US"];')
        self.m = self.session.restart()
        self.open()
        items = self.m.chrome(DOC + 'return [...d.querySelectorAll("#nulavio-layout moz-visual-picker-item")].map(i => i.label);')
        self.assertEqual(items, ["Lateral", "Tabs on top", "Focus"])
        self.groups("paneNulavioProfiles")
        self.assertEqual(self.control("#nulavio-open-routing")["label"], "Which site opens in which profile")

    def test_04_a_failure_halfway_leaves_the_engines_page(self):
        self.m.chrome(BREAK_HALFWAY)
        try:
            page = self.open()
            # Nothing of Nulavio's is left, and nothing of the engine's is missing or moved.
            self.assertIsNone(page["extended"], page)
            self.assertEqual(page["nav"][: len(ENGINE_NAV)], ENGINE_NAV, page)
            self.assertEqual(page["general"], "pane-account-sync-title2", page)
            self.assertEqual(self.m.chrome(LEFTOVERS), {"groups": [], "panes": [], "settings": [], "nodes": 0})
            appearance = self.groups("paneAppearance")
            self.assertEqual([g for g in appearance if g in ENGINE_APPEARANCE], ENGINE_APPEARANCE, appearance)
            self.assertFalse([g for g in appearance if g.startswith("nulavio")], appearance)
            self.assertIn("about:preferences#tabsBrowsing", self.m.chrome(RELATED))
            self.assertEqual(self.groups("paneTabsBrowsing")[0], "browserLayout")
            self.assertIn("profiles", self.groups("paneSync"))
        finally:
            self.m.chrome(UNBREAK)
        # The next page load, with the registry whole again, has Nulavio's part.
        self.assertEqual(self.open()["extended"], "1")

    def test_05_the_alias_a_reload_a_second_window_and_coming_back(self):
        for address in ("about:settings#appearance", "about:preferences"):
            page = self.open(address)
            self.assertEqual((page["extended"], page["nav"][:3]), ("1", JOURNEY_NAV[:3]), address)
        self.m.chrome("gBrowser.selectedBrowser.reload();")
        self.m.chrome("return new Promise(resolve => setTimeout(resolve, 600));")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        self.assertEqual(self.m.chrome(NAV)["extended"], "1")
        # Away and back in the same tab (whether or not the engine kept the page).
        self.m.chrome(
            "const triggeringPrincipal = Services.scriptSecurityManager.getSystemPrincipal();"
            'gBrowser.selectedBrowser.fixupAndLoadURIString("about:license", { triggeringPrincipal });'
        )
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome('return gBrowser.selectedBrowser.currentURI.spec === "about:license";'), 15)
        )
        self.m.chrome("gBrowser.selectedBrowser.goBack();")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY) and self.m.chrome(NAV)["extended"] == "1", 20))
        self.assertEqual(self.groups("paneAppearance")[0], "nulavioLayout")
        # A second window: its page follows that window's layout, not the first one's.
        second = self.m.chrome("""
          const win = window.OpenBrowserWindow();
          return new Promise(resolve => win.addEventListener("load", () => resolve(true), { once: true }));
        """)
        self.assertTrue(second)
        script = """
          const win = [...Services.wm.getEnumerator("navigator:browser")].find(w => w !== window);
          const [action] = arguments;
          const tab = win.gBrowser.selectedTab;
          if (action === "open") {
            win.gBrowser.selectedTab = win.gBrowser.addTrustedTab("about:preferences#appearance");
            return true;
          }
          const d = win.gBrowser.selectedBrowser.contentDocument;
          const picker = d?.querySelector("#nulavio-layout");
          if (action === "value") return picker?.value || null;
          if (action === "pick") {
            [...picker.querySelectorAll("moz-visual-picker-item")].find(i => i.value === "focus").click();
            return true;
          }
        """
        self.m.chrome(script, ["open"])
        self.assertEqual(harness.wait_until(lambda: self.m.chrome(script, ["value"]), 20), "lateral")
        self.m.chrome(script, ["pick"])
        self.assertEqual(harness.wait_until(lambda: self.m.chrome(script, ["value"]) == "focus" and "focus", 15), "focus")
        # The first window's page shows the same choice: the layout is the profile's.
        self.assertEqual(self.control("#nulavio-layout", lambda s: s.get("value") == "focus")["value"], "focus")

    def test_06_what_is_true_now_is_read_and_a_failed_read_says_so(self):
        self.m.chrome('Services.prefs.setBoolPref("signon.rememberSignons", true);')
        self.open()
        self.groups("paneNulavioProfiles")
        here = self.control("#nulavio-here", lambda s: s.get("shown") and s.get("label"))
        self.assertEqual(here["label"], "NativeSettings", here)
        self.assertIn("Sem senha", here["description"], here)
        self.assertFalse(self.m.chrome(CONTROL, ["#nulavio-here-failed"])["shown"])
        self.groups("panePasswordsAutofill")
        self.assertEqual(self.control("#nulavio-passwords-now")["label"], "Em uso: o gerenciador do próprio navegador")
        # The engine's own checkbox, in the group below, changes the answer above it.
        self.m.chrome('Services.prefs.setBoolPref("signon.rememberSignons", false);')
        none = self.control("#nulavio-passwords-now", lambda s: s.get("label") == "Nenhum gerenciador ligado")
        self.assertEqual(none["label"], "Nenhum gerenciador ligado", none)
        self.groups("panePrivacy")
        self.assertEqual(self.control("#nulavio-guard-review")["description"], "Nada para rever.")
        self.groups("paneTabsBrowsing")
        key = self.control("#nulavio-key-toggle-immersive", lambda s: s.get("shown") and s.get("description"))
        self.assertEqual(key["description"], "Ctrl+Alt+I", key)
        self.assertFalse(self.m.chrome(CONTROL, ["#nulavio-keys-reset"])["shown"])

        # A read that fails: the controls behind it are not drawn, and the group says so in words.
        broken = """
          const { NulavioPersonalise } = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs");
          if (arguments[0]) {
            window.__nulavioState = NulavioPersonalise.state;
            NulavioPersonalise.state = () => Promise.reject(new Error("test: unreadable"));
          }
          else { NulavioPersonalise.state = window.__nulavioState; }
        """
        self.m.chrome(broken, [True])
        self.addCleanup(self.m.chrome, broken, [False])
        self.open()
        self.groups("paneAppearance")
        note = self.control("#nulavio-look-failed")
        self.assertTrue(note["shown"], note)
        self.assertIn("Não foi possível ler", note["message"], note)
        for control in ("#nulavio-accent", "#nulavio-more-contrast", "#nulavio-reduce-transparency"):
            self.assertFalse(self.m.chrome(CONTROL, [control])["shown"], control)
        # The layout was read: its card is unaffected.
        self.assertEqual(self.control("#nulavio-layout", lambda s: s.get("value") == "lateral")["value"], "lateral")

    def test_07_every_way_in_leads_to_the_one_page(self):
        where = "return gBrowser.selectedBrowser.currentURI.spec;"
        host = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSettings.sys.mjs").NulavioSettings'
        # A section of the old page names its pane; an unknown name opens nothing.
        self.m.chrome(f'{host}.openFor(window, "layout");')
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(where) == "about:preferences#appearance", 15), self.m.chrome(where)
        )
        refused = self.m.chrome(
            f'try {{ {host}.openFor(window, "https://example.org/"); return "opened"; }} catch (e) {{ return e.code; }}'
        )
        self.assertEqual(refused, "invalid-section")
        tabs = self.m.chrome("return gBrowser.tabs.length;")
        # Asked again, the settings tab is reused, at the pane asked for.
        self.m.chrome(f'{host}.openFor(window, "passwords");')
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(where) == "about:preferences#passwordsAutofill", 15), self.m.chrome(where)
        )
        self.assertEqual(self.m.chrome("return gBrowser.tabs.length;"), tabs)

        # From the settings page to a detail page and back, in the same tab.
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        self.groups("paneNulavioProfiles")
        self.control("#nulavio-open-routing")
        self.m.chrome(DOC + 'd.querySelector("#nulavio-open-routing").click();')
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(where).endswith("/settings/settings.html#routing"), 15), self.m.chrome(where)
        )
        for handle in self.m.window_handles():
            self.m.switch_to(handle)
            if self.m.current_url().endswith("/settings/settings.html#routing"):
                break
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 20)
        )
        rail = self.m.execute(
            "return [...document.querySelectorAll('.settings-nav a[data-section]')].map(a => a.dataset.section);"
        )
        for moved in ("layout", "appearance", "shortcuts"):
            self.assertNotIn(moved, rail)
        self.assertEqual(self.m.execute("return document.getElementById('settings-back').textContent;"), "Configurações")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#settings-back")})
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(where) == "about:preferences#nulavioProfiles", 15), self.m.chrome(where)
        )
        self.assertEqual(self.m.chrome("return gBrowser.tabs.length;"), tabs)


if __name__ == "__main__":
    unittest.main()
