"""Optional outer confinement with bubblewrap (launcher/nulavio_launcher/confine.py, docs/security/phase5-spikes.md)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import confine  # noqa: E402


def bwrap_works() -> bool:
    try:
        confine.check()
        return True
    except confine.ConfineError:
        return False


class WrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-confine-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.profile = self.home / ".local/share/nulavio/data/profiles/p"
        self.engine = self.tmp / "engine"
        for folder in (self.profile, self.engine, self.home / ".config/fontconfig"):
            folder.mkdir(parents=True)

    def wrap(self, **kwargs):
        return confine.wrap(["/engine/nulavio", "--profile", str(self.profile)], profile_dir=self.profile,
                            engine_dir=self.engine, home=self.home, binary="/usr/bin/bwrap", **kwargs)  # fmt: skip

    def pairs(self, args: list[str], option: str) -> list[str]:
        return [args[i + 1] for i, a in enumerate(args[: args.index("--")]) if a == option]

    def test_home_is_hidden_and_only_profile_and_downloads_are_writable(self):
        args = self.wrap()
        self.assertEqual(args[:4], ["/usr/bin/bwrap", "--ro-bind", "/", "/"])
        self.assertIn(str(self.home.resolve()), self.pairs(args, "--tmpfs"))
        self.assertEqual(self.pairs(args, "--bind")[0], "/proc")
        writable = [p for p in self.pairs(args, "--bind") if p != "/proc" and not p.startswith("/run/user")]
        self.assertEqual(writable, [str(self.profile.resolve()), str((self.home / "Downloads").resolve())])
        self.assertTrue((self.home / "Downloads").is_dir())
        self.assertEqual(args[args.index("--") + 1 :], ["/engine/nulavio", "--profile", str(self.profile)])

    def test_read_only_settings_only_when_present(self):
        read_only = self.pairs(self.wrap(), "--ro-bind")
        self.assertIn(str(self.home.resolve() / ".config/fontconfig"), read_only)
        self.assertNotIn(str(self.home.resolve() / ".mozilla/native-messaging-hosts"), read_only)
        self.assertIn(str(self.engine.resolve()), read_only)
        for path in read_only:
            self.assertFalse(path.endswith((".ssh", ".gnupg", ".aws")), path)

    def test_engine_sandboxes_are_left_alone(self):
        args = self.wrap(supervised=True)
        for option in ("--unshare-pid", "--unshare-user", "--disable-userns", "--unshare-all", "--cap-add"):
            self.assertNotIn(option, args)  # PIDs stay real (profile lock); user namespaces stay available
        self.assertIn("--new-session", args)
        self.assertIn("--die-with-parent", args)
        self.assertNotIn("--die-with-parent", self.wrap())

    def test_downloads_folder_from_the_desktop_never_the_home_folder(self):
        config = self.home / ".config"
        (config / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Transferências"\n')
        self.assertEqual(confine.download_dir(self.home), self.home / "Transferências")
        (config / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/"\n')
        self.assertEqual(confine.download_dir(self.home), self.home / "Downloads")
        (config / "user-dirs.dirs").write_text("# nothing\n")
        self.assertEqual(confine.download_dir(self.home), self.home / "Downloads")

    def test_missing_bubblewrap_is_an_error_never_an_unconfined_start(self):
        with mock.patch.object(confine, "bwrap", return_value=None), self.assertRaises(confine.ConfineError):
            confine.check()


class CheckTest(unittest.TestCase):
    """Each answer of the check before a confined start (#282)."""

    def check(self, returncode: int, stderr: str = ""):
        answer = subprocess.CompletedProcess([], returncode, "", stderr)
        with mock.patch.object(confine, "bwrap", return_value="/usr/bin/bwrap"), \
             mock.patch.object(confine.subprocess, "run", return_value=answer) as run:  # fmt: skip
            try:
                return confine.check(), run.call_args.args[0]
            except confine.ConfineError as exc:
                return exc, run.call_args.args[0]

    def test_the_probe_runs_inside_bubblewrap_and_asks_for_the_engines_namespaces(self):
        binary, args = self.check(0)
        self.assertEqual(binary, "/usr/bin/bwrap")
        self.assertEqual(args[0], "/usr/bin/bwrap")
        self.assertEqual(args[args.index("--") + 1 :], [sys.executable, "-I", "-c", confine.NAMESPACE_PROBE])
        # CLONE_NEWUSER, CLONE_NEWPID and CLONE_NEWNET, in one call, as the engine's content sandbox needs them.
        self.assertIn("0x10000000 | 0x20000000 | 0x40000000", confine.NAMESPACE_PROBE)

    def test_namespaces_refused_inside_bubblewrap_refuse_the_start_and_say_the_trade_off(self):
        error, _ = self.check(confine.NAMESPACES_REFUSED, "Operation not permitted\n")
        self.assertIsInstance(error, confine.ConfineError)
        message = str(error)
        self.assertIn("not starting", message)
        self.assertIn("Operation not permitted", message)
        self.assertIn("bwrap-userns-restrict", message)
        self.assertIn("whole home folder", message)  # what running without --confined costs

    def test_bubblewrap_that_cannot_run_is_an_error(self):
        error, _ = self.check(1, "bwrap: No permissions to create new namespace\n")
        self.assertIsInstance(error, confine.ConfineError)
        self.assertIn("bubblewrap cannot run here (bwrap: No permissions to create new namespace)", str(error))
        self.assertNotIn("not starting", str(error))


@unittest.skipUnless(bwrap_works(), "bubblewrap is not installed or cannot create namespaces here")
class RealBubblewrapTest(unittest.TestCase):
    def test_the_probe_fails_where_nested_namespaces_are_denied(self):
        # Ubuntu's AppArmor denies them by capability; --disable-userns denies them by count: both refuse.
        args = ["bwrap", "--unshare-user", "--disable-userns", "--ro-bind", "/", "/", "--dev", "/dev", "--",
                sys.executable, "-I", "-c", confine.NAMESPACE_PROBE]  # fmt: skip
        probe = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
        if "--disable-userns" in probe.stderr:
            self.skipTest("this bubblewrap has no --disable-userns")
        self.assertEqual(probe.returncode, confine.NAMESPACES_REFUSED, probe.stderr)

    def test_a_confined_program_sees_only_the_profile_and_downloads(self):
        tmp = Path(tempfile.mkdtemp(prefix="nv-confine-real-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        home, profile = tmp / "home", tmp / "home/.local/share/nulavio/data/profiles/p"
        profile.mkdir(parents=True)
        (home / ".ssh").mkdir()
        (home / ".ssh" / "id_fake").write_text("artificial, not a key\n")
        script = (
            f"test -e {home}/.ssh/id_fake && echo secret-visible;"
            f"touch {profile}/written && echo profile-ok;"
            f"touch {home}/Downloads/written && echo downloads-ok;"
            f"touch {home}/elsewhere 2>/dev/null; test -e {home}/elsewhere && echo home-writable-but-in-memory;"
            f"test -e {Path.home()}/.bashrc -o -e {ROOT}/README.md && echo real-home-visible; true"
        )
        args = confine.wrap(["/bin/sh", "-c", script], profile_dir=profile, engine_dir=Path("/usr/bin"), home=home)
        out = subprocess.run(args, capture_output=True, text=True, timeout=30, check=True).stdout.split()
        self.assertNotIn("secret-visible", out)
        self.assertNotIn("real-home-visible", out)
        self.assertIn("profile-ok", out)
        self.assertIn("downloads-ok", out)
        self.assertTrue((profile / "written").exists())
        self.assertTrue((home / "Downloads" / "written").exists())
        self.assertFalse((home / "elsewhere").exists(), "a write outside the bound folders reached the disk")


if __name__ == "__main__":
    unittest.main()
