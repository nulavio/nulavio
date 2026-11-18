"""scripts/ci/gradle.sh: the Companion's Gradle steps run again only when a repository refused them (#516), and in CI
read Maven Central through a mirror first (#535)."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci" / "gradle.sh"
INIT = ROOT / "scripts" / "ci" / "maven-mirror.init.gradle"
MIRROR = "https://maven-central.storage-download.googleapis.com/maven2/"

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
MIRROR_REFUSED = """FAILURE: Build failed with an exception.
> Could not resolve all artifacts for configuration 'classpath'.
   > Could not resolve com.google.code.gson:gson:2.11.0.
      > Could not GET 'https://maven-central.storage-download.googleapis.com/maven2/com/google/code/gson/gson/2.11.0/gson-2.11.0.pom'.
         > Received status code 503 from server: Service Unavailable
"""


class GradleRetryTest(unittest.TestCase):
    def run_with(self, *outputs: str, waits: str | None = "0 0", mirror: str | None = None) -> tuple[int, int, str]:
        """Run the script with a gradlew that prints each output in turn and fails with 7, then succeeds once they run
        out. `waits` None leaves the script's default; `mirror` is NULAVIO_MAVEN_MIRROR (None: unset). Returns the exit
        code, how many times gradlew ran, and what the script printed; `self.slept` is the waits it asked for (a stub
        `sleep` records them), `self.runs` each run's arguments and the mirror Gradle was given."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for i, text in enumerate(outputs):
                (tmp_path / f"out{i}").write_text(text)
            stub = tmp_path / "gradlew"
            stub.write_text(
                "#!/usr/bin/env bash\n"
                f'cd "{tmp}"\n'
                'n=$(cat count 2>/dev/null || echo 0); echo $((n + 1)) > count\n'
                'echo "args: $* mirror=${NULAVIO_MAVEN_MIRROR-unset}" >> args\n'
                '[[ -f out$n ]] || { echo "BUILD SUCCESSFUL"; exit 0; }\n'
                'cat out$n >&2; exit 7\n'
            )  # fmt: skip
            stub.chmod(0o755)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            (bin_dir / "sleep").write_text(f'#!/usr/bin/env bash\necho "$1" >> "{tmp}/slept"\n')
            (bin_dir / "sleep").chmod(0o755)
            env = {**os.environ, "NULAVIO_GRADLEW": str(stub), "RUNNER_TEMP": tmp}
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env.pop("NULAVIO_GRADLE_RETRY_WAITS", None)
            env.pop("NULAVIO_MAVEN_MIRROR", None)
            if mirror is not None:
                env["NULAVIO_MAVEN_MIRROR"] = mirror
            if waits is not None:
                env["NULAVIO_GRADLE_RETRY_WAITS"] = waits
            done = subprocess.run([str(SCRIPT), "-q", ":nv1:test"], env=env, capture_output=True, text=True)
            count = int((tmp_path / "count").read_text())
            slept = tmp_path / "slept"
            self.slept = slept.read_text().split() if slept.exists() else []
            self.runs = (tmp_path / "args").read_text().splitlines()
            for run in self.runs:
                android = re.escape(str(ROOT / "android"))
                self.assertRegex(run, rf"^args: -p {android} --no-daemon (--init-script \S+ )?-q :nv1:test ")
            self.assertEqual(sorted(p.name for p in tmp_path.glob("gradle.*")), [], "the log is left behind")
            return done.returncode, count, done.stdout

    def test_a_rate_limit_runs_gradle_again(self):
        code, count, out = self.run_with(RATE_LIMITED, RATE_LIMITED)
        self.assertEqual((code, count), (0, 3))
        warnings = [line for line in out.splitlines() if line.startswith("::warning title=Gradle::")]
        self.assertEqual(len(warnings), 2)
        self.assertIn("(https://repo.maven.apache.org: Received status code 429 from server)", warnings[0])
        self.assertIn("run 2 of 3", warnings[0])
        self.assertEqual(self.slept, ["0", "0"])

    def test_by_default_it_waits_2_then_5_minutes(self):
        """#535: on main a 429 outlasted 60 + 120 s (run of bdf68ec9); 120 + 300 s fits both jobs' time limits."""
        self.assertEqual(self.run_with(RATE_LIMITED, RATE_LIMITED, waits=None)[:2], (0, 3))
        self.assertEqual(self.slept, ["120", "300"])

    def test_it_gives_up_after_the_last_wait_with_gradles_failure(self):
        code, count, out = self.run_with(RATE_LIMITED, RATE_LIMITED, RATE_LIMITED, RATE_LIMITED)
        self.assertEqual((code, count), (7, 3))
        self.assertIn("Too Many Requests", out)  # Gradle's own output is shown, every time

    def test_a_server_error_or_a_dropped_connection_is_retried(self):
        for text in (
            "> Received status code 503 from server: Service Unavailable\n",
            "> Read timed out\n",
            "Exception in thread main java.io.IOException: Server returned HTTP response code: 503 for URL: x\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.run_with(text)[:2], (0, 2))

    def test_a_failed_dependency_verification_is_never_retried(self):
        self.assertEqual(self.run_with(VERIFICATION)[:2], (7, 1))

    def test_a_build_failure_or_a_missing_artifact_is_not_retried(self):
        for text in (LINT, NOT_FOUND):
            with self.subTest(text=text):
                self.assertEqual(self.run_with(text)[:2], (7, 1))

    def test_no_waits_means_one_run(self):
        self.assertEqual(self.run_with(RATE_LIMITED, waits="")[:2], (7, 1))

    def test_success_at_once(self):
        self.assertEqual(self.run_with()[:2], (0, 1))

    def test_without_a_mirror_gradle_reads_maven_central_only(self):
        self.run_with()
        self.assertEqual(self.runs, [f"args: -p {ROOT / 'android'} --no-daemon -q :nv1:test mirror="])
        self.run_with(mirror="")
        self.assertNotIn("--init-script", self.runs[0])

    def test_with_a_mirror_gradle_gets_the_init_script_and_the_url(self):
        code, count, out = self.run_with(mirror=MIRROR)
        self.assertEqual((code, count), (0, 1))
        run = f"args: -p {ROOT / 'android'} --no-daemon --init-script {INIT} -q :nv1:test mirror={MIRROR}"
        self.assertEqual(self.runs, [run])
        self.assertIn(f"through the mirror {MIRROR} first", out)

    def test_when_the_mirror_refuses_the_next_runs_go_to_maven_central(self):
        code, count, out = self.run_with(MIRROR_REFUSED, RATE_LIMITED, mirror=MIRROR)
        self.assertEqual((code, count), (0, 3))
        self.assertIn("--init-script", self.runs[0])
        for run in self.runs[1:]:
            self.assertNotIn("--init-script", run)
            self.assertTrue(run.endswith(" mirror="), run)
        warnings = [line for line in out.splitlines() if line.startswith("::warning title=Gradle::")]
        self.assertIn("maven-central.storage-download.googleapis.com: Received status code 503", warnings[0])
        self.assertIn("without the mirror", warnings[0])
        self.assertNotIn("without the mirror", warnings[1])

    def test_when_maven_central_refuses_the_mirror_stays(self):
        self.assertEqual(self.run_with(RATE_LIMITED, mirror=MIRROR)[:2], (0, 2))
        self.assertEqual([("--init-script" in run) for run in self.runs], [True, True])

    def test_a_failed_verification_is_not_retried_with_the_mirror_either(self):
        self.assertEqual(self.run_with(VERIFICATION, mirror=MIRROR)[:2], (7, 1))


class MirrorInitScriptTest(unittest.TestCase):
    """What the init script does is tried with Gradle in the pull request (#535); this checks what must not drift."""

    text = INIT.read_text(encoding="utf-8")

    def test_it_puts_the_mirror_right_before_maven_central_in_both_lists(self):
        self.assertIn("settings.pluginManagement.repositories", self.text)
        self.assertIn("settings.dependencyResolutionManagement.repositories", self.text)
        self.assertIn("def central = 'https://repo.maven.apache.org/maven2/'", self.text)
        self.assertIn("repositories.add(at, added)", self.text)
        self.assertIn('throw new GradleException("maven-mirror.init.gradle: no Maven Central', self.text)

    def test_it_takes_only_an_https_url(self):
        self.assertIn("System.getenv('NULAVIO_MAVEN_MIRROR')", self.text)
        self.assertIn("mirror ==~ /https:", self.text)

    def test_it_touches_nothing_but_repositories(self):
        code = "\n".join(line for line in self.text.splitlines() if not line.lstrip().startswith("//"))
        for word in ("verification", "Verification", "startParameter", "offline", "refresh", "allowInsecureProtocol",
                     "content {", "exclusiveContent", "metadataSources"):  # fmt: skip
            self.assertNotIn(word, code)

    def test_local_f_droid_and_release_builds_do_not_use_it(self):
        for path in [*(ROOT / "android").rglob("*.kts"), *(ROOT / "scripts" / "release").iterdir()]:
            if path.is_file():
                self.assertNotIn("maven-mirror", path.read_text(encoding="utf-8", errors="replace"), path)
                self.assertNotIn("NULAVIO_MAVEN_MIRROR", path.read_text(encoding="utf-8", errors="replace"), path)


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

    def test_both_gradle_steps_read_maven_central_through_the_mirror(self):
        steps = re.findall(r"(?m)^\s+env:\n\s+NULAVIO_MAVEN_MIRROR: (\S+) #.*\n\s+run: .*scripts/ci/gradle\.sh ", self.text)
        self.assertEqual(steps, [MIRROR, MIRROR])

    def test_nothing_turns_dependency_verification_off_or_refetches(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for text in (self.text, script):
            for flag in ("--refresh-dependencies", "--write-verification-metadata", "--dependency-verification", "--offline",
                         "dependency.verification"):  # fmt: skip
                self.assertNotIn(flag, text)
        # Their short forms (Gradle 9.8.2: -U, -M, -F), alone or among other letters, on every line that runs Gradle.
        lines = [line for line in self.text.splitlines() if "scripts/ci/gradle.sh " in line]
        lines += [line for line in script.splitlines() if '"$gradlew"' in line]
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertEqual([t for t in line.split() if re.fullmatch(r"-[A-Za-z]*[UMF][A-Za-z]*", t)], [], line)


if __name__ == "__main__":
    unittest.main()
