"""#315: the engine's split view (on by default in Firefox 160) in the Nulavio build. Two tabs side by side in one
window, from the tab menu or the engine's API: the address bar, the identity and, with Imersivo on, the band name the
focused side's site, never the other side's; the side that is not focused keeps the engine's own footer with its site
and connection; both sides are tabs of the same profile, in the side tab list and with the tabs on top."""

from __future__ import annotations

import unittest

import harness

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
STATE = """
const band = document.getElementById('nulavio-band');
const text = name => {
  const e = band.querySelector('.nv-band-' + name);
  return e && e.checkVisibility() ? e.textContent.trim() : null;
};
const footer = panel => {
  const f = panel.querySelector('split-view-footer');
  return f?.checkVisibility() ? f.textContent.replace(/\\s+/g, ' ').trim() : null;
};
const panels = [...document.querySelectorAll('.split-view-panel')];
return { selected: gBrowser.selectedBrowser.currentURI.hostPort, urlbar: gURLBar.value,
         split: Boolean(gBrowser.selectedTab.splitview), sides: gBrowser.selectedTab.splitview?.tabs.length ?? 0,
         panels: panels.map(p => ({ selected: p.classList.contains('deck-selected'), footer: footer(p) })),
         host: text('origin-host'), profile: text('name'),
         immersive: document.documentElement.hasAttribute('nulavio-immersive'), vertical: gBrowser.tabContainer.verticalMode };
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class SplitViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()
        cls.a = cls.server.url("/page/Lado-A")
        cls.b = cls.server.url("/page/Lado-B").replace("127.0.0.1", "localhost")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def setUp(self):
        self.m.chrome("window.resizeTo(1400, 900);")
        self.m.navigate(self.a)
        self.m.chrome("gBrowser.selectedTab = gBrowser.addTrustedTab(arguments[0]);", [self.b])
        # Marionette's content scripts stay in the first tab: the second tab's title is read from the window.
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome("return gBrowser.selectedBrowser.contentTitle;") == "Lado-B", 10)
        )
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.m.chrome(
            "Services.prefs.clearUserPref('nulavio.layout.immersive');"
            "gBrowser.selectedTab.splitview?.unsplitTabs?.('test');"
            "while (gBrowser.tabs.length > 1) gBrowser.removeTab(gBrowser.tabs[gBrowser.tabs.length - 1], { animate: false });"
        )
        self.apply("lateral")

    def apply(self, preset: str):
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(
                "const d = arguments[arguments.length - 1];"
                f"{LAYOUT}.apply(window, arguments[0]).then(() => d(true), e => d(String(e)));",
                [preset],
            )
        finally:
            self.m.set_context("content")

    def state(self) -> dict:
        return self.m.chrome(STATE)

    def split(self) -> None:
        self.assertTrue(self.m.chrome("return Services.prefs.getBoolPref('browser.tabs.splitView.enabled', false);"))
        self.assertTrue(self.m.chrome("return Boolean(gBrowser.addTabSplitView([gBrowser.tabs[0], gBrowser.tabs[1]]));"))
        self.assertTrue(harness.wait_until(lambda: self.state()["sides"] == 2, 10), self.state())

    def select(self, index: int) -> dict:
        self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[arguments[0]];", [index])
        want = ("127.0.0.1:" if index == 0 else "localhost:") + str(self.server.port)
        harness.wait_until(
            lambda: self.state()["selected"] == want and (not self.state()["immersive"] or self.state()["host"] == want), 10
        )
        return self.state()

    def check_sides(self) -> None:
        for index, host in ((0, "127.0.0.1"), (1, "localhost")):
            now = self.select(index)
            other = "localhost" if host == "127.0.0.1" else "127.0.0.1"
            self.assertEqual(now["selected"], f"{host}:{self.server.port}", now)
            self.assertIn(host, now["urlbar"])
            self.assertEqual(len(now["panels"]), 2, now)
            focused = [p for p in now["panels"] if p["selected"]]
            unfocused = [p for p in now["panels"] if not p["selected"]]
            self.assertEqual(len(focused), 1, now)
            # The side that is not focused names its own site in the engine's footer; the focused one has none.
            self.assertIsNone(focused[0]["footer"], now)
            self.assertIn(other, unfocused[0]["footer"] or "", now)
            if now["immersive"]:
                self.assertEqual(now["host"], f"{host}:{self.server.port}", now)
            self.assertEqual(now["profile"], "Pessoal")

    def test_01_the_address_and_the_identity_follow_the_focused_side(self):
        self.split()
        self.check_sides()

    def test_02_with_imersivo_the_band_names_the_focused_side(self):
        self.split()
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', true);")
        self.assertTrue(harness.wait_until(lambda: self.state()["immersive"], 10), self.state())
        self.check_sides()

    def test_03_with_the_tabs_on_top(self):
        self.assertIs(self.apply("top"), True)
        self.split()
        self.assertFalse(self.state()["vertical"])
        self.check_sides()

    def test_04_the_tab_menu_offers_it_in_the_browsers_language(self):
        items = self.m.chrome(
            "const menu = document.getElementById('tabContextMenu');"
            "return ['context_moveTabToSplitView', 'context_separateSplitView', 'context_reverseSplitView']"
            ".map(id => [id, Boolean(menu.querySelector('#' + id))]);"
        )
        self.assertEqual([present for _, present in items], [True, True, True], items)

    def test_05_captures_in_both_themes(self):
        self.split()
        folder = harness.artifacts_dir() / "split-view"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            for dark in (0, 1):
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                harness.wait_until(lambda: False, 0.8)
                self.m.set_context("chrome")
                try:
                    (folder / f"split-{'dark' if dark else 'light'}.png").write_bytes(self.m.screenshot_png())
                finally:
                    self.m.set_context("content")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")


if __name__ == "__main__":
    unittest.main()
