"""The tracking parameters Nulavio adds to the engine's clean links (#158, docs/research/clean-links.md)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "research" / "clean-links.md"
BASELINE = ROOT / "browser" / "config" / "prefs" / "baseline.js"


def table(word: str) -> set[str]:
    """The parameters of the rows whose last column says `word` (added, kept)."""
    names: set[str] = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 5 and cells[4].startswith(f"**{word}**"):
            names |= set(re.findall(r"`([^`]+)`", cells[0]))
    return names


def strip_list() -> list[str]:
    match = re.search(
        r'^user_pref\("privacy\.query_stripping\.strip_list", "([^"]*)"\);$', BASELINE.read_text(encoding="utf-8"), re.M
    )
    if not match:
        raise AssertionError("privacy.query_stripping.strip_list is not in baseline.js")
    return match.group(1).split()


class CleanLinksTest(unittest.TestCase):
    def test_the_pref_holds_exactly_the_parameters_the_table_adds(self):
        added = table("added")
        self.assertGreaterEqual(len(added), 5, "the table's added rows were not read")
        self.assertEqual(sorted(strip_list()), sorted(added))

    def test_no_parameter_the_table_keeps_is_stripped(self):
        kept = table("kept")
        self.assertIn("mkt_tok", kept)  # an unsubscribe link can depend on it
        self.assertFalse(kept & set(strip_list()))

    def test_only_exact_names_once_each(self):
        names = strip_list()
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertRegex(name, r"^[a-z_][a-z0-9_]*$", "the engine compares exact names: no patterns, no upper case")


if __name__ == "__main__":
    unittest.main()
