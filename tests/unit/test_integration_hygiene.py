"""The integration tests remove what they put in /tmp.

Each engine session makes a temporary home there (about 180 MB once uBlock Origin and its lists are in it), and /tmp is
often a tmpfs: a module that only stops its session leaves the home behind at every run, the device fills, and other
modules then fail for no reason of their own."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSION = re.compile(r"harness\.(?:GeckoProfileSession|Session)\(")
CLEANUP = re.compile(r"\.cleanup\(\)|add(?:Class)?Cleanup\([^)]*\.cleanup\b")


class IntegrationHygieneTest(unittest.TestCase):
    def test_every_module_that_starts_a_session_cleans_one_up(self):
        modules = sorted((ROOT / "tests" / "integration").glob("test_*.py"))
        self.assertTrue(modules)
        leaving = []
        for module in modules:
            text = module.read_text(encoding="utf-8")
            if SESSION.search(text) and not CLEANUP.search(text):
                leaving.append(module.name)
        self.assertEqual(leaving, [], "these start an engine session and never call its cleanup()")


if __name__ == "__main__":
    unittest.main()
