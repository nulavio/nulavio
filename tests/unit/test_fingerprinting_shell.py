"""What the Shell adds to the engine's fingerprinting protection (#79; ADR 0016 to 0018): where it starts and what it says.

Also the shape of the engine patches for the screen and the audio noise (0012, 0016).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
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


class AudioReadersTest(unittest.TestCase):
    """#406: the audio noise is also on what a node inside an offline rendering hands to script (patch 0016, ADR 0019).
    What a page reads is checked on the engine (tests/integration/test_fingerprinting.py, 11b); this holds the
    patch's shape, which that test cannot see: where it reaches, and that a context that plays is left alone."""

    NAME = "0016-rfp-the-audio-noise-on-what-a-node-reads-in-an-offline-rendering.patch"
    WEBAUDIO = "dom/media/webaudio/"

    def setUp(self):
        self.patch = (ROOT / "browser" / "patches" / self.NAME).read_text(encoding="utf-8")
        self.header, _, diff = self.patch.partition("\n---\n")
        # The lines the patch adds, per file.
        self.added: dict[str, str] = {}
        for part in ("\n" + diff).split("\n--- a/")[1:]:
            path, _, body = part.partition("\n")
            self.added[path] = "\n".join(ln[1:] for ln in body.splitlines() if ln.startswith("+") and not ln.startswith("+++"))

    def test_it_is_applied_after_the_patch_that_adds_the_noise(self):
        lines = (ROOT / "browser" / "patches" / "series").read_text(encoding="utf-8").splitlines()
        series = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        self.assertIn(self.NAME, series)
        self.assertLess(series.index("0012-rfp-per-site-audio-noise-and-one-screen-size.patch"), series.index(self.NAME))
        self.assertIn("\nOwner: ", self.header)
        self.assertIn("\nUpstream: ", self.header)

    def test_it_reaches_the_readers_and_nothing_else(self):
        readers = {"AnalyserNode.cpp", "ScriptProcessorNode.cpp", "AudioWorkletNode.cpp", "DynamicsCompressorNode.cpp"}
        expected = {self.WEBAUDIO + name for name in readers | {"AudioContext.cpp", "AudioContext.h", "DynamicsCompressorNode.h"}}
        expected |= {"toolkit/components/resistfingerprinting/nsRFPService." + ext for ext in ("cpp", "h")}
        self.assertEqual(set(self.added), expected)
        for name in sorted(readers):
            with self.subTest(reader=name):
                self.assertIn("nsRFPService::RandomizeAudioSamplesWithKey(", self.added[self.WEBAUDIO + name])
        # A worklet has two places: its inputs, and the values of a parameter a node is connected to, in a block
        # where that node gave samples, on the whole value there (the stored schedule is not changed, and a block in
        # which no connected node gave samples reads as written).
        worklet = self.added[self.WEBAUDIO + "AudioWorkletNode.cpp"]
        self.assertEqual(worklet.count("RandomizeAudioSamplesWithKey("), 2)
        self.assertIn(
            "if (frames == WEBAUDIO_BLOCK_SIZE && connected &&\n        !connected->LastChunks()[0].IsNull()) {", worklet
        )
        # The noise is patch 0012's own steps, moved to one function, not a second set of numbers.
        service = self.added["toolkit/components/resistfingerprinting/nsRFPService.cpp"]
        self.assertEqual(service.count("1.0e-4f / 32768.0f"), 1)
        self.assertEqual(service.count("MoveAudioSamples("), 3)  # the function, and its two callers
        # No new target: the readers follow AudioRandomization, which the default set of both tracks turns on.
        self.assertNotIn("RFPTargets.inc", self.patch)
        for path in ("browser/branding/nulavio/pref/firefox-branding.js", "browser/config/prefs/baseline.js"):
            line = next(
                ln
                for ln in (ROOT / path).read_text(encoding="utf-8").splitlines()
                if '"privacy.fingerprintingProtection.overrides"' in ln
            )
            self.assertIn("+AudioRandomization", line, path)

    def test_what_a_value_reads_does_not_depend_on_how_many_values_are_read(self):
        """Review of #593: the noise is made from the values, so noise made from fewer of them is other noise. An
        analyser's short read of its samples gets the start of the whole window's noisy copy (its spectrum is always
        made from the whole window); the other readers put the noise on all they hand over, whatever script reads."""
        analyser = self.added[self.WEBAUDIO + "AnalyserNode.cpp"]
        self.assertIn("if (aLength < fftSize) {", analyser)
        self.assertIn(
            "GetTimeDomainData(window.Elements(), fftSize);\n      PodCopy(aData, window.Elements(), aLength);", analyser
        )
        # Without room for the whole window the page reads silence, not the plain samples.
        self.assertIn(
            "if (!window.SetLength(fftSize, fallible)) {\n        // Not the plain samples instead.\n"
            "        PodZero(aData, aLength);\n        return;",
            analyser,
        )
        self.assertIn(
            "noiseKey, mInputBuffer->GetDataForWrite(i),\n                  aNode->BufferSize());",
            self.added[self.WEBAUDIO + "ScriptProcessorNode.cpp"],
        )
        worklet = self.added[self.WEBAUDIO + "AudioWorkletNode.cpp"]
        block = "RandomizeAudioSamplesWithKey(mNoiseKey, dest,\n" + " " * 49 + "WEBAUDIO_BLOCK_SIZE);"
        self.assertEqual(worklet.count(block), 2)
        self.assertIn("&reduction, 1);", self.added[self.WEBAUDIO + "DynamicsCompressorNode.cpp"])

    def test_a_context_that_plays_has_no_key_so_nothing_a_person_hears_is_changed(self):
        context = self.added[self.WEBAUDIO + "AudioContext.cpp"]
        # The one place the key is made: only for an offline context, and only where the protection applies.
        self.assertIn("Document* doc = aIsOffline ? aWindow->GetExtantDoc() : nullptr;", context)
        self.assertIn("doc->ShouldResistFingerprinting(RFPTarget::AudioRandomization)", context)
        self.assertEqual(context.count("GetFingerprintingRandomizationKey("), 1)
        self.assertIn("const nsTArray<uint8_t> mAudioNoiseKey;", self.added[self.WEBAUDIO + "AudioContext.h"])
        # Every reader takes the key from the context (the worklet's engine holds a copy made when the node was):
        # none asks the document itself, so none can be on where the context's key is empty.
        for name in ("AnalyserNode.cpp", "ScriptProcessorNode.cpp", "AudioWorkletNode.cpp", "DynamicsCompressorNode.cpp"):
            with self.subTest(reader=name):
                added = self.added[self.WEBAUDIO + name]
                self.assertIn("AudioNoiseKey()", added)
                self.assertNotIn("ShouldResistFingerprinting", added)
                self.assertNotIn("CookieJarSettings", added)
        # An empty key changes nothing.
        service = self.added["toolkit/components/resistfingerprinting/nsRFPService.cpp"]
        self.assertIn("if (aSiteKey.Length() < sizeof(words) || !aData || !aLength) {\n    return;", service)

    def test_the_documents_name_the_readers(self):
        for page in ("docs/adr/0019-rendered-audio-differs-per-site.md", "docs/research/fingerprinting.md"):
            text = (ROOT / page).read_text(encoding="utf-8")
            with self.subTest(page=page):
                for words in ("patch 0016", "AnalyserNode", "ScriptProcessorNode", "AudioWorklet", "reduction"):
                    self.assertTrue(words in text, f"{page} does not say: {words}")


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


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class GuardAndTheShellsOwnSetTest(unittest.TestCase):
    """#654: at each start with "let sites see my motion and contrast preferences" on, the Shell writes the engine's
    set again from the build's default. After a build whose default changed, the Guard took that for a change made
    outside the browser. The module now tells the Guard which set is its own; the Guard keeps it in its record, and
    leaves out only a change from exactly the set its record kept as Nulavio's to exactly the one the module holds now.
    Anything else about the set is still reported (tests/lib/guard_own_writes_driver.mjs runs both modules; test_guard
    07 the real engine)."""

    @classmethod
    def setUpClass(cls):
        modules = [str(SHELL / "modules" / name) for name in ("NulavioGuard.sys.mjs", "NulavioFingerprinting.sys.mjs")]
        done = subprocess.run(
            ["node", str(ROOT / "tests" / "lib" / "guard_own_writes_driver.mjs"), *modules],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        cls.out = json.loads(done.stdout)

    def test_the_shells_own_update_after_a_new_build_is_not_reported(self):
        case = self.out["ownUpdate"]
        self.assertEqual(case["set"], self.out["current"])
        self.assertEqual(len(case["findings"]), 1, "the case the issue is about did not happen: nothing was tested")
        self.assertEqual(case["reported"], [])
        self.assertEqual(case["told"], [self.out["current"]])
        self.assertEqual(case["findings"][0][2], self.out["current"])
        current = self.out["current"]
        self.assertEqual(
            self.out["sameBuild"], {"set": current, "written": current, "told": [current], "findings": [], "reported": []}
        )

    def test_a_set_changed_while_closed_is_still_reported(self):
        for name in ("outsidePlain", "outsideStripped"):
            with self.subTest(name):
                case = self.out[name]
                self.assertEqual(case["told"], [None])  # the module did not write it before: not its own
                self.assertEqual(case["reported"], case["findings"])
                self.assertEqual(len(case["reported"]), 1)
        # The Shell took the accessibility entry out of the set put there, and that is still reported.
        self.assertEqual(self.out["outsideStripped"]["reported"][0][2], "+CanvasRandomization")

    def test_a_forged_memory_of_the_shells_set_does_not_hide_a_change(self):
        # The module rewrites what it takes for its own set; the record did not keep the earlier one as Nulavio's.
        case = self.out["forgedWritten"]
        self.assertEqual(case["told"], [self.out["current"]])
        self.assertEqual(case["reported"], case["findings"])
        self.assertEqual(len(case["reported"]), 1)

    def test_a_forged_set_the_shell_writes_over_leaves_only_its_own_update(self):
        # A set and the module's memory forged on a profile whose record kept the earlier set as Nulavio's: the module
        # writes the build's set over both, so the profile ends as after Nulavio's own update, with nothing of the
        # forgery left, and the one change since the record is that update.
        case, own = self.out["forgedOverwritten"], self.out["ownUpdate"]
        self.assertEqual((case["set"], case["written"]), (own["set"], own["written"]))
        self.assertEqual(case["findings"], own["findings"])
        self.assertEqual(case["reported"], [])

    def test_only_the_shells_memory_forged_does_not_hide_the_replacement_of_a_persons_set(self):
        # OpenCodeReview on #825: the person's own set is in the record; only the module's memory of its set, a
        # setting the Guard does not watch, is changed in the closed profile to name it. The module then writes the
        # build's set over the person's: still a change made outside, since the record never held that set as Nulavio's.
        case = self.out["forgedMemoryOnly"]
        self.assertEqual(case["set"], self.out["current"], "the module did not write its set: nothing was tested")
        self.assertEqual(
            case["findings"], [["privacy.fingerprintingProtection.overrides", "+CanvasRandomization", self.out["current"]]]
        )
        self.assertEqual(case["reported"], case["findings"])

    def test_the_setting_turned_on_outside_is_reported_with_the_set_it_brings(self):
        case = self.out["shareOutside"]
        self.assertEqual(case["told"], [self.out["current"]])  # its own set now; the record kept none
        self.assertEqual(
            {f[0] for f in case["reported"]},
            {"nulavio.fingerprinting.shareAccessibility", "privacy.fingerprintingProtection.overrides"},
        )
        self.assertEqual(self.out["shareOff"]["told"], [])

    def test_the_guard_goes_by_both_values_and_the_name(self):
        self.assertEqual(
            self.out["filter"],
            {
                "same": 0,
                "otherBefore": 1,
                "otherAfter": 1,
                "notOwnedThen": 1,
                "notOwnedNow": 1,
                "otherName": 1,
                "otherKind": 1,
                "none": 1,
            },
        )
        self.assertEqual(
            self.out["ownedValues"],
            [{"privacy.fingerprintingProtection.overrides": self.out["current"], "a": 1, "b": True}, {}, {}, {}],
        )
        guard = (SHELL / "modules" / "NulavioGuard.sys.mjs").read_text(encoding="utf-8")
        check = guard[guard.index("  async #check() {") : guard.index("  /** The engine's notice, or a change")]
        # Nulavio's value at the last start comes from the record, never from the profile at this one.
        self.assertIn("const fresh = Guard.withoutOwnValues(found, saved.owned, this.#owned);", check)
        # The record then keeps only what was declared at this start: nothing is carried over from the last one.
        self.assertEqual(check.count("owned: { ...this.#owned }"), 2)
        self.assertNotIn("saved.owned,", check.replace("withoutOwnValues(found, saved.owned,", ""))
        self.assertIn("owned: Guard.ownedValues(data.owned)", guard)  # read from the profile: checked
        self.assertIn("{ schema: SCHEMA, updated: new Date().toISOString(), snapshot, pending, expected, owned }", guard)
        # The module tells its set only where it remembers one made from the build's default, and none otherwise.
        apply = MODULE[MODULE.index("function applyAccessibility(changed) {") : MODULE.index("/** Tell the Guard")]
        self.assertIn(
            "if (next !== null && !own) {\n    Services.prefs.setStringPref(WRITTEN, next);\n    ownValue(next);\n  } else {\n"
            "    Services.prefs.clearUserPref(WRITTEN);\n    ownValue(null);",
            apply,
        )
        self.assertEqual(MODULE.count("ownValue("), 3)  # the two calls and the function
        self.assertNotIn("ownPrefChanges", MODULE)  # by name, it would hide a change made outside
        self.assertNotIn("ownPrefWrite", guard + MODULE)  # by the profile's value, a forged memory would pass


if __name__ == "__main__":
    unittest.main()
