"""Fingerprinting: what a web page can read in the Nulavio build, checked on the real engine.

Each claim in docs/research/fingerprinting.md has a test here, so a change in the
engine, in a patch or in a default that weakens it fails a run:

* the User-Agent is Firefox's own, in the page and on the wire (patch 0009);
* the protection set is the engine's set for the Strict category with Nulavio's
  additions (firefox-branding.js), read from the engine itself;
* canvas reads of every kind (raw pixels, exported image, blob, offscreen) differ
  between two sites, stay stable within one, and are not the plain values;
* a page does not learn the size of the toolbars and the sidebar, where the
  window is, or the real number of processors (every computer says 4);
* a page reads one screen size, 1920 by 1080, whatever the display is
  (NulavioFingerprinting.sys.mjs), from its first script on;
* a font the person installed is not visible to pages (patch 0010; Fedora and
  Ubuntu, the distributions the engine has font lists for);
* with WebGL available, the graphics card's model is not given out;
* a page reads UTC as its time zone; a site with "use my time zone on this
  site" on, in the shield's panel, reads the system's, with its subdomains
  and nothing else;
* a page is not told that the system asks for less motion or more contrast;
  Nulavio's own pages are; one setting tells sites again, and a bar offers it
  once when the system has one of them on;
* a site the person exempts from tracking protection gets the plain values,
  and only that site.

"Plain values" are read in the same session with the protections off, so the
tests compare like with like on any machine. Nulavio build only.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
import tiny_font

ROOT = Path(__file__).resolve().parents[2]
PROBE_FONT = "Nulavio Probe Font"  # made for the test, installed only in the throwaway home
ALLOW_LIST = 'ChromeUtils.importESModule("resource://gre/modules/ContentBlockingAllowList.sys.mjs").ContentBlockingAllowList'
OVERRIDES_PREF = "privacy.fingerprintingProtection.overrides"
GRANULAR_PREF = "privacy.fingerprintingProtection.granularOverrides"
SHARE_PREF = "nulavio.fingerprinting.shareAccessibility"
OFFERED_PREF = "nulavio.fingerprinting.accessibilityOffered"
ACCESSIBILITY = {"CSSPrefersReducedMotion", "CSSPrefersContrast", "CSSPrefersReducedTransparency"}
FINGERPRINTING = (
    "ChromeUtils.importESModule("
    '"resource://builtin-addons/nulavio-shell/modules/NulavioFingerprinting.sys.mjs").NulavioFingerprinting'
)
ASKS = "return [matchMedia('(prefers-reduced-motion: reduce)').matches, matchMedia('(prefers-contrast: more)').matches];"
# A new browser window, what its bar says, one of its buttons pressed (by its place), and the window closed.
NEW_WINDOW_BAR = """
const done = arguments[arguments.length - 1];
(async () => {
  const win = OpenBrowserWindow();
  await new Promise(r => {
    const seen = s => {
      if (s === win) { Services.obs.removeObserver(seen, "browser-delayed-startup-finished"); r(); }
    };
    Services.obs.addObserver(seen, "browser-delayed-startup-finished");
  });
  let bar = null;
  for (let i = 0; i < 40 && !bar; i++) {
    await new Promise(r => setTimeout(r, 100));
    bar = win.gNotificationBox.getNotificationWithValue("nulavio-accessibility-offer");
  }
  const buttons = bar ? [...bar.buttonContainer.querySelectorAll("button")] : [];
  const out = bar && { text: bar.messageText.textContent.trim(), buttons: buttons.map(b => b.label || b.textContent.trim()) };
  if (bar && arguments[0] !== null) {
    // A bar ignores clicks for a moment after it appears (the engine's guard against a click meant for a page).
    for (let i = 0; i < 40 && bar._clickjackingDelayActive; i++) {
      await new Promise(r => win.setTimeout(r, 100));
    }
    buttons[arguments[0]].click();
    await new Promise(r => win.setTimeout(r, 100));
  }
  win.close();
  return out;
})().then(done, e => done({ error: String(e) }));
"""
SETTING = """
const toggle = document.getElementById("nulavio-share-accessibility");
return toggle
  ? { shown: toggle.checkVisibility(), label: toggle.label, description: toggle.description, pressed: toggle.pressed }
  : null;
"""
DARK_NOW = "return matchMedia('(prefers-color-scheme: dark)').matches;"
SYSTEM_ZONE = ("America/Sao_Paulo", 180)  # the session's TZ: the name, and minutes behind UTC in January
# Sites with a registrable domain, which the per-site switch needs (127.0.0.1 and localhost have none).
ZONE_SITES = ("zone-one.example", "www.zone-one.example", "zone-two.example")
PANEL = """
const done = arguments[arguments.length - 1];
(async () => {
  const panel = () => document.getElementById("trustpanel-popup");
  if (panel()?.state !== "open") {
    await gTrustPanelHandler.showPopup();
    await new Promise(r => (panel().state === "open" ? r() : panel().addEventListener("popupshown", r, { once: true })));
  }
  const row = document.getElementById("nulavio-trustpanel-timezone");
  const toggle = row?.querySelector("moz-toggle");
  const state = row && { shown: !row.hidden && row.checkVisibility(), on: toggle.pressed,
    label: row.querySelector("label.trustpanel-header").textContent,
    name: toggle.buttonEl.getAttribute("aria-label"),  // the widget moves the switch's name to its button
    description: document.getElementById("nulavio-trustpanel-timezone-description").textContent,
    after: row.previousElementSibling?.id };
  if (arguments[0] === "press" && toggle) {
    toggle.click();  // the switch itself: it closes the panel and reloads the page
  } else if (arguments[0] !== "keep") {
    panel().hidePopup();
  }
  return state;
})().then(done, e => done({ error: String(e) }));
"""
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


class SlowPage(http.server.BaseHTTPRequestHandler):
    """A site whose /slow page takes two and a half seconds to answer. Each page keeps what its first script read."""

    def do_GET(self):
        if self.path.startswith("/slow"):
            time.sleep(2.5)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<!doctype html><meta charset=utf-8><title>slow</title>"
            b"<script>document.documentElement.dataset.screen = screen.width + 'x' + screen.height;</script>"
        )

    def log_message(self, *_args):
        pass


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
        cls.session.env["TZ"] = SYSTEM_ZONE[0]
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

    def panel(self, then: str = "close") -> dict:
        """The time zone row of the shield's panel for the page shown. Then the panel is closed, kept open
        ("keep"), or the row's switch is pressed ("press")."""
        self.m.set_context("chrome")
        try:
            state = self.m.execute_async(PANEL, [then])
        finally:
            self.m.set_context("content")
        self.assertNotIn("error", state or {}, state)
        return state

    def key(self, value: str) -> None:
        """One real key press in the browser's own window."""
        actions = [{"type": "keyDown", "value": value}, {"type": "keyUp", "value": value}]
        self.m.set_context("chrome")
        try:
            self.m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "keyboard", "actions": actions}]})
            self.m.send("WebDriver:ReleaseActions")
        finally:
            self.m.set_context("content")

    def arrives(self, script: str, want: str) -> bool:
        return bool(harness.wait_until(lambda: self.m.execute(script) == want, 10))

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
        # Every computer reports 4, the engine's one value for Linux, not its tiers (4, or 8 from 8 processors up).
        self.assertEqual(plain["hw"], os.cpu_count())
        self.assertEqual(page["hw"], 4)

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

    def test_09_pages_read_utc_and_a_site_with_the_switch_on_reads_the_systems_time_zone(self):
        utc, system = {"zone": "Atlantic/Reykjavik", "offset": 0}, dict(zip(("zone", "offset"), SYSTEM_ZONE, strict=True))
        one, sub, two = ZONE_SITES
        origins = [f"http://{site}:{self.server.port}" for site in ZONE_SITES]
        self.m.chrome(
            "Services.prefs.setStringPref('network.dns.localDomains', arguments[0].join(','));"
            "Services.prefs.setStringPref('dom.securecontext.allowlist', arguments[0].join(','));"  # the page hashes
            "for (const origin of arguments[1]) {"
            "  const principal = Services.scriptSecurityManager.createContentPrincipalFromOrigin(origin);"
            "  Services.perms.addFromPrincipal(principal, 'https-only-load-insecure', Ci.nsIPermissionManager.ALLOW_ACTION); }",
            [list(ZONE_SITES), origins],
        )
        granular = f"return Services.prefs.getStringPref('{GRANULAR_PREF}', '');"
        # The page's own Intl and Date: a script run from here has a realm of its own, which keeps the system's.
        zone = (
            "return JSON.stringify({ zone: window.Intl.DateTimeFormat().resolvedOptions().timeZone,"
            " offset: new window.Date(2026, 0, 15, 12).getTimezoneOffset() });"
        )
        with self.unprotected():
            self.assertEqual(self.measure(one)["tz"], system, "the session's time zone did not take: nothing was tested")
        # By default every page reads UTC, under the engine's name for it.
        self.assertEqual((self.measure(one)["tz"], self.measure(two)["tz"], self.measure("127.0.0.1")["tz"]), (utc, utc, utc))
        self.assertEqual(self.m.chrome(granular), "")
        # A site without a registrable domain cannot have the switch: the engine's per-site list goes by domain.
        self.assertFalse(self.panel()["shown"])
        # The switch is in the shield's panel, under the engine's own, off, with a name and an explanation.
        self.measure(one)
        row = self.panel()
        self.record("timezone-row", row)
        self.assertEqual((row["shown"], row["on"], row["after"]), (True, False, "trustpanel-toggle-section"))
        self.assertEqual(row["label"], row["name"])
        self.assertIn("UTC", row["description"])
        # The keyboard reaches it as it reaches the engine's own switch, and Space presses it. The page then
        # reloads and reads the system's time zone; so does its subdomain; no other site does.
        self.panel("keep")
        focused = "return document.activeElement?.id ?? '';"
        for _ in range(12):
            if self.m.chrome(focused) == "nulavio-trustpanel-timezone-toggle":
                break
            self.key("\ue015")  # ArrowDown
        self.assertEqual(self.m.chrome(focused), "nulavio-trustpanel-timezone-toggle", "the arrow keys never reached the switch")
        self.key(" ")
        self.assertTrue(self.arrives(zone, json.dumps(system, separators=(",", ":"))), self.m.execute(zone))
        self.assertEqual(
            json.loads(self.m.chrome(granular)),
            [{"firstPartyDomain": one, "thirdPartyDomain": "*", "overrides": "-JSDateTimeUTC"}],
        )
        self.assertEqual((self.measure(sub)["tz"], self.measure(two)["tz"]), (system, utc))
        self.measure(one)
        row = self.panel()
        self.assertEqual((row["shown"], row["on"]), (True, True))
        self.assertNotIn("UTC", row["description"])
        # Pressed again, with the pointer: UTC again, and the engine's list is empty. Then on again for the rest.
        self.panel("press")
        self.assertTrue(self.arrives(zone, json.dumps(utc, separators=(",", ":"))), self.m.execute(zone))
        self.assertEqual(self.m.chrome(granular), "")
        self.panel("press")
        self.assertTrue(self.arrives(zone, json.dumps(system, separators=(",", ":"))), self.m.execute(zone))
        # Settings lists it with the other site exceptions, and removing it there puts UTC back.
        listed = "return Services.perms.getAllByTypes(['nulavio-timezone']).map(p => p.principal.origin);"
        self.assertEqual(self.m.chrome(listed), [f"https://{one}"])
        self.m.chrome(
            "const [p] = Services.perms.getAllByTypes(['nulavio-timezone']);"
            "Services.perms.removeFromPrincipal(p.principal, p.type);"
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(granular) == "", 10), self.m.chrome(granular))
        self.assertEqual(self.measure(one)["tz"], utc)
        # The switch acts only on the site its panel was opened on (review of #379): opened on one site and
        # pressed after the tab went to another, it changes nothing for either.
        self.measure(one)
        self.panel("keep")
        self.measure(two)
        self.m.chrome("document.getElementById('nulavio-trustpanel-timezone-toggle').click();")
        self.assertEqual((self.m.chrome(listed), self.m.chrome(granular)), ([], ""))
        self.assertEqual(self.measure(two)["tz"], utc)
        # Nulavio's own pages keep the system's time zone.
        self.m.navigate(self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('newtab/newtab.html');"))
        self.assertEqual(json.loads(self.m.execute(zone)), system)

    def chrome_async(self, script: str, args: list) -> dict:
        self.m.set_context("chrome")
        try:
            out = self.m.execute_async(script, args)
        finally:
            self.m.set_context("content")
        self.assertNotIn("error", out or {}, out)
        return out

    def share(self, on: bool) -> None:
        self.m.chrome(f"{FINGERPRINTING}.setShareAccessibility(arguments[0]);", [on])

    def test_10_pages_are_not_told_the_systems_motion_and_contrast_until_one_setting_says_so(self):
        user_set = (
            f"return Services.prefs.prefHasUserValue('{OVERRIDES_PREF}')"
            f" ? Services.prefs.getStringPref('{OVERRIDES_PREF}') : null;"
        )
        system = ("ui.prefersReducedMotion", "ui.useAccessibilityTheme")  # the engine's stand-ins for the desktop's settings
        clear = "for (const pref of arguments) Services.prefs.clearUserPref(pref);"
        flags = "return [Services.prefs.getBoolPref(arguments[0], false), Services.prefs.getBoolPref(arguments[1], false)];"
        self.addCleanup(self.m.chrome, clear, [*system, SHARE_PREF, OFFERED_PREF])
        # The system has neither preference on: no bar in a new window.
        self.assertIsNone(self.chrome_async(NEW_WINDOW_BAR, [None]))
        # The system asks for less motion and more contrast.
        self.m.chrome("for (const pref of arguments) Services.prefs.setIntPref(pref, 1);", list(system))
        with self.unprotected():
            self.measure()
            self.assertEqual(self.m.execute(ASKS), [True, True], "the system's settings did not take: nothing was tested")
        # A page is told neither; Nulavio's own page follows the system.
        self.measure()
        self.assertEqual(self.m.execute(ASKS), [False, False])
        self.m.navigate(self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('newtab/newtab.html');"))
        self.assertEqual(self.m.execute(ASKS), [True, True])
        self.assertIsNone(self.m.chrome(user_set))
        # A new window now offers the setting once, in words, with two answers. "Keep as it is": nothing changes
        # and it is not offered again.
        bar = self.chrome_async(NEW_WINDOW_BAR, [1])
        self.record("accessibility-bar", bar)
        self.assertTrue(bar["text"] and len(bar["buttons"]) == 2 and all(bar["buttons"]), bar)
        self.assertEqual(self.m.chrome(flags, [SHARE_PREF, OFFERED_PREF]), [False, True])
        self.assertIsNone(self.chrome_async(NEW_WINDOW_BAR, [None]))
        # Offered again (as on a profile that never answered), "Let sites see them" turns the setting on.
        self.m.chrome("Services.prefs.clearUserPref(arguments[0]);", [OFFERED_PREF])
        self.assertIsNotNone(self.chrome_async(NEW_WINDOW_BAR, [0]))
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome("return Services.prefs.getBoolPref(arguments[0], false);", [SHARE_PREF]), 5)
        )
        # On: the engine's set is the build's without the three entries, and only those; pages are told both.
        added, removed = shipped_overrides()
        self.assertLessEqual(ACCESSIBILITY, added)
        want = {f"+{t}" for t in added - ACCESSIBILITY} | {f"-{t}" for t in removed}
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(user_set) is not None, 5))
        self.assertEqual(set(self.m.chrome(user_set).split(",")), want)
        page = self.measure()
        self.assertEqual(self.m.execute(ASKS), [True, True])
        self.assertEqual((page["hw"], page["screen"]["size"]), (4, "1920x1080"), "the rest of the protection changed with it")
        # Off again, from Settings' own writer: the engine's set is the build's default again.
        self.share(False)
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(user_set) is None, 5), self.m.chrome(user_set))
        self.measure()
        self.assertEqual(self.m.execute(ASKS), [False, False])
        # Settings has the switch, with the protections in Privacidade e Segurança, with its explanation; pressing
        # it is the same setting. (The system's settings are put back first: the page is pictured as most see it.)
        self.m.chrome(clear, list(system))
        self.m.navigate("about:preferences#privacy")
        self.assertTrue(harness.wait_until(lambda: (self.m.execute(SETTING) or {}).get("shown"), 15), self.m.execute(SETTING))
        state = self.m.execute(SETTING)
        self.record("accessibility-setting", state)
        self.assertTrue(state["label"].strip() and state["description"].strip() and not state["pressed"], state)
        self.m.execute("document.getElementById('nulavio-share-accessibility').scrollIntoView({block: 'center'});")
        try:
            for dark in (0, 1):
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                harness.wait_until(lambda want=bool(dark): self.m.execute(DARK_NOW) == want, 10)
                (self.shots / f"accessibility-setting-{'dark' if dark else 'light'}.png").write_bytes(self.m.screenshot_png())
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")
        self.m.execute("document.getElementById('nulavio-share-accessibility').click();")
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome("return Services.prefs.getBoolPref(arguments[0], false);", [SHARE_PREF]), 5)
        )

    def test_08_pages_read_one_screen_size_and_an_exempted_site_reads_the_displays(self):
        constant = {"size": "1920x1080", "avail": "1920x1080", "availAt": "0,0", "device1920": True}
        live = "return screen.width + 'x' + screen.height;"
        first, other = self.measure("127.0.0.1"), self.measure("localhost")
        with self.unprotected():
            plain = self.measure("127.0.0.1")["screen"]
        self.record("screen", {"protected": first["screen"], "plain": plain})
        self.assertNotEqual(plain["size"], constant["size"], "this display has the constant's size: nothing was tested")
        self.assertFalse(plain["device1920"])
        # What the page's first script reads, on two sites: the size, the available area and the media queries agree.
        self.assertEqual((first["screen"], other["screen"]), (constant, constant))
        self.measure("127.0.0.1")
        self.m.chrome(f"{ALLOW_LIST}.add(gBrowser.selectedBrowser);")  # the shield's switch in the address bar
        try:
            # The exempted site reads the display's, also when it comes after a protected page and changes process;
            # the page after it reads the constant again.
            self.assertEqual(self.measure("127.0.0.1")["screen"], plain)
            self.assertEqual(self.measure("localhost")["screen"], constant)
            self.assertEqual(self.measure("127.0.0.1")["screen"], plain)
            self.assertEqual(self.measure("localhost")["screen"], constant)
            # Back and forward come from the engine's cache and ask for nothing: each page still reads its own.
            for step, host, want in (("back", "127.0.0.1", plain["size"]), ("forward", "localhost", constant["size"])):
                self.m.execute(f"history.{step}();")
                self.assertTrue(self.arrives(f"return [location.hostname, {live[7:-1]}].join(' ');", f"{host} {want}"), step)
        finally:
            self.measure("127.0.0.1")
            self.m.chrome(f"{ALLOW_LIST}.remove(gBrowser.selectedBrowser);")
        self.assertEqual(self.measure("127.0.0.1")["screen"], constant)

    def test_08b_the_page_shown_keeps_the_constant_while_an_exempted_site_is_on_its_way(self):
        # Review of #375: a protected page that sends the tab to a site the person exempted is still there until
        # the answer comes. It must not read the display's size in that time.
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowPage)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        site = f"http://127.0.0.1:{server.server_address[1]}"
        live = "return location.hostname + ' ' + screen.width + 'x' + screen.height;"
        first = "return document.documentElement.dataset.screen ?? '';"
        with self.unprotected():
            plain = self.measure()["screen"]["size"]
        self.m.navigate(site + "/fast")
        self.m.chrome(f"{ALLOW_LIST}.add(gBrowser.selectedBrowser);")
        forget = (
            "const site = Services.scriptSecurityManager.createContentPrincipalFromOrigin(arguments[0]);"
            "Services.perms.removeFromPrincipal(site, 'trackingprotection');"
        )
        self.addCleanup(self.m.chrome, forget, [f"https://127.0.0.1:{server.server_address[1]}"])
        self.m.navigate(site + "/fast")
        self.assertEqual(self.m.execute(first), plain, "the site is not exempted: nothing was tested")
        self.measure("localhost")
        self.m.chrome(
            "gBrowser.selectedBrowser.loadURI(Services.io.newURI(arguments[0]),"
            " { triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal() });",
            [site + "/slow"],
        )
        seen = []
        while (now := self.m.execute(live)).startswith("localhost ") and len(seen) < 200:
            seen.append(now)
            time.sleep(0.1)
        self.assertGreaterEqual(len(seen), 5, "the slow page came at once: the page before it was never read while waiting")
        self.assertEqual(set(seen), {"localhost 1920x1080"})
        # Arrived: the exempted site reads the display's size, from its first script.
        self.assertTrue(self.arrives(first, plain), self.m.execute(first))
        self.assertEqual(self.m.execute(live), f"127.0.0.1 {plain}")

    def test_08d_only_pages_of_the_web_get_the_constant_and_an_open_page_follows_the_switch(self):
        # From the independent review of #375.
        live = "return screen.width + 'x' + screen.height;"
        with self.unprotected():
            plain = self.measure()["screen"]["size"]
        # An extension's page in a tab reads the display's size: the engine keeps its fingerprinting protection
        # away from extensions, and one may place its windows by the screen. (The Shell's new tab is such a page.)
        self.m.navigate(self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('newtab/newtab.html');"))
        self.assertEqual(self.m.execute(live), plain)
        # A page that stays open follows the engine's switch, without a new load: off, then on again.
        self.assertEqual(self.measure()["screen"]["size"], "1920x1080")
        with self.unprotected():
            self.assertTrue(self.arrives(live, plain), self.m.execute(live))
        self.assertTrue(self.arrives(live, "1920x1080"), self.m.execute(live))

    def test_08c_a_private_window_has_the_constant_and_its_own_exemptions(self):
        with self.unprotected():
            plain = self.measure()["screen"]["size"]
        before = set(self.m.window_handles())
        self.m.chrome("OpenBrowserWindow({ private: true });")
        self.assertTrue(harness.wait_until(lambda: len(set(self.m.window_handles()) - before) == 1, 20))
        private = next(iter(set(self.m.window_handles()) - before))
        self.m.switch_to(private)
        try:
            self.assertTrue(self.m.chrome("return PrivateBrowsingUtils.isWindowPrivate(window);"))
            self.assertEqual(self.measure("127.0.0.1")["screen"]["size"], "1920x1080")
            # The shield's switch in a private window is kept apart from the ordinary windows' (review of #375).
            self.m.chrome(f"{ALLOW_LIST}.add(gBrowser.selectedBrowser);")
            try:
                self.assertEqual(self.measure("127.0.0.1")["screen"]["size"], plain)
                self.assertEqual(self.measure("localhost")["screen"]["size"], "1920x1080")
            finally:
                self.measure("127.0.0.1")
                self.m.chrome(f"{ALLOW_LIST}.remove(gBrowser.selectedBrowser);")
            self.assertEqual(self.measure("127.0.0.1")["screen"]["size"], "1920x1080")
        finally:
            self.m.chrome("window.close();")
            self.m.switch_to(next(iter(before)))
        # The ordinary window was never exempted by it.
        self.assertEqual(self.measure("127.0.0.1")["screen"]["size"], "1920x1080")


if __name__ == "__main__":
    unittest.main()
