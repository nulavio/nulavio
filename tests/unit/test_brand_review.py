"""The brand review of 2026-11 (#175): its proposals are generated, measured and leave the brand alone.

These checks last while the review is open. The pull request that applies the maintainer's choice
retires them together with docs/brand/review-2026-11.md's proposals.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "brand"))

import build_logo  # noqa: E402
import build_review  # noqa: E402
import build_tokens  # noqa: E402
import contrast  # noqa: E402

REVIEW = ROOT / "docs" / "brand" / "review-2026-11.md"
N_ROUTE = f'd="{build_logo.ROUTE}"'  # today's symbol
WORDMARK = build_logo.wordmark_paths()[0]
LOWERCASE_N = WORDMARK[: WORDMARK.index(" M41.0 ")]  # the wordmark's first letter; "u" starts at x = 41


class ProposalsTest(unittest.TestCase):
    def test_proposals_are_generated_and_committed(self):
        committed = sorted(p.name for p in (build_review.OUT / "proposals").glob("*.svg"))
        generated = build_review.proposal_svgs()
        self.assertEqual(committed, sorted(generated), "run scripts/brand/build_review.py")
        for name, text in generated.items():
            with self.subTest(svg=name):
                self.assertEqual((build_review.OUT / "proposals" / name).read_text(), text, "run scripts/brand/build_review.py")
                self.assertIn("a proposal, not an approved asset", text)

    def test_writing_the_proposals_touches_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_review, "OUT", Path(tmp) / "review"):
            written = build_review.write_proposals()
            self.assertEqual({p.parent for p in written}, {Path(tmp) / "review" / "proposals"})
            self.assertEqual(sorted(p.name for p in Path(tmp).rglob("*") if p.is_file()), sorted(p.name for p in written))

    def test_no_proposed_lockup_shows_the_initial_twice(self):
        svgs = build_review.proposal_svgs()
        for name in ("a-lockup-initial.svg", "a-lockup-initial-on-dark.svg"):
            with self.subTest(svg=name):  # A: the route is the only N, and "ulavio" follows it
                self.assertNotIn(LOWERCASE_N, svgs[name])
                self.assertEqual(svgs[name].count(f"L{build_review.n(build_review.A_WIDTH)} "), 1)
                self.assertIn(WORDMARK[len(LOWERCASE_N) + 1 :], svgs[name])
        for name in ("c-lockup.svg", "c-lockup-on-dark.svg"):
            with self.subTest(svg=name):  # C: the whole wordmark beside a symbol that is not the N
                self.assertIn(WORDMARK, svgs[name])
                self.assertNotIn(N_ROUTE, svgs[name])
                self.assertIn(f'd="{build_review.RUMO_ROUTE}"', svgs[name])
        # B draws nothing new: its name is the approved wordmark, which has no symbol beside it.
        self.assertNotIn(N_ROUTE, (build_logo.ASSETS / "logo" / "nulavio-wordmark.svg").read_text())

    def test_the_initial_keeps_the_symbols_trail(self):
        dots = build_review.initial_dots()
        self.assertEqual(len(dots), len(build_logo.DOTS))
        radii = [r for _cx, _cy, r in dots]
        self.assertEqual(radii, sorted(radii, reverse=True), "the points shrink away from the stem")
        self.assertEqual(radii[0], build_logo.W_STROKE / 2, "the first point is as wide as the wordmark's stroke")
        self.assertGreater(dots[0][1] - radii[0], build_review.A_STEM_END + build_logo.W_STROKE / 2, "clear of the stem's cap")

    def test_small_masters_of_the_new_symbol_keep_a_single_point(self):
        svgs = build_review.proposal_svgs()
        for name in ("c-icon-16.svg", "c-icon-24.svg"):
            with self.subTest(svg=name):
                self.assertEqual(svgs[name].count("<circle"), 1)  # guidelines: below 24 px, one point
        self.assertEqual(svgs["c-icon.svg"].count("<circle"), 3)


class ColourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(contrast.TOKENS.read_text(encoding="utf-8"))
        cls.candidates = {row["name"]: row for row in build_review.accent_candidates(cls.data)}

    def test_every_mark_pair_meets_its_minimum(self):
        for what, fg, bg, minimum in build_review.MARK_PAIRS:
            with self.subTest(pair=what):
                self.assertGreaterEqual(contrast.ratio(fg, bg), minimum)

    def test_oklch_round_trip(self):
        for colour in (build_review.MINT, build_review.MINT_DARK, build_review.NAVY, "#E7AE61"):
            with self.subTest(colour=colour):
                self.assertEqual(build_review.from_oklch(*build_review.oklch(colour)), colour)

    def test_todays_accent_is_measured_as_it_is(self):
        today = self.candidates["Mint, as today"]
        self.assertEqual((today["scale"]["400"], today["scale"]["700"]), (build_review.MINT, build_review.MINT_DARK))
        self.assertEqual((today["failed"], today["variant_failed"]), (0, 0))
        self.assertGreaterEqual(today["separation"], build_tokens.SEPARATION_MIN)

    def test_the_other_hues_pass_contrast_and_break_the_separation_rule(self):
        # The review's reason to keep the palette: a turned accent is not ruled out by contrast,
        # it is ruled out by the distance the tokens keep between the accent and what it must not mean.
        stale = "the review's palette conclusion no longer holds on these tokens: run build_review.py --report and refresh it"
        others = [row for name, row in self.candidates.items() if name != "Mint, as today"]
        self.assertEqual(len(others), 3)
        for row in others:
            with self.subTest(accent=row["name"]):
                self.assertEqual((row["failed"], row["variant_failed"]), (0, 0), stale)
                self.assertLess(row["separation"], build_tokens.SEPARATION_MIN, stale)
                self.assertAlmostEqual(build_review.oklch(row["scale"]["400"])[2], row["hue"], places=6)
                self.assertGreater(abs(row["hue"] - build_review.oklch(build_review.MINT)[2]), 10)

    def test_the_review_quotes_the_marks_measured_pairs(self):
        # Only the marks' own pairs, which depend on the brand's colours alone. The accent table is
        # dated in the document: it moves with every token the accent is kept apart from.
        text = REVIEW.read_text(encoding="utf-8")
        for line in build_review.mark_report():
            with self.subTest(line=line):
                self.assertIn(line + "\n", text, "run scripts/brand/build_review.py --report")


class DocumentTest(unittest.TestCase):
    def test_the_review_shows_every_sheet_and_says_nothing_is_chosen(self):
        text = REVIEW.read_text(encoding="utf-8")
        for sheet in (
            "overview",
            "capture-crops",
            "status-shields",
            "palette",
            "contexts-today",
            "contexts-a",
            "contexts-b",
            "contexts-c",
        ):
            with self.subTest(sheet=sheet):
                self.assertTrue((build_review.OUT / f"{sheet}.webp").is_file())
                self.assertIn(f"assets/review/2026-11/{sheet}.webp", text)
        self.assertIn("Nothing has been chosen", text)

    def test_the_guidelines_still_describe_the_approved_brand(self):
        guidelines = (ROOT / "docs" / "brand" / "guidelines.md").read_text(encoding="utf-8")
        self.assertIn("Vanishing Route", guidelines)
        self.assertIn("review-2026-11.md", guidelines)
        self.assertNotIn("Rumo", guidelines)


if __name__ == "__main__":
    unittest.main()
