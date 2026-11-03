"""Opt-in real cgroup/cleanup probes, without a full Firefox build or host pressure."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts/build/build_guard.py"


@unittest.skipUnless(os.environ.get("NULAVIO_BUILD_RESOURCE_TESTS") == "1", "opt-in bounded Podman resource probes")
class BuildResourcesTest(unittest.TestCase):
    def setUp(self):
        if not shutil.which("podman"):
            self.skipTest("podman required")
        self.base = Path(tempfile.mkdtemp(prefix="nulavio-resource-probe-"))
        self.addCleanup(shutil.rmtree, self.base)
        self.env = dict(os.environ, NULAVIO_BUILD_MEMORY_GIB="1")

    def launch(self, name, program):
        control = self.base / name
        log = (self.base / f"{name}.log").open("w")
        self.addCleanup(log.close)
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-I",
                str(GUARD),
                "--control",
                str(control),
                "--",
                "localhost/nulavio-build:f44",
                "--",
                "python3",
                "-c",
                program,
            ],
            env=self.env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        self.addCleanup(self.stop, process, control)
        return process, control

    def stop(self, process, control):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
        cid = control / "container-id"
        if cid.exists():
            subprocess.run(["podman", "rm", "--force", cid.read_text().strip()], check=False, capture_output=True, timeout=20)

    def wait_file(self, process, file, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and process.poll() is None:
            if file.exists():
                return
            time.sleep(0.1)
        self.fail(f"probe failed to reach {file}; logs in {self.base}")

    def test_children_receive_enforced_limits(self):
        process, control = self.launch("limits", "import time; a=bytearray(64*1024**2); time.sleep(7)")
        self.assertEqual(process.wait(timeout=25), 0)
        limits = json.loads((control / "limits.json").read_text())
        self.assertEqual(limits["memory.max"], 1024**3)
        self.assertEqual(limits["memory.swap.max"], 0)
        self.assertEqual(limits["cpu.max"], [200000, 100000])
        self.assertEqual(limits["pids.max"], 512)
        self.assertFalse(json.loads((control / "result.json").read_text())["oom"])

    def test_cgroup_oom_reduces_next_attempt(self):
        process, control = self.launch("oom", "a=bytearray(1536*1024**2)")
        self.assertNotEqual(process.wait(timeout=25), 0)
        self.assertTrue(json.loads((control / "result.json").read_text())["oom"])
        process, control = self.launch("retry", 'import os; assert os.environ["MOZ_PARALLEL_BUILD"]=="1"')
        self.assertEqual(process.wait(timeout=25), 0)
        self.assertEqual(json.loads((control / "config.json").read_text())["jobs"], 1)

    def test_signal_stops_even_a_child_that_ignores_term(self):
        program = 'import subprocess,time; subprocess.Popen(["bash","-c","trap \'\' TERM; sleep 600"]); time.sleep(600)'
        process, control = self.launch("signal", program)
        self.wait_file(process, control / "inside.json")
        process.send_signal(signal.SIGTERM)
        self.assertNotEqual(process.wait(timeout=35), 0)
        cid = (control / "container-id").read_text().strip()
        inspected = subprocess.run(["podman", "container", "exists", cid], capture_output=True, timeout=10)
        self.assertNotEqual(inspected.returncode, 0, "container and all namespace children must be gone")

    def test_lost_supervisor_expires_lease_and_stops_tree(self):
        process, control = self.launch("lease", 'import subprocess,time; subprocess.Popen(["sleep","600"]); time.sleep(600)')
        self.wait_file(process, control / "inside.json")
        process.kill()
        process.wait(timeout=5)
        cid = (control / "container-id").read_text().strip()
        # No host pressure is generated: only wait for the inner 30-second lease.
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = json.loads(subprocess.check_output(["podman", "inspect", cid], text=True, timeout=10))[0]["State"]
            if not state["Running"]:
                break
            time.sleep(1)
        self.assertFalse(state["Running"], "supervisor death must not leave a live workload")
        self.assertEqual(json.loads((control / "inside-stop.json").read_text())["reason"], "supervisor heartbeat expired")


if __name__ == "__main__":
    unittest.main()
