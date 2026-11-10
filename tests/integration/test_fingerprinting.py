"""Fingerprinting: what a web page can read in the Nulavio build, checked on the real engine.

Each claim in docs/research/fingerprinting.md has a test here, so a change in the
engine, in a patch or in a default that weakens it fails a run:

* the User-Agent is Firefox's own, in the page and on the wire (patch 0009);
* the protection set is the engine's set for the Strict category with Nulavio's
  additions (firefox-branding.js), read from the engine itself;
* canvas reads of every kind (raw pixels, exported image, blob, offscreen) differ
  between two sites, stay stable within one, and are not the plain values;
* a page does not learn the size of the toolbars and the sidebar, where the
  window is, or the real number of processors;
* a font the person installed is not visible to pages (patch 0010; Fedora and
  Ubuntu, the distributions the engine has font lists for);
* with WebGL available, the graphics card's model is not given out;
* a site the person exempts from tracking protection gets the plain values,
  and only that site.

"Plain values" are read in the same session with the protections off, so the
tests compare like with like on any machine. Nulavio build only.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
import tiny_font

ROOT = Path(__file__).resolve().parents[2]
PROBE_FONT = "Nulavio Probe Font"  # made for the test, installed only in the throwaway home
ALLOW_LIST = 'ChromeUtils.importESModule("resource://gre/modules/ContentBlockingAllowList.sys.mjs").ContentBlockingAllowList'
OVERRIDES_PREF = "privacy.fingerprintingProtection.overrides"
# What Nulavio relies on from the engine's own set: if Mozilla drops one, the claim that names it goes too.
RELIED_ON = {"CanvasRandomization", "FontVisibilityLangPack", "NavigatorHWConcurrencyTiered", "ScreenAvailToResolution"}
TARGETS = """
const { RFPHelper } = ChromeUtils.importESModule("resource://gre/modules/RFPHelper.sys.mjs");
const set = Services.rfp.enabledFingerprintingProtections;
const on = Object.entries(RFPHelper.getTargets())
  .filter(([, bit]) => (set.getNth32BitSet(Math.floor(bit / 32)) >>> (bit % 32)) & 1).map(([name]) => name);
return { on, engine: String(RFPHelper.getTargetDefaults()).split(","),
  overrides: Services.prefs.getStringPref("privacy.fingerprintingProtection.overrides", ""),
  userSet: Services.prefs.prefHasUserValue("privacy.fingerprintingProtection.overrides"),
  category: Services.prefs.getStringPref("browser.contentblocking.category"),
  enabled: Services.prefs.getBoolPref("privacy.fingerprintingProtection"),
  resist: Services.prefs.getBoolPref("privacy.resistFingerprinting") };
"""


def shipped_overrides() -> tuple[set[str], set[str]]:
    """(added, removed) targets in the build's default (browser/branding/nulavio/pref/firefox-branding.js)."""
    text = (ROOT / "browser" / "branding" / "nulavio" / "pref" / "firefox-branding.js").read_text(encoding="utf-8")
    value = re.search(rf'^pref\("{re.escape(OVERRIDES_PREF)}", "([^"]*)"\);', text, re.M).group(1)
    items = [item.strip() for item in value.split(",") if item.strip()]
    return {i[1:] for i in items if i.startswith("+")}, {i[1:] for i in items if i.startswith("-")}


def distribution() -> str:
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("ID="):
                return line[3:].strip().strip('"')
    except OSError:
        pass
    return ""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults and patches (NULAVIO_ENGINE)")
class FingerprintingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        # A font "the person installed": in the home's font directory, in no distribution's list.
        fonts = Path(cls.session.env["XDG_DATA_HOME"]) / "fonts"
        fonts.mkdir(parents=True)
        (fonts / "nulavio-probe.ttf").write_bytes(tiny_font.build(PROBE_FONT))
        cls.m = cls.session.start()
        # The Shell puts tracking protection in Strict once, at the profile's first start.
        strict = "return Services.prefs.getStringPref('browser.contentblocking.category') === 'strict';"
        assert harness.wait_until(lambda: cls.m.chrome(strict), 30), "the profile never reached the Strict category"
        cls.shots = harness.artifacts_dir() / "fingerprinting"
        cls.shots.mkdir(parents=True, exist_ok=True)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    # -- helpers -------------------------------------------------------------------

    def measure(self, host: str = "127.0.0.1", font: str | None = None) -> dict:
        """What the page at this site reads. 127.0.0.1 and localhost are two sites to the engine."""
        type(self).n += 1
        query = f"n={self.n}" + (f"&font={font.replace(' ', '%20')}" if font else "")
        self.m.navigate(f"http://{host}:{self.server.port}/fp-surface?{query}")
        read = "return document.getElementById('fp')?.textContent ?? '';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(read), 30), "the page never finished")
        result = json.loads(self.m.execute(read))
        self.assertNotIn("fatal", result, result)
        return result

    @contextlib.contextmanager
    def unprotected(self):
        """The same session with the engine's fingerprinting protections off: the plain values."""
        self.m.chrome(
            "Services.prefs.setStringPref('browser.contentblocking.category', 'standard');"
            "Services.prefs.setBoolPref('privacy.baselineFingerprintingProtection', false);"
        )
        try:
            self.assertFalse(self.m.chrome("return Services.prefs.getBoolPref('privacy.fingerprintingProtection');"))
            yield
        finally:
            self.m.chrome(
                "Services.prefs.clearUserPref('privacy.baselineFingerprintingProtection');"
                "Services.prefs.setStringPref('browser.contentblocking.category', 'strict');"
            )
            on = "return Services.prefs.getBoolPref('privacy.fingerprintingProtection');"
            self.assertTrue(harness.wait_until(lambda: self.m.chrome(on), 10), "the protection did not come back")

    def record(self, name: str, data: dict) -> None:
        (self.shots / f"{name}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # -- tests ---------------------------------------------------------------------

    def test_01_the_user_agent_is_firefoxs_in_the_page_and_on_the_wire(self):
        page = self.measure()
        self.assertRegex(page["ua"], r"^Mozilla/5\.0 \(X11; Linux [a-z0-9_]+; rv:(\d+)\.0\) Gecko/20100101 Firefox/\1\.0$")
        for key in ("ua", "appVersion", "platform", "oscpu", "vendor"):
            self.assertNotIn("nulavio", page[key].lower(), f"navigator.{key} names the browser")
        self.assertEqual(self.server.agents["/fp-surface"], page["ua"], "the header sent is not what the page reads")
        # A request the browser makes on its own (not a page's) carries the same name.
        self.m.set_context("chrome")
        try:
            self.m.execute_async(
                "const done = arguments[arguments.length - 1]; fetch(arguments[0]).then(() => done(true), () => done(false));",
                [self.server.url("/page/own-request")],
            )
        finally:
            self.m.set_context("content")
        self.assertEqual(self.server.agents["/page/own-request"], page["ua"])

    def test_02_the_protection_set_is_the_engines_plus_nulavios(self):
        state = self.m.chrome(TARGETS)
        added, removed = shipped_overrides()
        self.record("targets", state)
        self.assertEqual((state["category"], state["enabled"], state["resist"]), ("strict", True, False))
        self.assertFalse(state["userSet"], "the overrides are a default of the build, which a person can change")
        in_effect = {item.strip() for item in state["overrides"].split(",") if item.strip()}
        self.assertEqual(in_effect, {f"+{t}" for t in added} | {f"-{t}" for t in removed})
        engine = set(state["engine"])
        self.assertLessEqual(RELIED_ON, engine, "the engine's own set lost a protection Nulavio's docs name")
        self.assertLessEqual(removed, engine, "an override removes something the engine no longer turns on")
        self.assertEqual(set(state["on"]), (engine - removed) | added)

    def test_03_canvas_reads_differ_per_site_and_stay_stable_within_one(self):
        first, other, again = self.measure("127.0.0.1"), self.measure("localhost"), self.measure("127.0.0.1")
        with self.unprotected():
            plain, plain_other = self.measure("127.0.0.1"), self.measure("localhost")
        self.record("canvas", {"site": first["canvas"], "other-site": other["canvas"], "plain": plain["canvas"]})
        for kind in ("pixels", "dataUrl", "blob", "offscreen"):
            with self.subTest(read=kind):
                # Without the protection both sites read the same, so every difference below comes from it.
                self.assertEqual(plain["canvas"][kind], plain_other["canvas"][kind])
                self.assertNotEqual(first["canvas"][kind], plain["canvas"][kind], "the plain value was given out")
                self.assertNotEqual(first["canvas"][kind], other["canvas"][kind], "two sites read the same value")
                # A site that reads twice, or again later in the session, gets the same answer (sites keep working).
                self.assertEqual(first["canvas"][kind], again["canvas"][kind])
        self.assertEqual(first["canvas"]["pixels"], first["canvas"]["pixelsAgain"])
        self.assertEqual(first["canvas"]["dataUrl"], first["canvas"]["dataUrlAgain"])

    def test_04_window_chrome_position_and_processor_count_are_not_given_out(self):
        page = self.measure()
        with self.unprotected():
            plain = self.measure()
        self.record("window", {"protected": {**page["win"], "hw": page["hw"]}, "plain": {**plain["win"], "hw": plain["hw"]}})
        # The outer size and the content's place on the screen give away the toolbars and the sidebar's width.
        self.assertNotEqual(plain["win"]["outer"], plain["win"]["inner"], "this window has no chrome to hide: nothing was tested")
        self.assertEqual(page["win"]["outer"], page["win"]["inner"])
        self.assertEqual((page["win"]["xy"], page["win"]["innerScreen"]), ("0,0", "0,0"))
        cores = os.cpu_count()
        self.assertEqual(plain["hw"], cores)
        self.assertLessEqual(page["hw"], cores)
        if cores > 8:
            self.assertLess(page["hw"], cores)  # reported in tiers

    def test_05_a_font_the_person_installed_is_not_visible_to_pages(self):
        with self.unprotected():
            self.assertTrue(self.measure(font=PROBE_FONT)["font"], "the test font did not load: nothing was tested")
        if distribution() not in ("fedora", "ubuntu"):
            self.skipTest("the engine has font lists for Fedora and Ubuntu only (docs/research/fingerprinting.md)")
        self.assertFalse(self.measure(font=PROBE_FONT)["font"], "a page can tell that the font is installed")
        # The system's default font is still there for pages.
        if shutil.which("fc-match"):
            default = subprocess.run(
                ["fc-match", "-f", "%{family[0]}", "sans-serif"], capture_output=True, text=True, timeout=30, check=False
            ).stdout.strip()
            if default:
                self.assertTrue(self.measure(font=default)["font"], f"the default font ({default}) is hidden from pages")

    def test_06_webgl_does_not_name_the_graphics_card(self):
        first, other = self.measure("127.0.0.1"), self.measure("localhost")
        if not isinstance(first["webgl"], dict):
            self.skipTest("no WebGL in this run (headless); NULAVIO_TEST_HEADFUL=1 on a display checks the values")
        with self.unprotected():
            plain = self.measure("127.0.0.1")
        self.record("webgl", {"protected": first["webgl"], "plain": plain["webgl"]})
        self.assertEqual((first["webgl"]["renderer"], first["webgl"]["unmaskedRenderer"]), ("Mozilla", "Mozilla"))
        self.assertNotEqual(first["webgl"]["readPixels"], plain["webgl"]["readPixels"])
        self.assertNotEqual(first["webgl"]["readPixels"], other["webgl"]["readPixels"])

    def test_07_an_exempted_site_gets_the_plain_values_and_only_that_site(self):
        with self.unprotected():
            plain = self.measure("127.0.0.1")
        self.measure("127.0.0.1")
        self.m.chrome(f"{ALLOW_LIST}.add(gBrowser.selectedBrowser);")  # the shield's switch in the address bar
        try:
            exempt, other = self.measure("127.0.0.1"), self.measure("localhost")
            self.assertEqual(exempt["canvas"]["pixels"], plain["canvas"]["pixels"])
            self.assertEqual(exempt["win"]["outer"], plain["win"]["outer"])
            self.assertNotEqual(other["canvas"]["pixels"], plain["canvas"]["pixels"], "the exemption reached another site")
            self.assertEqual(other["win"]["outer"], other["win"]["inner"])
        finally:
            self.measure("127.0.0.1")
            self.m.chrome(f"{ALLOW_LIST}.remove(gBrowser.selectedBrowser);")
        self.assertNotEqual(self.measure("127.0.0.1")["canvas"]["pixels"], plain["canvas"]["pixels"])


if __name__ == "__main__":
    unittest.main()
