"""scripts/perf/gate.py: perf.yml fails a run only past a measure's threshold and outside its interval (#367)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "perf"))

import gate  # noqa: E402

RUN_SPEC = importlib.util.spec_from_file_location("perf_run_for_gate", ROOT / "scripts" / "perf" / "run.py")
perf_run = importlib.util.module_from_spec(RUN_SPEC)
RUN_SPEC.loader.exec_module(perf_run)

EVIDENCE = ROOT / "docs" / "research" / "evidence" / "perf-runner-noise-2026-11-18"


def results(**changes: tuple[float, tuple[float, float]]) -> dict:
    """A perf.json where each named measure moved by `change` (a fraction) with the given interval; the others did not."""
    metrics, intervals = {}, {}
    for name in gate.THRESHOLDS:
        change, bounds = changes.get(name, (0.0, (-0.05, 0.05)))
        metrics[name] = {"build": [100 * (1 + change)] * 5, "baseline": [100.0] * 5}
        intervals[name] = list(bounds)
        if name.startswith("pss_mib_"):
            metrics[name.replace("pss_mib_", "unreadable_", 1)] = {"build": [0] * 5, "baseline": [0] * 5}
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

    def test_exactly_at_the_threshold_passes_and_just_above_fails(self):
        # 550 against 500 is exactly +10 %; in floats 550 / 500 - 1 is 0.10000000000000009, past 0.10.
        def pss(build: float):
            data = results(pss_mib_1_tabs=(0.0, (0.05, 0.2)))
            data["metrics"]["pss_mib_1_tabs"] = {"build": [build] * 5, "baseline": [500.0] * 5}
            return {n: (v, w) for n, v, w in gate.verdicts(data)}["pss_mib_1_tabs"]

        self.assertEqual(pss(550.0)[0], "pass")
        verdict, words = pss(550.01)
        self.assertEqual(verdict, "fail")
        # +10.002 %: the line is not "+10.0 % ... fails past +10 %"
        self.assertIn("+10.002%", words)
        self.assertEqual(pss(550.0 * (1 + 1e-12))[0], "fail")
        self.assertEqual(self.verdict(results(speedometer3_score=(-0.1, (-0.2, -0.05))))["speedometer3_score"], "pass")

    def test_memory_with_unreadable_processes_is_not_judged_whatever_it_reads(self):
        for side in ("build", "baseline"):
            for change in (-0.3, 0.3):  # a reading too low looks like an improvement on the release, a regression on the baseline
                with self.subTest(side=side, change=change):
                    data = results(pss_mib_10_tabs=(change, (-0.4, -0.2) if change < 0 else (0.2, 0.4)))
                    data["metrics"]["unreadable_10_tabs"][side] = [0, 0, 2, 0, 0]
                    found = self.verdict(data)
                    self.assertEqual(found["pss_mib_10_tabs"], "missing")
                    self.assertEqual(found["pss_mib_1_tabs"], "pass")
                    self.assertEqual(self.gate(data, "--strict").returncode, 1)
        data = results()
        del data["metrics"]["unreadable_1_tabs"]  # no count: the reading cannot be trusted either
        self.assertEqual(self.verdict(data)["pss_mib_1_tabs"], "missing")

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
        """A name changed in run.py would leave the gate with nothing to judge (--strict then fails every run). One run
        of one_run with `--tabs 1 10`, the engine and the readings faked, names every PSS measure and its unreadable
        count."""
        fake = mock.MagicMock()
        fake.wait_until.side_effect = lambda check, _seconds: check()
        session = mock.MagicMock()
        session.process.pid = 1
        session.start.return_value = session.restart.return_value = opened = mock.MagicMock()
        added = []
        opened.chrome.side_effect = lambda script, args=None: (
            added.append(args) if script == perf_run.ADD_TAB else [len(added) + 1] * 2 if script == perf_run.SHOWN else None
        )
        fake.GeckoProfileSession.return_value = session
        server = mock.MagicMock()
        server.url.side_effect = lambda path: f"http://x{path}"
        with (
            mock.patch.dict(sys.modules, {"harness": fake}),
            mock.patch.dict(perf_run.os.environ, {}),
            mock.patch.object(perf_run, "startup_ms", return_value=1.0),
            mock.patch.object(perf_run, "instance_pids", return_value=[1]),
            mock.patch.object(perf_run, "pss_kib", return_value=(512 * 1024, 0)),
            mock.patch.object(perf_run, "sandbox", return_value="on"),
            mock.patch.object(perf_run.time, "sleep"),
        ):
            out = perf_run.one_run("engine", [1, 10], server, (("speedometer3_score", lambda m: 12.0),))
        for name in gate.THRESHOLDS:
            with self.subTest(name=name):
                self.assertIn(name, out)
        self.assertEqual((out["unreadable_1_tabs"], out["unreadable_10_tabs"]), (0, 0))

    def test_the_command_exits_1_on_a_failure_and_names_it(self):
        done = self.gate(results(pss_mib_1_tabs=(0.15, (0.11, 0.2))))
        self.assertEqual(done.returncode, 1)
        self.assertIn("- **worse**: pss_mib_1_tabs: +15.0%", done.stdout)

    def test_the_four_runs_the_thresholds_come_from_pass(self):
        runs = sorted(EVIDENCE.glob("*.json"))
        self.assertEqual(len(runs), 4)
        for run in runs:
            with self.subTest(run=run.name):
                self.assertEqual({v for _n, v, _w in gate.verdicts(json.loads(run.read_text()))}, {"pass"})

    def test_perf_yml_runs_the_gate_after_measuring_and_still_keeps_the_json(self):
        workflow = (ROOT / ".github" / "workflows" / "perf.yml").read_text(encoding="utf-8")
        measure = workflow.index("id: measure")
        gate_step = workflow.index("- name: The gate (#367)")
        upload_at = workflow.index("actions/upload-artifact")
        self.assertLess(measure, gate_step)
        self.assertLess(gate_step, upload_at)
        step = workflow[gate_step:upload_at]
        self.assertIn("python3 -I scripts/perf/gate.py --strict perf/perf.json", step)
        self.assertIn("steps.measure.outcome == 'success'", step)
        # GitHub's default shell has no pipefail: the pipe into tee would end with tee's status and pass.
        self.assertRegex(step, r"(?m)^\s+shell: bash\b")
        upload = workflow[workflow.index("actions/upload-artifact") :]
        self.assertIn("if: always()", upload.split("with:")[0])


if __name__ == "__main__":
    unittest.main()
