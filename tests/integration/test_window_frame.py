"""ADR 0010, "Uma superfície": the window's frame is one tone and the page is a card inside it.

Nothing is hidden by it: the margin is on the sides that have no chrome, a band that states something keeps
its fill, and full screen has no card."""

from __future__ import annotations

import unittest

import harness

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
# The frame of a window (this one, or the other one when `arguments[0]` is true), as it is drawn.
FRAME = """
const win = arguments[0] ? [...Services.wm.getEnumerator("navigator:browser")].find(w => w !== window) : window;
const doc = win.document;
const tone = el => win.getComputedStyle(el).backgroundColor;
const box = doc.getElementById("tabbrowser-tabbox");
const card = win.getComputedStyle(box);
const rect = box.getBoundingClientRect();
const band = doc.getElementById("nulavio-band");
const px = value => Math.round(parseFloat(value));
return {
  tones: {
    band: tone(band), toolbox: tone(doc.getElementById("navigator-toolbox")), tabs: tone(doc.getElementById("sidebar-container")),
  },
  frame: win.getComputedStyle(doc.documentElement).getPropertyValue("--toolbar-background-color").trim(),
  neutral: band.hasAttribute("nv-neutral"),
  // The rule line under the band, if one is drawn: its colour, or transparent when there is none.
  bandLine: (cs => (parseFloat(cs.borderBlockEndWidth) > 0 && cs.borderBlockEndStyle !== "none"
    ? cs.borderBlockEndColor : "rgba(0, 0, 0, 0)"))(win.getComputedStyle(band)),
  row: tone(band.querySelector(".nv-band-row")),
  radius: px(card.borderTopLeftRadius),
  outline: [card.outlineStyle, px(card.outlineWidth)],
  shadow: card.boxShadow,
  // The gap between the page and each edge of the window, in pixels: 0 where chrome sits on that side.
  gap: { left: px(card.marginLeft), right: px(card.marginRight), bottom: px(card.marginBottom), top: px(card.marginTop) },
  edges: {
    left: Math.round(rect.left),
    right: Math.round(win.innerWidth - rect.right),
    bottom: Math.round(win.innerHeight - rect.bottom),
  },
};
"""


@unittest.skipUnless(harness.nulavio_engine(), "the frame needs the built-in Shell on the engine")
class WindowFrameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Moldura")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()
        cls.page = cls.server.url("/page/Moldura")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def setUp(self):
        self.m.navigate(self.page)
        self.apply("lateral")

    def apply(self, preset: str) -> None:
        self.m.chrome(f"return {LAYOUT}.apply(window, arguments[0]).then(() => true);", [preset])

    def frame(self, other: bool = False) -> dict:
        return self.m.chrome(FRAME, [other])

    def settled(self, want, other: bool = False) -> dict:
        harness.wait_until(lambda: want(self.frame(other)), 10)
        return self.frame(other)

    def test_01_one_tone_and_the_page_is_a_card(self):
        frame = self.settled(lambda f: f["gap"]["right"] == 8)
        # Band, toolbar and tab column: the same tone, or nothing of their own over the frame's.
        resolved = self.m.chrome(
            "const probe = document.createElement('div'); probe.style.backgroundColor = arguments[0];"
            "document.documentElement.append(probe); const c = getComputedStyle(probe).backgroundColor;"
            "probe.remove(); return c;",
            [frame["frame"]],
        )
        for part, tone in frame["tones"].items():
            self.assertIn(tone, (resolved, "rgba(0, 0, 0, 0)"), f"{part}: {frame}")
        self.assertTrue(frame["neutral"], frame)
        self.assertEqual(frame["tones"]["band"], resolved, "the neutral band takes the frame's tone")
        self.assertIn(frame["row"], (resolved, "rgba(0, 0, 0, 0)"), frame)
        self.assertEqual(frame["bandLine"], "rgba(0, 0, 0, 0)", "no rule line under the neutral band")
        # The card: a radius, one hairline, no second line from a shadow.
        self.assertEqual((frame["radius"], frame["outline"], frame["shadow"]), (10, ["solid", 1], "none"), frame)
        # Tabs on the left: the page touches them, and stands off the right and bottom edges of the window.
        self.assertEqual(frame["gap"], {"left": 0, "right": 8, "bottom": 8, "top": 0}, frame)
        self.assertEqual((frame["edges"]["right"], frame["edges"]["bottom"]), (8, 8), frame)

    def test_01b_a_panel_beside_the_tabs_is_a_second_card(self):
        self.m.chrome("SidebarController.show('viewBookmarksSidebar');")
        self.addCleanup(self.m.chrome, "SidebarController.hide();")
        panel = """
          const box = document.getElementById("sidebar-box"), page = document.getElementById("tabbrowser-tabbox");
          const cs = getComputedStyle(box), b = box.getBoundingClientRect(), p = page.getBoundingClientRect();
          if (box.hidden || !b.width) return null;
          const px = value => Math.round(parseFloat(value));
          return {
            radius: px(cs.borderTopLeftRadius), outline: [cs.outlineStyle, px(cs.outlineWidth)],
            bottom: Math.round(innerHeight - b.bottom), gap: Math.round(p.left - b.right),
            pageBottom: Math.round(innerHeight - p.bottom),
          };
        """
        seen = harness.wait_until(lambda: self.m.chrome(panel), 15)
        self.assertEqual(seen, {"radius": 10, "outline": ["solid", 1], "bottom": 8, "gap": 8, "pageBottom": 8})

    def test_02_the_margin_is_on_the_sides_without_chrome(self):
        # The tab column on the other side: the margin changes sides with it.
        self.m.chrome("Services.prefs.setBoolPref('sidebar.position_start', false);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('sidebar.position_start');")
        frame = self.settled(lambda f: f["gap"]["left"] == 8)
        self.assertEqual((frame["gap"]["left"], frame["gap"]["right"], frame["edges"]["left"]), (8, 0, 8), frame)
        self.m.chrome("Services.prefs.clearUserPref('sidebar.position_start');")
        self.assertEqual(self.settled(lambda f: f["gap"]["right"] == 8)["gap"]["left"], 0)
        # Right to left: the same rule, mirrored.
        self.m.chrome("Services.prefs.setStringPref('intl.l10n.pseudo', 'bidi');")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('intl.l10n.pseudo');")
        frame = self.settled(lambda f: f["gap"]["left"] == 8)
        self.assertEqual((frame["gap"]["left"], frame["gap"]["right"], frame["edges"]["left"]), (8, 0, 8), frame)
        self.m.chrome("Services.prefs.clearUserPref('intl.l10n.pseudo');")
        self.settled(lambda f: f["gap"]["right"] == 8)
        # Immersive: no chrome on either side, a margin on both.
        self.m.chrome("Services.prefs.setBoolPref('nulavio.layout.immersive', true); gBrowser.selectedBrowser.focus();")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('nulavio.layout.immersive');")
        frame = self.settled(lambda f: f["gap"]["left"] == 8)
        self.assertEqual((frame["gap"]["left"], frame["gap"]["right"], frame["gap"]["bottom"]), (8, 8, 8), frame)
        self.m.chrome("Services.prefs.clearUserPref('nulavio.layout.immersive');")
        # Tabs on top and Foco keep a card with the same radius and hairline.
        for preset in ("top", "focus"):
            with self.subTest(preset=preset):
                self.apply(preset)
                frame = self.settled(lambda f: f["gap"]["right"] == 8 and f["radius"] == 10)
                self.assertEqual(
                    (frame["radius"], frame["outline"], frame["gap"]["right"], frame["gap"]["bottom"]), (10, ["solid", 1], 8, 8)
                )
                # With tabs on top the band is a row of its own: still the frame's tone, still no line under it.
                self.assertEqual(frame["bandLine"], "rgba(0, 0, 0, 0)", frame)

    def test_03_full_screen_has_no_card(self):
        self.m.chrome("window.fullScreen = true;")
        self.addCleanup(self.m.chrome, "window.fullScreen = false;")
        frame = self.settled(lambda f: f["radius"] == 0)
        self.assertEqual((frame["radius"], frame["gap"]), (0, {"left": 0, "right": 0, "bottom": 0, "top": 0}), frame)
        self.m.chrome("window.fullScreen = false;")
        self.assertEqual(self.settled(lambda f: f["radius"] == 10)["radius"], 10)

    def test_03b_a_short_window_keeps_every_pixel_for_the_page(self):
        # A 1280 x 800 screen at 150 % is 853 x 533 CSS pixels: no margin and no radius there.
        self.m.send("WebDriver:SetWindowRect", {"width": 853, "height": 533})
        self.addCleanup(self.m.send, "WebDriver:SetWindowRect", {"width": 1280, "height": 800})
        frame = self.settled(lambda f: f["radius"] == 0)
        self.assertEqual(
            (frame["radius"], frame["gap"]["bottom"], frame["gap"]["right"], frame["edges"]["bottom"]), (0, 0, 0, 0), frame
        )
        self.m.send("WebDriver:SetWindowRect", {"width": 1280, "height": 800})
        self.assertEqual(self.settled(lambda f: f["radius"] == 10)["gap"]["bottom"], 8)

    def test_04_a_band_that_states_something_keeps_its_fill_and_its_line(self):
        plain = self.settled(lambda f: f["gap"]["right"] == 8)
        opened = self.m.chrome("""
          const win = OpenBrowserWindow({ private: true });
          return new Promise(resolve => win.addEventListener("load", () => resolve(true), { once: true }));
        """)
        self.assertTrue(opened)
        close = "[...Services.wm.getEnumerator('navigator:browser')].find(w => w !== window)?.close();"
        self.addCleanup(self.m.chrome, close)
        private = self.settled(lambda f: not f["neutral"] and f["radius"] == 10, other=True)
        self.assertFalse(private["neutral"], private)
        # The private band is not the frame's tone, its row is filled, and its rule line is drawn.
        self.assertNotEqual(private["row"], "rgba(0, 0, 0, 0)", private)
        self.assertNotEqual(private["row"], plain["tones"]["band"], private)
        self.assertNotEqual(private["bandLine"], "rgba(0, 0, 0, 0)", private)
        # The page is a card there too, in the private window's own (themed) colours: the frame's tone is
        # not Nulavio's there, only the shape is.
        self.assertEqual((private["radius"], private["outline"], private["gap"]["right"]), (10, ["solid", 1], 8), private)
        self.assertNotEqual(private["frame"], plain["frame"], private)

    def test_05_more_contrast_and_forced_colours_keep_the_cards_edge(self):
        edge = "return getComputedStyle(document.getElementById('tabbrowser-tabbox')).outlineColor;"
        normal = self.m.chrome(edge)
        # The system's contrast setting (the engine exempts its own windows from forced colours on some
        # platforms, so the sheet answers to either query, as it does for the band).
        self.m.chrome("Services.prefs.setIntPref('ui.useAccessibilityTheme', 1);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('ui.useAccessibilityTheme');")
        forced = harness.wait_until(lambda: self.m.chrome(edge) != normal and self.m.chrome(edge), 10)
        self.assertTrue(forced, "the edge takes the system's text colour")
        canvas_text = self.m.chrome(
            "const p = document.createElement('div'); p.style.color = 'CanvasText'; document.documentElement.append(p);"
            "const c = getComputedStyle(p).color; p.remove(); return c;"
        )
        self.assertEqual(forced, canvas_text)
        frame = self.frame()
        self.assertEqual(frame["outline"], ["solid", 1], frame)


if __name__ == "__main__":
    unittest.main()
