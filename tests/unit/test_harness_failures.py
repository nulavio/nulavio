"""A failing `nulavio` call in the integration harness says why (#257).

On 2026-11-14 an engine integration job failed once on `nulavio setup` with only a
CalledProcessError: the harness captured the command's stderr and the error does not
show it, so the cause could not be read. These run the real launcher, with an argument
it refuses, in a throwaway home.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import harness  # noqa: E402


class HarnessFailureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nulavio-harness-failure-")
        home = Path(self.tmp.name)
        self.session = object.__new__(harness.Session)  # only nulavio() is used: no engine is started
        self.session.env = {"PATH": os.environ["PATH"], "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                            "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache")}  # fmt: skip

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_failed_call_names_its_status_and_what_it_wrote_on_stderr(self):
        with self.assertRaises(harness.NulavioCallFailed) as caught:
            self.session.nulavio("no-such-command")
        message = str(caught.exception)
        self.assertIsInstance(caught.exception, AssertionError)  # a test failure, as before, not an error
        self.assertIn("nulavio no-such-command exited with status 2", message)
        self.assertIn("  | ", message)
        self.assertIn("no-such-command", message.split("stderr", 1)[1])  # argparse's own words, quoted

    def test_check_false_still_returns_the_result(self):
        done = self.session.nulavio("no-such-command", check=False)
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stderr)

    def test_a_long_stderr_keeps_its_end(self):
        lines = "\n".join(f"line {i}" for i in range(100))
        failed = subprocess.CompletedProcess(["nulavio"], 1, stdout="", stderr=lines + "\n")
        with (
            mock.patch.object(harness.subprocess, "run", return_value=failed),
            self.assertRaises(harness.NulavioCallFailed) as caught,
        ):
            self.session.nulavio("setup", "--yes", "--profile", "contrast")
        message = str(caught.exception)
        self.assertIn("nulavio setup --yes --profile contrast exited with status 1", message)
        self.assertIn("(last 40 of 100 lines)", message)
        self.assertIn("  | line 99", message)
        self.assertIn("  | line 60", message)
        self.assertNotIn("line 59\n", message)
        empty = subprocess.CompletedProcess(["nulavio"], 3, stdout="", stderr="")
        with (
            mock.patch.object(harness.subprocess, "run", return_value=empty),
            self.assertRaises(harness.NulavioCallFailed) as caught,
        ):
            self.session.nulavio("setup")
        self.assertIn("(nothing on stderr)", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
