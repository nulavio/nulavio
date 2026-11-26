"""#663: no search engine takes the assistant's "@ia" keyword, under Node (tests/lib/search_alias_driver.mjs).

An engine alias followed by a space makes the address bar ask that engine for suggestions, so an engine called "@ia"
would get what is typed for the assistant (threat model AI-T36). Nulavio Search refuses the alias in its own ways to
add or rename an engine (`normalizeAlias`), and takes it off an engine that has it: at start-up (older profiles) and
right after a change, since the engine's own Settings dialogs write the alias themselves. Settings then says which
engine lost it. The real engine runs the same in tests/integration/test_search.py (05b, 08).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
MODULE = SHELL / "modules" / "NulavioSearch.sys.mjs"


def locale(name: str) -> dict:
    return json.loads((SHELL / "_locales" / name / "messages.json").read_text(encoding="utf-8"))


class ReservedAliasListTest(unittest.TestCase):
    def test_the_assistant_keyword_is_reserved(self):
        """The list follows the manifest: a keyword the assistant answers to is one no engine may take."""
        keyword = json.loads((SHELL / "manifest.json").read_text(encoding="utf-8"))["omnibox"]["keyword"]
        text = MODULE.read_text(encoding="utf-8")
        reserved = json.loads(re.search(r"export const RESERVED_ALIASES = Object\.freeze\((\[.*?\])\);", text).group(1))
        self.assertIn(keyword.lower(), reserved)

    def test_settings_says_it_in_both_locales(self):
        for name in ("en", "pt_BR"):
            with self.subTest(locale=name):
                messages = locale(name)
                self.assertIn("@ia", messages["err_alias_reserved"]["message"])
                self.assertIn("$NAMES$", messages["searchAliasReserved"]["message"])
        panes = (SHELL / "settings" / "native" / "panes.mjs").read_text(encoding="utf-8")
        self.assertIn('msg("searchAliasReserved"', panes)
        self.assertIn("releasedAliases()", panes)

    def test_settings_says_it_under_the_search_shortcuts(self):
        """In the group placed right after the engine's Search Shortcuts (nulavioSearchAdd), not with the suggestion
        switches; tests/integration/test_settings_search.py (05) reads it on the page."""
        panes = (SHELL / "settings" / "native" / "panes.mjs").read_text(encoding="utf-8")
        groups = dict(re.findall(r"\n      (nulavio\w+): \{\n(.*?)\n      \},", panes, re.S))
        self.assertIn("searchAliasBar", groups["nulavioSearchAdd"])
        self.assertNotIn("searchAliasBar", groups["nulavioSearch"])
        self.assertIn('"searchShortcuts", "nulavioSearchAdd"', panes)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ReservedAliasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run(
            ["node", str(ROOT / "tests" / "lib" / "search_alias_driver.mjs"), str(MODULE)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        cls.out = json.loads(done.stdout)

    def test_the_alias_is_refused_however_it_is_typed(self):
        normalized = self.out["normalized"]
        for typed in ("ia", "@ia", "@IA", "  Ia "):
            with self.subTest(typed=typed):
                self.assertEqual(normalized[typed], "alias-reserved")
        # Only that keyword: longer ones that start or end with it stay usable.
        self.assertEqual(normalized["iab"], "@iab")
        self.assertEqual(normalized["media"], "@media")
        self.assertEqual(normalized["@ddg"], "@ddg")
        self.assertEqual(normalized[""], "")

    def test_the_shells_ways_to_add_or_rename_an_engine_refuse_it(self):
        refused = self.out["refused"]
        self.assertEqual(refused["setAlias"], "alias-reserved")
        self.assertEqual(refused["setAliasKept"], "@ddg", "a refused rename changed the alias")
        self.assertEqual(refused["addCustom"], "alias-reserved")
        self.assertEqual(refused["addSearxng"], "alias-reserved")
        self.assertEqual(refused["added"], 0, "an engine was added with the reserved alias")

    def test_an_engine_that_has_it_loses_it_at_start_up(self):
        startup = self.out["startup"]
        self.assertEqual(startup["archive"], "")
        self.assertEqual(startup["ddg"], "@ddg", "another engine's alias was touched")
        self.assertEqual(startup["released"], ["Archive"])
        self.assertEqual(len(startup["logged"]), 1, startup["logged"])

    def test_the_engines_own_dialogs_cannot_keep_it(self):
        """The engine's add and edit dialogs write the alias themselves: it is taken off right after, and the
        passes this takes are bounded (taking it off is itself a change to the engine)."""
        after = self.out["afterChange"]
        self.assertEqual(after["ddg"], "")
        self.assertEqual(after["fresh"], "")
        self.assertEqual(after["released"], ["Archive", "Duck", "Fresh"])
        self.assertTrue(after["passesBounded"])
        self.assertEqual(after["logged"], 2)

    def test_settings_stops_naming_an_engine_once_it_has_another_alias(self):
        after = self.out["afterNewAlias"]
        self.assertEqual(after["archive"], "@archive")
        self.assertEqual(after["released"], ["Duck", "Fresh"])

    def test_a_hidden_engine_is_named_again_once_it_is_back(self):
        hidden = self.out["hidden"]
        self.assertEqual(hidden["whileHidden"], ["Fresh"])
        self.assertEqual(hidden["back"], ["Duck", "Fresh"], "hiding the engine dropped its warning for good")

    def test_an_alias_given_then_cleared_before_settings_reads_is_not_named(self):
        """The engine was given another alias: clearing it afterwards is the person's choice, not "@ia" taken off."""
        after = self.out["replacedThenCleared"]
        self.assertEqual(after["fresh"], "")
        self.assertEqual(after["released"], ["Duck"])


if __name__ == "__main__":
    unittest.main()
