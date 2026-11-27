"""Exercise the rehearsal's install-path handoff without a real build or packages."""

from __future__ import annotations

import os
import re
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
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True)
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

    def test_a_package_of_another_revision_is_refused_before_anything_runs(self):
        """The default output directory is per Firefox version, so the next revision's rehearsal finds the last one's
        packages (#637). It stops before the first step, with the earlier report as it was; a fresh directory and a
        re-run of the same release go on."""
        stale_rpm, stale_deb = "x86_64/nulavio-159.0.1-0.1.fc44.x86_64.rpm", "nulavio_159.0.1-0.1_amd64.deb"
        this = ["x86_64/nulavio-159.0.1-0.2.fc44.x86_64.rpm", "nulavio_159.0.1-0.2_amd64.deb"]
        for present, refused in (([stale_rpm], True), ([*this, stale_deb], True), ([], False), (this, False)):
            with (
                self.subTest(present=present),
                tempfile.TemporaryDirectory(prefix="nulavio-rehearsal-test-") as directory,
            ):
                tmp = Path(directory)
                repo, _work, out, script, env = self.scaffold(tmp)
                reached = tmp / "reached-verify"
                (repo / "scripts/upstream/verify_firefox_release.py").write_text(f"open({str(reached)!r}, 'w')\n")
                (script.parent / "make_rpm.sh").write_text("#!/bin/sh\nexit 41\n")
                (script.parent / "make_rpm.sh").chmod(0o755)
                (out / "packages" / "x86_64").mkdir(parents=True)
                for name in present:
                    (out / "packages" / name).write_bytes(b"package")
                (out / "rehearsal.md").write_text("the earlier rehearsal's report\n")
                result = subprocess.run(
                    ["bash", str(script), "159.0.1", str(out)], env=env, capture_output=True, text=True, timeout=15
                )
                if refused:
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn(Path(present[-1]).name, result.stderr)
                    self.assertIn("is not of release 159.0.1-0.2", result.stderr)
                    self.assertFalse(reached.exists(), "a step ran before the refusal")
                    self.assertEqual((out / "rehearsal.md").read_text(), "the earlier rehearsal's report\n")
                else:
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("rehearsal: rpm failed", result.stderr)
                    self.assertTrue(reached.exists())

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
                    # Each records the version it was given (#198: make_distribution packs that version's notes).
                    body = f"import os, sys\nopen({str(reached)!r}, 'w').write(os.environ.get('NULAVIO_VERSION', 'unset'))\n"
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
                else:
                    # The full version of this rehearsal, <firefox>-<release>: whose notes the packages carry.
                    self.assertRegex((tmp / "reached-make_distribution.py").read_text(), r"^159\.0\.1-[0-9]+(\.[0-9]+)*$")
                self.assertFalse(packaged.exists(), "packaged after a failed install")


class RehearsalSbomTest(unittest.TestCase):
    """The sbom step names each package by this rehearsal's release (#637). An output directory that still holds a
    package of another revision is refused before any SBOM is written: that package's SBOM would carry this release."""

    RPM = "x86_64/nulavio-160.0.1-0.2.fc44.x86_64.rpm"
    DEB = "nulavio_160.0.1-0.2_amd64.deb"

    @classmethod
    def setUpClass(cls):
        script = (ROOT / "scripts" / "release" / "rehearse_release.sh").read_text(encoding="utf-8")
        functions = []
        for name in ("of_this_release", "sbom"):
            match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", script, re.S | re.M)
            if match is None:
                raise AssertionError(f"rehearse_release.sh must define {name} as a function")
            functions.append(match.group(0))
        cls.helper, cls.function = functions

    def scaffold(self, tmp: Path, files: list[str]) -> Path:
        repo, out = tmp / "repo", tmp / "out"
        (repo / "scripts" / "release").mkdir(parents=True)
        # A stand-in for sbom.py that writes what it was asked to describe.
        (repo / "scripts" / "release" / "sbom.py").write_text("import sys\nprint(' '.join(sys.argv[1:]))\n")
        (out / "packages" / "x86_64").mkdir(parents=True)
        for name in files:
            (out / "packages" / name).write_bytes(b"package")
        return out

    def run_step(self, tmp: Path) -> subprocess.CompletedProcess:
        # As the step runs it: errexit on, the script's variables set. Not what a surrounding rehearsal exported.
        env = {k: v for k, v in os.environ.items() if not k.startswith("NULAVIO_")}
        code = f"set -euo pipefail\nrepo=$1 out=$2 version=160.0.1\n{self.helper}{self.function}sbom\n"
        return subprocess.run(
            ["bash", "-c", code, "sbom", str(tmp / "repo"), str(tmp / "out")],
            env={**env, "NULAVIO_RELEASE": "0.2"},
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_this_releases_packages_get_their_sboms_again_on_a_rerun(self):
        with tempfile.TemporaryDirectory(prefix="nulavio-rehearsal-sbom-") as directory:
            tmp = Path(directory)
            out = self.scaffold(tmp, [self.RPM, self.DEB])
            for name in (self.RPM, self.DEB):
                (out / "packages" / (name + ".cdx.json")).write_text("an earlier run of this release\n")
            result = self.run_step(tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in (self.RPM, self.DEB):
                written = (out / "packages" / (name + ".cdx.json")).read_text()
                self.assertIn(f"--package {out / 'packages' / name} ", written)
                self.assertIn("--release-version 160.0.1-0.2", written)

    def test_the_packages_checked_are_the_ones_described(self):
        """The step lists the packages once and checks and describes that list: a second expansion of the globs could
        take a package copied in after the check. No command runs between the two, so this reads the step's text."""
        for pattern in ('"$out"/packages/x86_64/nulavio-*.rpm', '"$out"/packages/nulavio_*.deb'):
            self.assertEqual(self.function.count(pattern), 1, pattern)

    def test_a_missing_package_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="nulavio-rehearsal-sbom-") as directory:
            tmp = Path(directory)
            out = self.scaffold(tmp, [self.RPM])
            result = self.run_step(tmp)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertFalse((out / "packages" / (self.RPM + ".cdx.json")).exists())

    def test_a_package_of_another_revision_is_refused_before_any_sbom(self):
        for stale in (
            "x86_64/nulavio-160.0.1-0.1.fc44.x86_64.rpm",
            "x86_64/nulavio-160.0.1-0.20.fc44.x86_64.rpm",
            "x86_64/nulavio-160.0.1-0.2.1.fc44.x86_64.rpm",
            "x86_64/nulavio-160.0.2-0.2.fc44.x86_64.rpm",
            "nulavio_160.0.1-0.1_amd64.deb",
            "nulavio_160.0.1-0.2.1_amd64.deb",
        ):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory(prefix="nulavio-rehearsal-sbom-") as directory:
                tmp = Path(directory)
                out = self.scaffold(tmp, [self.RPM, self.DEB, stale])
                kept = out / "packages" / (stale + ".cdx.json")
                kept.write_text("the SBOM of that revision\n")
                result = self.run_step(tmp)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(Path(stale).name, result.stderr)
                self.assertEqual(kept.read_text(), "the SBOM of that revision\n")
                for name in (self.RPM, self.DEB):
                    self.assertFalse((out / "packages" / (name + ".cdx.json")).exists(), f"{name}: written before the refusal")


if __name__ == "__main__":
    unittest.main()
