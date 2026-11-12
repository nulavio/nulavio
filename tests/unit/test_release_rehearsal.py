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
    def scaffold(self, tmp: Path) -> tuple[Path, Path, Path, Path, dict]:
        """A repository with the rehearsal script and stubs for what it calls, a built tree to install, and a clean
        environment. No real build, packager, network or default cache is used."""
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
            "scripts/upstream/refresh_extensions_lock.py",
            "scripts/build/make_distribution.py",
            "scripts/build/make_tools.py",
            "tests/run.py",
        ):
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Test stub: no host state or network.\n")
        for stub in ("scripts/build/build_nulavio.sh", "scripts/release/run_integration.sh"):
            path = repo / stub
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
        tree = tmp / "nulavio"
        tree.mkdir()
        (tree / "application.ini").write_text("Version=159.0.1\n")
        dist = work / "firefox-159.0.1" / "obj-nulavio" / "dist"
        dist.mkdir(parents=True)
        with tarfile.open(dist / "nulavio-159.0.1.en-US.linux-x86_64.tar.xz", "w:xz") as archive:
            archive.add(tree, arcname="nulavio")
        # Not what a surrounding rehearsal exported (NULAVIO_RELEASE, NULAVIO_BUILD_PROFILE, …):
        # this suite also runs inside rehearse_release.sh.
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("NULAVIO_")},
            "HOME": str(tmp / "home"),
            "NULAVIO_BUILD_DIR": str(work),
            "NULAVIO_INSTALL_DIR": str(tmp / "unrelated-install"),
        }
        return repo, work, out, script, env

    def test_packagers_receive_the_tree_installed_by_this_rehearsal(self):
        with tempfile.TemporaryDirectory(prefix="nulavio-rehearsal-test-") as directory:
            tmp = Path(directory)
            _repo, work, out, script, env = self.scaffold(tmp)
            release = script.parent
            # Stop at each packager in turn.
            for packager in ("rpm", "deb"):
                for name in ("make_rpm.sh", "check_rpm.sh", "make_deb.sh"):
                    path = release / name
                    body = (
                        'printf "%s\\n" "${NULAVIO_INSTALL_DIR-unset}" > "$1/install-path"\n'
                        'printf "%s\\n" "${NULAVIO_RELEASE-unset}" > "$1/release"\nexit 41\n'
                    )
                    path.write_text("#!/bin/sh\n" + (body if name == f"make_{packager}.sh" else "exit 0\n"))
                    path.chmod(0o755)
                result = subprocess.run(
                    ["bash", str(script), "159.0.1", str(out)], env=env, capture_output=True, text=True, timeout=15
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(f"rehearsal: {packager} failed", result.stderr)
                self.assertEqual((out / "packages" / "install-path").read_text().strip(), str(work / "install" / "nulavio"))
                self.assertEqual((out / "packages" / "release").read_text().strip(), "0.2")

    def test_a_failing_command_inside_the_install_step_stops_the_rehearsal(self):
        """The install step is a function of the script. What it runs first is the gate that compares uBlock Origin's
        list registry with the pinned package: when that fails (the copy differs, or the package could not be had),
        the distribution files are not written and nothing is packaged. The same for the distribution files
        themselves."""
        for failing, status in (
            ("scripts/upstream/refresh_extensions_lock.py", 1),
            ("scripts/upstream/refresh_extensions_lock.py", 2),
            ("scripts/build/make_distribution.py", 1),
        ):
            with (
                self.subTest(failing=failing, status=status),
                tempfile.TemporaryDirectory(prefix="nulavio-rehearsal-test-") as directory,
            ):
                tmp = Path(directory)
                repo, _work, out, script, env = self.scaffold(tmp)
                for name in (
                    "scripts/upstream/refresh_extensions_lock.py",
                    "scripts/build/make_distribution.py",
                    "scripts/build/make_tools.py",
                ):
                    reached = tmp / ("reached-" + Path(name).name)
                    body = f"import sys\nopen({str(reached)!r}, 'w').close()\n"
                    (repo / name).write_text(body + (f"sys.exit({status})\n" if name == failing else ""))
                packaged = tmp / "packaged"
                (script.parent / "make_rpm.sh").write_text(f"#!/bin/sh\ntouch {packaged}\nexit 41\n")
                (script.parent / "make_rpm.sh").chmod(0o755)
                result = subprocess.run(
                    ["bash", str(script), "159.0.1", str(out)], env=env, capture_output=True, text=True, timeout=15
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("rehearsal: install failed", result.stderr)
                self.assertIn("| install |", (out / "rehearsal.md").read_text())
                self.assertIn("failed", (out / "rehearsal.md").read_text().split("| install |", 1)[1].splitlines()[0])
                self.assertTrue((tmp / ("reached-" + Path(failing).name)).exists())
                self.assertFalse((tmp / "reached-make_tools.py").exists(), "the step carried on past the failure")
                if failing.endswith("refresh_extensions_lock.py"):
                    self.assertFalse((tmp / "reached-make_distribution.py").exists(), "policies were written past the gate")
                self.assertFalse(packaged.exists(), "packaged after a failed install")


if __name__ == "__main__":
    unittest.main()
