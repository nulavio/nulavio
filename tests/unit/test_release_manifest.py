"""Only what a finished rehearsal of reviewed history checked can be signed and published."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
sys.path.insert(0, str(ROOT / "scripts" / "upstream"))

import release_manifest  # noqa: E402
from verify_firefox_release import SIGNING_SUBKEYS  # noqa: E402

RPM = "packages/x86_64/nulavio-159.0.1-0.1.fc44.x86_64.rpm"
DEB = "packages/nulavio_159.0.1-0.1_amd64.deb"
SOURCE = "b5fe407199685f8bddf3b2c81feb8b805429e6f3d307c9430f53456f85b6e063"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nulavio-manifest-test-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git = ["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
        subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
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

    def write(self):
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
        # Both signatures are checked with the public key alone, before anything is uploaded.
        self.assertIn('gpgv --keyring "$tmp/keyring.gpg" "$dists/InRelease"', script)
        self.assertIn('gpgv --keyring "$tmp/keyring.gpg" "$dists/Release.gpg" "$dists/Release"', script)
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
        self.assertIn("field debs", publish)

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
