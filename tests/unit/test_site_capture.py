"""The host steps of the site's captures (#173): compose (scripts/site/capture_site.py) and the scene stills
(scripts/site/scene_stills.py). The capture itself needs the build and runs through the integration runner;
these check what the host does with what it is given, before anything in the tree changes."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import struct
import sys
import tempfile
import unittest
import unittest.mock
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "site"), str(ROOT / "tests" / "lib"), str(ROOT / "launcher")]

import capture_site  # noqa: E402

PILLOW = importlib.util.find_spec("PIL") is not None


def png(width: int, height: int, shade: int = 0x80) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\0" + bytes([shade] * 3) * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def strip(state: str, locale: str = "en-US", theme: str = "light", raw: str = "0" * 20 + ".png") -> dict:
    cues = [{"x": 10, "y": 2, "w": 60, "h": 20}]
    return {
        "name": f"band-{state}-strip-{locale}-{theme}",
        "raw": raw,
        "crop_css": None,
        "strip": {"cues": cues, "band": {"x": 0, "y": 0, "w": 200, "h": 24}, "align": "start"},
        "meta": {"figure": "fig-2", "state": state, "locale": locale, "theme": theme},
        "date": "2026-11-27T00:00:00Z",
    }


def shot(name: str, raw: str = "0" * 20 + ".png") -> dict:
    crop = {"x": 0, "y": 0, "w": 50, "h": 20}
    return {
        "name": name,
        "raw": raw,
        "crop_css": crop,
        "strip": None,
        "meta": {"figure": "fig-1"},
        "date": "2026-11-27T00:00:00Z",
    }


@unittest.skipUnless(PILLOW, "compose needs Pillow")
class ComposeTest(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.tmp = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.shots, self.masters, self.raw = self.tmp / "shots", self.tmp / "masters", self.tmp / "raw"
        for path in (self.shots, self.masters, self.raw):
            path.mkdir()
        (self.raw / ("0" * 20 + ".png")).write_bytes(png(400, 60))
        stack.enter_context(unittest.mock.patch.object(capture_site, "SHOTS", self.shots))
        stack.enter_context(unittest.mock.patch.object(capture_site, "MASTERS", self.masters))
        stack.enter_context(unittest.mock.patch.object(capture_site, "git", lambda *a: "" if a[0] == "status" else "abc1234"))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def record(self, entries: list[dict], figures: dict | None = None, buildid: str = "20261119020726") -> None:
        record = {"schema": 1, "harness": "h", "buildid": buildid, "firefox": "160.0.1", "args": [], "scale": 2,
                  "dom_changes": [], "left_out": [], "figures": figures or {}, "entries": entries}  # fmt: skip
        (self.raw / "captures.json").write_text(json.dumps(record), encoding="utf-8")

    def manifest(self) -> dict:
        return json.loads((self.shots / "manifest.json").read_text(encoding="utf-8"))

    def tree(self) -> dict[str, bytes]:
        return {
            str(p.relative_to(self.tmp)): p.read_bytes()
            for p in sorted(self.tmp.rglob("*"))
            if p.is_file() and "raw" not in p.parts
        }

    def test_a_run_of_one_language_keeps_the_others_words(self):
        self.record([shot("window-en-US-light"), shot("window-pt-BR-light")],
                    {"fig-1": {"en-US": {"transcript": "On screen"}, "pt-BR": {"transcript": "Na tela"}}})  # fmt: skip
        self.assertEqual(capture_site.compose(self.raw), 0)
        self.record([shot("window-pt-BR-light")], {"fig-1": {"pt-BR": {"transcript": "Na tela, de novo"}}})
        self.assertEqual(capture_site.compose(self.raw), 0)
        self.assertEqual(
            self.manifest()["figures"]["fig-1"],
            {"en-US": {"transcript": "On screen"}, "pt-BR": {"transcript": "Na tela, de novo"}},
        )

    def test_names_that_are_not_a_captures_shape_change_nothing(self):
        for bad in ({"name": "../../outside"}, {"name": "/tmp/x"}, {"raw": "../secret.png"}, {"raw": "/etc/x.png"}):
            with self.subTest(bad=bad):
                self.record([{**shot("window-en-US-light"), **bad}])
                with self.assertRaises(SystemExit):
                    capture_site.compose(self.raw)
                self.assertEqual(self.tree(), {})

    def test_a_capture_that_fails_half_way_leaves_the_set_as_it_was(self):
        self.record([shot("window-en-US-light"), shot("window-pt-BR-light")])
        self.assertEqual(capture_site.compose(self.raw), 0)
        before = self.tree()
        (self.raw / ("1" * 20 + ".png")).write_bytes(png(400, 60, shade=0x20))
        # A new picture for the first, then a screenshot that is not there: nothing is written.
        self.record([shot("window-en-US-light", "1" * 20 + ".png"), shot("window-pt-BR-light", "2" * 20 + ".png")])
        with self.assertRaises(FileNotFoundError):
            capture_site.compose(self.raw)
        self.assertEqual(self.tree(), before)

    def test_a_cut_outside_the_screenshot_is_refused(self):
        self.record([{**shot("window-en-US-light"), "crop_css": {"x": 150, "y": 0, "w": 100, "h": 20}}])
        with self.assertRaises(SystemExit):
            capture_site.compose(self.raw)
        self.assertEqual(self.tree(), {})

    def test_the_landing_strips_are_cut_together_or_not_at_all(self):
        self.record([strip("personal"), strip("protected"), strip("temporary")])
        self.assertEqual(capture_site.compose(self.raw), 0)
        sizes = {(f["width"], f["height"]) for f in self.manifest()["files"]}
        self.assertEqual(len(sizes), 1, "one width and one height for the three")
        before = self.tree()
        self.record([strip("protected")])  # alone, its width could differ from the two it would sit with
        with self.assertRaises(SystemExit):
            capture_site.compose(self.raw)
        self.assertEqual(self.tree(), before)


class CaptureCommandTest(unittest.TestCase):
    def test_an_unknown_selection_is_an_argument_error_before_anything_runs(self):
        with unittest.mock.patch.object(capture_site, "capture") as capture:
            for only in ("guards", "window,", ""):
                with self.subTest(only=only), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        capture_site.main(["--only", only])
                    self.assertEqual(raised.exception.code, 2)
            capture.assert_not_called()


@unittest.skipUnless(PILLOW, "the stills need Pillow")
class SceneStillsTest(unittest.TestCase):
    def test_a_frame_of_another_size_or_a_rectangle_outside_it_is_refused(self):
        import scene_stills

        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "frame.png"
            frame.write_bytes(png(1920, 1200))
            _, size = scene_stills.cut(frame, (0, 0, 800, 500), 1.5, False, [1920, 1200])
            self.assertEqual(size, (1200, 750))
            with self.assertRaises(SystemExit):  # Pillow would pad the rest of the rectangle
                scene_stills.cut(frame, (0, 0, 800, 500), 1.5, False, [2560, 1600])
            with self.assertRaises(SystemExit):
                scene_stills.cut(frame, (900, 0, 800, 500), 1.5, False, [1920, 1200])


if __name__ == "__main__":
    unittest.main()
