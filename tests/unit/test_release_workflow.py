"""The CI release path: upload order to R2, the published-repository check, and the workflow's boundaries."""

from __future__ import annotations

import hashlib
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
# The same call with its argument boundaries, one JSON list a line: what the order assertions read.
python3 -I -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_AWS_LOG.json"
# A write that fails (a network error, a cancelled run): FAKE_AWS_FAIL_ON is a destination the call names.
case " $* " in
  *" ${FAKE_AWS_FAIL_ON:-no such destination} "*) exit 1 ;;
esac
# The bucket, for upload_repo.sh's check before it writes (#656): FAKE_AWS_LISTING is what list-objects-v2 prints
# (the empty listing's shape of aws-cli 2 otherwise), and a download copies from FAKE_AWS_BUCKET.
case " $* " in
  *" s3api list-objects-v2 "*)
    [ -z "${FAKE_AWS_LIST_FAILS:-}" ] || exit 254
    if [ -n "${FAKE_AWS_LISTING:-}" ]; then cat "$FAKE_AWS_LISTING"; else printf '{"RequestCharged": null}\\n'; fi
    ;;
  *" s3 cp s3://"*)
    shift 2
    cp "$FAKE_AWS_BUCKET/${3#s3://nulavio-packages/}" "$4"
    ;;
esac
"""


def hold(test, bucket: Path, key: str, data: str):
    """Put an object in the stand-in bucket, as an earlier run's upload, and list it."""
    (bucket / key).parent.mkdir(parents=True, exist_ok=True)
    (bucket / key).write_text(data)
    listing = test.tmp / "listing.json"
    entry = {"Key": key, "LastModified": "2026-11-20T10:00:00+00:00", "Size": len(data)}
    listing.write_text(json.dumps({"Contents": [entry], "RequestCharged": None}))
    test.env.update(FAKE_AWS_LISTING=str(listing), FAKE_AWS_BUCKET=str(bucket))


# #740: the signed pair under its revision's keys (<firefox>-<release>, the tag without its v: the release number
# alone starts again with each Firefox version), then the served pair, signature first as before. A publish that
# stops between the served repomd.xml.asc and repomd.xml leaves a matching signed pair that the runbook copies.
PAIR_THEN_SERVED = [
    ("repodata/repomd.xml.asc", "rpm/repodata/160.0-0.3/repomd.xml.asc"),
    ("repodata/repomd.xml", "rpm/repodata/160.0-0.3/repomd.xml"),
    ("repodata/repomd.xml.asc", "rpm/repodata/repomd.xml.asc"),
    ("repodata/repomd.xml", "rpm/repodata/repomd.xml"),
]


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class UploadRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="upload repo "))  # a space: the argument boundaries must hold
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
        self.assertEqual(len(calls), 6)
        for call in calls:
            self.assertIn("key=r2-key secret=r2-secret token=none region=auto checksums=when_required", call)
            self.assertIn("--endpoint-url https://acct.r2.cloudflarestorage.com s3", call)
            self.assertNotIn("--delete", call)
        # First what the bucket holds in the pool (#656), with s3api's own flags: --only-show-errors is s3's.
        self.assertIn("s3api list-objects-v2 --bucket nulavio-packages --prefix rpm/x86_64/ --output json", calls[0])
        self.assertNotIn("--only-show-errors", calls[0])
        calls = calls[1:]
        self.assertIn("sync", calls[0])
        self.assertIn("--exclude repodata/repomd.xml --exclude repodata/repomd.xml.asc", calls[0])
        self.assertEqual(self.writes()[1:], PAIR_THEN_SERVED)
        self.assertTrue(calls[-1].rstrip().endswith("s3://nulavio-packages/rpm/repodata/repomd.xml --only-show-errors"))

    def writes(self) -> list[tuple[str, str]]:
        """The writes to the bucket in order, as (staged file, key); a sync is ("sync", its prefix)."""
        found = []
        for call in self.uploads():
            if "sync" in call:
                found.append(("sync", call[call.index("sync") + 2].removeprefix("s3://nulavio-packages/")))
            else:
                source, destination = call[call.index("cp") + 1 : call.index("cp") + 3]
                found.append((Path(source).relative_to(self.repo).as_posix(),
                              destination.removeprefix("s3://nulavio-packages/")))  # fmt: skip
        return found

    def test_the_revision_pair_is_written_before_the_served_pair(self):
        out = self.run_upload()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.writes(), [("sync", "rpm/"), *PAIR_THEN_SERVED])

    def test_a_publish_stopped_before_the_served_repomd_leaves_the_revision_pair(self):
        # The state of #740: the served signature is the new one, the served repomd.xml the old one.
        self.env["FAKE_AWS_FAIL_ON"] = "s3://nulavio-packages/rpm/repodata/repomd.xml"
        out = self.run_upload()
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.writes()[1:], PAIR_THEN_SERVED)  # the last one is the write that failed

    def test_a_revision_pair_that_fails_to_upload_leaves_the_served_pair_alone(self):
        for key in ("rpm/repodata/160.0-0.3/repomd.xml.asc", "rpm/repodata/160.0-0.3/repomd.xml"):
            with self.subTest(key=key):
                self.log.unlink(missing_ok=True)
                self.env["FAKE_AWS_FAIL_ON"] = f"s3://nulavio-packages/{key}"
                out = self.run_upload()
                self.assertNotEqual(out.returncode, 0)
                self.assertEqual(self.writes()[-1][1], key)
                self.assertNotIn("rpm/repodata/repomd.xml.asc", [written for _, written in self.writes()])

    def test_a_three_part_firefox_version_names_its_revision(self):
        # The bucket's real package on 2026-11-26.
        (self.repo / "x86_64" / "nulavio-160.0-0.3.fc44.x86_64.rpm").rename(
            self.repo / "x86_64" / "nulavio-160.0.1-0.3.fc44.x86_64.rpm"
        )
        out = self.run_upload()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual([key for _, key in self.writes()[1:3]],
                         ["rpm/repodata/160.0.1-0.3/repomd.xml.asc", "rpm/repodata/160.0.1-0.3/repomd.xml"])  # fmt: skip

    def test_the_staged_packages_name_one_revision(self):
        # The revision goes into the keys: the packages' names must give one, in the form of the tag.
        for names in (["nulavio-160.0-0.3.fc44.x86_64.rpm", "nulavio-160.0-0.4.fc44.x86_64.rpm"],
                      ["nulavio-160.0-0.3.x86_64.rpm"], ["nulavio-160.0-0.3.fc44.noarch.rpm"],
                      ["nulavio-160.0-x.fc44.x86_64.rpm"], ["nulavio-160.0-0..3.fc44.x86_64.rpm"]):  # fmt: skip
            with self.subTest(names=names):
                for old in (self.repo / "x86_64").iterdir():
                    old.unlink()
                for name in names:
                    (self.repo / "x86_64" / name).write_text("x")
                self.log.unlink(missing_ok=True)
                out = self.run_upload()
                self.assertEqual(out.returncode, 2, out.stderr)
                self.assertIn("revision", out.stderr)
                self.assertFalse(self.log.exists())  # not even the listing

    def test_refuses_an_unsigned_repository(self):
        (self.repo / "repodata" / "repomd.xml.asc").unlink()
        out = self.run_upload()
        self.assertEqual(out.returncode, 2)
        self.assertIn("not a signed repository", out.stderr)
        self.assertFalse(self.log.exists())

    def uploads(self) -> list[list[str]]:
        """The calls that write to the bucket, each as its argument list."""
        log = self.log.with_name(self.log.name + ".json")
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [
            call for call in calls if "sync" in call or ("cp" in call and call[call.index("cp") + 1].startswith(f"{self.repo}/"))
        ]

    def test_a_package_the_bucket_holds_with_other_bytes_is_never_overwritten(self):
        # #656: a run that uploaded 160.0-0.3 and stopped before its draft left no tag and no draft; a fresh run that
        # built 160.0-0.3 again stops here, before anything of the repository is written.
        key = "rpm/x86_64/nulavio-160.0-0.3.fc44.x86_64.rpm"
        hold(self, self.tmp / "bucket", key, "the earlier run's build")
        out = self.run_upload()
        self.assertEqual(out.returncode, 3, out.stderr)
        self.assertIn(f"nulavio-packages/{key}, uploaded 2026-11-20T10:00:00+00:00, holds other bytes", out.stderr)
        self.assertIn("Re-run that run's publish job while its signed files last", out.stderr)
        self.assertIn('"After a failed publish"', out.stderr)
        self.assertEqual(self.uploads(), [])
        self.assertIn(f"s3 cp s3://nulavio-packages/{key} ", self.log.read_text())  # it was compared, by download

    def test_the_same_bytes_are_uploaded_again(self):
        # The same run's publish job, run again after a later step failed: the signed bytes are the ones in the bucket.
        hold(self, self.tmp / "bucket", "rpm/x86_64/nulavio-160.0-0.3.fc44.x86_64.rpm", "x")
        out = self.run_upload()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(self.uploads()), 5)
        # Another package in the pool (an older release) is neither downloaded nor in the way.
        hold(self, self.tmp / "bucket", "rpm/x86_64/nulavio-160.0-0.2.fc44.x86_64.rpm", "older")
        self.log.unlink()
        out = self.run_upload()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn(" cp s3://", self.log.read_text())

    def test_a_listing_that_fails_or_cannot_be_read_stops_the_upload(self):
        self.env["FAKE_AWS_LIST_FAILS"] = "1"
        out = self.run_upload()
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.uploads(), [])
        del self.env["FAKE_AWS_LIST_FAILS"]
        self.log.unlink()
        listing = self.tmp / "listing.json"
        listing.write_text("not json")
        self.env["FAKE_AWS_LISTING"] = str(listing)
        out = self.run_upload()
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.uploads(), [])

    def test_a_download_that_fails_stops_the_upload(self):
        hold(self, self.tmp / "bucket", "rpm/x86_64/nulavio-160.0-0.3.fc44.x86_64.rpm", "x")
        (self.tmp / "bucket" / "rpm" / "x86_64" / "nulavio-160.0-0.3.fc44.x86_64.rpm").unlink()
        out = self.run_upload()
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.uploads(), [])


# The runbook's upload token reaches aws alone (#742): every other stand-in records the process that saw it.
RUNBOOK_LEAK = """
if {"r2-key-id", "r2-secret"} & set(os.environ.values()):
    with open(os.environ["FAKE_LEAK_LOG"], "a") as leak:
        print("WHO", file=leak)
"""
RUNBOOK_CURL = """#!/bin/sh
# Stand-in for curl ... --max-filesize <n>M -o <file> <url>: the URL's path from FAKE_CDN when it holds it (a cached
# copy), else from FAKE_BUCKET; curl's 22 (a 404), or its 63 for a file past --max-filesize.
exec python3 -I -c '
import json, os, shutil, sys
LEAK
args = sys.argv[1:]
with open(os.environ["FAKE_CURL_LOG"], "a") as log:
    print(json.dumps(args), file=log)
if os.environ.get("FAKE_FSIZE_LOG"):
    import resource
    with open(os.environ["FAKE_FSIZE_LOG"], "a") as log:
        print(json.dumps(resource.getrlimit(resource.RLIMIT_FSIZE)), file=log)
path = args[-1].removeprefix("https://packages.nulavio.net/")
held = [os.path.join(root, path) for root in (os.environ.get("FAKE_CDN"), os.environ["FAKE_BUCKET"]) if root]
held = [src for src in held if os.path.isfile(src)]
if not held:
    sys.exit(22)
limit = args[args.index("--max-filesize") + 1] if "--max-filesize" in args else None
if limit and os.path.getsize(held[0]) > int(limit.removesuffix("M")) << 20:
    sys.exit(63)
shutil.copyfile(held[0], args[args.index("-o") + 1])
' "$@"
""".replace("LEAK", RUNBOOK_LEAK.replace("WHO", "curl"))
RUNBOOK_AWS = """#!/bin/sh
# Stand-in for aws <global options> s3 cp --only-show-errors <from> <to> on FAKE_BUCKET: a download, or an upload of
# a local file (which writes other bytes with FAKE_AWS_CORRUPT).
exec python3 -I -c '
import json, os, shutil, sys
names = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE",
         "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE", "AWS_REQUEST_CHECKSUM_CALCULATION")
args = sys.argv[1:]
with open(os.environ["FAKE_AWS_LOG"], "a") as log:
    print(json.dumps({"args": args, "env": {name: os.environ.get(name) for name in names}}), file=log)
if len(args) != 11 or args[6:9] != ["s3", "cp", "--only-show-errors"]:
    sys.exit(9)
def key(url):
    return os.path.join(os.environ["FAKE_BUCKET"], url.removeprefix("s3://nulavio-packages/"))
src, dst = args[9:]
if dst.startswith("s3://"):
    if os.environ.get("FAKE_AWS_CORRUPT"):
        with open(key(dst), "w") as f:
            f.write("corrupt")
    else:
        shutil.copyfile(src, key(dst))
elif os.path.isfile(key(src)):
    shutil.copyfile(key(src), dst)
else:
    sys.exit(1)
' "$@"
"""
RUNBOOK_ZSTD = """#!/bin/sh
# Stand-in for zstd -q -d -o <out> <in>: the stand-in primary file is not compressed.
exec python3 -I -c '
import os, shutil, sys
LEAK
args = sys.argv[1:]
if len(args) != 5 or args[:3] != ["-q", "-d", "-o"]:
    sys.exit(9)
shutil.copyfile(args[4], args[3])
' "$@"
""".replace("LEAK", RUNBOOK_LEAK.replace("WHO", "zstd"))
# Stand-in for release_manifest.py: a "signature" is "signed:" and the file's SHA-256; a "repomd.xml" is a label, then
# the primary file's key and its SHA-256 on the second line; a "primary file" is "nulavio <version>-<release>".
RUNBOOK_MANIFEST = """import hashlib, os, sys
LEAK
args = sys.argv[1:]
key = ["--key", "site/keys/nulavio-packages.asc", "--fingerprint", "298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1"]
def read(name):
    with open(name, "rb") as f:
        return f.read()
if args[0] == "verify-signed" and len(args) == 7 and args[3:] == key:
    sys.exit(0 if read(args[2]) == b"signed:" + hashlib.sha256(read(args[1])).hexdigest().encode() else 1)
elif args[0] == "dnf-primary" and len(args) == 2:
    print(read(args[1]).decode().splitlines()[1].split()[0])
elif args[0] == "dnf-compressed" and len(args) == 3:
    sys.exit(0 if hashlib.sha256(read(args[2])).hexdigest() == read(args[1]).decode().splitlines()[1].split()[1] else 1)
elif args[0] == "dnf-served" and len(args) == 3:
    print(read(args[2]).decode().removeprefix("nulavio "))
else:
    sys.exit(f"unexpected arguments: {args}")
""".replace("LEAK", RUNBOOK_LEAK.replace("WHO", "python3"))


def signed(text: str) -> tuple[bytes, bytes]:
    data = text.encode()
    return data, b"signed:" + hashlib.sha256(data).hexdigest().encode()


def repodata(label: str, listed: str) -> tuple[bytes, bytes, str, bytes]:
    """A stand-in dnf index: repomd.xml, its signature, the key of the primary file it names, and that file."""
    primary = f"nulavio {listed}".encode()
    digest = hashlib.sha256(primary).hexdigest()
    href = f"repodata/{digest}-primary.xml.zst"
    repomd, signature = signed(f"<repomd>{label}</repomd>\n{href} {digest}\n")
    return repomd, signature, href, primary


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class FailedPublishRunbookTest(unittest.TestCase):
    """build.md, "After a failed publish", state 4 (#740, #742): the block checks the revision's pair over HTTPS,
    then the live objects in R2 and the revision the primary file they name lists, and uploads those verified bytes
    onto the served keys only once every check passed; the upload token, taken at a prompt, reaches the aws calls
    alone; it then reads the served pair back from R2 and requires the public index to serve it and to list the
    revision; every download is bounded."""

    REVISION = "160.0.1-0.4"
    BUCKET = "s3://nulavio-packages/rpm/repodata"
    LOCAL = "<local>"

    @classmethod
    def setUpClass(cls):
        text = (ROOT / "docs" / "architecture" / "build.md").read_text(encoding="utf-8")
        state = text[text.index("4. **The build job stops at the signature of `repomd.xml`**") :]
        block = state[state.index("   ```sh\n") + len("   ```sh\n") : state.index("\n   ```\n")]
        cls.block = "\n".join(line.removeprefix("   ") for line in block.splitlines()) + "\n"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="runbook "))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = self.tmp / "repo"
        (self.repo / "scripts" / "release").mkdir(parents=True)
        (self.repo / "scripts" / "release" / "release_manifest.py").write_text(RUNBOOK_MANIFEST)
        (self.repo / "site" / "keys").mkdir(parents=True)
        (self.repo / "site" / "keys" / "nulavio-packages.asc").write_text("the release key")
        self.bucket = self.tmp / "bucket"
        self.cdn = self.tmp / "cdn"  # what the CDN still serves from its cache, when it holds the key
        self.rpm = self.bucket / "rpm"
        self.served = self.rpm / "repodata"
        (self.served / self.REVISION).mkdir(parents=True)
        self.new, new_sig, href, primary = repodata("the failed run's", self.REVISION)
        self.href, self.primary = href, primary
        self.old, _, old_href, old_primary = repodata("the run before", "160.0.1-0.3")
        (self.served / self.REVISION / "repomd.xml").write_bytes(self.new)
        (self.served / self.REVISION / "repomd.xml.asc").write_bytes(new_sig)
        (self.served / "repomd.xml.asc").write_bytes(new_sig)  # the publish stopped here
        (self.served / "repomd.xml").write_bytes(self.old)
        (self.rpm / href).write_bytes(primary)
        (self.rpm / old_href).write_bytes(old_primary)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name, body in (("curl", RUNBOOK_CURL), ("aws", RUNBOOK_AWS), ("zstd", RUNBOOK_ZSTD)):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(stat.S_IRWXU)
        self.log = self.tmp / "aws.json"
        self.curl_log = self.tmp / "curl.json"
        self.leak_log = self.tmp / "leak.txt"
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir()
        script = self.block.replace("<firefox>-<release>", self.REVISION).replace("<account id>", "acct")
        (self.tmp / "block.sh").write_text(script)
        self.env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_BUCKET": str(self.bucket),
                    "FAKE_CDN": str(self.cdn), "FAKE_AWS_LOG": str(self.log), "FAKE_CURL_LOG": str(self.curl_log),
                    "FAKE_LEAK_LOG": str(self.leak_log), "TMPDIR": str(self.scratch),
                    # What the maintainer's shell may hold: never used for the upload.
                    "AWS_SESSION_TOKEN": "sso-token", "AWS_PROFILE": "admin", "AWS_DEFAULT_PROFILE": "admin",
                    "AWS_ACCESS_KEY_ID": "maintainer-key", "AWS_SECRET_ACCESS_KEY": "maintainer-secret"}  # fmt: skip

    def run_block(self, *options: str, file_size_limit: str = ""):
        # file_size_limit: the soft and hard limit (in KiB, ulimit -f) of the shell the block is pasted into.
        shell = ["bash"]
        if file_size_limit:
            shell = ["bash", "-c", 'ulimit -f "$1" && exec bash "${@:2}"', "bash", file_size_limit]
        return subprocess.run([*shell, *options, str(self.tmp / "block.sh")], cwd=self.repo, env=self.env,
                              capture_output=True, text=True, input="r2-key-id\nr2-secret\n")  # fmt: skip

    def cache(self, key: str, data: bytes):
        (self.cdn / key).parent.mkdir(parents=True, exist_ok=True)
        (self.cdn / key).write_bytes(data)

    def calls(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def writes(self) -> list[dict]:
        return [call for call in self.calls() if call["args"][-1].startswith("s3://")]

    def curls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.curl_log.read_text().splitlines()] if self.curl_log.exists() else []

    def test_the_verified_pair_is_uploaded_in_the_upload_order_and_served(self):
        out = self.run_block()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"restored: dnf is served {self.REVISION}'s pair, which verifies and lists {self.REVISION}",
                      out.stdout)  # fmt: skip
        b, rev, local = self.BUCKET, self.REVISION, self.LOCAL
        self.assertEqual([[arg if arg.startswith("s3://") else local for arg in call["args"][9:]] for call in self.calls()], [
            [f"{b}/{rev}/repomd.xml", local], [f"{b}/{rev}/repomd.xml.asc", local], [f"{b}/repomd.xml.asc", local],
            [f"s3://nulavio-packages/rpm/{self.href}", local],  # the primary file it names, from R2 too
            [local, f"{b}/repomd.xml.asc"], [local, f"{b}/repomd.xml"],  # the signature first, as upload_repo.sh
            [f"{b}/repomd.xml.asc", local], [f"{b}/repomd.xml", local],
        ])  # fmt: skip
        self.assertEqual((self.served / "repomd.xml").read_bytes(), self.new)
        self.assertEqual((self.served / "repomd.xml.asc").read_bytes(),
                         (self.served / self.REVISION / "repomd.xml.asc").read_bytes())  # fmt: skip
        self.assertEqual(list(self.scratch.iterdir()), [])  # its temporary directory is gone

    def test_the_token_reaches_the_aws_calls_alone(self):
        out = self.run_block()
        self.assertEqual(out.returncode, 0, out.stderr)
        for call in self.calls():
            # I3: the token reaches aws through its environment, from the prompt; never as an argument.
            self.assertEqual(call["env"]["AWS_ACCESS_KEY_ID"], "r2-key-id")
            self.assertEqual(call["env"]["AWS_SECRET_ACCESS_KEY"], "r2-secret")
            self.assertNotIn("r2-secret", json.dumps(call["args"]))
            for inherited in ("AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
                self.assertIsNone(call["env"][inherited])
            self.assertEqual(call["env"]["AWS_CONFIG_FILE"], "/dev/null")
            self.assertEqual(call["env"]["AWS_SHARED_CREDENTIALS_FILE"], "/dev/null")
            self.assertEqual(call["env"]["AWS_REQUEST_CHECKSUM_CALCULATION"], "when_required")
        # curl, python3 and zstd ran after the prompt and never saw it.
        self.assertGreater(len(self.curls()), 3)
        self.assertFalse(self.leak_log.exists(), self.leak_log.read_text() if self.leak_log.exists() else "")

    def test_a_shell_left_in_allexport_does_not_export_the_token(self):
        # set -a, left on after sourcing an env file, would export what read assigns: the block turns it off.
        out = self.run_block("-a")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual({call["env"]["AWS_SECRET_ACCESS_KEY"] for call in self.calls()}, {"r2-secret"})
        self.assertFalse(self.leak_log.exists(), self.leak_log.read_text() if self.leak_log.exists() else "")

    def test_no_credential_is_written_on_a_command_line(self):
        self.assertNotRegex(self.block, r"AWS_(ACCESS_KEY_ID|SECRET_ACCESS_KEY)=")
        self.assertNotRegex(self.block, r"R2_(ACCESS_KEY_ID|SECRET_ACCESS_KEY)=")
        self.assertNotRegex(self.block, r"\benv\s")  # env NAME=value puts the value on env's command line
        self.assertIn("read -rsp", self.block)
        self.assertTrue(self.block.startswith("(\nset -euo pipefail\n"), self.block[:40])

    def test_every_download_is_bounded(self):
        out = self.run_block()
        self.assertEqual(out.returncode, 0, out.stderr)
        curls = self.curls()
        # The revision's pair and the served signature, then the served pair and the primary file it names.
        self.assertEqual(len(curls), 6)
        for args in curls:
            self.assertEqual(args[:10], ["-fsS", "--proto", "=https", "--retry", "3", "--max-time", "60",
                                         "--retry-max-time", "180", "--max-filesize"])  # fmt: skip
            self.assertEqual(args[10], "8M" if args[-1].endswith("-primary.xml.zst") else "1M", args[-1])
        for call in self.calls():
            self.assertEqual(call["args"][:9], ["--endpoint-url", "https://acct.r2.cloudflarestorage.com",
                                                "--cli-connect-timeout", "30", "--cli-read-timeout", "60",
                                                "s3", "cp", "--only-show-errors"])  # fmt: skip

    def test_every_file_the_block_writes_is_capped_at_32_mib(self):
        # ulimit -f: what aws reads from R2 and the decompressed primary file included.
        self.env["FAKE_FSIZE_LOG"] = str(self.tmp / "fsize.json")
        out = self.run_block()
        self.assertEqual(out.returncode, 0, out.stderr)
        for soft, _ in map(json.loads, (self.tmp / "fsize.json").read_text().splitlines()):
            self.assertNotEqual(soft, -1)  # RLIM_INFINITY
            self.assertLessEqual(soft, 32 << 20)

    def test_a_lower_file_size_limit_of_the_shell_stays(self):
        # A shell with a lower limit, hard and soft: raising it fails (or, as root, loosens it).
        self.env["FAKE_FSIZE_LOG"] = str(self.tmp / "fsize.json")
        out = self.run_block(file_size_limit="16384")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"restored: dnf is served {self.REVISION}'s pair", out.stdout)
        limits = {tuple(json.loads(line)) for line in (self.tmp / "fsize.json").read_text().splitlines()}
        self.assertEqual(limits, {(16 << 20, 16 << 20)})

    def test_a_download_past_its_size_limit_stops_it(self):
        big, big_sig, _, _ = repodata("x" * (1 << 20), self.REVISION)  # signed, and past 1 MiB
        (self.served / self.REVISION / "repomd.xml").write_bytes(big)
        (self.served / self.REVISION / "repomd.xml.asc").write_bytes(big_sig)
        (self.served / "repomd.xml.asc").write_bytes(big_sig)
        self.assert_stopped_before_any_copy(self.run_block())

    def assert_stopped_before_any_copy(self, out):
        self.assertNotEqual(out.returncode, 0)
        self.assertNotIn("restored", out.stdout)
        self.assertEqual(self.calls(), [])
        self.assertEqual((self.served / "repomd.xml").read_bytes(), self.old)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def assert_stopped_before_any_write(self, out):
        self.assertNotEqual(out.returncode, 0)
        self.assertNotIn("restored", out.stdout)
        self.assertNotEqual(self.calls(), [])  # it read R2
        self.assertEqual(self.writes(), [])
        self.assertEqual((self.served / "repomd.xml").read_bytes(), self.old)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_another_served_signature_stops_it_before_any_copy(self):
        # A pair of another revision would roll dnf back: cmp stops the block.
        (self.served / "repomd.xml.asc").write_bytes(signed("<repomd>another run's</repomd>")[1])
        self.assert_stopped_before_any_copy(self.run_block())

    def test_a_revision_pair_that_does_not_verify_stops_it_before_any_copy(self):
        (self.served / self.REVISION / "repomd.xml").write_bytes(b"<repomd>changed</repomd>")
        self.assert_stopped_before_any_copy(self.run_block())

    def test_a_missing_revision_pair_stops_it_before_any_copy(self):
        # A run made before #740 left none.
        shutil.rmtree(self.served / self.REVISION)
        self.assert_stopped_before_any_copy(self.run_block())

    def test_another_signature_in_r2_stops_it_while_the_cdn_shows_the_run_s(self):
        self.cache("rpm/repodata/repomd.xml.asc", (self.served / "repomd.xml.asc").read_bytes())
        (self.served / "repomd.xml.asc").write_bytes(signed("<repomd>another run's</repomd>")[1])
        self.assert_stopped_before_any_write(self.run_block())

    def test_a_revision_pair_in_r2_that_does_not_verify_stops_it_while_the_cdn_shows_a_good_one(self):
        self.cache(f"rpm/repodata/{self.REVISION}/repomd.xml", self.new)
        (self.served / self.REVISION / "repomd.xml").write_bytes(b"<repomd>changed</repomd>")
        self.assert_stopped_before_any_write(self.run_block())

    def assert_restored_in_r2_only(self, out):
        self.assertNotEqual(out.returncode, 0)  # the cleanup does not hide it
        self.assertIn(f"the bucket serves {self.REVISION}'s pair", out.stdout)
        self.assertNotIn("restored", out.stdout)
        self.assertEqual((self.served / "repomd.xml").read_bytes(), self.new)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_a_cdn_that_still_serves_the_old_index_fails_it_after_the_upload(self):
        self.cache("rpm/repodata/repomd.xml", self.old)
        self.assert_restored_in_r2_only(self.run_block())

    def test_a_served_index_that_lists_another_revision_fails_it(self):
        other, other_sig, href, primary = repodata("the failed run's, listing another", "160.0.1-0.3")
        (self.served / self.REVISION / "repomd.xml").write_bytes(other)
        (self.served / self.REVISION / "repomd.xml.asc").write_bytes(other_sig)
        (self.served / "repomd.xml.asc").write_bytes(other_sig)
        (self.rpm / href).write_bytes(primary)
        out = self.run_block()
        # It reads the primary file that pair names before it writes: an older index never reaches the served keys.
        self.assertIn("the dnf index lists nulavio 160.0.1-0.3", out.stdout)
        self.assert_stopped_before_any_write(out)

    def test_a_primary_file_past_its_size_limit_fails_it(self):
        # The site serves one past 8 MiB: R2's passed before the upload, so it fails at the public check.
        self.cache(f"rpm/{self.href}", b"x" * ((8 << 20) + 1))
        self.assert_restored_in_r2_only(self.run_block())

    def test_a_primary_file_missing_from_r2_stops_it_while_the_cdn_shows_it(self):
        self.cache(f"rpm/{self.href}", self.primary)
        (self.rpm / self.href).unlink()
        self.assert_stopped_before_any_write(self.run_block())

    def test_a_damaged_primary_file_in_r2_stops_it_while_the_cdn_shows_a_good_one(self):
        self.cache(f"rpm/{self.href}", self.primary)
        (self.rpm / self.href).write_bytes(b"nulavio 160.0.1-0.4, damaged")
        out = self.run_block()
        self.assertNotIn("the dnf index lists", out.stdout)  # refused by its checksum, before it is read
        self.assert_stopped_before_any_write(out)

    def test_a_served_pair_that_does_not_verify_after_the_copy_fails_it(self):
        self.env["FAKE_AWS_CORRUPT"] = "1"
        out = self.run_block()
        self.assertNotEqual(out.returncode, 0)  # the cleanup does not hide it
        self.assertNotIn("restored", out.stdout)
        self.assertNotIn("the bucket serves", out.stdout)
        self.assertEqual(list(self.scratch.iterdir()), [])


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
        self.assertEqual(len(calls), 5)
        self.assertIn("s3api list-objects-v2 --bucket nulavio-packages --prefix apt/pool/main/n/nulavio/ --output json",
                      calls[0])  # fmt: skip
        calls = calls[1:]
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

    def test_a_deb_the_bucket_holds_with_other_bytes_is_never_overwritten(self):  # #656
        key = "apt/pool/main/n/nulavio/nulavio_160.0-0.4_amd64.deb"
        hold(self, self.tmp / "bucket", key, "the earlier run's build")
        out = self.run_upload()
        self.assertEqual(out.returncode, 3, out.stderr)
        self.assertIn(f"nulavio-packages/{key}, uploaded 2026-11-20T10:00:00+00:00, holds other bytes", out.stderr)
        calls = self.log.read_text().splitlines()
        self.assertEqual([call for call in calls if " sync " in call or f" cp {self.repo}" in call], [])
        (self.tmp / "bucket" / key).write_text("x")  # the same bytes: uploaded again
        out = self.run_upload()
        self.assertEqual(out.returncode, 0, out.stderr)


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
        self.assertIn("needs: [build, companion]", self.sign)
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

    def test_the_build_takes_a_revision_above_the_served_one_and_builds_that_one(self):
        # #656: a run that uploaded and stopped before its draft left no tag and no draft, only the bucket's index.
        # The build job counts the served version, computes the revision once, and both the whats-new check and the
        # rehearsal use that one value.
        step = self.build[self.build.index("id: revision") : self.build.index("- name: What is new in this version")]
        script = step.split("run: |", 1)[1]
        self.assertIn("sed -n 's/^URIs: //p' site/apt/nulavio.sources", step)
        # #729: the APT version only from the Packages file that the Release text names by SHA-256 (apt-served),
        # fetched by that hash, and only once the release key's signature of InRelease verifies: one object, as apt
        # reads it, so a publish stopped mid-upload (plain Packages, Release or Release.gpg replaced, InRelease not
        # yet) leaves the build a consistent snapshot (the review of e665e9f7).
        # Every transfer is bounded in time as in size (the review of e665e9f7): 60 s each, 180 s with the retries.
        get = "get=(curl -fsSL --proto '=https' --retry 3 --max-time 60 --retry-max-time 180)"
        self.assertIn(get, step)
        for name, url in (("InRelease", "$apt/dists/stable/InRelease"), ("repomd.xml.asc", "$rpm/repodata/repomd.xml.asc")):
            self.assertIn(f"""\"${{get[@]}}" --max-filesize 1M -o "$RUNNER_TEMP/{name}" "{url}\"""", step)
        packages = 'packages=$(python3 -I scripts/release/release_manifest.py apt-packages "$RUNNER_TEMP/Release")'
        fetch_packages = '"${get[@]}" --max-filesize 8M -o "$RUNNER_TEMP/Packages" "$apt/dists/stable/$packages"'
        self.assertIn(packages, step)
        self.assertIn(fetch_packages, step)
        key = ' \\\n            --key site/keys/nulavio-packages.asc --fingerprint "$FINGERPRINT"'
        apt_check = ('python3 -I scripts/release/release_manifest.py verify-clearsigned "$RUNNER_TEMP/InRelease" '
                     '"$RUNNER_TEMP/Release"' + key)  # fmt: skip
        dnf_check = ('python3 -I scripts/release/release_manifest.py verify-signed "$RUNNER_TEMP/repomd.xml" '
                     '"$RUNNER_TEMP/repomd.xml.asc"' + key)  # fmt: skip
        self.assertIn(apt_check, step)
        self.assertIn(dnf_check, step)
        self.assertEqual(step.count("release_manifest.py verify-signed"), 1)
        self.assertEqual(step.count("release_manifest.py verify-clearsigned"), 1)
        # Neither the plain Packages object nor Release and Release.gpg as a pair: the ones an upload replaces first.
        self.assertNotIn("Release.gpg", script)
        self.assertNotIn("binary-amd64/Packages", script)
        self.assertLess(step.index(apt_check), step.index(packages))
        self.assertLess(step.index(packages), step.index(fetch_packages))
        self.assertIn("FINGERPRINT: 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1 # site/keys/nulavio-packages.asc", step)
        self.assertIn("command -v gpg >/dev/null || scripts/ci/apt_install.sh gnupg", step)
        served = (
            'served=$(python3 -I scripts/release/release_manifest.py apt-served "$RUNNER_TEMP/Release" "$RUNNER_TEMP/Packages")'
        )
        dnf_primary = 'primary=$(python3 -I scripts/release/release_manifest.py dnf-primary "$RUNNER_TEMP/repomd.xml")'
        self.assertIn(served, step)
        # Checked before anything reads the file: Release before apt-served, repomd.xml before dnf-primary.
        self.assertLess(step.index(apt_check), step.index(served))
        self.assertLess(step.index(dnf_check), step.index(dnf_primary))
        self.assertNotIn("awk", script)
        self.assertIn('if ! [[ "$served" =~ ^[0-9]+(\\.[0-9]+)+-[0-9]+(\\.[0-9]+)*$ ]]; then', step)
        # #723: and the dnf index, which is uploaded first and so may serve a revision the APT index does not: the
        # primary file its repomd.xml names, read from files so that a failed download or decompression stops the job.
        self.assertIn("sed -n 's/^baseurl=//p' site/rpm/nulavio.repo", step)
        self.assertIn('"${get[@]}" --max-filesize 1M -o "$RUNNER_TEMP/repomd.xml" "$rpm/repodata/repomd.xml"', step)
        self.assertIn(dnf_primary, step)
        self.assertIn('"${get[@]}" --max-filesize 8M -o "$RUNNER_TEMP/primary.xml.zst" "$rpm/$primary"', step)
        # The compressed file is checked against repomd.xml's checksum before zstd reads it (the review of e665e9f7).
        compressed = ('python3 -I scripts/release/release_manifest.py dnf-compressed "$RUNNER_TEMP/repomd.xml" '
                      '"$RUNNER_TEMP/primary.xml.zst"')  # fmt: skip
        self.assertIn(compressed, step)
        self.assertLess(step.index('primary.xml.zst" "$rpm/$primary"'), step.index(compressed))
        self.assertLess(step.index(compressed), step.index("zstd -q -d"))
        # Bounded (the review of f2a6c211), far above the real files of 2026-11-25 (1.5 to 6.3 kB): every download
        # stops at --max-filesize, and the decompression at the shell's file-size limit (blocks of 1 KiB), whose
        # failure stops this bash -e step.
        self.assertIn('(ulimit -f 32768 && zstd -q -d -f -o "$RUNNER_TEMP/primary.xml" "$RUNNER_TEMP/primary.xml.zst")',
                      step)  # fmt: skip
        commands = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
        self.assertEqual(commands.count("curl"), 1)  # the one bounded command line, in get
        self.assertEqual(step.count('"${get[@]}"'), 5)
        self.assertEqual(len(re.findall(r'"\$\{get\[@\]\}" --max-filesize [0-9]+M -o ', step)), 5)
        self.assertEqual(step.count("zstd -q -d"), 1)
        self.assertIn('dnf=$(python3 -I scripts/release/release_manifest.py dnf-served "$RUNNER_TEMP/repomd.xml" '
                      '"$RUNNER_TEMP/primary.xml")', step)  # fmt: skip
        self.assertIn('if ! [[ "$dnf" =~ ^[0-9]+(\\.[0-9]+)+-[0-9]+(\\.[0-9]+)*$ ]]; then', step)
        # No pipe: this shell has no pipefail, so a failed download or check must stop the job by itself.
        reads = script[script.index("apt=$(") : script.index("release=$(")]
        self.assertNotIn("|", reads.replace("||", ""))
        self.assertIn('release=$(python3 -I scripts/release/release_manifest.py next-release "$FIREFOX" --also "v$served" '
                      '--also "v$dnf")', step)  # fmt: skip
        self.assertIn('echo "release=$release" >> "$GITHUB_OUTPUT"', step)
        self.assertNotIn("${{", step.split("run: |", 1)[1])
        self.assertEqual(self.build.count("next-release"), 1)
        self.assertLess(self.build.index("id: revision"), self.build.index("whats_new.py require"))
        self.assertIn('RELEASE: ${{ steps.revision.outputs.release }}\n        run: python3 -I scripts/release/whats_new.py '
                      'require "$FIREFOX-$RELEASE"', self.build)  # fmt: skip
        start = self.build.index("- name: Rehearse the release")
        rehearse = self.build[start : self.build.index("run: scripts/release/rehearse_release.sh", start)]
        self.assertIn("NULAVIO_RELEASE: ${{ steps.revision.outputs.release }}", rehearse)

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
        # #324: built by Flathub's builder in a job with no attestation, parsed in a job with no token.
        job = self.text[self.text.index("\n  flatpak-check:\n") : self.text.index("\n  companion:\n")]
        self.assertIn("scripts/release/check_flatpak_bundle.py --bundle", job)
        self.assertIn("contents: read", job)
        for held in ("id-token", "attestations", "environment:", "secrets."):
            self.assertNotIn(held, job)
        for later in (self.sign, self.publish):
            self.assertNotIn("check_flatpak_bundle.py", later)
            self.assertNotIn("apt_install.sh flatpak", later)
        self.assertIn("-type f -name '*.flatpak'", job)  # one regular file, nothing else accepted

    def test_the_bundle_is_never_a_release_asset(self):
        # #467: the bundle never updates itself (R75), so a release does not offer it until Flathub (#88-#91). The
        # flatpak jobs stay as a check of Flathub's build; signing neither waits for them nor takes their bundle.
        for job in (self.sign, self.publish):
            for name in ("flatpak-bundle", "NULAVIO_FLATPAK_BUNDLE", "--flatpak ", "needs.flatpak", ".flatpak'"):
                with self.subTest(name=name):
                    self.assertNotIn(name, job)
        self.assertNotIn("flatpak", self.sign.split("steps:", 1)[0].split("needs:", 1)[1].split("\n", 1)[0])

    def test_the_flatpak_is_composed_and_linted_as_flathub_does(self):
        self.assertIn("--compose-url-policy=full", self.text)
        self.assertIn("flatpak-builder-lint org.flatpak.Builder repo repo", self.text)

    def test_a_bundle_given_by_hand_is_still_checked_before_signing(self):
        # publish_release.sh keeps NULAVIO_FLATPAK_BUNDLE for a run by hand (#467): the bundle is checked against the
        # archive, or by the hash a check accepted, before anything is signed, refused in CI without that hash, and
        # covered by SHA256SUMS.
        script = (RELEASE / "publish_release.sh").read_text(encoding="utf-8")
        signing = script.index('"$repo/scripts/release/sign_repo.sh"')
        self.assertLess(script.index("if [[ -n ${NULAVIO_FLATPAK_BUNDLE_SHA256"), signing)  # the compare, not a comment
        self.assertLess(script.index("check_flatpak_bundle.py"), signing)
        self.assertIn("GITHUB_ACTIONS", script)
        self.assertLess(script.index('cp "$bundle" "$stage/github/"'), script.index("sha256sum -- * >SHA256SUMS"))
        self.assertIn('"nulavio-${tag#v}.x86_64.flatpak"', script)

    def test_the_flatpak_is_started_before_it_is_bundled(self):
        flatpak_job = self.text[self.text.index("\n  flatpak:\n") :]
        self.assertLess(flatpak_job.index("check_flatpak.sh"), flatpak_job.index("flatpak build-bundle"))


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

    def test_the_sanitised_build_keeps_the_content_sandbox(self):
        # #490: the engine's configure turns the sandbox off for an AddressSanitizer build on Linux; the variant asks for
        # it, and test_engine_slice 04 checks it there like in every other run (no skip).
        asan = (ROOT / "browser" / "build" / "mozconfig.asan").read_text(encoding="utf-8")
        self.assertRegex(asan, r"(?m)^ac_add_options\s+--enable-sandbox\s*$")
        # the trial input is gone, so no run can build the variant without it
        text = (ROOT / ".github" / "workflows" / "asan.yml").read_text(encoding="utf-8")
        self.assertNotIn("inputs.sandbox", text)
        self.assertNotIn("--enable-sandbox' >>", text)
        # the sandbox test has no skip of its own
        engine = (ROOT / "tests" / "integration" / "test_engine_slice.py").read_text(encoding="utf-8")
        start = engine.index("    def test_04_content_processes_are_sandboxed(self):")
        end = engine.index("\n    def ", start + 1)
        self.assertNotIn("skipTest(", engine[start:end])

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
        # Only an attestation made on a GitHub-hosted runner counts: the attesting job, never the build machine.
        cls.hosted = re.compile(re.escape(cls.verify) + r" \\\n +--deny-self-hosted-runners ")

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
            'scripts/build/networking_check.py "$firefox" --expected-claim \\\n',
            '--compiler-from "$RUNNER_TEMP/claim/networking-claim.json" > "$RUNNER_TEMP/expected.json"',
            'cmp "$RUNNER_TEMP/claim/networking-claim.json" "$RUNNER_TEMP/expected.json"',
            "actions/attest-build-provenance@",
            'gh attestation verify "$RUNNER_TEMP/expected.json"',
        )]  # fmt: skip
        self.assertEqual(steps, sorted(steps))
        self.assertIn("subject-path: ${{ runner.temp }}/expected.json", text)  # bytes the attesting job made itself
        self.assertIn('      - "scripts/build/**"', text)  # what makes the reading is in the claim, so it starts a run too
        self.assertIn('      - ".github/workflows/networking-check.yml"', text)
        self.assertIn('      - "ci/containers/fedora-build.Containerfile"', text)
        # Every file whose digest is in the claim starts a run when it changes on main.
        sys.path.insert(0, str(ROOT / "scripts" / "build"))
        import networking_check

        watched = re.findall(r'(?m)^      - "([^"]+)"', text.split("\n  workflow_dispatch:", 1)[0])
        for path in networking_check.READ_WITH:
            self.assertTrue(any(path == w or (w.endswith("/**") and path.startswith(w[:-2])) for w in watched), path)
        for path in (networking_check.MOZCONFIG, networking_check.VARIANT, networking_check.SERIES):
            self.assertTrue(any(w.endswith("/**") and path.startswith(w[:-2]) for w in watched), path)
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
        self.assertRegex(text, self.hosted)  # found here as the signing job will look for it
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
        self.assertRegex(step, self.hosted)
        self.assertIn("exit 1", step)
        self.assertNotIn("|| true", step)
        self.assertNotIn("continue-on-error", step)
        self.assertNotIn("accepted", step.replace('says "accepted"', ""))  # no way round it for an accepted record

    def test_the_build_job_only_gives_notice(self):
        build = self.jobs["build"]
        start = build.index("Is the Rust networking reading attested")
        step = build[start : build.index("- name:", start + 10)]
        # After the build: the claim names the Rust compiler the build used (#472), which nothing knows before it.
        self.assertLess(build.index('scripts/release/rehearse_release.sh "$FIREFOX" "$RUNNER_TEMP/rehearsal"'), start)
        self.assertIn('release_manifest.py networking-claim "$RUNNER_TEMP/rehearsal" --repo .', step)
        self.assertRegex(step, self.hosted)
        self.assertIn("::warning", step)
        self.assertNotIn("exit 1", step)  # a rehearsal is not stopped by it; the signing job is where it is required
        self.assertNotIn("--expected-claim", build)  # nothing asks before the build, when the compiler is not known

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
