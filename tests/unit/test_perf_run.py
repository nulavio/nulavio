"""scripts/perf/run.py: the medians and the change it reports (#80)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "perf"))
import run  # noqa: E402


class PerfRunTest(unittest.TestCase):
    def test_change_is_the_builds_median_against_the_baselines(self):
        self.assertAlmostEqual(run.change([110, 100, 120], [100, 90, 110]), 0.10)
        self.assertIsNone(run.change([], [1]))
        self.assertIsNone(run.change([1], [0]))

    def test_the_table_names_each_measure_with_both_medians_and_the_change(self):
        results = {"metrics": {"startup_first_ms": {"build": [110.0, 100.0, 120.0], "baseline": [100.0, 90.0, 110.0]}}}
        text = run.table(results)
        self.assertIn("startup_first_ms", text)
        self.assertIn("110.0", text)
        self.assertIn("+10.0 %", text)


if __name__ == "__main__":
    unittest.main()
