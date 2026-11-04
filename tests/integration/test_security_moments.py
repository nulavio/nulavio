"""One template for the security moments (UX4, audit SB-24). Nulavio build only.

Every page that asks for a safety decision opens with the same context line and says why it
appeared, under the same words, in a "why" disclosure. Pages are opened bare (no request id),
which is enough for the parts of the template that do not depend on the request.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

PAGES = {
    "vault/unlock.html": "unlock",
    "vault/phone.html": "phone",
    "vault/methods.html": "methods",
    "ai/request.html": "request",
    "warning/warning.html": "download",
    "passwords/lookalike.html": "lookalike",
    "routing/ask.html": "routing",
    "routing/blocked.html": "routing",
}

STATE = """
const why = document.querySelector('details.why, details#why');
const line = document.querySelector('.moment__context');
return {
  kind: line?.dataset.kind ?? null,
  mark: Boolean(line?.querySelector('.moment__mark')),
  text: line?.querySelector('.moment__kind')?.textContent ?? null,
  why: why?.querySelector('summary')?.textContent ?? null,
  body: why ? [...why.querySelectorAll('p, li')].map(e => e.textContent).join(' ').length : 0,
};
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class SecurityMomentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def test_01_every_moment_has_the_context_line_and_says_why(self):
        seen = {}
        for page, kind in PAGES.items():
            self.m.navigate(self.base + page)
            state = harness.wait_until(lambda: (s := self.m.execute(STATE))["text"] and s["why"] and s, timeout=15)
            self.assertTrue(state, f"{page}: no context line or no why disclosure: {self.m.execute(STATE)}")
            self.assertEqual(state["kind"], kind, page)
            self.assertTrue(state["mark"], page)
            self.assertTrue(state["text"].startswith("Nulavio · "), (page, state["text"]))
            self.assertGreater(state["body"], 20, f"{page}: the why disclosure says nothing")
            seen[page] = state["why"]
        expected = self.m.execute("return browser.i18n.getMessage('momentWhy');")
        self.assertEqual(set(seen.values()), {expected}, seen)  # one wording on every page


if __name__ == "__main__":
    unittest.main()
