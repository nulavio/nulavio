"""UX6 Settings > Aparência on the real build: density, accent and "Mais contraste".

Each option writes only the pref options.json declares, reaches the window, the Shell pages and the
about: pages, never the security, private-window or focus colours, and walking every value of every
option leaves every other pref as it was. Headless, throwaway profile.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

import harness
from test_window_band import BAND_PROBE, assert_band

ROOT = Path(__file__).resolve().parents[2]
OPTIONS = json.loads((ROOT / "browser" / "shell" / "shared" / "options.json").read_text(encoding="utf-8"))["options"]
APPEARANCE = {o["id"]: o for o in OPTIONS if o["writer"] == "NulavioPersonalise"}
OPTION_PREFS = {pref for o in APPEARANCE.values() for pref in o["prefs"]}

USER_PREFS = """
const out = {};
for (const name of Services.prefs.getChildList("")) {
  if (!Services.prefs.prefHasUserValue(name)) continue;
  const type = Services.prefs.getPrefType(name);
  out[name] = type === Services.prefs.PREF_BOOL ? Services.prefs.getBoolPref(name)
    : type === Services.prefs.PREF_INT ? Services.prefs.getIntPref(name) : Services.prefs.getStringPref(name, "");
}
return {prefs: out, permissions: Services.perms.all.length};
"""
# Prefs the engine itself moves on its own while a test runs (session, timestamps, telemetry ids).
NOISE = (
    "browser.sessionstore.",
    "toolkit.startup.",
    "places.",
    "app.update.lastUpdateTime.",
    "browser.laterrun.",
    "browser.engagement.",
    "idle.",
    "storage.vacuum.",
    "browser.pageActions.",
    "media.gmp",
    "extensions.databaseSchema",
    "browser.newtabpage.activity-stream.impressionId",
    "browser.migration.",
    "privacy.purge_trackers.date_in_cookie_database",
    "browser.download.",
    "browser.startup.lastColdStartupCheck",
    "datareporting.",
    "browser.uiCustomization.state",
    "sidebar.backupState",
    "sidebar.old-sidebar.has-used",
    "browser.toolbars.bookmarks.visibility",
    "doh-rollout.",
    "network.trr.blocklist_cleanup_done",
    "browser.contextual-services.contextId",
    "nimbus.",
    "services.",
    "dom.push.",
    "trailhead.",
    "browser.urlbar.",
    "media.videocontrols.",
)

COLOURS = """
const css = getComputedStyle(document.documentElement);
const v = name => css.getPropertyValue(name).trim();
return {accent: v('--nv-color-accent-default'), focus: v('--nv-color-focus'), text2: v('--nv-color-text-secondary'),
  acting: v('--nv-color-security-acting-edge'), privateAccent: v('--nv-color-chrome-private-accent'),
  route: v('--nv-color-route-vertical'), border: v('--nv-color-border-control')};
"""


def quiet(prefs: dict) -> dict:
    return {k: v for k, v in prefs.items() if not k.startswith(NOISE)}


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class AppearanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        cls.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', 0);")
        cls.shots = harness.artifacts_dir() / "appearance-ux6"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        for pref in (*OPTION_PREFS, "ui.systemUsesDarkTheme", "ui.useAccessibilityTheme", "ui.prefersReducedTransparency"):
            cls.m.chrome("Services.prefs.clearUserPref(arguments[0]);", [pref])
        cls.session.cleanup()

    def tearDown(self):
        for pref in OPTION_PREFS:
            self.m.chrome("Services.prefs.clearUserPref(arguments[0]);", [pref])

    # -- helpers -----------------------------------------------------------------------------------

    def open(self) -> None:
        self.m.navigate(self.base + "settings/settings.html#appearance")
        ready = "return document.documentElement.dataset.ready === 'true';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(ready), 20))

    def choose(self, selector: str) -> None:
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f"label:has(> {selector})")})

    def pref(self, name: str):
        return self.m.chrome(
            "const n = arguments[0]; if (!Services.prefs.prefHasUserValue(n)) return null;"
            "const t = Services.prefs.getPrefType(n);"
            "return t === 128 ? Services.prefs.getBoolPref(n)"
            "  : t === 64 ? Services.prefs.getIntPref(n) : Services.prefs.getStringPref(n);",
            [name],
        )

    def wait_pref(self, name: str, value) -> None:
        self.assertTrue(harness.wait_until(lambda: self.pref(name) == value, 10), (name, self.pref(name), value))

    def snapshot(self) -> dict:
        return self.m.chrome(USER_PREFS)

    # -- tests -------------------------------------------------------------------------------------

    def test_01_density_writes_only_uidensity_and_automatic_clears_it(self):
        self.open()
        self.assertEqual(self.m.execute("return document.querySelector('input[name=density]:checked').value;"), "auto")
        for value, stored in (("compact", 1), ("touch", 2), ("normal", 0), ("auto", None)):
            self.choose(f'input[name="density"][value="{value}"]')
            self.wait_pref("browser.uidensity", stored)
            if stored is not None:
                window = self.m.chrome("return document.documentElement.getAttribute('uidensity');")
                self.assertEqual(window, {1: "compact", 2: "touch", 0: None}[stored])

    def test_02_accent_reaches_the_window_shell_and_about_pages_but_not_security_private_or_focus(self):
        self.open()
        base_window = self.m.chrome(COLOURS)
        base_page = self.m.execute(COLOURS)
        self.choose('input[name="accent"][value="blue"]')
        self.wait_pref("nulavio.appearance.accent", "blue")
        page = lambda: self.m.execute(COLOURS)  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: page()["accent"] == "#2D64B5", 10), page())
        self.assertEqual(self.m.execute("return document.documentElement.dataset.accent;"), "blue")
        shown = page()
        self.assertEqual(shown["route"], "#2D64B5")
        self.assertEqual(shown["focus"], base_page["focus"], "focus stays mint")
        self.assertEqual(shown["acting"], base_page["acting"], "the acting seal stays mint")
        window = self.m.chrome(COLOURS)
        self.assertIn("#2D64B5", window["accent"])
        for key in ("focus", "acting", "privateAccent"):
            self.assertEqual(window[key], base_window[key], key)
        self.m.navigate("about:preferences")
        accent_var = "return getComputedStyle(document.documentElement).getPropertyValue('--color-accent-primary');"

        def about():
            return self.m.execute(accent_var)

        self.assertTrue(harness.wait_until(lambda: "#2D64B5" in about(), 10), about())
        self.shoot("about-preferences-blue")
        self.open()
        self.choose('input[name="accent"][value="mint"]')
        self.wait_pref("nulavio.appearance.accent", None)
        self.assertTrue(harness.wait_until(lambda: page()["accent"] == base_page["accent"], 10), page())

    def test_03_more_contrast_raises_text_and_borders_in_the_window_and_pages(self):
        self.open()
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("label:has(> #more-contrast)")})
        self.wait_pref("nulavio.appearance.moreContrast", True)
        page = lambda: self.m.execute(COLOURS)  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: page()["text2"] == "#23495A", 10), page())
        self.assertEqual(self.m.execute("return document.documentElement.dataset.contrast;"), "more")
        card = self.m.execute(
            "const c = getComputedStyle(document.querySelector('#appearance .card'));"
            "return [c.borderTopWidth, c.borderTopColor, getComputedStyle(document.body).color];"
        )
        self.assertEqual(card[0], "1px")
        self.assertEqual(card[1], card[2], "cards are framed in the text colour")
        self.assertIn("#23495A", self.m.chrome(COLOURS)["text2"])
        self.shoot("settings-more-contrast")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("label:has(> #more-contrast)")})
        self.wait_pref("nulavio.appearance.moreContrast", None)

    def test_04_the_system_asking_for_high_contrast_turns_the_switch_on_with_its_reason(self):
        self.open()
        self.m.chrome("Services.prefs.setIntPref('ui.useAccessibilityTheme', 1);")
        try:
            state = lambda: self.m.execute(  # noqa: E731
                "const s = document.getElementById('more-contrast');"
                "return [s.checked, s.disabled, document.getElementById('more-contrast-system').hidden,"
                " document.documentElement.dataset.contrast];"
            )
            self.assertTrue(harness.wait_until(lambda: state() == [True, True, False, "more"], 10), state())
            self.assertIsNone(self.pref("nulavio.appearance.moreContrast"), "the system's request is not saved as a choice")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.useAccessibilityTheme');")
        self.assertTrue(
            harness.wait_until(lambda: not self.m.execute("return document.getElementById('more-contrast').disabled;"), 10)
        )

    def test_05_walking_every_option_changes_only_its_own_prefs(self):
        """UX6 done criterion: no option can turn a protection off."""
        self.open()
        before = self.snapshot()
        walk = [("density", v) for v in APPEARANCE["density"]["values"]] + [("accent", v) for v in APPEARANCE["accent"]["values"]]
        for option, value in walk:
            self.choose(f'input[name="{option}"][value="{value}"]')
            pref = APPEARANCE[option]["prefs"][0]
            expected = APPEARANCE[option]["prefValues"][APPEARANCE[option]["values"].index(value)]
            self.wait_pref(pref, expected)
            now = self.snapshot()
            changed = {
                k for k in set(quiet(now["prefs"])) | set(quiet(before["prefs"])) if now["prefs"].get(k) != before["prefs"].get(k)
            }
            self.assertLessEqual(changed, OPTION_PREFS, (option, value))
            self.assertEqual(now["permissions"], before["permissions"])
        # The ambience first: "Reduzir transparência" only applies while something is transparent.
        for switch, pref in (
            ("#newtab-ambience", "nulavio.appearance.newtabAmbience"),
            ("#reduce-transparency", "nulavio.appearance.reduceTransparency"),
            ("#more-contrast", "nulavio.appearance.moreContrast"),
        ):
            self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f"label:has(> {switch})")})
            self.wait_pref(pref, True)
            now = self.snapshot()
            changed = {
                k for k in set(quiet(now["prefs"])) | set(quiet(before["prefs"])) if now["prefs"].get(k) != before["prefs"].get(k)
            }
            self.assertLessEqual(changed, OPTION_PREFS, switch)
        for switch in ("#more-contrast", "#reduce-transparency", "#newtab-ambience"):
            self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f"label:has(> {switch})")})
            time.sleep(0.3)
        self.choose('input[name="density"][value="auto"]')
        self.choose('input[name="accent"][value="mint"]')
        for pref in OPTION_PREFS:
            self.wait_pref(pref, None)
        after = self.snapshot()
        self.assertEqual(quiet(after["prefs"]), quiet(before["prefs"]))

    def test_06_security_indicators_stay_whole_in_every_variant(self):
        self.m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 768})
        with harness.FixtureServer() as server:
            self.m.navigate(server.url("/page/Variants"))
            for accent in ("mint", "blue"):
                for contrast in (False, True):
                    for density in (None, 1, 2):
                        self.m.chrome(
                            "const [a, c, d] = arguments;"
                            "a === 'mint' ? Services.prefs.clearUserPref('nulavio.appearance.accent')"
                            "  : Services.prefs.setStringPref('nulavio.appearance.accent', a);"
                            "c ? Services.prefs.setBoolPref('nulavio.appearance.moreContrast', true)"
                            "  : Services.prefs.clearUserPref('nulavio.appearance.moreContrast');"
                            "d === null ? Services.prefs.clearUserPref('browser.uidensity')"
                            "  : Services.prefs.setIntPref('browser.uidensity', d);",
                            [accent, contrast, density],
                        )
                        time.sleep(0.4)
                        with self.subTest(accent=accent, contrast=contrast, density=density):
                            assert_band(self, self.m.chrome(f"return {BAND_PROBE};"))
                            # The address bar stays whole and on top (the engine folds the identity box away
                            # for a page served by this computer, so the address itself is what is checked).
                            address = self.m.chrome(
                                "const e = document.getElementById('urlbar-input'); const r = e.getBoundingClientRect();"
                                "const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
                                "return {w: r.width, opacity: getComputedStyle(document.getElementById('urlbar')).opacity,"
                                " hit: e.closest('#urlbar').contains(hit), value: e.value};"
                            )
                            self.assertEqual((address["opacity"], address["hit"]), ("1", True), address)
                            self.assertIn("127.0.0.1", address["value"])
            self.m.set_context("chrome")
            try:
                (self.shots / "window-blue-more-touch.png").write_bytes(self.m.screenshot_png())
            finally:
                self.m.set_context("content")
        for pref in ("browser.uidensity", *OPTION_PREFS):
            self.m.chrome("Services.prefs.clearUserPref(arguments[0]);", [pref])

    def test_07_a_change_reaches_every_open_shell_page(self):
        self.open()
        settings = self.m.send("WebDriver:GetWindowHandle")["value"]
        handles = set(self.m.window_handles())
        self.m.chrome(
            "const principal = Services.scriptSecurityManager.getSystemPrincipal();"
            "gBrowser.selectedTab = gBrowser.addTab(arguments[0], {triggeringPrincipal: principal});",
            [self.base + "newtab/newtab.html"],
        )
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, 10))
        newtab = (set(self.m.window_handles()) - handles).pop()
        self.m.switch_to(newtab)
        painted = "return document.documentElement.hasAttribute('data-painted');"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(painted), 20))
        self.m.switch_to(settings)
        self.m.execute("browser.nulavioPersonalise.setAccent('blue');")
        self.wait_pref("nulavio.appearance.accent", "blue")
        self.m.switch_to(newtab)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.accent;") == "blue", 10)
        )
        self.m.execute("browser.nulavioPersonalise.setAccent('mint');")
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.accent;") == "mint", 10)
        )
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(settings)

    def test_08_captures_the_section_in_both_themes_and_accents(self):
        self.open()
        painted = "return document.documentElement.dataset.accent;"
        for accent in ("mint", "blue"):
            self.m.execute("return browser.nulavioPersonalise.setAccent(arguments[0]);", [accent])
            self.assertTrue(harness.wait_until(lambda want=accent: self.m.execute(painted) == want, 10))
            self.shoot(f"settings-appearance-{accent}")

    def newtab(self) -> None:
        self.m.navigate(self.base + "newtab/newtab.html")
        painted = "return document.documentElement.hasAttribute('data-painted');"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(painted), 20))

    def look(self) -> dict:
        return self.m.execute(
            "const card = document.querySelector('.card:not([hidden])'), c = getComputedStyle(card);"
            "const probe = document.createElement('span'); document.body.append(probe);"
            "probe.style.background = 'var(--nv-color-surface-frostFallback)';"
            "const solid = getComputedStyle(probe).backgroundColor; probe.remove();"
            "return {ambience: document.documentElement.dataset.ambience,"
            " gradient: getComputedStyle(document.body).backgroundImage.includes('linear-gradient'),"
            " blur: c.backdropFilter, solid: c.backgroundColor === solid};"
        )

    def test_09_the_ambience_is_opt_in_and_never_in_a_private_window(self):
        self.newtab()
        self.assertEqual(self.look(), {"ambience": "off", "gradient": False, "blur": "none", "solid": True})
        self.m.execute("return browser.nulavioPersonalise.setNewtabAmbience(true);")
        self.assertTrue(harness.wait_until(lambda: self.look()["gradient"], 10), self.look())
        on = self.look()
        self.assertEqual((on["ambience"], on["solid"]), ("on", False), on)
        self.assertIn("blur", on["blur"])
        self.shoot("newtab-ambience")
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        handles = set(self.m.window_handles())
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, 20))
        private = (set(self.m.window_handles()) - handles).pop()
        self.m.switch_to(private)
        try:
            harness.wait_until(lambda: self.m.current_url() == "about:privatebrowsing", 20)
            self.m.navigate(self.base + "newtab/newtab.html")
            loaded = "return document.readyState === 'complete' && Boolean(document.querySelector('.card'));"
            self.assertTrue(harness.wait_until(lambda: self.m.execute(loaded), 20))
            time.sleep(1)
            seen = self.look()
            self.assertNotEqual(seen["ambience"], "on", seen)
            self.assertFalse(seen["gradient"], seen)
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)

    def test_10_reduce_transparency_the_system_and_more_contrast_make_the_cards_solid(self):
        self.m.chrome("Services.prefs.setBoolPref('nulavio.appearance.newtabAmbience', true);")
        self.newtab()
        self.assertTrue(harness.wait_until(lambda: not self.look()["solid"], 10), self.look())
        for setup, undo in (
            (
                "Services.prefs.setBoolPref('nulavio.appearance.reduceTransparency', true);",
                "Services.prefs.clearUserPref('nulavio.appearance.reduceTransparency');",
            ),
            (
                "Services.prefs.setBoolPref('nulavio.appearance.moreContrast', true);",
                "Services.prefs.clearUserPref('nulavio.appearance.moreContrast');",
            ),
            (
                "Services.prefs.setIntPref('ui.prefersReducedTransparency', 1);",
                "Services.prefs.clearUserPref('ui.prefersReducedTransparency');",
            ),
        ):
            with self.subTest(setup=setup):
                self.m.chrome(setup)
                try:
                    self.assertTrue(harness.wait_until(lambda: self.look()["solid"], 10), self.look())
                    self.assertEqual(self.look()["blur"], "none")
                    self.assertTrue(self.look()["gradient"], "the background stays; only the cards turn solid")
                finally:
                    self.m.chrome(undo)
                self.assertTrue(harness.wait_until(lambda: not self.look()["solid"], 10), self.look())

    def test_11_reduce_transparency_says_why_when_it_cannot_change_anything(self):
        self.open()
        why = lambda: self.m.execute(  # noqa: E731
            "const c = document.getElementById('reduce-transparency');"
            "return [c.disabled, c.checked, document.getElementById('reduce-transparency-why').textContent];"
        )
        self.assertEqual(why(), [True, False, self.message("reduceTransparencyIdle")])
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("label:has(> #newtab-ambience)")})
        self.assertTrue(harness.wait_until(lambda: why() == [False, False, self.message("reduceTransparencyHint")], 10), why())
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("label:has(> #more-contrast)")})
        self.assertTrue(harness.wait_until(lambda: why() == [True, True, self.message("reduceTransparencyContrast")], 10), why())

    def message(self, key: str) -> str:
        return self.m.execute("return browser.i18n.getMessage(arguments[0]);", [key])

    def shoot(self, name: str) -> None:
        for dark in (0, 1):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            time.sleep(0.4)
            (self.shots / f"{name}-{'dark' if dark else 'light'}.png").write_bytes(self.m.screenshot_png(full=False))
        self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', 0);")


if __name__ == "__main__":
    unittest.main()
