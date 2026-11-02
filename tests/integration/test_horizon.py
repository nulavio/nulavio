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
import pngdiff
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


RESULTS = """
const [base, done] = arguments;
(async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  gURLBar.focus();
  gURLBar.search(new URL(base).host);
  for (let i = 0; i < 50 && !(gURLBar.view.isOpen && gURLBar.view.visibleRowCount > 1); i++) await wait(100);
  gURLBar.view.selectedRowIndex = 1;
  await wait(300);
  const cs = e => getComputedStyle(e);
  const probe = value => {
    const el = document.createElement("div");
    el.style.color = value;
    document.documentElement.append(el);
    const c = getComputedStyle(el).color;
    el.remove();
    return c;
  };
  const part = (row, sel) => { const e = row.querySelector(sel); return e && e.textContent.trim() ? cs(e).color : null; };
  const describe = row => ({bg: cs(row).backgroundColor, outline: cs(row).outlineStyle, outlineColor: cs(row).outlineColor,
    title: part(row, ".urlbarView-title"), url: part(row, ".urlbarView-url"), action: part(row, ".urlbarView-action")});
  const rows = [...document.querySelectorAll(".urlbarView-row:not([hidden])")];
  const selected = rows.find(r => r.hasAttribute("selected"));
  return {open: gURLBar.view.isOpen, selected: selected ? describe(selected) : null,
    others: rows.filter(r => r !== selected).map(describe),
    panel: cs(document.querySelector("#urlbar .urlbar-background")).backgroundColor,
    tint: probe("var(--nv-color-accent-tint)"), focus: probe("var(--nv-color-focus)")};
})().then(done, e => done({error: String(e)}));
"""


SYMBOLS = """
const [view, selectShell, done] = arguments;
(async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const url = WebExtensionPolicy.getByID("shell@nulavio.net").getURL("settings/settings.html");
  let tab = gBrowser.tabs.find(t => t.linkedBrowser.currentURI.spec === url);
  if (!tab) {
    tab = gBrowser.addTrustedTab(url);
  }
  gBrowser.selectedTab = selectShell ? tab : gBrowser.tabs.find(t => t !== tab && !t.pinned);
  await SidebarController.promiseInitialized;
  await SidebarController.show(view);
  await wait(1500);
  const main = document.querySelector("sidebar-main");
  await main.updateComplete;
  const deep = (root, out = []) => {
    for (const el of root.querySelectorAll("*")) {
      if (el.localName === "moz-button" && el.getAttribute("view")) out.push(el);
      if (el.shadowRoot) deep(el.shadowRoot, out);
    }
    return out;
  };
  const rect = e => { const b = e.getBoundingClientRect(); return [b.x, b.y, b.width, b.height]; };
  const launcher = deep(main.shadowRoot).find(b => b.getAttribute("view") === "shell_nulavio_net-sidebar-action");
  const action = document.getElementById("shell_nulavio_net-BAP");
  return {
    dpr: devicePixelRatio,
    tab: rect(tab.querySelector(".tab-icon-image")),
    action: rect(action.querySelector(".toolbarbutton-icon")),
    launcher: launcher ? rect(launcher.shadowRoot.querySelector("img")) : null,
    open: launcher?.getAttribute("type") === "icon",
  };
})().then(done, e => done({error: String(e)}));
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


def symbol_on_surface(png: bytes, rect: list[float], dpr: float) -> tuple[str, str]:
    """(symbol colour, surface colour) in a rendered icon box: the surface is the most common colour, the
    symbol the most common one that clearly differs from it (anti-aliased edges are rarer)."""
    width, height, bpp, rows = pngdiff.decode(png)
    x0, y0, w, h = (round(v * dpr) for v in rect)
    counts: dict[str, int] = {}
    for y in range(max(0, y0), min(height, y0 + h)):
        row = rows[y]
        for x in range(max(0, x0), min(width, x0 + w)):
            key = "#" + bytes(row[x * bpp : x * bpp + 3]).hex().upper()
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts, key=counts.get, reverse=True)
    surface = ranked[0]
    symbol = next((c for c in ranked[1:] if ratio(c, surface) > 1.25), surface)
    return symbol, surface


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
            # UX3F M6: distinct dark surface steps (toolbar navy.875, selected tab navy.750).
            self.assertEqual(rgb(s["navbar"]), "#0F1C2A")
            self.assertEqual(rgb(s["selectedBg"]), "#1E4252")
            self.assert_contrast(s["selectedText"], s["selectedBg"], 4.5, "selected tab label")
            self.assert_contrast(s["otherText"], s["toolbox"], 4.5, "background tab label")
            self.assert_contrast(s["fieldText"], s["fieldBg"], 4.5, "address text")
            self.assert_contrast(s["fieldBorder"], s["navbar"], 3.0, "address field boundary")
            self.assert_contrast(s["mark"]["color"], s["selectedBg"], 3.0, "selected-tab mark")
        finally:
            self.set_pref("ui.systemUsesDarkTheme", 0)

    def test_04_route_mark_only_on_the_selected_tab(self):
        # D-UX2: a fresh Nulavio profile starts in Lateral (vertical tabs, 3px x 20px edge mark, UX3F A5);
        # switching to horizontal tabs yields the 16px x 2px mark, still only on the selected tab.
        self.assertEqual(self.m.chrome("return document.getElementById('tabbrowser-tabs').getAttribute('orient');"), "vertical")
        s = self.state()
        self.assertEqual(s["mark"]["content"], '""')
        self.assertEqual((s["mark"]["w"], s["mark"]["h"]), ("3px", "20px"))
        self.assertEqual(rgb(s["mark"]["color"]), rgb(s["accent"]))
        self.assertEqual(s["otherMark"], "none")
        self.set_pref("sidebar.verticalTabs", False)
        try:
            horizontal = harness.wait_until(
                lambda: (
                    self.m.chrome("return document.getElementById('tabbrowser-tabs').getAttribute('orient');") == "horizontal"
                ),
                timeout=10,
            )
            self.assertTrue(horizontal, "horizontal tabs did not engage")
            s_horiz = self.state()
            self.assertEqual(s_horiz["mark"]["content"], '""')
            self.assertEqual((s_horiz["mark"]["w"], s_horiz["mark"]["h"]), ("16px", "2px"))
            self.assertEqual(rgb(s_horiz["mark"]["color"]), rgb(s_horiz["accent"]))
            self.assertEqual(s_horiz["otherMark"], "none")
        finally:
            self.set_pref("sidebar.verticalTabs", True)
            harness.wait_until(
                lambda: self.m.chrome("return document.getElementById('tabbrowser-tabs').getAttribute('orient');") == "vertical",
                timeout=10,
            )

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
                harness.wait_until(lambda: rgb(self.state()["navbar"]) == "#0F1C2A", timeout=10), "Dark != Horizon dark"
            )
            self.assertTrue(self.enable_theme("firefox-alpenglow@mozilla.org"))
            self.assertTrue(harness.wait_until(lambda: self.state()["lwtheme"], timeout=10), "theme not applied")
            s = self.state()
            self.assertNotIn(rgb(s["navbar"]), ("#0F1C2A", "#F1F7F5"), "Horizon colours leaked into a user theme")
            self.assertEqual(rgb(s["mark"]["color"]), rgb(s["selectedText"]), "mark follows the theme's text colour")
        finally:
            self.enable_theme("default-theme@mozilla.org")
            harness.wait_until(lambda: not self.state()["lwtheme"], timeout=10)

    def test_12_reduced_motion_disables_the_mark_animation(self):
        # The default Lateral strip uses the vertical keyframes (UX3F B4).
        self.assertIn(self.state()["mark"]["animation"], ("nulavio-route-in", "nulavio-route-in-v"))
        self.set_pref("ui.prefersReducedMotion", 1)
        try:
            self.assertEqual(self.state()["mark"]["animation"], "none")
        finally:
            self.clear_pref("ui.prefersReducedMotion")

    def test_13_vertical_tabs_get_a_vertical_mark(self):
        try:
            self.set_pref("sidebar.verticalTabs", False)
            horizontal = harness.wait_until(
                lambda: (
                    self.m.chrome("return document.getElementById('tabbrowser-tabs').getAttribute('orient');") == "horizontal"
                ),
                timeout=10,
            )
            self.assertTrue(horizontal, "horizontal tabs did not engage")
            self.assertEqual((self.state()["mark"]["w"], self.state()["mark"]["h"]), ("16px", "2px"))
            self.set_pref("sidebar.verticalTabs", True)
            vertical = harness.wait_until(
                lambda: self.m.chrome("return document.getElementById('tabbrowser-tabs').getAttribute('orient');") == "vertical",
                timeout=10,
            )
            self.assertTrue(vertical, "vertical tabs did not engage")
            s = self.state()
            self.assertEqual((s["mark"]["w"], s["mark"]["h"]), ("3px", "20px"))
            self.assertEqual(rgb(s["mark"]["color"]), rgb(s["accent"]))
        finally:
            self.set_pref("sidebar.verticalTabs", True)
            harness.wait_until(
                lambda: self.m.chrome("return document.getElementById('tabbrowser-tabs').getAttribute('orient');") == "vertical",
                timeout=10,
            )

    def results_row(self) -> dict:
        """Open the address-bar results for the fixture server and select the second row (keyboard selection)."""
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(RESULTS, [self.server.url("/")])
        finally:
            self.m.set_context("content")

    def test_14_address_bar_results_selected_row_is_readable_and_visible(self):
        # WCS-09: the keyboard-selected result used the system SelectedItem (white on #3399FF, 2.9:1 in light;
        # a cyan row in dark). Horizon gives it the accent tint, primary text and the focus ring.
        for dark in (0, 1):
            with self.subTest(scheme="dark" if dark else "light"):
                self.set_pref("ui.systemUsesDarkTheme", dark)
                try:
                    self.assertTrue(harness.wait_until(lambda want=bool(dark): self.state()["dark"] == want, timeout=10))
                    r = self.results_row()
                    self.assertTrue(r["open"] and r["selected"], r)
                    sel = r["selected"]
                    self.assertEqual(rgb(sel["bg"]), rgb(r["tint"]), "selected row is not in the accent tint")
                    for part in ("title", "url", "action"):
                        if sel[part]:
                            self.assert_contrast(sel[part], sel["bg"], 4.5, f"selected result {part}")
                    self.assertEqual((sel["outline"], rgb(sel["outlineColor"])), ("solid", rgb(r["focus"])), sel)
                    self.assert_contrast(sel["outlineColor"], r["panel"], 3.0, "selected-row ring on the results panel")
                    for row in r["others"]:
                        self.assertEqual(row["outline"], "none", "only the selected row carries the ring")
                        self.assert_contrast(row["title"], r["panel"], 4.5, "result title")
                        if row["url"]:
                            self.assert_contrast(row["url"], r["panel"], 4.5, "result URL")
                finally:
                    self.m.chrome("gURLBar.view.close(); gURLBar.blur();")
                    self.set_pref("ui.systemUsesDarkTheme", 0)

    def test_15_the_nulavio_symbol_follows_the_colour_scheme(self):
        # WCS-11: the Shell shipped one mint-on-dark symbol (1.3-1.6:1 on light chrome). It is now Mint 700 in
        # light and mint in dark (one SVG with a colour-scheme query) on the tab, the toolbar button and the
        # sidebar launcher, and stays >= 3:1 where it sits, including the launcher's pressed (open) state.
        expected = {0: "#0F7A68", 1: "#6FE0C5"}
        # UX3F B2: in the launcher the assistant is a tool glyph in the chrome icon colour.
        launcher_expected = {0: "#23495A", 1: "#BFD0D6"}
        try:
            for dark, vertical in ((0, False), (0, True), (1, False), (1, True)):
                self.set_pref("ui.systemUsesDarkTheme", dark)
                self.set_pref("sidebar.verticalTabs", vertical)
                self.assertTrue(harness.wait_until(lambda want=bool(dark): self.state()["dark"] == want, timeout=10))
                for view, select_shell in (("shell_nulavio_net-sidebar-action", True), ("viewBookmarksSidebar", False)):
                    self.m.set_context("chrome")
                    try:
                        boxes = self.m.execute_async(SYMBOLS, [view, select_shell])
                        png = self.m.screenshot_png()
                    finally:
                        self.m.set_context("content")
                    self.assertNotIn("error", boxes, boxes)
                    self.assertTrue(boxes["launcher"], "the assistant is missing from the sidebar launcher")
                    self.assertEqual(boxes["open"], view != "viewBookmarksSidebar")
                    tab_state = "selected" if select_shell else "background"
                    launcher_state = "open" if boxes["open"] else "closed"
                    for where in ("tab", "action", "launcher"):
                        state = {"tab": tab_state, "launcher": launcher_state}.get(where, "")
                        with self.subTest(scheme="dark" if dark else "light", vertical=vertical, where=where, state=state):
                            symbol, surface = symbol_on_surface(png, boxes[where], boxes["dpr"])
                            want = launcher_expected[dark] if where == "launcher" else expected[dark]
                            self.assertEqual(symbol, want, f"symbol {symbol} on {surface}")
                            self.assertGreaterEqual(ratio(symbol, surface), 3.0, f"{symbol} on {surface}")
        finally:
            self.m.chrome("SidebarController.hide();")
            self.clear_pref("sidebar.verticalTabs")
            self.set_pref("ui.systemUsesDarkTheme", 0)


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
