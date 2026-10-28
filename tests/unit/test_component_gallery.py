"""Packaging and source boundaries of the UX2 component system."""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "build"))
import make_shell  # noqa: E402

SHARED = ROOT / "browser" / "shell" / "shared"


class Specimens(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.controls = 0
        self.unsafe = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        inert = "inert" in attrs or any(self.stack)
        if tag in ("button", "input", "select"):
            self.controls += 1
            if not inert:
                self.unsafe.append(tag)
        if tag not in ("input", "meta", "link", "img", "path", "br"):
            self.stack.append(inert)

    def handle_endtag(self, tag):
        if tag not in ("input", "meta", "link", "img", "path", "br") and self.stack:
            self.stack.pop()


class ComponentGalleryTest(unittest.TestCase):
    def test_packaged_base_is_shell_owned_and_gallery_uses_production_css(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "shell"
            files = make_shell.assemble(out)
            self.assertEqual((out / "shared/base.css").read_bytes(), (SHARED / "base.css").read_bytes())
            self.assertNotEqual((out / "shared/base.css").read_bytes(), (ROOT / "browser/startpage/startpage.css").read_bytes())
            for name in ("base", "components", "pages", "accessibility", "shell"):
                self.assertIn(f"shared/{name}.css", files)
            gallery = (out / "dev/gallery/index.html").read_text()
            for name in ("tokens", "base", "shell"):
                self.assertEqual(gallery.count(f"../../shared/{name}.css"), 1)
            self.assertNotIn("<script", gallery)
            self.assertIn("Artificial examples only", gallery)
            parser = Specimens()
            parser.feed(gallery)
            self.assertGreater(parser.controls, 15)
            self.assertEqual(parser.unsafe, [])

    def test_cascade_imports_are_single_and_base_has_no_startpage_components(self):
        entry = (SHARED / "shell.css").read_text()
        self.assertEqual(re.findall(r'@import url\("(.*?)"\)', entry), ["components.css", "pages.css", "accessibility.css"])
        self.assertIn("nv-base, nv-components, nv-pages, nv-gallery, nv-accessibility", entry)
        base = (SHARED / "base.css").read_text()
        for selector in (".hero", ".card", ".facts", "radial-gradient"):
            self.assertNotIn(selector, base)
        for name, layer in (
            ("base", "base"),
            ("components", "components"),
            ("pages", "pages"),
            ("accessibility", "accessibility"),
        ):
            css = (SHARED / f"{name}.css").read_text()
            self.assertIn(f"@layer nv-{layer}", css)
            self.assertNotIn("@import", css)
