"""scripts/perf/gate.py: perf.yml fails a run only past a measure's threshold and outside its interval (#367)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "perf"))

import gate  # noqa: E402

EVIDENCE = ROOT / "docs" / "research" / "evidence" / "perf-runner-noise-2026-11-18"


def results(**changes: tuple[float, tuple[float, float]]) -> dict:
    """A perf.json where each named measure moved by `change` (a fraction) with the given interval; the others did not."""
    metrics, intervals = {}, {}
    for name in gate.THRESHOLDS:
        change, bounds = changes.get(name, (0.0, (-0.05, 0.05)))
        metrics[name] = {"build": [100 * (1 + change)] * 5, "baseline": [100.0] * 5}
        intervals[name] = list(bounds)
    return {"metrics": metrics, "intervals": intervals}


class PerfGateTest(unittest.TestCase):
    def verdict(self, data: dict) -> dict:
        return {name: verdict for name, verdict, _words in gate.verdicts(data)}

    def test_worse_past_the_threshold_and_outside_the_interval_fails(self):
        found = self.verdict(results(startup_first_ms=(0.20, (0.12, 0.30)), speedometer3_score=(-0.12, (-0.2, -0.05))))
        self.assertEqual(found["startup_first_ms"], "fail")
        self.assertEqual(found["speedometer3_score"], "fail")
        self.assertEqual(found["pss_mib_1_tabs"], "pass")

    def test_noise_or_a_small_change_passes(self):
        # Past the threshold but the interval holds 0: noise. Outside the interval but under the threshold: the runner's
        # own drift (v160.0-0.4's first start, +2.3 % with an interval of +0.5 … +5.0 %).
        found = self.verdict(results(startup_first_ms=(0.20, (-0.05, 0.40)), startup_second_ms=(0.023, (0.005, 0.05))))
        self.assertEqual(set(found.values()), {"pass"})

    def test_a_better_measure_never_fails(self):
        found = self.verdict(results(pss_mib_10_tabs=(-0.30, (-0.4, -0.2)), speedometer3_score=(0.30, (0.2, 0.4))))
        self.assertEqual(set(found.values()), {"pass"})

    def test_a_measure_without_an_interval_is_said_and_not_judged(self):
        data = results()
        data["intervals"]["pss_mib_1_tabs"] = None
        del data["metrics"]["speedometer3_score"]
        found = self.verdict(data)
        self.assertEqual((found["pss_mib_1_tabs"], found["speedometer3_score"]), ("missing", "missing"))

    def test_at_the_threshold_it_passes_and_a_fall_whose_interval_holds_0_passes(self):
        found = self.verdict(results(startup_first_ms=(0.15, (0.1, 0.2)), speedometer3_score=(-0.2, (-0.3, 0.01))))
        self.assertEqual(set(found.values()), {"pass"})

    def gate(self, data: dict, *flags: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "perf.json"
            path.write_text(json.dumps(data))
            return subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "perf" / "gate.py"), *flags, str(path)],
                                  capture_output=True, text=True)  # fmt: skip

    def test_strict_fails_on_a_measure_not_measured(self):
        data = results()
        data["intervals"]["speedometer3_score"] = None
        self.assertEqual(self.gate(data).returncode, 0)
        done = self.gate(data, "--strict")
        self.assertEqual(done.returncode, 1)
        self.assertIn("- **not judged**: speedometer3_score", done.stdout)

    def test_the_measures_are_the_ones_run_py_writes(self):
        """A name changed in run.py would leave the gate with nothing to judge (--strict then fails every run)."""
        source = (ROOT / "scripts" / "perf" / "run.py").read_text(encoding="utf-8")
        for name in gate.THRESHOLDS:
            with self.subTest(name=name):
                written = f'"{name}"' in source or (name.startswith("pss_mib_") and 'f"pss_mib_{count}_tabs"' in source)
                self.assertTrue(written, name)

    def test_the_command_exits_1_on_a_failure_and_names_it(self):
        done = self.gate(results(pss_mib_1_tabs=(0.15, (0.11, 0.2))))
        self.assertEqual(done.returncode, 1)
        self.assertIn("- **worse**: pss_mib_1_tabs: +15.0%", done.stdout)

    def test_the_four_runs_the_thresholds_come_from_pass(self):
        runs = sorted(EVIDENCE.glob("*.json"))
        self.assertEqual(len(runs), 4)
        for run in runs:
            with self.subTest(run=run.name):
                self.assertNotIn("fail", {v for _n, v, _w in gate.verdicts(json.loads(run.read_text()))})

    def test_perf_yml_runs_the_gate_after_measuring_and_still_keeps_the_json(self):
        workflow = (ROOT / ".github" / "workflows" / "perf.yml").read_text(encoding="utf-8")
        step = workflow[workflow.index("- name: The gate (#367)") : workflow.index("actions/upload-artifact")]
        self.assertIn("python3 -I scripts/perf/gate.py --strict perf/perf.json", step)
        self.assertIn("steps.measure.outcome == 'success'", step)
        # GitHub's default shell has no pipefail: the pipe into tee would end with tee's status and pass.
        self.assertRegex(step, r"(?m)^\s+shell: bash\b")
        self.assertLess(workflow.index("scripts/perf/gate.py"), workflow.index("actions/upload-artifact"))
        upload = workflow[workflow.index("actions/upload-artifact") :]
        self.assertIn("if: always()", upload.split("with:")[0])


if __name__ == "__main__":
    unittest.main()
