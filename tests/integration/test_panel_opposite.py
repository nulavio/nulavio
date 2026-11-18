"""#527: the side panel on the side of the page opposite the tabs (Aparência, off by default).

The engine places the panel (patch 0013, `SidebarController.setPosition()`, behind `nulavio.sidebar.panelOpposite`);
Nulavio's sheets give it the window's margin on its outer side (horizon.css, and window-band.css in Imersivo). The
geometry is read for every layout, both sides of the tabs (`sidebar.position_start`), with Imersivo off and on, in
both themes at 1440 x 900 and 1366 x 768, and compared with the same window with the setting off: the panel is
after the page with the tabs on the left and before it with the tabs on the right, the margin at the window's edge
and the gap between the page and the panel are the ones the page had, and the page and the panel are as wide.
That comparison is what notices when Mozilla's sidebar styles change under Nulavio's rules (#249).

A test of what the patch adds fails on a build of this tree that lacks it (NULAVIO_BUILT_FROM_TREE=1, as the
release's run sets) and skips on an older engine with this tree's Shell (a development package)."""

from __future__ import annotations

import unittest

import harness
import settings_page
from test_profiles import chrome_async

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
PREF = "nulavio.sidebar.panelOpposite"
ASSISTANT = "shell_nulavio_net-sidebar-action"
# The window as drawn: each part's left and right edge (null when it is not shown), the window's frame margin and
# what the engine and the Shell marked on the root.
GEOMETRY = """
const root = document.documentElement;
const part = id => {
  const e = document.getElementById(id);
  if (!e || !e.checkVisibility()) return null;
  const b = e.getBoundingClientRect();
  return b.width ? [Math.round(b.left), Math.round(b.right)] : null;
};
const card = gBrowser.selectedBrowser.closest(".browserContainer").getBoundingClientRect();
const frame = getComputedStyle(root).getPropertyValue("--nulavio-frame-margin").trim();
return {
  width: innerWidth, height: innerHeight, launcher: part("sidebar-container"), panel: part("sidebar-box"),
  splitter: part("sidebar-splitter"), page: [Math.round(card.left), Math.round(card.right)],
  frame: frame ? Math.round(parseFloat(frame)) : 0, opposite: root.hasAttribute("nulavio-panel-opposite"),
  end: root.hasAttribute("sidebar-positionend"), immersive: root.hasAttribute("nulavio-immersive"),
  expanded: SidebarController.getUIState().launcherExpanded, current: SidebarController.currentID,
  still: !document.getAnimations().some(a => a.playState === "running"),
};
"""
AWAY = "window.synthesizeMouseEvent('mousemove', Math.round(innerWidth / 2), Math.round(innerHeight / 2), {}, {});"
SHOW = "return SidebarController.show(arguments[0]).then(() => SidebarController.currentID);"
LAUNCHER_BUTTON = "document.querySelector('sidebar-main').shadowRoot.querySelector(`moz-button[view='${arguments[0]}']`)"


def width(span: list) -> int:
    return span[1] - span[0]


@unittest.skipUnless(harness.nulavio_engine(), "the side panel's setting needs the built-in Shell on the engine")
class PanelOppositeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Painel")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()
        cls.page = cls.server.url("/page/Painel")
        cls.artifacts = harness.artifacts_dir() / "panel-opposite"
        cls.artifacts.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def setUp(self):
        self.m.navigate(self.page)
        self.addCleanup(self.m.chrome, f"Services.prefs.clearUserPref('{PREF}');")
        self.addCleanup(self.m.chrome, "SidebarController.hide();")

    # -- helpers ---------------------------------------------------------------------------------------------------

    def geometry(self) -> dict:
        return self.m.chrome(GEOMETRY)

    def apply(self, preset: str) -> None:
        result = chrome_async(self.m, f"return {LAYOUT}.apply(window, arguments[0]).then(state => state.preset);", [preset])
        self.assertEqual(result.get("ok"), preset, result)

    def show(self, view: str = ASSISTANT) -> None:
        self.assertEqual(chrome_async(self.m, SHOW, [view]).get("ok"), view)

    def settle(self, want, what: str) -> dict:
        """The window once `want` holds of it and nothing moves any more (the engine animates the change)."""
        harness.wait_until(lambda: (g := self.geometry())["still"] and want(g), 10)
        now = self.geometry()
        self.assertTrue(now["still"] and want(now), f"{what}: {now}")
        return now

    def opposite(self, on: bool) -> dict:
        if on:
            self.m.chrome(f"Services.prefs.setBoolPref('{PREF}', true);")
        else:
            self.m.chrome(f"Services.prefs.clearUserPref('{PREF}');")
        if not on:
            return self.settle(lambda g: not g["opposite"], "the setting off")
        return self.settle(lambda g: g["opposite"] and g["panel"] and g["page"], "the setting on")

    def needs_the_patch(self) -> None:
        """Patch 0013 marks the root when the setting is on. A build of this tree must have it."""
        self.m.chrome(f"Services.prefs.setBoolPref('{PREF}', true);")
        has = harness.wait_until(
            lambda: self.m.chrome("return document.documentElement.hasAttribute('nulavio-panel-opposite');"), 5
        )
        self.m.chrome(f"Services.prefs.clearUserPref('{PREF}');")
        if has:
            harness.wait_until(
                lambda: not self.m.chrome("return document.documentElement.hasAttribute('nulavio-panel-opposite');"), 5
            )
            return
        if harness.built_from_this_tree():
            self.fail("this engine is a build of this tree and does not place the panel opposite: patch 0013 is missing")
        self.skipTest("an engine without patch 0013 (a development package with this tree's Shell)")

    def capture(self, name: str) -> None:
        self.m.set_context("chrome")
        try:
            (self.artifacts / f"{name}.png").write_bytes(self.m.screenshot_png())
        finally:
            self.m.set_context("content")

    def side(self, name: str, start: bool, immersive: bool) -> None:
        """Tabs on the left (start) or the right, Imersivo on or off, the toolbar and the tab list at rest."""
        self.m.chrome("Services.prefs.setBoolPref('sidebar.position_start', arguments[0]);", [start])
        if immersive:
            self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', true);")
        else:
            self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.m.chrome(AWAY + "gBrowser.selectedBrowser.focus();")
        self.settle(lambda g: g["end"] is not start and g["immersive"] is immersive, name)
        if immersive:
            toolbar = "return getComputedStyle(document.getElementById('nav-bar')).opacity === '0';"
            self.assertTrue(harness.wait_until(lambda: self.m.chrome(toolbar), 10), f"{name}: the toolbar stayed")

    def assert_opposite(self, off: dict, on: dict, where: str) -> None:
        """The arrangement with the setting on, against the same window with it off."""
        page, panel, start = on["page"], on["panel"], not on["end"]
        self.assertFalse(off["opposite"], where)
        self.assertTrue(off["panel"] and panel, f"{where}: no panel: {off} / {on}")
        at = f"{where}: off {off}, on {on}"
        # Off: the panel beside the tabs, between them and the page.
        if start:
            self.assertLessEqual(off["panel"][1], off["page"][0], "off, the panel is not before the page: " + at)
        else:
            self.assertGreaterEqual(off["panel"][0], off["page"][1], "off, the panel is not after the page: " + at)
        # On: the panel on the other side of the page; the tabs stay where they were.
        self.assertEqual(on["launcher"], off["launcher"], "the tabs moved: " + at)
        if start:
            self.assertGreaterEqual(panel[0], page[1], "the panel is not after the page: " + at)
            if on["launcher"] and not on["immersive"]:
                self.assertLessEqual(on["launcher"][1], page[0], "the page is not after the tabs: " + at)
        else:
            self.assertLessEqual(panel[1], page[0], "the panel is not before the page: " + at)
            if on["launcher"] and not on["immersive"]:
                self.assertGreaterEqual(on["launcher"][0], page[1], "the page is not before the tabs: " + at)
        # The window's margin, now the panel's: as wide as the page's was on that side, and the frame's.
        edge_off = on["width"] - off["page"][1] if start else off["page"][0]
        edge_on = on["width"] - panel[1] if start else panel[0]
        self.assertEqual(edge_on, edge_off, "the margin at the window's edge: " + at)
        self.assertEqual(edge_on, on["frame"], "the margin at the window's edge is not the frame's: " + at)
        self.assertGreater(edge_on, 0, "the panel touches the window's edge: " + at)
        # One gap between the page and the panel: the splitter, as with the panel beside the tabs.
        gap_off = off["page"][0] - off["panel"][1] if start else off["panel"][0] - off["page"][1]
        gap_on = panel[0] - page[1] if start else page[0] - panel[1]
        self.assertEqual(gap_on, gap_off, "the gap between the page and the panel: " + at)
        # The page and the panel as wide as with the setting off; the page starts where the panel did.
        self.assertEqual(width(page), width(off["page"]), "the page's width: " + at)
        self.assertEqual(width(panel), width(off["panel"]), "the panel's width: " + at)
        if start:
            self.assertEqual(page[0], off["panel"][0], at)
        else:
            self.assertEqual(page[1], off["panel"][1], at)

    def restore(self) -> None:
        for pref in ("sidebar.position_start", "nulavio.layout.immersive", "ui.systemUsesDarkTheme"):
            self.m.chrome(f"Services.prefs.clearUserPref('{pref}');")

    # -- tests -------------------------------------------------------------------------------------------------------

    def test_00_off_in_a_new_profile_the_panel_opens_beside_the_tabs(self):
        self.assertFalse(self.m.chrome(f"return Services.prefs.prefHasUserValue('{PREF}');"))
        self.assertFalse(self.m.chrome(f"return Services.prefs.getBoolPref('{PREF}', true);"), "the default is off")
        self.apply("lateral")
        self.show()
        now = self.settle(lambda g: g["panel"] is not None, "the assistant open")
        self.assertFalse(now["opposite"], now)
        self.assertLessEqual(now["launcher"][1], now["panel"][0] + 1, now)
        self.assertLessEqual(now["panel"][1], now["page"][0], now)

    def test_01_the_switch_in_appearance_writes_the_setting(self):
        settings_page.open_pane(self.m, "appearance")
        off = lambda now: now["shown"] and not now["pressed"] and not now["disabled"]  # noqa: E731
        control = settings_page.wait_control(self.m, "nulavio-panel-opposite", off)
        self.assertEqual(control["label"], "Painel lateral do outro lado das abas", control)
        self.assertIn("favoritos", control["description"] or "", control)
        marked = settings_page.DOC + 'return d.getElementById("nulavio-panel-opposite").dataset.option;'
        self.assertEqual(self.m.chrome(marked), "panelOpposite")
        settings_page.click(self.m, "#nulavio-panel-opposite")
        pref = f"return Services.prefs.getBoolPref('{PREF}', false);"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(pref), 10))
        settings_page.wait_control(self.m, "nulavio-panel-opposite", lambda now: now["pressed"])
        settings_page.click(self.m, "#nulavio-panel-opposite")
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(pref), 10))
        # Off again is no setting at all, as in a new profile.
        self.assertFalse(self.m.chrome(f"return Services.prefs.prefHasUserValue('{PREF}');"))

    def test_02_a_setting_an_administrator_locked_is_shown_and_cannot_change(self):
        self.m.chrome(f"Services.prefs.getDefaultBranch('').setBoolPref('{PREF}', true); Services.prefs.lockPref('{PREF}');")
        try:
            settings_page.open_pane(self.m, "appearance")
            locked = lambda now: now["shown"] and now["pressed"] and now["disabled"]  # noqa: E731
            settings_page.wait_control(self.m, "nulavio-panel-opposite", locked)
            note = settings_page.wait_control(self.m, "nulavio-look-locked")
            self.assertEqual(note["message"], "Algumas destas opções são gerenciadas pelo administrador.")
        finally:
            self.m.chrome(
                f"Services.prefs.unlockPref('{PREF}'); Services.prefs.getDefaultBranch('').setBoolPref('{PREF}', false);"
            )

    def test_03_the_panel_is_opposite_the_tabs_in_every_layout(self):
        """Lateral, Foco and Abas no topo; the tabs on the left and on the right; Imersivo off and on; light at
        1440 x 900 and dark at 1366 x 768. Each arrangement is read with the setting off and on, in the same window."""
        self.needs_the_patch()
        self.addCleanup(self.restore)
        self.addCleanup(self.apply, "lateral")
        self.addCleanup(
            self.m.chrome, "window.resizeTo(arguments[0], arguments[1]);", self.m.chrome("return [outerWidth, outerHeight];")
        )
        for (w, h), dark in (((1440, 900), 0), ((1366, 768), 1)):
            self.m.chrome("window.resizeTo(arguments[0], arguments[1]);", [w, h])
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            for preset in ("lateral", "focus", "top"):
                self.apply(preset)
                for immersive in (False, True):
                    for start in (True, False):
                        name = f"{preset}-{'left' if start else 'right'}{'-immersive' if immersive else ''}-{w}x{h}"
                        name += "-dark" if dark else "-light"
                        with self.subTest(name):
                            # Off again whatever this arrangement found, so the next one starts from the window as it is.
                            self.m.chrome(f"Services.prefs.clearUserPref('{PREF}');")
                            self.side(name, start, immersive)
                            self.show()
                            off = self.settle(lambda g: g["panel"] is not None and not g["opposite"], name + ", off")
                            on = self.opposite(True)
                            self.assertEqual(on["current"], ASSISTANT, on)
                            self.assert_opposite(off, on, name)
                            self.capture(name)
                            back = self.opposite(False)
                            self.assertEqual((back["page"], back["panel"]), (off["page"], off["panel"]), name + ", off again")
                            self.m.chrome("SidebarController.hide();")

    def test_04_foco_the_launcher_expanded_over_the_page_moves_neither_the_page_nor_the_panel(self):
        """In Foco the launcher opens over the page on hover. The engine keeps the collapsed launcher's room beside it,
        where it takes the panel to be; with the panel opposite, the page is there and must not move under it."""
        self.needs_the_patch()
        self.addCleanup(self.restore)
        self.addCleanup(self.apply, "lateral")
        self.apply("focus")
        for start in (True, False):
            with self.subTest(start=start):
                self.m.chrome(f"Services.prefs.clearUserPref('{PREF}');")
                self.side(f"focus, {start}", start, False)
                self.show()
                rest = self.opposite(True)
                self.assertFalse(rest["expanded"], rest)
                x = (rest["launcher"][0] + rest["launcher"][1]) // 2
                self.m.set_context("chrome")
                try:
                    move = {"type": "pointerMove", "origin": "viewport", "x": x, "y": rest["height"] // 2, "duration": 100}
                    pointer = {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": [move]}
                    self.m.send("WebDriver:PerformActions", {"actions": [pointer]})
                finally:
                    self.m.set_context("content")
                expanded = self.settle(lambda g: g["expanded"], "the launcher expanded")
                self.assertGreater(width(expanded["launcher"]), width(rest["launcher"]), expanded)
                self.assertEqual((expanded["page"], expanded["panel"]), (rest["page"], rest["panel"]), f"{rest} / {expanded}")
                self.m.set_context("chrome")
                try:
                    self.m.send("WebDriver:ReleaseActions")
                finally:
                    self.m.set_context("content")
                self.m.chrome(AWAY)
                self.settle(lambda g: not g["expanded"], "the launcher back")
                self.opposite(False)

    def test_05_the_splitter_resizes_the_panel_from_the_page_side(self):
        """A drag of the splitter with the pointer, through the engine's own event path (the #249 probe's synthetic drag
        could not run): toward the page, the panel grows by as much, and its outer edge stays at the window's margin."""
        self.needs_the_patch()
        self.addCleanup(self.restore)
        self.apply("lateral")
        for start in (True, False):
            with self.subTest(start=start):
                self.side(f"lateral, {start}", start, False)
                self.show()
                before = self.opposite(True)
                x = (before["splitter"][0] + before["splitter"][1]) // 2
                y = before["height"] // 2
                toward = -80 if start else 80  # the page is before the panel with the tabs on the left
                steps = [
                    {"type": "pointerMove", "origin": "viewport", "x": x + toward * i // 8, "y": y, "duration": 16}
                    for i in range(1, 9)
                ]
                actions = [
                    {"type": "pointerMove", "origin": "viewport", "x": x, "y": y, "duration": 50},
                    {"type": "pointerDown", "button": 0},
                    *steps,
                    {"type": "pointerUp", "button": 0},
                ]
                self.m.set_context("chrome")
                try:
                    pointer = {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": actions}
                    self.m.send("WebDriver:PerformActions", {"actions": [pointer]})
                    self.m.send("WebDriver:ReleaseActions")
                finally:
                    self.m.set_context("content")
                was = width(before["panel"])
                after = self.settle(lambda g, was=was: width(g["panel"]) != was, "the panel resized")
                self.assertAlmostEqual(width(after["panel"]), width(before["panel"]) + 80, delta=2, msg=f"{before} / {after}")
                outer = (lambda g: g["width"] - g["panel"][1]) if start else (lambda g: g["panel"][0])
                self.assertEqual(outer(after), outer(before), f"the panel's outer edge moved: {before} / {after}")
                self.assertAlmostEqual(width(after["page"]), width(before["page"]) - 80, delta=2, msg=f"{before} / {after}")
                self.m.chrome("SidebarController._box.style.removeProperty('width');")
                self.opposite(False)

    def test_06_shortcuts_and_the_launcher_open_every_panel_on_that_side(self):
        """The assistant's key (Alt+Shift+A), the engine's bookmarks key and a click on the launcher's history button:
        each panel opens on the side opposite the tabs, the engine's own as well as the assistant."""
        self.needs_the_patch()
        self.addCleanup(self.restore)
        self.apply("lateral")
        self.m.chrome(f"Services.prefs.setBoolPref('{PREF}', true);")
        assistant_key = (
            "[...document.querySelectorAll('#ext-keyset-id-shell_nulavio_net key')].find(k => k.getAttribute('key') === 'A')"
        )
        opened = {
            ASSISTANT: f"{assistant_key}.doCommand();",
            "viewBookmarksSidebar": "document.getElementById('viewBookmarksSidebarKb').doCommand();",
            "viewHistorySidebar": f"{LAUNCHER_BUTTON}.click();",
        }
        for view, how in opened.items():
            with self.subTest(view=view):
                self.m.chrome(how, [view])
                now = self.settle(lambda g, view=view: g["current"] == view and g["panel"] and g["opposite"], view)
                self.assertGreaterEqual(now["panel"][0], now["page"][1], now)
                self.assertGreater(now["width"] - now["panel"][1], 0, now)

    def test_07_every_window_follows_the_setting_and_a_new_one_starts_with_it(self):
        self.needs_the_patch()
        self.addCleanup(self.restore)
        self.apply("lateral")
        opened = chrome_async(
            self.m,
            """
          const w = OpenBrowserWindow();
          await new Promise(resolve => { const obs = subject => { if (subject === w) {
            Services.obs.removeObserver(obs, 'browser-delayed-startup-finished'); resolve(); } };
            Services.obs.addObserver(obs, 'browser-delayed-startup-finished'); });
          return true;
        """,
        )
        self.assertEqual(opened.get("ok"), True, opened)
        close = "for (const w of Services.wm.getEnumerator('navigator:browser')) if (w !== window) w.close();"
        self.addCleanup(self.m.chrome, close)
        marked = (
            "return [...Services.wm.getEnumerator('navigator:browser')].map(w =>"
            " [w.document.documentElement.hasAttribute('nulavio-panel-opposite'), w.SidebarController._box.style.order]);"
        )
        self.m.chrome(f"Services.prefs.setBoolPref('{PREF}', true);")
        self.assertTrue(harness.wait_until(lambda: all(on for on, _ in self.m.chrome(marked)), 10), self.m.chrome(marked))
        self.m.chrome(close)
        # A window opened with the setting on is arranged from its first setPosition().
        opened = chrome_async(
            self.m,
            """
          const w = OpenBrowserWindow();
          await new Promise(resolve => { const obs = subject => { if (subject === w) {
            Services.obs.removeObserver(obs, 'browser-delayed-startup-finished'); resolve(); } };
            Services.obs.addObserver(obs, 'browser-delayed-startup-finished'); });
          return [w.document.documentElement.hasAttribute('nulavio-panel-opposite'), w.SidebarController._box.style.order,
                  w.document.getElementById('tabbrowser-tabbox').style.order];
        """,
        )
        here, box, page = opened.get("ok")
        self.assertTrue(here, opened)
        self.assertGreater(int(box), int(page), opened)
        self.m.chrome(f"Services.prefs.clearUserPref('{PREF}');")
        self.assertTrue(harness.wait_until(lambda: not any(on for on, _ in self.m.chrome(marked)), 10), self.m.chrome(marked))
        orders = "return [SidebarController._box.style.order, document.getElementById('tabbrowser-tabbox').style.order];"
        box, page = self.m.chrome(orders)
        self.assertLess(int(box), int(page), "off, the panel is before the page again")


if __name__ == "__main__":
    unittest.main()
