"""The CI release path: upload order to R2, the published-repository check, and the workflow's boundaries."""

from __future__ import annotations

import io
import json
import os
import re
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


ENVIRONMENT = re.compile(r"^\s*environment:[ \t]*(?:#.*)?(?:\n\s*name:[ \t]*)?['\"]?([^\s'\"#]*)", re.M)


def job_environments(workflow: str) -> list[tuple[str, str]]:
    """(job, environment) for each job of a workflow that names one, as `environment: <name>` or as
    `environment:` with `name: <name>` on the next line. Jobs are the two-space keys under `jobs:`."""
    jobs = re.split(r"^  ([A-Za-z0-9_-]+):[ \t]*$", workflow.split("\njobs:\n", 1)[-1], flags=re.M)
    return [(job, name) for job, body in zip(jobs[1::2], jobs[2::2], strict=True) for name in ENVIRONMENT.findall(body)]


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
        self.build, self.sign = self.text.split("\n  sign:\n", 1)
        self.sign, self.publish = self.sign.split("\n  publish:\n", 1)
        self.build, self.flatpak = self.build.split("\n  flatpak:\n", 1)
        self.flatpak, self.companion = self.flatpak.split("\n  companion:\n", 1)

    def test_manual_from_main_with_approval_before_signing(self):
        self.assertIn("on:\n  workflow_dispatch:", self.text)
        self.assertNotIn("pull_request", self.text)
        self.assertIn("if: github.ref == 'refs/heads/main'", self.build)
        self.assertIn("environment: release\n", self.sign)
        self.assertIn("needs: [build, flatpak, flatpak-check, companion]", self.sign)
        self.assertIn("needs.build.result == 'success'", self.sign)  # a failed Flatpak never holds back a release

    def test_every_job_that_can_attest_runs_main_only(self):
        # An attestation from release.yml on main is what the notes tell people to check (release_notes.py):
        # a job with that token runs only on main, by its own guard or by needing the build's success.
        jobs = re.split(r"\n  (?=[a-z][a-z-]*:\n)", self.text.split("\njobs:\n", 1)[1])  # every job, as many as there are
        self.assertGreaterEqual(len(jobs), 4)
        for job in jobs:
            if "id-token: write" in job or "attestations: write" in job:
                self.assertTrue("if: github.ref == 'refs/heads/main'" in job or "needs.build.result == 'success'" in job,
                                job.splitlines()[0])  # fmt: skip
        self.assertIn("if: github.ref == 'refs/heads/main'", self.companion)
        self.assertNotIn("id-token", self.flatpak)

    def test_the_build_machine_never_holds_signing_or_upload_credentials(self):
        self.assertIn("runs-on: blacksmith-", self.build)
        self.assertIn("environment: build", self.build)
        for secret in ("R2_", "NULAVIO_SIGNING_ROLE_ARN", "NULAVIO_KMS_KEY_ARN", "configure-aws-credentials"):
            self.assertNotIn(secret, self.build)
        for job in (self.sign, self.publish):
            self.assertIn("runs-on: ubuntu-24.04", job)
            self.assertNotIn("GOOGLE_SAFEBROWSING", job)

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
        verify = self.sign.index("gh attestation verify")
        self.assertLess(verify, self.sign.index('scripts/release/publish_release.sh "'))
        self.assertIn("--source-ref refs/heads/main", self.sign)
        self.assertLess(self.publish.index("upload_repo.sh"), self.publish.index("check_published.sh"))
        self.assertIn('scripts/release/upload_repo.sh "$RUNNER_TEMP/publish/apt"', self.publish)
        check = (RELEASE / "check_published.sh").read_text(encoding="utf-8")
        self.assertIn('check "APT ($sources_file)" apt_install', check)
        self.assertIn("APT::Update::Error-Mode=any", check)
        # The published source file is the reviewed one, whole (run in test_release_script_protections),
        # and that copy is what apt uses.
        self.assertIn('-v "$sources:/nulavio.sources:ro"', check)
        self.assertNotIn('curl -fsSL --retry 3 "$SOURCES_FILE"', check)

    def test_the_signing_session_leaves_the_environment_once_everything_is_signed(self):
        # #328 (F7): the upload, the install checks and the release draft run without the KMS role's session.
        drop = self.sign.index("printf '%s=\\n' AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN >> \"$GITHUB_ENV\"")
        self.assertLess(self.sign.index("scripts/release/publish_release.sh"), drop)
        self.assertLess(self.sign.index("scripts/release/sign_companion.sh"), drop)
        self.assertLess(drop, self.sign.index("attest-build-provenance"))
        self.assertEqual(self.sign.count("configure-aws-credentials"), 1)

    def test_the_upload_runs_in_a_job_that_cannot_take_the_signing_role(self):
        # #334: the role trusts tokens of the `release` environment (ci/aws/); the job that holds the R2 token is in
        # another environment, asks for no token and has no AWS step. It takes only the archive whose hash the sign
        # job gave as its output, and the job that can sign never holds the R2 token.
        self.assertIn("environment: release-upload\n", self.publish)
        self.assertIn("needs: sign\n", self.publish)
        for held in (
            "id-token:",
            "attestations:",
            "configure-aws-credentials",
            "NULAVIO_KMS",
            "NULAVIO_SIGNING",
            "publish_release.sh",
        ):
            self.assertNotIn(held, self.publish)
        self.assertIn("contents: write # the draft GitHub release", self.publish)
        self.assertNotIn("R2_", self.sign)
        self.assertIn("contents: read\n", self.sign)
        self.assertNotIn("release-upload", (ROOT / "ci" / "aws" / "release-signing-trust.json").read_text(encoding="utf-8"))
        self.assertIn("signed-sha256: ${{ steps.hand-over.outputs.sha256 }}", self.sign)
        check = self.publish.index("needs.sign.outputs.signed-sha256")
        self.assertLess(check, self.publish.index('tar -C "$RUNNER_TEMP" -xf'))
        self.assertLess(self.publish.index('tar -C "$RUNNER_TEMP" -xf'), self.publish.index("upload_repo.sh"))
        self.assertIn('[ -z "$SIGNED" ]', self.publish)  # no hash, no upload

    def test_an_older_run_cannot_upload_again(self):
        # A re-run of `publish` alone gets its old run's signed files and hash, and release-upload asks for no
        # approval: the job refuses a release older than any tagged, published or drafted one before the upload.
        check = self.publish.index("release_manifest.py not-older")
        self.assertLess(self.publish.index('tar -C "$RUNNER_TEMP" -xf'), check)
        self.assertLess(check, self.publish.index("upload_repo.sh"))
        step = self.publish[self.publish.rindex("- name:", 0, check) : check]
        # Every release, drafts included, the way the build job reads them; an assignment, so a failing gh fails the
        # step.
        self.assertIn("releases=$(gh api --paginate \"repos/$GITHUB_REPOSITORY/releases\" --jq '.[].tag_name')", step)
        # And what the bucket serves now: a newer upload whose run stopped before its draft has no tag and no draft.
        self.assertIn("served=$(curl -fsSL --proto '=https'", step)
        self.assertIn("sed -n 's/^URIs: //p' site/apt/nulavio.sources", step)
        self.assertIn('also=(--also "v$served")', step)
        # Without pipefail a failing curl leaves it empty: the form check stops the job then, and on anything that
        # is not <version>-<release>, which not-older would otherwise drop without a word.
        self.assertIn('if ! [[ "$served" =~ ^[0-9]+(\\.[0-9]+)+-[0-9]+(\\.[0-9]+)*$ ]]; then', step)
        self.assertNotIn("${{", step.split("run: |", 1)[1])

    def test_only_the_release_jobs_name_the_signing_and_upload_environments(self):
        # `release-upload` has no required reviewer (#334): any job on main that named it would get the R2 token
        # without the maintainer's approval (R60). So the jobs that may name either environment are listed.
        named = set()
        for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
            for job, name in job_environments(path.read_text(encoding="utf-8")):
                self.assertNotIn("${{", name, f"{path.name} {job}")  # a name from an expression could be either
                if name in ("release", "release-upload"):
                    named.add((path.name, job, name))
        self.assertEqual(
            named,
            {
                ("release.yml", "sign", "release"),
                ("release-signing-check.yml", "sign", "release"),
                ("release.yml", "publish", "release-upload"),
            },
        )

    def test_the_environment_reader_sees_both_forms_in_each_job(self):
        text = (
            "on: push\njobs:\n  a:\n    environment: release-upload # x\n    steps: []\n"
            "  b:\n    environment:\n      name: 'release-upload'\n      url: x\n"
            "  c:\n    environment: ${{ inputs.where }}\n  d:\n    steps: []\n"
        )
        self.assertEqual(job_environments(text), [("a", "release-upload"), ("b", "release-upload"), ("c", "${{")])

    def test_the_signing_role_trusts_the_two_signing_workflows_on_main_only(self):
        # #326: the subject carries job_workflow_ref (the repository's OIDC template), so a new workflow that names the
        # release environment cannot take the role; nor can a job of another environment or another branch.
        trust = json.loads((ROOT / "ci" / "aws" / "release-signing-trust.json").read_text(encoding="utf-8"))
        (statement,) = trust["Statement"]
        self.assertEqual(statement["Action"], "sts:AssumeRoleWithWebIdentity")
        self.assertEqual(set(statement["Condition"]), {"StringEquals"})  # no wildcard match
        condition = statement["Condition"]["StringEquals"]
        self.assertEqual(condition["token.actions.githubusercontent.com:aud"], "sts.amazonaws.com")
        prefix = "repo:nulavio@355057103/nulavio@1433296085:environment:release:job_workflow_ref:nulavio/nulavio/"
        self.assertEqual(
            condition["token.actions.githubusercontent.com:sub"],
            [f"{prefix}.github/workflows/{name}@refs/heads/main" for name in ("release.yml", "release-signing-check.yml")],
        )

    def test_the_release_is_drafted_from_the_runner_build(self):
        # That the published repositories install exactly the released version is run, not read, in
        # test_release_script_protections.CheckPublishedTest.
        self.assertIn("gh release create", self.publish)
        self.assertIn("--draft", self.publish)
        self.assertIn("NULAVIO_BUILD_PROFILE: runner", self.build)

    def test_the_companion_apk_is_rebuilt_attested_signed_through_kms_and_checked(self):
        # ADR 0014: built twice without secrets, attested; signed only in the approved publish job,
        # checked with apksigner against the published certificate, before publish_release.sh.
        self.assertIn("scripts/release/build_companion.sh", self.companion)
        # #286: the wrapper JAR is checked before it runs with id-token, and the tags are there for the version check.
        validate = self.companion.index("gradle/actions/wrapper-validation@")
        self.assertLess(validate, self.companion.index("scripts/release/build_companion.sh"))
        self.assertIn("fetch-depth: 0", self.companion)
        self.assertIn("companion_version.py", (RELEASE / "build_companion.sh").read_text(encoding="utf-8"))
        for held in ("secrets.", "environment:", "configure-aws-credentials", "KMS"):
            self.assertNotIn(held, self.companion)
        self.assertIn("attest-build-provenance", self.companion)
        self.assertIn('"$RUNNER_TEMP"/companion/nulavio-companion-*', self.sign)  # provenance checked
        aws = self.sign.index("configure-aws-credentials")
        sign = self.sign.index("scripts/release/sign_companion.sh")
        stage = self.sign.index("NULAVIO_COMPANION_APK=$apk")
        self.assertLess(aws, sign)
        self.assertLess(sign, stage)
        self.assertIn("--companion", self.sign)  # the notes name the APK and its certificate
        publish = (RELEASE / "publish_release.sh").read_text(encoding="utf-8")
        self.assertLess(publish.index('cp "$apk" "$apk.cdx.json" "$stage/github/"'), publish.index("sha256sum -- * >SHA256SUMS"))

    def test_the_bundle_is_checked_against_the_attested_archive_in_a_job_that_cannot_sign(self):
        # #324: built by Flathub's builder in a job with no attestation, parsed in a job with no token, and only its
        # hash compared next to the signing role. Left out when it differs.
        job = self.text[self.text.index("\n  flatpak-check:\n") : self.text.index("\n  companion:\n")]
        self.assertIn("scripts/release/check_flatpak_bundle.py --bundle", job)
        self.assertIn("contents: read", job)
        for held in ("id-token", "attestations", "environment:", "secrets."):
            self.assertNotIn(held, job)
        for later in (self.sign, self.publish):
            self.assertNotIn("check_flatpak_bundle.py", later)
            self.assertNotIn("apt_install.sh flatpak", later)
        compare = self.sign.index("needs.flatpak-check.outputs.bundle-sha256")
        self.assertLess(compare, self.sign.index("release_notes.py notes"))  # the notes name only an accepted bundle
        self.assertLess(compare, self.sign.index("configure-aws-credentials"))
        self.assertIn('rm -rf "$RUNNER_TEMP/flatpak-bundle"', self.sign[compare : self.sign.index("release_notes.py notes")])
        self.assertIn("-type f -name '*.flatpak'", job)  # one regular file, nothing else accepted
        self.assertIn("GITHUB_ACTIONS", (RELEASE / "publish_release.sh").read_text(encoding="utf-8"))
        self.assertIn("NULAVIO_FLATPAK_BUNDLE_SHA256=$ACCEPTED", self.sign)
        script = (RELEASE / "publish_release.sh").read_text(encoding="utf-8")
        self.assertLess(script.index("NULAVIO_FLATPAK_BUNDLE_SHA256"), script.index('"$repo/scripts/release/sign_repo.sh"'))
        self.assertLess(script.index("check_flatpak_bundle.py"), script.index('"$repo/scripts/release/sign_repo.sh"'))

    def test_the_flatpak_is_composed_and_linted_as_flathub_does(self):
        self.assertIn("--compose-url-policy=full", self.text)
        self.assertIn("flatpak-builder-lint org.flatpak.Builder repo repo", self.text)

    def test_the_bundle_is_attested_checked_and_signed_with_the_release(self):
        flatpak_job = self.text[self.text.index("\n  flatpak:\n") :]
        self.assertLess(flatpak_job.index("check_flatpak.sh"), flatpak_job.index("flatpak build-bundle"))
        sign = self.sign.index(
            "NULAVIO_FLATPAK_BUNDLE=$bundle NULAVIO_FLATPAK_BUNDLE_SHA256=$ACCEPTED NULAVIO_COMPANION_APK=$apk"
        )
        self.assertLess(sign, self.sign.index("subject-path: ${{ runner.temp }}/publish/github/*"))
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


class PrecheckTest(unittest.TestCase):
    """#430: `rehearse_release.sh --precheck` builds the variant whose Rust library can be read for the engine's
    networking check. It is not a release rehearsal, and nothing it leaves can be signed."""

    @classmethod
    def setUpClass(cls):
        cls.script = (RELEASE / "rehearse_release.sh").read_text(encoding="utf-8")

    def test_the_precheck_chooses_its_one_variant_itself(self):
        refusal = self.script.index("unset NULAVIO_MOZCONFIG_EXTRA: a variant build is never a release")
        chosen = self.script.index("if (( precheck )); then export NULAVIO_MOZCONFIG_EXTRA=mozconfig.no-lto; fi")
        self.assertLess(refusal, chosen)  # a caller's variant (a sanitised build) is refused first
        self.assertEqual(self.script.count("export NULAVIO_MOZCONFIG_EXTRA="), 1)

    def test_a_callers_variant_is_refused_in_a_precheck_too(self):
        for variant in ("mozconfig.asan", "mozconfig.no-lto"):
            out = subprocess.run(
                ["bash", str(RELEASE / "rehearse_release.sh"), "--precheck", "160.0", "/nonexistent"],
                env={**os.environ, "NULAVIO_MOZCONFIG_EXTRA": variant},
                capture_output=True,
                text=True,
            )
            self.assertEqual(out.returncode, 2, variant)
            self.assertIn("never a release", out.stderr)

    def test_the_library_is_read_right_after_the_build_and_before_the_tests(self):
        order = [self.script.index(text) for text in (
            'step build "$repo/scripts/build/build_nulavio.sh" "$version"',
            'step networking-check python3 -I "$repo/scripts/build/networking_check.py" "$version" --work "$work" --write',
            'step unit-tests python3 -I "$repo/tests/run.py" unit',
            'step integration-tests "$repo/scripts/release/run_integration.sh" "$install"',
            "step precheck-result precheck_result",
            'step rpm "$repo/scripts/release/make_rpm.sh" "$out/packages"',
        )]  # fmt: skip
        self.assertEqual(order, sorted(order))

    def test_a_precheck_stops_before_any_package_and_writes_no_manifest(self):
        after_tests = self.script[self.script.index("step precheck-result precheck_result") :]
        stop, packages = after_tests.index("    exit 0\nfi\n"), after_tests.index("step rpm ")
        self.assertLess(stop, packages)  # it leaves before the first packaging step
        self.assertLess(packages, after_tests.index("step manifest manifest"))  # which a release run reaches last
        # The steps between the tests and that exit make nothing a release could use.
        self.assertNotRegex(after_tests[:stop], r"step (rpm|deb|archive|sbom|manifest|signed-repository)")
        self.assertIn('rm -f "$out/manifest.json" "$out/precheck.json"', self.script)
        self.assertIn('"signable": False', self.script)
        self.assertRegex(self.script, r"if \(\( precheck \)\); then\n    # Nothing a release run could take")
        self.assertIn('mkdir -p "$out/packages"', self.script.split("else\n", 1)[1][:200])  # made for a rehearsal only

    def test_the_last_step_writes_a_result_that_is_not_a_manifest(self):
        # The pre-check's own code for its last step, run as the script runs it (the manifest step is tested the same way).
        match = re.search(
            r"precheck_result\(\) \{\n    python3 -I - \"\$out\" \"\$version\" \"\$repo\" \"\$work/firefox-\$version\" <<'EOF'\n"
            r"(.*?)\nEOF\n\}\n",
            self.script,
            re.S,
        )
        self.assertIsNotNone(match, "rehearse_release.sh must define precheck_result as a Python heredoc")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            writer, out, repo, tree = tmp / "writer.py", tmp / "out", tmp / "repo", tmp / "firefox-199.0"
            writer.write_text(match.group(1))
            for path in (out, repo / "browser" / "build", tree):
                path.mkdir(parents=True)
            git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
            subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
            subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
            (tree / ".nulavio-source-sha256").write_text("ab" * 32 + "\n")
            record = {"firefox": "199.0", "source_sha256": "ab" * 32, "result": "passed", "checked": "2026-11-17", "how": "read"}
            (repo / "browser" / "build" / "networking-check.json").write_text(json.dumps(record))

            def run() -> subprocess.CompletedProcess:
                return subprocess.run(
                    [sys.executable, "-I", str(writer), str(out), "199.0", str(repo), str(tree)], capture_output=True, text=True
                )

            done = run()
            self.assertEqual(done.returncode, 0, done.stderr)
            result = json.loads((out / "precheck.json").read_text())
            self.assertEqual((result["precheck"], result["signable"], result["variant"]), ("ok", False, "mozconfig.no-lto"))
            self.assertEqual((result["firefox"], result["source_sha256"]), ("199.0", "ab" * 32))
            self.assertEqual(result["networking_check"]["result"], "passed")
            self.assertRegex(result["nulavio_base_commit"], r"^[0-9a-f]{40}$")
            self.assertFalse((out / "manifest.json").exists())
            for key in ("packages", "sboms", "rehearsal", "engine_json"):  # what release_manifest.py asks of a manifest
                self.assertNotIn(key, result)
            # A record that is not this build's passing one: no result is written.
            for wrong in ({**record, "firefox": "198.0"}, {**record, "source_sha256": "cd" * 32}, {**record, "result": "failed"}):
                (out / "precheck.json").unlink(missing_ok=True)
                (repo / "browser" / "build" / "networking-check.json").write_text(json.dumps(wrong))
                done = run()
                self.assertNotEqual(done.returncode, 0, wrong)
                self.assertIn("not this build's passing record", done.stderr)
                self.assertFalse((out / "precheck.json").exists())

    def test_no_workflow_runs_a_precheck_and_one_builds_the_variant_to_read_it(self):
        # networking-check.yml builds the variant so that the reading is a workflow's and can be attested (#455).
        # Nothing else may: a variant is never a release, and nothing that packages, signs or publishes builds one.
        for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            text = workflow.read_text(encoding="utf-8")
            self.assertNotIn("--precheck", text, workflow.name)
            if workflow.name != "networking-check.yml":
                self.assertNotIn("mozconfig.no-lto", text, workflow.name)


class NetworkingAttestationTest(unittest.TestCase):
    """#455: a release is signed only when a workflow, not a committed record, says the Rust code was read."""

    @classmethod
    def setUpClass(cls):
        workflows = ROOT / ".github" / "workflows"
        cls.check = (workflows / "networking-check.yml").read_text(encoding="utf-8")
        cls.release = (workflows / "release.yml").read_text(encoding="utf-8")
        body = cls.release.split("\njobs:\n", 1)[1]
        cls.jobs = {m.group(1): m.group(2) for m in re.finditer(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", body, re.M | re.S)}
        cls.verify = '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/networking-check.yml" --source-ref refs/heads/main'

    def test_the_workflow_reads_its_own_build_and_attests_only_the_claim(self):
        text = self.check
        self.assertIn("NULAVIO_MOZCONFIG_EXTRA: mozconfig.no-lto", text)
        self.assertIn("if: github.ref == 'refs/heads/main'", text)
        self.assertRegex(
            text,
            r"(?m)^  push:\n    branches: \[main\]\n    paths:\n      - \"browser/build/\*\*\"\n      - \"browser/patches/\*\*\"",
        )
        steps = [text.index(part) for part in (
            'scripts/build/build_nulavio.sh "$firefox"',
            'scripts/build/networking_check.py "$firefox" --claim-out "$RUNNER_TEMP/claim/networking-claim.json"',
            'scripts/build/networking_check.py "$firefox" --expected-claim > "$RUNNER_TEMP/expected.json"',
            'cmp "$RUNNER_TEMP/claim/networking-claim.json" "$RUNNER_TEMP/expected.json"',
            "actions/attest-build-provenance@",
            'gh attestation verify "$RUNNER_TEMP/expected.json"',
        )]  # fmt: skip
        self.assertEqual(steps, sorted(steps))
        self.assertIn("subject-path: ${{ runner.temp }}/expected.json", text)  # bytes the attesting job made itself
        self.assertEqual(text.count("subject-path:"), 1)  # the claim, and nothing else
        # The job that runs the build cannot sign; the job that signs builds nothing.
        body = text.split("\njobs:\n", 1)[1]
        jobs = {m.group(1): m.group(2) for m in re.finditer(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", body, re.M | re.S)}
        self.assertEqual(sorted(jobs), ["attest", "read"])
        self.assertNotIn("id-token", jobs["read"])
        self.assertNotIn("attestations", jobs["read"])
        self.assertIn("blacksmith-16vcpu-ubuntu-2404", jobs["read"])
        self.assertIn("needs: read", jobs["attest"])
        self.assertIn("runs-on: ubuntu-24.04", jobs["attest"])
        for word in ("build_nulavio", "secrets.", "environment:", "podman"):
            self.assertNotIn(word, jobs["attest"], word)
        for name, job in jobs.items():
            self.assertIn("if: github.ref == 'refs/heads/main'", job, name)
        self.assertIn(self.verify, text)  # found here as the signing job will look for it
        commands = "\n".join(line for line in text.split("\njobs:\n", 1)[1].splitlines() if not line.lstrip().startswith("#"))
        self.assertNotIn("--write", commands)  # it changes nothing in the checkout
        self.assertNotIn("networking-check.json", commands)  # nor reads the committed record
        # Nothing a release could use leaves this workflow.
        for word in (
            "rehearse_release",
            "make_rpm",
            "make_deb",
            "make_archive",
            "publish_release",
            "sign_repo",
            "R2_",
            "AWS_",
            "manifest.json",
        ):
            self.assertNotIn(word, text, word)

    def test_no_other_workflow_shares_the_signer_workflows_name(self):
        # `gh attestation verify --signer-workflow` matches by prefix: another file whose name starts the same
        # way could sign a claim the release would take.
        names = [path.name for path in (ROOT / ".github" / "workflows").iterdir()]
        self.assertEqual([name for name in names if name.startswith("networking-check")], ["networking-check.yml"])

    def test_the_signing_job_requires_the_attestation_before_it_signs(self):
        sign = self.jobs["sign"]
        gate = sign.index(
            'release_manifest.py networking-claim "$RUNNER_TEMP/rehearsal" --repo . > "$RUNNER_TEMP/networking-claim.json"'
        )
        verify = sign.index('gh attestation verify "$RUNNER_TEMP/networking-claim.json"')
        role = sign.index("aws-actions/configure-aws-credentials@")
        self.assertLess(gate, verify)
        self.assertLess(verify, role)  # before the signing role is taken
        step = sign[gate : sign.index("- name:", gate)]  # this step alone
        self.assertIn(self.verify, step)
        self.assertIn("exit 1", step)
        self.assertNotIn("|| true", step)
        self.assertNotIn("continue-on-error", step)
        self.assertNotIn("accepted", step.replace('says "accepted"', ""))  # no way round it for an accepted record

    def test_the_build_job_only_gives_notice(self):
        build = self.jobs["build"]
        start = build.index("Is the Rust networking reading attested")
        step = build[start : build.index("- name:", start + 10)]
        self.assertIn("--expected-claim", step)
        self.assertIn(self.verify, step)
        self.assertIn("::warning", step)
        self.assertNotIn("exit 1", step)  # an urgent update runs the reading in parallel with the build

    def test_the_prebuild_tool_only_ever_prechecks(self):
        tool = (RELEASE / "autobuild.py").read_text(encoding="utf-8")
        self.assertIn('"rehearse_release.sh"), "--precheck", version, str(out)]', tool)
        self.assertEqual(tool.count('/ "rehearse_release.sh")'), 1)  # one call, and it is the pre-check
        self.assertNotIn("READY TO SIGN", tool)
        self.assertIn('"the pre-check left a manifest.json: it must not"', tool)


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
