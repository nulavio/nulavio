"""The CI release path: upload order to R2, the published-repository check, and the workflow's boundaries."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

FAKE_AWS = """#!/bin/sh
{
  printf 'key=%s secret=%s token=%s region=%s checksums=%s ' \\
    "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" "${AWS_SESSION_TOKEN:-none}" "$AWS_REGION" "$AWS_REQUEST_CHECKSUM_CALCULATION"
  printf '%s ' "$@"
  printf '\\n'
} >> "$FAKE_AWS_LOG"
"""


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class UploadRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = self.tmp / "rpm"
        (self.repo / "repodata").mkdir(parents=True)
        (self.repo / "x86_64").mkdir()
        for name in ("repodata/repomd.xml", "repodata/repomd.xml.asc", "repodata/abc-primary.xml.zst",
                     "nulavio-packages.asc", "x86_64/nulavio-160.0-0.3.fc44.x86_64.rpm"):  # fmt: skip
            (self.repo / name).write_text("x")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "aws").write_text(FAKE_AWS)
        (bin_dir / "aws").chmod(stat.S_IRWXU)
        self.log = self.tmp / "aws.log"
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_AWS_LOG": str(self.log),
            "R2_ACCESS_KEY_ID": "r2-key",
            "R2_SECRET_ACCESS_KEY": "r2-secret",
            "R2_ACCOUNT": "acct",
            # What the KMS signing role left in the job: never used for the upload.
            "AWS_ACCESS_KEY_ID": "kms-role-key",
            "AWS_SECRET_ACCESS_KEY": "kms-role-secret",
            "AWS_SESSION_TOKEN": "kms-role-token",
        }

    def run_upload(self):
        return subprocess.run(["bash", str(RELEASE / "upload_repo.sh"), str(self.repo)], env=self.env,
                              capture_output=True, text=True)  # fmt: skip

    def test_packages_first_signed_metadata_last_with_the_r2_token_only(self):
        out = self.run_upload()
        self.assertEqual(out.returncode, 0, out.stderr)
        calls = self.log.read_text().splitlines()
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertIn("key=r2-key secret=r2-secret token=none region=auto checksums=when_required", call)
            self.assertIn("--endpoint-url https://acct.r2.cloudflarestorage.com s3", call)
            self.assertNotIn("--delete", call)
        self.assertIn("sync", calls[0])
        self.assertIn("--exclude repodata/repomd.xml --exclude repodata/repomd.xml.asc", calls[0])
        self.assertIn("repomd.xml.asc s3://nulavio-packages/rpm/repodata/repomd.xml.asc", calls[1])
        self.assertTrue(calls[2].rstrip().endswith("s3://nulavio-packages/rpm/repodata/repomd.xml --only-show-errors"))

    def test_refuses_an_unsigned_repository(self):
        (self.repo / "repodata" / "repomd.xml.asc").unlink()
        out = self.run_upload()
        self.assertEqual(out.returncode, 2)
        self.assertIn("not a signed repository", out.stderr)
        self.assertFalse(self.log.exists())


class ReleaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.build, self.publish = self.text.split("\n  publish:\n", 1)

    def test_manual_from_main_with_approval_before_signing(self):
        self.assertIn("on:\n  workflow_dispatch:", self.text)
        self.assertNotIn("pull_request", self.text)
        self.assertIn("if: github.ref == 'refs/heads/main'", self.build)
        self.assertIn("environment: release", self.publish)
        self.assertIn("needs: build", self.publish)

    def test_the_build_machine_never_holds_signing_or_upload_credentials(self):
        self.assertIn("runs-on: blacksmith-", self.build)
        self.assertIn("environment: build", self.build)
        for secret in ("R2_", "NULAVIO_SIGNING_ROLE_ARN", "NULAVIO_KMS_KEY_ARN", "configure-aws-credentials"):
            self.assertNotIn(secret, self.build)
        self.assertIn("runs-on: ubuntu-24.04", self.publish)
        self.assertNotIn("GOOGLE_SAFEBROWSING", self.publish)

    def test_provenance_is_checked_before_signing_and_the_release_is_a_draft(self):
        verify = self.publish.index("gh attestation verify")
        self.assertLess(verify, self.publish.index('scripts/release/publish_release.sh "'))
        self.assertIn("--source-ref refs/heads/main", self.publish)
        self.assertLess(self.publish.index("upload_repo.sh"), self.publish.index("check_published.sh"))
        self.assertIn("gh release create", self.publish)
        self.assertIn("--draft", self.publish)
        self.assertIn("NULAVIO_BUILD_PROFILE: runner", self.build)


class AsanWorkflowTest(unittest.TestCase):
    def test_weekly_asan_build_runs_the_integration_suite_and_fails_on_a_report(self):
        text = (ROOT / ".github" / "workflows" / "asan.yml").read_text(encoding="utf-8")
        self.assertIn("schedule:", text)
        self.assertIn("NULAVIO_MOZCONFIG_EXTRA: mozconfig.asan", text)
        self.assertIn("tests/run.py integration", text)
        self.assertIn('grep -l "ERROR: AddressSanitizer"', text)
        self.assertIn("__asan_init", text)
        self.assertNotIn("R2_", text)
        self.assertNotIn("id-token", text)
        asan = (ROOT / "browser" / "build" / "mozconfig.asan").read_text(encoding="utf-8")
        self.assertIn("--enable-address-sanitizer", asan)

    @unittest.skipUnless(shutil.which("bash"), "bash not available")
    def test_a_variant_build_is_never_rehearsed_as_a_release(self):
        out = subprocess.run(
            ["bash", str(RELEASE / "rehearse_release.sh"), "160.0", "/nonexistent"],
            env={**os.environ, "NULAVIO_MOZCONFIG_EXTRA": "mozconfig.asan"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(out.returncode, 2)
        self.assertIn("never a release", out.stderr)
        build = (ROOT / "scripts" / "build" / "build_nulavio.sh").read_text(encoding="utf-8")
        self.assertIn("NULAVIO_MOZCONFIG_EXTRA =~ ^mozconfig", build)


if __name__ == "__main__":
    unittest.main()
