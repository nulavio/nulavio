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

# Invariant I1 (REVIEW.md): the prefs of a protection. A test may read one; a line that
# names one in any other way (a setter, a prefs file, a dictionary of prefs, an argument handed to a script) is
# looked at as a write, since the name is all that such a line needs to carry. Clearing one is a write too: it
# drops a value the profile had of its own, and what is left is whatever the default is.
PROTECTION = (
    r"(?:security\.sandbox\.|security\.(?:tls|ssl|cert_pinning|OCSP|pki|mixed_content)\.|security\.enterprise_roots"
    r"|xpinstall\.signatures\.|extensions\.blocklist\.|extensions\.update\.|browser\.safebrowsing\.|services\.settings\."
    r"|app\.update\.|dom\.security\.https_only_mode|fission\.autostart)"
)
NAMES_PROTECTION = re.compile(PROTECTION)
READS_PROTECTION = re.compile(
    r"(?:get(?:Bool|Int|Char|String)Pref|prefHasUserValue|prefIsLocked|self\.pref)\(\s*\\?['\"]"
    + PROTECTION
    + r"[\w.\-]*\\?['\"]"
)
# The tests whose subject is what the browser says of a protection that is off. Nothing else may write one.
SHOWN_OFF = {
    # The Guard reports a Safe Browsing pref that something switched off in user.js while the profile was closed.
    ("test_guard.py", "test_02_changes_made_while_closed_are_reported_and_undone_or_kept"),
    # The welcome lists a protection that is off (HTTPS-Only) with its warning, not only what is fine.
    ("test_firstrun_stage.py", "test_01b_the_welcome_says_so_when_a_protection_is_off"),
}
# Tests that name a protection's pref without a getter on the same line, and only compare it: looked at one by one.
NAMED_TO_COMPARE = {
    # The appearance options change no setting that is a protection: the names say which settings must be among
    # the ones compared before and after.
    ("test_appearance.py", "test_05_walking_every_option_changes_only_its_own_prefs"),
}


def names_a_protection_other_than_to_read_it(line: str) -> bool:
    return bool(NAMES_PROTECTION.search(READS_PROTECTION.sub("", line)))


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

    def test_a_wait_for_a_page_reads_the_document_only_when_it_is_there(self):
        # While a page is being replaced the document has no root element for a moment, and
        # `document.documentElement.dataset` then throws instead of answering "not yet": the wait ends
        # in an error on a fast machine (the first nightly rehearsal of main, test_vault_ui 05).
        racy = re.compile(r"return document\.documentElement\.dataset\.ready")
        found = []
        for module in sorted((ROOT / "tests").rglob("*.py")):
            if module == Path(__file__).resolve():
                continue
            for number, line in enumerate(module.read_text(encoding="utf-8").splitlines(), 1):
                if racy.search(line):
                    found.append(f"{module.relative_to(ROOT)}:{number}")
        self.assertEqual(found, [], "write document.documentElement?.dataset.ready")

    def test_a_protection_is_switched_off_only_where_that_is_what_the_test_shows(self):
        """I1: no test weakens a protection to get a page loaded or a step done. The one exception is a test whose
        subject is the browser's own answer to a protection that is off; those are named here, each on its
        throwaway profile, and a new one is a change to this list that a reviewer sees. (Whether such a test puts
        the pref back is that test's to show on the engine, as test_firstrun_stage 01b does; it is not read here.)"""
        found = set()
        for module in sorted([*(ROOT / "tests" / "integration").glob("*.py"), *(ROOT / "tests" / "lib").glob("*.py")]):
            inside = None
            for line in module.read_text(encoding="utf-8").splitlines():
                named = re.match(r"\s*def (\w+)\(", line)
                if named:
                    inside = named.group(1)
                if names_a_protection_other_than_to_read_it(line):
                    found.add((module.name, inside))
        self.assertEqual(found, SHOWN_OFF | NAMED_TO_COMPARE)
        # The ways a test here writes a pref are all seen: a setter, a prefs file, the harness's dictionary of
        # prefs, a name handed to a script as an argument, a pref put on the default branch.
        for line in (
            "self.m.chrome(\"Services.prefs.setBoolPref('dom.security.https_only_mode', false);\")",
            "user_js.write('user_pref(\"browser.safebrowsing.malware.enabled\", false);\\n')",
            "Services.prefs.setIntPref('security.sandbox.content.level', 0)",
            'prefs.write("user_pref(\\"xpinstall.signatures.required\\", false);")',
            'harness.PROFILE_TEST_PREFS.update({"dom.security.https_only_mode": False})',
            'self.m.chrome("Services.prefs.setBoolPref(arguments[0], false);", ["dom.security.https_only_mode"])',
            "defaults.setBoolPref('app.update.auto', false); Services.prefs.lockPref('app.update.auto');",
            'PREFS = {"services.settings.server": "http://127.0.0.1:1/"}',
            # Clearing drops a value the profile had of its own (the launcher's baseline in user.js, say).
            "Services.prefs.clearUserPref('dom.security.https_only_mode');",
            "for (const n of ['network.dns.localDomains', 'dom.security.https_only_mode']) Services.prefs.clearUserPref(n);",
            # A read and a write on one line: the read does not hide the write.
            "if (Services.prefs.getBoolPref('fission.autostart')) Services.prefs.setBoolPref('fission.autostart', false);",
        ):
            self.assertTrue(names_a_protection_other_than_to_read_it(line), line)
        for line in (
            "self.assertTrue(self.pref('dom.security.https_only_mode'))",
            " sbLists: d.getStringPref('browser.safebrowsing.provider.google5.lists'),",
            'const v5 = Services.prefs.getBoolPref("browser.safebrowsing.provider.google5.enabled", false);',
            "Services.prefs.setBoolPref('nulavio.immersive.enabled', true);",
            'Services.prefs.setIntPref("network.trr.mode", 5);',  # a choice of the person's, tested as one (DNS)
        ):
            self.assertFalse(names_a_protection_other_than_to_read_it(line), line)


if __name__ == "__main__":
    unittest.main()
