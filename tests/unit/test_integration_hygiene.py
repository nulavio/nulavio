"""What every integration test keeps to: it removes what it put in /tmp, and it leaves the protections on.

Each engine session makes a temporary home there (about 180 MB once uBlock Origin and its lists are in it), and /tmp is
often a tmpfs: a module that only stops its session leaves the home behind at every run, the device fills, and other
modules then fail for no reason of their own."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = re.compile(r"harness\.(?:GeckoProfileSession|Session)\(")
CLEANUP = re.compile(r"\.cleanup\(\)|add(?:Class)?Cleanup\([^)]*\.cleanup\b")

# Invariant I1 (.github/ai-review/instructions.md): the prefs of a protection, as a test would write them into a
# profile, at run time (set…Pref) or in a prefs file (user_pref). Reading one, or clearing a user value, is not this.
PROTECTION = (
    r"(?:security\.sandbox\.|xpinstall\.signatures\.required|browser\.safebrowsing\.|services\.settings\."
    r"|app\.update\.|dom\.security\.https_only_mode|fission\.autostart)"
)
WRITES_PROTECTION = re.compile(r"(?:set(?:Bool|Int|Char|String)Pref|user_pref)\(\s*\\?['\"]" + PROTECTION)
# The tests whose subject is what the browser says of a protection that is off. Nothing else may write one.
SHOWN_OFF = {
    # The Guard reports a Safe Browsing pref that something switched off in user.js while the profile was closed.
    ("test_guard.py", "test_02_changes_made_while_closed_are_reported_and_undone_or_kept"),
    # The welcome lists a protection that is off (HTTPS-Only) with its warning, not only what is fine.
    ("test_firstrun_stage.py", "test_01b_the_welcome_says_so_when_a_protection_is_off"),
}


class IntegrationHygieneTest(unittest.TestCase):
    def test_every_module_that_starts_a_session_cleans_one_up(self):
        modules = sorted((ROOT / "tests" / "integration").glob("test_*.py"))
        self.assertTrue(modules)
        leaving = []
        for module in modules:
            text = module.read_text(encoding="utf-8")
            if SESSION.search(text) and not CLEANUP.search(text):
                leaving.append(module.name)
        self.assertEqual(leaving, [], "these start an engine session and never call its cleanup()")

    def test_a_protection_is_switched_off_only_where_that_is_what_the_test_shows(self):
        """I1: no test weakens a protection to get a page loaded or a step done. The one exception is a test whose
        subject is the browser's own answer to a protection that is off; those are named here, each on its
        throwaway profile, and a new one is a change to this list that a reviewer sees."""
        found = set()
        for module in sorted([*(ROOT / "tests" / "integration").glob("*.py"), *(ROOT / "tests" / "lib").glob("*.py")]):
            inside = None
            for line in module.read_text(encoding="utf-8").splitlines():
                named = re.match(r"\s*def (\w+)\(", line)
                if named:
                    inside = named.group(1)
                if WRITES_PROTECTION.search(line):
                    found.add((module.name, inside))
        self.assertEqual(found, SHOWN_OFF)
        # One that is switched off at run time is put back by the same test.
        stage = (ROOT / "tests" / "integration" / "test_firstrun_stage.py").read_text(encoding="utf-8")
        body = stage[stage.index("def test_01b_the_welcome_says_so_when_a_protection_is_off") :].split("\n    def ", 1)[0]
        self.assertIn("addCleanup(self.m.chrome, \"Services.prefs.clearUserPref('dom.security.https_only_mode');\")", body)
        # The pattern does find a test that would do it.
        for line in (
            "self.m.chrome(\"Services.prefs.setBoolPref('dom.security.https_only_mode', false);\")",
            "user_js.write('user_pref(\"browser.safebrowsing.malware.enabled\", false);\\n')",
            "Services.prefs.setIntPref('security.sandbox.content.level', 0)",
            'prefs.write("user_pref(\\"xpinstall.signatures.required\\", false);")',
        ):
            self.assertRegex(line, WRITES_PROTECTION)
        for line in (
            "self.assertTrue(self.pref('dom.security.https_only_mode'))",
            "Services.prefs.clearUserPref('dom.security.https_only_mode');",
            "Services.prefs.setBoolPref('nulavio.immersive.enabled', true);",
        ):
            self.assertNotRegex(line, WRITES_PROTECTION)


if __name__ == "__main__":
    unittest.main()
