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
        # A new tab has the constant before any page; then the page's own process decides, at the two moments a
        # page comes to be shown: its window created, or the page taken back from the engine's cache.
        self.assertIn('const TOPICS = ["browsing-context-attached", ', MODULE)
        self.assertIn("events: { DOMWindowCreated: {}, pageshow: {} },", MODULE)
        self.assertIn("allFrames: false,", MODULE)
        self.assertIn('if (event.type === "pageshow" && !event.persisted) {', CHILD)

    def test_it_follows_the_engines_switch_and_the_engines_own_word_for_an_exempted_site(self):
        self.assertIn("exempted = Boolean(this.document.cookieJarSettings?.isOnContentBlockingAllowList);", CHILD)
        self.assertIn("setScreen(context, protectionOn(context.usePrivateBrowsing) && !exempted);", CHILD)
        # Nothing is taken from a page still shown: no hook on a request that is only on its way.
        for text in (MODULE, CHILD):
            self.assertNotIn("http-on-modify-request", text)
            self.assertNotIn("sendAsyncMessage", text)  # the two halves exchange nothing
        self.assertNotIn("Services.prefs.set", CHILD)  # the page's half reads the engine's switches and writes none


class TimeZoneTest(unittest.TestCase):
    def test_the_only_pref_written_is_the_engines_per_site_list_and_only_its_own_entries(self):
        self.assertIn('const GRANULAR = "privacy.fingerprintingProtection.granularOverrides";', MODULE)
        # Every write, whatever its argument looks like: one set and one clear, both of the per-site list.
        self.assertEqual(len(re.findall(r"Services\.prefs\.set\w+Pref\(", MODULE)), 1)
        self.assertEqual(MODULE.count("Services.prefs.clearUserPref("), 1)
        self.assertIn("Services.prefs.setStringPref(GRANULAR, text);", MODULE)
        self.assertIn("Services.prefs.clearUserPref(GRANULAR);", MODULE)
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


if __name__ == "__main__":
    unittest.main()
