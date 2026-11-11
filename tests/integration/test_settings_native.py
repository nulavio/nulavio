"""ADR 0008: one settings page. Nulavio's options are native groups inside the engine's about:preferences."""

from __future__ import annotations

import unittest

import harness

# The appearance pane as the page built it: its groups in order, the layout picker and the navigation.
PROBE = """
const d = gBrowser.selectedBrowser.contentDocument;
if (!d?.documentURI.startsWith("about:preferences") || d.readyState !== "complete") return null;
const picker = d.querySelector("#nulavio-layout");
const pane = picker?.closest("setting-pane");
if (!pane) return {extended: d.documentElement.getAttribute("nulavio-settings")};
return {
  extended: d.documentElement.getAttribute("nulavio-settings"),
  nav: [...d.querySelectorAll("moz-page-nav-button")].map(b => b.id),
  groups: [...pane.querySelectorAll("setting-group")].map(g => g.getAttribute("groupid")),
  value: picker.value,
  items: [...picker.querySelectorAll("moz-visual-picker-item")].map(i => [i.value, i.label]),
};
"""
ENGINE_APPEARANCE = ["appearance", "browserTheme", "windowDensity", "relatedSettings"]


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class NativeSettingsTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="NativeSettings")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def open(self):
        self.m.chrome('gBrowser.selectedTab = gBrowser.addTrustedTab("about:preferences#appearance");')
        harness.wait_until(lambda: (self.m.chrome(PROBE) or {}).get("items"), 20)
        return self.m.chrome(PROBE)

    def test_01_layout_is_the_first_group_of_the_engines_appearance_pane(self):
        page = self.open()
        self.assertEqual(page["extended"], "1")
        # The seam (the pane edited as the page registers it) worked: ours first, the engine's all still there, in their order.
        self.assertEqual(page["groups"][0], "nulavioLayout", page)
        self.assertEqual([g for g in page["groups"] if g in ENGINE_APPEARANCE], ENGINE_APPEARANCE, page)
        self.assertLess(page["groups"].index("windowDensity"), page["groups"].index("nulavioLook"), page)
        # Journey order in the navigation: how it looks, who you are, then the engine's panes.
        self.assertEqual(page["nav"][:2], ["category-appearance", "category-nulavio-profiles"], page)
        self.assertEqual([value for value, _ in page["items"]], ["lateral", "top", "focus"], page)
        self.assertEqual([label for _, label in page["items"]], ["Lateral", "Abas no topo", "Foco"], page)

    def test_02_the_card_changes_the_real_layout(self):
        page = self.open()
        self.assertEqual(page["value"], "lateral", page)
        self.assertTrue(self.m.chrome('return Services.prefs.getBoolPref("sidebar.verticalTabs");'))
        self.m.chrome("""
          const picker = gBrowser.selectedBrowser.contentDocument.querySelector("#nulavio-layout");
          [...picker.querySelectorAll("moz-visual-picker-item")].find(item => item.value === "top").click();
        """)
        harness.wait_until(lambda: not self.m.chrome('return Services.prefs.getBoolPref("sidebar.verticalTabs");'), 10)
        harness.wait_until(lambda: self.m.chrome(PROBE)["value"] == "top", 10)

    def test_02b_the_immersive_switch_sits_under_the_layout_and_writes_through_the_layout_module(self):
        self.open()
        switch = """
          const toggle = gBrowser.selectedBrowser.contentDocument.querySelector("#nulavio-immersive");
          return toggle && { group: toggle.closest("setting-group")?.getAttribute("groupid"), label: toggle.label,
            pressed: toggle.pressed, disabled: toggle.disabled };
        """
        pref = 'return Services.prefs.getBoolPref("nulavio.layout.immersive", false);'
        self.addCleanup(self.m.chrome, 'Services.prefs.clearUserPref("nulavio.layout.immersive");')
        self.assertEqual(
            self.m.chrome(switch), {"group": "nulavioLayout", "label": "Imersivo", "pressed": False, "disabled": False}
        )
        self.m.chrome('gBrowser.selectedBrowser.contentDocument.querySelector("#nulavio-immersive").click();')
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(pref), 10))
        # Changed from elsewhere (the key): the switch follows.
        self.m.chrome('Services.prefs.setBoolPref("nulavio.layout.immersive", false);')
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(switch)["pressed"] is False, 10), self.m.chrome(switch))

    def test_03_words_come_in_english_too(self):
        self.m.chrome('Services.locale.requestedLocales = ["en-US"];')
        self.m = self.session.restart()
        page = self.open()
        self.assertEqual([label for _, label in page["items"]], ["Lateral", "Tabs on top", "Focus"], page)


if __name__ == "__main__":
    unittest.main()
