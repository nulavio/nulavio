"""#323: the engine's tab groups in the Nulavio build. Created, renamed, coloured and collapsed, in the side tab list
(Lateral, Foco) and with the tabs on top; a group's colour is never one of the colours that mean something in Nulavio
(orange, purple and red are left out of the palette it offers), and it is never read as the profile: the band keeps
the profile's colour whatever the groups are. A closed group comes back from the closed groups, a group stays as it was
through Imersivo, and a restart that restores the session brings it back. AI grouping stays off."""

from __future__ import annotations

import json
import unittest

import harness

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
GROUP = """
const group = gBrowser.getAllTabGroups()[0];
if (!group) return null;
const label = group.querySelector('.tab-group-label');
const line = getComputedStyle(group).getPropertyValue('--tab-group-color').trim();
return { label: group.label, color: group.color, collapsed: group.collapsed, tabs: group.tabs.length,
         shownTabs: group.tabs.filter(t => { const r = t.getBoundingClientRect();
           return r.width > 1 && r.height > 1
             && t.checkVisibility({ visibilityProperty: true, opacityProperty: true }); }).length,
         labelShown: Boolean(label?.checkVisibility()),
         labelColour: label ? getComputedStyle(label).backgroundColor : null, line,
         flag: getComputedStyle(document.querySelector('#nulavio-band .nv-band-flag')).backgroundColor,
         vertical: gBrowser.tabContainer.verticalMode };
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class TabGroupsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def setUp(self):
        self.m.navigate(self.server.url("/page/um"))
        self.m.chrome(
            "gBrowser.addTrustedTab(arguments[0]); gBrowser.addTrustedTab(arguments[1]);",
            [self.server.url("/page/dois"), self.server.url("/page/tres")],
        )
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.m.chrome(
            "for (const g of gBrowser.getAllTabGroups()) gBrowser.ungroupTabs?.(g) ?? g.ungroupTabs();"
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

    def group(self) -> dict | None:
        return self.m.chrome(GROUP)

    def journey(self, preset: str) -> None:
        self.assertIs(self.apply(preset), True)
        # Created with no colour: the engine takes the next one from the palette Nulavio offers.
        self.m.chrome("gBrowser.addTabGroup([gBrowser.tabs[1], gBrowser.tabs[2]], { label: 'Trabalho' });")
        now = self.group()
        self.assertEqual((now["label"], now["tabs"], now["collapsed"]), ("Trabalho", 2, False), now)
        self.assertNotIn(now["color"], ("orange", "purple", "red"))
        self.assertTrue(now["labelShown"], now)
        self.assertEqual(now["vertical"], preset != "top")
        # Renamed and coloured.
        self.m.chrome("const g = gBrowser.getAllTabGroups()[0]; g.label = 'Projeto'; g.color = 'cyan';")
        now = self.group()
        self.assertEqual((now["label"], now["color"]), ("Projeto", "cyan"))
        # Collapsed: its tabs leave the list (the selected tab is not in it); expanded: they are back.
        self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[0]; gBrowser.getAllTabGroups()[0].collapsed = true;")
        self.assertTrue(harness.wait_until(lambda: self.group()["shownTabs"] == 0, 5), self.group())
        self.m.chrome("gBrowser.getAllTabGroups()[0].collapsed = false;")
        self.assertTrue(harness.wait_until(lambda: self.group()["shownTabs"] == 2, 5), self.group())

    def test_01_with_the_side_tab_list(self):
        self.journey("lateral")

    def test_02_with_foco(self):
        self.journey("focus")

    def test_03_with_the_tabs_on_top(self):
        self.journey("top")

    def test_04_a_group_colour_is_never_the_profiles_and_the_palette_leaves_out_the_colours_with_meaning(self):
        offered = self.m.chrome(
            "const editor = document.getElementById('tab-group-editor');"
            "const seen = new Set(); for (let i = 0; i < 40; i++) seen.add(editor.nextUnusedColor); return [...seen];"
        )
        self.assertFalse({"orange", "purple", "red"} & set(offered), offered)
        folder = harness.artifacts_dir() / "tab-groups"
        folder.mkdir(parents=True, exist_ok=True)
        flag = "return getComputedStyle(document.querySelector('#nulavio-band .nv-band-flag')).backgroundColor;"
        try:
            for dark in (0, 1):
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                harness.wait_until(lambda: False, 0.5)
                profile = self.m.chrome(flag)
                for color in ("green", "yellow", "blue", "cyan", "pink", "gray"):
                    self.m.chrome(
                        "for (const g of gBrowser.getAllTabGroups()) g.ungroupTabs();"
                        "gBrowser.addTabGroup([gBrowser.tabs[1]], { label: 'Grupo', color: arguments[0] });",
                        [color],
                    )
                    now = self.group()
                    # The band says the profile, in the profile's colour: a group of any colour does not change it.
                    self.assertNotEqual(now["labelColour"], now["flag"], (color, now))
                    self.assertEqual(self.m.chrome(flag), profile, color)
                self.m.set_context("chrome")
                try:
                    (folder / f"groups-{'dark' if dark else 'light'}.png").write_bytes(self.m.screenshot_png())
                finally:
                    self.m.set_context("content")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")
        # AI grouping stays off (baseline.js).
        self.assertFalse(self.m.chrome("return Services.prefs.getBoolPref('browser.tabs.groups.smart.enabled');"))
        print(json.dumps(offered))

    def make_group(self) -> str:
        self.m.chrome("gBrowser.addTabGroup([gBrowser.tabs[1], gBrowser.tabs[2]], { label: 'Trabalho', color: 'cyan' });")
        return self.m.chrome("return gBrowser.getAllTabGroups()[0].id;")

    def groups(self) -> list:
        return self.m.chrome(
            "return gBrowser.getAllTabGroups().map(g => [g.id, g.label, g.color, g.collapsed,"
            " g.tabs.map(t => new URL(t.linkedBrowser.currentURI.spec).pathname)]);"
        )

    def test_05_a_closed_group_comes_back_from_the_closed_groups(self):
        group = self.make_group()
        self.m.set_context("chrome")
        try:
            self.m.execute_async(
                "const done = arguments[arguments.length - 1];"
                "gBrowser.removeTabGroup(gBrowser.getAllTabGroups()[0]).then(() => done(true), e => done(String(e)));"
            )
        finally:
            self.m.set_context("content")
        self.assertEqual(self.groups(), [])
        closed = "return SessionStore.getClosedTabGroups({ sourceWindow: window }).map(g => [g.id, g.name, g.tabs.length]);"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(closed), 10))
        self.assertEqual(self.m.chrome(closed)[0], [group, "Trabalho", 2])
        self.m.chrome("SessionStore.undoCloseTabGroup(window, arguments[0], window);", [group])
        self.assertTrue(harness.wait_until(lambda: self.groups(), 10))
        self.assertEqual(self.groups(), [[group, "Trabalho", "cyan", False, ["/page/dois", "/page/tres"]]])
        self.assertEqual(self.m.chrome(closed), [])

    def test_06_with_imersivo_a_group_stays_as_it_was(self):
        group = self.make_group()
        self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[0]; gBrowser.getAllTabGroups()[0].collapsed = true;")
        name = "return document.querySelector('#nulavio-band .nv-band-name')?.textContent.trim() ?? null;"
        before = self.m.chrome(name)
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', true);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('nulavio.layout.immersive');")
        on = "return document.documentElement.hasAttribute('nulavio-immersive');"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(on), 10))
        self.assertEqual(self.groups(), [[group, "Trabalho", "cyan", True, ["/page/dois", "/page/tres"]]])
        self.assertEqual(self.m.chrome(name), before)
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', false);")
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(on), 10))
        self.assertEqual(self.groups(), [[group, "Trabalho", "cyan", True, ["/page/dois", "/page/tres"]]])
        self.m.chrome("gBrowser.getAllTabGroups()[0].collapsed = false;")
        self.assertTrue(harness.wait_until(lambda: self.group()["shownTabs"] == 2, 5), self.group())

    def test_07_a_restart_brings_the_group_back_when_the_session_is_restored(self):
        # "Open previous windows and tabs" (Settings > Home: browser.startup.page = 3), as a person turns it on.
        group = self.make_group()
        self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[0]; gBrowser.getAllTabGroups()[0].collapsed = true;")
        self.m.chrome("Services.prefs.setIntPref('browser.startup.page', 3);")
        try:
            type(self).m = self.m = self.session.restart()
            self.assertTrue(harness.wait_until(lambda: self.groups(), 30))
            self.assertEqual(self.groups(), [[group, "Trabalho", "cyan", True, ["/page/dois", "/page/tres"]]])
            self.assertTrue(harness.wait_until(lambda: self.group()["shownTabs"] == 0, 5), self.group())
            # The band still says the profile after the restore.
            self.assertEqual(
                self.m.chrome("return document.querySelector('#nulavio-band .nv-band-name')?.textContent.trim();"),
                "Pessoal",
            )
        finally:
            self.m.chrome("Services.prefs.clearUserPref('browser.startup.page');")


if __name__ == "__main__":
    unittest.main()
