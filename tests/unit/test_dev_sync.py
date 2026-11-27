"""scripts/build/dev_sync.py on a small fake package: what it replaces, what it says, and what --reset gives back."""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))

import dev_sync  # noqa: E402
import make_branding  # noqa: E402

BRANDING = "chrome/browser/content/branding/"
# What the fake package holds before any sync: the build's own files.
BUILT = {
    BRANDING + "aboutDialog.css": b"the build's css",
    BRANDING + "illustration-shield-ok.svg": b"the build's shield",
    BRANDING + "about-wordmark.svg": b"the build's name",
    BRANDING + "about-logo.png": b"the build's logo",
    BRANDING + "icon16.png": b"the build's icon entry",
    BRANDING + "theme/horizon.css": b"the build's theme",
    "defaults/preferences/firefox-branding.js": b"the build's prefs",
    "chrome/browser/content/browser/browser.xhtml": b"the engine's own file",
}


def fake_build(pixels: bytes):
    """make_branding.build without a rasteriser: the committed text files, and `pixels` for every file
    that ImageMagick would render."""

    def build(target: Path) -> None:
        shutil.copytree(make_branding.TEMPLATES, target)
        content = target / "content"
        for name in ("about-wordmark.svg", "firefox-wordmark.svg", "about-logo.svg", "document_pdf.svg"):
            (content / name).write_text(f"<svg><!-- {name} --></svg>", encoding="utf-8")
        for name in ("about.png", "about-logo.png", "about-logo@2x.png", "about-logo-private.png", "about-logo-private@2x.png"):
            (content / name).write_bytes(pixels)
        for name in (*dev_sync.ICON_NAMES, "document.ico"):
            (target / name).write_bytes(pixels + name.encode())

    return build


class DevSyncTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.install = Path(tmp.name) / "nulavio"
        self.omni = self.install / "browser" / "omni.ja"
        self.icons = self.install / "browser" / "chrome" / "icons" / "default"
        self.icons.mkdir(parents=True)
        with zipfile.ZipFile(self.omni, "w") as package:
            for name, data in BUILT.items():
                package.writestr(name, data)
        for name in dev_sync.ICON_NAMES:
            (self.icons / name).write_bytes(b"the build's " + name.encode())
        self.built_omni = self.omni.read_bytes()

    def sync(self, *flags: str, magick: bool, pixels: bytes = b"rendered") -> str:
        """Run the command on the fake package. Nothing of the host is used: whether `magick` is there
        is given, the rasteriser is the fake one, and the distribution and tools are not generated."""
        said = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "argv", ["dev_sync.py", "--install", str(self.install), *flags]))
            stack.enter_context(mock.patch.object(dev_sync, "have_magick", lambda: magick))
            stack.enter_context(mock.patch.object(make_branding, "build", fake_build(pixels)))
            refresh = stack.enter_context(mock.patch.object(dev_sync, "refresh"))
            stack.enter_context(contextlib.redirect_stdout(said))
            self.assertEqual(dev_sync.main(), 0)
        self.assertEqual(refresh.call_count, 0 if "--reset" in flags else 1)
        return said.getvalue()

    def entries(self) -> dict[str, bytes]:
        with zipfile.ZipFile(self.omni) as package:
            return {name: package.read(name) for name in package.namelist()}

    def icon_files(self) -> dict[str, bytes]:
        return {path.name: path.read_bytes() for path in sorted(self.icons.iterdir())}

    def built_icons(self) -> dict[str, bytes]:
        return {name: b"the build's " + name.encode() for name in dev_sync.ICON_NAMES}

    def test_without_imagemagick_the_text_files_are_synced_and_the_rest_is_the_builds(self):
        said = self.sync(magick=False)
        self.assertIn("branding: text only", said)
        self.assertIn("no `magick` on this host", said)
        now = self.entries()
        source = ROOT / "browser" / "branding" / "nulavio" / "content"
        for name in ("aboutDialog.css", "illustration-shield-ok.svg", "illustration-shield-alert.svg"):
            self.assertEqual(now[BRANDING + name], (source / name).read_bytes(), name)
        self.assertEqual(now[BRANDING + "about-wordmark.svg"], make_branding.context_fill_wordmark().encode())
        self.assertEqual(now[BRANDING + "firefox-wordmark.svg"], make_branding.context_fill_wordmark().encode())
        self.assertEqual(now[BRANDING + "document_pdf.svg"], make_branding.document_pdf_svg().encode())
        for name in ("about-logo.png", "icon16.png"):  # rendered files: the build's own, and none added
            self.assertEqual(now[BRANDING + name], BUILT[BRANDING + name], name)
        self.assertEqual([n for n in now if n.endswith((".png", ".ico"))], [BRANDING + "about-logo.png", BRANDING + "icon16.png"])
        self.assertEqual(now["chrome/browser/content/browser/browser.xhtml"], b"the engine's own file")
        self.assertEqual(self.icon_files(), self.built_icons())  # untouched: no copy was needed

    def test_every_branding_file_is_text_or_rendered(self):
        # The text-only path leaves out exactly the files a rasteriser makes. A new entry of jar.mn that is
        # neither committed nor generated as text here would be dropped without a word.
        packed = dev_sync.jar_entries(ROOT / "browser" / "branding" / "nulavio" / "content")
        left_out = sorted(set(packed) - set(dev_sync.text_branding()))
        self.assertTrue(left_out)
        self.assertEqual([name for name in left_out if not name.endswith((".png", ".ico"))], [])
        self.assertEqual([name for name in dev_sync.text_branding() if name.endswith((".png", ".ico"))], [])

    def test_no_branding_leaves_the_builds_branding_on_any_host(self):
        for magick in (True, False):
            with self.subTest(magick=magick):
                said = self.sync("--no-branding", magick=magick)
                self.assertIn("branding: left alone", said)
                now = self.entries()
                for name in ("aboutDialog.css", "illustration-shield-ok.svg", "about-wordmark.svg", "about-logo.png"):
                    self.assertEqual(now[BRANDING + name], BUILT[BRANDING + name], name)
                self.assertNotIn(BRANDING + "firefox-wordmark.svg", now)
                # The Shell, the window theme, the prefs and the modules are synced as before.
                self.assertNotEqual(now[BRANDING + "theme/horizon.css"], BUILT[BRANDING + "theme/horizon.css"])
                self.assertNotEqual(now["defaults/preferences/firefox-branding.js"], b"the build's prefs")
                self.assertTrue(any(name.startswith("modules/nulavio/") for name in now))
                self.assertEqual(self.icon_files(), self.built_icons())

    def test_the_rendered_branding_replaces_the_window_icons_and_reset_gives_them_back(self):
        said = self.sync(magick=True)
        self.assertIn("branding: rendered with ImageMagick", said)
        self.assertIn("5 window icons replaced", said)
        now = self.entries()
        self.assertEqual(now[BRANDING + "about-logo.png"], b"rendered")
        self.assertEqual(now[BRANDING + "icon16.png"], b"rendereddefault16.png")
        self.assertEqual(now[BRANDING + "document.ico"], b"rendereddocument.ico")
        files = self.icon_files()
        for name in dev_sync.ICON_NAMES:
            self.assertEqual(files[name], b"rendered" + name.encode())
            self.assertEqual(files[name + ".orig"], b"the build's " + name.encode())
        # A second sync replaces the icons again and leaves the copies of the build's own as they are.
        self.sync(magick=True, pixels=b"again")
        files = self.icon_files()
        for name in dev_sync.ICON_NAMES:
            self.assertEqual(files[name], b"again" + name.encode())
            self.assertEqual(files[name + ".orig"], b"the build's " + name.encode())
        self.assertEqual(self.omni.with_name("omni.ja.orig").read_bytes(), self.built_omni)

        said = self.sync("--reset", magick=True)
        self.assertIn("omni.ja, default16.png, default32.png, default48.png, default64.png, default128.png restored", said)
        self.assertEqual(self.omni.read_bytes(), self.built_omni)
        self.assertEqual(
            {name: data for name, data in self.icon_files().items() if not name.endswith(".orig")}, self.built_icons()
        )
        self.assertEqual([p.name for p in self.install.rglob("*.tmp")], [])  # every write went through a rename

    def test_a_run_that_says_the_icons_are_the_builds_puts_them_back(self):
        # The archive is always rewritten from omni.ja.orig; the icons are files, and an earlier rendered
        # sync would otherwise outlast a run that reports the build's own branding.
        for flags, magick, expected in ((("--no-branding",), True, "left alone"), ((), False, "text only")):
            with self.subTest(flags=flags, magick=magick):
                self.sync(magick=True)
                self.assertNotEqual(self.icon_files()["default16.png"], b"the build's default16.png")
                self.assertIn(expected, self.sync(*flags, magick=magick))
                files = self.icon_files()
                self.assertEqual({name: files[name] for name in dev_sync.ICON_NAMES}, self.built_icons())

    def test_reset_on_a_package_that_was_never_synced_changes_nothing(self):
        said = self.sync("--reset", magick=True)
        self.assertIn("nothing to restore", said)
        self.assertEqual(self.omni.read_bytes(), self.built_omni)
        self.assertEqual(self.icon_files(), self.built_icons())

    def test_an_icon_the_package_does_not_have_is_not_created(self):
        (self.icons / "default128.png").unlink()
        said = self.sync(magick=True)
        self.assertIn("4 window icons replaced", said)
        self.assertFalse((self.icons / "default128.png").exists())  # nothing --reset could not take back


class IntoPlaceTest(unittest.TestCase):
    """A file is replaced whole or not at all, through a temporary file nobody planted, which is
    removed when the write fails; the file keeps its permissions."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.target = self.dir / "default16.png"
        self.target.write_bytes(b"the build's icon")
        self.target.chmod(0o644)

    def test_a_failed_write_leaves_the_file_and_no_temporary_file(self):
        def fail(tmp: Path) -> None:
            tmp.write_bytes(b"half")
            raise OSError("disk full")

        with self.assertRaises(OSError):
            dev_sync.into_place(self.target, fail)
        self.assertEqual(self.target.read_bytes(), b"the build's icon")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["default16.png"])

    def test_a_link_planted_at_the_old_temporary_name_is_not_written_through(self):
        outside = self.dir / "outside"
        outside.write_bytes(b"someone else's file")
        (self.dir / "default16.png.tmp").symlink_to(outside)
        dev_sync.write_into_place(self.target, b"new icon")
        self.assertEqual(self.target.read_bytes(), b"new icon")
        self.assertEqual(outside.read_bytes(), b"someone else's file")

    def test_the_file_keeps_its_permissions(self):
        dev_sync.write_into_place(self.target, b"new icon")
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)


if __name__ == "__main__":
    unittest.main()
