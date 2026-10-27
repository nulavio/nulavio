"""Temporary profiles (launcher/nulavio_launcher/temporary.py): where, lifecycle, deletion limits."""

from __future__ import annotations

import fcntl
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import cli, paths, temporary  # noqa: E402

MOUNTINFO = """\
22 1 259:3 / / rw,relatime shared:1 - btrfs /dev/nvme0n1p3 rw,seclabel
29 55 0:89 / /run/user/1000 rw,nosuid,nodev,relatime shared:966 - tmpfs tmpfs rw,mode=700,uid=1000
31 22 0:40 / /tmp rw,nosuid,nodev shared:2 - tmpfs tmpfs rw,seclabel
40 22 0:50 / /mnt/my\\040disk rw,relatime - ext4 /dev/sdb1 rw
41 29 0:51 / /run/user/1000/doc rw,nosuid,nodev,relatime - fuse.portal portal rw
"""


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def guard_is_held(path: Path) -> bool:
    fd = os.open(path / temporary.GUARD, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


class StorageDetectionTest(unittest.TestCase):
    def test_filesystem_type_uses_the_longest_mount_point(self):
        with mock.patch("os.path.realpath", side_effect=lambda p: str(p)):
            self.assertEqual(temporary.filesystem_type(Path("/run/user/1000/nulavio/t"), MOUNTINFO), "tmpfs")
            self.assertEqual(temporary.filesystem_type(Path("/run/user/1000/doc/x"), MOUNTINFO), "fuse.portal")
            self.assertEqual(temporary.filesystem_type(Path("/home/u/.cache/nulavio"), MOUNTINFO), "btrfs")
            self.assertEqual(temporary.filesystem_type(Path("/mnt/my disk/p"), MOUNTINFO), "ext4")
            self.assertEqual(temporary.filesystem_type(Path("/tmpfoo/p"), MOUNTINFO), "btrfs")  # not under /tmp

    def test_swap_on_disk(self):
        header = "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"
        self.assertFalse(temporary.swap_on_disk(header))
        self.assertFalse(temporary.swap_on_disk(header + "/dev/zram0 partition 8388604 0 100\n"))
        self.assertTrue(temporary.swap_on_disk(header + "/dev/zram0 partition 1 0 100\n/swapfile file 1 0 -2\n"))
        self.assertTrue(temporary.swap_on_disk(header + "/dev/nvme0n1p2 partition 1 0 -2\n"))


class TempHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self._env = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.home), "LANG": "pt_BR.UTF-8"})
        self._env.start()
        self.old_umask = os.umask(0o022)
        self.created: list[temporary.Temporary] = []

    def tearDown(self):
        for temp in self.created:
            temp.release()
        os.umask(self.old_umask)
        self._env.stop()
        self._tmp.cleanup()

    def make(self) -> temporary.Temporary:
        temp = temporary.create()
        self.created.append(temp)
        return temp


class RuntimeDirTest(unittest.TestCase):
    def test_xdg_runtime_dir_only_when_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir(mode=0o700)
            env = {"XDG_RUNTIME_DIR": str(run), "NULAVIO_HOME": ""}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(paths.runtime_home(), run / "nulavio")
                os.chmod(run, 0o755)
                self.assertIsNone(paths.runtime_home())  # someone else could list or race it
                os.chmod(run, 0o700)
                os.environ["XDG_RUNTIME_DIR"] = "relative/run"
                self.assertIsNone(paths.runtime_home())
                link = Path(tmp) / "link"
                link.symlink_to(run)
                os.environ["XDG_RUNTIME_DIR"] = str(link)
                self.assertIsNone(paths.runtime_home())

    def test_without_a_runtime_dir_the_profile_goes_to_the_cache_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_RUNTIME_DIR": "", "NULAVIO_HOME": "", "XDG_CACHE_HOME": str(Path(tmp) / "cache")}
            with mock.patch.dict(os.environ, env):
                self.assertEqual(temporary.root(), Path(tmp) / "cache" / "nulavio" / "temporary")


class CreateTest(TempHome):
    def test_create_makes_a_private_profile_with_its_marker_prefs_and_guard(self):
        temp = self.make()
        self.assertEqual(temp.path.parent, self.home / "runtime" / "temporary")
        self.assertTrue(temp.path.name.startswith("tmp-"))
        self.assertEqual(mode(temp.path), 0o700)
        marker = json.loads((temp.path / temporary.MARKER).read_text())
        self.assertEqual(marker["schema"], 1)
        self.assertEqual(marker["in_memory"], temp.in_memory)
        self.assertEqual(mode(temp.path / temporary.MARKER), 0o600)
        prefs_js = (temp.path / "prefs.js").read_text()
        self.assertIn('user_pref("nulavio.profile.temporary", true);', prefs_js)
        self.assertIn('user_pref("signon.rememberSignons", false);', prefs_js)
        self.assertIn('user_pref("browser.download.manager.addToRecentDocs", false);', prefs_js)
        settings = json.loads((temp.path / "nulavio" / "settings.json").read_text())
        self.assertTrue(settings["temporary"])
        self.assertEqual(settings["locale"], "pt-BR")
        self.assertTrue(guard_is_held(temp.path))
        self.assertNotEqual(self.make().path, temp.path)

    def test_no_pref_weakens_a_protection(self):
        for name in temporary.PREFS:
            self.assertFalse(
                any(word in name for word in ("sandbox", "safebrowsing", "security.", "network.", "extensions.", "remote.")),
                name,
            )


class DeleteTest(TempHome):
    def test_remove_deletes_a_closed_temporary_profile(self):
        temp = self.make()
        (temp.path / "cookies.sqlite").write_bytes(b"x")
        temporary.remove(temp.path)
        self.assertFalse(temp.path.exists())

    def test_remove_refuses_anything_that_is_not_a_temporary_profile(self):
        temp = self.make()
        other = self.home / "data" / "profiles" / "default"
        other.mkdir(parents=True)
        (other / temporary.MARKER).write_text("{}")
        with self.assertRaises(temporary.TemporaryError):
            temporary.remove(other)  # marker, but outside the temporary root
        bare = temp.path.parent / "tmp-nomarker"
        bare.mkdir()
        with self.assertRaises(temporary.TemporaryError):
            temporary.remove(bare)
        link = temp.path.parent / "tmp-link"
        link.symlink_to(other)
        with self.assertRaises(temporary.TemporaryError):
            temporary.remove(link)
        self.assertTrue(other.exists() and bare.exists())

    def test_remove_refuses_while_the_engine_runs(self):
        temp = self.make()
        os.symlink(f"127.0.0.1:+{os.getpid()}", temp.path / "lock")
        with self.assertRaises(temporary.TemporaryError) as caught:
            temporary.remove(temp.path)
        self.assertEqual(caught.exception.code, "in-use")
        self.assertTrue(temp.path.exists())

    def test_cleanup_removes_only_orphans(self):
        held, orphan, running, stale = (self.make() for _ in range(4))  # create() cleans up too: make all first
        orphan.release()  # its reaper was killed
        running.release()
        os.symlink(f"127.0.0.1:+{os.getpid()}", running.path / "lock")  # but its engine still runs
        stale.release()
        os.symlink("127.0.0.1:+999999999", stale.path / "lock")  # engine crashed long ago
        half = held.path.parent / "tmp-halfcreated"
        half.mkdir()
        removed = temporary.cleanup()
        self.assertEqual(removed, 2)
        self.assertTrue(held.path.exists())
        self.assertTrue(running.path.exists())
        self.assertTrue(half.exists())
        self.assertFalse(orphan.path.exists())
        self.assertFalse(stale.path.exists())

    def test_reap_unused_profile_after_grace(self):
        temp = self.make()
        self.assertEqual(temporary.reap(temp.path, temp.guard_fd, grace=0.2, poll=0.05), "unused")
        self.assertFalse(temp.path.exists())

    def test_reap_waits_for_the_engine_then_deletes(self):
        temp = self.make()
        engine = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(engine.kill)
        os.symlink(f"127.0.0.1:+{engine.pid}", temp.path / "lock")
        started = time.monotonic()

        def close_engine():
            time.sleep(0.5)
            engine.kill()
            engine.wait()

        import threading

        threading.Thread(target=close_engine, daemon=True).start()
        self.assertEqual(temporary.reap(temp.path, temp.guard_fd, grace=5, poll=0.05), "closed")
        self.assertGreaterEqual(time.monotonic() - started, 0.5)
        self.assertFalse(temp.path.exists())


class ApiTest(TempHome):
    def test_create_starts_a_reaper_that_holds_the_guard(self):
        spawned = []
        with mock.patch.object(temporary, "spawn_reaper", side_effect=lambda t: spawned.append(t.path)):
            answer = temporary.api_request({"op": "create"})
        self.assertEqual(spawned, [Path(answer["path"])])
        self.assertEqual(set(answer), {"path", "inMemory", "swapOnDisk"})
        self.assertFalse(guard_is_held(Path(answer["path"])))  # the mock reaper did not take it over

    def test_real_reaper_inherits_the_guard_and_deletes_after_grace(self):
        temp = self.make()
        reaper = temporary.spawn_reaper(temp, grace=1)
        temp.release()
        self.created.remove(temp)
        time.sleep(0.3)
        self.assertTrue(temp.path.exists())
        self.assertTrue(guard_is_held(temp.path))  # the reaper keeps it
        self.assertEqual(reaper.wait(timeout=20), 0)
        self.assertFalse(temp.path.exists())

    def test_cli_api_errors_are_codes(self):
        for raw in ("not json", "[]", json.dumps({"op": "delete", "path": "/"}), "x" * 5000):
            out = io.StringIO()
            with mock.patch.object(sys, "stdin", io.StringIO(raw)), redirect_stdout(out):
                self.assertEqual(cli.main(["temporary", "api"]), 0)
            self.assertEqual(json.loads(out.getvalue())["error"], "bad-request")

    def test_run_temporary_deletes_the_profile_when_the_engine_exits_or_fails(self):
        seen = []

        def fake_run(args, eng, prof, supervise=False):
            self.assertTrue(supervise)  # the launcher waits for the engine
            self.assertTrue(guard_is_held(prof.path))
            seen.append(prof.path)
            if len(seen) == 2:
                raise OSError("engine failed")
            return 0

        engine = mock.Mock(builtin_theme=True)
        with mock.patch.object(cli.engine_mod, "find_engine", return_value=engine), \
             mock.patch.object(cli.engine_mod, "check_supported"), mock.patch.object(cli, "_run", side_effect=fake_run), \
             mock.patch.object(cli.extensions, "install") as install, redirect_stdout(io.StringIO()):  # fmt: skip
            self.assertEqual(cli.main(["run", "--temporary"]), 0)
            self.assertEqual(cli.main(["run", "--temporary"]), 1)  # the error is reported, the profile still goes
        install.assert_not_called()  # the Nulavio build installs uBlock Origin by policy
        self.assertEqual(len(seen), 2)
        self.assertFalse(any(path.exists() for path in seen))

    def test_run_temporary_installs_the_pinned_filter_for_distribution_firefox(self):
        engine = mock.Mock(builtin_theme=False)
        with mock.patch.object(cli.engine_mod, "find_engine", return_value=engine), \
             mock.patch.object(cli.engine_mod, "check_supported"), mock.patch.object(cli, "_run", return_value=0), \
             mock.patch.object(cli.extensions, "install") as install, redirect_stdout(io.StringIO()):  # fmt: skip
            self.assertEqual(cli.main(["run", "--temporary"]), 0)
        entry, target = install.call_args.args
        self.assertEqual(entry.key, "ublock-origin")
        self.assertEqual(target.parent, self.home / "runtime" / "temporary")

    def test_cli_clean(self):
        temp = self.make()
        temp.release()
        self.created.remove(temp)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(["temporary", "clean"]), 0)
        self.assertIn("1 temporary profile(s) deleted", out.getvalue())
        self.assertFalse(temp.path.exists())


if __name__ == "__main__":
    unittest.main()
