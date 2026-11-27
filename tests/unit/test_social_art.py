"""The social media art (#175): generated from the brand sources by one command, in the sizes the networks ask for."""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "brand"))

import build_logo  # noqa: E402
import build_social  # noqa: E402

SVG_NS = "{http://www.w3.org/2000/svg}"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


def numbers(element: ET.Element, *names: str) -> list[float]:
    return [float(element.get(name)) for name in names]


class SocialArtTest(unittest.TestCase):
    def test_committed_svgs_are_the_generated_ones(self):
        generated = build_social.all_svgs()
        committed = sorted(str(p.relative_to(build_social.OUT)) for p in build_social.OUT.rglob("*.svg"))
        self.assertEqual(committed, sorted(generated), "run scripts/brand/build_social.py")
        for rel, text in generated.items():
            with self.subTest(svg=rel):
                self.assertEqual((build_social.OUT / rel).read_text(encoding="utf-8"), text, "run scripts/brand/build_social.py")

    def test_every_file_has_its_size(self):
        expected = {"profile/avatar": (400, 400)}
        expected |= {f"profile/header-{lang}": build_social.HEADER_SIZE for lang in build_social.TAGLINE}
        for lang in build_social.SAMPLES:
            for fmt, (w, h, _margin, _free) in build_social.FORMATS.items():
                expected[f"posts/{fmt}-{lang}"] = (w, h)
        self.assertEqual(
            {k: v[:2] for k, v in build_social.FORMATS.items()},
            {"16x9": (1600, 900), "1x1": (1080, 1080), "4x5": (1080, 1350), "9x16": (1080, 1920)},
        )
        for stem, size in expected.items():
            with self.subTest(file=stem):
                root = ET.fromstring((build_social.OUT / f"{stem}.svg").read_text(encoding="utf-8"))
                self.assertEqual((int(root.get("width")), int(root.get("height"))), size)
                self.assertIsNotNone(root.find(f"{SVG_NS}title"))
                self.assertEqual(png_size(build_social.OUT / f"{stem}.png"), size, "run scripts/brand/build_social.py")
        self.assertTrue((build_social.OUT / "crop-check.png").is_file())

    def test_both_languages_for_every_post_format(self):
        self.assertEqual(sorted(build_social.SAMPLES), ["en", "pt-BR"])
        self.assertEqual(sorted(build_social.TAGLINE), ["en", "pt-BR"])
        for fmt in build_social.FORMATS:
            for lang in ("en", "pt-BR"):
                text = (build_social.OUT / "posts" / f"{fmt}-{lang}.svg").read_text(encoding="utf-8")
                self.assertIn(f'xml:lang="{lang}"', text)

    def test_the_marks_come_from_the_logo_generator(self):
        avatar = build_social.avatar_svg()
        self.assertIn(f'd="{build_logo.ROUTE}"', avatar)
        self.assertIn(f"scale({build_logo.n(build_logo.ICON_SCALE)})", avatar)
        self.assertNotIn("rx=", avatar, "full bleed: a circle crop must show no tile corner")
        for text in (build_social.header_svg("en"), build_social.post_svg("1x1", build_social.SAMPLES["en"])):
            self.assertIn(f'd="{build_logo.initial_route()}"', text)  # the lockup, never the symbol beside the name
            self.assertNotIn(f'd="{build_logo.ROUTE}"', text)

    def test_the_avatar_route_fits_inside_its_circle(self):
        half_w, half_h = 46 * build_logo.ICON_SCALE / 2, 54.1 * build_logo.ICON_SCALE / 2
        self.assertLess((half_w**2 + half_h**2) ** 0.5, 48 * 0.9)  # inside the circle, with a margin

    def test_header_text_stays_out_of_the_avatar_and_the_cropped_bands(self):
        for lang in build_social.TAGLINE:
            root = ET.fromstring(build_social.header_svg(lang))
            group = next(g for g in root.iter(f"{SVG_NS}g") if g.get("transform", "").startswith("translate("))
            x, y = (float(v) for v in group.get("transform")[len("translate(") :].split(")")[0].split())
            self.assertGreater(x, build_social.AVATAR_ZONE[2])
            self.assertGreaterEqual(y, build_social.SAFE_BAND)
            for span in root.iter(f"{SVG_NS}tspan"):
                sx, sy = numbers(span, "x", "y")
                self.assertGreater(sx, build_social.AVATAR_ZONE[2])
                self.assertLess(sy, build_social.HEADER_SIZE[1] - build_social.SAFE_BAND)

    def test_story_text_stays_clear_of_the_top_and_bottom(self):
        _w, h, _margin, (top, bottom) = build_social.FORMATS["9x16"]
        root = ET.fromstring(build_social.post_svg("9x16", build_social.SAMPLES["pt-BR"]))
        for span in root.iter(f"{SVG_NS}tspan"):
            self.assertGreater(float(span.get("y")), top)
            self.assertLess(float(span.get("y")), h - bottom)

    def test_text_is_input_and_escaped(self):
        post = {"lang": "en", "kicker": "Release <notes>", "title": 'A & B\n"quoted"', "body": "x", "footer": "nulavio.net"}
        text = build_social.post_svg("16x9", post)
        ET.fromstring(text)
        self.assertIn("A &amp; B", text)
        self.assertIn("RELEASE &lt;NOTES&gt;", text)
        self.assertNotIn("<notes>", text)
        with self.assertRaises(ValueError):
            build_social.post_svg("16x9", {"lang": "en", "title": "x", "href": "https://example.com"})
        with self.assertRaises(ValueError):
            build_social.post_svg("1x1", {"lang": "en", "title": "word " * 200})

    def test_one_command_renders_a_new_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "post.json"
            source.write_text(json.dumps({"lang": "pt-BR", "title": "Nova versão"}), encoding="utf-8")
            done = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(ROOT / "scripts" / "brand" / "build_social.py"),
                    "--svg-only",
                    "post",
                    "--text",
                    str(source),
                    "--out",
                    tmp,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(
                sorted(p.name for p in Path(tmp).glob("*.svg")), sorted(f"{f}-pt-BR.svg" for f in build_social.FORMATS)
            )

    def test_writing_touches_only_the_social_directory(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_social, "OUT", Path(tmp) / "social"):
            written = build_social.write_all(svg_only=True)
            self.assertTrue(all(Path(tmp) / "social" in p.parents for p in written))


if __name__ == "__main__":
    unittest.main()
