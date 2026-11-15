"""scripts/perf/run.py: the medians and the change it reports, and how it reads a process tree's memory (#80)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("perf_run", ROOT / "scripts" / "perf" / "run.py")
perf_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(perf_run)


class PerfStatisticsTest(unittest.TestCase):
    def test_change_is_the_builds_median_against_the_baselines(self):
        self.assertAlmostEqual(perf_run.change([110, 100, 120], [100, 90, 110]), 0.10)
        self.assertIsNone(perf_run.change([], [1]))
        self.assertIsNone(perf_run.change([1], [0]))

    def test_the_interval_holds_the_change_and_is_the_same_every_time(self):
        build, baseline = [110.0, 108.0, 112.0, 109.0, 111.0], [100.0, 99.0, 101.0, 100.0, 102.0]
        low, high = perf_run.interval(build, baseline)
        self.assertLess(low, perf_run.change(build, baseline))
        self.assertLess(perf_run.change(build, baseline), high)
        self.assertGreater(low, 0)  # clearly more: 0 is outside
        self.assertEqual(perf_run.interval(build, baseline), (low, high))
        noise = perf_run.interval([100.0, 90.0, 110.0, 95.0, 105.0], [102.0, 92.0, 108.0, 97.0, 103.0])
        self.assertLess(noise[0], 0)
        self.assertGreater(noise[1], 0)  # the same spread on both sides: 0 is inside
        self.assertIsNone(perf_run.interval([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0, 5.0]))  # too few runs to resample

    def test_the_table_names_each_measure_with_both_medians_and_the_change(self):
        results = {"metrics": {"startup_first_ms": {"build": [110.0, 100.0, 120.0], "baseline": [100.0, 90.0, 110.0]}}}
        text = perf_run.table(results)
        self.assertIn("startup_first_ms", text)
        self.assertIn("110.0", text)
        self.assertIn("+10.0 %", text)


class FrameMetricsTest(unittest.TestCase):
    def test_each_scene_gets_its_median_interval_per_run_and_side(self):
        run = {"raw": {"tab_switch": [[16.0, 17.0], [18.0]], "sidebar_collapse": []}, "new_tab_poll_ms": [120.0, 140.0]}
        frames = {"runs": {"build": [run, run], "baseline": [{"raw": {"tab_switch": [[20.0]]}, "new_tab_poll_ms": [150.0]}]}}
        metrics = perf_run.frame_metrics(frames)
        self.assertEqual(metrics["frame_tab_switch_ms"], {"build": [17.0, 17.0], "baseline": [20.0]})
        self.assertEqual(metrics["frame_new_tab_ms"], {"build": [130.0, 130.0], "baseline": [150.0]})
        self.assertEqual(metrics["frame_sidebar_collapse_ms"], {"build": [], "baseline": []})  # no samples, no value
        self.assertIn("frame_dialog_open_ms", metrics)


class FrameScenePartialTest(unittest.TestCase):
    def test_runs_done_before_a_failure_are_kept_with_the_error(self):
        import json
        import tempfile
        from unittest import mock

        def child(command, **kwargs):  # one run written, then the scene script fails
            out = Path(command[command.index("--out") + 1])
            (out / "perf.json").write_text(json.dumps({"runs": {"build": [{"raw": {"tab_switch": [[16.0]]}}]}}))
            return mock.Mock(returncode=1)

        with mock.patch.object(perf_run.subprocess, "run", side_effect=child):
            frames = perf_run.frame_scene_on("b", "a", 2, "9", Path(tempfile.gettempdir()) / "unused")
        self.assertEqual(frames["error"], "frame_scene.py exited with 1")
        self.assertEqual(perf_run.frame_metrics(frames)["frame_tab_switch_ms"], {"build": [16.0], "baseline": []})

        with mock.patch.object(perf_run.subprocess, "run", return_value=mock.Mock(returncode=1)):
            self.assertEqual(perf_run.frame_scene_on("b", "a", 2, "9", Path("unused"))["runs"], {})  # nothing written


class PrivateDisplayTest(unittest.TestCase):
    def test_the_cookie_entry_is_xauths_format_for_any_host(self):
        import struct

        entry = perf_run.xauthority("12", b"\x01" * 16)
        family, rest = struct.unpack(">H", entry[:2])[0], entry[2:]
        fields = []
        while rest:
            size = struct.unpack(">H", rest[:2])[0]
            fields.append(rest[2 : 2 + size])
            rest = rest[2 + size :]
        self.assertEqual(family, 0xFFFF)  # FamilyWild
        self.assertEqual(fields, [b"", b"12", b"MIT-MAGIC-COOKIE-1", b"\x01" * 16])


class PinnedBenchmarkTest(unittest.TestCase):
    def test_an_archive_that_is_not_the_pinned_one_is_refused_and_removed(self):
        import tempfile

        cache = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, cache)
        pin = perf_run.PINNED["speedometer"]
        archive = cache / f"speedometer-{pin['commit']}-{pin['sha256'][:16]}.tar.gz"
        archive.write_bytes(b"not the archive")  # as a download that was replaced or cut
        with self.assertRaises(perf_run.MeasureError):
            perf_run.pinned("speedometer", cache)
        self.assertFalse(archive.exists())
        self.assertFalse((cache / f"speedometer-{pin['commit']}-{pin['sha256'][:16]}").exists())

    def test_an_archive_of_the_pinned_size_with_another_digest_is_refused(self):
        import tempfile

        cache = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, cache)
        pin = perf_run.PINNED["speedometer"]
        archive = cache / f"speedometer-{pin['commit']}-{pin['sha256'][:16]}.tar.gz"
        archive.write_bytes(b"\0" * pin["size"])  # the size alone does not make it the archive
        with self.assertRaises(perf_run.MeasureError):
            perf_run.pinned("speedometer", cache)
        self.assertFalse(archive.exists())
        self.assertFalse((cache / f"speedometer-{pin['commit']}-{pin['sha256'][:16]}").exists())

    def test_the_pinned_archive_is_unpacked_without_its_top_folder(self):
        import hashlib
        import io
        import tarfile
        import tempfile
        from unittest import mock

        cache = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, cache)
        packed = io.BytesIO()
        with tarfile.open(fileobj=packed, mode="w:gz") as tar:
            for name, data in (
                ("Speedometer-abc/index.html", b"<title>s</title>"),
                ("Speedometer-abc/resources/main.mjs", b"//"),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        data = packed.getvalue()
        pin = {"commit": "abc", "url": "unused", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        (cache / f"speedometer-abc-{pin['sha256'][:16]}.tar.gz").write_bytes(data)  # there already: nothing is downloaded
        with mock.patch.dict(perf_run.PINNED, {"speedometer": pin}):
            tree = perf_run.pinned("speedometer", cache)
            self.assertEqual((tree / "index.html").read_bytes(), b"<title>s</title>")
            self.assertTrue((tree / "resources" / "main.mjs").is_file())
            self.assertFalse((tree / "Speedometer-abc").exists())
            self.assertEqual(perf_run.pinned("speedometer", cache), tree)  # verified once, then reused

    def test_an_archive_whose_sha512_differs_is_refused_even_when_its_sha256_matches(self):
        import hashlib
        import tempfile
        from unittest import mock

        cache = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, cache)
        data = b"firefox"
        pin = {"release": "1", "url": "https://x/firefox-1.tar.xz", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        pin["sha512"] = "0" * 128
        archive = cache / f"firefox-1-{pin['sha256'][:16]}.tar.xz"
        archive.write_bytes(data)
        with mock.patch.dict(perf_run.PINNED, {"firefox": pin}), self.assertRaises(perf_run.MeasureError):
            perf_run.pinned("firefox", cache)
        self.assertFalse(archive.exists())

    def test_firefox_is_mozillas_release_archive_with_both_digests(self):
        pin = perf_run.PINNED["firefox"]
        self.assertEqual(
            pin["url"],
            f"https://archive.mozilla.org/pub/firefox/releases/{pin['release']}/linux-x86_64/en-US/firefox-{pin['release']}.tar.xz",
        )
        self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(pin["sha512"], r"^[0-9a-f]{128}$")  # the line of Mozilla's signed SHA512SUMS, for a reader to compare
        self.assertGreater(pin["size"], 0)

    def test_the_table_gets_a_firefox_column_when_firefox_ran(self):
        results = {"metrics": {"startup_first_ms": {"build": [100.0], "baseline": [100.0], "firefox": [150.0]}}}
        text = perf_run.table(results)
        self.assertIn("Firefox (median)", text)
        self.assertIn("150.0", text)
        self.assertNotIn("Firefox", perf_run.table({"metrics": {"x": {"build": [1.0], "baseline": [1.0]}}}))

    def test_each_pin_is_a_commit_with_its_archive_and_digest(self):
        self.assertEqual(set(perf_run.PINNED), {"speedometer", "jetstream", "motionmark", "firefox"})
        for name, pin in perf_run.PINNED.items():
            if name == "firefox":
                continue
            with self.subTest(name=name):
                self.assertRegex(pin["commit"], r"^[0-9a-f]{40}$")
                self.assertEqual(
                    pin["url"], f"https://codeload.github.com/WebKit/{pin['url'].split('/')[4]}/tar.gz/{pin['commit']}"
                )
                self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
                self.assertGreater(pin["size"], 0)

    def test_a_benchmark_that_ends_without_a_number_is_an_error(self):
        for value in (None, float("nan"), float("inf"), 0, -1, "12"):
            with self.subTest(value=value), self.assertRaises(perf_run.MeasureError):
                perf_run.finite("JetStream", value)
        self.assertEqual(perf_run.finite("MotionMark", 412.5), 412.5)


@unittest.skipUnless(Path("/proc/self/smaps_rollup").exists(), "needs Linux /proc")
class PerfProcessTreeTest(unittest.TestCase):
    def test_the_tree_holds_children_and_grandchildren_and_their_memory_is_read(self):
        # A child that starts a grandchild, as the engine starts its fork server and the fork server its pages.
        child = subprocess.Popen(["sh", "-c", "sleep 30 & wait"], start_new_session=True)
        self.addCleanup(child.wait)
        self.addCleanup(os.killpg, child.pid, 9)  # the child and its grandchild, one group
        pids = []
        for _ in range(100):
            pids = perf_run.instance_pids(child.pid)
            if len(pids) >= 2:
                break
            subprocess.run(["sleep", "0.05"], check=True)
        self.assertIn(child.pid, pids)
        self.assertGreaterEqual(len(pids), 2, pids)
        self.assertNotIn(os.getpid(), pids)
        total, unreadable = perf_run.pss_kib(pids)
        self.assertGreater(total, 0)
        self.assertEqual(unreadable, 0)

    def test_a_process_that_ended_is_neither_memory_nor_unreadable(self):
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        self.assertEqual(perf_run.pss_kib([gone.pid]), (0, 0))


if __name__ == "__main__":
    unittest.main()
