"""NulavioRouting.openIn, the person's explicit choice of a profile, under Node (tests/lib/routing_open_in_driver.mjs).

The link menu's "Open link in profile", a choice on the ask or blocked page and the held-back address opened after an
unlock all go through openIn. It sends the link with the routed flag, so no rule moves it again, and marked
`--nulavio-route-by explicit` (#791), as the engine's "Move tab to profile" is since #785: the receiving profile then
tracks no routed arrival, and its band never says "Aberto pela sua regra" for it, even in the profile the site's rule
names. A rule's own send and the default destination's are still tracked, for their notices (D-UX19, UX6). The real
engine runs this in tests/integration/test_routing.py (test_14c, test_04b, test_24).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "browser" / "shell" / "modules" / "NulavioRouting.sys.mjs"
ROUTER = ROOT / "browser" / "shell" / "modules" / "NulavioRouter.sys.mjs"
ROUTED_FLAG = re.search(r'export const ROUTED_FLAG = "([^"]+)";', ROUTER.read_text(encoding="utf-8")).group(1)
ROUTE_BY_FLAG = re.search(r'export const ROUTE_BY_FLAG = "([^"]+)";', ROUTER.read_text(encoding="utf-8")).group(1)
EXPLICIT = [f"--{ROUTED_FLAG}", f"--{ROUTE_BY_FLAG}", "explicit"]
LINK = ["-new-tab", "https://bank.example/page"]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class OpenInTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(
            ["node", str(ROOT / "tests" / "lib" / "routing_open_in_driver.mjs"), str(MODULE), str(ROUTER)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        cls.cases = json.loads(done.stdout)

    def test_a_running_profile_gets_the_link_marked_explicit(self):
        case = self.cases["running"]
        self.assertEqual(case["answer"], {"action": "delivered"}, case)
        self.assertEqual(case["sent"], [{"path": "/profiles/other", "args": [*EXPLICIT, *LINK], "activate": True}], case)
        self.assertEqual(case["started"], [], case)

    def test_a_profile_that_is_not_running_starts_with_the_same_marker(self):
        case = self.cases["cold"]
        self.assertEqual(case["answer"], {"action": "started"}, case)
        self.assertEqual(case["sent"], [], case)
        self.assertEqual(case["started"], [["--profile", "/profiles/other", *EXPLICIT, *LINK]], case)

    def test_an_unlocked_protected_profile_gets_it_marked_too(self):
        """The held-back address the unlock page opens once the profile is unlocked (NulavioVault)."""
        case = self.cases["unlocked"]
        self.assertEqual([s["args"] for s in case["sent"]], [[*EXPLICIT, *LINK]], case)

    def test_nothing_is_sent_where_openIn_refuses_or_stays(self):
        self.assertEqual(self.cases["current"]["answer"], {"action": "current"})
        for name, code in (("locked", "locked"), ("agent", "agent-route"), ("not_web", "invalid-url")):
            with self.subTest(name):
                self.assertEqual(self.cases[name]["error"], code, self.cases[name])
        for name in ("current", "locked", "agent", "not_web"):
            with self.subTest(name):
                self.assertEqual((self.cases[name]["sent"], self.cases[name]["started"]), ([], []), self.cases[name])

    def test_the_receiving_profile_does_not_track_it_as_a_routed_arrival(self):
        """What openIn sent, handed to the other profile's command-line handler: the flags are taken, the link is left
        for the browser to open, and no arrival is tracked, so arrivedBy() credits it to no rule."""
        received = self.cases["received"]["open_in"]
        self.assertEqual(received["left"], LINK, received)
        self.assertFalse(received["tracked"], received)
        self.assertEqual(received["listened"], [], received)

    def test_a_rules_send_and_the_default_destinations_are_still_tracked(self):
        for name in ("rule", "default"):
            with self.subTest(name):
                received = self.cases["received"][name]
                self.assertEqual(received["left"], LINK, received)
                self.assertTrue(received["tracked"], received)
                self.assertEqual(received["listened"], ["TabOpen"], received)


if __name__ == "__main__":
    unittest.main()
