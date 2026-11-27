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
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SCRIPT = ROOT / "scripts" / "brand" / "build_social.py"


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
        # Two 750 px panels (black, white) over the 1500 x 500 header: the avatar samples at their real 400 and 48 px.
        self.assertEqual(png_size(build_social.OUT / "crop-check.png"), (1500, 460 + build_social.HEADER_SIZE[1]))

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

    def test_the_image_carries_its_language_and_its_whole_text(self):
        # role="img" hides the children: the name is <title>, the rest of the visible text is <desc>,
        # and the language is on the root, where it also covers the name.
        cases = [(f"profile/header-{lang}.svg", lang, [tagline]) for lang, tagline in build_social.TAGLINE.items()]
        for lang, sample in build_social.SAMPLES.items():
            rest = [sample["kicker"], sample["body"], sample["footer"]]
            cases += [(f"posts/{fmt}-{lang}.svg", lang, rest) for fmt in build_social.FORMATS]
        for rel, lang, rest in cases:
            with self.subTest(svg=rel):
                root = ET.fromstring((build_social.OUT / rel).read_text(encoding="utf-8"))
                self.assertEqual(root.get(XML_LANG), lang)
                self.assertEqual(root.get("role"), "img")
                title, desc = root.find(f"{SVG_NS}title"), root.find(f"{SVG_NS}desc")
                self.assertEqual(root.get("aria-labelledby"), title.get("id"))
                self.assertIsNotNone(desc, "the text beside the title has no accessible equivalent")
                self.assertEqual(root.get("aria-describedby"), desc.get("id"))
                self.assertNotEqual(title.get("id"), desc.get("id"))
                for visible in rest:
                    self.assertIn(visible, desc.text)
        for text in (build_social.avatar_svg(), build_social.post_svg("1x1", {"lang": "en", "title": "Only a title"})):
            root = ET.fromstring(text)
            self.assertIsNone(root.find(f"{SVG_NS}desc"))  # nothing to describe: no empty element, no dangling reference
            self.assertIsNone(root.get("aria-describedby"))
        self.assertIsNone(ET.fromstring(build_social.avatar_svg()).get(XML_LANG))  # a name only, the same in every language

    def test_every_line_is_measured_against_its_width(self):
        for lang, sample in build_social.SAMPLES.items():
            for fmt, (width, _h, margin, _free) in build_social.FORMATS.items():
                root = ET.fromstring(build_social.post_svg(fmt, sample))
                for element in root.iter(f"{SVG_NS}text"):
                    size, weight = float(element.get("font-size")), int(element.get("font-weight"))
                    for span in element.iter(f"{SVG_NS}tspan"):
                        with self.subTest(fmt=fmt, lang=lang, line=span.text):
                            end = float(span.get("x")) + build_social.advance(span.text, size, weight)
                            self.assertLessEqual(end, width - margin)
        # Sixteen capital Ws are fewer characters than the old count allowed, and 1361 px wide at 88 px bold.
        self.assertGreater(build_social.advance("W" * 16, 88, 700), 1080)
        refused = (
            {"title": "W" * 40},  # one word, no place to break it
            {"title": "W" * 16},
            {"title": "x", "body": "M" * 40},
            {"title": "x", "kicker": "release notes for everyone who waited " * 2},  # set in capitals, on one line
            {"title": "x", "footer": "nulavio.net/en/download/" + "a-long-address/" * 5},  # one line, right of the trail
        )
        for extra in refused:
            with self.subTest(post=extra), self.assertRaisesRegex(ValueError, "wid"):
                build_social.post_svg("1x1", {"lang": "en", **extra})
        # Two wide words that the old count kept on one line (17 characters): they take two.
        lines = build_social.wrap("MMMMMMMM MMMMMMMM", 88.0, 904.0, 700)
        self.assertEqual(lines, ["MMMMMMMM", "MMMMMMMM"])
        self.assertEqual(build_social.wrap("il il il il il il il il", 88.0, 904.0, 700), ["il il il il il il il il"])

    def test_the_top_check_uses_the_topmost_line(self):
        # 16:9, six title lines under a kicker: the kicker's 30 px line clears the lockup (its baseline is at
        # 243.6 px, the lockup ends at 156.7 px). The check measured it as an 88 px title line and refused.
        six = {"lang": "en", "kicker": "News", "title": "a\nb\nc\nd\ne\nf"}
        root = ET.fromstring(build_social.post_svg("16x9", six))
        self.assertEqual(len(list(root.iter(f"{SVG_NS}tspan"))), 7)
        with self.assertRaisesRegex(ValueError, "does not fit"):
            build_social.post_svg("16x9", {**six, "title": six["title"] + "\ng"})
        with self.assertRaisesRegex(ValueError, "does not fit"):  # without a kicker the title is the top line
            build_social.post_svg("16x9", {"lang": "en", "title": "a\nb\nc\nd\ne\nf\ng"})

    def test_a_post_is_checked_before_anything_is_written(self):
        good = {"lang": "en", "title": "x"}
        refused = {
            "a list": ["lang", "title"],
            "null": None,
            "a string": "lang title",
            "blank title": {**good, "title": " \n "},
            "empty title": {**good, "title": ""},
            "lang with a slash": {**good, "lang": "en/../../x"},
            "lang with dots": {**good, "lang": ".."},
            "lang with a quote": {**good, "lang": 'en" onload="x'},
            "empty lang": {**good, "lang": ""},
            "NUL": {**good, "title": "a\x00b"},
            "a control character": {**good, "body": "a\x1bb"},
            "a lone surrogate": {**good, "footer": "a\ud800b"},
            "U+FFFE": {**good, "kicker": "a\ufffeb"},
            "a number": {**good, "body": 3},
            "an arrow, which Noto Sans does not have": {**good, "title": "160.0 \u2192 161.0"},
            "a kicker whose capital is not measured": {**good, "kicker": "\u00ff"},
        }
        for what, post in refused.items():
            with self.subTest(post=what), self.assertRaises(ValueError):
                build_social.validate(post)
        for lang in ("en", "pt-BR", "es-419", "zh-Hant-TW"):
            self.assertEqual(build_social.validate({**good, "lang": lang})["lang"], lang)
        spaced = {**good, "kicker": " Notas \t da  versão\n", "body": "ÿ “aspas” — €", "footer": " nulavio.net "}
        kept = build_social.validate(spaced)
        self.assertEqual((kept["kicker"], kept["footer"]), ("Notas da versão", "nulavio.net"))  # one line each

    def run_post(self, post: object, out: Path, *, raw: str | None = None) -> subprocess.CompletedProcess:
        source = out.parent / "post.json"
        source.write_text(raw if raw is not None else json.dumps(post), encoding="utf-8")
        command = [sys.executable, "-I", str(SCRIPT), "--svg-only", "post", "--text", str(source), "--out", str(out)]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_a_refused_post_leaves_the_directory_as_it_was(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            self.assertEqual(self.run_post({"lang": "en", "title": "First"}, out).returncode, 0)
            before = {p.name: p.read_bytes() for p in out.iterdir()}
            self.assertEqual(sorted(before), sorted(f"{f}-en.svg" for f in build_social.FORMATS))
            # Five lines of two ten-letter words fit 16:9 as they are; in 1:1 each wraps, and ten lines do not fit.
            title = "\n".join(["abcdefghij abcdefghij"] * 5)
            build_social.post_svg("16x9", {"lang": "en", "title": title})
            with self.assertRaises(ValueError):
                build_social.post_svg("1x1", {"lang": "en", "title": title})
            bad = (
                ({"lang": "en", "title": title}, None),
                ({"lang": "en/x", "title": "x"}, None),
                (["lang", "title"], None),
                (None, None),
                ({"lang": "en", "title": "a\x00b"}, None),
                (None, "{not json"),
            )
            for post, raw in bad:
                with self.subTest(post=post, raw=raw):
                    done = self.run_post(post, out, raw=raw)
                    self.assertNotEqual(done.returncode, 0)
                    self.assertNotIn("Traceback", done.stderr)
                    self.assertIn("post.json", done.stderr)
                    self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)

    def test_a_failed_rasteriser_leaves_the_directory_as_it_was(self):
        calls = []

        def fails_on_the_third(source: Path, out: Path) -> None:
            calls.append(source.name)
            if len(calls) == 3:
                raise subprocess.CalledProcessError(1, "magick")
            out.write_bytes(b"png")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "16x9-en.svg").write_text("old", encoding="utf-8")
            failing = mock.patch.object(build_social, "rasterise", fails_on_the_third)
            with failing, self.assertRaises(subprocess.CalledProcessError):
                build_social.write_post({"lang": "en", "title": "New"}, out)
            self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, {"16x9-en.svg": b"old"})
            with mock.patch.object(build_social, "rasterise", lambda source, png: png.write_bytes(b"png")):
                written = build_social.write_post({"lang": "en", "title": "New"}, out)
            names = sorted(f"{f}-en.{ext}" for f in build_social.FORMATS for ext in ("svg", "png"))
            self.assertEqual(sorted(p.name for p in out.iterdir()), names)
            self.assertEqual(sorted(p.name for p in written), names)
            self.assertIn("New", (out / "16x9-en.svg").read_text(encoding="utf-8"))

    def test_writing_touches_only_the_social_directory(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_social, "OUT", Path(tmp) / "social"):
            written = build_social.write_all(svg_only=True)
            self.assertTrue(all(Path(tmp) / "social" in p.parents for p in written))


if __name__ == "__main__":
    unittest.main()
