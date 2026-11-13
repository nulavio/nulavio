"""Per-site privacy on the Nulavio build (S14): real engine signals, no invented counters.

* Every baseline pref the build ships in distribution.ini is in effect in an
  engine profile, and tracking protection is in its Strict category (the
  engine recomputes a category that is only a default to "standard").
* A third-party script the engine's classifier lists as a tracker (through
  its own test-entries pref, test profile only) is blocked in a normal
  window; the engine's content-blocking log, which the address bar's site
  panel shows, records it; the site panel lists it.
* The per-site switch (the engine's allow list) lets it load; Settings ->
  Site exceptions lists that exception and removing it blocks the tracker
  again.
"""

from __future__ import annotations

import configparser
import json
import os
import sys
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
import settings_page

PRIVACY = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs").NulavioPrivacy'
ALLOW_LIST = 'ChromeUtils.importESModule("resource://gre/modules/ContentBlockingAllowList.sys.mjs").ContentBlockingAllowList'
BLOCKED_TRACKING = 0x00001000  # nsIWebProgressListener.STATE_BLOCKED_TRACKING_CONTENT


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise AssertionError(result["error"])
    return result["ok"]


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's profiles and Shell (NULAVIO_ENGINE)")
class PrivacyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        # Test profile only: the engine's classifier lists "localhost" as a tracker.
        cls.m.chrome("Services.prefs.setStringPref('urlclassifier.trackingTable.testEntries', 'localhost');")
        cls.shots = harness.artifacts_dir() / "privacy"
        cls.shots.mkdir(parents=True, exist_ok=True)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def load_fixture(self) -> str:
        type(self).n += 1
        self.m.navigate(self.server.url(f"/privacy-page?n={self.n}"))
        time.sleep(0.5)
        return self.m.execute("return document.getElementById('state').textContent;")

    def blocked_origins(self) -> list[str]:
        log = json.loads(self.m.chrome("return gBrowser.selectedBrowser.getContentBlockingLog();"))
        return [origin for origin, events in log.items() if any(e[0] & BLOCKED_TRACKING and e[1] for e in events)]

    def test_01_baseline_prefs_are_in_effect_and_tracking_protection_is_strict(self):
        ini = configparser.ConfigParser(delimiters=("=",), interpolation=None)
        ini.optionxform = str
        ini.read(self.session.engine.path.parent / "distribution" / "distribution.ini")
        expected = dict(ini["Preferences"])
        self.assertTrue(expected)
        actual = self.m.chrome(
            "const out = {}; for (const name of arguments[0]) { const t = Services.prefs.getPrefType(name);"
            " out[name] = t === 128 ? Services.prefs.getBoolPref(name) : t === 64 ? Services.prefs.getIntPref(name)"
            " : t === 32 ? Services.prefs.getStringPref(name) : null; } return out;",
            [list(expected)],
        )
        for name, raw in expected.items():
            with self.subTest(pref=name):
                self.assertEqual(actual[name], json.loads(raw), f"{name} is not in effect")
        state = self.m.chrome(
            "return [Services.prefs.getStringPref('browser.contentblocking.category'),"
            " Services.prefs.getBoolPref('privacy.trackingprotection.enabled'),"
            " Services.prefs.getIntPref('nulavio.privacy.seeded', 0)];"
        )
        self.assertEqual(state, ["strict", True, 1])

    def test_02_tracker_blocked_logged_and_shown_in_the_site_panel(self):
        self.assertEqual(self.load_fixture(), "no tracker")
        origin = f"http://localhost:{self.server.port}"
        self.assertIn(origin, self.blocked_origins())
        # The address bar's site panel (the engine's trust panel) counts what the log holds.
        self.m.chrome("document.getElementById('trust-icon-container').click();")
        header = self.m.chrome(
            "return document.getElementById('trustpanel-blocker-section-header')?.getAttribute('data-l10n-args') ?? '';"
        )
        self.assertTrue(harness.wait_until(lambda: '"count":1' in self.m.chrome(
            "return document.getElementById('trustpanel-blocker-section-header')?.getAttribute('data-l10n-args') ?? '';"
        ), timeout=10), header)  # fmt: skip
        self.m.chrome("document.getElementById('trustpanel-popup')?.hidePopup();")

    def test_03_per_site_switch_is_listed_in_settings_and_reversible(self):
        self.assertEqual(self.load_fixture(), "no tracker")
        self.m.chrome(f"{ALLOW_LIST}.add(gBrowser.selectedBrowser);")  # what the site panel's switch does
        self.assertEqual(self.load_fixture(), "tracker ran")
        exceptions = chrome_async(self.m, f"return {PRIVACY}.exceptions();")
        site = [e for e in exceptions if e["type"] == "trackingprotection"]
        self.assertEqual([e["site"] for e in site], ["127.0.0.1"])

        # The settings page lists it (ADR 0011: "Sites com exceções", in Privacidade e segurança).
        settings_page.open_pane(self.m, "privacy")
        each = "moz-box-item.nulavio-exception"
        of_type = lambda kind: lambda found: any(row["data"].get("type") == kind for row in found)  # noqa: E731
        rows = settings_page.wait_rows(self.m, "nulavio-exceptions", of_type("trackingprotection"), each)
        built_in = [row for row in rows if "Padrão do navegador" in row["description"]]  # said in words
        mine = [row for row in rows if row not in built_in]
        self.assertEqual(len(mine), 1, rows)
        self.assertEqual(mine[0]["data"]["type"], "trackingprotection")
        self.assertIn("Proteção contra rastreamento desligada", mine[0]["description"])
        # The engine's own defaults are listed as such (addons.mozilla.org may offer add-ons).
        amo = lambda row: urlsplit(row["data"].get("origin", "")).hostname == "addons.mozilla.org"  # noqa: E731
        self.assertTrue(any(row["data"]["type"] == "install" and amo(row) for row in built_in), rows)
        # uBlock Origin's state, as the add-on manager and its own storage report it.
        self.assertTrue(settings_page.wait_control(self.m, "nulavio-filter-lists")["label"])
        settings_page.shoot(self.m, self.shots, "exceptions")
        settings_page.click_row(self.m, "nulavio-exceptions", "trackingprotection", "remove", each)
        settings_page.wait_rows(self.m, "nulavio-exceptions", lambda found: not of_type("trackingprotection")(found), each)
        self.assertEqual(self.load_fixture(), "no tracker")  # the protection applies again

    def measure(self) -> dict:
        type(self).n += 1
        self.m.navigate(self.server.url(f"/fp-probe?n={self.n}"))
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.getElementById('fp').textContent;"), 10))
        return json.loads(self.m.execute("return document.getElementById('fp').textContent;"))

    def test_04_fingerprinting_surface_measured_in_strict_and_standard(self):
        strict = self.measure()
        self.m.chrome("Services.prefs.setStringPref('browser.contentblocking.category', 'standard');")
        try:
            self.assertFalse(self.m.chrome("return Services.prefs.getBoolPref('privacy.fingerprintingProtection');"))
            standard = self.measure()
        finally:
            self.m.chrome("Services.prefs.setStringPref('browser.contentblocking.category', 'strict');")
        self.assertTrue(self.m.chrome("return Services.prefs.getBoolPref('privacy.fingerprintingProtection');"))
        cores = os.cpu_count()
        (self.shots / "fingerprinting.json").write_text(
            json.dumps({"cores": cores, "strict": strict, "standard": standard}, indent=2) + "\n"
        )
        # Strict turns on the engine's fingerprinting protection in normal windows: the processor count is
        # reported in tiers. Canvas readings stay stable within a session (sites that read twice keep
        # working). docs/research/fingerprinting.md records what was and was not observed.
        self.assertEqual(standard["hardwareConcurrency"], cores)
        self.assertLessEqual(strict["hardwareConcurrency"], cores)
        if cores > 8:
            self.assertLess(strict["hardwareConcurrency"], cores)
        for run in (strict, standard):
            self.assertEqual(run["dataUrl"], run["dataUrlAgain"])


if __name__ == "__main__":
    unittest.main()
