"""Only what a finished rehearsal of reviewed history checked can be signed and published."""

from __future__ import annotations

import hashlib
import json
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

    def test_signing_refuses_packages_the_manifest_does_not_list(self):
        packages = self.out / "packages"
        self.assertEqual(len(release_manifest.check_packages(self.out / "manifest.json", packages)), 2)
        (packages / "x86_64" / "nulavio-159.0.1-0.2.fc44.x86_64.rpm").write_bytes(b"another build")
        with self.assertRaises(release_manifest.ManifestError) as caught:
            release_manifest.check_packages(self.out / "manifest.json", packages)
        self.assertIn("0.2", str(caught.exception))

    def test_sign_repo_runs_the_check_before_signing(self):
        script = (ROOT / "scripts" / "release" / "sign_repo.sh").read_text(encoding="utf-8")
        check, sign = script.index("release_manifest.py"), script.index("rpmsign")
        self.assertLess(check, sign)
        # dnf reads repodata/ under baseurl, and sign_repo.sh writes it at the top of <repo-out>.
        self.assertIn("baseurl=${NULAVIO_REPO_BASEURL:-https://packages.nulavio.net/rpm}", script)
        self.assertIn("createrepo_c --quiet /repo\n", script)


if __name__ == "__main__":
    unittest.main()
