"""ADR 0008: one settings page. Nulavio's options are native groups inside the engine's about:preferences."""

from __future__ import annotations

import time
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
    "category-ai-features",
    "category-tabs-browsing",
    "category-home",
    "category-downloads",
]
# Makes the page throw while Nulavio's part is being added; the window's capture listener runs before the
# Shell's own DOMContentLoaded listener on the document. "group": the group registry refuses one of Nulavio's
# groups, after several settings and groups were added. "pane": the page's own register_module throws AFTER
# doing its work for Nulavio's second pane, when the wrapper, a pane and its navigation entry are already in.
BREAK_HALFWAY = """
const [where] = arguments;
const breaker = {
  observe(win) {
    let uri; try { uri = win.document.documentURIObject; } catch { return; }
    if (!uri?.schemeIs("about") || uri.filePath !== "preferences") return;
    win.addEventListener("DOMContentLoaded", () => {
      if (where === "group") {
        const { SettingGroupManager } = win.ChromeUtils.importESModule(
          "chrome://browser/content/preferences/config/SettingGroupManager.mjs", { global: "current" });
        const real = SettingGroupManager.registerGroup;
        SettingGroupManager.registerGroup = function (id, config) {
          if (id === "nulavioProtections") throw new Error("test: the registry broke halfway");
          return real.call(this, id, config);
        };
      } else {
        const real = win.register_module;
        win.register_module = function (name, module) {
          real.call(this, name, module);
          if (name === "paneNulavioIntegrations") throw new Error("test: the page broke after registering a pane");
        };
      }
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
  // What the page itself keeps for a pane (its search runs every init it finds), the pane elements, the
  // navigation entries and the link to Nulavio's words.
  inits: [...w.gCategoryInits.keys(), ...w.gCategoryModules.keys()].filter(k => /^paneNulavio/.test(k)),
  nodes: [...d.querySelectorAll('[id^="category-nulavio"]')].length
    + [...d.querySelectorAll("setting-pane")].filter(pane => /^paneNulavio/.test(pane.name)).length,
  words: [...d.querySelectorAll('link[rel="localization"]')].map(link => link.getAttribute("href"))
    .filter(href => href.startsWith("nulavio/")).length,
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
        self.assertTrue(wanted(state), (selector, state))
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
        # Nulavio's two groups sit right after the engine's groups on the same subject.
        self.assertEqual(search[search.index("searchShortcuts") + 1], "nulavioSearchAdd", search)
        self.assertEqual(search[search.index("searchSuggestions") + 1], "nulavioSearch", search)
        # One arrangement control: the engine's two-way picker gives way to a pointer to Aparência; its other groups stay.
        tabs = self.groups("paneTabsBrowsing")
        self.assertEqual(tabs[0], "nulavioLayoutMoved", tabs)
        self.assertNotIn("browserLayout", tabs)
        self.assertEqual(tabs[tabs.index("keyboardShortcuts") + 1], "nulavioShortcuts", tabs)
        for group in ("tabs", "pageNavigation", "media", "performance"):
            self.assertIn(group, tabs)
        self.m.chrome(DOC + 'd.querySelector("#nulavio-layout-moved").click();')
        self.assertEqual(self.groups("paneAppearance")[0], "nulavioLayout")
        # The engine's old address of its picker still lands on something: the pointer keeps the target's name.
        self.assertEqual(
            self.m.chrome(DOC + 'return d.querySelector("#nulavio-layout-moved").closest("setting-group").dataset.subcategory;'),
            "layout",
        )
        # ...and Aparência no longer sends people to that pane "for the layout": the two would point at each other.
        self.assertEqual(self.m.chrome(RELATED), ["about:preferences#accessibility", "about:preferences#home"])
        # The engine's first pane: its own "Perfis" entry gives way to the profiles pane.
        general = self.groups("paneSync")
        self.assertNotIn("profiles", general)
        self.assertIn("defaultBrowserSync", general)
        self.assertEqual(self.groups("paneNulavioProfiles"), ["nulavioHere", "nulavioProfilesManage", "nulavioRouting"])

    def test_01c_the_assistant_and_the_engines_ai_controls_are_one_pane(self):
        label = DOC + "return d.getElementById(arguments[0])?.textContent.trim() ?? null;"
        self.open()
        # Where the engine shows its AI pane: Nulavio's assistant first in it, under one name, every control kept.
        ai = self.groups("paneAi")
        self.assertEqual(ai[0], "nulavioAssistantEntry", ai)
        self.assertIn("aiFeatures", ai)
        self.assertNotIn("aiControlsDescription", ai)
        self.assertEqual(self.m.chrome(label, ["category-ai-features"]), "Assistente e IA")
        self.assertIsNone(self.m.chrome(label, ["category-nulavio-assistant"]))
        host = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSettings.sys.mjs").NulavioSettings'
        where = "return gBrowser.selectedBrowser.currentURI.spec;"
        self.m.chrome(f'{host}.openFor(window, "ai");')
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(where) == "about:preferences#ai", 15), self.m.chrome(where))
        # Where it does not (read when the page is built), the assistant has a pane of its own.
        self.m.chrome('Services.prefs.setBoolPref("browser.preferences.aiControls", false);')
        self.addCleanup(self.m.chrome, 'Services.prefs.clearUserPref("browser.preferences.aiControls");')
        self.m.chrome("gBrowser.removeTab(gBrowser.selectedTab);")  # the page built before the change keeps its panes
        page = self.open("about:preferences")
        self.assertIn("category-nulavio-assistant", page["nav"])
        self.assertNotIn("category-ai-features", page["nav"])
        self.assertEqual(self.groups("paneNulavioAssistant"), ["nulavioAssistantEntry"])
        self.m.chrome(f'{host}.openFor(window, "ai");')
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(where) == "about:preferences#nulavioAssistant", 15), self.m.chrome(where)
        )

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
        # The page's own words (Fluent) and the Shell's messages for the actions, both in English.
        heading = (
            DOC
            + """const group = d.querySelector('setting-group[groupid="nulavioRouting"]');"""
            + """return group?.querySelector("moz-fieldset")?.label ?? null;"""
        )
        self.assertEqual(harness.wait_until(lambda: self.m.chrome(heading), 15), "Which site opens in which profile")
        self.assertEqual(self.control("#nulavio-routing-enabled", lambda s: s.get("label"))["label"], "Use routing rules")
        self.assertEqual(self.control("#nulavio-profile-new-create", lambda s: s.get("label"))["label"], "Create profile")

    def test_04_a_failure_halfway_leaves_the_engines_page(self):
        nothing = {"groups": [], "panes": [], "settings": [], "inits": [], "nodes": 0, "words": 0}
        for where in ("group", "pane"):
            with self.subTest(broken=where):
                self.m.chrome(BREAK_HALFWAY, [where])
                try:
                    page = self.open()
                    # Nothing of Nulavio's is left, and nothing of the engine's is missing or moved.
                    self.assertIsNone(page["extended"], page)
                    self.assertEqual(page["nav"][: len(ENGINE_NAV)], ENGINE_NAV, page)
                    self.assertEqual(page["general"], "pane-account-sync-title2", page)
                    self.assertEqual(self.m.chrome(LEFTOVERS), nothing)
                    # The engine's panes are registered as the engine wrote them: the wrapper is gone too.
                    appearance = self.groups("paneAppearance")
                    self.assertEqual([g for g in appearance if g in ENGINE_APPEARANCE], ENGINE_APPEARANCE, appearance)
                    self.assertFalse([g for g in appearance if g.startswith("nulavio")], appearance)
                    self.assertIn("about:preferences#tabsBrowsing", self.m.chrome(RELATED))
                    self.assertEqual(self.groups("paneTabsBrowsing")[0], "browserLayout")
                    self.assertIn("profiles", self.groups("paneSync"))
                    # An engine group Nulavio edits in place (DNS) is the engine's again: its summary line and its
                    # own name are back, and none of Nulavio's controls is in it.
                    self.assertIn("dnsOverHttps", self.groups("panePrivacy"))
                    dns = self.m.chrome(
                        DOC
                        + """
                      const group = d.querySelector('setting-group[groupid="dnsOverHttps"]');
                      return { summary: !!group?.querySelector("#dohModeBoxItem"),
                               ours: !!group?.querySelector('[id^="nulavio-"]'),
                               named: group?.querySelector("moz-fieldset")?.getAttribute("data-l10n-id") ?? null };
                    """
                    )
                    self.assertEqual(dns, {"summary": True, "ours": False, "named": "dns-over-https-group2"}, where)
                    # The page's own search still runs: it starts every pane it knows, and none is a removed one.
                    searched = self.m.chrome(
                        DOC + "return w.gSearchResultsPane.runCategoryInitialization().then(() => true, e => String(e));"
                    )
                    self.assertIs(searched, True)
                finally:
                    self.m.chrome(UNBREAK)
        # The next page load, with the page whole again, has Nulavio's part.
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
        # (Once the window's own start-up is over: until then it loads its home page into whatever tab is selected,
        # and a tab opened at "load" lost its page to it about one time in three.)
        second = self.m.chrome("""
          const win = window.OpenBrowserWindow();
          return new Promise(resolve => {
            const started = subject => {
              if (subject === win) {
                Services.obs.removeObserver(started, "browser-delayed-startup-finished");
                resolve(true);
              }
            };
            Services.obs.addObserver(started, "browser-delayed-startup-finished");
          });
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
        # The manager in use is marked in the list of managers; the row above it only speaks when none is on.
        in_use = (
            DOC
            + """const rows = d.querySelectorAll('#nulavio-passwords-providers moz-box-item[data-in-use="true"]');"""
            + "return [...rows].map(r => r.label);"
        )
        self.assertEqual(harness.wait_until(lambda: self.m.chrome(in_use), 15), ["O gerenciador de senhas do navegador (em uso)"])
        self.assertFalse(self.m.chrome(CONTROL, ["#nulavio-passwords-now"])["shown"])
        # The engine's own checkbox, in the group below, changes the answer above it.
        self.m.chrome('Services.prefs.setBoolPref("signon.rememberSignons", false);')
        # With it off and none of the known managers on, the row says only what was read: another extension may do it.
        off = "O gerenciador do navegador está desligado"
        none = self.control("#nulavio-passwords-now", lambda s: s.get("label") == off)
        self.assertEqual(none["label"], off, none)
        self.assertIn("Outra extensão pode", none["description"])
        self.groups("panePrivacy")
        self.assertEqual(self.control("#nulavio-guard-review")["description"], "Nada para rever.")
        # The Guard's count follows the Guard: a finding that arrives, or one decided on the review page.
        guard = 'const G = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs").NulavioGuard;'
        self.m.chrome(guard + 'G.findings = () => [{}, {}]; Services.obs.notifyObservers(null, "nulavio-guard-changed");')
        self.addCleanup(self.m.chrome, guard + "delete G.findings;")
        two = "2 mudanças para rever."
        self.assertEqual(self.control("#nulavio-guard-review", lambda s: s.get("description") == two)["description"], two)
        # Coming back to the tab reads again: a profile renamed or protected elsewhere shows as it is now.
        profiles = 'const P = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles;'
        self.m.chrome(profiles + 'P.here = async () => ({ name: "Outro nome", protection: "unlocked", temporary: false });')
        self.addCleanup(self.m.chrome, profiles + "delete P.here;")
        self.m.chrome(DOC + 'd.dispatchEvent(new w.Event("visibilitychange"));')
        self.groups("paneNulavioProfiles")
        renamed = self.control("#nulavio-here", lambda s: s.get("label") == "Outro nome")
        self.assertEqual(renamed["label"], "Outro nome", renamed)
        self.assertIn("Protegido", renamed["description"], renamed)
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

    def test_06a_what_the_content_filter_blocks_is_one_row_away(self):
        privacy = 'const N = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs").NulavioPrivacy;'
        where = "return gBrowser.selectedBrowser.currentURI.spec;"
        # The module's own entry, with uBlock Origin as it is in this profile (the policy installs it from the network).
        real = self.m.chrome(
            privacy
            + """
          const active = N.filter().active;
          try { N.openFilterLists(); return { active, opened: true }; } catch (e) { return { active, code: e.code }; }
        """
        )
        if real["active"]:
            self.assertTrue(real["opened"], real)
            lists = "/dashboard.html#3p-filters.html"
            self.assertTrue(harness.wait_until(lambda: self.m.chrome(where).endswith(lists), 15), self.m.chrome(where))
        else:
            self.assertEqual(real["code"], "filter-missing", real)
        # Which lists are switched on is read from uBlock Origin's own settings, and reading leaves them as they were.
        selection = """
          const { ExtensionStorageIDB } = ChromeUtils.importESModule("resource://gre/modules/ExtensionStorageIDB.sys.mjs");
          const policy = WebExtensionPolicy.getByID("uBlock0@raymondhill.net");
          if (!policy?.active) return null;
          const store = await ExtensionStorageIDB.open(ExtensionStorageIDB.getStoragePrincipal(policy.extension));
          const { selectedFilterLists } = await store.get("selectedFilterLists");
          store.close();
          return selectedFilterLists ?? null;
        """
        selected = "return (async () => {" + selection + "})();"
        before = None
        if real["active"]:
            # uBlock Origin is still choosing and ordering its lists in the first seconds of a new profile: wait
            # until two readings a moment apart agree, so that a difference afterwards is this module's doing.
            def settled():
                first = self.m.chrome(selected)
                time.sleep(0.7)
                return first is not None and first == self.m.chrome(selected)

            self.assertTrue(harness.wait_until(settled, 30, interval=0.1), "uBlock Origin's selection keeps changing")
            before = self.m.chrome(selected)
        answer = self.m.chrome(privacy + "return N.filterLists();")
        if before is None:
            self.assertIsNone(answer, "a selection was reported that uBlock Origin does not have")
        else:
            cookies = {"fanboy-cookiemonster", "ublock-cookies-easylist", "adguard-cookies", "ublock-cookies-adguard"}
            self.assertEqual(answer, {"cookieNotices": bool(cookies & set(before))})
            after = self.m.chrome(selected)
            # The same lists; their order is uBlock Origin's own, and it still reorders them now and then.
            self.assertEqual(sorted(after), sorted(before), "reading uBlock Origin's lists changed them")

        # The row says what was read and opens uBlock Origin's own page.
        state = (
            privacy
            + "window.__lists ??= 0; N.filter = () => ({ installed: true, active: arguments[0] });"
            + "N.filterLists = async () => arguments[1];"
        )
        self.m.chrome(state + "N.openFilterLists = () => { window.__lists++; };", [True, {"cookieNotices": True}])
        self.addCleanup(self.m.chrome, privacy + "delete N.filter; delete N.filterLists; delete N.openFilterLists;")
        self.open()
        self.groups("panePrivacy")
        row = self.control("#nulavio-filter-lists", lambda s: s.get("shown") and s.get("label"))
        self.assertEqual(row["label"], "O que o uBlock Origin bloqueia", row)
        self.assertIn("Avisos de cookies: escondidos", row["description"])
        # No cookie-notice list on: said as it is, with the way to switch one on.
        self.m.chrome(state, [True, {"cookieNotices": False}])
        self.m.chrome(DOC + 'd.dispatchEvent(new w.Event("visibilitychange"));')
        shown = self.control("#nulavio-filter-lists", lambda s: "à mostra" in (s.get("description") or ""))
        self.assertIn("Avisos de cookies: à mostra. Nenhuma lista de avisos de cookies está ligada", shown["description"])
        # Not read (uBlock Origin still starting): the row claims nothing about cookie notices.
        self.m.chrome(state, [True, None])
        self.m.chrome(DOC + 'd.dispatchEvent(new w.Event("visibilitychange"));')
        unknown = self.control("#nulavio-filter-lists", lambda s: "depende das listas" in (s.get("description") or ""))
        self.assertNotIn("escondidos", unknown["description"])
        self.assertNotIn("à mostra", unknown["description"])
        self.m.chrome(DOC + 'd.querySelector("#nulavio-filter-lists").click();')
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return window.__lists;") == 1, 10))
        # Turned off: the row says so, and leads to where it is turned on.
        self.m.chrome(state, [False, None])
        self.m.chrome(DOC + 'd.dispatchEvent(new w.Event("visibilitychange"));')
        off = "O uBlock Origin não está ligado neste perfil"
        self.assertEqual(self.control("#nulavio-filter-lists", lambda s: s.get("label") == off)["label"], off)
        # Turned on again while the page is open: the row's words follow, they do not stay from the state before.
        self.m.chrome(state, [True, {"cookieNotices": True}])
        self.m.chrome(DOC + 'd.dispatchEvent(new w.Event("visibilitychange"));')
        again = self.control("#nulavio-filter-lists", lambda s: s.get("label") == "O que o uBlock Origin bloqueia")
        self.assertIn("Avisos de cookies: escondidos", again["description"])
        self.m.chrome(state, [False, None])
        self.m.chrome(DOC + 'd.dispatchEvent(new w.Event("visibilitychange"));')
        self.control("#nulavio-filter-lists", lambda s: s.get("label") == off)
        self.m.chrome(DOC + 'd.querySelector("#nulavio-filter-lists").click();')
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(where) == "about:addons", 15), self.m.chrome(where))
        self.assertEqual(self.m.chrome("return window.__lists;"), 1)

    def test_06b_every_profile_is_listed_with_its_protection(self):
        rows = (
            DOC
            + """
          const list = d.querySelector("#nulavio-profile-list");
          if (!list || list.closest("setting-control")?.hidden) return null;
          return [...list.querySelectorAll("moz-box-item.nulavio-profile")].map(row => [row.label, row.description]);
        """
        )
        self.open()
        self.groups("paneNulavioProfiles")
        seen = harness.wait_until(lambda: (self.m.chrome(rows) or [None])[0] and self.m.chrome(rows), 15)
        self.assertEqual(seen, [["NativeSettings", "Este perfil. Sem senha."]])
        # A profile created elsewhere (the profile menu, another window) joins the list without a reload.
        profiles = 'const P = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles;'
        self.m.chrome(profiles + 'return P.create({ templateId: "work", name: "Trabalho" }).then(() => true);')
        two = harness.wait_until(lambda: len(self.m.chrome(rows) or []) == 2 and self.m.chrome(rows), 20)
        self.assertEqual(two, [["NativeSettings", "Este perfil. Sem senha."], ["Trabalho", "Sem senha."]], two)
        # The rows are part of the page: its own search finds a profile by name.
        found = self.m.chrome(
            DOC
            + """
          const input = w.gSearchResultsPane.searchInput;
          input.value = "Trabalho";
          return w.gSearchResultsPane.searchFunction({ target: input }).then(() => {
            const list = d.querySelector("#nulavio-profile-list");
            return Boolean(list && list.getBoundingClientRect().height > 0 && !list.closest("[hidden]"));
          });
        """
        )
        self.assertTrue(found, "the page's search does not find a profile's name")
        # A list that cannot be read is not drawn, and the group says so.
        broken = (
            profiles
            + """
          if (arguments[0]) { window.__nulavioList = P.list; P.list = () => Promise.reject(new Error("test: unreadable")); }
          else { delete P.list; }
        """
        )
        self.m.chrome(broken, [True])
        self.addCleanup(self.m.chrome, broken, [False])
        self.open()
        self.groups("paneNulavioProfiles")
        note = self.control("#nulavio-profile-list-failed")
        self.assertIn("Não foi possível ler", note["message"], note)
        self.assertEqual(self.m.chrome(rows) or [], [])

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
        self.groups("paneNulavioIntegrations")
        self.control("#nulavio-open-integrations")
        self.m.chrome(DOC + 'd.querySelector("#nulavio-open-integrations").click();')
        detail = "/settings/settings.html#integrations"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(where).endswith(detail), 15), self.m.chrome(where))
        for handle in self.m.window_handles():
            self.m.switch_to(handle)
            if self.m.current_url().endswith(detail):
                break
        ready = "return document.documentElement.dataset.ready === 'true';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(ready), 20))
        rail = self.m.execute(
            "return [...document.querySelectorAll('.settings-nav a[data-section]')].map(a => a.dataset.section);"
        )
        # What the settings page draws itself has no entry on a detail page (ADR 0008, ADR 0011).
        for moved in ("layout", "appearance", "shortcuts", "profiles", "routing", "exceptions", "passwords", "search", "dns"):
            self.assertNotIn(moved, rail)
        self.assertEqual(self.m.execute("return document.getElementById('settings-back').textContent;"), "Configurações")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#settings-back")})
        back = "about:preferences#nulavioIntegrations"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(where) == back, 15), self.m.chrome(where))
        self.assertEqual(self.m.chrome("return gBrowser.tabs.length;"), tabs)
        # An old address of the routing section (a bookmark, a tab left open) opens the settings page at its pane.
        shell = self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('settings/settings.html#routing');")
        self.m.navigate(shell)
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(where) == "about:preferences#nulavioProfiles", 15), self.m.chrome(where)
        )


if __name__ == "__main__":
    unittest.main()
