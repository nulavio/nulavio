"""Repository hygiene: no secrets, no unexpected executables, no remote code in config."""

from __future__ import annotations

import os
import re
import stat
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache", "artifacts", ".claude"}  # .claude: local agent worktrees, not in git
TEXT_SUFFIXES = {
    ".py", ".js", ".mjs", ".json", ".md", ".html", ".css", ".svg", ".yml", ".yaml", ".toml", ".txt", ".in", "",
    ".sh", ".java", ".kts", ".xml", ".properties", ".patch", ".spec", ".conf", ".Containerfile", ".lockfile",
    ".ftl", ".mn", ".build", ".desktop",
}  # fmt: skip
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "generic bearer": re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{20,}"),
}
EXECUTABLES = {"bin/nulavio", "android/gradlew"}
# Workflow write permissions: (workflow file, job id, permission) -> why. Every other permission is read-only
# or absent; a new write needs an entry here and a reason a reviewer can check.
WRITE_PERMISSIONS = {
    ("ai-review.yml", "review", "id-token"): "Workload Identity Federation to the Claude API (no GitHub write)",
    ("ai-review.yml", "publish", "pull-requests"): "one advisory comment, posted by scripts/ci/post_ai_review.py",
    ("upstream.yml", "firefox-release", "issues"): "one issue per newer Firefox release (scripts/release/upstream_issue.py)",
    ("scorecard.yml", "analysis", "security-events"): "uploads Scorecard's SARIF to the Security tab",
    ("scorecard.yml", "analysis", "id-token"): "signs the published result for scorecard.dev (publish_results)",
    ("release-signing-check.yml", "sign", "id-token"): "OIDC to AWS: the role only the release environment may assume (ci/aws/)",
    ("release.yml", "build", "id-token"): "signs the build-provenance attestation of the packages (Sigstore)",
    ("release.yml", "build", "attestations"): "stores that attestation with the repository",
    ("release.yml", "publish", "id-token"): "OIDC to AWS (KMS signing role, ci/aws/) and the attestation of the signed files",
    ("release.yml", "publish", "attestations"): "stores the attestation of the signed files",
    ("release.yml", "publish", "contents"): "drafts the GitHub release; the maintainer publishes it",
}
# Expressions that carry text an attacker or a model can choose; they never go inside a run: script.
UNTRUSTED_IN_RUN = re.compile(r"\$\{\{[^}]*\b(github\.event\.|github\.head_ref|steps\.|needs\.|inputs\.)")


def workflow_jobs(text: str) -> dict[str, str]:
    """Job id -> its text, for workflows in this repository's layout (two-space indentation)."""
    body = text.split("\njobs:\n", 1)[1]
    return {m.group(1): m.group(2) for m in re.finditer(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", body, re.M | re.S)}


def permission_entries(text: str, indent: int) -> list[tuple[str, str]]:
    """(name, access) pairs of the permissions: keys at the given indentation, block or flow style."""
    pad = " " * indent
    entries = []
    for match in re.finditer(rf"^{pad}permissions:[ \t]*(\S.*)?\n((?:{pad}  .*\n)*)", text + "\n", re.M):
        inline = (match.group(1) or "").split("#", 1)[0].strip()
        if inline in ("read-all", "write-all"):
            entries.append(("*", inline.split("-")[0]))
        entries += re.findall(r"([\w-]+)\s*:\s*(\w+)", inline if inline.startswith("{") else match.group(2))
    return entries


def run_scripts(text: str) -> list[str]:
    """The script of every run: key (inline or block scalar)."""
    scripts, lines = [], text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not match:
            continue
        indent, value = len(match.group(1)), match.group(2)
        if value not in ("|", ">", "|-", ">-"):
            scripts.append(value)
            continue
        body = []
        for following in lines[index + 1 :]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        scripts.append("\n".join(body))
    return scripts


def repo_files():
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if Path(root).is_relative_to(ROOT / "android"):
            dirs[:] = [d for d in dirs if d not in {"build", ".gradle", ".kotlin"}]  # Gradle outputs (ignored by git)
        for name in files:
            yield Path(root) / name


class HygieneTest(unittest.TestCase):
    def test_no_secrets_committed(self):
        hits = []
        for path in repo_files():
            if path.suffix not in TEXT_SUFFIXES or path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(errors="ignore")
            for label, pattern in SECRET_PATTERNS.items():
                if pattern.search(text):
                    hits.append(f"{path.relative_to(ROOT)}: {label}")
        self.assertEqual(hits, [])

    def test_only_expected_files_are_executable(self):
        unexpected = []
        for path in repo_files():
            rel = str(path.relative_to(ROOT))
            mode = path.stat().st_mode
            if mode & stat.S_IXUSR and rel not in EXECUTABLES and not rel.startswith("scripts/"):
                unexpected.append(rel)
            if mode & stat.S_IWOTH:
                unexpected.append(f"{rel} (world-writable)")
        self.assertEqual(unexpected, [])

    def test_workflow_actions_are_pinned_by_sha(self):
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            for line in workflow.read_text().splitlines():
                match = re.search(r"uses:\s*([^\s#]+)", line)
                if match and not match.group(1).startswith("./"):
                    self.assertRegex(match.group(1), r"@[0-9a-f]{40}$", f"{workflow.name}: {line.strip()}")
            self.assertIn("permissions:", workflow.read_text())

    def test_launcher_has_no_third_party_imports(self):
        allowed_local = {"nulavio_launcher"}
        import sys

        stdlib = set(sys.stdlib_module_names)
        for source in (ROOT / "launcher" / "nulavio_launcher").rglob("*.py"):
            for match in re.finditer(r"^(?:from|import)\s+([a-zA-Z_][\w]*)", source.read_text(), re.M):
                module = match.group(1)
                self.assertTrue(
                    module in stdlib or module in allowed_local or module == "__future__",
                    f"{source.name} imports third-party module {module}",
                )


class WorkflowSecurityTest(unittest.TestCase):
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

    def test_write_permissions_are_on_jobs_and_listed(self):
        found = set()
        for workflow in self.workflows:
            text = workflow.read_text()
            top = text.split("\njobs:\n", 1)[0]
            for name, access in permission_entries(top, 0):
                self.assertNotEqual(access, "write", f"{workflow.name}: {name}: write belongs on a job, not the workflow")
            for job, body in workflow_jobs(text).items():
                for name, access in permission_entries(body, 4):
                    if access == "write":
                        found.add((workflow.name, job, name))
        self.assertEqual(found, set(WRITE_PERMISSIONS), "update WRITE_PERMISSIONS (with the reason) or drop the write")

    def test_no_untrusted_expression_inside_a_run_script(self):
        for workflow in self.workflows:
            for script in run_scripts(workflow.read_text()):
                self.assertIsNone(UNTRUSTED_IN_RUN.search(script), f"{workflow.name}: pass it through env: instead")

    def test_pull_request_head_is_checked_out_only_into_its_own_path(self):
        for workflow in self.workflows:
            for step in re.split(r"^ +- ", workflow.read_text(), flags=re.M)[1:]:
                if "actions/checkout@" in step and re.search(r"github\.event\.pull_request\.head|github\.head_ref", step):
                    self.assertRegex(step, r"(?m)^\s+path: \S", f"{workflow.name}: pull request code next to trusted code")
                    self.assertIn("persist-credentials: false", step, workflow.name)


if __name__ == "__main__":
    unittest.main()
