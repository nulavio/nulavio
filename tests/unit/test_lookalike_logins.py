"""Flow D's read of the saved logins under Node, with a stand-in login manager (tests/lib/lookalike_logins_driver.mjs).

Reading the logins decrypts them, which asks for a Primary Password that is set and not yet entered. The look-alike
check runs on any site with a password field, so it must not read them then (#708, R41), and must still find a
look-alike once the person has entered it. The window actors are in test_lookalike_actors.py; the real engine runs
the check in tests/integration/test_passwords.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOUND = {"suspicious": True, "site": "paypa1.example", "similar": "paypal.example"}
LOCKED = {"suspicious": False, "locked": True}


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class LookalikeLoginsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        driver = ROOT / "tests" / "lib" / "lookalike_logins_driver.mjs"
        module = ROOT / "browser" / "shell" / "modules" / "NulavioPasswords.sys.mjs"
        done = subprocess.run(["node", str(driver), str(module)], capture_output=True, text=True, timeout=60, check=True)
        cls.cases = json.loads(done.stdout)

    def test_a_primary_password_not_entered_is_never_asked_for(self):
        case = self.cases["locked"]
        self.assertEqual((case["prompts"], case["reads"]), (0, 0), case)
        self.assertEqual(case["first"], LOCKED)
        self.assertEqual(case["again"], LOCKED)  # nothing kept: each check looks at the token again
        self.assertEqual(self.cases["locked_no_logins"], {"first": LOCKED, "reads": 0, "prompts": 0})

    def test_continuing_while_locked_remembers_nothing(self):
        expected = {"answer": {"dismissed": False}, "remembered": 0, "reads": 0, "prompts": 0}
        self.assertEqual(self.cases["locked_dismiss"], expected)

    def test_continue_back_to_the_tabs_page_remembers_nothing_without_a_page_to_go_back_to(self):
        case = self.cases["dismiss_back"]
        self.assertEqual(case["first"], {"threw": "no-way-back", "remembered": 0})
        self.assertEqual(case["none"], {"threw": "no-way-back", "remembered": 0})
        self.assertEqual(case["after"], {"dismissed": True, "remembered": 1})
        self.assertEqual(case["can"], [False, True, False, False])

    def test_the_look_alike_is_found_once_the_primary_password_is_entered(self):
        case = self.cases["locked_then_entered"]
        self.assertEqual(case["locked"], LOCKED)
        self.assertEqual(case["entered"], FOUND)
        self.assertEqual((case["prompts"], case["reads"]), (0, 1), case)

    def test_without_a_primary_password_the_look_alike_is_found(self):
        case = self.cases["no_primary_password"]
        self.assertEqual((case["first"], case["again"]), (FOUND, FOUND))
        self.assertEqual(case["reads"], 1, case)  # kept until the saved logins change

    def test_a_store_still_starting_is_waited_for_not_taken_as_locked(self):
        case = self.cases["store_starting"]
        self.assertEqual(case["first"], FOUND)
        self.assertEqual(case["reads"], 1, case)

    def test_a_change_to_the_saved_logins_is_read_again(self):
        case = self.cases["storage_changed"]
        self.assertEqual(case["first"], FOUND)
        self.assertEqual(case["after"], {"suspicious": False})
        self.assertEqual(case["reads"], 2, case)


if __name__ == "__main__":
    unittest.main()
