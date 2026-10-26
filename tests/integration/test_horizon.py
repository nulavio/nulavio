"""Nulavio Horizon window theme (Track B): applied, accessible, and stepping aside when it should.

Runs against the Nulavio build only (the theme ships inside it; distribution
Firefox has no Horizon). Colours are checked on the rendered window, so the
contrast ratios below are what users see, not what the tokens promise.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "brand"))
import harness
from contrast import ratio

SHEET = "chrome://branding/content/theme/horizon.css"

STATE = """
const cs = (el, pseudo) => getComputedStyle(el, pseudo || null);
const probe = (value) => {  // resolve a CSS colour expression against the chrome root
  const el = document.createElement("div");
  el.style.color = value;
  document.documentElement.append(el);
  const c = getComputedStyle(el).color;
  el.remove();
  return c;
};
const selected = gBrowser.selectedTab;
const other = gBrowser.tabs.find(t => !t.selected && !t.pinned);
const label = t => t.querySelector(".tab-label");
const bg = t => t.querySelector(".tab-background");
const mark = cs(bg(selected), "::after");
const field = document.querySelector("#urlbar .urlbar-background");
return {
  sheet: [...document.styleSheets].some(s => s.href === arguments[0]),
  pref: Services.prefs.getBoolPref("nulavio.horizon.enabled", false),
  lwtheme: document.documentElement.hasAttribute("lwtheme"),
  dark: matchMedia("(prefers-color-scheme: dark)").matches,
  forced: matchMedia("(forced-colors)").matches,
  navbar: cs(document.getElementById("nav-bar")).backgroundColor,
  toolbox: probe("var(--toolbox-background-color)"),
  accent: probe("var(--nv-color-accent-default)"),
  focus: probe("var(--focus-outline-color)"),
  selectedText: cs(label(selected)).color,
  selectedBg: cs(bg(selected)).backgroundColor,
  otherText: other ? cs(label(other)).color : null,
  otherMark: other ? cs(bg(other), "::after").content : null,
  fieldBg: cs(field).backgroundColor,
  fieldBorder: cs(field).borderTopColor,
  fieldText: cs(document.getElementById("urlbar-input") || document.querySelector("#urlbar input")).color,
  mark: {content: mark.content, w: mark.width, h: mark.height, color: mark.backgroundColor, animation: mark.animationName},
  tabMinHeight: cs(document.documentElement).getPropertyValue("--tab-min-height").trim(),
  urlbarHeight: cs(document.documentElement).getPropertyValue("--urlbar-height").trim(),
};
"""


def rgb(css: str) -> str:
    """'rgb(1, 2, 3)' / 'rgba(...)' / 'color(srgb r g b)' -> '#RRGGBB' (alpha ignored)."""
    css = css.strip()
    if css.startswith("color(srgb"):
        parts = [float(v) for v in css[len("color(srgb") :].strip(" )").split()[:3]]
        values = [round(v * 255) for v in parts]
    else:
        values = [round(float(v)) for v in css[css.index("(") + 1 : css.index(")")].replace("/", ",").split(",")[:3]]
    return "#" + "".join(f"{v:02X}" for v in values)


@unittest.skipUnless(harness.engine_available(), "no supported Gecko engine installed")
class HorizonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        harness.TEST_PREFS.update({"ui.systemUsesDarkTheme": 0})
        cls.session = harness.Session(profile="horizon")
        cls.m = cls.session.start()
        if cls.m.chrome("return Services.appinfo.name;") != "Nulavio":
            cls.tearDownClass()
            raise unittest.SkipTest("Horizon ships in the Nulavio build only")
        cls.m.chrome(
            "const [b, n] = arguments; for (const x of n) gBrowser.addTrustedTab(b + x);"
            "gBrowser.pinTab(gBrowser.addTrustedTab(b + 'Pinned'));"
            "gBrowser.selectedTab = gBrowser.tabs[gBrowser.tabs.length - 1];",
            [cls.server.url("/page/"), ["Inbox", "Research"]],
        )
        cls.m.chrome("gBrowser.selectedTab = gBrowser.tabs.find(t => t.label === 'Research');")
        time.sleep(1.5)

    @classmethod
    def tearDownClass(cls):
        harness.TEST_PREFS.pop("ui.systemUsesDarkTheme", None)
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def state(self) -> dict:
        return self.m.chrome(STATE, [SHEET])

    def set_pref(self, name: str, value) -> None:
        kind = {bool: "Bool", int: "Int", str: "String"}[type(value)]
        self.m.chrome(f"Services.prefs.set{kind}Pref(arguments[0], arguments[1]);", [name, value])
        time.sleep(0.6)

    def clear_pref(self, name: str) -> None:
        self.m.chrome("Services.prefs.clearUserPref(arguments[0]);", [name])
        time.sleep(0.6)

    def assert_contrast(self, fg: str, bg: str, minimum: float, what: str) -> None:
        value = ratio(rgb(fg), rgb(bg))
        self.assertGreaterEqual(value, minimum, f"{what}: {rgb(fg)} on {rgb(bg)} = {value:.2f}")

    # -- applied ---------------------------------------------------------
    def test_01_theme_loaded_and_enabled_by_default(self):
        s = self.state()
        self.assertTrue(s["sheet"], "browser.xhtml does not load the Horizon stylesheet (patch 0003)")
        self.assertTrue(s["pref"])

    def test_02_light_colours_and_rendered_contrast(self):
        s = self.state()
        self.assertFalse(s["dark"])
        self.assertEqual(rgb(s["navbar"]), "#F1F7F5")
        self.assertEqual(rgb(s["toolbox"]), "#E2EBEE")
        self.assertEqual(rgb(s["selectedBg"]), "#FFFFFF")
        self.assert_contrast(s["selectedText"], s["selectedBg"], 4.5, "selected tab label")
        self.assert_contrast(s["otherText"], s["toolbox"], 4.5, "background tab label")
        self.assert_contrast(s["fieldText"], s["fieldBg"], 4.5, "address text")
        self.assert_contrast(s["fieldBorder"], s["navbar"], 3.0, "address field boundary")
        self.assert_contrast(s["focus"], s["navbar"], 3.0, "focus ring on toolbar")
        self.assert_contrast(s["mark"]["color"], s["selectedBg"], 3.0, "selected-tab mark")

    def test_03_dark_colours_and_rendered_contrast(self):
        self.set_pref("ui.systemUsesDarkTheme", 1)
        try:
            self.assertTrue(harness.wait_until(lambda: self.state()["dark"], timeout=10), "dark scheme not applied")
            s = self.state()
            self.assertEqual(rgb(s["navbar"]), "#0B1623")
            self.assertEqual(rgb(s["selectedBg"]), "#183746")
            self.assert_contrast(s["selectedText"], s["selectedBg"], 4.5, "selected tab label")
            self.assert_contrast(s["otherText"], s["toolbox"], 4.5, "background tab label")
            self.assert_contrast(s["fieldText"], s["fieldBg"], 4.5, "address text")
            self.assert_contrast(s["fieldBorder"], s["navbar"], 3.0, "address field boundary")
            self.assert_contrast(s["mark"]["color"], s["selectedBg"], 3.0, "selected-tab mark")
        finally:
            self.set_pref("ui.systemUsesDarkTheme", 0)

    def test_04_route_mark_only_on_the_selected_tab(self):
        s = self.state()
        self.assertEqual(s["mark"]["content"], '""')
        self.assertEqual((s["mark"]["w"], s["mark"]["h"]), ("16px", "2px"))
        self.assertEqual(rgb(s["mark"]["color"]), rgb(s["accent"]))
        self.assertEqual(s["otherMark"], "none")

    def test_05_densities_keep_their_sizes(self):
        # Computed custom properties come back with var() already substituted.
        self.assertEqual(self.state()["tabMinHeight"], "34px")
        for density, tab, field in ((1, "30px", "max(30px, 1.4em)"), (2, "41px", "max(40px, 1.4em)")):
            self.set_pref("browser.uidensity", density)
            s = self.state()
            self.assertEqual((s["tabMinHeight"], s["urlbarHeight"]), (tab, field), f"density {density}")
        self.clear_pref("browser.uidensity")
        height = self.m.chrome("return gBrowser.selectedTab.getBoundingClientRect().height;")
        self.assertGreaterEqual(height, 34)

    # -- usable and safe --------------------------------------------------
    def test_06_controls_meet_the_minimum_target_size(self):
        sizes = self.m.chrome(
            "return ['back-button','stop-reload-button','unified-extensions-button','PanelUI-menu-button',"
            "'new-tab-button','tabs-newtab-button']"
            ".map(id => document.getElementById(id)).filter(e => e && e.getBoundingClientRect().width > 0)"
            ".map(e => ({id: e.id, w: e.getBoundingClientRect().width, h: e.getBoundingClientRect().height}));"
        )
        self.assertTrue(any(s["id"] == "unified-extensions-button" for s in sizes), "extensions button missing")
        for s in sizes:
            self.assertGreaterEqual(min(s["w"], s["h"]), 24, f"{s['id']} below WCAG 2.5.8 target size: {s}")

    def test_07_security_ui_is_untouched(self):
        # Trust, tracking-protection, permission and remote-control indicators must
        # look the same (shown or hidden, same size) with Horizon on and off.
        probe = (
            "return ['trust-icon-container','tracking-protection-icon-container','identity-permission-box',"
            "'remote-control-box','notification-popup-box']"
            ".map(id => document.getElementById(id))"
            ".map(e => e && {id: e.id, display: getComputedStyle(e).display, visibility: getComputedStyle(e).visibility,"
            " w: Math.round(e.getBoundingClientRect().width)});"
        )
        on = self.m.chrome(probe)
        self.set_pref("nulavio.horizon.enabled", False)
        try:
            off = self.m.chrome(probe)
        finally:
            self.clear_pref("nulavio.horizon.enabled")
        self.assertTrue(on[0] and on[0]["display"] != "none", "trust indicator hidden")
        self.assertEqual([(x or {}).get("display") for x in on], [(x or {}).get("display") for x in off])
        self.assertEqual([(x or {}).get("visibility") for x in on], [(x or {}).get("visibility") for x in off])

    def test_08_keyboard_focus_is_visible_in_the_address_bar(self):
        self.m.chrome("gURLBar.select();")
        time.sleep(0.4)
        border = self.m.chrome(
            "const b = document.querySelector('#urlbar .urlbar-background'); const c = getComputedStyle(b);"
            "return {color: c.borderTopColor, outline: c.outlineColor, outlineStyle: c.outlineStyle, focused: gURLBar.focused};"
        )
        self.m.chrome("gURLBar.blur();")
        self.assertTrue(border["focused"])
        ring = border["color"] if rgb(border["color"]) == rgb(self.state()["focus"]) else border["outline"]
        self.assertEqual(rgb(ring), rgb(self.state()["focus"]), border)

    # -- stepping aside ---------------------------------------------------
    def test_09_pref_off_restores_the_upstream_look(self):
        self.set_pref("nulavio.horizon.enabled", False)
        try:
            s = self.state()
            self.assertNotEqual(rgb(s["navbar"]), "#F1F7F5")
            self.assertEqual(s["mark"]["content"], "none")
            self.assertNotIn("nv-size", s["tabMinHeight"])
        finally:
            self.clear_pref("nulavio.horizon.enabled")
        self.assertEqual(rgb(self.state()["navbar"]), "#F1F7F5")

    def enable_theme(self, addon_id: str) -> bool:
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(
                "const [id, done] = arguments;"
                "const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');"
                "AddonManager.getAddonByID(id).then(a => a ? a.enable().then(() => true) : false).then(done);",
                [addon_id],
            )
        finally:
            self.m.set_context("content")

    def test_10_user_theme_keeps_its_colours(self):
        # Firefox 158's built-in Light/Dark themes only pick the colour scheme
        # ([theme-in-app]): they get Horizon light/dark. Colourful and installed
        # themes ([lwtheme]) keep their own colours.
        if not self.enable_theme("firefox-compact-dark@mozilla.org"):
            self.skipTest("built-in themes not available")
        try:
            self.assertTrue(
                harness.wait_until(lambda: rgb(self.state()["navbar"]) == "#0B1623", timeout=10), "Dark != Horizon dark"
            )
            self.assertTrue(self.enable_theme("firefox-alpenglow@mozilla.org"))
            self.assertTrue(harness.wait_until(lambda: self.state()["lwtheme"], timeout=10), "theme not applied")
            s = self.state()
            self.assertNotIn(rgb(s["navbar"]), ("#0B1623", "#F1F7F5"), "Horizon colours leaked into a user theme")
            self.assertEqual(rgb(s["mark"]["color"]), rgb(s["selectedText"]), "mark follows the theme's text colour")
        finally:
            self.enable_theme("default-theme@mozilla.org")
            harness.wait_until(lambda: not self.state()["lwtheme"], timeout=10)

    def test_12_reduced_motion_disables_the_mark_animation(self):
        self.assertEqual(self.state()["mark"]["animation"], "nulavio-route-in")
        self.set_pref("ui.prefersReducedMotion", 1)
        try:
            self.assertEqual(self.state()["mark"]["animation"], "none")
        finally:
            self.clear_pref("ui.prefersReducedMotion")

    def test_13_vertical_tabs_get_a_vertical_mark(self):
        self.set_pref("sidebar.verticalTabs", True)
        try:
            vertical = harness.wait_until(
                lambda: self.m.chrome("return document.getElementById('tabbrowser-tabs').getAttribute('orient');") == "vertical",
                timeout=10,
            )
            self.assertTrue(vertical, "vertical tabs did not engage")
            s = self.state()
            self.assertEqual((s["mark"]["w"], s["mark"]["h"]), ("2px", "16px"))
        finally:
            self.set_pref("sidebar.verticalTabs", False)


@unittest.skipUnless(harness.engine_available(), "no supported Gecko engine installed")
class HorizonHighContrastTest(unittest.TestCase):
    """A high-contrast preference must win over Horizon colours (it is read at startup).

    Forced colours cannot be simulated for the browser window on Linux in this
    harness; the same media query guards both (docs/design/accessibility.md).
    """

    def test_high_contrast_preference_replaces_horizon_colours(self):
        harness.TEST_PREFS["ui.useAccessibilityTheme"] = 1
        session = harness.Session(profile="contrast")
        try:
            m = session.start()
            if m.chrome("return Services.appinfo.name;") != "Nulavio":
                self.skipTest("Horizon ships in the Nulavio build only")
            s = m.chrome(
                "return {contrast: matchMedia('(prefers-contrast)').matches,"
                " navbar: getComputedStyle(document.getElementById('nav-bar')).backgroundColor,"
                " mark: getComputedStyle(gBrowser.selectedTab.querySelector('.tab-background'), '::after').content};"
            )
            self.assertTrue(s["contrast"], "high-contrast preference not active")
            self.assertNotIn(rgb(s["navbar"]), ("#F1F7F5", "#0B1623"), "Horizon colours override high contrast")
            self.assertEqual(s["mark"], '""', "the selection mark (a non-colour cue) stays")
        finally:
            harness.TEST_PREFS.pop("ui.useAccessibilityTheme", None)
            session.cleanup()


if __name__ == "__main__":
    unittest.main()
