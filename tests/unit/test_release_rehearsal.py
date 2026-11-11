"""Exercise the rehearsal's install-path handoff without a real build or packages."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RehearsalInstallTest(unittest.TestCase):
    def test_packagers_receive_the_tree_installed_by_this_rehearsal(self):
        with tempfile.TemporaryDirectory(prefix="nulavio-rehearsal-test-") as directory:
            tmp = Path(directory)
            repo, work, out = tmp / "repo", tmp / "private-cache", tmp / "out"
            release = repo / "scripts" / "release"
            release.mkdir(parents=True)
            script = release / "rehearse_release.sh"
            shutil.copyfile(ROOT / "scripts" / "release" / script.name, script)
            shutil.copyfile(ROOT / "scripts" / "release" / "release_manifest.py", release / "release_manifest.py")
            # 159.0.1-0.1 is published: the rehearsal builds the next release, which dnf upgrades to.
            (repo / "packaging").mkdir()
            (repo / "packaging" / "release.json").write_text('{"version": "159.0.1-0.1"}')
            for name in (
                "scripts/upstream/verify_firefox_release.py",
                "scripts/build/make_distribution.py",
                "scripts/build/make_tools.py",
                "tests/run.py",
            ):
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Test stub: no host state or network.\n")
            build = repo / "scripts" / "build" / "build_nulavio.sh"
            build.write_text("#!/bin/sh\nexit 0\n")
            build.chmod(0o755)
            tree = tmp / "nulavio"
            tree.mkdir()
            (tree / "application.ini").write_text("Version=159.0.1\n")
            dist = work / "firefox-159.0.1" / "obj-nulavio" / "dist"
            dist.mkdir(parents=True)
            with tarfile.open(dist / "nulavio-159.0.1.en-US.linux-x86_64.tar.xz", "w:xz") as archive:
                archive.add(tree, arcname="nulavio")
            # Stop at each packager in turn. No real packager or default cache is accessed.
            for packager in ("rpm", "deb"):
                for name in ("make_rpm.sh", "check_rpm.sh", "make_deb.sh"):
                    path = release / name
                    body = (
                        'printf "%s\\n" "${NULAVIO_INSTALL_DIR-unset}" > "$1/install-path"\n'
                        'printf "%s\\n" "${NULAVIO_RELEASE-unset}" > "$1/release"\nexit 41\n'
                    )
                    path.write_text("#!/bin/sh\n" + (body if name == f"make_{packager}.sh" else "exit 0\n"))
                    path.chmod(0o755)
                # Not what a surrounding rehearsal exported (NULAVIO_RELEASE, NULAVIO_BUILD_PROFILE, …):
                # this suite also runs inside rehearse_release.sh.
                env = {
                    **{k: v for k, v in os.environ.items() if not k.startswith("NULAVIO_")},
                    "HOME": str(tmp / "home"),
                    "NULAVIO_BUILD_DIR": str(work),
                    "NULAVIO_INSTALL_DIR": str(tmp / "unrelated-install"),
                }
                result = subprocess.run(
                    ["bash", str(script), "159.0.1", str(out)], env=env, capture_output=True, text=True, timeout=15
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(f"rehearsal: {packager} failed", result.stderr)
                self.assertEqual((out / "packages" / "install-path").read_text().strip(), str(work / "install" / "nulavio"))
                self.assertEqual((out / "packages" / "release").read_text().strip(), "0.2")


if __name__ == "__main__":
    unittest.main()
