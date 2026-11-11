"""Resource policy regressions; real cgroup checks are a separate controlled probe."""

from __future__ import annotations

import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "build"))
import build_guard

GIB = 1024**3


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
        rejected = ({"MOZ_PARALLEL_BUILD": "16"}, {"CARGO_BUILD_JOBS": "2"}, {"NULAVIO_BUILD_MEMORY_GIB": "21"})
        for env in (*rejected, {"NULAVIO_BUILD_MEMORY_GIB": "32"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                build_guard.Config.from_env(env)
        self.assertEqual(build_guard.Config.from_env({"NULAVIO_BUILD_MEMORY_GIB": "20"}).memory_gib, 20)

    def test_runner_budget_is_explicit_and_bounded(self):
        config = build_guard.Config.from_env({"NULAVIO_BUILD_PROFILE": "runner"})
        self.assertEqual((config.memory_gib, config.jobs, config.cargo_jobs, config.cpus), (48, 16, 16, 16))
        self.assertEqual((config.pids, config.max_rustc), (8192, 16))
        small = build_guard.Config.from_env({"NULAVIO_BUILD_PROFILE": "runner", "MOZ_PARALLEL_BUILD": "8"})
        self.assertEqual((small.cpus, small.max_rustc), (8, 8))
        for env in ({"NULAVIO_BUILD_MEMORY_GIB": "57"}, {"MOZ_PARALLEL_BUILD": "17"}, {"MOZ_PARALLEL_BUILD": "0"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                build_guard.Config.from_env({"NULAVIO_BUILD_PROFILE": "runner", **env})
        with self.assertRaisesRegex(ValueError, "unknown"):
            build_guard.Config.from_env({"NULAVIO_BUILD_PROFILE": "server"})

    def test_runner_budget_refuses_a_host_too_small_for_it(self):
        config = build_guard.Config.from_env({"NULAVIO_BUILD_PROFILE": "runner"})
        laptop = {"total": 30 * GIB, "available": 20 * GIB, "swap_used": 0, "psi_full_avg10": 0.0, "cpu": []}
        with (
            mock.patch.object(build_guard, "host_sample", return_value=laptop),
            self.assertRaisesRegex(ValueError, "laptop budget"),
        ):
            build_guard.preflight(config)

    def test_missing_psi_is_refused_on_the_laptop_and_ignored_on_a_runner(self):
        runner = {"total": 62 * GIB, "available": 60 * GIB, "swap_used": 0, "psi_full_avg10": None, "cpu": []}
        with mock.patch.object(build_guard, "host_sample", return_value=runner), self.assertRaisesRegex(ValueError, "PSI"):
            build_guard.preflight(build_guard.Config.from_env({}))
        with (
            mock.patch.object(build_guard, "host_sample", return_value=runner),
            mock.patch.object(build_guard, "call", return_value=mock.Mock(stdout="")),
        ):
            build_guard.preflight(build_guard.Config.from_env({"NULAVIO_BUILD_PROFILE": "runner"}))
        guard = build_guard.PressurePolicy(min_available=4 * GIB, psi_limit=10, psi_seconds=30)
        self.assertIsNone(guard.reason(100, 8 * GIB, None))
        self.assertIn("available", guard.reason(100, 3 * GIB, None))

    def test_oom_retry_halves_runner_jobs(self):
        config = build_guard.Config.from_env({"NULAVIO_BUILD_PROFILE": "runner"})
        self.assertEqual(build_guard.retry_jobs(config, {"oom": True, "jobs": 16}), 8)
        self.assertEqual(build_guard.retry_jobs(config, {"memory_failure": True, "jobs": 2}), 1)

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
