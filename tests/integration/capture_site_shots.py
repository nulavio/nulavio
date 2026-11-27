"""Capture step of the site's figures (#173): not a test of the suite.

Its name does not match ``test*.py``, so the integration suite, CI and the release never run it. It is run
by name, where the integration tests run (the release test container, whose fonts are fixed and where the
site's recordings are made, with FUSE for the protected profile); ``<install-dir>`` is the directory that
holds the ``nulavio`` executable:

    NULAVIO_INTEGRATION_IMAGE=fedora-release-itest NULAVIO_TEST_ARTIFACTS=<dir> \\
        scripts/release/run_integration.sh <install-dir> capture_site_shots.py

The screenshots and ``captures.json`` go to ``<dir>/site-shots/``; on the host,
``python3 -I scripts/site/capture_site.py compose <dir>/site-shots`` cuts and encodes them into the tree.
A figure that cannot reach the state it shows fails this case and is left out, never staged.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests" / "lib"), str(ROOT / "scripts" / "site")]

import capture_site  # noqa: E402
import harness  # noqa: E402


class CaptureSiteShots(unittest.TestCase):
    def test_capture(self):
        if Path("/run/.containerenv").exists() and not os.environ.get("NULAVIO_TEST_ARTIFACTS"):
            # In the container, the default folder is in the copy of the checkout the runner deletes with it.
            self.fail("set NULAVIO_TEST_ARTIFACTS: the screenshots must outlive the container for compose to read them")
        raw = harness.artifacts_dir() / capture_site.RAW
        self.assertEqual(capture_site.capture(raw, ["pt-BR", "en-US"], {"window", "bands", "guard"}), 0)
        self.assertTrue((raw / "captures.json").is_file())


if __name__ == "__main__":
    unittest.main()
