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

    def test_continue_back_goes_only_from_the_warning_the_engines_actor_opened(self):
        case = self.cases["dismiss_back"]
        self.assertEqual(case["unbound"], {"threw": "no-way-back", "remembered": 0})
        self.assertEqual(case["none"], {"threw": "no-way-back", "remembered": 0})
        expected = {"bound": True, "fragment": False, "other_entry": False, "other_page": False, "unbound": False}
        self.assertEqual(case["can"], {**expected, "no_history": False})
        self.assertEqual(case["bound"], {"dismissed": True, "remembered": 1})

    def test_continue_back_remembers_nothing_once_the_tab_left_the_warning(self):
        case = self.cases["dismiss_back_left_during_the_read"]
        self.assertEqual((case["answer"], case["remembered"]), ({"threw": "no-way-back"}, 0), case)

    def test_continue_remembers_the_pair_the_warning_showed(self):
        case = self.cases["dismiss_shown_pair"]
        self.assertEqual(case["answer"], {"dismissed": True}, case)
        self.assertEqual(case["confirmed"], [{"site": FOUND["site"], "similar": FOUND["similar"]}])
        self.assertEqual(case["after"], {"suspicious": False})  # not warned again for this pair

    def test_continue_remembers_nothing_when_the_saved_logins_now_give_another_pair(self):
        """#762: the saved logins change while the warning is open; neither the pair shown nor the new one is saved."""
        case = self.cases["dismiss_pair_changed"]
        self.assertEqual(case["shown"], FOUND)
        self.assertEqual(case["now"], {**FOUND, "similar": "paypa.example"}, case)  # the address imitates another site
        self.assertEqual((case["answer"], case["confirmed"]), ({"dismissed": False}, []), case)

    def test_continue_remembers_nothing_when_no_pair_is_left(self):
        case = self.cases["dismiss_no_pair_left"]
        self.assertEqual((case["answer"], case["confirmed"]), ({"dismissed": False}, []), case)

    def test_continue_never_remembers_a_pair_the_warning_did_not_show(self):
        case = self.cases["dismiss_other_pair"]
        for name in ("other_similar", "other_site", "no_pair", "not_strings"):
            self.assertEqual(case[name], {"dismissed": False}, name)
        self.assertEqual(case["confirmed"], [])

    def test_continue_on_a_pair_already_confirmed_keeps_it_once(self):
        case = self.cases["dismiss_already_confirmed"]
        self.assertEqual((case["first"], case["again"]), ({"dismissed": True}, {"dismissed": True}), case)
        self.assertEqual(case["confirmed"], [{"site": FOUND["site"], "similar": FOUND["similar"]}])

    def test_continue_on_a_pair_already_confirmed_keeps_the_list_order(self):
        case = self.cases["dismiss_already_confirmed_keeps_order"]
        self.assertEqual((case["first"], case["other"], case["again"]), ({"dismissed": True},) * 3, case)
        newest_first = [
            {"site": "examp1e.example", "similar": "example.example"},
            {"site": FOUND["site"], "similar": FOUND["similar"]},
        ]
        self.assertEqual(case["confirmed"], newest_first)

    def test_continue_remembers_nothing_from_a_read_the_saved_logins_changed_after(self):
        case = self.cases["dismiss_after_a_burst_of_changes"]
        self.assertEqual((case["answer"], case["confirmed"]), ({"dismissed": False}, []), case)
        self.assertEqual(case["after"], {"suspicious": False}, case)  # the saved logins give no pair now

    def test_continue_back_says_no_way_back_first_when_the_tab_left_and_the_pair_changed(self):
        case = self.cases["dismiss_back_left_and_pair_changed"]
        self.assertEqual((case["answer"], case["remembered"]), ({"threw": "no-way-back"}, 0), case)

    def test_checks_at_once_share_one_read_of_the_saved_logins(self):
        case = self.cases["concurrent_checks"]
        self.assertEqual((case["first"], case["second"]), (FOUND, FOUND))
        self.assertEqual(case["reads"], 1, case)

    def test_a_burst_of_changes_does_not_hold_a_check_back(self):
        case = self.cases["storage_changed_during_every_read"]
        self.assertEqual((case["first"], case["reads"]), (FOUND, 3), case)

    def test_a_change_during_the_read_is_read_again(self):
        case = self.cases["storage_changed_during_the_read"]
        self.assertEqual(case["after"], {"suspicious": False}, case)

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
