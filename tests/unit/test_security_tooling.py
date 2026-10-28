"""Security scanners (scripts/security/, ci/sast/, .gitleaks.toml) and pinned build inputs.

The scanners themselves run in CI (job "security") and with scripts/security/scan.sh. These
tests check their configuration and coverage without the network. Only GitleaksHistoryTest runs
a scanner, and only when scan.sh's cache already holds it.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import string
import subprocess
import tempfile
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
# What Opengrep 1.32 takes as a suppression: the words SUPPRESSION matches, in any case, anywhere in
# the line (a string too) or alone on the line before; a bare one silences every rule. One form is
# allowed. The words are split here so that this file holds none of them and is checked like any other.
SUPPRESSION = re.compile(r"(?i)no(?:sem|opengrep)")
ALLOWED_FORM = "no" + "semgrep"
ALLOWED_SUPPRESSION = re.compile(ALLOWED_FORM + r": ([\w-]+) -- \S")


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


def git_files() -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode()
    return sorted({name for name in listed.split("\0") if name})


def scanned_files():
    """(path, text) of every file Opengrep may read: what git lists (scan.sh opengrep), minus the rules'
    own test cases (.semgrepignore), Markdown (no rule reads it) and binary files."""
    for name in git_files():
        path = ROOT / name
        if path.suffix == ".md" or path.is_symlink() or not path.is_file() or path.is_relative_to(RULE_CASES):
            continue
        data = path.read_bytes()
        if b"\0" not in data:
            yield path, data.decode(errors="replace")


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

    def test_no_rule_reads_markdown(self):
        # The suppression check leaves Markdown out: the documentation names the forms in prose.
        for rule_id, block in rules().items():
            if "languages: [generic]" in block:  # the other languages are Python, JavaScript and Java
                include, _, exclude = block.split("paths:", 1)[1].split("metadata:", 1)[0].partition("exclude:")
                globs = re.findall(r'"([^"]+)"', include)
                with self.subTest(rule=rule_id):
                    self.assertTrue('"*.md"' in exclude or all(re.search(r"\.(?!md$)\w+$", glob) for glob in globs))

    def test_suppressions_name_one_rule_and_the_reason(self):
        found = rules()
        seen = 0
        for path, text in scanned_files():
            for number, line in enumerate(text.splitlines(), 1):
                if tokens := SUPPRESSION.findall(line):
                    seen += 1
                    with self.subTest(path=str(path.relative_to(ROOT)), line=number, text=line.strip()):
                        match = ALLOWED_SUPPRESSION.search(line)
                        self.assertTrue(
                            match and len(tokens) == 1, f"write: {ALLOWED_FORM}: <rule id> -- <why this line is safe>"
                        )
                        self.assertIn(match[1], found)
        self.assertGreater(seen, 0)  # the walk reaches the known suppressions in scripts/ and tests/


class GitleaksConfigTest(unittest.TestCase):
    def test_default_rules_and_narrow_allowlists_for_test_fixtures(self):
        config = tomllib.loads((ROOT / ".gitleaks.toml").read_text())
        self.assertIs(config["extend"]["useDefault"], True)
        for allowlist in config["allowlists"]:
            with self.subTest(allowlist=allowlist["description"]):
                self.assertEqual(allowlist["condition"], "AND")  # the files AND the exact values
                self.assertTrue(allowlist["targetRules"])
                self.assertFalse({"commits", "stopwords"} & set(allowlist), "never allowlist whole commits or words")
                # b/: --remerge-diff names a file with a conflict b/<path> (scan.sh reads merges with it)
                self.assertTrue(all(path.startswith("^(b/)?tests/") and path.endswith("$") for path in allowlist["paths"]))
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

    def test_key_material_file_names(self):
        config = tomllib.loads((ROOT / ".gitleaks.toml").read_text())
        rule = next(r for r in config["rules"] if r["id"] == "nulavio-key-material-file")
        path = re.compile(rule["path"])  # Go's RE2 syntax, which Python reads the same way here
        keys = [
            "android/release.jks", "signing/upload.keystore", "app.p12", "tls/server.pem", "id_ed25519", "packaging/repo.key",
            "packaging-signing-backup.gpg",  # gpg --export-secret-keys -o (binary)
            "home/.gnupg/secring.gpg", ".gnupg/private-keys-v1.d/ABCD.key", "release-secrets.kdbx",  # KeePassXC
        ]  # fmt: skip
        for name in keys:
            self.assertRegex(name, path)
        for name in ("docs/security/signing.md", "packaging/repo-key.asc", "scripts/release/sign_repo.sh", "gpg.conf"):
            self.assertNotRegex(name, path)


def tools_cache() -> Path:
    """Where scan.sh keeps the scanners (looked up in the same order as scan.sh)."""
    if os.environ.get("NULAVIO_SECURITY_TOOLS"):
        return Path(os.environ["NULAVIO_SECURITY_TOOLS"])
    if os.environ.get("RUNNER_TEMP"):
        return Path(os.environ["RUNNER_TEMP"]) / "nulavio-security-tools"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "nulavio-security-tools"


def cached_download(tool: str) -> Path | None:
    """The scanner's pinned release download, if scan.sh's cache has it with the pinned SHA-256."""
    script = (SECURITY / "fetch_tools.sh").read_text()
    url = re.search(rf"^url\[{tool}\]=(\S+)$", script, re.M)[1]
    sha = re.search(rf"^sha\[{tool}\]=(\S+)$", script, re.M)[1]
    path = tools_cache() / "downloads" / url.rsplit("/", 1)[1]
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
        return path
    return None


# A line .gitleaks.toml allowlists in each test fixture: (file, how the line starts). The test
# reads the line from the file, so this one holds no key-like value.
ALLOWLISTED = (
    ("tests/unit/test_assistant.py", "KEY = "),
    ("tests/integration/test_assistant_ui.py", "KEY = "),
    ("tests/unit/test_upstream_fast_path.py", "SUBKEY = "),
    ("tests/fixtures/nv1-vectors.json", '"key": '),
)

# Binary, as `gpg --export-secret-keys -o` and KeePassXC write them; not keys.
BINARY_KEYS = {"signing-backup.gpg": bytes(range(256)), "release.kdbx": bytes(range(255, -1, -1)), "upload.jks": b"\0" * 64}


def fake_token() -> str:
    """A GitHub token's shape with random characters, made at run time: not a real token, and the
    repository holds no token-like string."""
    return "ghp_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(36))


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "needs git and bash")
class GitleaksHistoryTest(unittest.TestCase):
    """scan.sh gitleaks on a throwaway repository, with a fake token where `git log -p` alone shows
    nothing: a line added while resolving a merge, an octopus merge, a symlink replaced by a file,
    a file that .gitattributes marks as binary."""

    @classmethod
    def setUpClass(cls):
        cls.download = cached_download("gitleaks")
        if cls.download is None:
            if os.environ.get("NULAVIO_REQUIRE_SECURITY_TOOLS") == "1":  # CI's security job: never skip silently
                raise AssertionError("gitleaks is not in scan.sh's cache")
            raise unittest.SkipTest("gitleaks is not in scan.sh's cache, and unit tests download nothing")

    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="nv-gitleaks-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        downloads = tmp / "tools" / "downloads"
        downloads.mkdir(parents=True)
        (downloads / self.download.name).symlink_to(self.download)  # fetch_tools.sh checks it and unpacks it there
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp), "TMPDIR": str(tmp), "LC_ALL": "C",
            "NULAVIO_SECURITY_TOOLS": str(tmp / "tools"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }  # fmt: skip
        self.repo = tmp / "repo"
        (self.repo / "scripts" / "security").mkdir(parents=True)
        for name in ("scan.sh", "fetch_tools.sh"):
            shutil.copy2(SECURITY / name, self.repo / "scripts" / "security" / name)
        for name in (".gitleaks.toml", ".gitleaksignore"):
            shutil.copy2(ROOT / name, self.repo / name)
        (self.repo / "README.md").write_text("one\ntwo\nthree\n")
        self.git("init", "-q", "-b", "main")
        self.commit("base")

    def git(self, *args: str, check: bool = True) -> str:
        run = subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=check, capture_output=True, text=True)
        return run.stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def findings(self, check: str = "gitleaks") -> set[tuple[str, str, str]]:
        """(rule, file name, commit) of each finding; scan.sh must fail if and only if there is one."""
        result = subprocess.run(
            ["bash", "scripts/security/scan.sh", check], cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=120
        )
        found = set()
        for block in result.stdout.split("\n\n"):
            fields = dict(re.findall(r"^(RuleID|File|Commit):[ \t]*(\S*)$", block, re.M))
            if "RuleID" in fields:  # a conflicted file of a merge is named b/<path>, hence the name only
                found.add((fields["RuleID"], Path(fields["File"]).name, fields.get("Commit", "")))
        self.assertEqual(result.returncode, 1 if found else 0, result.stdout + result.stderr)
        return found

    def test_a_clean_history_passes(self):
        self.assertEqual(self.findings(), set())

    def test_a_secret_added_while_resolving_a_merge(self):
        self.git("switch", "-q", "-c", "side")
        (self.repo / "README.md").write_text("one\nside\nthree\n")
        self.commit("side")
        self.git("switch", "-q", "main")
        (self.repo / "README.md").write_text("one\nmain\nthree\n")
        self.commit("main")
        self.git("merge", "-q", "side", check=False)  # conflict
        (self.repo / "README.md").write_text(f'one\nmerged\ntoken = "{fake_token()}"\nthree\n')
        merge = self.commit("merge side")
        self.assertEqual(self.findings(), {("github-pat", "README.md", merge)})

    def test_allowlisted_fixtures_rewritten_while_resolving_a_merge(self):
        # --remerge-diff names a conflicted file b/<path>: .gitleaks.toml's allowlists must still
        # match it, and only it (the same lines in another file are still found).
        resolved = {}
        for name, start in ALLOWLISTED:
            resolved[name] = next(line for line in (ROOT / name).read_text().splitlines() if line.lstrip().startswith(start))
        resolved["elsewhere.py"] = "\n".join(resolved.values())
        self.git("switch", "-q", "-c", "side")
        for branch in ("side", "main"):
            if branch == "main":
                self.git("switch", "-q", "main")
            for name in resolved:
                (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
                (self.repo / name).write_text(f"{branch}\n")
            self.commit(branch)
        self.git("merge", "-q", "side", check=False)  # a conflict in every file
        for name, text in resolved.items():
            (self.repo / name).write_text(f"{text}\n")
        merge = self.commit("merge side")
        self.assertEqual(self.findings(), {("generic-api-key", "elsewhere.py", merge)})

    def test_a_secret_added_in_an_octopus_merge(self):
        for branch in ("a", "b"):
            self.git("switch", "-q", "-c", branch, "main")
            (self.repo / f"{branch}.txt").write_text(f"{branch}\n")
            self.commit(branch)
        self.git("switch", "-q", "main")
        (self.repo / "main.txt").write_text("main\n")
        self.commit("main")
        self.git("merge", "-q", "--no-commit", "a", "b")
        with open(self.repo / "README.md", "a") as handle:
            handle.write(f'token = "{fake_token()}"\n')
        merge = self.commit("merge a and b")
        self.assertEqual(len(self.git("rev-list", "--parents", "-n1", merge).split()), 4)
        self.assertEqual(self.findings(), {("github-pat", "README.md", merge)})

    def test_a_secret_in_a_file_that_replaces_a_symlink(self):
        (self.repo / "link").symlink_to("README.md")
        self.commit("link")
        (self.repo / "link").unlink()
        (self.repo / "link").write_text(f'token = "{fake_token()}"\n')
        change = self.commit("the symlink becomes a file")
        self.assertEqual(self.findings(), {("github-pat", "link", change)})

    def test_gitattributes_cannot_hide_a_file(self):
        (self.repo / ".gitattributes").write_text("*.txt -diff\n")
        (self.repo / "notes.txt").write_text(f'token = "{fake_token()}"\n')
        added = self.commit("notes")
        self.assertEqual(self.findings(), {("github-pat", "notes.txt", added)})

    def test_binary_key_files_in_a_commit(self):
        for name, data in BINARY_KEYS.items():
            (self.repo / name).write_bytes(data)
        added = self.commit("keys")
        self.assertEqual(self.findings(), {("nulavio-key-material-file", name, added) for name in BINARY_KEYS})

    def test_binary_key_files_in_the_staged_changes(self):
        for name, data in BINARY_KEYS.items():
            (self.repo / name).write_bytes(data)
        self.git("add", "-A")
        self.assertEqual(self.findings("staged"), {("nulavio-key-material-file", name, "") for name in BINARY_KEYS})


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
