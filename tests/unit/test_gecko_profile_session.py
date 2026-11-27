"""`GeckoProfileSession.start()` keeps working for the subclasses that override `enable_marionette` (#875).

The site tools (`scripts/site/capture_site.py`, `scripts/site/record_site.py`) override `enable_marionette(profile_dir)`
with one argument and call the inherited `start()` with none. Since #884 `start()` can also leave the first-run sequence
on; its default path must still make the one-argument call. No engine is started: the launch steps are replaced.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import harness  # noqa: E402


class OneArgument(harness.GeckoProfileSession):
    """As the site tools override it."""

    def enable_marionette(self, profile_dir: Path) -> None:
        self.calls.append(("one", Path(profile_dir)))


class Both(harness.GeckoProfileSession):
    def enable_marionette(self, profile_dir: Path, first_run: bool = False) -> None:
        self.calls.append(("both", Path(profile_dir), first_run))


class StartTest(unittest.TestCase):
    def session(self, cls):
        tmp = tempfile.TemporaryDirectory(prefix="nulavio-gps-unit-")
        self.addCleanup(tmp.cleanup)
        s = object.__new__(cls)  # no engine: __init__ needs the Nulavio build
        s.tmp = Path(tmp.name)
        s.name = "Pessoal"
        s.profile_dir = s.tmp / "profiles" / "first"
        s.env = {}
        s.engine = mock.Mock(path=Path("/nonexistent/nulavio"))
        s.calls = []
        s._start_private_bus = lambda: None
        s._run = lambda *args: s.profile_dir.mkdir() or mock.Mock(stderr="")
        s.connect = lambda profile_dir, process: "client"
        return s

    def start(self, s, *urls, **kwargs):
        with mock.patch.object(harness.subprocess, "Popen") as popen:
            self.assertEqual(s.start(*urls, **kwargs), "client")
        return popen.call_args.args[0]

    def test_the_default_start_makes_the_one_argument_call_a_site_tool_overrides(self):
        s = self.session(OneArgument)
        command = self.start(s)
        self.assertEqual(s.calls, [("one", s.profile_dir)])
        self.assertEqual(command, ["/nonexistent/nulavio", "-P", "Pessoal"])

    def test_first_run_and_the_urls_reach_the_profile_and_the_command_line(self):
        s = self.session(Both)
        command = self.start(s, "http://127.0.0.1:1/a", first_run=True)
        self.assertEqual(s.calls, [("both", s.profile_dir, True)])
        self.assertEqual(command, ["/nonexistent/nulavio", "-P", "Pessoal", "http://127.0.0.1:1/a"])


if __name__ == "__main__":
    unittest.main()
