"""scripts/ci/gradle.sh: the Companion's Gradle steps run again only when a repository refused them (#516)."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "gradle.sh"

RATE_LIMITED = """FAILURE: Build failed with an exception.
> Could not resolve all artifacts for configuration 'classpath'.
   > Could not resolve com.android.tools:sdk-common:32.5.1.
      > Could not parse POM https://dl.google.com/dl/android/maven2/com/android/tools/sdk-common/32.5.1/sdk-common-32.5.1.pom
         > Repository MavenRepo is disabled due to earlier error below:
            > Could not GET 'https://repo.maven.apache.org/maven2/com/google/code/gson/gson/2.11.0/gson-2.11.0.pom'.
               > Received status code 429 from server: Too Many Requests
"""
VERIFICATION = RATE_LIMITED + "Dependency verification failed for configuration ':app:releaseRuntimeClasspath'\n"
LINT = "FAILURE: Build failed with an exception.\n> Lint found errors in the project; aborting build.\n"
NOT_FOUND = "> Could not resolve com.example:gone:1.0.\n   > Could not find com.example:gone:1.0.\n"


class GradleRetryTest(unittest.TestCase):
    def run_with(self, *outputs: str, waits: str = "0 0") -> tuple[int, int, str]:
        """Run the script with a gradlew that prints each output in turn and fails, then succeeds once they run out.
        Returns the exit code, how many times gradlew ran, and what the script printed."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for i, text in enumerate(outputs):
                (tmp_path / f"out{i}").write_text(text)
            stub = tmp_path / "gradlew"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                f'cd "{tmp}"\n'
                'n=$(cat count 2>/dev/null || echo 0); echo $((n + 1)) > count; echo "args: $*" >> args\n'
                '[[ -f out$n ]] || { echo "BUILD SUCCESSFUL"; exit 0; }\n'
                'cat out$n >&2; exit 1\n'
            )  # fmt: skip
            stub.chmod(0o755)
            env = {**os.environ, "NULAVIO_GRADLEW": str(stub), "NULAVIO_GRADLE_RETRY_WAITS": waits, "RUNNER_TEMP": tmp}
            done = subprocess.run([str(SCRIPT), "-q", ":nv1:test"], env=env, capture_output=True, text=True)
            count = int((tmp_path / "count").read_text())
            self.assertIn(f"-p {ROOT / 'android'} --no-daemon -q :nv1:test", (tmp_path / "args").read_text())
            self.assertEqual(sorted(p.name for p in tmp_path.glob("gradle.*")), [], "the log is left behind")
            return done.returncode, count, done.stdout

    def test_a_rate_limit_runs_gradle_again(self):
        code, count, out = self.run_with(RATE_LIMITED, RATE_LIMITED)
        self.assertEqual((code, count), (0, 3))
        warnings = [line for line in out.splitlines() if line.startswith("::warning title=Gradle::")]
        self.assertEqual(len(warnings), 2)
        self.assertIn("https://repo.maven.apache.org", warnings[0])
        self.assertIn("Received status code 429", warnings[0])
        self.assertIn("run 2 of 3", warnings[0])

    def test_it_gives_up_after_the_last_wait_with_gradles_failure(self):
        code, count, out = self.run_with(RATE_LIMITED, RATE_LIMITED, RATE_LIMITED, RATE_LIMITED)
        self.assertEqual((code, count), (1, 3))
        self.assertIn("Too Many Requests", out)  # Gradle's own output is shown, every time

    def test_a_server_error_or_a_dropped_connection_is_retried(self):
        for text in ("> Received status code 503 from server: Service Unavailable\n", "> Read timed out\n"):
            with self.subTest(text=text):
                self.assertEqual(self.run_with(text)[:2], (0, 2))

    def test_a_failed_dependency_verification_is_never_retried(self):
        self.assertEqual(self.run_with(VERIFICATION)[:2], (1, 1))

    def test_a_build_failure_or_a_missing_artifact_is_not_retried(self):
        for text in (LINT, NOT_FOUND):
            with self.subTest(text=text):
                self.assertEqual(self.run_with(text)[:2], (1, 1))

    def test_no_waits_means_one_run(self):
        self.assertEqual(self.run_with(RATE_LIMITED, waits="")[:2], (1, 1))

    def test_success_at_once(self):
        self.assertEqual(self.run_with()[:2], (0, 1))


class WorkflowTest(unittest.TestCase):
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_every_gradle_step_in_ci_goes_through_the_wrapper(self):
        runs = re.findall(r"(?m)^\s+run: (.*gradle.*)$", self.text)
        self.assertEqual(
            runs,
            [
                'JAVA_HOME="$JAVA_HOME_21_X64" scripts/ci/gradle.sh -q :nv1:test',
                'JAVA_HOME="$JAVA_HOME_21_X64" scripts/ci/gradle.sh -q :app:lintDebug :app:assembleRelease',
            ],
        )
        self.assertNotIn("android/gradlew", self.text)

    def test_nothing_turns_dependency_verification_off_or_refetches(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for text in (self.text, script):
            for flag in ("--refresh-dependencies", "--write-verification-metadata", "--dependency-verification", "--offline"):
                self.assertNotIn(flag, text)


if __name__ == "__main__":
    unittest.main()
