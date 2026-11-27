"""Flow D's read of the saved logins under Node, with a stand-in login manager (tests/lib/lookalike_logins_driver.mjs).

Reading the logins decrypts them, which asks for a Primary Password that is set and not yet entered. The look-alike
check runs on any site with a password field, so it must not read them then (#708, R41), and must still find a
look-alike once the person has entered it. The window actors are in test_lookalike_actors.py; the real engine runs
the check in tests/integration/test_passwords.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from node_tool import requires_node  # noqa: E402

FOUND = {"suspicious": True, "site": "paypa1.example", "similar": "paypal.example"}
LOCKED = {"suspicious": False, "locked": True}


@requires_node
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

    def test_continue_remembers_the_pair_only_if_saved_before_the_logins_changed(self):
        runs = self.cases["dismiss_while_the_logins_change"]["runs"]
        for hops, run in enumerate(runs):
            # The change lands at every step of the Continue in turn: a pair remembered was saved before it.
            self.assertEqual(run["dismissed"], run["savedBeforeChange"], (hops, run))
            self.assertEqual(run["confirmed"], int(run["dismissed"]), (hops, run))
        self.assertEqual({run["dismissed"] for run in runs}, {True, False}, runs)  # both sides of the save are reached

    def test_continue_back_says_no_way_back_first_when_the_tab_left_and_the_pair_changed(self):
        case = self.cases["dismiss_back_left_and_pair_changed"]
        self.assertEqual((case["answer"], case["remembered"]), ({"threw": "no-way-back"}, 0), case)

    def test_continue_in_a_private_window_writes_nothing_to_the_profile(self):
        """#652: kept in memory for private windows only, until the last one closes; a normal window still warns."""
        case = self.cases["dismiss_in_private"]
        self.assertEqual(case["shown"], {**FOUND, "inPrivate": True})  # the page says what "continue" keeps there
        self.assertEqual((case["answer"], case["again"]), ({"dismissed": True}, {"dismissed": True}), case)
        self.assertEqual(case["saved"], {"prefs": [], "confirmed": []})  # not in prefs.js, not in Settings
        self.assertEqual(case["after"], {"private": {"suspicious": False}, "normal": FOUND}, case)
        self.assertEqual(case["closed"], {**FOUND, "inPrivate": True}, case)  # the last private window closed
        self.assertEqual(case["prefs"], [])

    def test_continue_back_in_a_private_window_keeps_the_binding_and_nothing_in_the_profile(self):
        case = self.cases["dismiss_in_private_back"]
        self.assertEqual(case["unbound"], {"threw": "no-way-back"})
        self.assertEqual(case["unboundAfter"], {**FOUND, "inPrivate": True})
        self.assertEqual((case["bound"], case["after"]), ({"dismissed": True}, {"suspicious": False}), case)
        self.assertEqual((case["prefs"], case["confirmed"]), ([], []), case)

    def test_continue_in_a_private_window_keeps_only_the_pair_shown(self):
        case = self.cases["dismiss_in_private_other_pair"]
        self.assertEqual((case["other"], case["none"]), ({"dismissed": False}, {"dismissed": False}), case)
        self.assertEqual((case["after"], case["prefs"]), ({**FOUND, "inPrivate": True}, []), case)

    def test_a_private_continue_under_way_when_the_last_private_window_closes_keeps_nothing(self):
        """A choice made before the private windows all closed does not carry into the next private window."""
        case = self.cases["dismiss_in_private_ended_during_read"]
        warned = {**FOUND, "inPrivate": True}
        self.assertEqual((case["first"], case["firstAfter"]), ({"dismissed": False}, warned), case)
        self.assertEqual(case["kept"], {"dismissed": True}, case)
        self.assertEqual((case["second"], case["secondAfter"]), ({"dismissed": False}, warned), case)
        self.assertEqual(case["prefs"], [], case)

    def test_no_private_pair_is_dropped_before_the_last_private_window_closes(self):
        """The page says "until you close them all": the 201st pair confirmed in one private session keeps the first."""
        case = self.cases["dismiss_in_private_many"]
        self.assertEqual(case["kept"], 201, case)
        self.assertEqual((case["first"], case["last"]), ({"suspicious": False}, {"suspicious": False}), case)
        self.assertEqual(case["prefs"], [], case)

    def test_no_pair_confirmed_in_the_profile_is_dropped(self):
        """The page says "until you remove it in Settings": the 201st pair confirmed keeps the first (#871)."""
        case = self.cases["dismiss_many"]
        self.assertEqual(case["kept"], 201, case)
        self.assertEqual((case["first"], case["last"]), ({"suspicious": False}, {"suspicious": False}), case)
        self.assertEqual(case["listed"], 201, case)
        self.assertEqual(case["newest"], {"site": "p200.example", "similar": "paypal.example"}, case)
        self.assertEqual(case["oldest"], {"site": "p0.example", "similar": "paypal.example"}, case)
        # Removed in Settings: warned again, and only that pair.
        self.assertIs(case["firstRemoved"], True, case)
        self.assertEqual(case["secondKept"], {"suspicious": False}, case)
        self.assertEqual(case["listedAfter"], 200, case)

    def test_a_check_reads_the_confirmed_pairs_as_they_are_now(self):
        case = self.cases["dismissed_changed_elsewhere"]
        self.assertEqual((case["answer"], case["confirmed"]), ({"dismissed": True}, {"suspicious": False}), case)
        self.assertEqual(case["reset"], FOUND, case)
        self.assertEqual(case["restored"], {"suspicious": False}, case)
        self.assertEqual(case["damaged"], FOUND, case)

    def test_an_entry_that_is_not_a_pair_is_skipped(self):
        """The list edited by hand: the pairs around a malformed entry still count, and Settings still lists them."""
        case = self.cases["dismissed_with_a_malformed_entry"]
        self.assertEqual(case["confirmed"], {"suspicious": False}, case)
        self.assertEqual(case["again"], {"dismissed": True}, case)
        self.assertEqual(case["other"], {"suspicious": True, "site": "examp1e.example", "similar": "example.example"})
        self.assertEqual(case["listed"], [{"site": "paypa1.example", "similar": "paypal.example"}], case)
        self.assertEqual((case["answer"], case["otherAfter"]), ({"dismissed": True}, {"suspicious": False}), case)
        self.assertEqual(case["kept"], ["paypa1.example paypal.example", "examp1e.example example.example"], case)

    def test_continue_does_not_go_through_the_whole_list_again(self):
        case = self.cases["dismiss_does_not_reread_the_list"]
        self.assertEqual(case["at100"], case["at20"], case)

    def test_continue_after_a_change_elsewhere_reads_the_list_as_it_is_now(self):
        case = self.cases["dismiss_after_a_change_elsewhere"]
        self.assertEqual(case["confirmed"], {"suspicious": False}, case)
        self.assertEqual(case["removed"], FOUND, case)
        self.assertEqual(case["other"], {"suspicious": False}, case)
        self.assertEqual(case["kept"], ["examp1e.example example.example"], case)

    def test_a_refused_write_remembers_nothing_and_keeps_the_list(self):
        case = self.cases["dismiss_write_refused"]
        self.assertEqual(case["before"], {"dismissed": True}, case)
        self.assertEqual(case["answer"], {"threw": "NS_ERROR_ILLEGAL_VALUE"}, case)
        self.assertEqual(case["after"], FOUND, case)
        self.assertEqual(case["confirmed"], [{"site": "examp1e.example", "similar": "example.example"}], case)

    def test_a_pair_confirmed_in_a_normal_window_is_not_warned_in_a_private_one(self):
        case = self.cases["dismiss_in_normal_counts_in_private"]
        self.assertEqual((case["answer"], case["inPrivate"]), ({"dismissed": True}, {"suspicious": False}), case)
        self.assertEqual(case["confirmed"], [{"site": FOUND["site"], "similar": FOUND["similar"]}])

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
