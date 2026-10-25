#!/usr/bin/env python3
"""Test entry point (stdlib unittest; no third-party packages needed).

    python3 -I tests/run.py unit          # fast, no engine, no network
    python3 -I tests/run.py integration   # needs the Gecko engine (headless)
    python3 -I tests/run.py all

Integration knobs: NULAVIO_NETWORK_TESTS=1, NULAVIO_TEST_XPI_CACHE=<dir>,
NULAVIO_TEST_HEADFUL=1, NULAVIO_TEST_ARTIFACTS=<dir>.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "launcher", ROOT / "tests" / "lib", ROOT / "scripts" / "brand"):
    sys.path.insert(0, str(extra))


def main(argv: list[str]) -> int:
    which = argv[1] if len(argv) > 1 else "unit"
    suites = {"unit": ["unit"], "integration": ["integration"], "all": ["unit", "integration"]}[which]
    loader = unittest.TestLoader()
    combined = unittest.TestSuite()
    for name in suites:
        combined.addTests(loader.discover(str(ROOT / "tests" / name), top_level_dir=str(ROOT / "tests" / name)))
    result = unittest.TextTestRunner(verbosity=2).run(combined)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
