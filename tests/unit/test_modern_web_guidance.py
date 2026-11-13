"""The development wrapper keeps queries pinned, private and project-scoped."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/dev/modern_web_guidance.sh"


class ModernWebGuidanceTests(unittest.TestCase):
    def run_wrapper(self, *args: str, installed: bool = True):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            wrapper = root / "scripts/dev/modern_web_guidance.sh"
            wrapper.parent.mkdir(parents=True)
            shutil.copyfile(WRAPPER, wrapper)
            cli = root / "ci/modern-web-guidance/node_modules/modern-web-guidance/skills/modern-web-guidance/modern-web.mjs"
            if installed:
                cli.parent.mkdir(parents=True)
                cli.touch()
            fake = Path(tmp) / "node"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                'print(json.dumps([os.getenv("DISABLE_TELEMETRY"), os.getcwd() == os.environ["EXPECTED_ROOT"], sys.argv[1:]]))\n'
            )
            fake.chmod(0o755)
            return subprocess.run(
                ["bash", str(wrapper), *args],
                cwd=tmp,
                env={
                    **os.environ,
                    "PATH": tmp + os.pathsep + os.environ["PATH"],
                    "DISABLE_TELEMETRY": "0",
                    "EXPECTED_ROOT": str(root),
                },
                capture_output=True,
                text=True,
                check=False,
            )

    def test_queries_disable_telemetry_pin_version_and_keep_arguments(self):
        for args in [("search", "accessible modal dialog"), ("retrieve", "a,b"), ("list",), ("--version",)]:
            with self.subTest(args=args):
                result = self.run_wrapper(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                telemetry, cwd, forwarded = json.loads(result.stdout)
                self.assertEqual(telemetry, "1")
                self.assertTrue(cwd)
                self.assertEqual(
                    forwarded,
                    ["ci/modern-web-guidance/node_modules/modern-web-guidance/skills/modern-web-guidance/modern-web.mjs", *args],
                )

    def test_mutating_and_scan_commands_do_not_invoke_node(self):
        for args in [(), ("install",), ("update",), ("set-allow-origin-trials",), ("legacy-scan", ".")]:
            with self.subTest(args=args):
                result = self.run_wrapper(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage:", result.stderr)

    def test_missing_installation_fails_without_downloading(self):
        result = self.run_wrapper("list", installed=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("npm ci --ignore-scripts", result.stderr)
