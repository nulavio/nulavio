"""UX6 Nulavio's look on the real build: density, accent, "Mais contraste", the new tab's background.

The options are in the settings page's Aparência pane (ADR 0008, ADR 0011; the density is the engine's own
group there). Each writes only the pref options.json declares, reaches the window, the Shell pages and the
about: pages, never the security, private-window or focus colours, and walking every value of every
option leaves every other pref as it was. Headless, throwaway profile.
"""

from __future__ import annotations

import json
import re
import time
import unittest
from pathlib import Path

import harness
import settings_page
from test_window_band import BAND_PROBE, assert_band

# What the engine records for its own background updates, written at any moment: the Safe Browsing lists, Remote
# Settings, and the media plugin check about 20 s after a start (with OpenH264's install the first time). Only the
# first family sits under a branch that is a protection; the others are named for the record of what failed a run.
BACKGROUND_CLOCK = re.compile(
    r"browser\.safebrowsing\.provider\.[a-z0-9]+\.(lastupdatetime|nextupdatetime|backofftime)"
    r"|services\.settings\.(last_update_seconds|clock_skew_seconds|last_etag)"
    # When each Remote Settings collection was last looked at, in any of its buckets (main, blocklists, security-state).
    r"|services\.settings\.[a-z0-9-]+\.[a-z0-9-]+\.last_check"
    r"|media\.gmp-manager\.(lastCheck|lastEmptyCheck|buildID)"
    r"|media\.gmp-gmpopenh264\.(lastInstallStart|lastDownload|lastUpdate|version|abi|hashValue)"
)

ROOT = Path(__file__).resolve().parents[2]
OPTIONS = json.loads((ROOT / "browser" / "shell" / "shared" / "options.json").read_text(encoding="utf-8"))["options"]
APPEARANCE = {o["id"]: o for o in OPTIONS if o["writer"] == "NulavioPersonalise"}
OPTION_PREFS = {pref for o in APPEARANCE.values() for pref in o["prefs"]}
# The settings that matter to "no option can turn a protection off": every Nulavio option's own, the baseline's,
# the ones the launcher's Guard rules name, and (read on the engine) the ones the Guard watches at run time.
EVERY_OPTION_PREF = {pref for o in OPTIONS for pref in o["prefs"]}
GUARD_RULES = {rule["pref"] for rule in json.loads((ROOT / "browser" / "config" / "guard-rules.json").read_text())["rules"]}
WATCHED = (
    'return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioGuard.sys.mjs").WATCHED_PREFS;'
)
# The engine's own density group names "Normal" its own way.
DENSITY = {"auto": "auto", "normal": "standard", "compact": "compact", "touch": "touch"}
PERSONALISE = (
    'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs").NulavioPersonalise'
)

USER_PREFS = """
const out = {};
for (const name of Services.prefs.getChildList("")) {
  if (!Services.prefs.prefHasUserValue(name)) continue;
  const type = Services.prefs.getPrefType(name);
  out[name] = type === Services.prefs.PREF_BOOL ? Services.prefs.getBoolPref(name)
    : type === Services.prefs.PREF_INT ? Services.prefs.getIntPref(name) : Services.prefs.getStringPref(name, "");
}
// Every permission, except the engine's record that a person clicked in a page of the Shell itself
// (storageAccessAPI for the Shell's own origin, written on any real click; it grants nothing to a site).
const shell = WebExtensionPolicy.getByID('shell@nulavio.net').getURL('').slice(0, -1); // without the trailing slash
const permissions = Services.perms.all
  .filter(p => !(p.type === 'storageAccessAPI' && p.principal.origin === shell))
  .map(p => [p.type, p.principal.origin, p.capability].join(' ')).sort();
return {prefs: out, permissions};
"""
COLOURS = """
const css = getComputedStyle(document.documentElement);
const v = name => css.getPropertyValue(name).trim();
return {accent: v('--nv-color-accent-default'), focus: v('--nv-color-focus'), text2: v('--nv-color-text-secondary'),
  acting: v('--nv-color-security-acting-edge'), privateAccent: v('--nv-color-chrome-private-accent'),
  route: v('--nv-color-route-vertical'), border: v('--nv-color-border-control')};
"""


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
        """The settings page at Aparência, with Nulavio's colours drawn."""
        settings_page.open_pane(self.m, "appearance")
        settings_page.wait_control(self.m, "nulavio-accent")

    def shell_page(self) -> None:
        """A page of the Shell, to see what reaches them (what is left of its own settings page)."""
        self.m.navigate(self.base + "settings/settings.html#integrations")
        ready = "return document.documentElement.dataset.ready === 'true';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(ready), 20))

    def switch(self, control: str) -> None:
        settings_page.wait_control(self.m, control, lambda now: now["shown"] and not now["disabled"])
        settings_page.click(self.m, f"#{control}")

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

    def matters(self):
        """Whether a setting is a protection, another option's or Nulavio's own: a change to one of those is never
        the engine's bookkeeping. The engine writes dozens of its own records in the background while a test runs
        (when it last checked a list, a plugin, a timer); a list of those names never ends, so the test looks at
        what must not change instead of at everything that may."""
        from nulavio_launcher import profile as launcher_profile

        watched = self.m.chrome(WATCHED)
        named = {name for name in watched if not name.endswith(".")} | GUARD_RULES | EVERY_OPTION_PREF
        named |= {pref.name for pref in launcher_profile.baseline_prefs()}
        branches = (*(name for name in watched if name.endswith(".")), "nulavio.")
        return lambda name: (name in named or name.startswith(branches)) and not BACKGROUND_CLOCK.fullmatch(name)

    # -- tests -------------------------------------------------------------------------------------

    def test_01_density_writes_only_uidensity_and_automatic_clears_it(self):
        self.open()
        self.assertEqual(settings_page.wait_control(self.m, "uiDensity")["value"], "auto")
        for value, stored in (("compact", 1), ("touch", 2), ("normal", 0), ("auto", None)):
            settings_page.choose(self.m, "uiDensity", DENSITY[value])
            self.wait_pref("browser.uidensity", stored)
            if stored is not None:
                window = self.m.chrome("return document.documentElement.getAttribute('uidensity');")
                self.assertEqual(window, {1: "compact", 2: "touch", 0: None}[stored])

    def test_02_accent_reaches_the_window_shell_and_about_pages_but_not_security_private_or_focus(self):
        self.shell_page()
        base_window = self.m.chrome(COLOURS)
        base_page = self.m.execute(COLOURS)
        self.open()
        settings_page.choose(self.m, "nulavio-accent", "blue")
        self.wait_pref("nulavio.appearance.accent", "blue")
        accent_var = "return getComputedStyle(document.documentElement).getPropertyValue('--color-accent-primary');"

        def about():
            return self.m.execute(accent_var)

        self.assertTrue(harness.wait_until(lambda: "#2D64B5" in about(), 10), about())
        self.shoot("about-preferences-blue")
        self.shell_page()
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
        self.open()
        settings_page.choose(self.m, "nulavio-accent", "mint")
        self.wait_pref("nulavio.appearance.accent", None)
        self.shell_page()
        self.assertTrue(harness.wait_until(lambda: page()["accent"] == base_page["accent"], 10), page())

    def test_03_more_contrast_raises_text_and_borders_in_the_window_and_pages(self):
        self.open()
        self.switch("nulavio-more-contrast")
        self.wait_pref("nulavio.appearance.moreContrast", True)
        self.shoot("settings-more-contrast")
        self.shell_page()
        page = lambda: self.m.execute(COLOURS)  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: page()["text2"] == "#23495A", 10), page())
        self.assertEqual(self.m.execute("return document.documentElement.dataset.contrast;"), "more")
        card = self.m.execute(
            "const c = getComputedStyle(document.querySelector('#integrations .card'));"
            "return [c.borderTopWidth, c.borderTopColor, getComputedStyle(document.body).color];"
        )
        self.assertEqual(card[0], "1px")
        self.assertEqual(card[1], card[2], "cards are framed in the text colour")
        self.assertIn("#23495A", self.m.chrome(COLOURS)["text2"])
        self.open()
        self.switch("nulavio-more-contrast")
        self.wait_pref("nulavio.appearance.moreContrast", None)

    def test_04_the_system_asking_for_high_contrast_turns_the_switch_on_with_its_reason(self):
        self.open()
        self.m.chrome("Services.prefs.setIntPref('ui.useAccessibilityTheme', 1);")
        try:
            by_system = lambda now: now["shown"] and now["pressed"] and now["disabled"]  # noqa: E731
            switch = settings_page.wait_control(self.m, "nulavio-more-contrast", by_system)
            self.assertEqual(switch["description"], "O seu sistema já pede alto contraste, e o Nulavio usa as cores dele.")
            self.assertIsNone(self.pref("nulavio.appearance.moreContrast"), "the system's request is not saved as a choice")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.useAccessibilityTheme');")
        free = settings_page.wait_control(self.m, "nulavio-more-contrast", lambda now: not now["disabled"] and not now["pressed"])
        self.assertIn("Textos e bordas mais fortes", free["description"])

    def test_05_walking_every_option_changes_only_its_own_prefs(self):
        """UX6 done criterion: no option can turn a protection off. Every value of every appearance option,
        through the settings page: at each step, of the settings that are a protection, another option's or
        Nulavio's own (`matters`), only the appearance options' own differ from the start, and at the end none
        does. Settings outside that set are the engine's to write, and it does, in the background."""
        self.open()
        before = self.snapshot()
        matters = self.matters()
        self.assertTrue(all(matters(pref) for pref in OPTION_PREFS), "the options' own settings are not in the set looked at")
        for protection in ("dom.security.https_only_mode", "browser.safebrowsing.malware.enabled", "network.trr.mode"):
            self.assertTrue(matters(protection), protection)
        walk = [("density", v) for v in APPEARANCE["density"]["values"]] + [("accent", v) for v in APPEARANCE["accent"]["values"]]
        for option, value in walk:
            if option == "density":
                settings_page.choose(self.m, "uiDensity", DENSITY[value])
            else:
                settings_page.choose(self.m, "nulavio-accent", value)
            pref = APPEARANCE[option]["prefs"][0]
            expected = APPEARANCE[option]["prefValues"][APPEARANCE[option]["values"].index(value)]
            self.wait_pref(pref, expected)
            now = self.snapshot()
            changed = {k for k in set(now["prefs"]) | set(before["prefs"]) if now["prefs"].get(k) != before["prefs"].get(k)}
            changed = {k for k in changed if matters(k)}
            self.assertLessEqual(changed, OPTION_PREFS, (option, value))
            self.assertEqual(now["permissions"], before["permissions"])
        # The ambience first: "Reduzir transparência" only applies while something is transparent.
        for switch, pref in (
            ("nulavio-newtab-ambience", "nulavio.appearance.newtabAmbience"),
            ("nulavio-reduce-transparency", "nulavio.appearance.reduceTransparency"),
            ("nulavio-more-contrast", "nulavio.appearance.moreContrast"),
        ):
            self.switch(switch)
            self.wait_pref(pref, True)
            now = self.snapshot()
            changed = {k for k in set(now["prefs"]) | set(before["prefs"]) if now["prefs"].get(k) != before["prefs"].get(k)}
            changed = {k for k in changed if matters(k)}
            self.assertLessEqual(changed, OPTION_PREFS, switch)
        for switch in ("nulavio-more-contrast", "nulavio-reduce-transparency", "nulavio-newtab-ambience"):
            self.switch(switch)
            time.sleep(0.3)
        settings_page.choose(self.m, "uiDensity", "auto")
        settings_page.choose(self.m, "nulavio-accent", "mint")
        for pref in OPTION_PREFS:
            self.wait_pref(pref, None)
        after = self.snapshot()
        steady = lambda prefs: {k: v for k, v in prefs.items() if matters(k)}  # noqa: E731
        self.assertEqual(steady(after["prefs"]), steady(before["prefs"]))

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
        self.shell_page()
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
        # The new tab may not have a document yet when the first check runs.
        painted = "return document.documentElement?.hasAttribute('data-painted') ?? false;"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(painted), 20))
        self.m.switch_to(settings)
        self.m.chrome(f"return {PERSONALISE}.set('accent', 'blue');")
        self.wait_pref("nulavio.appearance.accent", "blue")
        self.m.switch_to(newtab)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.accent;") == "blue", 10)
        )
        self.m.chrome(f"return {PERSONALISE}.set('accent', 'mint');")
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.accent;") == "mint", 10)
        )
        self.m.send("WebDriver:CloseWindow")
        self.m.switch_to(settings)

    def test_08_captures_the_group_in_both_themes_and_accents(self):
        self.open()
        accent_var = "return getComputedStyle(document.documentElement).getPropertyValue('--color-accent-primary');"
        for accent, colour in (("blue", "#2D64B5"), ("mint", None)):
            settings_page.choose(self.m, "nulavio-accent", accent)
            self.wait_pref("nulavio.appearance.accent", colour and accent)
            if colour:
                self.assertTrue(harness.wait_until(lambda colour=colour: colour in self.m.execute(accent_var), 10))
            self.m.chrome(settings_page.DOC + 'd.getElementById("nulavio-accent").scrollIntoView({ block: "center" });')
            self.shoot(f"settings-appearance-{accent}")

    def newtab(self) -> None:
        self.m.navigate(self.base + "newtab/newtab.html")
        # The new tab may not have a document yet when the first check runs.
        painted = "return document.documentElement?.hasAttribute('data-painted') ?? false;"
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
        self.m.chrome(f"return {PERSONALISE}.set('newtabAmbience', true);")
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

        def why(want):
            matches = lambda now: [now["disabled"], bool(now["pressed"]), now["description"]] == want  # noqa: E731
            return settings_page.wait_control(self.m, "nulavio-reduce-transparency", matches)

        why([True, False, "Nada está transparente agora: o fundo suave está desligado."])
        self.switch("nulavio-newtab-ambience")
        why([False, False, "Deixa sólidos os cartões da nova aba."])
        self.switch("nulavio-more-contrast")
        why([True, True, "“Mais contraste” já deixa os cartões sólidos."])
        self.assertIsNone(self.pref("nulavio.appearance.reduceTransparency"), "shown as in effect, not saved as a choice")

    def test_12_a_value_an_administrator_locked_is_the_one_shown(self):
        """Review: a locked accent (autoconfig lockPref) paints the window blue; the settings page and Shell pages say so too."""
        self.m.chrome(
            "Services.prefs.getDefaultBranch('').setStringPref('nulavio.appearance.accent', 'blue');"
            "Services.prefs.lockPref('nulavio.appearance.accent');"
        )
        try:
            self.open()
            locked = lambda now: now["shown"] and now["value"] == "blue" and now["disabled"]  # noqa: E731
            settings_page.wait_control(self.m, "nulavio-accent", locked)
            note = settings_page.wait_control(self.m, "nulavio-look-locked")
            self.assertEqual(note["message"], "Algumas destas opções são gerenciadas pelo administrador.")
            # The window is painted a moment after the page says so (it failed one run in three on a busy machine).
            accent = lambda: self.m.chrome(COLOURS)["accent"]  # noqa: E731
            self.assertTrue(harness.wait_until(lambda: "#2D64B5" in accent(), 10), accent())
            self.shell_page()
            self.assertEqual(self.m.execute("return document.documentElement.dataset.accent;"), "blue")
        finally:
            self.m.chrome(
                "Services.prefs.unlockPref('nulavio.appearance.accent');"
                "Services.prefs.getDefaultBranch('').setStringPref('nulavio.appearance.accent', '');"
            )

    def test_12b_a_locked_density_reads_as_the_engine_draws_it(self):
        """Review: a policy lock writes the default branch only. The engine (gUIDensity) then compacts
        short windows on top of that default: a locked Normal is Automático, a locked Toque is Toque
        (the window draws it). The module says so to whoever asks."""
        read = f"return {PERSONALISE}.state().then(state => [state.density, state.locked.density]);"
        drawn = "return document.documentElement.getAttribute('uidensity') || 'normal';"
        lock = "Services.prefs.getDefaultBranch('').setIntPref('browser.uidensity', arguments[0]);"
        for locked, shown, window in ((0, "auto", "normal"), (2, "touch", "touch")):
            with self.subTest(locked=locked):
                self.m.chrome(lock + "Services.prefs.lockPref('browser.uidensity');", [locked])
                try:
                    reads = lambda want=shown: self.m.chrome(read) == [want, True]  # noqa: E731
                    self.assertTrue(harness.wait_until(reads, 10), self.m.chrome(read))
                    self.assertEqual(self.m.chrome(drawn), window)  # 1366x768: not short, so no auto-compact
                finally:
                    self.m.chrome("Services.prefs.unlockPref('browser.uidensity');" + lock, [0])

    def shoot(self, name: str) -> None:
        for dark in (0, 1):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            time.sleep(0.4)
            (self.shots / f"{name}-{'dark' if dark else 'light'}.png").write_bytes(self.m.screenshot_png(full=False))
        self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', 0);")


if __name__ == "__main__":
    unittest.main()
