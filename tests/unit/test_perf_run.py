"""scripts/perf/run.py: the medians and the change it reports, and how it reads a process tree's memory (#80)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("perf_run", ROOT / "scripts" / "perf" / "run.py")
perf_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(perf_run)


class PerfStatisticsTest(unittest.TestCase):
    def test_change_is_the_builds_median_against_the_baselines(self):
        self.assertAlmostEqual(perf_run.change([110, 100, 120], [100, 90, 110]), 0.10)
        self.assertIsNone(perf_run.change([], [1]))
        self.assertIsNone(perf_run.change([1], [0]))

    def test_the_table_names_each_measure_with_both_medians_and_the_change(self):
        results = {"metrics": {"startup_first_ms": {"build": [110.0, 100.0, 120.0], "baseline": [100.0, 90.0, 110.0]}}}
        text = perf_run.table(results)
        self.assertIn("startup_first_ms", text)
        self.assertIn("110.0", text)
        self.assertIn("+10.0 %", text)


class PinnedBenchmarkTest(unittest.TestCase):
    def test_an_archive_that_is_not_the_pinned_one_is_refused_and_removed(self):
        import tempfile

        cache = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, cache)
        pin = perf_run.PINNED["speedometer"]
        archive = cache / f"speedometer-{pin['commit']}.tar.gz"
        archive.write_bytes(b"not the archive")  # as a download that was replaced or cut
        with self.assertRaises(perf_run.MeasureError):
            perf_run.pinned("speedometer", cache)
        self.assertFalse(archive.exists())
        self.assertFalse((cache / f"speedometer-{pin['commit']}").exists())

    def test_the_pin_is_a_commit_of_the_release_branch_with_its_digest(self):
        pin = perf_run.PINNED["speedometer"]
        self.assertRegex(pin["commit"], r"^[0-9a-f]{40}$")
        self.assertIn(pin["commit"], pin["url"])
        self.assertTrue(pin["url"].startswith("https://"))
        self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")


@unittest.skipUnless(Path("/proc/self/smaps_rollup").exists(), "needs Linux /proc")
class PerfProcessTreeTest(unittest.TestCase):
    def test_the_tree_holds_children_and_grandchildren_and_their_memory_is_read(self):
        # A child that starts a grandchild, as the engine starts its fork server and the fork server its pages.
        child = subprocess.Popen(["sh", "-c", "sleep 30 & wait"], start_new_session=True)
        self.addCleanup(child.wait)
        self.addCleanup(os.killpg, child.pid, 9)  # the child and its grandchild, one group
        pids = []
        for _ in range(100):
            pids = perf_run.instance_pids(child.pid)
            if len(pids) >= 2:
                break
            subprocess.run(["sleep", "0.05"], check=True)
        self.assertIn(child.pid, pids)
        self.assertGreaterEqual(len(pids), 2, pids)
        self.assertNotIn(os.getpid(), pids)
        total, unreadable = perf_run.pss_kib(pids)
        self.assertGreater(total, 0)
        self.assertEqual(unreadable, 0)

    def test_a_process_that_ended_is_neither_memory_nor_unreadable(self):
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.assertEqual(perf_run.pss_kib([gone.pid]), (0, 0))


if __name__ == "__main__":
    unittest.main()
