#!/usr/bin/env python3
"""Test entry point (stdlib unittest; no third-party packages needed).

    python3 -I tests/run.py unit          # fast, no engine, no network
    python3 -I tests/run.py integration   # needs the Gecko engine (headless)
    python3 -I tests/run.py all
    python3 -I tests/run.py integration 'test_assistant*.py'   # only matching modules
    python3 -I tests/run.py fuzz          # property-based fuzzing; needs requirements/fuzz.txt (#149)

Integration knobs: NULAVIO_NETWORK_TESTS=1, NULAVIO_REQUIRE_NETWORK=1, NULAVIO_TEST_XPI_CACHE=<dir>,
NULAVIO_TEST_HEADFUL=1, NULAVIO_TEST_ARTIFACTS=<dir>.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "launcher", ROOT / "tests" / "lib", ROOT / "scripts" / "brand"):
    sys.path.insert(0, str(extra))


def main(argv: list[str]) -> int:
    which = argv[1] if len(argv) > 1 else "unit"
    pattern = argv[2] if len(argv) > 2 else "test*.py"
    suites = {"unit": ["unit"], "integration": ["integration"], "all": ["unit", "integration"], "fuzz": ["fuzz"]}[which]
    loader = unittest.TestLoader()
    combined = unittest.TestSuite()
    for name in suites:
        combined.addTests(loader.discover(str(ROOT / "tests" / name), pattern=pattern, top_level_dir=str(ROOT / "tests" / name)))
    if "integration" not in suites:
        # tests/lib/harness.py sets this for the engines and tools it starts (#464); a unit module that imports it
        # must not leave the launcher's refusal of the distribution's Firefox off for the whole unit run.
        os.environ.pop("NULAVIO_TEST_DISTRIBUTION_FIREFOX", None)
    result = unittest.TextTestRunner(verbosity=2).run(combined)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
