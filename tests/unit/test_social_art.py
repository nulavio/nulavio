"""The social media art (#175): generated from the brand sources by one command, in the sizes the networks ask for."""

from __future__ import annotations

import fcntl
import json
import os
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
        for lang in ("en", "pt-BR", "es-419", "zh-Hant-TW", "zh-Hant", "de-CH-1901", "de-1996", "sl-rozaj-biske", "fil"):
            self.assertEqual(build_social.validate({**good, "lang": lang})["lang"], lang)
        # Not a tag BCP 47 can build: two regions, two scripts, a region before a script, a repeated
        # variant, an empty subtag, and the forms this script does not take (extension, private use,
        # grandfathered). Each would have reached xml:lang.
        malformed = ("en-US-GB", "en-Latn-Cyrl", "en-US-Latn", "de-1901-1901", "de-CH-1901-1901", "pt-BR-", "en--US")
        for lang in (*malformed, "en-US-u-ca-gregory", "en-x-priv", "i-klingon", "e", "abcd", "en_US", "\u00ebn", "en-U\uff33"):
            with self.subTest(lang=lang), self.assertRaisesRegex(ValueError, "language tag"):
                build_social.validate({**good, "lang": lang})
        spaced = {**good, "kicker": " Notas \t da  versão\n", "body": "ÿ “aspas” — €", "footer": " nulavio.net "}
        kept = build_social.validate(spaced)
        self.assertEqual((kept["kicker"], kept["footer"]), ("Notas da versão", "nulavio.net"))  # one line each

    def test_a_line_never_breaks_at_a_no_break_space(self):
        # 1:1 at 88 px bold has 904 px: "Download up to 10 GB" breaks before "GB" when the last space is an
        # ordinary one. The no-break space is the author's word that the number and its unit stay together.
        self.assertEqual(build_social.wrap("Download up to 10 GB", 88.0, 904.0, 700), ["Download up to 10", "GB"])
        self.assertEqual(build_social.wrap("Download up to 10\u00a0GB", 88.0, 904.0, 700), ["Download up to", "10\u00a0GB"])
        self.assertEqual(build_social.advance("10\u00a0GB", 88.0, 700), build_social.advance("10 GB", 88.0, 700))
        post = {"lang": "en", "title": "Download up to 10\u00a0GB", "body": "Up to 10\u00a0GB \u00a0a day."}
        text = build_social.post_svg("1x1", post)
        lines = [span.text for span in ET.fromstring(text).iter(f"{SVG_NS}tspan")]
        self.assertEqual(lines, ["Up to 10\u00a0GB \u00a0a day.", "Download up to", "10\u00a0GB"])
        self.assertIn(">10&#160;GB</tspan>", text)  # written as a reference, so that it shows in the file
        self.assertNotIn("\u00a0", text)
        with self.assertRaisesRegex(ValueError, "wider than the card"):  # joined words are one word
            build_social.post_svg("1x1", {"lang": "en", "title": "\u00a0".join(["Download"] * 4)})

    def test_every_line_break_is_a_line_and_other_white_space_is_refused(self):
        for separator in ("\n", "\r\n", "\r", "\u2028", "\u2029"):
            with self.subTest(separator=separator):
                post = build_social.validate({"lang": "en", "title": f"a{separator}b", "body": f"c{separator}d"})
                self.assertEqual((post["title"], post["body"]), ("a\nb", "c\nd"))
                root = ET.fromstring(build_social.post_svg("16x9", {"lang": "en", "title": f"a{separator}b"}))
                self.assertEqual([span.text for span in root.iter(f"{SVG_NS}tspan")], ["a", "b"])
        # White space that is neither a space, a tab nor one of those line breaks would be drawn as a space
        # where its author meant something else (or nothing XML can hold): refused, as the unmeasured are.
        for other in ("\x0b", "\x0c", "\x1c", "\x1f", "\x85", "\u2003", "\u202f", "\u3000", "\ufeff"):
            for key in ("kicker", "title", "body", "footer"):
                with self.subTest(other=other, key=key), self.assertRaisesRegex(ValueError, f"U\\+{ord(other):04X}"):
                    build_social.validate({"lang": "en", "title": "x", key: f"a{other}b"})
        self.assertEqual(build_social.wrap("a\tb  c", 88.0, 904.0, 700), ["a b c"])

    def test_white_space_around_a_text_is_not_a_line(self):
        # Six title lines and a footer fit 16:9 without a body. A body of three spaces was a line of
        # nothing that took 86.4 px and pushed the title into the lockup.
        six = {"lang": "en", "title": "a\nb\nc\nd\ne\nf", "footer": "nulavio.net"}
        plain = build_social.post_svg("16x9", six)
        for body in ("", "   ", " \n\t\n ", "\u00a0", "\r\n"):
            with self.subTest(body=body):
                self.assertEqual(build_social.post_svg("16x9", {**six, "body": body}), plain)
        self.assertEqual(build_social.post_svg("16x9", {**six, "title": "\n" + six["title"] + " \n"}), plain)
        kept = build_social.validate({"lang": "en", "title": "a\n\nb", "body": "\nc\n\nd\n"})
        self.assertEqual((kept["title"], kept["body"]), ("a\n\nb", "c\n\nd"))  # the breaks inside stay

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

    def test_a_failed_rasteriser_leaves_no_new_directory(self):
        def fails(source: Path, png: Path) -> None:
            raise subprocess.CalledProcessError(1, "magick")

        with tempfile.TemporaryDirectory() as tmp:
            for out in (Path(tmp) / "new", Path(tmp) / "a" / "b" / "c"):
                with self.subTest(out=out), mock.patch.object(build_social, "rasterise", fails):
                    with self.assertRaises(subprocess.CalledProcessError):
                        build_social.write_post({"lang": "en", "title": "New"}, out)
                    self.assertEqual(list(Path(tmp).iterdir()), [])
            # The same when the files are made and cannot be moved in.
            out = Path(tmp) / "a" / "b"
            with mock.patch.object(build_social, "publish", side_effect=OSError("no room")), self.assertRaises(OSError):
                build_social.write_post({"lang": "en", "title": "New"}, out, svg_only=True)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            written = build_social.write_post({"lang": "en", "title": "New"}, out, svg_only=True)
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(p.name for p in written))
            self.assertEqual([p.name for p in Path(tmp).rglob(".build_social-*")], [])

    def test_imagemagick_is_given_absolute_paths(self):
        # A relative --out that starts with "-" gave ImageMagick a file name it read as an option.
        seen = []

        def records(source: Path, png: Path) -> None:
            seen.extend((source, png))
            png.write_bytes(b"png")

        with tempfile.TemporaryDirectory() as tmp:
            before = os.getcwd()
            self.addCleanup(os.chdir, before)
            os.chdir(tmp)
            with mock.patch.object(build_social, "rasterise", records):
                written = build_social.write_post({"lang": "en", "title": "New"}, Path("-cards"))
            os.chdir(before)
            self.assertEqual(len(seen), 8)
            for path in seen:
                self.assertTrue(path.is_absolute(), path)
            names = sorted(f"{f}-en.{ext}" for f in build_social.FORMATS for ext in ("svg", "png"))
            self.assertEqual(
                sorted(str(p) for p in written), sorted(f"-cards/{name}" for name in names)
            )  # as the caller wrote it
            self.assertEqual(sorted(p.name for p in (Path(tmp) / "-cards").iterdir()), names)

    def old_post(self, out: Path, names: list[str]) -> dict[str, bytes]:
        out.mkdir()
        for name in names:
            (out / name).write_text(f"old {name}", encoding="utf-8")
        return {p.name: p.read_bytes() for p in out.iterdir()}

    def test_a_directory_in_the_way_is_refused_before_anything_moves(self):
        names = [f"{fmt}-en.svg" for fmt in build_social.FORMATS]
        for in_the_way in ("16x9-en.svg", "1x1-en.svg", "9x16-en.svg"):
            with self.subTest(directory=in_the_way), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out"
                before = self.old_post(out, [name for name in names if name != in_the_way])
                (out / in_the_way).mkdir()
                (out / in_the_way / "kept.txt").write_text("kept", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, f"{in_the_way} in .*a directory"):
                    build_social.write_post({"lang": "en", "title": "New"}, out, svg_only=True)
                self.assertEqual({p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}, before)
                self.assertEqual([p.name for p in (out / in_the_way).iterdir()], ["kept.txt"])
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["out"])
                done = self.run_post({"lang": "en", "title": "New"}, out)  # and the command says so, without a trace
                self.assertEqual(done.returncode, 1)
                self.assertNotIn("Traceback", done.stderr)
                self.assertIn(in_the_way, done.stderr)

    def test_a_move_that_fails_puts_back_what_was_replaced(self):
        names = [f"{fmt}-en.svg" for fmt in build_social.FORMATS]
        replace = os.replace
        # Each file there before takes two moves (the old one aside, the new one in); a file that is new takes one.
        for there_before, failing in ((names, 2), (names, 5), (names, 8), (names[:2], 4), (names[:2], 6), ([], 1), ([], 3)):
            calls = []

            def fails_once(source, destination, failing=failing, calls=calls):
                calls.append(destination)
                if len(calls) == failing:
                    raise OSError("the move failed")
                replace(source, destination)

            with self.subTest(there_before=len(there_before), failing=failing), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out"
                before = self.old_post(out, there_before)
                with (
                    mock.patch.object(build_social.os, "replace", fails_once),
                    self.assertRaisesRegex(OSError, "the move failed"),
                ):
                    build_social.write_post({"lang": "en", "title": "New"}, out, svg_only=True)
                self.assertGreaterEqual(len(calls), failing)
                self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)
                self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["out"])

    def test_two_runs_into_one_directory_are_not_mixed(self):
        names = [f"{fmt}-en.svg" for fmt in build_social.FORMATS]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            before = self.old_post(out, names)
            other_run = os.open(out, os.O_RDONLY)  # what publish holds while it moves its files in
            try:
                fcntl.flock(other_run, fcntl.LOCK_EX)
                with self.assertRaisesRegex(ValueError, "another run is writing"):
                    build_social.write_post({"lang": "en", "title": "New"}, out, svg_only=True)
                self.assertEqual({p.name: p.read_bytes() for p in out.iterdir()}, before)
            finally:
                os.close(other_run)
            build_social.write_post({"lang": "en", "title": "New"}, out, svg_only=True)
            self.assertIn("New", (out / "16x9-en.svg").read_text(encoding="utf-8"))
            self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(names))  # no lock file, nothing left behind

    def test_a_token_that_is_not_written_as_hex_is_refused(self):
        self.assertEqual(build_social.colour("color.primitive.navy.875"), build_social.CANVAS)
        for value in ("rgba(15, 28, 42, 1)", "rgba(15,\x0b28, 42, 1)", "#0F1C2A\n", '#0F1C2A" onload="x', "navy", 5, None):
            refused = self.assertRaisesRegex(ValueError, "color.primitive.navy.875: .*#RRGGBB")
            with self.subTest(value=value), mock.patch.object(build_social, "resolve", return_value=value), refused:
                build_social.colour("color.primitive.navy.875")

    def test_writing_touches_only_the_social_directory(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(build_social, "OUT", Path(tmp) / "social"):
            written = build_social.write_all(svg_only=True)
            self.assertTrue(all(Path(tmp) / "social" in p.parents for p in written))


if __name__ == "__main__":
    unittest.main()
