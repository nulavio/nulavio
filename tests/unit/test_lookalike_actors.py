"""Flow D's window actors under Node, with stand-ins for the engine (tests/lib/lookalike_actors_driver.mjs).

When the child asks the parent to check a page, and when the parent opens the warning after a check
that waited. The rules on what the child may read are in test_shell.py; the real engine runs the same
flow in tests/integration/test_passwords.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "browser" / "shell" / "modules"
WARNING = "moz-extension://shell/passwords/lookalike.html?"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class LookalikeActorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        driver = ROOT / "tests" / "lib" / "lookalike_actors_driver.mjs"
        child, parent = MODULES / "NulavioLookalikeChild.sys.mjs", MODULES / "NulavioLookalikeParent.sys.mjs"
        done = subprocess.run(
            ["node", str(driver), str(child), str(parent)], capture_output=True, text=True, timeout=60, check=True
        )
        cls.cases = json.loads(done.stdout)

    def asked(self, name: str) -> int:
        return self.cases[name]["asked"]

    def test_a_focus_the_page_gives_itself_asks_nothing(self):
        self.assertEqual(self.asked("child_script_focus"), 0)
        self.assertEqual(self.asked("child_focus_after_input"), 1)

    def test_the_first_click_or_key_in_a_field_the_page_focused_asks(self):
        self.assertEqual(self.asked("child_script_focus_then_key"), 1)
        self.assertEqual(self.asked("child_script_focus_then_click"), 1)
        # with or without the engine's activation: a trusted click or key is the person's (the page can use it up)
        self.assertEqual(self.asked("child_key_without_activation"), 1)
        self.assertEqual(self.asked("child_click_without_activation"), 1)

    def test_only_trusted_events_on_a_password_field(self):
        self.assertEqual(self.asked("child_untrusted"), 0)
        self.assertEqual(self.asked("child_not_a_password_field"), 0)
        self.assertEqual(self.asked("child_other_event"), 0)

    def test_a_held_keys_repeats_do_not_ask(self):
        self.assertEqual(self.asked("child_held_key_repeats"), 0)

    def test_once_per_document_unless_the_parent_did_not_decide(self):
        self.assertEqual(self.asked("child_once_per_document"), 1)
        self.assertEqual(self.asked("child_asks_again_when_not_decided"), 2)
        self.assertEqual(self.asked("child_not_again_when_the_query_fails"), 1)

    def test_the_warning_opens_for_the_checked_address(self):
        case = self.cases["parent_warns"]
        self.assertEqual(case["checked"], "https://paypa1.example/login")
        self.assertTrue(case["warned"])
        self.assertTrue(case["warning"].startswith(WARNING), case["warning"])
        self.assertIn("url=https%3A%2F%2Fpaypa1.example%2Flogin", case["warning"])
        self.assertIs(case["decided"], True)
        self.assertEqual(self.cases["parent_nothing_to_warn"], {**case, "warned": False, "warning": None})

    def test_a_locked_primary_password_decides_nothing_so_the_next_input_asks_again(self):
        # The module compared nothing rather than ask for the Primary Password (#708): the child asks again.
        case = self.cases["parent_primary_password_locked"]
        self.assertEqual((case["warned"], case["decided"]), (False, False), case)

    def test_a_change_of_address_inside_the_document_does_not_cancel_the_warning(self):
        case = self.cases["parent_replace_state"]
        self.assertTrue(case["warned"], case)
        self.assertIn("url=https%3A%2F%2Fpaypa1.example%2Flogin", case["warning"])  # the address that was checked
        self.assertIs(case["decided"], True)

    def test_a_page_the_tab_has_left_is_never_replaced(self):
        left = ("parent_tab_moved_on_cached", "parent_tab_shows_another_context", "parent_actor_gone", "parent_other_origin")
        for name in left:
            with self.subTest(name):
                self.assertEqual((self.cases[name]["warned"], self.cases[name]["decided"]), (False, False), self.cases[name])


if __name__ == "__main__":
    unittest.main()
