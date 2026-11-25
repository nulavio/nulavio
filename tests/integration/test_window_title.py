"""#322 (D-UX17's option): "Esconder o título da página na barra da janela". Off by default; on, every window of the
profile, private ones too, shows the brand (and the profile's name when there is more than one profile) instead of the
page's title, while navigating as well; off again, the page's title is back. Settings has the switch in Aparência."""

from __future__ import annotations

import unittest

import harness
import settings_page

TITLE = "return document.title;"
PERSONALISE = (
    'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs").NulavioPersonalise'
)
ENGINE = (
    "return ['privacy.exposeContentTitleInWindow', 'privacy.exposeContentTitleInWindow.pbm']"
    ".map(p => Services.prefs.getBoolPref(p));"
)


def chrome_async(m, script: str, args: list | None = None):
    m.set_context("chrome")
    try:
        return m.execute_async(script, args or [])
    finally:
        m.set_context("content")


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class WindowTitleTest(unittest.TestCase):
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

    def tearDown(self):
        self.set(False)

    def set(self, on: bool) -> None:
        chrome_async(
            self.m,
            "const done = arguments[arguments.length - 1];"
            f"{PERSONALISE}.set('hidePageTitle', arguments[0]).then(() => done(true), e => done(String(e)));",
            [on],
        )

    def title_is(self, want) -> bool:
        return harness.wait_until(lambda: want(self.m.chrome(TITLE)), 10)

    def test_01_off_by_default_the_window_shows_the_page(self):
        self.m.navigate(self.server.url("/page/Pagina-secreta"))
        self.assertTrue(self.title_is(lambda t: t.startswith("Pagina-secreta")), self.m.chrome(TITLE))
        self.assertEqual(self.m.chrome(ENGINE), [True, True])

    def test_02_on_the_window_never_shows_the_page_while_navigating_and_off_brings_it_back(self):
        self.m.navigate(self.server.url("/page/Pagina-secreta"))
        self.set(True)
        self.assertTrue(self.title_is(lambda t: "Pagina-secreta" not in t and "Nulavio" in t), self.m.chrome(TITLE))
        self.assertEqual(self.m.chrome(ENGINE), [False, False])
        self.m.navigate(self.server.url("/page/Outra-pagina"))
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.title") == "Outra-pagina", 10))
        self.assertFalse(harness.wait_until(lambda: "Outra-pagina" in self.m.chrome(TITLE), 2), self.m.chrome(TITLE))
        # A page that changes its own title does not reach the window either.
        self.m.execute("document.title = 'Mudou-sozinha';")
        self.assertFalse(harness.wait_until(lambda: "Mudou-sozinha" in self.m.chrome(TITLE), 2))
        # The tab keeps the page's title: only the window's is hidden (the switch says so).
        self.assertEqual(self.m.chrome("return gBrowser.selectedTab.label;"), "Mudou-sozinha")
        self.set(False)
        self.assertTrue(self.title_is(lambda t: t.startswith("Mudou-sozinha")), self.m.chrome(TITLE))
        self.assertEqual(self.m.chrome(ENGINE), [True, True])

    def test_03_a_private_window_follows_the_same_switch(self):
        self.set(True)
        handles = set(self.m.window_handles())
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, timeout=20))
        private = (set(self.m.window_handles()) - handles).pop()
        self.m.switch_to(private)
        try:
            # The new window is ready for a navigation once its delayed start-up has run and its first page has
            # loaded; a navigation sent before that can be replaced by the window's own first page.
            ready = (
                "return Boolean(window.gBrowserInit && gBrowserInit.delayedStartupFinished)"
                " && !gBrowser.selectedBrowser.webProgress.isLoadingDocument;"
            )
            self.assertTrue(harness.wait_until(lambda: self.m.chrome(ready), 20), "the private window never started")
            self.m.navigate(self.server.url("/page/Privada-secreta"))
            page = "return [document.title, location.href];"
            self.assertTrue(harness.wait_until(lambda: self.m.execute(page)[0] == "Privada-secreta", 10), self.m.execute(page))
            self.assertFalse(harness.wait_until(lambda: "Privada-secreta" in self.m.chrome(TITLE), 2), self.m.chrome(TITLE))
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)

    def test_05_a_locked_engine_switch_is_shown_as_it_is(self):
        # Review of #390: an administrator who locks the engine's switch to show titles in private windows gets a
        # switch that says off and cannot be changed, not one that says on while private windows show the page.
        self.m.chrome("Services.prefs.lockPref('privacy.exposeContentTitleInWindow.pbm');")
        self.addCleanup(self.m.chrome, "Services.prefs.unlockPref('privacy.exposeContentTitleInWindow.pbm');")
        self.set(True)
        settings_page.open_pane(self.m, "appearance")
        locked = lambda now: now["shown"] and now["disabled"] and not now["pressed"]  # noqa: E731
        self.assertTrue(settings_page.wait_control(self.m, "nulavio-hide-page-title", locked, timeout=15))

    def test_04_the_switch_is_in_aparencia_with_what_it_does_not_hide(self):
        settings_page.open_pane(self.m, "appearance")
        shown = settings_page.wait_control(
            self.m, "nulavio-hide-page-title", lambda now: now["shown"] and not now["pressed"], timeout=15
        )
        self.assertTrue(shown)
        now = settings_page.control(self.m, "nulavio-hide-page-title")
        self.assertRegex(now["label"], r"(Esconder o título da página|Hide the page title)")
        self.assertRegex(now["description"], r"(abas|tabs)")
        settings_page.click(self.m, "#nulavio-hide-page-title")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(ENGINE) == [False, False], 10))
        settings_page.click(self.m, "#nulavio-hide-page-title")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(ENGINE) == [True, True], 10))


if __name__ == "__main__":
    unittest.main()
