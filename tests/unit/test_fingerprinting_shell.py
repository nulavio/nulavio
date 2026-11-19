"""What the Shell adds to the engine's fingerprinting protection (#79; ADR 0016 to 0018): where it starts and what it says."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
MODULE = (SHELL / "modules" / "NulavioFingerprinting.sys.mjs").read_text(encoding="utf-8")
PATCH = (ROOT / "browser" / "patches" / "0012-rfp-per-site-audio-noise-and-one-screen-size.patch").read_text(encoding="utf-8")


class ScreenTest(unittest.TestCase):
    """The screen's size is the engine's alone (patch 0012, ADR 0016): the Shell's per-tab way went with #468."""

    def test_the_size_is_the_one_the_documents_name(self):
        width, height = re.search(r"kConstantScreenWidth = (\d+);.*?kConstantScreenHeight = (\d+);", PATCH, re.S).groups()
        size = f"{width}×{height}"
        self.assertEqual(size, "1920×1080")
        for page in (
            "docs/adr/0016-one-screen-size-and-processor-count-for-pages.md",
            "docs/research/fingerprinting.md",
            "docs/security/hardening.md",
        ):
            with self.subTest(page=page):
                self.assertIn(size, (ROOT / page).read_text(encoding="utf-8"))

    def test_the_engine_has_the_target_and_the_default_set_of_both_tracks_turns_it_on(self):
        self.assertIn("+ITEM_VALUE(ScreenSizeConstant,", PATCH)
        # Read as the build reads it (scripts/build/apply_patches.py): a commented line is not applied.
        lines = (ROOT / "browser" / "patches" / "series").read_text(encoding="utf-8").splitlines()
        series = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        self.assertIn("0012-rfp-per-site-audio-noise-and-one-screen-size.patch", series)
        # The entry as the engine reads the list (nsRFPService::CreateOverridesFromText): between commas, a sign
        # first, no space skipped. Nothing else gives pages the constant, so a set that lost it loses the screen.
        for path in ("browser/branding/nulavio/pref/firefox-branding.js", "browser/config/prefs/baseline.js"):
            line = next(
                ln
                for ln in (ROOT / path).read_text(encoding="utf-8").splitlines()
                if '"privacy.fingerprintingProtection.overrides"' in ln
            )
            overrides = re.search(r'"privacy\.fingerprintingProtection\.overrides", "([^"]+)"', line).group(1)
            self.assertIn("+ScreenSizeConstant", overrides.split(","), path)
            self.assertFalse({"-ScreenSizeConstant", "-AllTargets"} & set(overrides.split(",")), path)

    def test_the_shell_has_no_screen_size_of_its_own(self):
        # One mechanism (#468). The tab's own screen size is automation's (WebDriver BiDi's emulation): no module
        # of the Shell sets or clears it, and no window actor decides a size per page.
        self.assertFalse((SHELL / "modules" / "NulavioFingerprintingChild.sys.mjs").exists())
        for module in sorted(SHELL.rglob("*.*js")):
            text = module.read_text(encoding="utf-8")
            with self.subTest(module=module.name):
                self.assertNotRegex(text, r"\.(set|reset)ScreenAreaOverride\(")
                self.assertNotIn("NulavioFingerprintingChild", text)
        self.assertNotIn("registerWindowActor", MODULE)
        self.assertNotIn("browsing-context-attached", MODULE)
        # It still starts with the Shell, for the time zone's list and the motion and contrast setting.
        parent = (SHELL / "experiments" / "privacy" / "parent.js").read_text(encoding="utf-8")
        start = parent[parent.index("  onStartup() {") : parent.index("  onShutdown(")]
        self.assertIn("this.fingerprinting().watch();", start)
        # (One observer hears two preferences: the person's setting, and the engine's set, for #405.)
        self.assertIn("          if (data === SHARE) {\n            applyAccessibility(true);", MODULE)
        self.assertIn(
            "    Services.prefs.addObserver(OVERRIDES, watching);\n    Services.prefs.addObserver(SHARE, watching);", MODULE
        )
        self.assertIn(
            "    Services.prefs.removeObserver(OVERRIDES, watching);\n    Services.prefs.removeObserver(SHARE, watching);", MODULE
        )


class TimeZoneTest(unittest.TestCase):
    def test_the_only_pref_written_is_the_engines_per_site_list_and_only_its_own_entries(self):
        self.assertIn('const GRANULAR = "privacy.fingerprintingProtection.granularOverrides";', MODULE)
        # Every write, whatever its argument looks like, is one of these (test_personalisation pins the same counts).
        writes = re.findall(r"Services\.prefs\.(set\w+Pref|clearUserPref)\(([^,)]*)", MODULE)
        expected = [
            ("setStringPref", "GRANULAR"),
            ("clearUserPref", "GRANULAR"),
            # #405: the same list handed to the engine again after the general set changed (taken away and put
            # back, or an empty one set and cleared): the value before and after is the same.
            ("clearUserPref", "GRANULAR"),
            ("setStringPref", "GRANULAR"),
            ("setStringPref", "GRANULAR"),
            ("clearUserPref", "GRANULAR"),
            ("setStringPref", "OVERRIDES"),
            ("clearUserPref", "OVERRIDES"),
            ("setStringPref", "WRITTEN"),
            ("clearUserPref", "WRITTEN"),
            ("setBoolPref", "OFFERED"),
            ("setBoolPref", "OFFERED"),
            ("setBoolPref", "SHARE"),
            ("setBoolPref", "SHARE"),
            ("clearUserPref", "SHARE"),
        ]
        self.assertEqual(sorted(writes), sorted(expected))
        # An entry is this module's by its shape; a person's own entries in the list stay.
        self.assertIn('const ours = entry => entry?.thirdPartyDomain === "*" && entry?.overrides === SHOW_TIME_ZONE;', MODULE)
        self.assertIn("if (text === current || Services.prefs.prefIsLocked(GRANULAR)) {", MODULE)
        again = MODULE[MODULE.index("function handListAgain() {") : MODULE.index("/** For the page a tab shows")]
        self.assertIn("if (Services.prefs.prefIsLocked(GRANULAR)) {\n    return;", again)
        self.assertIn("Services.prefs.clearUserPref(GRANULAR);\n    Services.prefs.setStringPref(GRANULAR, current);", again)
        self.assertIn('Services.prefs.setStringPref(GRANULAR, "[]");\n    Services.prefs.clearUserPref(GRANULAR);', again)
        # Only after a change of the general set, and after the engine's own observer has it.
        self.assertIn("if (data === OVERRIDES && !watching.handing) {", MODULE)
        self.assertIn("Services.tm.dispatchToMainThread(() => {", MODULE)
        self.assertIn("watching.handing = false;\n                handListAgain();", MODULE)

    def test_the_choice_is_a_site_permission_that_settings_lists_and_a_private_window_cannot_make(self):
        self.assertIn('export const TIME_ZONE = "nulavio-timezone";', MODULE)
        privacy = (SHELL / "modules" / "NulavioPrivacy.sys.mjs").read_text(encoding="utf-8")
        types = privacy[privacy.index("export const TYPES = Object.freeze([") : privacy.index("]);")]
        self.assertIn('"nulavio-timezone",', types)
        panes = (SHELL / "settings" / "native" / "panes.mjs").read_text(encoding="utf-8")
        self.assertIn('"nulavio-timezone": { allow: "exceptionTimeZone" },', panes)
        self.assertIn("offered: Boolean(site) && !context?.usePrivateBrowsing && protectionOn() && !exempted", MODULE)
        # Pressed, it acts only on the site the panel was opened on.
        self.assertIn("if (now.offered && now.site === row.dataset.site) {", MODULE)

    def test_the_words_are_in_both_languages(self):
        for locale in ("en", "pt_BR"):
            words = json.loads((SHELL / "_locales" / locale / "messages.json").read_text(encoding="utf-8"))
            for key in ("timeZoneSwitch", "timeZoneSwitchOff", "timeZoneSwitchOn", "exceptionTimeZone"):
                with self.subTest(locale=locale, key=key):
                    self.assertTrue(words[key]["message"].strip())
            self.assertIn("UTC", words["timeZoneSwitchOff"]["message"])

    def test_utc_is_in_the_default_set_of_both_tracks(self):
        for path in ("browser/branding/nulavio/pref/firefox-branding.js", "browser/config/prefs/baseline.js"):
            line = next(
                ln
                for ln in (ROOT / path).read_text(encoding="utf-8").splitlines()
                if '"privacy.fingerprintingProtection.overrides"' in ln
            )
            self.assertIn("+JSDateTimeUTC", line, path)


class MotionAndContrastTest(unittest.TestCase):
    ENTRIES = ("CSSPrefersReducedMotion", "CSSPrefersContrast", "CSSPrefersReducedTransparency")

    def test_the_three_entries_are_in_the_default_set_of_both_tracks(self):
        for path in ("browser/branding/nulavio/pref/firefox-branding.js", "browser/config/prefs/baseline.js"):
            text = (ROOT / path).read_text(encoding="utf-8")
            line = next(ln for ln in text.splitlines() if '"privacy.fingerprintingProtection.overrides"' in ln)
            for entry in self.ENTRIES:
                self.assertIn(f"+{entry}", line, path)

    def test_the_setting_rewrites_the_set_itself_and_only_those_three_entries(self):
        self.assertIn(f"const ACCESSIBILITY = Object.freeze({json.dumps(list(self.ENTRIES))});", MODULE)
        apply = MODULE[MODULE.index("function applyAccessibility(changed) {") : MODULE.index("/** What the system asks for")]
        # On: from the build's default (so a new build's set is taken in), or from the person's own set, which
        # keeps its other entries. Off: only when just turned off; a person's own set gets the entries back.
        self.assertIn('const own = user !== null && user !== Services.prefs.getStringPref(WRITTEN, "");', apply)
        self.assertIn(
            'withoutAccessibility(own ? user : Services.prefs.getDefaultBranch("").getStringPref(OVERRIDES, ""))', apply
        )
        self.assertIn("} else if (!changed) {\n    return;", apply)
        self.assertIn("next = own ? withAccessibility(user) : null;", apply)
        self.assertIn("if (Services.prefs.prefIsLocked(OVERRIDES)) {", apply)
        self.assertIn('export const SHARE = "nulavio.fingerprinting.shareAccessibility";', MODULE)
        # It relaxes a protection: not one of the personalisation options, which may write none.
        options = json.loads((SHELL / "shared" / "options.json").read_text(encoding="utf-8"))["options"]
        self.assertFalse([o for o in options if "fingerprinting" in json.dumps(o)])
        panes = (SHELL / "settings" / "native" / "panes.mjs").read_text(encoding="utf-8")
        protections = panes[panes.index("      nulavioProtections: {") : panes.index("      nulavioExceptions: {")]
        self.assertIn(
            '{ id: "nulavio-share-accessibility", l10nId: "nulavio-share-accessibility", control: "moz-toggle" },', protections
        )
        self.assertIn("shell.NulavioFingerprinting.setShareAccessibility(Boolean(value));", panes)

    def test_the_guard_watches_the_setting(self):
        # A change made to it outside the browser (user.js, a script) is reported at the next start, like a change
        # to the engine's own fingerprinting prefs. (Review of #380.)
        guard = (SHELL / "modules" / "NulavioGuard.sys.mjs").read_text(encoding="utf-8")
        watched = guard[guard.index("WATCHED_PREFS = Object.freeze([") : guard.index("]);", guard.index("WATCHED_PREFS"))]
        self.assertIn('"nulavio.fingerprinting.shareAccessibility",', watched)
        self.assertIn('"privacy.fingerprintingProtection.",', watched)  # the set it rewrites

    def test_the_bar_is_offered_once_and_only_when_the_system_asks(self):
        offer = MODULE[MODULE.index("async function offerAccessibility(win) {") : MODULE.index("let watching = null;")]
        self.assertIn("if (Services.prefs.getBoolPref(OFFERED, false) || Services.prefs.getBoolPref(SHARE, false)) {", offer)
        self.assertIn("if (!(asks.reducedMotion || asks.moreContrast) || !box || box.getNotificationWithValue(BAR)) {", offer)
        self.assertIn('eventCallback: event => event === "dismissed" && Services.prefs.setBoolPref(OFFERED, true),', offer)
        for locale in ("en", "pt_BR"):
            words = json.loads((SHELL / "_locales" / locale / "messages.json").read_text(encoding="utf-8"))
            for key in ("accessibilityOffer", "accessibilityOfferShare", "accessibilityOfferKeep"):
                with self.subTest(locale=locale, key=key):
                    self.assertTrue(words[key]["message"].strip())


if __name__ == "__main__":
    unittest.main()
