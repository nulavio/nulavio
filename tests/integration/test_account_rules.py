"""Routing rules offered when the person signs in to Google in a profile (#220, decision 3).

The sign-in is the service's own sign-in cookie appearing in the profile: the test adds it as a sign-in
would, with a value made for the test, and talks to no Google server. In a group of profiles, a bar offers
once to open Google's sites in this profile; nothing is applied without the click, and either answer ends
the offer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

SHELL = "resource://builtin-addons/nulavio-shell/modules"
PRELUDE = (
    f'const R = ChromeUtils.importESModule("{SHELL}/NulavioRouting.sys.mjs").NulavioRouting;'
    f'const P = ChromeUtils.importESModule("{SHELL}/NulavioProfiles.sys.mjs").NulavioProfiles;'
)
SIGN_IN = """
Services.cookies.add(".google.com", "/", args[0], "nulavio-test", true, true, true, Date.now() + 3600 * 1000,
                     {}, Ci.nsICookie.SAMESITE_NONE, Ci.nsICookie.SCHEME_HTTPS, false);
"""
BAR = """
const bar = gNotificationBox.getNotificationWithValue("nulavio-account-rules");
if (!bar) return null;
const buttons = [...bar.buttonContainer.querySelectorAll("button")].map(b => b.label);
return { text: bar.messageText.textContent.trim(), buttons };
"""
# A click on one of the bar's buttons (index 0: the offer, 1: not now), once the bar's own guard against clicks
# that come too soon has passed (a click before it restarts the wait, as for a person).
READY = 'return !gNotificationBox.getNotificationWithValue("nulavio-account-rules")?._clickjackingDelayActive;'
PRESS = """
const bar = gNotificationBox.getNotificationWithValue("nulavio-account-rules");
bar.buttonContainer.querySelectorAll("button")[arguments[0]].click();
"""
GOOGLE = {"google.com", "gmail.com", "youtube.com", "googleusercontent.com"}


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        f"(async () => {{ {PRELUDE} {body} }})().then(v => done({{ok: v ?? null}}), e => done({{error: e?.code ?? String(e)}}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise AssertionError(result["error"])
    return result["ok"]


@unittest.skipUnless(harness.nulavio_engine(), "the offer is the Nulavio build's Shell (NULAVIO_ENGINE)")
class AccountRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        # A group of profiles, as when the person made a second one.
        chrome_async(cls.m, "return P.create({templateId: 'work', name: 'Trabalho'});")
        cls.here = chrome_async(cls.m, "return (await P.current()).id;")

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def reset(self) -> None:
        chrome_async(
            self.m,
            "for (const rule of R.rules()) await R.removeRule(rule.id);"
            "Services.prefs.clearUserPref('nulavio.accountRules.offered');"
            "Services.cookies.removeAll();"
            "gNotificationBox.getNotificationWithValue('nulavio-account-rules')?.close();",
        )

    def sign_in(self, name: str = "SID") -> None:
        chrome_async(self.m, SIGN_IN, [name])

    def bar(self):
        return self.m.chrome(BAR)

    def test_01_a_google_sign_in_is_offered_once_and_the_rules_open_its_sites_here(self):
        self.reset()
        self.addCleanup(self.reset)
        self.assertEqual(chrome_async(self.m, "return R.rules();"), [])
        self.sign_in()
        self.assertTrue(harness.wait_until(self.bar, 10), "no offer after a Google sign-in")
        shown = self.bar()
        print(f"bar: {shown}", file=sys.stderr)
        self.assertIn("Google", shown["text"])
        self.assertEqual(len(shown["buttons"]), 2)
        # Nothing is applied before the click.
        self.assertEqual(chrome_async(self.m, "return R.rules();"), [])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 10))
        self.m.chrome(PRESS, [0])
        added = lambda: chrome_async(self.m, "return R.rules();")  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: {r["value"] for r in added()} >= GOOGLE, 10), added())
        for rule in added():
            self.assertEqual((rule["match"], rule["action"], rule["profileId"]), ("domain", "open-in", self.here), rule)
        self.assertTrue(chrome_async(self.m, "return R.enabled();"))
        self.assertIsNone(self.bar())
        # Offered once: another sign-in cookie, or the same one again, brings no second bar.
        self.sign_in("__Secure-1PSID")
        self.assertFalse(harness.wait_until(self.bar, 3), "offered twice")

    def test_02_not_now_adds_nothing_and_ends_the_offer(self):
        self.reset()
        self.addCleanup(self.reset)
        self.sign_in()
        self.assertTrue(harness.wait_until(self.bar, 10), "no offer after a Google sign-in")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 10))
        self.m.chrome(PRESS, [1])
        self.assertTrue(harness.wait_until(lambda: self.bar() is None, 5))
        self.assertEqual(chrome_async(self.m, "return R.rules();"), [])
        self.assertEqual(self.m.chrome("return Services.prefs.getStringPref('nulavio.accountRules.offered', '');"), "google")
        self.sign_in()
        self.assertFalse(harness.wait_until(self.bar, 3), "offered again after Not now")

    def test_03_another_sites_cookie_or_a_private_one_offers_nothing(self):
        self.reset()
        self.addCleanup(self.reset)
        chrome_async(
            self.m,
            "Services.cookies.add('.example.org', '/', 'SID', 'x', true, true, true, Date.now() + 3600 * 1000,"
            " {}, Ci.nsICookie.SAMESITE_NONE, Ci.nsICookie.SCHEME_HTTPS, false);"
            "Services.cookies.add('.google.com', '/', 'SID', 'x', true, true, true, Date.now() + 3600 * 1000,"
            " {privateBrowsingId: 1}, Ci.nsICookie.SAMESITE_NONE, Ci.nsICookie.SCHEME_HTTPS, false);",
        )
        self.assertFalse(harness.wait_until(self.bar, 3), "offered for another site or a private window")


if __name__ == "__main__":
    unittest.main()
