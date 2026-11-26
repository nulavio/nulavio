"""Only what a finished rehearsal of reviewed history checked can be signed and published."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import release_manifest  # noqa: E402
import networking_fixture  # noqa: E402
from verify_firefox_release import SIGNING_SUBKEYS  # noqa: E402

RPM = "packages/x86_64/nulavio-159.0.1-0.1.fc44.x86_64.rpm"
DEB = "packages/nulavio_159.0.1-0.1_amd64.deb"
SOURCE = "b5fe407199685f8bddf3b2c81feb8b805429e6f3d307c9430f53456f85b6e063"
# The Rust compiler the manifest says built the release (#472).
COMPILER = {"rustc_version": "1.99.0", "rustc_commit": "b940084d7eb6a299eb4bfeb8e34901bc051e7ac4"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# The dnf index as createrepo_c writes it (sign_repo.sh), cut down from the bucket's on 2026-11-25 (#723).
PRIMARY_HREF = "repodata/" + "8f064b7e2db78c916db1cee8fc66d805f476b50ccc2c7d4a310869b0d6b6ed14" + "-primary.xml.zst"


def dnf_primary_xml(*packages: tuple[str, str, str]) -> bytes:
    entries = "".join(
        f'<package type="rpm">\n  <name>{name}</name>\n  <arch>x86_64</arch>\n  <version epoch="0" ver="{ver}" rel="{rel}"/>\n'
        f'  <location href="x86_64/{name}-{ver}-{rel}.x86_64.rpm"/>\n  <format>\n'
        f'    <rpm:provides><rpm:entry name="{name}" flags="EQ" epoch="0" ver="9.9" rel="9.9"/></rpm:provides>\n'
        f"  </format>\n</package>\n"
        for name, ver, rel in packages
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<metadata xmlns="http://linux.duke.edu/metadata/common" '
        f'xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="{len(packages)}">\n{entries}</metadata>\n'
    ).encode()


def dnf_repomd(primary: bytes, href: str = PRIMARY_HREF) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<repomd xmlns="http://linux.duke.edu/metadata/repo" '
        'xmlns:rpm="http://linux.duke.edu/metadata/rpm">\n  <revision>1795642880</revision>\n'
        '  <data type="primary">\n    <checksum type="sha256">8f064b7e</checksum>\n'
        f'    <open-checksum type="sha256">{hashlib.sha256(primary).hexdigest()}</open-checksum>\n'
        f'    <location href="{href}"/>\n  </data>\n'
        '  <data type="other">\n    <location href="repodata/0-other.xml.zst"/>\n  </data>\n</repomd>\n'
    ).encode()


class ReleaseManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nulavio-manifest-test-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
        # The base commit says the pinned release passed the networking check, read with its own mozconfig,
        # variant and patch stack (#430).
        self.record = self.repo / release_manifest.NETWORKING_RECORD
        networking_fixture.write_inputs(self.repo)
        networking_fixture.write_record(self.repo, "159.0.1", SOURCE)
        subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "base"], check=True)
        self.base = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run([*git, "checkout", "-q", "-b", "side"], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "unreviewed"], check=True)
        self.side = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        self.out = self.tmp / "rehearsal"
        for name, body in ((RPM, b"rpm"), (DEB, b"deb"), (RPM + ".cdx.json", b"{}"), (DEB + ".cdx.json", b"{}")):
            (self.out / name).parent.mkdir(parents=True, exist_ok=True)
            (self.out / name).write_bytes(body)
        self.manifest = {
            "firefox": "159.0.1",
            "source_sha256": SOURCE,
            "signing_subkey": min(SIGNING_SUBKEYS),
            "compiled_with": dict(COMPILER),
            "engine_json": {"firefox": "159.0.1", "source_sha256": SOURCE},
            "nulavio_base_commit": self.base,
            "worktree_diff_sha256": hashlib.sha256(b"").hexdigest(),
            "untracked": [],
            "packages": [{"file": f, "sha256": digest(self.out / f)} for f in (RPM, DEB)],
            "sboms": [{"file": f + ".cdx.json", "sha256": digest(self.out / (f + ".cdx.json"))} for f in (RPM, DEB)],
            "rehearsal": "ok",
        }
        self.write()

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)], check=True)

    def write(self, notes: bool = True):
        # The packages carry their own version's notes (#198) unless a test says otherwise.
        self.manifest.pop("whats_new", None)
        if notes:
            try:
                self.manifest["whats_new"] = release_manifest.tag(self.manifest)[0].removeprefix("v")
            except release_manifest.ManifestError:
                pass  # a manifest the test means to be refused for something else
        (self.out / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def verify(self):
        return release_manifest.verify(self.out, self.repo, "main")

    def refused(self, fragment: str):
        with self.assertRaises(release_manifest.ManifestError) as caught:
            self.verify()
        self.assertIn(fragment, str(caught.exception))

    def test_a_clean_rehearsal_gives_the_tag_and_the_files(self):
        info = self.verify()
        self.assertEqual(info["tag"], "v159.0.1-0.1")
        self.assertEqual(info["rpms"], [RPM])
        self.assertEqual(info["commit"], self.base)

    def test_packages_without_their_own_versions_notes_are_refused(self):
        # A security pre-build made before packaging/whats-new/<version>.json existed packs no notes (#198).
        self.write(notes=False)
        self.refused("carry no notes")
        tag = self.verify_tag_with_notes()
        self.manifest["whats_new"] = "159.0.1-0.0"  # another version's
        (self.out / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        self.refused(f"no notes for {tag}")

    def verify_tag_with_notes(self) -> str:
        self.write()
        return self.verify()["tag"].removeprefix("v")

    def test_uncommitted_or_untracked_changes_are_refused(self):
        self.manifest["worktree_diff_sha256"] = "0" * 64
        self.write()
        self.refused("uncommitted")
        self.manifest["worktree_diff_sha256"] = hashlib.sha256(b"").hexdigest()
        self.manifest["untracked"] = ["browser/build/mozconfig.local"]
        self.write()
        self.refused("untracked")

    def test_an_unfinished_rehearsal_or_a_mismatched_engine_pin_is_refused(self):
        self.manifest["engine_json"]["source_sha256"] = "1" * 64
        self.write()
        self.refused("engine.json")
        self.manifest["engine_json"]["source_sha256"] = SOURCE
        self.manifest["rehearsal"] = "failed"
        self.write()
        self.refused("did not finish")

    def commit_record(self, record: dict | None, branch: str = "main") -> str:
        """A new commit on the branch with this record (None: without the file); the manifest is built from it."""
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "checkout", "-q", branch], check=True)
        if record is None:
            subprocess.run([*git, "rm", "-q", release_manifest.NETWORKING_RECORD], check=True)
        else:
            self.record.parent.mkdir(parents=True, exist_ok=True)
            self.record.write_text(json.dumps(record) if isinstance(record, dict) else record)
            subprocess.run([*git, "add", "."], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "record"], check=True)
        head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        self.manifest["nulavio_base_commit"] = head
        self.write()
        return head

    def test_a_release_nobody_checked_for_networking_in_rust_is_refused(self):
        good = networking_fixture.record(self.repo, "159.0.1", SOURCE)
        for record, said in (
            ({**good, "firefox": "159.0"}, "is about Firefox 159.0, not the 159.0.1"),  # the pin moved, the record did not
            ({**good, "source_sha256": "1" * 64}, "nobody checked its Rust code"),
            ({**good, "result": "failed"}, "says 'failed'"),
            ({**good, "result": "accepted"}, "says 'accepted'"),  # accepted by nobody in particular
            ({**good, "result": "accepted", "accepted_in": "the maintainer said so"}, "says 'accepted'"),
            ("not json", "cannot be read at the base commit"),
            (None, "cannot be read at the base commit"),
        ):
            with self.subTest(record=record):
                self.commit_record(record)
                self.refused(said)
        self.commit_record({**good, "result": "accepted", "accepted_in": "#430"})
        self.assertEqual(self.verify()["firefox"], "159.0.1")
        self.commit_record(good)
        self.assertEqual(self.verify()["firefox"], "159.0.1")

    def test_a_patch_or_a_mozconfig_changed_since_the_reading_asks_for_a_new_one(self):
        said = "is for another mozconfig or patch stack"
        good = networking_fixture.record(self.repo, "159.0.1", SOURCE)
        for change in (
            lambda: (self.repo / "browser/patches/0001-example.patch").write_text("--- a/dom/y.cpp\n+++ b/dom/y.cpp\n"),
            lambda: (self.repo / "browser/build/mozconfig").write_text("ac_add_options --enable-lto=cross\n"),
            lambda: (self.repo / "browser/build/mozconfig.no-lto").write_text("ac_add_options --enable-debug\n"),
        ):
            with self.subTest(change=change):
                change()
                self.commit_record(good)  # the files changed, the record is the one read before
                self.refused(said)
                self.commit_record(networking_fixture.record(self.repo, "159.0.1", SOURCE))  # read again
                self.assertEqual(self.verify()["firefox"], "159.0.1")
                good = networking_fixture.record(self.repo, "159.0.1", SOURCE)
        without = {key: value for key, value in good.items() if key != "built_with"}
        self.commit_record(without)  # a record from before the binding says nothing about what it was read with
        self.refused(said)
        accepted = {**good, "result": "accepted", "accepted_in": "#430"}
        self.commit_record({**without, "result": "accepted", "accepted_in": "#430"})  # accepted for no inputs in particular
        self.refused(said)
        self.commit_record(accepted)  # accepted for this mozconfig, variant and patch stack
        self.assertEqual(self.verify()["firefox"], "159.0.1")
        (self.repo / "browser/patches/0001-example.patch").write_text("--- a/dom/z.cpp\n+++ b/dom/z.cpp\n")
        self.commit_record(accepted)  # a patch changed since it was accepted
        self.refused(said)

    def commit_reader(self, text: str) -> None:
        """The reader, the build script and the workflow at the base commit (what the claim's read_with names)."""
        for path in networking_fixture.networking_check.READ_WITH:
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(text + path + "\n")
        self.commit_record(json.loads(self.record.read_text()))

    def test_a_base_commit_that_is_not_a_full_hash_is_refused_before_git_sees_it(self):
        for value in ("--output=/tmp/x", "main", "HEAD~1", self.base[:12], "", None, 7):
            with self.subTest(value=value):
                self.manifest["nulavio_base_commit"] = value
                self.write()
                self.refused("not a full commit hash")
                with self.assertRaises(release_manifest.ManifestError) as caught:
                    release_manifest.networking_claim(self.out, self.repo)
                self.assertIn("not a full commit hash", str(caught.exception))

    def test_a_base_commit_without_the_reader_gives_no_claim(self):
        with self.assertRaises(release_manifest.ManifestError) as caught:
            release_manifest.networking_claim(self.out, self.repo)
        self.assertIn("cannot be read at", str(caught.exception))

    def test_the_claim_comes_from_the_manifest_and_the_base_commit_never_from_the_record(self):
        nc = networking_fixture.networking_check
        self.commit_reader("# the reader\n")
        expected = nc.claim("159.0.1", SOURCE, nc.repository_inputs(self.repo), nc.repository_reader(self.repo), COMPILER)
        self.assertEqual(release_manifest.networking_claim(self.out, self.repo), expected)
        # A reader changed at the base commit is another claim.
        self.commit_reader("# the reader, tightened\n")
        self.assertNotEqual(release_manifest.networking_claim(self.out, self.repo), expected)
        expected = nc.claim("159.0.1", SOURCE, nc.repository_inputs(self.repo), nc.repository_reader(self.repo), COMPILER)
        # A record that says "accepted", or names another release, changes nothing in the claim.
        self.commit_record({"firefox": "1.0", "source_sha256": "0" * 64, "result": "accepted", "accepted_in": "#1"})
        self.assertEqual(release_manifest.networking_claim(self.out, self.repo), expected)
        # A patch changed at the base commit is another claim: the old attestation no longer fits.
        (self.repo / "browser/patches/0001-example.patch").write_text("--- a/dom/y.cpp\n+++ b/dom/y.cpp\n")
        self.commit_record(networking_fixture.record(self.repo, "159.0.1", SOURCE))
        self.assertNotEqual(release_manifest.networking_claim(self.out, self.repo), expected)
        # The command prints those bytes and nothing else.
        done = subprocess.run(
            [sys.executable, "-I", str(ROOT / "scripts" / "release" / "release_manifest.py"), "networking-claim", str(self.out),
             "--repo", str(self.repo)],
            capture_output=True,
        )  # fmt: skip
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, release_manifest.networking_claim(self.out, self.repo))

    def test_a_release_built_with_another_rust_compiler_asks_for_another_claim(self):
        # #472: the reading and the release are two builds, and the container's package manager may have served
        # two compilers. The claim names the one the release build used, from its manifest.
        self.commit_reader("# the reader\n")
        attested = release_manifest.networking_claim(self.out, self.repo)  # what a reading with COMPILER attested
        self.assertEqual(json.loads(attested)["compiled_with"], COMPILER)
        for other in ({**COMPILER, "rustc_version": "1.99.1"}, {**COMPILER, "rustc_commit": "0" * 40}):
            with self.subTest(compiled_with=other):
                self.manifest["compiled_with"] = other
                self.write()
                needed = release_manifest.networking_claim(self.out, self.repo)
                self.assertNotEqual(needed, attested)
                self.assertEqual(json.loads(needed)["compiled_with"], other)
        # A manifest that does not say, or says it in a form rustc does not report, gives no claim: nothing to sign on.
        for bad in (None, {}, {"rustc_version": "1.99.0"}, {**COMPILER, "rustc_version": "$(id)"}, "rustc 1.99.0"):
            with self.subTest(compiled_with=bad):
                self.manifest["compiled_with"] = bad
                self.write()
                with self.assertRaises(release_manifest.ManifestError) as caught:
                    release_manifest.networking_claim(self.out, self.repo)
                self.assertIn("Rust compiler", str(caught.exception))
        del self.manifest["compiled_with"]  # a rehearsal made before #472
        self.write()
        with self.assertRaises(release_manifest.ManifestError) as caught:
            release_manifest.networking_claim(self.out, self.repo)
        self.assertIn("rehearse again", str(caught.exception))

    def test_the_record_is_read_at_the_base_commit_not_in_the_working_tree(self):
        self.commit_record(networking_fixture.record(self.repo, "159.0", SOURCE))
        self.record.write_text(json.dumps(networking_fixture.record(self.repo, "159.0.1", SOURCE)))  # not committed
        self.refused("is about Firefox 159.0")

    def test_a_package_changed_after_the_rehearsal_is_refused(self):
        (self.out / RPM).write_bytes(b"rpm, rebuilt by hand")
        self.refused("changed since the rehearsal")

    def test_a_base_commit_off_the_reviewed_branch_is_refused(self):
        self.manifest["nulavio_base_commit"] = self.side
        self.write()
        self.refused("is not on main")

    def published(self, version: str):
        (self.repo / "packaging").mkdir(exist_ok=True)
        (self.repo / "packaging" / "release.json").write_text(json.dumps({"version": version}), encoding="utf-8")

    def test_a_release_not_newer_than_the_published_one_is_refused(self):
        # dnf upgrades only to a higher version-release: the same number never reaches installed copies.
        self.published("159.0.1-0.1")
        self.refused("not newer than the published 159.0.1-0.1")
        self.published("160.0-0.1")
        self.refused("not newer")
        self.published("159.0.1-0.0.9")
        self.assertEqual(self.verify()["tag"], "v159.0.1-0.1")

    def test_an_existing_tag_is_refused(self):
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "tag", "v159.0.1-0.1", self.base], check=True)
        self.refused("already exists")

    def test_the_next_release_counts_up_from_the_published_one(self):
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo), "0.1")
        self.published("159.0.1-0.1")
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo), "0.2")
        self.assertEqual(release_manifest.next_release("160.0", self.repo), "0.1")
        self.published("159.0.1-0.9")
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo), "0.10")
        self.published("160.0-0.10")
        self.refused("not newer")  # the Firefox version is compared first

    def test_a_revision_the_bucket_serves_is_taken_though_nothing_tagged_or_drafted_it(self):
        # #656: run A uploaded 159.0.1-0.2 and stopped before its draft; the build job of run B names the version the
        # bucket's APT index serves, and B builds 0.3 instead of uploading other bytes as 0.2.
        subprocess.run(["git", "-C", str(self.repo), "tag", "v159.0.1-0.1", self.base], check=True)
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo), "0.2")  # what B picked before #656
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo, ["v159.0.1-0.2"]), "0.3")
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo, ["v159.0.1-0.1"]), "0.2")  # served = tagged
        # Another Firefox version, or anything that is not a release tag, is not counted.
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo, ["v160.0-0.7", "159.0.1-0.9", "x"]), "0.2")
        self.assertEqual(release_manifest.next_release("160.0", self.repo, ["v159.0.1-0.2"]), "0.1")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = release_manifest.main(["next-release", "159.0.1", "--repo", str(self.repo), "--also", "v159.0.1-0.2"])
        self.assertEqual((code, out.getvalue()), (0, "0.3\n"))
        release_manifest.check_newer("v159.0.1-0.3", self.repo)  # and the sign job's verify takes it

    def test_a_revision_only_the_dnf_index_serves_is_taken_too(self):
        # #723: run A uploaded the dnf repository of 159.0.1-0.3, then its APT upload failed. The APT index still
        # serves 0.2; the dnf index serves 0.3 (with the distribution, as rpm writes it). The build job of run B reads
        # both, and B builds 0.4 instead of stopping at the dnf upload with other bytes under 0.3.
        subprocess.run(["git", "-C", str(self.repo), "tag", "v159.0.1-0.2", self.base], check=True)
        primary = dnf_primary_xml(("nulavio", "159.0.1", "0.3.fc44"), ("nulavio-debug", "159.0.1", "0.9.fc44"))
        repomd = dnf_repomd(primary)
        self.assertEqual(release_manifest.dnf_primary(repomd), PRIMARY_HREF)
        dnf = release_manifest.dnf_served(repomd, primary)
        self.assertEqual(dnf, "159.0.1-0.3")
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo, ["v159.0.1-0.2"]), "0.3")  # APT alone
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo, ["v159.0.1-0.2", f"v{dnf}"]), "0.4")
        # The highest of several nulavio packages; the commands the build job runs print the same.
        two = dnf_primary_xml(("nulavio", "159.0.1", "0.10.fc44"), ("nulavio", "159.0.1", "0.9.fc45"))
        self.assertEqual(release_manifest.dnf_served(dnf_repomd(two), two), "159.0.1-0.10")
        (self.tmp / "repomd.xml").write_bytes(repomd)
        (self.tmp / "primary.xml").write_bytes(primary)
        repomd_file, primary_file = str(self.tmp / "repomd.xml"), str(self.tmp / "primary.xml")
        for argv, printed in ((["dnf-primary", repomd_file], PRIMARY_HREF + "\n"),
                              (["dnf-served", repomd_file, primary_file], "159.0.1-0.3\n")):  # fmt: skip
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = release_manifest.main(argv)
            self.assertEqual((code, out.getvalue()), (0, printed))

    def test_a_dnf_index_that_cannot_be_read_stops_the_build(self):
        # Fail closed, as the APT read does: the build job must not pick a revision from an index it could not read.
        primary = dnf_primary_xml(("nulavio", "159.0.1", "0.3.fc44"))
        repomd = dnf_repomd(primary)
        cut = primary[:-20]
        cases = [
            ("readable XML", b"<repomd", primary),
            ("declares a DTD", b'<!DOCTYPE r [<!ENTITY a "aaaa">]>' + repomd, primary),
            ("0 primary files", repomd.replace(b'type="primary"', b'type="other"'), primary),
            ("not repodata/<sha256>-primary.xml.zst", dnf_repomd(primary, href="../x86_64/evil.xml.zst"), primary),
            ("open-checksum", repomd, primary.replace(b"0.3.fc44", b"0.2.fc44")),
            ("lists no nulavio package", dnf_repomd(other := dnf_primary_xml(("other", "1.0", "1"))), other),
            ("not <version>-<release>", dnf_repomd(odd := dnf_primary_xml(("nulavio", "159.0.1", "0.3.el9"))), odd),
            # From the review of f2a6c211: two primary entries; an open-checksum that is missing, or that has the
            # right digest under another type (only sha256 is read); a primary file that is not readable XML.
            ("2 primary files", repomd.replace(b'type="other"', b'type="primary"'), primary),
            ("open-checksum", re.sub(rb"\s*<open-checksum[^>]*>[0-9a-f]+</open-checksum>", b"", repomd), primary),
            ("open-checksum", repomd.replace(b'<open-checksum type="sha256">', b'<open-checksum type="sha1">'), primary),
            ("the primary file is not readable XML", dnf_repomd(cut), cut),
        ]
        for fragment, index, data in cases:
            with self.subTest(fragment), self.assertRaises(release_manifest.ManifestError) as caught:
                release_manifest.dnf_primary(index)
                release_manifest.dnf_served(index, data)
            self.assertIn(fragment, str(caught.exception))
        empty = self.tmp / "empty.xml"
        empty.write_bytes(b"")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(release_manifest.main(["dnf-primary", str(empty)]), 1)
        # A file the job did not write is a clean error too, not a traceback.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(release_manifest.main(["dnf-served", str(self.tmp / "none.xml"), str(empty)]), 1)
        self.assertIn("release_manifest: ", err.getvalue())

    def test_a_dnf_index_in_another_encoding_cannot_declare_an_entity(self):
        # The review of f2a6c211: a byte search for <!DOCTYPE misses it in UTF-16, and the entity then expanded into
        # the release. createrepo_c writes UTF-8: anything else is refused, and expat refuses a DTD in any encoding.
        utf8 = dnf_primary_xml(("nulavio", "159.0.1", "0.3.fc44")).decode()
        crafted = utf8.replace('encoding="UTF-8"?>', 'encoding="UTF-16"?><!DOCTYPE metadata [<!ENTITY r "0.9.fc44">]>')
        crafted = crafted.replace('rel="0.3.fc44"', 'rel="&r;"')
        for primary, fragment in ((crafted.encode("utf-16"), "is not UTF-8"),
                                  (crafted.replace("UTF-16", "UTF-8").encode(), "declares a DTD")):  # fmt: skip
            with self.subTest(fragment), self.assertRaises(release_manifest.ManifestError) as caught:
                release_manifest.dnf_served(dnf_repomd(primary), primary)
            self.assertIn(fragment, str(caught.exception))
        # And repomd.xml the same way.
        repomd = dnf_repomd(primary := utf8.encode()).decode().replace('encoding="UTF-8"', 'encoding="UTF-16"')
        with self.assertRaises(release_manifest.ManifestError) as caught:
            release_manifest.dnf_primary(repomd.encode("utf-16"))
        self.assertIn("repomd.xml is not UTF-8", str(caught.exception))
        # A DTD with no entity, which expat reads in any encoding, is refused as well.
        doctype = b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE repomd SYSTEM "x.dtd">' + dnf_repomd(primary)[39:]
        with self.assertRaises(release_manifest.ManifestError) as caught:
            release_manifest.dnf_primary(doctype)
        self.assertIn("declares a DTD", str(caught.exception))

    def test_signing_refuses_packages_the_manifest_does_not_list(self):
        packages = self.out / "packages"
        self.assertEqual(len(release_manifest.check_packages(self.out / "manifest.json", packages)), 2)
        (packages / "x86_64" / "nulavio-159.0.1-0.2.fc44.x86_64.rpm").write_bytes(b"another build")
        with self.assertRaises(release_manifest.ManifestError) as caught:
            release_manifest.check_packages(self.out / "manifest.json", packages)
        self.assertIn("0.2", str(caught.exception))

    def test_next_revision_reserves_tags_even_when_site_metadata_lags(self):
        self.published("159.0.1-0.1")
        for tag in ("v159.0.1-0.9", "v159.0.1-0.10", "unrelated", "v160.0-0.3"):
            subprocess.run(["git", "-C", str(self.repo), "tag", tag, self.base], check=True)
        self.assertEqual(release_manifest.next_release("159.0.1", self.repo), "0.11")

    def test_existing_newer_tag_prevents_a_downgrade_with_stale_site_metadata(self):
        subprocess.run(["git", "-C", str(self.repo), "tag", "v160.0-0.1", self.base], check=True)
        self.refused("not newer")

    def test_an_upload_is_refused_when_a_newer_release_is_tagged_published_or_drafted(self):
        check = release_manifest.check_not_older
        check("v159.0.1-0.1", self.repo)  # nothing else exists
        check("v159.0.1-0.1", self.repo, ["v159.0.1-0.1", "v159.0.1-0.0.9", "v158.0-0.4", "unrelated"])
        for newer in ("v159.0.1-0.2", "v159.0.1-0.1.1", "v160.0-0.1"):
            with self.subTest(draft=newer), self.assertRaises(release_manifest.ManifestError) as caught:
                check("v159.0.1-0.1", self.repo, [newer])
            self.assertIn("roll the dnf and APT repositories back", str(caught.exception))
        subprocess.run(["git", "-C", str(self.repo), "tag", "v159.0.1-0.1", self.base], check=True)
        check("v159.0.1-0.1", self.repo)  # its own tag: the same release uploaded again
        subprocess.run(["git", "-C", str(self.repo), "tag", "v159.0.1-0.3", self.base], check=True)
        with self.assertRaises(release_manifest.ManifestError):
            check("v159.0.1-0.1", self.repo)
        self.published("160.0-0.1")
        with self.assertRaises(release_manifest.ManifestError):
            check("v159.0.1-0.3", self.repo)
        with self.assertRaises(release_manifest.ManifestError):
            check("159.0.1-0.1", self.repo)
        self.assertEqual(release_manifest.main(["not-older", "v160.0-0.2", "--repo", str(self.repo), "--also", "v160.0-0.1"]), 0)
        self.assertEqual(release_manifest.main(["not-older", "v160.0-0.2", "--repo", str(self.repo), "--also", "v160.0-0.3"]), 1)

    def test_the_portable_archive_is_listed_checked_and_published(self):
        archive = "packages/nulavio-159.0.1-0.1.linux-x86_64.tar.xz"
        (self.out / archive).write_bytes(b"tree")
        packages = self.out / "packages"
        with self.assertRaises(release_manifest.ManifestError):  # not listed yet: nothing is signed
            release_manifest.check_packages(self.out / "manifest.json", packages)
        self.manifest["packages"].append({"file": archive, "sha256": digest(self.out / archive)})
        self.write()
        self.assertEqual(self.verify()["archives"], [archive])
        self.assertEqual(len(release_manifest.check_packages(self.out / "manifest.json", packages)), 3)
        (self.out / archive).write_bytes(b"changed")
        self.refused("changed since the rehearsal")
        publish = (ROOT / "scripts" / "release" / "publish_release.sh").read_text(encoding="utf-8")
        self.assertIn("field archives", publish)

    def test_the_deb_is_listed_with_the_rpms_version(self):
        self.assertEqual(self.verify()["debs"], [DEB])
        other = "packages/nulavio_159.0.1-0.2_amd64.deb"
        (self.out / other).write_bytes(b"deb2")
        self.manifest["packages"] = [e for e in self.manifest["packages"] if e["file"] != DEB]
        self.manifest["packages"].append({"file": other, "sha256": digest(self.out / other)})
        self.write()
        self.refused("not the version of the RPM")
        self.manifest["packages"][-1] = {"file": "packages/nulavio-159.0.1.deb", "sha256": digest(self.out / other)}
        (self.out / "packages/nulavio-159.0.1.deb").write_bytes(b"deb2")
        self.write()
        self.refused("not a Nulavio .deb file name")

    def test_the_apt_source_file_must_be_the_same_at_the_base_commit_and_on_the_branch(self):
        # The release notes give its SHA-256 at the base commit; the site serves the branch's.
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        sources = self.repo / "site" / "apt" / "nulavio.sources"
        subprocess.run([*git, "checkout", "-q", "main"], check=True)
        sources.parent.mkdir(parents=True)
        sources.write_text("Types: deb\n")
        subprocess.run([*git, "add", "site"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "sources"], check=True)
        base = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        self.manifest["nulavio_base_commit"] = base
        self.write()
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "later, unrelated"], check=True)
        self.assertEqual(self.verify()["tag"], "v159.0.1-0.1")
        sources.write_text("Types: deb\nURIs: https://elsewhere.example\n")
        subprocess.run([*git, "commit", "-q", "-am", "the file changed"], check=True)
        self.refused("changed on main since the base commit")

    def test_sign_apt_repo_runs_the_check_before_signing_and_checks_what_it_signed(self):
        script = (ROOT / "scripts" / "release" / "sign_apt_repo.sh").read_text(encoding="utf-8")
        check = script.index("release_manifest.py")
        index, sign = script.index("apt-ftparchive packages"), script.index("--clearsign")
        self.assertLess(check, index)
        self.assertLess(index, sign)
        # apt fetches the indexes by hash, and the metadata carries no MD5 or SHA-1.
        for option in ("APT::FTPArchive::DoByHash=true", "APT::FTPArchive::MD5=false", "APT::FTPArchive::SHA1=false"):
            self.assertIn(option, script)
        code = script.split("set -euo pipefail", 1)[1]
        self.assertNotIn("Valid-Until", code, "an expiry would stop apt update while a release waits")
        # Both signatures are checked with the public key alone before anything is uploaded: run, not
        # read, in test_release_script_protections.SignAptRepoTest.
        # The file that turns apt's checks on is never written where the packages are uploaded.
        # (it builds one in its own temporary directory, pointed at the repository, to have apt check it)
        for line in code.splitlines():
            if ".sources" in line and "$out" in line:
                self.assertIn('-v "$out:/repo:ro"', line, "the repository is mounted read-only for that check")
                self.assertNotRegex(line, r'>>?\s*"?\$out')
        self.assertIn("apt-get -qq download nulavio", code)
        self.assertNotIn("trusted=yes", script)
        # An image given in its place is pinned like the default, or nothing runs.
        pkgs = self.tmp / "image-check" / "pkgs"
        pkgs.mkdir(parents=True)
        (pkgs / "nulavio_1.0-0.1_amd64.deb").write_bytes(b"x")
        run = subprocess.run(
            ["bash", str(ROOT / "scripts/release/sign_apt_repo.sh"), str(pkgs), str(self.tmp / "image-check/out"), "A" * 40],
            env={**os.environ, "NULAVIO_APT_IMAGE": "docker.io/library/ubuntu:26.10"}, capture_output=True, text=True,
        )  # fmt: skip
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIn("must be registry/name:tag@sha256:digest", run.stderr)
        publish = (ROOT / "scripts" / "release" / "publish_release.sh").read_text(encoding="utf-8")
        self.assertIn('sign_apt_repo.sh" "$out/packages" "$stage/apt" "$key"', publish)
        # A rehearsal without its .deb is refused: test_release_script_protections.PublishReleaseTest.

    def test_sign_repo_runs_the_check_before_signing(self):
        script = (ROOT / "scripts" / "release" / "sign_repo.sh").read_text(encoding="utf-8")
        check, sign = script.index("release_manifest.py"), script.index("rpmsign")
        self.assertLess(check, sign)
        # dnf reads repodata/ under baseurl, and sign_repo.sh writes it at the top of <repo-out>.
        self.assertIn("createrepo_c --quiet /repo\n", script)
        # The file that turns dnf's checks on is never written where the packages are uploaded.
        self.assertNotIn("> /repo/nulavio.repo", script)
        self.assertNotIn("gpgcheck", script)

    def test_the_repo_file_comes_from_the_site_with_both_checks_on(self):
        release = json.loads((ROOT / "packaging" / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(release["repo_file"], "https://nulavio.net/rpm/nulavio.repo")
        lines = (ROOT / "site" / "rpm" / "nulavio.repo").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, [
            "[nulavio]", "name=Nulavio", "baseurl=https://packages.nulavio.net/rpm", "enabled=1",
            "gpgcheck=1", "repo_gpgcheck=1", f"gpgkey={release['key_url']}",
        ])  # fmt: skip
        for readme in ("README.md", "README.pt-BR.md"):
            text = (ROOT / readme).read_text(encoding="utf-8")
            self.assertIn("--from-repofile=https://nulavio.net/rpm/nulavio.repo", text)
            self.assertNotIn("packages.nulavio.net/rpm/nulavio.repo", text)


if __name__ == "__main__":
    unittest.main()
