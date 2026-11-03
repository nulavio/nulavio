"""Resource policy regressions; real cgroup checks are a separate controlled probe."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "build"))
import build_guard


class PolicyTest(unittest.TestCase):
    def test_low_memory_blocks_new_work(self):
        guard = build_guard.PressurePolicy(min_available=4 * 1024**3, psi_limit=10, psi_seconds=30)
        self.assertIn("available", guard.reason(0, 3 * 1024**3, 0))

    def test_pressure_must_be_continuous_and_reset_on_recovery(self):
        guard = build_guard.PressurePolicy(min_available=4 * 1024**3, psi_limit=10, psi_seconds=30)
        for now in (0, 10, 29):
            self.assertIsNone(guard.reason(now, 8 * 1024**3, 11))
        self.assertIsNone(guard.reason(30, 8 * 1024**3, 9))
        self.assertIsNone(guard.reason(40, 8 * 1024**3, 11))
        self.assertIsNone(guard.reason(69, 8 * 1024**3, 11))
        self.assertIn("pressure", guard.reason(70, 8 * 1024**3, 11))

    def test_emergency_does_not_wait_for_pressure_duration(self):
        guard = build_guard.PressurePolicy(min_available=4 * 1024**3, psi_limit=10, psi_seconds=30)
        self.assertIn("available", guard.reason(0, 512 * 1024**2, 0))

    def test_limit_configuration_never_infers_cpu_count(self):
        config = build_guard.Config.from_env({})
        self.assertEqual((config.memory_gib, config.jobs, config.cargo_jobs, config.cpus), (16, 2, 1, 2))
        for env in ({"MOZ_PARALLEL_BUILD": "16"}, {"CARGO_BUILD_JOBS": "2"}, {"NULAVIO_BUILD_MEMORY_GIB": "32"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                build_guard.Config.from_env(env)

    def test_oom_retry_reduces_jobs_once_and_preserves_refusal(self):
        config = build_guard.Config.from_env({})
        self.assertEqual(build_guard.retry_jobs(config, {"oom": True, "jobs": 2}), 1)
        with self.assertRaisesRegex(ValueError, "one job"):
            build_guard.retry_jobs(config, {"oom": True, "jobs": 1})

    def test_successful_recovery_does_not_automatically_raise_jobs(self):
        self.assertEqual(build_guard.retry_jobs(build_guard.Config.from_env({}), {"jobs": 1, "oom": False}), 1)

    def test_cpu_percent_uses_deltas_not_lifetime_totals(self):
        # user nice system idle iowait irq softirq steal
        self.assertEqual(build_guard.cpu_percent([100, 0, 100, 800, 0, 0, 0, 0], [110, 0, 120, 860, 10, 0, 0, 0]), (20, 10))


if __name__ == "__main__":
    unittest.main()
