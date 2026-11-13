"""Run the workflow's actual shell blocks with a disposable Git remote and a fake gh."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/release-metadata.yml"
FAKE_GH = """#!{python}
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
with open(os.environ['GH_CALLS'], 'a') as f:
    f.write(json.dumps(args) + '\\n')
if args[0] == 'api':
    print(pathlib.Path(os.environ['RELEASE_FIXTURE']).read_text())
elif args[:2] == ['release', 'download']:
    dest = pathlib.Path(args[args.index('--dir') + 1])
    dest.mkdir()
    shutil.copyfile(os.environ['MANIFEST_FIXTURE'], dest / 'manifest.json')
elif args[:2] == ['attestation', 'verify']:
    sys.exit(int(os.environ.get('ATTESTATION_RC', '0')))
elif args[:2] == ['pr', 'list']:
    print(os.environ.get('EXISTING_PR', ''))
elif args[:2] == ['pr', 'create']:
    print('https://github.com/nulavio/nulavio/pull/999')
elif args[:2] != ['auth', 'setup-git']:
    sys.exit('unexpected gh call: ' + repr(args))
"""


def shell_step(name: str) -> str:
    block = WORKFLOW.read_text().split(f"      - name: {name}\n", 1)[1].split("\n      - ", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1])


class MetadataWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-qb", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        for name, body in {
            "CHANGELOG.md": "# Changelog\n\n<!-- releases -->\n",
            "packaging/release.json": '{"version": "160.0-0.1", "channel": "alpha"}',
            "browser/build/engine.json": '{"firefox": "160.0"}',
        }.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        script = self.repo / "scripts/release/release_metadata.py"
        script.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "scripts/release/release_metadata.py", script)
        shutil.copyfile(ROOT / "scripts/release/release_manifest.py", script.with_name("release_manifest.py"))
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.git("tag", "v160.0-0.2")
        subprocess.run(["git", "init", "-q", "--bare", str(self.base / "remote")], check=True)
        self.git("remote", "add", "origin", str(self.base / "remote"))
        run = self.base / "run"
        run.mkdir()
        binary = self.base / "bin"
        binary.mkdir()
        gh = binary / "gh"
        gh.write_text(FAKE_GH.format(python=sys.executable))
        gh.chmod(0o700)
        release = self.base / "release.json"
        release.write_text(
            json.dumps(
                {
                    "tag_name": "v160.0-0.2",
                    "draft": False,
                    "prerelease": True,
                    "published_at": "2026-11-13T12:00:00Z",
                    "html_url": "https://github.com/nulavio/nulavio/releases/tag/v160.0-0.2",
                    "body": "## Fixes\n\n- Profiles.",
                }
            )
        )
        manifest = self.base / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "nulavio_base_commit": self.sha,
                    "firefox": "160.0",
                    "packages": [{"file": "packages/x86_64/nulavio-160.0-0.2.fc44.x86_64.rpm"}],
                }
            )
        )
        self.env = {
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(run),
            "GITHUB_REPOSITORY": "nulavio/nulavio",
            "TAG": "v160.0-0.2",
            "GH_TOKEN": "",
            "GITHUB_OUTPUT": str(run / "output"),
            "GITHUB_STEP_SUMMARY": str(run / "summary"),
            "GH_CALLS": str(run / "gh-calls"),
            "RELEASE_FIXTURE": str(release),
            "MANIFEST_FIXTURE": str(manifest),
        }

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True).stdout

    def step(self, name):
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", shell_step(name)], cwd=self.repo, env=self.env, capture_output=True, text=True
        )

    def prepare(self):
        for name in (
            "Fetch the published release and verify its build provenance",
            "Generate changelog, download metadata and recovery patch",
        ):
            result = self.step(name)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generation_and_missing_token_keep_a_recovery_patch_without_any_remote_write(self):
        self.prepare()
        patch = (Path(self.env["RUNNER_TEMP"]) / "release-metadata.patch").read_text()
        self.assertIn("160.0-0.2", patch)
        self.assertIn("Profiles.", patch)
        result = self.step("Open the metadata pull request, or report recovery instructions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not configured", result.stdout)
        self.assertEqual(self.git("branch", "--show-current").strip(), "main")
        self.assertNotIn('"create"', Path(self.env["GH_CALLS"]).read_text())

    def test_dedicated_token_pushes_only_a_branch_and_creates_a_pr_then_reuses_it(self):
        self.prepare()
        self.env["GH_TOKEN"] = "test-only-placeholder"
        result = self.step("Open the metadata pull request, or report recovery instructions")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        branch = "agent/release/chore-metadata-v160.0-0.2"
        self.assertIn(branch, self.git("ls-remote", "--heads", "origin"))
        changed = self.git("diff", "--name-only", self.sha, "HEAD").splitlines()
        self.assertEqual(changed, ["CHANGELOG.md", "packaging/release.json"])
        self.assertIn("Signed-off-by:", self.git("log", "-1", "--format=%B"))
        self.env["EXISTING_PR"] = "https://github.com/nulavio/nulavio/pull/999"
        result = self.step("Open the metadata pull request, or report recovery instructions")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = Path(self.env["GH_CALLS"]).read_text()
        self.assertEqual(calls.count('["pr", "create"'), 1)

    def test_bad_attestation_stops_before_bookkeeping_and_invalid_tag_never_reaches_gh(self):
        self.env["ATTESTATION_RC"] = "1"
        result = self.step("Fetch the published release and verify its build provenance")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((Path(self.env["RUNNER_TEMP"]) / "release-metadata.patch").exists())
        calls = Path(self.env["GH_CALLS"]).read_text()
        self.env["TAG"] = "v160.0-0.2; echo injected"
        result = self.step("Fetch the published release and verify its build provenance")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(Path(self.env["GH_CALLS"]).read_text(), calls)

    def test_metadata_merge_triggers_the_site_workflow(self):
        text = (ROOT / ".github/workflows/site.yml").read_text()
        paths = text.split("    paths:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
        patterns = [
            line.strip().split(" #", 1)[0].removeprefix("- ").strip('"')
            for line in paths.splitlines()
            if line.strip().startswith("- ")
        ]
        self.assertTrue(
            any(fnmatch.fnmatchcase("packaging/release.json", pattern) for pattern in patterns),
            "merging the generated metadata PR must deploy the download pages",
        )

    def test_attested_manifest_for_another_revision_at_the_same_commit_is_refused(self):
        fixture = Path(self.env["MANIFEST_FIXTURE"])
        fixture.write_text(
            json.dumps(
                {
                    "nulavio_base_commit": self.sha,
                    "firefox": "160.0",
                    "packages": [{"file": "packages/x86_64/nulavio-160.0-0.1.fc44.x86_64.rpm"}],
                }
            )
        )
        result = self.step("Fetch the published release and verify its build provenance")
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.git("diff")
        result = self.step("Generate changelog, download metadata and recovery patch")
        self.assertNotEqual(result.returncode, 0, "a valid attestation cannot establish a different package revision")
        self.assertIn("revision", result.stderr)
        self.assertEqual(self.git("diff"), before)


if __name__ == "__main__":
    unittest.main()
