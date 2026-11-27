"""The site's recording pipeline (scripts/site/record_site.py, #173): its timeline arithmetic, the checks compose
makes before it publishes, that the committed samples are what the media policy says, and that the capture step
stays out of the integration suite. The capture itself needs the build and runs through the integration runner;
drawing and encoding need Pillow and ffmpeg and are checked by running them (docs/design/site-redesign.md)."""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import typing
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


def webp(loops: int, durations: list[int]) -> bytes:
    """The container of an animated WebP, with no image data: enough for what record_site reads from it."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return kind + struct.pack("<I", len(data)) + data + b"\0" * (len(data) & 1)

    frames = b"".join(chunk(b"ANMF", bytes(12) + ms.to_bytes(3, "little") + b"\0" + b"x") for ms in durations)
    body = b"WEBP" + chunk(b"VP8X", bytes(10)) + chunk(b"ANIM", bytes(4) + struct.pack("<H", loops)) + frames
    return b"RIFF" + struct.pack("<I", len(body)) + body


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

    def test_the_video_is_never_shorter_than_the_scene_and_its_length_is_a_whole_number_of_frames(self):
        timeline = {"frames": [{"t": 0, "file": "0000.png"}], "cursor": [], "end": 9.719}  # 10.319 s with the tail
        self.assertEqual(record_site.frame_count(timeline, 30), 310)  # 10.333 s: what the manifest and the captions say
        self.assertEqual(record_site.frame_count(timeline, 2), 21)
        self.assertEqual(record_site.frame_count({**timeline, "end": 9.4}, 30), 300)  # exactly 10 s stays 10 s

    def test_the_short_loop_never_runs_longer_than_five_seconds_at_any_frame_rate(self):
        for fps in (7, 24, 25, 30, 50, 60):
            indices, frame_ms = record_site.loop_frames((2.0, 7.0), fps)
            self.assertLessEqual(len(indices) * frame_ms, 5000, fps)
            self.assertGreater(len(indices) * frame_ms, 4800, fps)
            self.assertTrue(all(2.0 * fps <= i < 7.0 * fps for i in indices), fps)
        self.assertEqual(record_site.loop_frames((2.0, 7.0), 30), (list(range(60, 210, 3)), 100))
        self.assertEqual(len(record_site.loop_frames((2.0, 7.0), 25)[0]), 62)  # 63 frames of 80 ms would be 5.04 s
        self.assertEqual(record_site.loop_frames((9.0, 10.0), 30), ([270, 273, 276, 279, 282, 285, 288, 291, 294, 297], 100))

    def test_a_loop_is_read_back_from_its_file(self):
        self.assertEqual(record_site.webp_animation(webp(1, [100, 2400, 2500])), (1, 5000))
        self.assertEqual(record_site.webp_animation(webp(0, [80] * 63)), (0, 5040))  # endless and too long: refused
        with self.assertRaises(ValueError):
            record_site.webp_animation(png(1, 1))
        with self.assertRaises(ValueError):
            record_site.webp_animation(b"RIFF\x04\0\0\0WEBP")  # a still image

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

    def test_a_caption_that_cannot_be_read_in_its_time_is_reported(self):
        cues = [
            {"t": 0.0, "text": "In the “Personal” profile, the work intranet's address is typed."},
            {"t": 3.995, "text": "A rule sends that site to the “Work” profile."},  # 45 characters in about 1 s
            {"t": 5.019, "text": "The link opens in the “Work” window, and the band says the rule did it."},
        ]
        fast = record_site.fast_cues(cues, 10.333)
        self.assertEqual(len(fast), 1)
        self.assertIn("A rule sends that site", fast[0])
        self.assertEqual(record_site.fast_cues(cues, 6.0), [fast[0], record_site.fast_cues(cues[2:], 6.0)[0]])  # the last one too
        self.assertEqual(record_site.fast_cues([{"t": 0.0, "text": "x" * 40}], 2.0), [])  # 20 a second is the limit
        self.assertEqual(len(record_site.fast_cues([{"t": 0.0, "text": "x" * 41}], 2.0)), 1)
        self.assertEqual(len(record_site.fast_cues([{"t": 1.0, "text": "x"}, {"t": 1.0, "text": "y" * 3}], 9.0)), 1)

    def test_a_scene_whose_captions_cannot_be_read_is_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = record_site.Recorder(Path(tmp), "link-routed", "en-US")
            rec.caption("A rule sends that site to the “Work” profile.")
            rec.hold(1.0)
            with self.assertRaisesRegex(RuntimeError, "too briefly"):
                rec.save("", {})
            self.assertFalse((rec.dir / "timeline.json").exists())

    def test_every_scene_has_captions_in_both_languages_with_the_same_count(self):
        for scene in record_site.SCENES:
            counts = {locale: len(record_site.TEXT[locale]["cap"][scene]) for locale in record_site.LOCALES}
            self.assertEqual(len(set(counts.values())), 1, (scene, counts))
            self.assertGreaterEqual(counts["pt-BR"], 2)


class ComposeChecksTest(unittest.TestCase):
    """What compose checks before it writes anything to its output directory."""

    TIMELINE: typing.ClassVar = {
        "schema": 1,
        "scene": "link-routed",
        "locale": "en-US",
        "frames": [{"t": 0, "file": "0000.png"}],
        "poster": "0000.png",
    }

    def test_a_timeline_names_only_this_scripts_scenes_and_frames(self):
        record_site.check_timeline(self.TIMELINE)
        for change in (
            {"scene": "../../site/index"},
            {"locale": "en-US/../.."},
            {"frames": [{"t": 0, "file": "../../../etc/hostname"}]},
            {"frames": [{"t": 0, "file": "/etc/hostname"}]},
            {"poster": "../0000.png"},
            {"frames": []},
            {"schema": 2},
        ):
            with self.assertRaises(ValueError, msg=change):
                record_site.check_timeline({**self.TIMELINE, **change})

    def test_no_timeline_is_an_error_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp) / "artifacts", Path(tmp) / "out"
            (root / "recordings" / "link-routed-en-US").mkdir(parents=True)
            (root / "recordings" / "link-routed-en-US" / "timeline.json").write_text("{}", encoding="utf-8")
            said = io.StringIO()
            with contextlib.redirect_stderr(said):  # the artifact root instead of its recordings/ directory
                self.assertEqual(record_site.compose(root, out, 1280, 800, 30, 2_000_000), 2)
            self.assertIn("timeline.json", said.getvalue())
            self.assertFalse(out.exists())

    def test_personal_values_are_found_where_they_can_be_and_fixed_text_is_not_mistaken_for_one(self):
        manifest = '{"locale": "en-US", "harness": "ci/containers/fedora-release-itest", "notes": ["a work profile"]}'
        seen = ["On screen: the address “http://localhost:36017/intranet” is typed; its data is encrypted."]
        found = record_site.personal_values
        self.assertEqual(found(manifest, seen, "/home/someone", "en", "fedora"), [])  # parts of the fixed text
        self.assertEqual(found(manifest, seen, "/home/someone", "work", "localhost"), [])  # only what was read counts
        self.assertEqual(found(manifest, seen, "/home/someone", "someone", "localhost.localdomain"), [])
        self.assertEqual(found(manifest + "/home/someone/x", seen, "/home/someone", "", ""), ["/home/someone"])
        self.assertEqual(found(manifest, [*seen, "the band reads “someone · desk-7”"], "/root", "someone", "desk-7"),
                         ["someone", "desk-7"])  # fmt: skip
        self.assertEqual(found(manifest, ["the address “http://desk-7.example:1/” is typed"], "/", "", "desk-7"), [])
        self.assertEqual(found(manifest, ["encrypted"], "", "en", "crypt"), [])  # a word, not a part of one

    def test_a_capture_run_starts_from_an_empty_directory(self):
        """A run that fails before any scene leaves no timeline of an earlier run for compose to publish."""

        class NoEngine:
            @staticmethod
            def nulavio_engine():
                return None

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recordings"
            (out / "link-routed-en-US").mkdir(parents=True)
            (out / "link-routed-en-US" / "timeline.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                record_site.Scenes(NoEngine, out)
            self.assertEqual(list(out.iterdir()), [])


class SamplesTest(unittest.TestCase):
    """The committed samples are what the media policy (docs/design/site-redesign.md) says: read from the files."""

    DIR = ROOT / "docs" / "design" / "recordings" / "2026-11"

    def setUp(self):
        self.manifest = json.loads((self.DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_every_scene_is_there_in_both_languages_with_the_files_the_manifest_lists(self):
        keys = {f"{scene}-{locale}" for scene in record_site.SCENES for locale in record_site.LOCALES}
        self.assertEqual(set(self.manifest["recordings"]), keys)
        listed = {"manifest.json"}
        for key, recording in self.manifest["recordings"].items():
            self.assertEqual({f["file"] for f in recording["files"]},
                             {f"{key}{end}" for end in (".webm", ".mp4", "-loop.webp", "-poster.webp", ".vtt")})  # fmt: skip
            for described in recording["files"]:
                data = (self.DIR / described["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), described["sha256"], described["file"])
                self.assertLessEqual(len(data), self.manifest["budget_bytes_per_file"], described["file"])
                listed.add(described["file"])
        self.assertEqual({p.name for p in self.DIR.iterdir()}, listed)  # nothing left over from another run

    def test_loops_play_once_and_stop_within_five_seconds(self):
        for key, recording in self.manifest["recordings"].items():
            loops, total = record_site.webp_animation((self.DIR / f"{key}-loop.webp").read_bytes())
            self.assertEqual(loops, 1, key)
            self.assertLessEqual(total, 5000, key)
            self.assertEqual(total, recording["loop_ms"], key)
            start, stop = recording["loop_s"]
            self.assertTrue(start <= recording["cuts"][-1]["t"] < stop, key)  # the loop shows the window that opens

    def test_captions_last_to_the_end_of_the_video_and_can_be_read(self):
        for key, recording in self.manifest["recordings"].items():
            end = recording["duration_s"]
            self.assertAlmostEqual(end * recording["fps"], round(end * recording["fps"]), places=2, msg=key)
            self.assertEqual(record_site.fast_cues(recording["captions"], end), [], key)
            track = (self.DIR / f"{key}.vtt").read_text(encoding="utf-8")
            self.assertEqual(track, record_site.webvtt(recording["captions"], end), key)
            self.assertIn(f"--> {record_site.vtt_time(end)}", track.splitlines()[-2], key)

    def test_each_recording_says_what_captured_it_and_what_composed_it(self):
        self.assertNotIn("commit", self.manifest)  # no revision is claimed for the footage as a whole
        for key, recording in self.manifest["recordings"].items():
            self.assertRegex(recording["capture"]["script_blob"], r"^[0-9a-f]{40}$", key)
            self.assertRegex(recording["capture"]["utc"], r"^\d{4}-\d\d-\d\dT", key)
            self.assertRegex(recording["capture"]["buildid"], r"^\d{14}$", key)
            self.assertRegex(recording["composed"]["commit"], r"^[0-9a-f]{7,}$", key)


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
                self.assertNotIn("@", page)  # no address of anyone
                self.assertNotIn("url(", page)
            self.assertIsNone(record_site.fixture_page(locale, "/nowhere"))

    def test_fixture_pages_have_something_on_them_and_the_same_shape_in_both_languages(self):
        shapes = {}
        for locale in record_site.LOCALES:
            pages = record_site.TEXT[locale]["pages"]
            self.assertEqual(len(pages), 5)
            for path, (site, title, lead, blocks) in pages.items():
                self.assertTrue(site and title and lead, path)
                page = record_site.fixture_page(locale, path).decode()
                self.assertIn("<table>", page)
                self.assertIn("<ul>", page)
                self.assertGreaterEqual(sum(len(rows) for _heading, rows in blocks), 7, path)
                for _heading, rows in blocks:  # a table's rows all have its header's cells
                    self.assertEqual(len({len(row) if isinstance(row, tuple) else 0 for row in rows}), 1, path)
            shapes[locale] = [[(type(rows[0]), len(rows)) for _heading, rows in page[3]] for page in pages.values()]
        self.assertEqual(shapes["pt-BR"], shapes["en-US"])

    def test_the_wrapper_keeps_the_captures_when_a_step_fails_and_makes_its_cache_directory(self):
        """Run for real with an install directory that has no build: the integration runner refuses it before any
        container or engine starts."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "not" / "there" / "yet"
            done = subprocess.run(
                ["bash", str(ROOT / "scripts" / "site" / "record_site.sh"), str(Path(tmp) / "no-build")],
                env={**os.environ, "XDG_CACHE_HOME": str(cache)},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertIn("has no nulavio executable", done.stderr)
            kept = list(cache.glob("nulavio-record.*"))
            self.assertEqual(len(kept), 1, done.stderr)
            self.assertIn(f"the captures are kept in {kept[0]}/recordings", done.stderr)


if __name__ == "__main__":
    unittest.main()
