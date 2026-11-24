"""Optional outer confinement with bubblewrap (launcher/nulavio_launcher/confine.py, docs/security/phase5-spikes.md)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import confine  # noqa: E402


def listen(path: Path) -> socket.socket:
    """A listening Unix socket at `path`, closed when the test ends."""
    path.parent.mkdir(parents=True, exist_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(4)
    return server


def bwrap_runs() -> bool:
    """bubblewrap is installed and can run a program here (the probe's answer is not asked)."""
    binary = confine.bwrap()
    if not binary:
        return False
    return subprocess.run([binary, "--ro-bind", "/", "/", "--dev", "/dev", "--", "/bin/true"],
                          capture_output=True, timeout=20, check=False).returncode == 0  # fmt: skip


class WrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="nv-confine-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.profile = self.home / ".local/share/nulavio/data/profiles/p"
        self.engine = self.tmp / "engine"
        for folder in (self.profile, self.engine, self.home / ".config/fontconfig"):
            folder.mkdir(parents=True)
        self.runtime = self.tmp / "run"
        self.runtime.mkdir(mode=0o700)
        # The host's session must not decide what these tests see.
        env = {"XDG_RUNTIME_DIR": str(self.runtime), "NULAVIO_HOME": str(self.tmp / "nulavio-home"), "DISPLAY": ""}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for variable in ("WAYLAND_DISPLAY", "DISPLAY"):
            os.environ.pop(variable, None)
        self.addCleanup(lambda: [s.close() for s in self.sockets])
        self.sockets: list[socket.socket] = []

    def socket(self, path: Path) -> Path:
        self.sockets.append(listen(path))
        return path

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
        writable = [p for p in self.pairs(args, "--bind") if p != "/proc"]
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

    def test_runtime_folder_is_hidden_and_only_display_and_sound_come_back(self):
        wayland = self.socket(self.runtime / "wayland-7")
        kept = [wayland, self.socket(self.runtime / "pipewire-0"), self.socket(self.runtime / "pulse/native")]
        for name in ("bus", "systemd/private", "pipewire-0-manager", "ssh-agent.socket", "gnupg/S.gpg-agent"):
            self.socket(self.runtime / name)
        (self.runtime / "nulavio/temporary/tmp-0123456789ab").mkdir(parents=True)
        os.environ["WAYLAND_DISPLAY"] = "wayland-7"
        args = self.wrap()
        self.assertIn(str(self.runtime.resolve()), self.pairs(args, "--tmpfs"))
        at = args.index(str(self.runtime.resolve()))
        self.assertEqual(args[at - 3 : at], ["--perms", "0700", "--tmpfs"], "still private inside")
        from_run = [p for o in ("--bind", "--ro-bind") for p in self.pairs(args, o) if p.startswith(str(self.runtime))]
        self.assertEqual(sorted(from_run), sorted(str(p) for p in kept), "only the display and sound sockets")
        self.assertNotIn(str(self.runtime / "pulse/native"), self.pairs(args, "--bind"), "put back read-only")
        for variable in ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "XAUTHORITY"):
            self.assertIn(variable, self.pairs(args, "--unsetenv"))

    def test_everything_is_hidden_before_anything_is_put_back(self):
        # A temporary profile lives in the runtime folder: an empty folder mounted after it would hide it.
        profile = self.runtime / "nulavio/temporary/tmp-0123456789ab"
        profile.mkdir(parents=True)
        args = confine.wrap(["/engine/nulavio"], profile_dir=profile, engine_dir=self.engine, home=self.home,
                            binary="/usr/bin/bwrap")  # fmt: skip
        options = args[: args.index("--")]
        hides = [i for i, a in enumerate(options) if a == "--tmpfs"]
        put_back = [i for i, a in enumerate(options) if a in ("--bind", "--ro-bind") and options[i + 1] not in ("/", "/proc")]
        self.assertTrue(hides and put_back)
        self.assertLess(max(hides), min(put_back))
        self.assertIn(str(profile.resolve()), self.pairs(args, "--bind"))

    def test_no_x_server_and_an_x11_only_session_is_refused(self):
        (self.home / ".Xauthority").write_text("artificial\n")
        os.environ["DISPLAY"] = ":0"
        with self.assertRaises(confine.ConfineError) as refused:
            self.wrap()
        self.assertIn("X11", str(refused.exception))
        self.assertIn("without --confined", str(refused.exception))
        self.socket(self.runtime / "wayland-0")
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        args = self.wrap()  # a Wayland session: started, with no X server inside
        bound = [p for o in ("--bind", "--ro-bind") for p in self.pairs(args, o)]
        self.assertFalse([p for p in bound if p.endswith((".Xauthority", ".X11-unix"))], bound)
        self.assertIn("DISPLAY", self.pairs(args, "--unsetenv"))

    def test_nulavio_folders_are_hidden_wherever_they_are(self):
        # A data folder outside the home folder holds the other profiles too: only this one comes back.
        elsewhere = self.tmp / "srv/nulavio"
        profile = elsewhere / "data/profiles/p"
        (elsewhere / "data/profiles/other").mkdir(parents=True)
        profile.mkdir(parents=True)
        (elsewhere / "state").mkdir()
        os.environ["NULAVIO_HOME"] = str(elsewhere)
        args = confine.wrap(["/engine/nulavio"], profile_dir=profile, engine_dir=self.engine, home=self.home,
                            binary="/usr/bin/bwrap")  # fmt: skip
        hidden = self.pairs(args, "--tmpfs")
        self.assertIn(str((elsewhere / "data").resolve()), hidden)
        self.assertIn(str((elsewhere / "state").resolve()), hidden)
        self.assertIn(str(profile.resolve()), self.pairs(args, "--bind"))
        self.assertFalse([p for p in self.pairs(args, "--ro-bind") if "other" in p])
        if Path("/dev/shm").is_dir():
            self.assertIn("/dev/shm", hidden)  # its own, not the host's

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
        # CLONE_NEWUSER, NEWPID, NEWNET, NEWIPC and NEWUTS in one call, then a capability used in them.
        self.assertIn("0x10000000 | 0x20000000 | 0x40000000 | 0x08000000 | 0x04000000", confine.NAMESPACE_PROBE)
        self.assertIn("sethostname", confine.NAMESPACE_PROBE)

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


# Run inside bubblewrap: connect to each Unix socket named in argv and print which ones answered.
CONNECT = (
    "import socket, sys\n"
    "for path in sys.argv[1:]:\n"
    "    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
    "    try:\n"
    "        s.connect(path)\n"
    "        print('connected', path)\n"
    "    except OSError:\n"
    "        pass\n"
    "    finally:\n"
    "        s.close()\n"
)


@unittest.skipUnless(bwrap_runs(), "bubblewrap is not installed or cannot run here")
class RealBubblewrapTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for variable in ("WAYLAND_DISPLAY", "DISPLAY", "NULAVIO_HOME"):
            os.environ.pop(variable, None)

    def test_a_confined_program_reaches_no_session_socket_and_no_other_profile(self):
        # The fixture stands in for the session's runtime folder. It is made inside the real one where there is
        # one, so nothing but the confinement hides it; otherwise in /dev/shm, which is the host's without it.
        runtime = [os.environ.get("XDG_RUNTIME_DIR", ""), f"/run/user/{os.getuid()}"]
        base = next((Path(p) for p in runtime if p.startswith("/") and os.access(p, os.W_OK)), Path("/dev/shm"))
        if not base.is_dir():
            self.skipTest("no runtime folder and no /dev/shm here")
        run = Path(tempfile.mkdtemp(prefix="nv-confine-", dir=base))
        self.addCleanup(shutil.rmtree, run, True)
        sockets = {name: listen(run / name) for name in ("wayland-7", "pipewire-0", "bus", "systemd/private",
                                                         "ssh-agent.socket")}  # fmt: skip
        for server in sockets.values():
            self.addCleanup(server.close)
        nulavio = run / "nulavio-home"
        profile, other = nulavio / "data/profiles/p", nulavio / "data/profiles/other"
        for folder in (profile, other):
            folder.mkdir(parents=True)
        (other / "cookies.sqlite").write_text("artificial\n")
        os.environ.update(XDG_RUNTIME_DIR=str(run), WAYLAND_DISPLAY="wayland-7", NULAVIO_HOME=str(nulavio))
        home = Path(tempfile.mkdtemp(prefix="nv-confine-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        args = confine.wrap([sys.executable, "-I", "-c", CONNECT, *(str(run / n) for n in sockets)],
                            profile_dir=profile, engine_dir=Path(sys.executable).resolve().parent, home=home,
                            binary=confine.bwrap())  # fmt: skip
        script = f"test -e {other}/cookies.sqlite && echo other-profile-visible; echo runtime-mode-$(stat -c %a {run}); true"
        seen = subprocess.run(args, capture_output=True, text=True, timeout=30, check=True).stdout.split("\n")
        shell = [*args[: args.index("--") + 1], "/bin/sh", "-c", script]
        seen += subprocess.run(shell, capture_output=True, text=True, timeout=30, check=True).stdout.split("\n")
        connected = sorted(Path(line.split(" ", 1)[1]).name for line in seen if line.startswith("connected "))
        self.assertEqual(connected, ["pipewire-0", "wayland-7"], "only the display and sound sockets answer")
        self.assertNotIn("other-profile-visible", seen)
        self.assertIn("runtime-mode-700", seen)

    def test_the_host_shared_memory_folder_is_not_shared(self):
        if not Path("/dev/shm").is_dir():
            self.skipTest("no /dev/shm here")
        marker = Path(tempfile.mkdtemp(prefix="nv-confine-", dir="/dev/shm"))
        self.addCleanup(shutil.rmtree, marker, True)
        home = Path(tempfile.mkdtemp(prefix="nv-confine-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        (home / "p").mkdir()
        written = Path(f"{marker}.inside")
        self.addCleanup(written.unlink, missing_ok=True)
        script = f"test -e {marker} && echo host-shm-visible; touch {written}; true"
        args = confine.wrap(["/bin/sh", "-c", script], profile_dir=home / "p", engine_dir=Path("/usr/bin"), home=home,
                            binary=confine.bwrap())  # fmt: skip
        out = subprocess.run(args, capture_output=True, text=True, timeout=30, check=True).stdout.split()
        self.assertNotIn("host-shm-visible", out)
        self.assertFalse(written.exists(), "a write in /dev/shm reached the host")

    def test_the_probe_fails_where_nested_namespaces_are_denied(self):
        # Ubuntu's AppArmor denies them by capability (measured: unpriv_bwrap inside bubblewrap, unprivileged_userns
        # outside); --disable-userns denies them by count: the probe refuses all of them.
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
        # binary= : what is hidden is checked even where the probe refuses the engine (Ubuntu), so this still runs there.
        args = confine.wrap(["/bin/sh", "-c", script], profile_dir=profile, engine_dir=Path("/usr/bin"), home=home,
                            binary=confine.bwrap())  # fmt: skip
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
