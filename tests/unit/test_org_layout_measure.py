"""The script behind the repository layout evidence (ADR 0013) still describes this tree."""

from __future__ import annotations

import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock

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
            ".agents/skills/modern-web-guidance/SKILL.md": "process",
            ".mwgrc": "process",
            "ci/modern-web-guidance/package-lock.json": "process",
            "scripts/dev/modern_web_guidance.sh": "process",
            "tests/unit/test_modern_web_guidance.py": "process",
            "tests/unit/test_agent_skills.py": "process",
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

    def test_every_prefix_still_names_tracked_files_and_little_is_left_unattributed(self):
        # A path that was renamed would silently fall into "shared" or "tests" and bend the numbers.
        # Read from git, as the script does, with the script's own matching.
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout.decode()
        files = [name for name in listed.split("\0") if name]
        for name, prefixes in measure.COMPONENTS:
            for prefix in prefixes:
                self.assertTrue(
                    any(f == prefix or f.startswith(prefix) for f in files), f"{name}: no tracked file under {prefix}"
                )
        for prefix in (*measure.POLICY_TEXT, measure.SCREENSHOTS):
            self.assertTrue(any(f == prefix or f.startswith(prefix) for f in files), prefix)
        shared = sorted(f for f in files if measure.component(f) == "shared")
        expected = [".coderabbit.yaml", ".editorconfig", ".gitignore", ".gitleaks.toml", ".gitleaksignore", ".semgrepignore",
                    "pyproject.toml", "requirements/dev.txt"]  # fmt: skip
        self.assertEqual(shared, expected, "a new top-level path belongs to a component, or to this list")

    def test_paths_come_from_git_as_they_are(self):
        # With git's default, "site/café.html" arrives quoted and escaped and matches no component.
        with mock.patch.object(measure.subprocess, "run") as run:
            run.return_value.stdout = ""
            measure.git("log", "--name-only")
        self.assertEqual(run.call_args.args[0][:3], ["git", "-c", "core.quotePath=false"])
        self.assertEqual(measure.component("site/café.html"), "site")

    def test_a_renamed_directory_is_noticed(self):
        self.assertEqual(measure.component("site-src/index.html"), "shared")  # not "site": the test above would then fail
        self.assertEqual(measure.component("scripts/rel/x.py"), "shared")

    def test_the_media_budget_says_when_it_is_passed_and_what_adr_0013_asks_then(self):
        result = measure.media_budget("HEAD")
        self.assertEqual(result["budget_bytes"], 250_000_000)
        self.assertGreater(result["media_bytes_packed"], 0)
        self.assertEqual(result["over_budget"], result["media_bytes_packed"] > 250_000_000)
        under = measure.budget_summary({**result, "media_bytes_packed": 75_900_000, "over_budget": False})
        self.assertIn("75.9 MB, budget 250.0 MB (ADR 0013, point 3)", under)
        self.assertNotIn("Over the budget", under)
        with mock.patch.object(measure, "history_blobs", return_value={"all:media": [250_000_001, 0]}):
            over = measure.media_budget("HEAD")
        self.assertTrue(over["over_budget"])
        text = measure.budget_summary(over)
        self.assertIn("**Over the budget.** New capture sets go to a repository of their own", text)
        self.assertIn("No history is rewritten", text)
        self.assertTrue((ROOT / "docs" / "adr" / "0013-repository-layout.md").is_file())

    def test_each_release_measures_it_where_the_history_is_complete(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        publish = workflow[workflow.index("\n  publish:\n") :]
        self.assertIn("fetch-depth: 0", publish)  # the whole history, not a shallow clone
        step = publish.index('org_layout_measure.py --budget --ref HEAD --summary "$GITHUB_STEP_SUMMARY"')
        self.assertLess(publish.index("Draft the GitHub release"), step)
        self.assertIn("${{ runner.temp }}/media-budget.json", publish[step:])
        self.assertNotIn("publish/media-budget.json", publish)  # publish_release.sh wants its stage empty


if __name__ == "__main__":
    unittest.main()
