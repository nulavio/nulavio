"""The UX7 frame-time scene's statistics and budget (scripts/research/frame_scene.py), on fixed numbers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "research"))

import frame_scene


class FrameSceneTest(unittest.TestCase):
    def test_stats_drop_the_first_interval_and_use_nearest_rank(self):
        self.assertEqual(frame_scene.intervals_after_first([90, 16, 17, 16]), [16.0, 17.0, 16.0])
        values = [float(v) for v in range(1, 21)]  # 1..20
        self.assertEqual(frame_scene.nearest_rank(values, 95), 19.0)
        self.assertEqual(frame_scene.nearest_rank(values, 50), 10.0)
        self.assertEqual(frame_scene.nearest_rank([7.0], 95), 7.0)
        self.assertIsNone(frame_scene.nearest_rank([], 95))
        self.assertEqual(frame_scene.summary([16.0, 17.0, 33.0]), {"n": 3, "p50": 17.0, "p95": 33.0, "max": 33.0})

    def test_budget_flags_only_non_overlapping_regressions(self):
        self.assertFalse(frame_scene.regression([17.0, 18.0, 30.0], [16.0, 17.0, 18.0]))  # overlapping ranges
        self.assertTrue(frame_scene.regression([20.0, 21.0, 22.0], [16.0, 16.5, 17.0]))  # >10 % and apart
        self.assertFalse(frame_scene.regression([17.4, 17.5, 17.6], [16.5, 16.6, 16.7]))  # apart but within 10 %
        self.assertFalse(frame_scene.regression([], [16.0]))
        # Review: more than 10 % worse, but the ranges overlap: not flagged (the clause the name promises).
        self.assertFalse(frame_scene.regression([16.0, 22.0, 23.0], [16.0, 17.0, 18.0]))

    def test_verdict_reads_each_budget_line(self):
        scenes = {
            "sidebar_collapse": {"n": 30, "p50": 16.6, "p95": 18.0, "max": 40.0},
            "tab_switch": {"n": 30, "p50": 16.6, "p95": 25.0, "max": 40.0},
            "new_tab": {"n": 10, "p50": 80.0, "p95": 120.0, "max": 130.0},
            "idle": {"reflows": 0, "framesConstructed": 2},
        }
        self.assertEqual(
            frame_scene.verdict(scenes),
            {
                "sidebar_collapse": True,
                "sidebar_expand": False,  # no samples: the scene did not run, which is not a pass
                "tab_switch": False,
                "dialog_open": False,
                "new_tab": True,
                "idle": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
