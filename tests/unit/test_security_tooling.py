"""Security scanners (scripts/security/, ci/sast/, .gitleaks.toml) and pinned build inputs.

The scanners themselves run in CI (job "security") and with scripts/security/scan.sh. These
tests check their configuration and coverage without the network and without the tools.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECURITY = ROOT / "scripts" / "security"
RULES = ROOT / "ci" / "sast" / "nulavio-rules.yml"
RULE_CASES = ROOT / "tests" / "fixtures" / "sast"
WRAPPER = ROOT / "android" / "gradle" / "wrapper"

# Gradle's own checksums for the wrapper this repository pins, from
#   https://services.gradle.org/distributions/gradle-9.8.2-wrapper.jar.sha256
#   https://services.gradle.org/distributions/gradle-9.8.2-bin.zip.sha256
# Upgrading Gradle: regenerate the wrapper, then copy both published values here.
GRADLE_PUBLISHED = {
    "9.8.2": {
        "wrapper_jar": "3b8a25775a69158b5ad2b1d17a80a88dc7b40a352a73eb27d06c612a7ce68e98",
        "bin_zip": "21bd5da2de49b642904077f38c0efdc7778e92b3ed0889392dca61b97e389607",
    },
}
TOOLS = {"actionlint", "gitleaks", "opengrep", "shellcheck", "zizmor"}
CHECKS = ("actionlint", "zizmor", "gitleaks", "shellcheck", "opengrep", "opengrep-rules")
SHEBANG = re.compile(r"^#!\s*(/usr)?/bin/(env\s+)?(ba|da|k)?sh(\s|$)")
SOURCE_DIRS = ("launcher", "scripts", "browser", "tests", "bin", "android", "packaging", "ci/containers")
SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".java", ".kts", ".sh", ".xml", ".yml", ".yaml", ".Containerfile", ""}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache", "artifacts", "build", ".gradle", ".kotlin"}


def rules() -> dict[str, str]:
    """Rule id -> the YAML text of that rule. The standard library has no YAML parser, and the
    rules file keeps every rule in one "  - id:" block."""
    blocks = re.split(r"^  - id: ", RULES.read_text(), flags=re.M)[1:]
    return {block.split("\n", 1)[0].strip(): block for block in blocks}


def rule_annotations() -> list[tuple[str, str, str]]:
    """(file, "ruleid" or "ok", rule id) for each annotation in the rules' test cases."""
    found = []
    for case in sorted(RULE_CASES.iterdir()):
        for match in re.finditer(r"(?:#|//|<!--)\s*(ruleid|ok):\s*([\w, -]+?)\s*(?:-->)?$", case.read_text(), re.M):
            found += [(case.name, match[1], rule_id.strip()) for rule_id in match[2].split(",")]
    return found


def source_files():
    """The code Opengrep scans, minus the rules' own test cases and this file."""
    for name in SOURCE_DIRS:
        for root, dirs, files in os.walk(ROOT / name):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for file_name in files:
                path = Path(root) / file_name
                if path.suffix in SOURCE_SUFFIXES and not path.is_relative_to(RULE_CASES) and path != Path(__file__).resolve():
                    yield path


def git_files() -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted({name for name in listed.split("\0") if name})


class PinnedInputsTest(unittest.TestCase):
    def test_gradle_wrapper_is_gradles_published_one(self):
        properties = (WRAPPER / "gradle-wrapper.properties").read_text()
        url = r"^distributionUrl=https\\://services\.gradle\.org/distributions/gradle-([\d.]+)-bin\.zip$"
        version = re.search(url, properties, re.M)
        self.assertIsNotNone(version, "the wrapper must download a -bin.zip from services.gradle.org")
        self.assertIn(version[1], GRADLE_PUBLISHED, "new Gradle version: add its published checksums to GRADLE_PUBLISHED")
        published = GRADLE_PUBLISHED[version[1]]
        jar = hashlib.sha256((WRAPPER / "gradle-wrapper.jar").read_bytes()).hexdigest()
        self.assertEqual(jar, published["wrapper_jar"], "gradle-wrapper.jar is not the one Gradle published")
        self.assertIn(f"distributionSha256Sum={published['bin_zip']}\n", properties)

    def test_scanners_are_pinned_by_version_and_sha256(self):
        script = (SECURITY / "fetch_tools.sh").read_text()
        urls = dict(re.findall(r"^url\[(\w+)\]=(\S+)$", script, re.M))
        shas = dict(re.findall(r"^sha\[(\w+)\]=(\S+)$", script, re.M))
        self.assertEqual(set(urls), TOOLS)
        self.assertEqual(set(shas), TOOLS)
        for tool in TOOLS:
            with self.subTest(tool=tool):
                self.assertRegex(urls[tool], r"^https://github\.com/[\w.-]+/[\w.-]+/releases/download/v?\d+\.\d+\.\d+/")
                self.assertRegex(shas[tool], r"^[0-9a-f]{64}$")

    def test_downloads_are_checked_before_use(self):
        script = (SECURITY / "fetch_tools.sh").read_text()
        self.assertIn("set -euo pipefail", script)
        self.assertIn("sha256sum --check --strict", script)
        self.assertIn("--proto '=https' --proto-redir '=https' --tlsv1.2", script)
        scan = (SECURITY / "scan.sh").read_text()
        self.assertIn('"$repo/scripts/security/fetch_tools.sh" "$tools"', scan)  # every run checks the cache again


class OpengrepRulesTest(unittest.TestCase):
    def test_every_rule_is_complete(self):
        found = rules()
        self.assertGreaterEqual(len(found), 10)
        for rule_id, block in found.items():
            with self.subTest(rule=rule_id):
                self.assertRegex(rule_id, r"^nulavio-[a-z0-9-]+$")
                for field in ("message:", "languages:", "severity: ERROR", "cwe:"):
                    self.assertIn(field, block)
                if "languages: [generic]" in block:
                    self.assertIn("paths:", block, "a generic rule must say which files it reads")

    def test_every_rule_has_cases_that_must_and_must_not_match(self):
        found = rules()
        annotations = rule_annotations()
        for _, kind, rule_id in annotations:
            self.assertIn(rule_id, found, f"{kind} annotation for an unknown rule")
        for rule_id in found:
            with self.subTest(rule=rule_id):
                kinds = {kind for _, kind, annotated in annotations if annotated == rule_id}
                self.assertEqual(kinds, {"ruleid", "ok"})

    def test_only_the_rule_cases_are_left_out_of_the_scan(self):
        lines = [line.strip() for line in (ROOT / ".semgrepignore").read_text().splitlines()]
        self.assertEqual([line for line in lines if line and not line.startswith("#")], ["tests/fixtures/sast/"])

    def test_suppressions_name_one_rule_and_the_reason(self):
        found = rules()
        seen = 0
        for path in source_files():
            for line in path.read_text(errors="ignore").splitlines():
                if "nosemgrep" in line:
                    seen += 1
                    with self.subTest(path=str(path.relative_to(ROOT)), line=line.strip()):
                        match = re.search(r"nosemgrep: ([\w-]+) -- \S", line)
                        self.assertIsNotNone(match, "write: nosemgrep: <rule id> -- <why this line is safe>")
                        self.assertIn(match[1], found)
        self.assertGreater(seen, 0)  # the walk reaches the known suppressions in tests/


class GitleaksConfigTest(unittest.TestCase):
    def test_default_rules_and_narrow_allowlists_for_test_fixtures(self):
        config = tomllib.loads((ROOT / ".gitleaks.toml").read_text())
        self.assertIs(config["extend"]["useDefault"], True)
        for allowlist in config["allowlists"]:
            with self.subTest(allowlist=allowlist["description"]):
                self.assertEqual(allowlist["condition"], "AND")  # the files AND the exact values
                self.assertTrue(allowlist["targetRules"])
                self.assertFalse({"commits", "stopwords"} & set(allowlist), "never allowlist whole commits or words")
                self.assertTrue(all(path.startswith("^tests/") and path.endswith("$") for path in allowlist["paths"]))
                self.assertTrue(all(value.startswith("^") and value.endswith("$") for value in allowlist["regexes"]))

    def test_no_inline_exceptions_and_an_opt_in_hook_for_staged_changes(self):
        scan = (SECURITY / "scan.sh").read_text()
        self.assertIn("--ignore-gitleaks-allow", scan)  # "gitleaks:allow" in a line would hide a finding from review
        self.assertIn("run_gitleaks git --pre-commit --staged", scan)
        hook = ROOT / "scripts" / "git-hooks" / "pre-commit"
        self.assertTrue(os.access(hook, os.X_OK))
        self.assertIn('/scripts/security/scan.sh" staged', hook.read_text())

    def test_every_documented_hooks_path_is_the_one_directory(self):
        # core.hooksPath takes one directory: two documented values would turn one hook off.
        hooks = ROOT / "scripts" / "git-hooks"
        self.assertTrue((hooks / "pre-commit").is_file() and (hooks / "pre-push").is_file())
        values = set()
        for name in git_files():
            path = ROOT / name
            if path.suffix in (".md", ".sh", "") and path.is_file() and not path.is_symlink():
                values.update(re.findall(r"git config core\.hooksPath\s+([^\s`)]+)", path.read_text(errors="replace")))
        self.assertEqual(values, {"scripts/git-hooks"})

    def test_ignored_findings_are_exact_fingerprints(self):
        for line in (ROOT / ".gitleaksignore").read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertRegex(line, r"^[0-9a-f]{40}:[^:\s]+:[\w-]+:\d+$")


@unittest.skipUnless(shutil.which("git") and shutil.which("bash") and (ROOT / ".git").exists(), "needs git, bash and a checkout")
class ShellCoverageTest(unittest.TestCase):
    def test_every_shell_script_is_checked(self):
        listed = subprocess.run(
            ["bash", str(SECURITY / "scan.sh"), "shell-files"], capture_output=True, text=True, check=True, timeout=120
        ).stdout.split()
        expected = []
        for name in git_files():
            path = ROOT / name
            if not path.is_file() or path.is_symlink():
                continue
            with open(path, "rb") as handle:
                first = handle.read(128).split(b"\n", 1)[0].decode(errors="ignore")
            if name.endswith(".sh") or SHEBANG.match(first):
                expected.append(name)
        self.assertEqual(sorted(listed), expected)
        for script in ("bin/nulavio", "android/gradlew", "scripts/release/make_deb.sh", "scripts/security/scan.sh"):
            self.assertIn(script, listed)


class SecurityJobTest(unittest.TestCase):
    def test_ci_runs_every_scanner_blocking_and_read_only(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        job = re.search(r"^  security:\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow, re.M | re.S)
        self.assertIsNotNone(job, 'ci.yml has no "security" job')
        job = job[1]
        self.assertIn("    permissions:\n      contents: read\n", job)
        self.assertIn("persist-credentials: false", job)
        self.assertIn("fetch-depth: 0", job)  # gitleaks reads every commit
        self.assertNotIn("continue-on-error", job)
        self.assertNotIn("secrets.", job)
        self.assertEqual(job.count("${{ github.token }}"), 1)  # zizmor's step only
        steps = re.findall(r"run: scripts/security/scan\.sh ([\w -]+)", job)
        self.assertEqual(sorted(check for step in steps for check in step.split()), sorted(CHECKS))


if __name__ == "__main__":
    unittest.main()
