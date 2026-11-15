"""Meeting links, per profile (#221): open in the service's app (the default) or join in the browser.

With "join in the browser", a Zoom meeting link goes to the address where Zoom documents joining from a
browser, before any request leaves; with the default, the link is left as it is. Zoom's names are resolved
to this machine, where nothing answers on 443: the test reads which address the tab tried, never Zoom.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

PERSONALISE = (
    'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs").NulavioPersonalise'
)
TRIED = "return gBrowser.selectedBrowser.currentURI.spec;"


@unittest.skipUnless(harness.nulavio_engine(), "the meeting-link choice is the Nulavio build's Shell (NULAVIO_ENGINE)")
class MeetingLinksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.m.chrome("Services.prefs.setStringPref('network.dns.localDomains', 'zoom.us,acme.zoom.us,example.org');")

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def choose(self, value: str) -> None:
        self.m.set_context("chrome")
        try:
            self.m.execute_async(
                f"const done = arguments[arguments.length - 1]; {PERSONALISE}"
                ".set('meetingLinks', arguments[0]).then(() => done(true));",
                [value],
            )
        finally:
            self.m.set_context("content")

    def tried(self, link: str) -> str:
        self.m.navigate("about:blank")  # never the error page of the link before
        self.m.chrome("gBrowser.selectedBrowser.loadURI(Services.io.newURI(arguments[0]), "
                      "{ triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal() });", [link])  # fmt: skip
        # Nothing answers there: the tab ends on the engine's error page, with the address it tried.
        failed = "return gBrowser.selectedBrowser.documentURI?.spec.startsWith('about:neterror') ?? false;"
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(failed) and "zoom" in self.m.chrome(TRIED), 15), self.m.chrome(TRIED)
        )
        return self.m.chrome(TRIED)

    def test_01_by_default_the_link_is_left_as_it_is(self):
        self.assertEqual(self.m.chrome("return Services.prefs.getStringPref('nulavio.meetings.join', '');"), "")
        self.assertEqual(self.tried("https://zoom.us/j/1234567890?pwd=abc123"), "https://zoom.us/j/1234567890?pwd=abc123")

    def test_02_join_in_the_browser_goes_to_zooms_browser_join_address(self):
        self.choose("browser")
        self.addCleanup(self.choose, "app")
        self.assertEqual(self.m.chrome("return Services.prefs.getStringPref('nulavio.meetings.join', '');"), "browser")
        cases = {
            "https://zoom.us/j/1234567890?pwd=abc123": "https://zoom.us/wc/join/1234567890?pwd=abc123",
            "https://acme.zoom.us/j/98765432101?pwd=x.y-z&uname=Ana": "https://acme.zoom.us/wc/join/98765432101?pwd=x.y-z",
            "https://zoom.us/j/123456789": "https://zoom.us/wc/join/123456789",
            "https://zoom.us/s/1234567890": "https://zoom.us/s/1234567890",  # a host's start link: not a join link
        }
        for link, want in cases.items():
            with self.subTest(link=link):
                self.assertEqual(self.tried(link), want)

    def test_03_settings_offers_the_choice_in_integrations(self):
        self.m.navigate("about:preferences#nulavioIntegrations")
        group = (
            "const radio = document.querySelector('[data-option=\"meetingLinks\"]');"
            "return radio ? { shown: radio.checkVisibility(), label: radio.label, value: radio.value,"
            "  options: [...radio.querySelectorAll('moz-radio')].map(o => [o.value, o.label]) } : null;"
        )
        self.assertTrue(harness.wait_until(lambda: (self.m.execute(group) or {}).get("shown"), 15), self.m.execute(group))
        state = self.m.execute(group)
        print(f"settings: {state}", file=sys.stderr)
        self.assertEqual([value for value, _ in state["options"]], ["app", "browser"])
        self.assertTrue(all(label.strip() for _, label in state["options"]), state)
        self.assertEqual(state["value"], "app")


if __name__ == "__main__":
    unittest.main()
