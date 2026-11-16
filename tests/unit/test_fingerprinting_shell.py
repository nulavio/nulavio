"""What the Shell adds to the engine's fingerprinting protection (#79, ADR 0016): where it starts and what it says."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
MODULE = (SHELL / "modules" / "NulavioFingerprinting.sys.mjs").read_text(encoding="utf-8")
CHILD = (SHELL / "modules" / "NulavioFingerprintingChild.sys.mjs").read_text(encoding="utf-8")


class ScreenTest(unittest.TestCase):
    def test_the_size_is_the_one_the_documents_name(self):
        width, height = re.search(r"export const SCREEN = Object\.freeze\(\{ width: (\d+), height: (\d+) \}\);", CHILD).groups()
        size = f"{width}×{height}"
        self.assertEqual(size, "1920×1080")
        for page in (
            "docs/adr/0016-one-screen-size-and-processor-count-for-pages.md",
            "docs/research/fingerprinting.md",
            "docs/security/hardening.md",
        ):
            with self.subTest(page=page):
                self.assertIn(size, (ROOT / page).read_text(encoding="utf-8"))

    def test_it_starts_with_the_shell_and_each_page_decides_as_its_window_is_created(self):
        parent = (SHELL / "experiments" / "privacy" / "parent.js").read_text(encoding="utf-8")
        start = parent[parent.index("  onStartup() {") : parent.index("  onShutdown(")]
        self.assertIn("this.fingerprinting().watch();", start)
        # The page's own process decides, at the two moments a page comes to be shown: its window created, or
        # the page taken back from the engine's cache (capturing: before the page's own listeners).
        self.assertIn("events: { DOMWindowCreated: {}, pageshow: { capture: true } },", MODULE)
        self.assertIn("allFrames: false,", MODULE)
        self.assertIn('messageManagerGroups: ["browsers"],', MODULE)  # tabs only: no extension popup, no sidebar
        self.assertIn('if (event.type === "pageshow" && !event.persisted) {', CHILD)
        # Nothing gives a context the constant when it is made (every context would get it, an extension's too),
        # except as the fallback when the actor cannot be registered, where no page could decide for itself.
        self.assertNotIn("browsing-context-attached", MODULE.replace('const FALLBACK_TOPIC = "browsing-context-attached";', ""))
        failed = MODULE[MODULE.index("    } catch (e) {\n      // Without the actor") :]
        self.assertIn("Services.obs.addObserver(watching.fallback, FALLBACK_TOPIC);", failed[: failed.index("    sync();")])
        self.assertEqual(MODULE.count("FALLBACK_TOPIC"), 3)  # declared, added in the failure path, removed
        # Pages already open are decided again when the engine's protection is switched on or off.
        # So is a change of the engine's set, which says who gives pages the constant (the engine or the tab).
        switches = MODULE[MODULE.index("const SWITCHES = [") : MODULE.index("];", MODULE.index("const SWITCHES = ["))]
        self.assertEqual(
            re.findall(r'"([^"]+)"', switches),
            [
                "privacy.fingerprintingProtection",
                "privacy.fingerprintingProtection.pbmode",
                "privacy.fingerprintingProtection.overrides",
            ],
        )
        # (One observer hears two kinds of preference: the person's setting, and the engine's switches.)
        self.assertIn("          if (data === SHARE) {\n            applyAccessibility(true);", MODULE)
        self.assertIn("            if (!(engine && watching.engine)) {\n              decideOpenPages();", MODULE)

    def test_it_follows_the_engines_switch_and_the_engines_own_word_for_an_exempted_site(self):
        wants = CHILD[CHILD.index("export function wantsConstant(") : CHILD.index("export class NulavioFingerprintingChild")]
        self.assertIn("if (!protectionOn(isPrivate) || engineDecides()) {", wants)
        self.assertIn("return !cookieJarSettings?.isOnContentBlockingAllowList;", wants)
        # Not for the browser's own pages or an extension's.
        self.assertIn('principal?.isSystemPrincipal || principal?.addonPolicy || principal?.schemeIs?.("moz-extension")', wants)
        self.assertIn(
            "setScreen(context, wantsConstant(doc.nodePrincipal, doc.cookieJarSettings, context.usePrivateBrowsing));", CHILD
        )
        # Nothing is taken from a page still shown: no hook on a request that is only on its way.
        for text in (MODULE, CHILD):
            self.assertNotIn("http-on-modify-request", text)
            self.assertNotIn("sendAsyncMessage", text)  # the two halves exchange nothing
        self.assertNotIn("Services.prefs.set", CHILD)  # the page's half reads the engine's switches and writes none

    def test_an_engine_with_the_patch_decides_per_document_and_the_tabs_size_is_left_unset(self):
        # The engine's target, by the name patch 0012 gives it, and the build's set turns it on.
        self.assertIn('const TARGET = "ScreenSizeConstant"; // Nulavio\'s engine patch 0012', CHILD)
        patch = (ROOT / "browser" / "patches" / "0012-rfp-per-site-audio-noise-and-one-screen-size.patch").read_text(
            encoding="utf-8"
        )
        self.assertIn("+ITEM_VALUE(ScreenSizeConstant,", patch)
        width, height = re.search(r"kConstantScreenWidth = (\d+);.*?kConstantScreenHeight = (\d+);", patch, re.S).groups()
        self.assertEqual((width, height), ("1920", "1080"))  # the engine's size is the Shell's
        branding = (ROOT / "browser" / "branding" / "nulavio" / "pref" / "firefox-branding.js").read_text(encoding="utf-8")
        overrides = re.search(r'pref\("privacy\.fingerprintingProtection\.overrides", "([^"]+)"\);', branding).group(1)
        self.assertIn("+ScreenSizeConstant", overrides.split(","))
        # Known to the engine (asked once, of the engine's own list of targets) and turned on by the set.
        decides = CHILD[CHILD.index("export function engineDecides(") : CHILD.index("/** Give a tab the constant screen")]
        self.assertIn(
            'TARGET in ChromeUtils.importESModule("resource://gre/modules/RFPTargetConstants.sys.mjs").Targets', decides
        )
        self.assertIn('return known && turnsOn(Services.prefs.getStringPref(OVERRIDES, ""), TARGET);', decides)
        # Then no path gives a tab the constant: not a page's own decision, not the fallback.
        self.assertIn("subject.isContent && !subject.isDiscarded && !engineDecides()) {", MODULE)
        # Nor does a page clear the tab's size at each load: that would undo WebDriver BiDi's screen emulation,
        # which is the same value (independent review of #402).
        handle = CHILD[CHILD.index("  handleEvent(event) {") :]
        self.assertLess(handle.index("if (engineDecides()) {\n      return;"), handle.index("setScreen(context,"))
        # The set is read as the engine reads it: no space skipped, a sign first.
        turns = CHILD[CHILD.index("export function turnsOn(") : CHILD.index("/** Whether the engine gives each document")]
        self.assertNotIn(".trim()", turns)
        self.assertIn('(item[0] === "+" || item[0] === "-")', turns)
        self.assertEqual(len(re.findall(r"\bsetScreen\(", MODULE)), 2)  # the fallback, and the pages already open
        self.assertIn(
            "setScreen(context, wantsConstant(page.documentPrincipal, page.cookieJarSettings, context.usePrivateBrowsing));",
            MODULE,
        )


class TimeZoneTest(unittest.TestCase):
    def test_the_only_pref_written_is_the_engines_per_site_list_and_only_its_own_entries(self):
        self.assertIn('const GRANULAR = "privacy.fingerprintingProtection.granularOverrides";', MODULE)
        # Every write, whatever its argument looks like, is one of these (test_personalisation pins the same counts).
        writes = re.findall(r"Services\.prefs\.(set\w+Pref|clearUserPref)\(([^,)]*)", MODULE)
        expected = [
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

    def test_the_choice_is_a_site_permission_that_settings_lists_and_a_private_window_cannot_make(self):
        self.assertIn('export const TIME_ZONE = "nulavio-timezone";', MODULE)
        privacy = (SHELL / "modules" / "NulavioPrivacy.sys.mjs").read_text(encoding="utf-8")
        types = privacy[privacy.index("export const TYPES = Object.freeze([") : privacy.index("]);")]
        self.assertIn('"nulavio-timezone",', types)
        panes = (SHELL / "settings" / "native" / "panes.mjs").read_text(encoding="utf-8")
        self.assertIn('"nulavio-timezone": { allow: "exceptionTimeZone" },', panes)
        self.assertIn("offered: Boolean(site) && !context?.usePrivateBrowsing && protectionOn(false) && !exempted", MODULE)
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
