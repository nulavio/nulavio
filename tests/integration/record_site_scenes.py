"""Capture step of the site's recordings (#173, #176): not a test of the suite.

Its name does not match ``test*.py``, so the integration suite, CI and the release never run it. It is run
by name, where the integration tests run (the release test container, with FUSE for the Vault scene);
``<install-dir>`` is the directory that holds the ``nulavio`` executable:

    NULAVIO_INTEGRATION_IMAGE=fedora-release-itest NULAVIO_TEST_ARTIFACTS=<dir> \\
        scripts/release/run_integration.sh <install-dir> record_site_scenes.py

Each scene and language is one case. Frames and a timeline go to ``<dir>/recordings/<scene>-<locale>/``;
``python3 -I scripts/site/record_site.py compose <dir>/recordings`` turns them into video on the host, and
needs every one of them. A scene that cannot reach the state it shows fails: it is never staged, and it
leaves no ``timeline.json``, which a scene gets only after it and its teardown passed. Every run empties
``<dir>/recordings/`` first, so compose never finds a timeline of an earlier run there.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests" / "lib"), str(ROOT / "scripts" / "site")]

import harness  # noqa: E402
import record_site  # noqa: E402


class RecordSiteScenes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenes = record_site.Scenes(harness, harness.artifacts_dir() / "recordings")

    def record(self, scene: str, locale: str) -> None:
        out = self.scenes.record(scene, locale)
        self.assertTrue((out / "timeline.json").is_file())


def _case(scene: str, locale: str):
    return lambda self: self.record(scene, locale)


for _scene in record_site.SCENES:
    for _locale in record_site.LOCALES:
        setattr(RecordSiteScenes, f"test_{_scene.replace('-', '_')}_{_locale.replace('-', '_')}", _case(_scene, _locale))


if __name__ == "__main__":
    unittest.main()
