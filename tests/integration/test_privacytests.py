"""PrivacyTests.org's 25 fingerprinting probes, run on the Nulavio build with PrivacyTests' pass rule (#79).

The probe pages are PrivacyTests' own files, unchanged (tests/fixtures/privacytests/, MIT). Each test here has
the name PrivacyTests gives the probe, so a red test maps to a red cell on their site.

How a probe passes, as in their scripts (scripts/test.js, settings-fingerprint-test.js, render.js):

* each page loads on three first-party sites; a probe whose value differs between them is "farbled";
* Settings and Screen probes pass when every run farbled, or when the value is the same in run A and run B,
  between which the system's settings change (Screen: the display's size);
* Device probes pass when they farble, or when the value is the same on different machines.

What this file does with one machine:

* Settings runs A and B are two sessions that differ in time zone, reduced motion, contrast and installed
  fonts. A third session has another display size, for the Screen probes.
* The plain values are read in the same sessions with the protections off (test_00). They show that a setting
  really changed, so a stable protected value means something.
* A Device probe cannot change machine here. It passes when it farbles, or when its value is one that
  DEVICE_CONSTANTS says is the same on every machine by construction (an API the engine does not have, the
  engine's own math library). The values are written here, and this module runs on three machines: a
  developer's computer, the release build's (every release, before it is signed) and GitHub's runner (every
  published release: the privacytests workflow). A value that followed the machine would fail on one of
  them, which is their comparison between machines. Pull requests do not run it: they have no Nulavio build.

Not changed by anything here, so their tests show stability only: the panels around the screen (a headless
run has none), the keyboard layout (the engine has no Keyboard Map API) and reduced transparency (the engine
keeps that media query off). Their pages record those two as "Unsupported", which test_00b holds.

The audio probe and the two Screen probes pass only on an engine with Nulavio's patch 0012; on an older one
(160.0-0.6 or earlier, under this tree's Shell) they are skipped with that reason.

KNOWN_GAPS lists the probes that do not pass yet, each with its reason. A probe listed there is skipped with
that reason while it fails, and fails the run once it passes, until its line is removed: the list only gets
shorter. Every other probe must pass. Nulavio build only.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
import tiny_font

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "privacytests"
SITES = ("pt-one.example", "pt-two.example", "pt-three.example")  # three first parties; they resolve to this machine
# PrivacyTests' pages post their results only with a sessionId in the address, which is never given here. One
# path does not ask for it: the Device page's watchdog posts when `new AudioContext()` takes over two seconds.
# So both of its results addresses resolve to this machine too, where nothing listens for them.
LOCAL_ONLY = (*SITES, "results.privacytests.org", "results.pto2.example")
PAGES = {"Device": "deviceFingerprinting", "Settings": "settingsFingerprinting", "Screen": "screenFingerprinting"}
PROBES = {
    "Device": (
        "Logical CPU cores",
        "Device memory",
        "JavaScript heap size limit",
        "Math: Infinity - Infinity",
        "Math.tan(-1e300)",
        "Math.sin(-1e300)",
        "Math.tanh(0.123)",
        "AudioContext fingerprint",
        "Canvas2D geometry",
        "userAgentData.architecture",
        "userAgentData.platformVersion",
        "AudioContext base latency",
    ),
    "Settings": (
        "Time zone",
        "Reduced motion preference",
        "Reduced transparency preference",
        "Display contrast preference",
        "Keyboard layout",
        "Available screen width",
        "Available screen height",
        "Available screen left",
        "Available screen top",
        "User-installed font (DOM)",
        "User-installed font (canvas)",
    ),
    "Screen": ("Screen width", "Screen height"),
}
# The same on every machine by construction. The NaN byte is x86-64's: Nulavio has no other build (#79).
DEVICE_CONSTANTS = {
    "Logical CPU cores": "4",  # NavigatorHWConcurrency: the engine's one value for every machine on Linux
    "Device memory": "undefined",  # the engine has no Device Memory API
    "JavaScript heap size limit": "undefined",  # nor performance.memory
    "Math: Infinity - Infinity": "255",
    "Math.tan(-1e300)": "-1.4214488238747245",  # the engine's own math library (JSMathFdlibm), not the system's
    "Math.sin(-1e300)": "0.8178819121159085",
    "Math.tanh(0.123)": "0.12238344189440875",
    "userAgentData.architecture": "undefined",  # no User-Agent Client Hints
    "userAgentData.platformVersion": "undefined",
    "AudioContext base latency": "0",  # the engine reports no buffering, whatever the audio device
}
# Probes that do not pass yet, and why (#79). Each fix removes its line.
KNOWN_GAPS: dict[str, str] = {}
# A probe that passes only with Nulavio's engine patch 0012. This tree's Shell may be run on an engine from before
# the patch (160.0-0.6 or earlier); a build of this tree has it, and the probe must then pass. The screen's size
# is the engine's alone since #468: the Shell no longer sets it per tab.
BEFORE_THE_PATCH = {
    "AudioContext fingerprint": "this engine is from before patch 0012, which adds per-site noise to rendered audio",
    "Screen width": "this engine is from before patch 0012, which gives every document one screen size",
    "Screen height": "this engine is from before patch 0012, which gives every document one screen size",
}
HAS_PATCH = """
const { RFPHelper } = ChromeUtils.importESModule("resource://gre/modules/RFPHelper.sys.mjs");
return "AudioRandomization" in RFPHelper.getTargets();
"""
FONT_TEXT = "font fingerprinting"  # the text PrivacyTests' font probes measure
RUNS = {  # what "the system" is in each session
    "A": {"tz": "Europe/Paris", "screen": (1366, 768), "fonts": False, "motion": 1, "contrast": 1},
    "B": {"tz": "Europe/Berlin", "screen": (1366, 768), "fonts": True, "motion": 0, "contrast": 0},
    "other display": {"tz": "Europe/Paris", "screen": (1600, 900), "fonts": False, "motion": 1, "contrast": 1},
}
RESULTS = "return document.body.getAttribute('data-test-results');"
UNSUPPORTED = "Error: Unsupported"  # what their page records for a probe that threw new Error('Unsupported')
# What the engine does not have, and must go on saying so: a probe that starts to answer is a new reading.
NOT_IN_THE_ENGINE = {"Keyboard layout", "Reduced transparency preference"}
PREPARE = """
Services.prefs.setStringPref("network.dns.localDomains", arguments[0].join(","));
// crypto.subtle, which the canvas probe hashes with, exists only in a secure context: PrivacyTests serves HTTPS.
Services.prefs.setStringPref("dom.securecontext.allowlist", arguments[1].join(","));
for (const origin of arguments[2]) {
  const principal = Services.scriptSecurityManager.createContentPrincipalFromOrigin(origin);
  Services.perms.addFromPrincipal(principal, "https-only-load-insecure", Ci.nsIPermissionManager.ALLOW_ACTION);
}
Services.prefs.setIntPref("ui.prefersReducedMotion", arguments[3]);
Services.prefs.setIntPref("ui.useAccessibilityTheme", arguments[4]);
"""


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def merged(per_site: list[str]) -> str | list[str]:
    """PrivacyTests' mergeDomainResults: all three values when they differ (farbled), otherwise the one value."""
    return list(per_site) if len(set(per_site)) > 1 else per_site[0]


def farbled(value: str | list[str]) -> bool:
    return isinstance(value, list)


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults and patches (NULAVIO_ENGINE)")
class PrivacyTestsProbes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(Quiet, directory=str(FIXTURES))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.addClassCleanup(cls.server.shutdown)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.port = cls.server.server_address[1]
        cls.read = {name: cls.run_session(config) for name, config in RUNS.items()}
        folder = harness.artifacts_dir() / "privacytests"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "values.json").write_text(json.dumps(cls.read, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def run_session(cls, config: dict) -> dict:
        """{"protected" | "plain": {group: {probe: value, merged over the three sites}}} for one system configuration."""
        session = harness.GeckoProfileSession(name="Pessoal")
        try:
            session.env["TZ"] = config["tz"]
            session.env["MOZ_HEADLESS_WIDTH"], session.env["MOZ_HEADLESS_HEIGHT"] = map(str, config["screen"])
            if config["fonts"]:  # fonts "the person installed": PrivacyTests installs Monoton and Rosemary
                fonts = Path(session.env["XDG_DATA_HOME"]) / "fonts"
                fonts.mkdir(parents=True)
                for family in ("Monoton", "Rosemary"):
                    (fonts / f"{family.lower()}.ttf").write_bytes(tiny_font.build(family, FONT_TEXT))
            m = session.start()
            strict = "return Services.prefs.getStringPref('browser.contentblocking.category') === 'strict';"
            assert harness.wait_until(lambda: m.chrome(strict), 30), "the profile never reached the Strict category"
            origins = [f"http://{site}:{cls.port}" for site in SITES]
            m.chrome(PREPARE, [list(LOCAL_ONLY), list(SITES), origins, config["motion"], config["contrast"]])
            cls.patched = bool(m.chrome(HAS_PATCH))
            # A build of this tree has the patch: without it the audio probe would be skipped, not failed.
            assert cls.patched or not harness.built_from_this_tree(), "a build of this tree without patch 0012's targets"
            out = {"protected": cls.load_pages(m)}
            with cls.unprotected(m):
                out["plain"] = cls.load_pages(m)
            return out
        finally:
            session.cleanup()

    @classmethod
    def load_pages(cls, m) -> dict:
        groups = {}
        for group, page in PAGES.items():
            per_site: dict[str, list[str]] = {}
            for site in SITES:
                m.navigate(f"http://{site}:{cls.port}/{page}.html")
                assert harness.wait_until(lambda: m.execute(RESULTS), 30), f"{page} never finished on {site}"
                for probe, result in json.loads(m.execute(RESULTS)).items():
                    # A probe of something the engine does not have throws "Unsupported" (their pages since
                    # 2026-11-16); it has no value, on any site or in any run, which their rule takes as stable.
                    # Only the probes named for it: any other probe that throws fails, whatever it throws.
                    if probe in NOT_IN_THE_ENGINE and result.get("error") == UNSUPPORTED:
                        result = {"value": "unsupported"}
                    assert "error" not in result, f"{probe} on {site}: {result['error']}"
                    per_site.setdefault(probe, []).append(result["value"])
            assert set(per_site) == set(PROBES[group]), f"{page}: the probes are not the ones this file names"
            groups[group] = {probe: merged(values) for probe, values in per_site.items()}
        return groups

    @staticmethod
    @contextlib.contextmanager
    def unprotected(m):
        """The same session with the engine's fingerprinting protections off: the plain values."""
        m.chrome(
            "Services.prefs.setStringPref('browser.contentblocking.category', 'standard');"
            "Services.prefs.setBoolPref('privacy.baselineFingerprintingProtection', false);"
        )
        try:
            assert not m.chrome("return Services.prefs.getBoolPref('privacy.fingerprintingProtection');")
            yield
        finally:
            m.chrome(
                "Services.prefs.clearUserPref('privacy.baselineFingerprintingProtection');"
                "Services.prefs.setStringPref('browser.contentblocking.category', 'strict');"
            )

    # -- the rule ------------------------------------------------------------------

    def values(self, group: str, probe: str, mode: str = "protected") -> list:
        runs = ("A", "other display") if group == "Screen" else ("A", "B")
        return [self.read[run][mode][group][probe] for run in runs]

    def passes(self, group: str, probe: str) -> bool:
        values = self.values(group, probe)
        if all(farbled(value) for value in values):
            return True
        if group == "Device":
            return probe in DEVICE_CONSTANTS and all(value == DEVICE_CONSTANTS[probe] for value in values)
        return values[0] == values[1]

    def check(self, group: str, probe: str) -> None:
        read = f"{probe}: {self.values(group, probe)}"
        gaps = {**KNOWN_GAPS, **({} if self.patched else BEFORE_THE_PATCH)}
        if self.passes(group, probe):
            self.assertNotIn(probe, gaps, f"it passes now: remove its line from the gaps. {read}")
            return
        if probe in gaps:
            if group == "Screen":  # before the patch nothing hides the display's size, and nothing changes it
                self.assertEqual(self.values(group, probe), self.values(group, probe, "plain"), read)
            self.skipTest(f"known gap (#79): {gaps[probe]}. {read}")
        self.fail(f"neither different on the three sites in both runs nor stable between them. {read}")

    # -- tests ---------------------------------------------------------------------

    def test_00_the_settings_really_changed_between_the_runs(self):
        plain = functools.partial(self.values, mode="plain")
        self.assertEqual(plain("Settings", "Time zone"), ["Europe/Paris", "Europe/Berlin"])
        self.assertEqual(plain("Settings", "Reduced motion preference"), ["reduce", "no-preference"])
        self.assertEqual(plain("Settings", "Display contrast preference"), ["more", "no-preference"])
        self.assertEqual(plain("Settings", "User-installed font (DOM)"), ["not-detected", "detected"])
        self.assertEqual(plain("Settings", "User-installed font (canvas)"), ["not-detected", "detected"])
        self.assertEqual(plain("Screen", "Screen width"), ["1366", "1600"])
        self.assertEqual(plain("Screen", "Screen height"), ["768", "900"])
        # Without the protections no site reads anything of its own: whatever differs per site comes from them.
        for group, probes in PROBES.items():
            for probe in probes:
                with self.subTest(probe=probe):
                    self.assertFalse(any(farbled(value) for value in plain(group, probe)), plain(group, probe))

    def test_00b_what_the_engine_does_not_have_reads_unsupported_with_and_without_the_protections(self):
        for probe in sorted(NOT_IN_THE_ENGINE):
            with self.subTest(probe=probe):
                for mode in ("protected", "plain"):
                    self.assertEqual(self.values("Settings", probe, mode), ["unsupported", "unsupported"])

    def test_01_every_known_gap_names_a_probe(self):
        every = {probe for probes in PROBES.values() for probe in probes}
        self.assertLessEqual(set(KNOWN_GAPS) | set(BEFORE_THE_PATCH), every)
        self.assertFalse(set(KNOWN_GAPS) & set(BEFORE_THE_PATCH))
        self.assertLessEqual(set(DEVICE_CONSTANTS), set(PROBES["Device"]))


def _probe_test(group: str, probe: str):
    def test(self):
        self.check(group, probe)

    test.__doc__ = f"PrivacyTests, {group}: {probe}"
    return test


for _group, _probes in PROBES.items():
    for _number, _probe in enumerate(_probes, 1):
        _slug = "".join(ch if ch.isalnum() else "_" for ch in _probe.lower()).strip("_")
        while "__" in _slug:
            _slug = _slug.replace("__", "_")
        setattr(PrivacyTestsProbes, f"test_{_group.lower()}_{_number:02d}_{_slug}", _probe_test(_group, _probe))


if __name__ == "__main__":
    unittest.main()
