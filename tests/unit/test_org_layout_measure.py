"""The script behind the repository layout evidence (ADR 0013) still describes this tree."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("org_layout_measure", ROOT / "scripts" / "research" / "org_layout_measure.py")
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)


class OrgLayoutMeasureTest(unittest.TestCase):
    def test_paths_are_counted_with_what_they_build_deploy_or_test(self):
        cases = {
            "site/index.html": "site",
            "scripts/site/build_site.py": "site",
            ".github/workflows/site.yml": "site",
            "tests/unit/test_site.py": "site",
            "android/app/build.gradle.kts": "android",
            "tests/unit/test_companion_build.py": "android",
            "scripts/release/publish_release.sh": "release",
            ".github/workflows/release.yml": "release",
            "tests/unit/test_release_manifest.py": "release",
            ".github/workflows/ci.yml": "process",
            "scripts/ci/post_ai_review.py": "process",
            "docs/process/issues.md": "process",
            "docs/design/screenshots/ux2/a.png": "design-media",
            "docs/adr/0001-engine-selection.md": "docs",
            "launcher/nulavio_launcher/cli.py": "launcher",
            "browser/shell/modules/NulavioSearch.sys.mjs": "browser",
            "scripts/build/build_nulavio.sh": "browser",
            "tests/unit/test_vault.py": "tests",
            "pyproject.toml": "shared",
        }
        for path, expected in cases.items():
            self.assertEqual(measure.component(path), expected, path)

    def test_every_prefix_still_names_something_in_the_tree(self):
        # A path that was renamed would silently fall into "shared" or "tests" and bend the numbers.
        for name, prefixes in measure.COMPONENTS:
            for prefix in prefixes:
                matches = list(ROOT.glob(prefix.rstrip("/") + "*"))
                self.assertTrue(matches, f"{name}: nothing matches {prefix}")


if __name__ == "__main__":
    unittest.main()
