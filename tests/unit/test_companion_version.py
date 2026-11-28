"""The Companion's version moves with the app between releases (scripts/release/companion_version.py, #286)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "companion_version.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"

GRADLE = """android {{
    defaultConfig {{
        applicationId = "net.nulavio.companion"
        versionCode = {code}
        versionName = "{name}"
    }}
}}
"""


class CompanionVersionTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="nulavio-companion-version-"))
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q", "-b", "main")
        self.write("android/app/src/main/java/App.java", "class App {}\n")
        self.write("android/AGENTS.md", "notes\n")
        self.version(1, "0.1.0")
        self.commit("before the APK was released")
        self.git("tag", "v160.0-0.4")  # no build_companion.sh: this release shipped no APK
        self.write("scripts/release/build_companion.sh", "#!/bin/sh\n")
        self.commit("the release job builds the APK")
        self.git("tag", "v160.0-0.5")

    def git(self, *args: str) -> str:
        command = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args]
        return subprocess.run(command, capture_output=True, text=True, check=True).stdout

    def write(self, path: str, text: str) -> None:
        (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / path).write_text(text)

    def version(self, code: int, name: str) -> None:
        self.write("android/app/build.gradle.kts", GRADLE.format(code=code, name=name))

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def check(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(self.repo), *args],
                              capture_output=True, text=True, check=False)  # fmt: skip

    def pull_request(self, path: str, text: str, version: tuple[int, str] | None = None) -> str:
        """A pull request's checkout: a branch off main that writes `path` (and the version), merged into main
        without fast-forward as GitHub's refs/pull/<n>/merge is. Returns the base commit, HEAD is the merge."""
        base = self.git("rev-parse", "HEAD").strip()
        self.git("switch", "-q", "-c", "topic")
        self.write(path, text)
        if version:
            self.version(*version)
        self.commit("the pull request")
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "merge", "topic")
        return base

    def test_an_app_change_without_a_new_version_is_refused(self):
        self.write("android/app/src/main/java/App.java", "class App { int changed; }\n")
        self.commit("change the app")
        run = self.check()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("android/ changed since v160.0-0.5", run.stderr)
        self.assertIn("raise versionCode and change versionName", run.stderr)

    def test_a_new_code_with_the_same_name_or_a_new_name_with_the_same_code_is_refused(self):
        self.write("android/app/src/main/java/App.java", "class App { int changed; }\n")
        for code, name in ((2, "0.1.0"), (1, "0.2.0")):
            with self.subTest(code=code, name=name):
                self.version(code, name)
                self.commit(f"{code} {name}")
                self.assertEqual(self.check().returncode, 1)

    def test_an_app_change_with_both_raised_passes(self):
        self.write("android/app/src/main/java/App.java", "class App { int changed; }\n")
        self.version(2, "0.2.0")
        self.commit("change the app and its version")
        run = self.check()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("0.2.0 (2); v160.0-0.5 had 0.1.0 (1)", run.stdout)

    def test_changes_that_do_not_reach_the_apk_need_no_new_version(self):
        self.write("android/AGENTS.md", "more notes\n")
        self.write("android/nv1/src/test/java/VectorsTest.java", "class VectorsTest {}\n")
        self.write("android/fdroid/net.nulavio.companion.yml", "Categories: [Security]\n")
        self.commit("docs, tests and F-Droid metadata")
        self.assertEqual(self.check().returncode, 0, self.check().stderr)

    def test_the_version_code_never_goes_down(self):
        self.version(2, "0.2.0")
        self.commit("raise")
        self.git("tag", "v160.0-0.6")
        self.version(1, "0.3.0")
        self.commit("lower the code")
        run = self.check()
        self.assertEqual(run.returncode, 1)
        self.assertIn("versionCode went down from 2 (v160.0-0.6) to 1", run.stderr)

    def test_a_release_that_shipped_no_apk_and_a_rerun_of_the_same_commit_are_not_compared(self):
        # Only v160.0-0.4 (no APK) and the tag on this very commit (a rerun of 0.5): nothing to compare.
        self.git("tag", "-d", "v160.0-0.5")
        self.write("android/app/src/main/java/App.java", "class App { int changed; }\n")
        self.commit("change the app")
        self.git("tag", "v160.0-0.5")
        run = self.check()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("no earlier release shipped the Companion", run.stdout)

    def test_a_shallow_clone_is_refused_not_passed_blind(self):
        shallow = Path(tempfile.mkdtemp(prefix="nulavio-companion-shallow-"))
        self.addCleanup(shutil.rmtree, shallow, True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{self.repo}", str(shallow / "c")], check=True)
        run = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(shallow / "c")],
                             capture_output=True, text=True, check=False)  # fmt: skip
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("shallow clone", run.stderr)

    def test_a_pull_request_that_leaves_the_app_alone_passes_even_when_main_needs_a_version(self):
        # #906: main got an app change without a version (merged before this check); a docs pull request is not the
        # place to fix it, and the release run still refuses it.
        self.write("android/app/src/main/java/App.java", "class App { int changed; }\n")
        self.commit("change the app on main")
        self.assertEqual(self.check().returncode, 1)
        base = self.pull_request("docs/notes.md", "notes\n")
        run = self.check("--changed-since", base)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"android/ did not change since {base}", run.stdout)

    def test_a_pull_request_that_changes_only_files_outside_the_apk_passes(self):
        base = self.pull_request("android/AGENTS.md", "more notes\n")
        self.assertEqual(self.check("--changed-since", base).returncode, 0)

    def test_a_pull_request_that_changes_the_app_without_a_new_version_is_refused(self):
        base = self.pull_request("android/app/src/main/java/App.java", "class App { int changed; }\n")
        run = self.check("--changed-since", base)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("android/ changed since v160.0-0.5", run.stderr)

    def test_a_pull_request_that_changes_the_app_with_a_new_version_passes(self):
        base = self.pull_request("android/app/src/main/java/App.java", "class App { int changed; }\n", (2, "0.2.0"))
        run = self.check("--changed-since", base)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("0.2.0 (2); v160.0-0.5 had 0.1.0 (1)", run.stdout)

    def test_the_second_app_change_after_a_release_needs_no_second_version(self):
        # The comparison is with the last release, not with main: one new version per release, not per change.
        self.pull_request("android/app/src/main/java/App.java", "class App { int changed; }\n", (2, "0.2.0"))
        self.git("branch", "-q", "-D", "topic")
        base = self.pull_request("android/app/src/main/java/Other.java", "class Other {}\n")
        self.assertEqual(self.check("--changed-since", base).returncode, 0)

    def test_a_base_that_is_not_in_the_clone_or_looks_like_an_option_is_refused(self):
        for base in ("b" * 40, "", "--output=/dev/null"):
            with self.subTest(base=base):
                run = self.check(f"--changed-since={base}")
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertIn("is not a commit in this clone", run.stderr)

    def test_a_shallow_clone_is_refused_on_a_pull_request_too(self):
        base = self.git("rev-parse", "HEAD").strip()
        shallow = Path(tempfile.mkdtemp(prefix="nulavio-companion-shallow-"))
        self.addCleanup(shutil.rmtree, shallow, True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{self.repo}", str(shallow / "c")], check=True)
        run = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(shallow / "c"), "--changed-since", base],
                             capture_output=True, text=True, check=False)  # fmt: skip
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("shallow clone", run.stderr)


class WorkflowTest(unittest.TestCase):
    """ci.yml runs the check on pull requests, in the required Companion job (#906)."""

    def setUp(self):
        text = CI.read_text(encoding="utf-8")
        self.job = text[text.index("\n  companion:\n") : text.index("\n  changes:\n")]

    def test_the_companion_job_runs_the_check_with_the_base_and_the_tags(self):
        self.assertIn("name: Companion app (lint, release build)\n", self.job)  # the required check's name
        self.assertIn("fetch-depth: 0 #", self.job)  # every tag and the base; the script refuses a shallow clone
        step = re.search(r"(?m)^      - name: .*companion_version\.py.*\n((?:        .*\n)+)", self.job)
        self.assertIsNotNone(step)
        self.assertIn("if: ${{ !cancelled() && github.event_name == 'pull_request' }}", step[1])
        self.assertIn("BASE: ${{ github.event.pull_request.base.sha }}", step[1])
        self.assertIn('run: python3 -I scripts/release/companion_version.py --repo . --changed-since "$BASE"', step[1])
        self.assertNotIn("continue-on-error", step[1])  # it fails the job, not only warns
        self.assertLess(self.job.index(":app:assembleRelease"), self.job.index("companion_version.py"))

    def test_the_release_still_refuses_on_its_own(self):
        self.assertIn("companion_version.py", (ROOT / "scripts" / "release" / "build_companion.sh").read_text())


if __name__ == "__main__":
    unittest.main()
