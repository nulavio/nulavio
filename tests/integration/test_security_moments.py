"""One template for the security moments (UX4, audit SB-24). Nulavio build only.

Every page that asks for a safety decision opens with the same context line and says why it
appeared, under the same words, in a "why" disclosure. The line never repeats the band's
"Nulavio · …" name or the mark (review 2026-11-09 V4): only the band can be trusted, and pages
that take a password say to look there. Pages are opened bare (no request id),
which is enough for the parts of the template that do not depend on the request.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

# The band's name for each kind (NulavioWindow SURFACES). Where a password is typed is read from each page.
SURFACES = {
    "unlock": "bandSurfaceUnlock",
    "phone": "bandSurfacePhone",
    "methods": "bandSurfaceMethods",
    "request": "bandSurfacePermission",
    "download": "bandSurfaceDownload",
    "lookalike": "bandSurfacePassword",
    "routing": "bandSurfaceRouting",
}

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
  line: line?.textContent ?? '',
  check: document.querySelector('.moment__check')?.textContent ?? null,
  secret: Boolean(document.querySelector('input[type=password]')),
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
            surface = self.m.execute("return browser.i18n.getMessage(arguments[0]);", [SURFACES[kind]])
            self.assertFalse(state["mark"], page)
            self.assertEqual(state["text"], surface, page)
            self.assertNotIn("Nulavio", state["line"], page)
            # A page that takes a password says where to look before typing it; no other page does.
            self.assertEqual(state["secret"], kind in {"unlock", "methods", "phone"}, page)
            if state["secret"]:
                self.assertIn(f"“Nulavio · {surface}”", state["check"] or "", page)
            else:
                self.assertIsNone(state["check"], page)
            self.assertGreater(state["body"], 20, f"{page}: the why disclosure says nothing")
            seen[page] = state["why"]
        expected = self.m.execute("return browser.i18n.getMessage('momentWhy');")
        self.assertEqual(set(seen.values()), {expected}, seen)  # one wording on every page


if __name__ == "__main__":
    unittest.main()
