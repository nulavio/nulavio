"""The host steps of the site's captures (#173): compose (scripts/site/capture_site.py) and the scene stills
(scripts/site/scene_stills.py). The capture itself needs the build and runs through the integration runner;
these check what the host does with what it is given, before anything in the tree changes."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
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
        # The manifest is refused when it holds this machine's home, user or host name: fixed values that no
        # fixture contains, so a runner whose user is called `light` or `en` tests the same thing.
        stack.enter_context(unittest.mock.patch.dict(os.environ, {"USER": "nv-test-user-q7"}))
        stack.enter_context(unittest.mock.patch.object(capture_site.Path, "home", lambda: Path("/nv-test-home-q7")))
        name = os.uname()
        uname = type(name)((*name[:1], "nv-test-host-q7", *name[2:]))
        stack.enter_context(unittest.mock.patch.object(capture_site.os, "uname", lambda: uname))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def record(
        self, entries: list[dict], figures: dict | None = None, buildid: str = "20261119020726", complete: bool = True
    ) -> None:
        record = {"schema": 1, "harness": "h", "buildid": buildid, "firefox": "160.0.1", "args": [], "scale": 2,
                  "complete": complete, "dom_changes": [], "left_out": [], "figures": figures or {},
                  "entries": entries}  # fmt: skip
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

    def test_a_capture_that_stopped_is_not_composed(self):
        # Stopped between languages: the first language's scenes are there, the record never says it finished.
        self.record([shot("window-pt-BR-light")], complete=False)
        with self.assertRaises(SystemExit):
            capture_site.compose(self.raw)
        self.assertEqual(self.tree(), {})

    def test_a_write_that_fails_leaves_the_set_as_it_was(self):
        self.record([shot("window-en-US-light"), shot("window-pt-BR-light")])
        self.assertEqual(capture_site.compose(self.raw), 0)
        before = self.tree()
        (self.raw / ("1" * 20 + ".png")).write_bytes(png(400, 60, shade=0x20))
        self.record([shot("window-en-US-light", "1" * 20 + ".png"), shot("window-pt-BR-light", "1" * 20 + ".png")])
        real, calls = Path.write_bytes, []

        def full_disk(path, data):
            calls.append(path)
            if len(calls) == 3:  # after the first picture's master and WebP: the disk is full
                raise OSError(28, "No space left on device")
            return real(path, data)

        with unittest.mock.patch.object(capture_site.Path, "write_bytes", full_disk), self.assertRaises(OSError):
            capture_site.compose(self.raw)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.tree(), before, "no picture replaced, no manifest written, nothing staged left")

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

    def test_strips_of_one_css_width_get_one_pixel_width_wherever_they_start(self):
        # 96.4167 CSS px at 2x: from x=0 the edges rounded apart gave 193 px, from x=12.3 they gave 192 px.
        def at(state, x):
            e = strip(state)
            e["strip"]["cues"] = [{"x": x + 8, "y": 2, "w": 80.4167, "h": 20}]
            return e

        self.record([at("personal", 0), at("protected", 12.3), at("temporary", 50.15)])
        self.assertEqual(capture_site.compose(self.raw), 0)
        self.assertEqual({(f["width"], f["height"]) for f in self.manifest()["files"]}, {(193, 48)})

    def test_strip_cues_are_measured_from_the_bands_own_top(self):
        def low(state, band_y, cue_y):
            e = strip(state)
            e["strip"]["band"].update(y=band_y, h=20)
            e["strip"]["cues"][0].update(y=cue_y, h=16)
            return e

        # A band 8 px down with its cue inside it is cut; a cue that starts above its band, or ends below it, is not.
        self.record([low("personal", 8, 10), low("protected", 8, 10), low("temporary", 8, 11)])
        self.assertEqual(capture_site.compose(self.raw), 0)
        before = self.tree()
        for cue_y in (6, 13):
            with self.subTest(cue_y=cue_y):
                self.record([low("personal", 8, 10), low("protected", 8, 10), low("temporary", 8, cue_y)])
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

    def test_the_time_of_a_still_is_when_the_video_shows_it(self):
        import scene_stills

        # Captures at 0, 6.414 and 6.5 s: the video (30 frames a second) takes the last capture at or before each
        # of its frames, so the one of 6.414 s is on screen from frame 193 (6.433 s) to frame 195 (6.5 s).
        timeline = {"frames": [{"t": 0.0, "file": "0000.png"}, {"t": 6.414, "file": "0001.png"}, {"t": 6.5, "file": "0002.png"}],
                    "cursor": [], "end": 7.0}  # fmt: skip
        self.assertEqual(scene_stills.shown_s(timeline, "0001.png"), [6.433, 6.5])
        # A capture another one replaces before the next video frame is never shown: it cannot be a still.
        timeline["frames"].insert(2, {"t": 6.42, "file": "0003.png"})
        with self.assertRaises(SystemExit):
            scene_stills.shown_s(timeline, "0001.png")

    def test_frames_that_are_not_the_recorders_own_are_refused_before_anything_is_read(self):
        import scene_stills

        manifest = json.loads((scene_stills.CLIPS / "manifest.json").read_text(encoding="utf-8"))
        key, clip = next(iter(manifest["recordings"].items()))
        timeline = {"schema": 1, "scene": clip["scene"], "locale": clip["locale"], "captured": clip["capture"]["utc"],
                    "script_blob": clip["capture"]["script_blob"], "buildid": clip["capture"]["buildid"],
                    "frames": [{"t": 0.0, "file": "0000.png"}], "poster": "0000.png", "scale": 1.5}  # fmt: skip
        with tempfile.TemporaryDirectory() as tmp:
            root, outside = Path(tmp) / "frames", Path(tmp) / "outside.png"
            outside.write_bytes(png(1920, 1200))
            (root / key).mkdir(parents=True)
            for case in ("name", "link", "timeline-link"):
                with self.subTest(case=case):
                    tl = dict(timeline, frames=[{"t": 0.0, "file": "../../outside.png" if case == "name" else "0000.png"}])
                    target = root / key / "timeline.json"
                    target.unlink(missing_ok=True)
                    frame = root / key / "0000.png"
                    frame.unlink(missing_ok=True)
                    if case == "timeline-link":
                        (Path(tmp) / "tl.json").write_text(json.dumps(tl), encoding="utf-8")
                        target.symlink_to(Path(tmp) / "tl.json")
                    else:
                        target.write_text(json.dumps(tl), encoding="utf-8")
                    if case == "link":
                        frame.symlink_to(outside)
                    with unittest.mock.patch.object(scene_stills, "publish") as publish, self.assertRaises(SystemExit):
                        scene_stills.main([str(root)])
                    publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
