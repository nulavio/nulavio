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
import unittest.mock
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

    def test_the_short_loop_shows_the_window_the_scene_cuts_to_however_late_it_opened(self):
        """An unlock may take up to 25 s on a slow host: the loop then starts later, so the window still gets its part."""
        shows, longest = record_site.LOOP_SHOWS, record_site.LOOP_MAX
        cut = {"highlight": 6.0, "cuts": [{"t": 9.0}]}
        self.assertEqual(record_site.loop_window(cut, 13.0), (6.0, 11.0))  # the cut is early enough: from the highlight
        late = {"highlight": 6.0, "cuts": [{"t": 2.0}, {"t": 24.0}]}  # the last cut is the one that counts
        start, stop = record_site.loop_window(late, 28.0)
        self.assertEqual((start, stop), (24.0 + shows - longest, 24.0 + shows))
        self.assertTrue(start <= 24.0 <= stop - shows)
        self.assertGreaterEqual(shows, 1.0)

    def test_the_video_is_never_shorter_than_the_scene_and_its_length_is_a_whole_number_of_frames(self):
        timeline = {"frames": [{"t": 0, "file": "0000.png"}], "cursor": [], "end": 9.719}  # 10.319 s with the tail
        self.assertEqual(record_site.frame_count(timeline), 310)  # 10.333 s: what the manifest and the captions say
        self.assertEqual(record_site.frame_count({**timeline, "end": 9.4}), 300)  # exactly 10 s stays 10 s

    def test_the_short_loop_is_ten_frames_a_second_inside_its_window(self):
        self.assertEqual((record_site.FPS, record_site.LOOP_STEP, record_site.LOOP_MS), (30, 3, 100))  # 10 a second at most
        self.assertEqual(record_site.loop_frames((2.0, 7.0)), list(range(60, 210, 3)))  # 50 frames of 100 ms: 5 s
        self.assertEqual(record_site.loop_frames((9.0, 10.0)), [270, 273, 276, 279, 282, 285, 288, 291, 294, 297])
        # A window that starts between two frames starts at the next one (frame 92 is at 3.067 s, before the highlight),
        # and ends before the first frame at or after its end.
        self.assertEqual(record_site.loop_frames((3.07, 8.07)), list(range(93, 243, 3)))
        self.assertEqual(record_site.loop_frames((3.07, 3.5)), [93, 96, 99, 102])
        self.assertEqual(len(record_site.loop_frames((0.0, 60.0))), 50)  # never more than 5 s

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
        # Measured as the WebVTT file says it, in whole milliseconds: 1.2 - 1.0 is a little less than 0.2 in floating point.
        self.assertEqual(record_site.fast_cues([{"t": 1.0, "text": "four"}], 1.2), [])
        self.assertEqual(len(record_site.fast_cues([{"t": 1.0, "text": "fives"}], 1.2)), 1)

    def test_a_scene_whose_captions_cannot_be_read_is_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = record_site.Recorder(Path(tmp), "link-routed", "en-US")
            rec.caption("A rule sends that site to the “Work” profile.")
            rec.hold(1.0)
            with self.assertRaisesRegex(RuntimeError, "too briefly"):
                rec.save("", {})
            self.assertEqual(list(rec.dir.iterdir()), [])

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

    def test_a_timeline_is_the_one_of_its_directory_and_names_only_this_scripts_frames(self):
        record_site.check_timeline(self.TIMELINE, "link-routed", "en-US")
        for change in (
            {"scene": "profile-opens"},  # another scene's timeline in this scene's directory
            {"locale": "pt-BR"},
            {"scene": "../../site/index"},
            {"frames": [{"t": 0, "file": "../../../etc/hostname"}]},
            {"frames": [{"t": 0, "file": "/etc/hostname"}]},
            {"poster": "../0000.png"},
            {"frames": []},
            {"schema": 2},
        ):
            with self.assertRaises(ValueError, msg=change):
                record_site.check_timeline({**self.TIMELINE, **change}, "link-routed", "en-US")

    def test_a_file_of_the_capture_is_a_regular_file_never_a_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene, elsewhere = Path(tmp) / "link-routed-en-US", Path(tmp) / "elsewhere"
            scene.mkdir()
            elsewhere.mkdir()
            (scene / "0000.png").write_bytes(png(1, 1))
            (elsewhere / "0000.png").write_bytes(png(1, 1))
            self.assertEqual(record_site.captured(scene / "0000.png"), scene / "0000.png")
            (scene / "0001.png").symlink_to(elsewhere / "0000.png")
            (Path(tmp) / "linked-scene").symlink_to(elsewhere)
            for path in (scene / "0001.png", Path(tmp) / "linked-scene" / "0000.png", scene / "0002.png", scene):
                with self.assertRaises(ValueError, msg=path):
                    record_site.captured(path)

    def test_a_capture_with_a_scene_missing_is_not_composed_and_nothing_is_written(self):
        """The set is made whole or not at all: no scene of an earlier run is kept beside the new ones."""
        with tempfile.TemporaryDirectory() as tmp:
            root, out = Path(tmp) / "recordings", Path(tmp) / "out"
            for scene in record_site.SCENES:
                for locale in record_site.LOCALES:
                    (root / f"{scene}-{locale}").mkdir(parents=True)
                    (root / f"{scene}-{locale}" / "timeline.json").write_text("{}", encoding="utf-8")
            (root / "link-routed-pt-BR" / "timeline.json").rename(root / "link-routed-pt-BR" / "timeline.json.part")
            out.mkdir()
            (out / "manifest.json").write_text("as it was", encoding="utf-8")
            said = io.StringIO()
            with contextlib.redirect_stderr(said):
                self.assertEqual(record_site.compose(root, out), 2)
                self.assertEqual(record_site.compose(Path(tmp), out), 2)  # the artifact root, not its recordings/
            self.assertIn("for link-routed-pt-BR:", said.getvalue())
            self.assertEqual([p.name for p in out.iterdir()], ["manifest.json"])
            self.assertEqual((out / "manifest.json").read_text(encoding="utf-8"), "as it was")

    def test_compose_takes_the_captures_directory_and_nothing_else(self):
        """No frame rate, size, budget or output directory to choose: nothing to validate."""
        said = io.StringIO()
        for extra in (["--out", "x"], ["--fps", "60"], ["--width", "0"], ["--budget", "1"], ["second-directory"]):
            with contextlib.redirect_stderr(said), self.assertRaises(SystemExit, msg=extra):
                record_site.main(["compose", "captures", *extra])

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


class TeardownTest(unittest.TestCase):
    """A scene's teardown: every step runs whatever the others did, and only a case that passed leaves a timeline."""

    def record(self, tmp: str, cleanup_fails: bool, unmount_fails: bool = False):
        done = []

        home = Path(tmp) / "session"

        class Session:
            tmp = home

            def cleanup(self):
                done.append("session")
                if cleanup_fails:
                    raise RuntimeError("the session could not be cleaned up")

        class Fixtures:
            def __init__(self, _locale):
                pass

            def close(self):
                done.append("fixtures")

        def scene(rec, _session, _fixtures, _locale, others):
            others.append(unittest.mock.Mock(quit=unittest.mock.Mock(side_effect=OSError("gone"))))
            rec.size, rec.scale = (2, 2), 1.5
            rec.frames.append({"t": 0.0, "file": "0000.png"})
            return "On screen: nothing."

        (home / "home" / "Banking.vault").mkdir(parents=True)
        scenes = record_site.Scenes.__new__(record_site.Scenes)
        scenes.out, scenes.meta = Path(tmp) / "recordings", {}
        scenes.session = lambda _locale: Session()
        scenes.link_routed = scene
        unmount = unittest.mock.Mock(side_effect=OSError("no fusermount3") if unmount_fails else None)
        with (
            unittest.mock.patch.object(record_site, "Fixtures", Fixtures),
            unittest.mock.patch.object(record_site.subprocess, "run", unmount),
        ):
            try:
                scenes.record("link-routed", "en-US")
                error = None
            except (RuntimeError, OSError) as raised:
                error = raised
        self.assertEqual(unmount.call_args.args[0][:3], ["fusermount3", "-u", "-z"])
        return error, done, sorted(p.name for p in (scenes.out / "link-routed-en-US").iterdir())

    def test_a_scene_that_passed_and_was_torn_down_leaves_its_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            error, done, files = self.record(tmp, cleanup_fails=False)
            self.assertIsNone(error)
            self.assertEqual(done, ["session", "fixtures"])
            self.assertEqual(files, ["timeline.json"])
            timeline = json.loads((Path(tmp) / "recordings" / "link-routed-en-US" / "timeline.json").read_text(encoding="utf-8"))
            self.assertIn(record_site.FIXTURE_NOTE, timeline["notes"])

    def test_a_teardown_that_fails_leaves_no_timeline_and_still_closes_the_session_and_the_fixture_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            error, done, files = self.record(tmp, cleanup_fails=True)
            self.assertIsInstance(error, RuntimeError)
            self.assertEqual(done, ["session", "fixtures"])
            self.assertEqual(files, ["timeline.json.part"])  # compose reads timeline.json only
        with tempfile.TemporaryDirectory() as tmp:
            error, done, files = self.record(tmp, cleanup_fails=False, unmount_fails=True)
            self.assertIsInstance(error, OSError)
            self.assertEqual(done, ["session", "fixtures"])  # after the unmount could not even start
            self.assertEqual(files, ["timeline.json.part"])


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
            cut = recording["cuts"][-1]["t"]  # the loop shows the window that opens, for a second at least
            self.assertTrue(start <= cut <= stop - record_site.LOOP_SHOWS, key)

    def test_captions_last_to_the_end_of_the_video_and_can_be_read(self):
        for key, recording in self.manifest["recordings"].items():
            end = recording["duration_s"]
            self.assertEqual(recording["fps"], record_site.FPS, key)
            # A whole number of frames, written as compose writes it: to the millisecond.
            self.assertEqual(round(round(end * record_site.FPS) / record_site.FPS, 3), end, key)
            self.assertEqual(record_site.fast_cues(recording["captions"], end), [], key)
            track = (self.DIR / f"{key}.vtt").read_text(encoding="utf-8")
            self.assertEqual(track, record_site.webvtt(recording["captions"], end), key)
            self.assertIn(f"--> {record_site.vtt_time(end)}", track.splitlines()[-2], key)

    def test_the_cut_says_what_its_real_seconds_include(self):
        """#928: the seconds cut are not all start-up or routing; the script's own preparation and pause are in them."""
        self.assertEqual(self.manifest["edits"], record_site.EDITS)
        cut = next(edit for edit in record_site.EDITS if "nothing is recorded" in edit)
        self.assertIn("content blocker", cut)
        self.assertIn(f"fixed {record_site.ROUTED_SETTLE} s pause", cut)

    def test_the_cut_says_where_its_seconds_start_and_what_the_blocker_check_shows(self):
        """#928 round 2: the timer starts after the last filmed frame of the window cut from, and some start-up or
        routing happens before it; the blocker check only sees that no tab is marked late, not that it is installed."""
        self.assertEqual(self.manifest["edits"], record_site.EDITS)
        cut = next(edit for edit in record_site.EDITS if "nothing is recorded" in edit)
        self.assertIn("the real seconds cut count from that last frame", cut)
        self.assertIn("while the window the video cuts from was still filmed is not in them", cut)
        self.assertIn("does not show that the blocker is installed", cut)
        self.assertNotIn("content blocker was ready", cut)

    def test_each_recording_says_what_captured_it_and_what_composed_it(self):
        self.assertNotIn("commit", self.manifest)  # no revision is claimed for the footage as a whole
        for key, recording in self.manifest["recordings"].items():
            self.assertRegex(recording["capture"]["script_blob"], r"^[0-9a-f]{40}$", key)
            self.assertRegex(recording["capture"]["utc"], r"^\d{4}-\d\d-\d\dT", key)
            self.assertRegex(recording["capture"]["buildid"], r"^\d{14}$", key)
            self.assertRegex(recording["composed"]["commit"], r"^[0-9a-f]{7,}$", key)

    def test_each_recording_notes_what_the_script_arranged_for_neutrality(self):
        """A window's own first page and Settings' provider list never show: the recording says what was done instead."""
        for key, recording in self.manifest["recordings"].items():
            self.assertIn(record_site.FIXTURE_NOTE, recording["notes"], key)
            in_settings = recording["scene"] in ("profile-opens", "protected-unlocks")
            self.assertEqual(record_site.SETTINGS_NOTE in recording["notes"], in_settings, key)


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

    WRAPPER = "scripts/site/record_site.sh"  # as the documentation writes it: by its path from the checkout

    def wrapper(self, tmp: str, *args: str, cwd: Path = ROOT, path: str | None = None):
        """Run for real. `cache` has a space in its name, and CDPATH is set, as a maintainer's shell may have them."""
        cache = Path(tmp) / "not there" / "yet"
        env = {**os.environ, "XDG_CACHE_HOME": str(cache), "CDPATH": ".", "PATH": path or os.environ["PATH"]}
        wrapper = self.WRAPPER if cwd == ROOT else str(ROOT / self.WRAPPER)
        done = subprocess.run(["bash", wrapper, *args], cwd=cwd, env=env, capture_output=True, text=True, check=False)
        return done, list(cache.glob("nulavio-record.*"))

    def test_the_wrapper_keeps_the_captures_when_the_capture_fails_and_makes_its_cache_directory(self):
        """With an install directory that has no build: the integration runner refuses it before any container or engine
        starts."""
        with tempfile.TemporaryDirectory() as tmp:
            done, kept = self.wrapper(tmp, str(Path(tmp) / "no-build"))
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertIn("has no nulavio executable", done.stderr)
            self.assertEqual(len(kept), 1, done.stderr)
            self.assertIn(f"the capture failed (status 2); its files are kept in {kept[0]}/recordings", done.stderr)
            self.assertNotIn("compose them again", done.stderr)  # a capture that failed is not composed

    def test_the_wrapper_takes_the_install_directory_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args in ((), (tmp, "docs/design/recordings/elsewhere")):
                done, kept = self.wrapper(tmp, *args)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("usage: record_site.sh <install-dir>", done.stderr)
                self.assertEqual(kept, [])

    def test_the_documented_command_starts_the_capture_on_the_install_directory_and_says_how_to_compose_again(self):
        """`scripts/site/record_site.sh <install-dir>`, with the directory that holds the executable, from another
        directory and by a relative path, reaches the container with that directory as the build. podman is a stand-in
        that records its arguments and captures nothing, so compose then refuses and the wrapper prints the command that
        composes again, which must run as pasted."""
        with tempfile.TemporaryDirectory() as tmp:
            install, bin_dir = Path(tmp) / "-install dir", Path(tmp) / "bin"
            install.mkdir()
            bin_dir.mkdir()
            (install / "nulavio").write_text("#!/bin/sh\n", encoding="utf-8")
            (install / "nulavio").chmod(0o755)
            (bin_dir / "podman").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{tmp}/podman.args"\n', encoding="utf-8")
            (bin_dir / "podman").chmod(0o755)
            path = f"{bin_dir}:{os.environ['PATH']}"
            done, kept = self.wrapper(tmp, "./-install dir", cwd=Path(tmp), path=path)
            self.assertEqual(done.returncode, 2, done.stderr)
            args = (Path(tmp) / "podman.args").read_text(encoding="utf-8").splitlines()
            self.assertIn(f"{install}:/opt/nulavio-built:ro", args)
            self.assertIn(f"{ROOT}:/src:ro", args)
            self.assertEqual(args[-1], "record_site_scenes.py")
            self.assertIn(f"{kept[0]}:/artifacts", args)
            self.assertIn("the compose failed (status 2)", done.stderr)
            again = done.stderr.split("compose them again with: ")[1].splitlines()[0]
            self.assertIn(str(ROOT / "scripts" / "site" / "record_site.py"), again)
            retried = subprocess.run(["bash", "-c", again], cwd=tmp, capture_output=True, text=True, check=False)
            self.assertEqual(retried.returncode, 2, retried.stderr)
            self.assertIn(f"no timeline.json under {kept[0]}/recordings for", retried.stderr)


if __name__ == "__main__":
    unittest.main()
