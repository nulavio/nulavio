"""#318: a calm page-loading line along the top of the page. It follows the engine's progress for the selected tab's
document, goes at once when the document has loaded or the load stops, never shows for a background tab, sits on the
page under the toolbar, the band and any notification bar, is neutral (never a status colour or the band's), is
decorative for assistive technology, and holds still under reduced motion. #458: off in a new profile, with nothing
attached to the window; a switch in Settings, Aparência, turns it on and off at once, also while a page loads."""

from __future__ import annotations

import time
import unittest

import harness
import settings_page

PERSONALISE = (
    'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs").NulavioPersonalise'
)
ATTACHED = (
    "return ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioLoadLine.sys.mjs')"
    ".NulavioLoadLine.attachedCount();"
)

LINE = """
const line = document.getElementById('nulavio-load-line');
if (!line) return null;
const box = line.getBoundingClientRect(), page = gBrowser.selectedBrowser.getBoundingClientRect();
const before = getComputedStyle(line, '::before');
return { shown: !line.hidden && box.height > 0, state: line.dataset.state ?? null,
         inSelected: line.parentNode === gBrowser.selectedBrowser.parentNode,
         top: Math.round(box.top), pageTop: Math.round(page.top), height: box.height,
         hidden: line.getAttribute('aria-hidden'), colour: before.backgroundColor, animation: before.animationName,
         band: getComputedStyle(document.getElementById('nulavio-band')).backgroundColor };
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class LoadLineTest(unittest.TestCase):
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
        self.m.navigate(self.server.url("/page/inicio"))

    def line(self) -> dict:
        return self.m.chrome(LINE)

    def set(self, on: bool) -> None:
        self.m.set_context("chrome")
        try:
            done = self.m.execute_async(
                "const done = arguments[arguments.length - 1];"
                f"{PERSONALISE}.set('loadLine', arguments[0]).then(() => done(true), e => done(String(e)));",
                [on],
            )
        finally:
            self.m.set_context("content")
        self.assertIs(done, True)

    def load(self, ms: int) -> None:
        """Start a slow load in the selected tab without waiting for it (navigate would)."""
        self.m.chrome(
            "openTrustedLinkIn(arguments[0], 'current');",
            [self.server.url(f"/slow-page?ms={ms}&n={time.time_ns()}")],
        )

    def test_00_off_in_a_new_profile_with_nothing_attached(self):
        # #458: a new profile has no pref, and nothing is attached: no element, no progress listener.
        self.assertFalse(self.m.chrome("return Services.prefs.prefHasUserValue('nulavio.window.loadLine');"))
        self.assertIsNone(self.line())
        self.assertEqual(self.m.chrome(ATTACHED), 0)
        self.load(3000)
        for _ in range(10):
            self.assertIsNone(self.line())
            harness.wait_until(lambda: False, 0.2)
        self.m.chrome("gBrowser.selectedBrowser.stop();")
        self.set(True)  # the tests below are about the line itself
        self.assertTrue(harness.wait_until(lambda: self.line() is not None, 5))
        self.assertEqual(self.m.chrome(ATTACHED), 1)

    def test_01_shown_while_the_page_loads_and_gone_when_it_has_loaded(self):
        self.assertFalse(self.line()["shown"])
        self.load(4000)
        seen = harness.wait_until(lambda: (lambda now: now if now["shown"] else None)(self.line()), 5)
        self.assertTrue(seen, self.line())
        self.assertEqual(seen["state"], "loading")
        self.assertTrue(seen["inSelected"])
        self.assertEqual(seen["hidden"], "true")
        # On the page's top edge: under the toolbar, the band and any notification bar, never over them.
        self.assertEqual(seen["top"], seen["pageTop"])
        self.assertEqual(seen["height"], 2)
        # Neutral: not the band's colour.
        self.assertNotEqual(seen["colour"], seen["band"])
        self.assertEqual(seen["animation"], "nulavio-load-cross")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.title") == "slow-page", 15))
        self.assertTrue(harness.wait_until(lambda: not self.line()["shown"], 5), self.line())

    def test_02_a_stopped_load_ends_it_at_once(self):
        self.load(8000)
        self.assertTrue(harness.wait_until(lambda: self.line()["shown"], 5))
        self.m.chrome("gBrowser.selectedBrowser.stop();")
        self.assertTrue(harness.wait_until(lambda: not self.line()["shown"], 2), self.line())

    def test_03_a_background_tab_never_shows_it(self):
        self.m.chrome(
            "gBrowser.addTrustedTab(arguments[0], { inBackground: true });",
            [self.server.url("/slow-page?ms=3000&n=background")],
        )
        for _ in range(15):
            self.assertFalse(self.line()["shown"], self.line())
            harness.wait_until(lambda: False, 0.2)
        self.m.chrome("gBrowser.removeTab(gBrowser.tabs[gBrowser.tabs.length - 1]);")

    def test_04_still_under_reduced_motion(self):
        # A real load under reduced motion: the line is there and does not move (test_01: it moves otherwise).
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 1);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('ui.prefersReducedMotion');")
        # The engine applies a changed system preference to the window's style at its next refresh, not when the
        # preference is set (nsPresContext::ThemeChanged): wait until the window's sheet has taken it in (the line's
        # reduced-motion rule is the only one that sets this opacity), so the load below starts under it (#436).
        reduced = "return getComputedStyle(document.getElementById('nulavio-load-line'), '::before').opacity;"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(reduced) == "0.35", 10), self.m.chrome(reduced))
        self.load(4000)
        now = harness.wait_until(lambda: (lambda line: line if line["shown"] else None)(self.line()), 5)
        self.assertTrue(now, self.line())
        self.assertEqual((now["state"], now["animation"]), ("loading", "none"), now)
        self.m.chrome("gBrowser.selectedBrowser.stop();")

    def test_06_the_switch_takes_effect_while_a_page_loads(self):
        self.set(False)
        self.addCleanup(self.set, True)
        self.assertTrue(harness.wait_until(lambda: self.line() is None and self.m.chrome(ATTACHED) == 0, 5))
        self.load(6000)
        harness.wait_until(lambda: False, 0.5)
        self.assertIsNone(self.line())
        self.set(True)  # on while the page loads: shown at once for the load under way
        seen = harness.wait_until(lambda: (lambda now: now if now and now["shown"] else None)(self.line()), 5)
        self.assertTrue(seen, self.line())
        self.set(False)  # off while it still loads: the element and the listener go at once
        self.assertTrue(harness.wait_until(lambda: self.line() is None and self.m.chrome(ATTACHED) == 0, 5))
        self.m.chrome("gBrowser.selectedBrowser.stop();")

    def test_07_the_switch_is_in_aparencia(self):
        self.set(False)
        self.addCleanup(self.set, True)
        settings_page.open_pane(self.m, "appearance")
        off = settings_page.wait_control(self.m, "nulavio-load-line", lambda now: now["shown"] and not now["pressed"], timeout=15)
        self.assertTrue(off)
        now = settings_page.control(self.m, "nulavio-load-line")
        self.assertRegex(now["label"], r"(linha de carregamento|loading line)")
        settings_page.click(self.m, "#nulavio-load-line")
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome("return Services.prefs.getBoolPref('nulavio.window.loadLine', false);"), 10)
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(ATTACHED) >= 1, 10))
        settings_page.click(self.m, "#nulavio-load-line")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(ATTACHED) == 0, 10))
        self.m.navigate(self.server.url("/page/inicio"))

    def test_05_captures_in_both_themes(self):
        folder = harness.artifacts_dir() / "load-line"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            for dark in (0, 1):
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                self.load(6000)
                self.assertTrue(harness.wait_until(lambda: self.line()["shown"], 5))
                harness.wait_until(lambda: False, 1.2)
                self.m.set_context("chrome")
                try:
                    (folder / f"load-line-{'dark' if dark else 'light'}.png").write_bytes(self.m.screenshot_png())
                finally:
                    self.m.set_context("content")
                self.m.chrome("gBrowser.selectedBrowser.stop();")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")


if __name__ == "__main__":
    unittest.main()
