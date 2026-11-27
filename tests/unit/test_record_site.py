"""The site's recording pipeline (scripts/site/record_site.py, #173): its timeline arithmetic, and that its capture
step stays out of the integration suite. The capture itself needs the build and runs through the integration
runner; composing needs Pillow and ffmpeg and is checked by running it (docs/design/site-redesign.md)."""

from __future__ import annotations

import fnmatch
import typing
import struct
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "site"))

import record_site  # noqa: E402


def png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\0" + b"\0\0\0" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


class EaseTest(unittest.TestCase):
    def test_starts_and_ends_still_and_never_overshoots(self):
        self.assertEqual(record_site.ease(0), 0)
        self.assertEqual(record_site.ease(1), 1)
        self.assertAlmostEqual(record_site.ease(0.5), 0.5)
        values = [record_site.ease(i / 100) for i in range(101)]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(0 <= v <= 1 for v in values))
        self.assertLess(record_site.ease(0.05), 0.05)  # slow start
        self.assertGreater(record_site.ease(0.95), 0.95)  # slow stop
        self.assertEqual((record_site.ease(-1), record_site.ease(2)), (0, 1))


class CursorTest(unittest.TestCase):
    KEYS: typing.ClassVar = [
        {"t": 1.0, "xy": [0, 0]},
        {"t": 2.0, "xy": [100, 50]},
        {"t": 3.0, "xy": None},
        {"t": 4.0, "xy": [10, 10]},
    ]

    def test_hidden_before_the_first_key_and_after_a_hide(self):
        self.assertIsNone(record_site.cursor_at(self.KEYS, 0.5))
        self.assertIsNone(record_site.cursor_at(self.KEYS, 3.5))
        self.assertIsNone(record_site.cursor_at([], 1))

    def test_eased_between_keys_and_still_on_a_key(self):
        self.assertEqual(record_site.cursor_at(self.KEYS, 1.0), (0, 0))
        self.assertEqual(record_site.cursor_at(self.KEYS, 1.5), (50, 25))
        x, _ = record_site.cursor_at(self.KEYS, 1.25)
        self.assertLess(x, 25)  # eased, not linear
        self.assertEqual(record_site.cursor_at(self.KEYS, 2.5), (100, 50))  # the next key hides it: stays put till then
        self.assertEqual(record_site.cursor_at(self.KEYS, 9), (10, 10))

    def test_moves_of_the_recorder_hold_still_between_moves(self):
        rec = record_site.Recorder.__new__(record_site.Recorder)
        rec.t, rec.keys, rec.xy, rec.scale, rec.clicks = 0.0, [], None, 1.5, []
        rec.move((300, 300), 0.5)
        rec.hold(2.0)
        rec.move((600, 300), 0.5)
        rec.click()
        self.assertEqual(record_site.cursor_at(rec.keys, 1.5), (300, 300))
        self.assertEqual(record_site.cursor_at(rec.keys, 3.0), (600, 300))
        self.assertEqual(rec.clicks, [{"t": 3.0, "xy": [600, 300]}])
        self.assertLess(rec.keys[0]["xy"][0], 300)  # the first move comes in from somewhere, not out of nowhere


class FramesTest(unittest.TestCase):
    def test_the_last_frame_taken_at_or_before_the_time_is_shown(self):
        frames = [{"t": 0.0, "file": "a"}, {"t": 1.0, "file": "b"}, {"t": 1.5, "file": "c"}]
        self.assertEqual([record_site.frame_at(frames, t) for t in (0, 0.99, 1.0, 1.4, 7)], ["a", "a", "b", "b", "c"])

    def test_ripples_run_for_their_length_only(self):
        clicks = [{"t": 1.0, "xy": [5, 6]}]
        self.assertEqual(record_site.ripples_at(clicks, 0.9), [])
        self.assertEqual(record_site.ripples_at(clicks, 1.0), [(5, 6, 0.0)])
        self.assertEqual(record_site.ripples_at(clicks, 1.01 + record_site.CLICK_LENGTH), [])

    def test_duration_holds_the_last_frame(self):
        timeline = {"frames": [{"t": 0, "file": "a"}, {"t": 4.0, "file": "b"}], "cursor": [{"t": 4.5, "xy": None}]}
        self.assertEqual(record_site.duration_of(timeline), 4.5 + record_site.TAIL)
        # A hold after the last frame (the result left on screen) counts.
        self.assertEqual(record_site.duration_of({**timeline, "end": 7.0}), 7.0 + record_site.TAIL)

    def test_the_short_loop_lasts_five_seconds_at_most_from_the_highlight(self):
        self.assertEqual(record_site.loop_window({"highlight": 2.0}, 12.0), (2.0, 2.0 + record_site.LOOP_MAX))
        self.assertEqual(record_site.loop_window({"highlight": 9.0}, 12.0), (9.0, 12.0))
        self.assertEqual(record_site.loop_window({"highlight": None}, 12.0), (12.0 - record_site.LOOP_MAX, 12.0))
        self.assertEqual(record_site.loop_window({}, 3.0), (0.0, 3.0))
        self.assertLessEqual(record_site.LOOP_MAX, 5.0)  # WCAG 2.2.2: what moves by itself stops within 5 s

    def test_png_size_is_read_from_the_header(self):
        self.assertEqual(record_site.png_size(png(3, 2)), (3, 2))
        with self.assertRaises(ValueError):
            record_site.png_size(b"GIF89a" + bytes(30))


class CaptionsTest(unittest.TestCase):
    def test_webvtt(self):
        text = record_site.webvtt([{"t": 0, "text": "Um"}, {"t": 2.5, "text": "Dois --> três"}], 3661.0049)
        self.assertEqual(
            text.splitlines(),
            ["WEBVTT", "", "1", "00:00:00.000 --> 00:00:02.500", "Um", "", "2", "00:00:02.500 --> 01:01:01.005",
             "Dois → três"],
        )  # fmt: skip

    def test_every_scene_has_captions_in_both_languages_with_the_same_count(self):
        for scene in record_site.SCENES:
            counts = {locale: len(record_site.TEXT[locale]["cap"][scene]) for locale in record_site.LOCALES}
            self.assertEqual(len(set(counts.values())), 1, (scene, counts))
            self.assertGreaterEqual(counts["pt-BR"], 2)


class OutsideTheSuiteTest(unittest.TestCase):
    def test_the_capture_step_is_run_by_name_only(self):
        """tests/run.py integration discovers test*.py: the recordings never run in CI, the release or a plain suite run."""
        shim = ROOT / "tests" / "integration" / "record_site_scenes.py"
        self.assertTrue(shim.is_file())
        self.assertFalse(fnmatch.fnmatch(shim.name, "test*.py"))
        self.assertIn("record_site_scenes.py", (ROOT / "scripts" / "site" / "record_site.sh").read_text(encoding="utf-8"))

    def test_fixture_pages_carry_only_their_own_text(self):
        for locale in record_site.LOCALES:
            for path in record_site.TEXT[locale]["pages"]:
                page = record_site.fixture_page(locale, path).decode()
                self.assertNotIn("http", page.replace('lang="', ""))  # no link, image or font from anywhere
                self.assertNotIn("<script", page)
            self.assertIsNone(record_site.fixture_page(locale, "/nowhere"))


if __name__ == "__main__":
    unittest.main()
