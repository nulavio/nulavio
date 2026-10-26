"""Repository hygiene: no secrets, no unexpected executables, no remote code in config."""

from __future__ import annotations

import os
import re
import stat
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".ruff_cache", "artifacts"}
TEXT_SUFFIXES = {".py", ".js", ".json", ".md", ".html", ".css", ".svg", ".yml", ".yaml", ".toml", ".txt", ".in", ""}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "generic bearer": re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._-]{20,}"),
}
EXECUTABLES = {"bin/nulavio"}


def repo_files():
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
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


if __name__ == "__main__":
    unittest.main()
