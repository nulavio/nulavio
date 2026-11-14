"""The Companion's version moves with the app between releases (scripts/release/companion_version.py, #286)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "companion_version.py"

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

    def check(self) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(self.repo)],
                              capture_output=True, text=True, check=False)  # fmt: skip

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


if __name__ == "__main__":
    unittest.main()
