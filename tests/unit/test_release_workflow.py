"""The CI release path: upload order to R2, the published-repository check, and the workflow's boundaries."""

from __future__ import annotations

import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
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


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class UploadAptRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = self.tmp / "apt"
        for name in ("dists/stable/Release", "dists/stable/Release.gpg", "dists/stable/InRelease",
                     "dists/stable/main/binary-amd64/Packages", "dists/stable/main/binary-amd64/by-hash/SHA256/abc",
                     "pool/main/n/nulavio/nulavio_160.0-0.4_amd64.deb"):  # fmt: skip
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text("x")
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "aws").write_text(FAKE_AWS)
        (bin_dir / "aws").chmod(stat.S_IRWXU)
        self.log = self.tmp / "aws.log"
        self.env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_AWS_LOG": str(self.log),
                    "R2_ACCESS_KEY_ID": "r2-key", "R2_SECRET_ACCESS_KEY": "r2-secret", "R2_ACCOUNT": "acct"}  # fmt: skip

    def run_upload(self, path=None):
        return subprocess.run(["bash", str(RELEASE / "upload_repo.sh"), str(path or self.repo)], env=self.env,
                              capture_output=True, text=True)  # fmt: skip

    def test_pool_and_indexes_first_then_release_then_inrelease(self):
        out = self.run_upload()
        self.assertEqual(out.returncode, 0, out.stderr)
        calls = self.log.read_text().splitlines()
        self.assertEqual(len(calls), 4)
        self.assertIn("sync", calls[0])
        self.assertIn("s3://nulavio-packages/apt/", calls[0])
        self.assertIn(
            "--exclude dists/stable/Release --exclude dists/stable/Release.gpg --exclude dists/stable/InRelease", calls[0]
        )
        self.assertIn("dists/stable/Release s3://nulavio-packages/apt/dists/stable/Release ", calls[1])
        self.assertIn("s3://nulavio-packages/apt/dists/stable/Release.gpg", calls[2])
        self.assertIn("s3://nulavio-packages/apt/dists/stable/InRelease", calls[3])  # apt reads it first: last up
        for call in calls:
            self.assertNotIn("--delete", call)

    def test_refuses_an_unsigned_repository_or_another_directory(self):
        (self.repo / "dists" / "stable" / "InRelease").unlink()
        out = self.run_upload()
        self.assertEqual(out.returncode, 2)
        self.assertIn("not a signed repository", out.stderr)
        other = self.tmp / "debs"
        other.mkdir()
        out = self.run_upload(other)
        self.assertEqual(out.returncode, 2)
        self.assertIn("neither a staged rpm/ nor apt/", out.stderr)
        self.assertFalse(self.log.exists())


class ReleaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.build, self.publish = self.text.split("\n  publish:\n", 1)
        self.build, self.flatpak = self.build.split("\n  flatpak:\n", 1)

    def test_manual_from_main_with_approval_before_signing(self):
        self.assertIn("on:\n  workflow_dispatch:", self.text)
        self.assertNotIn("pull_request", self.text)
        self.assertIn("if: github.ref == 'refs/heads/main'", self.build)
        self.assertIn("environment: release", self.publish)
        self.assertIn("needs: [build, flatpak]", self.publish)
        self.assertIn("needs.build.result == 'success'", self.publish)  # a failed Flatpak never holds back a release

    def test_the_build_machine_never_holds_signing_or_upload_credentials(self):
        self.assertIn("runs-on: blacksmith-", self.build)
        self.assertIn("environment: build", self.build)
        for secret in ("R2_", "NULAVIO_SIGNING_ROLE_ARN", "NULAVIO_KMS_KEY_ARN", "configure-aws-credentials"):
            self.assertNotIn(secret, self.build)
        self.assertIn("runs-on: ubuntu-24.04", self.publish)
        self.assertNotIn("GOOGLE_SAFEBROWSING", self.publish)

    def test_the_flatpak_is_built_and_started_from_this_run_without_secrets(self):
        self.assertIn("needs: build", self.flatpak)
        self.assertIn("runs-on: ubuntu-24.04", self.flatpak)
        for held in ("secrets.", "environment:", "id-token", "configure-aws-credentials"):
            self.assertNotIn(held, self.flatpak)
        self.assertIn("flatpak-builder-lint org.flatpak.Builder manifest", self.flatpak)
        self.assertIn("flatpak-builder-lint org.flatpak.Builder repo", self.flatpak)
        self.assertIn("scripts/release/check_flatpak.sh", self.flatpak)
        self.assertIn("flatpak_manifest.py --archive", self.publish)
        self.assertIn("--url", self.publish)

    def test_provenance_is_checked_before_signing_and_the_release_is_a_draft(self):
        verify = self.publish.index("gh attestation verify")
        self.assertLess(verify, self.publish.index('scripts/release/publish_release.sh "'))
        self.assertIn("--source-ref refs/heads/main", self.publish)
        self.assertLess(self.publish.index("upload_repo.sh"), self.publish.index("check_published.sh"))
        self.assertIn('scripts/release/upload_repo.sh "$RUNNER_TEMP/publish/apt"', self.publish)
        check = (RELEASE / "check_published.sh").read_text(encoding="utf-8")
        self.assertIn('check "APT ($sources_file)" apt_install', check)
        self.assertIn("APT::Update::Error-Mode=any", check)
        # The published source file is the reviewed one, whole, and that copy is what apt uses.
        self.assertIn('cmp -s "$sources" "$repo/site/apt/nulavio.sources"', check)
        self.assertIn('-v "$sources:/nulavio.sources:ro"', check)
        self.assertNotIn('curl -fsSL --retry 3 "$SOURCES_FILE"', check)

    def test_the_published_version_must_be_the_released_one(self):
        # rpm adds the distribution after the release; a .deb's version has nothing after it.
        check = (RELEASE / "check_published.sh").read_text(encoding="utf-8")
        start = check.index("matches() {")
        matches = check[start : check.index("\n}\n", start) + 3]
        cases = {
            ("dnf (x)", "160.0-0.4.fc44"): True, ("dnf (x)", "160.0-0.4"): True, ("dnf (x)", "160.0-0.4.1"): False,
            ("dnf (x)", "160.0-0.41.fc44"): False, ("APT (x)", "160.0-0.4"): True, ("APT (x)", "160.0-0.4.1"): False,
            ("APT (x)", "160.0-0.4.fc44"): False, ("APT (x)", "apt install failed"): False,
        }  # fmt: skip
        for (name, got), expected in cases.items():
            script = matches + '\nexpected=160.0-0.4\nmatches "$1" "$2"'
            run = subprocess.run(["bash", "-c", script, "-", name, got], capture_output=True, text=True)
            self.assertEqual(run.returncode == 0, expected, (name, got))
        self.assertIn("gh release create", self.publish)
        self.assertIn("--draft", self.publish)
        self.assertIn("NULAVIO_BUILD_PROFILE: runner", self.build)

    def test_the_flatpak_is_composed_and_linted_as_flathub_does(self):
        self.assertIn("--compose-url-policy=full", self.text)
        self.assertIn("flatpak-builder-lint org.flatpak.Builder repo repo", self.text)

    def test_the_bundle_is_attested_checked_and_signed_with_the_release(self):
        flatpak_job = self.text[self.text.index("\n  flatpak:\n") :]
        self.assertLess(flatpak_job.index("check_flatpak.sh"), flatpak_job.index("flatpak build-bundle"))
        sign = self.publish.index("NULAVIO_FLATPAK_BUNDLE=$bundle scripts/release/publish_release.sh")
        self.assertLess(sign, self.publish.index("subject-path: ${{ runner.temp }}/publish/github/*"))
        publish = (RELEASE / "publish_release.sh").read_text(encoding="utf-8")
        self.assertLess(publish.index('cp "$bundle" "$stage/github/"'), publish.index("sha256sum -- * >SHA256SUMS"))
        self.assertIn('"nulavio-${tag#v}.x86_64.flatpak"', publish)


class AsanWorkflowTest(unittest.TestCase):
    def test_weekly_asan_build_runs_the_integration_suite_and_fails_on_a_report(self):
        text = (ROOT / ".github" / "workflows" / "asan.yml").read_text(encoding="utf-8")
        self.assertIn("schedule:", text)
        self.assertIn("NULAVIO_MOZCONFIG_EXTRA: mozconfig.asan", text)
        self.assertIn("scripts/release/run_integration.sh", text)
        self.assertIn("NULAVIO_INTEGRATION_IMAGE: fedora-release-itest", text)
        self.assertIn('grep -l "ERROR: AddressSanitizer"', text)
        self.assertIn("__asan_init", text)
        self.assertNotRegex(text, r"\| *grep -q")  # SIGPIPE with pipefail
        self.assertIn("NULAVIO_ENGINE: ${{ runner.temp }}/install/nulavio/nulavio", text)  # the executable
        self.assertIn('found.vendor == "Nulavio"', text)  # the engine tests cannot skip silently
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


class RepeatableBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        sys.path.insert(0, str(RELEASE))
        import compare_builds

        self.compare = compare_builds

    def archive(self, name, files, mode=0o644):
        path = self.tmp / name
        with tarfile.open(path, "w:xz") as archive:
            for member_name, body in files.items():
                info = tarfile.TarInfo(member_name)
                info.size, info.mode, info.mtime = len(body), mode, 1_700_000_000
                archive.addfile(info, io.BytesIO(body))
        return path

    def test_identical_archives_pass(self):
        first = self.archive("a.tar.xz", {"nulavio/libxul.so": b"same"})
        second = self.tmp / "b.tar.xz"
        second.write_bytes(first.read_bytes())
        self.assertEqual(self.compare.main([str(first), str(second)]), 0)

    def test_a_difference_fails_and_names_the_file(self):
        first = self.archive("a.tar.xz", {"nulavio/libxul.so": b"one", "nulavio/same": b"x"})
        second = self.archive("b.tar.xz", {"nulavio/libxul.so": b"two", "nulavio/same": b"x"})
        summary = self.tmp / "summary.md"
        code = self.compare.main([str(first), str(second), "--summary", str(summary), "--extract", str(self.tmp / "d")])
        self.assertEqual(code, 1)
        report = summary.read_text(encoding="utf-8")
        self.assertIn("`nulavio/libxul.so`: content", report)
        self.assertNotIn("nulavio/same", report)
        self.assertEqual((self.tmp / "d" / "second" / "nulavio" / "libxul.so").read_bytes(), b"two")

    def test_the_build_date_is_the_commit_time_and_the_workflow_builds_twice(self):
        build = (ROOT / "scripts" / "build" / "build_nulavio.sh").read_text(encoding="utf-8")
        self.assertIn('-e MOZ_BUILD_DATE="$build_date"', build)
        self.assertIn('-e SOURCE_DATE_EPOCH="$commit_time"', build)
        text = (ROOT / ".github" / "workflows" / "repeatable.yml").read_text(encoding="utf-8")
        self.assertIn("copy: [first, second]", text)
        self.assertIn("runs-on: blacksmith-", text)
        self.assertIn("scripts/release/compare_builds.py", text)
        self.assertNotIn("R2_", text)
        self.assertNotIn("id-token", text)


if __name__ == "__main__":
    unittest.main()
