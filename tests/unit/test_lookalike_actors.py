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
REAL, FAKE = "https://paypal.example/account", "https://paypa1.example/login"


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

    def warned(self, name: str, url: str, page: str | None, asked: list[str]) -> None:
        """The warning opened for `url`, with `page` as where "continue" goes (None: to `url` itself)."""
        case = self.cases[name]
        self.assertEqual((case["warned"], case["decided"]), (True, True), case)
        self.assertTrue(case["warning"].startswith(WARNING), case["warning"])
        self.assertEqual((case["url"], case["page"]), (url, page), case)
        self.assertEqual(case["asked"], asked, case)

    def not_warned(self, name: str, decided: bool, asked: list[str] | None = None) -> None:
        case = self.cases[name]
        self.assertEqual((case["warned"], case["decided"]), (False, decided), case)
        if asked is not None:
            self.assertEqual(case["asked"], asked, case)

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
        self.assertEqual(self.cases["parent_nothing_to_warn"], {**case, "warned": False, "warning": None, "url": None})

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

    # Password fields in frames: each document from the field's up to the tab's page is checked, nearest first.

    def test_a_lookalike_frame_in_another_sites_page_shows_the_warning_and_continue_goes_back_to_that_page(self):
        self.warned("frame_lookalike_in_a_real_page", FAKE, REAL, [FAKE])

    def test_a_frame_without_an_address_of_its_own_is_checked_by_its_principals_site(self):
        self.warned(
            "frame_blank_with_a_lookalike_principal",
            "https://paypa1.example/",
            "https://news.example/",
            ["https://paypa1.example/"],
        )
        self.warned("frame_blob_with_a_lookalike_principal", "https://paypa1.example/", REAL, ["https://paypa1.example/"])
        # One check per site: the srcdoc frame and the frame around it are the same site.
        self.warned("frame_srcdoc_inside_a_lookalike_frame", "https://paypa1.example/", REAL, ["https://paypa1.example/"])

    def test_a_sandboxed_frame_is_checked_by_its_address(self):
        self.warned("frame_sandboxed_on_the_lookalike_site", FAKE, REAL, [FAKE])
        # A sandboxed srcdoc has no site of its own; the page around it is checked.
        self.not_warned("frame_sandboxed_srcdoc_in_a_real_page", True, [REAL])

    def test_a_data_frame_is_checked_by_the_documents_around_it(self):
        # In the look-alike page itself, "continue" goes to the checked address: the tab's page.
        self.warned("frame_data_in_a_lookalike_page", FAKE, None, [FAKE])
        self.warned("frame_data_in_a_lookalike_frame", FAKE, REAL, [FAKE])

    def test_a_lookalike_frame_around_the_fields_frame_is_found(self):
        self.warned("frame_nested_lookalike_in_the_middle", FAKE, REAL, ["https://widgets.example/login", FAKE])
        # The nearest look-alike decides, and nothing past it is checked.
        nearest = "https://paypa1-login.example/form"
        self.warned("frame_nearest_lookalike_decides", nearest, FAKE, [nearest])

    def test_a_frame_of_another_site_on_a_real_page_is_not_warned(self):
        self.not_warned("frame_real_in_a_real_page", True, ["https://widgets.example/login", REAL])

    def test_documents_without_a_sites_address_are_never_checked(self):
        # The system's, an expanded principal's or an extension's (Nulavio's unlock page): nothing to compare.
        self.not_warned("frame_no_site_anywhere", True, [])

    def test_a_locked_primary_password_decides_nothing_for_a_frame_either(self):
        self.not_warned("frame_primary_password_locked", False, [FAKE, REAL])

    def test_a_frame_of_a_page_the_tab_has_left_never_replaces_it(self):
        left = (
            "frame_tab_page_navigated",
            "frame_tab_page_navigated_during_a_later_check",
            "frame_tab_page_changed_only_at_the_top",
            "frame_tab_shows_another_context",
            "frame_actor_gone",
            "frame_blank_other_site",
        )
        for name in left:
            with self.subTest(name):
                self.not_warned(name, False)

    def test_continue_goes_to_the_tabs_page_where_it_is_now(self):
        self.warned("frame_tab_page_replace_state", FAKE, f"{REAL}?tab=2#top", [FAKE])

    def test_a_tab_page_without_a_sites_address_leaves_continue_nowhere_to_go(self):
        # The warning opens; its "continue" has no page to go back to (an empty `page`), never the frame's document.
        self.warned("frame_tab_page_without_a_site", FAKE, "", [FAKE])

    def test_a_field_in_the_tabs_page_opens_the_warning_as_before(self):
        for name in ("parent_warns", "parent_replace_state"):
            with self.subTest(name):
                self.warned(name, FAKE, None, [FAKE])


if __name__ == "__main__":
    unittest.main()
