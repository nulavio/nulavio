"""Optional outer confinement with bubblewrap (launcher/nulavio_launcher/confine.py, docs/security/phase5-spikes.md)."""

from __future__ import annotations

import ctypes
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

    def test_dev_is_bubblewraps_own_with_only_the_gpu_and_cameras_put_back(self):
        args = self.wrap()
        self.assertEqual(self.pairs(args, "--dev"), ["/dev"])
        self.assertNotIn("/dev", self.pairs(args, "--dev-bind"), "never the host's whole /dev")
        self.assertEqual(self.pairs(args, "--dev-bind"), [str(p) for p in confine.device_nodes()])
        self.assertIn("--unshare-ipc", args)  # System V IPC is its own

    def test_device_nodes_are_the_gpu_and_cameras_only_and_never_a_link(self):
        dev = self.tmp / "dev"
        for name in ("dri", "input", "pts", "bus/usb"):
            (dev / name).mkdir(parents=True)
        for name in ("video0", "uinput", "hidraw0", "nvidiactl"):
            (dev / name).write_text("")  # regular files: not device nodes
        (dev / "nvidia-caps").symlink_to(dev / "input")
        (dev / "video9").symlink_to("/dev/null")
        self.assertEqual(confine.device_nodes(dev), [dev / "dri"])
        found = confine.device_nodes()
        for node in found:
            self.assertRegex(node.name, r"^(dri|nvidia.*|video[0-9]+)$")
            self.assertFalse(node.is_symlink())

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

    def destinations(self, args: list[str]) -> list[str]:
        options = args[: args.index("--")]
        return [options[i + 2] for i, a in enumerate(options) if a in ("--bind", "--ro-bind", "--dev-bind")]

    def triples(self, args: list[str]) -> list[tuple[str, str, str]]:
        options = args[: args.index("--")]
        return [(a, options[i + 1], options[i + 2]) for i, a in enumerate(options) if a.endswith("bind")]

    def binds(self, args: list[str]) -> list[tuple[str, str]]:
        options = args[: args.index("--")]
        return [(options[i + 1], options[i + 2]) for i, a in enumerate(options) if a == "--bind"]

    def test_a_downloads_folder_through_a_link_is_put_back_where_the_browser_looks(self):
        # ~/Downloads as a link to another disk (#711): the link is in the hidden home folder, so the folder is bound
        # at ~/Downloads too, or the engine would make an empty one there, in memory.
        real = self.tmp / "disk/Downloads"
        real.mkdir(parents=True)
        (self.home / "Downloads").symlink_to(real)
        binds = self.binds(self.wrap())
        self.assertIn((str(real.resolve()), str(real.resolve())), binds)
        self.assertIn((str(real.resolve()), str(self.home.resolve() / "Downloads")), binds)
        self.assertEqual(len(binds), 4, binds)  # /proc, the profile, Downloads twice: nothing else writable

    def test_a_data_folder_through_a_link_is_put_back_at_the_profile_path_the_engine_is_given(self):
        disk = self.tmp / "disk/nulavio"
        (disk / "data/profiles/p").mkdir(parents=True)
        (disk / "data/profiles/other").mkdir()
        link = self.home / ".local/share/nulavio-linked"
        link.symlink_to(disk)
        os.environ["NULAVIO_HOME"] = str(link)  # the data folder is reached through the link, as ~/.local/share may be
        profile = link / "data/profiles/p"
        args = confine.wrap(["/engine/nulavio", "--profile", str(profile)], profile_dir=profile,
                            engine_dir=self.engine, home=self.home, binary="/usr/bin/bwrap")  # fmt: skip
        real = str((disk / "data/profiles/p").resolve())
        self.assertIn((real, real), self.binds(args))
        self.assertIn((real, str(profile)), self.binds(args))
        self.assertIn(str((disk / "data").resolve()), self.pairs(args, "--tmpfs"), "the other profiles stay hidden")
        self.assertFalse([b for b in self.binds(args) if "other" in b[0] or "other" in b[1]])
        self.assertEqual(args[args.index("--") + 1 :], ["/engine/nulavio", "--profile", str(profile)])

    def test_a_downloads_link_inside_the_profile_is_put_back_by_the_profile_bind_and_never_mounted_on(self):
        # The profile bind already puts the link back inside; bubblewrap refuses to mount on a link ("Can't mount on
        # symlink destination"), so a second bind there would stop the confined start.
        real = self.tmp / "disk/Downloads"
        real.mkdir(parents=True)
        (self.profile / "Downloads").symlink_to(real)
        dirs = self.home / ".config/user-dirs.dirs"
        dirs.write_text('XDG_DOWNLOAD_DIR="$HOME/.local/share/nulavio/data/profiles/p/Downloads"\n')
        args = self.wrap()
        self.assertFalse([d for d in self.destinations(args) if Path(d).is_symlink()], self.destinations(args))
        self.assertEqual(self.binds(args)[1:], [(str(self.profile.resolve()),) * 2, (str(real.resolve()),) * 2])
        # Seen from the walk: a link under a folder put back is followed; one in a folder still hidden is not.
        restored = [(self.profile.resolve(), True), (real.resolve(), True)]
        self.assertIsNone(confine.seen_inside(self.profile / "Downloads", [self.home.resolve()], restored))
        (self.home / "Downloads").symlink_to(real)
        found = confine.seen_inside(self.home / "Downloads", [self.home.resolve()], restored)
        self.assertEqual(found, self.home.resolve() / "Downloads")

    def test_a_downloads_link_inside_a_profile_reached_through_a_hidden_link_is_never_mounted_on(self):
        # The profile is at ~/link/p with ~/link a link: it is bound at ~/link/p too, and that bind puts back the
        # Downloads link inside it. ~/link is then a plain folder inside, holding only p.
        disk = self.tmp / "disk"
        for folder in (disk / "x/p", disk / "x/dl", disk / "Downloads"):
            folder.mkdir(parents=True)
        (self.home / "link").symlink_to(disk / "x")
        (disk / "x/p/Downloads").symlink_to(disk / "Downloads")
        profile, home, dirs = self.home / "link/p", self.home.resolve(), self.home / ".config/user-dirs.dirs"
        for downloads, expected in (("p/Downloads", None), ("dl", home / "link/dl")):
            with self.subTest(downloads=downloads):
                dirs.write_text(f'XDG_DOWNLOAD_DIR="$HOME/link/{downloads}"\n')
                args = confine.wrap(["/engine/nulavio"], profile_dir=profile, engine_dir=self.engine, home=self.home,
                                    binary="/usr/bin/bwrap")  # fmt: skip
                self.assertFalse([d for d in self.destinations(args) if Path(d).is_symlink()])
                real = (self.home / "link" / downloads).resolve()
                extra = [(str(real), str(expected))] if expected else []
                self.assertEqual(self.binds(args)[1:], [(str((disk / "x/p").resolve()),) * 2,
                                                        (str((disk / "x/p").resolve()), str(home / "link/p")),
                                                        (str(real),) * 2, *extra])  # fmt: skip

    def test_a_downloads_folder_in_a_linked_read_only_folder_is_bound_writable_where_the_browser_looks(self):
        # ~/.fonts is a link and is put back read-only, so ~/.fonts/Downloads is there inside but not writable: the
        # folder is bound writable at that path too, never on a link that the read-only put-back shows.
        fonts = self.tmp / "disk/fonts"
        fonts.mkdir(parents=True)
        (self.home / ".fonts").symlink_to(fonts)
        (self.home / ".config/user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/.fonts/Downloads"\n')
        home, fonts = self.home.resolve(), fonts.resolve()
        layouts = {
            "a plain folder": (None, fonts / "Downloads", home / ".fonts/Downloads"),
            "an absolute link": (fonts.parent / "dl2", fonts.parent / "dl2", None),  # writable where it points
            "a relative link": ("dl2", fonts / "dl2", home / ".fonts/dl2"),
        }
        for layout, (target, real, extra) in layouts.items():
            with self.subTest(layout):
                for leftover in (fonts / "Downloads", fonts / "dl2", fonts.parent / "dl2"):
                    if leftover.is_symlink():
                        leftover.unlink()
                if target is None:
                    (fonts / "Downloads").mkdir(exist_ok=True)
                else:
                    if (fonts / "Downloads").is_dir():
                        (fonts / "Downloads").rmdir()
                    real.mkdir(exist_ok=True)
                    (fonts / "Downloads").symlink_to(target)
                args = self.wrap()
                self.assertIn(("--ro-bind", str(home / ".fonts"), str(home / ".fonts")), self.triples(args))
                expected = [(str(real), str(real))] + ([(str(real), str(extra))] if extra else [])
                self.assertEqual(self.binds(args)[2:], expected)

    def test_a_link_still_there_inside_adds_no_bind(self):
        # A home folder reached through a link outside the hidden folders (/home -> var/home): the link is there
        # inside, so the resolved path bound at itself is what the browser's path leads to.
        users = self.tmp / "var/home/u"
        (users / ".local/share/p").mkdir(parents=True)
        (self.tmp / "home-link").symlink_to("var/home")
        bound = [(users.resolve() / ".local/share/p", True)]  # the resolved path, bound writable at itself
        self.assertIsNone(confine.seen_inside(self.tmp / "home-link/u/.local/share/p", [users], bound))
        self.assertEqual(confine.seen_inside(self.tmp / "home-link/u/.local/share/p", [users], [(users, False)]),
                         users.resolve() / ".local/share/p", "reached, but only read-only: bound writable there")  # fmt: skip
        (self.tmp / "disk").mkdir()
        (users / "Downloads").symlink_to(self.tmp / "disk")
        self.assertEqual(confine.seen_inside(self.tmp / "home-link/u/Downloads", [users]), users / "Downloads")
        (users / "loop").symlink_to(users / "loop")
        with self.assertRaises(confine.ConfineError):
            confine.seen_inside(self.tmp / "home-link/u/loop/x", [self.tmp / "elsewhere"])
        with self.assertRaises(confine.ConfineError):
            confine.seen_inside(Path("relative/p"), [users])
        # A hidden folder written under a linked parent (/var/tmp with /var a link) still ends the walk.
        (self.tmp / "realvar/tmp").mkdir(parents=True)
        (self.tmp / "var-link").symlink_to("realvar")
        (self.tmp / "realvar/tmp/x").symlink_to(self.tmp / "disk")
        found = confine.seen_inside(self.tmp / "var-link/tmp/x", [self.tmp / "var-link/tmp"])
        self.assertEqual(found, (self.tmp / "realvar").resolve() / "tmp/x")

    def test_a_downloads_link_to_a_missing_folder_or_a_missing_profile_is_refused(self):
        (self.home / "Downloads").symlink_to(self.tmp / "unplugged-disk/Downloads")
        with self.assertRaises(confine.ConfineError) as refused:
            self.wrap()
        self.assertIn("Downloads", str(refused.exception))
        self.assertIn("without --confined", str(refused.exception))
        self.assertFalse((self.tmp / "unplugged-disk").exists(), "nothing made where the link points")
        (self.home / "Downloads").unlink()
        with self.assertRaises(confine.ConfineError) as refused:
            confine.wrap(["/engine/nulavio"], profile_dir=self.home / "missing", engine_dir=self.engine,
                         home=self.home, binary="/usr/bin/bwrap")  # fmt: skip
        self.assertIn("profile folder", str(refused.exception))


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

# Run inside bubblewrap: argv is pairs of a name and a folder; write a file in each and print "<name>-ok", or
# "<name>-<errno name>" (downloads-EROFS) when it could not be written.
WRITE = (
    "import errno, sys\n"
    "from pathlib import Path\n"
    "for name, folder in zip(sys.argv[1::2], sys.argv[2::2]):\n"
    "    try:\n"
    "        (Path(folder) / 'written').touch()\n"
    "        print(name + '-ok')\n"
    "    except OSError as exc:\n"
    "        print(name + '-' + errno.errorcode.get(exc.errno, 'error'))\n"
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

    def test_a_confined_program_sees_no_host_terminal_input_device_or_ipc_segment(self):
        home = Path(tempfile.mkdtemp(prefix="nv-confine-home-"))
        self.addCleanup(shutil.rmtree, home, True)
        (home / "p").mkdir()
        primary, secondary = os.openpty()  # another terminal of the session
        self.addCleanup(os.close, primary)
        self.addCleanup(os.close, secondary)
        terminal = os.ttyname(secondary)
        libc = ctypes.CDLL(None, use_errno=True)
        segment = libc.shmget(0, 4096, 0o600)  # IPC_PRIVATE: a System V segment made outside
        self.assertGreaterEqual(segment, 0, os.strerror(ctypes.get_errno()))
        self.addCleanup(libc.shmctl, segment, 0, None)  # IPC_RMID, this segment only
        script = (
            f"test -e {terminal} && echo host-terminal-visible;"
            "for n in /dev/input /dev/uinput /dev/hidraw0 /dev/kvm /dev/fuse; do test -e $n && echo visible-$n; done;"
            f"awk '$2 == {segment} {{ print \"segment-visible\" }}' /proc/sysvipc/shm; echo listing; ls -A /dev; true"
        )
        args = confine.wrap(["/bin/sh", "-c", script], profile_dir=home / "p", engine_dir=Path("/usr/bin"), home=home,
                            binary=confine.bwrap())  # fmt: skip
        out = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
                             check=True).stdout.split()  # fmt: skip
        self.assertNotIn("host-terminal-visible", out)
        self.assertFalse([line for line in out if line.startswith("visible-")], out)
        self.assertNotIn("segment-visible", out)
        put_back = {p.name for p in confine.device_nodes()}
        # bubblewrap's own /dev; "console" is the launcher's own terminal, when it has one.
        own = {"console", "core", "fd", "full", "null", "ptmx", "pts", "random", "shm", "stderr", "stdin", "stdout",
               "tty", "urandom", "zero"}  # fmt: skip
        listed = set(out[out.index("listing") + 1 :])
        self.assertLessEqual(listed, own | put_back)

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

    def test_files_written_through_linked_downloads_and_data_folders_land_in_the_real_folders(self):
        # #711: ~/Downloads and ~/.local/share as links to another disk. Without the second bind the writes go to
        # empty in-memory folders and are lost.
        tmp = Path(tempfile.mkdtemp(prefix="nv-confine-real-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        home, disk = tmp / "home", tmp / "disk"
        (disk / "Downloads").mkdir(parents=True)
        (disk / "share/nulavio/data/profiles/p").mkdir(parents=True)
        (home / ".local").mkdir(parents=True)
        (home / "Downloads").symlink_to(disk / "Downloads")
        (home / ".local/share").symlink_to(disk / "share")
        profile = home / ".local/share/nulavio/data/profiles/p"
        write = [sys.executable, "-I", "-c", WRITE, "profile", str(profile), "downloads", str(home / "Downloads")]
        args = confine.wrap(write, profile_dir=profile, engine_dir=Path(sys.executable).resolve().parent, home=home,
                            binary=confine.bwrap())  # fmt: skip
        out = subprocess.run(args, capture_output=True, text=True, timeout=30, check=True).stdout.split()
        self.assertEqual(out, ["profile-ok", "downloads-ok"])
        self.assertTrue((disk / "share/nulavio/data/profiles/p/written").exists())
        self.assertTrue((disk / "Downloads/written").exists())

    def test_a_downloads_link_inside_the_profile_starts_and_writes_to_the_real_folder(self):
        # The profile bind puts the link back; a bind on the link itself would stop the start (bubblewrap refuses it).
        # Twice: the profile at its own path, and reached through a link in the home folder.
        for linked in (False, True):
            with self.subTest(linked=linked):
                tmp = Path(tempfile.mkdtemp(prefix="nv-confine-real-"))
                self.addCleanup(shutil.rmtree, tmp, True)
                home, disk = tmp / "home", tmp / "disk"
                (home / ".config").mkdir(parents=True)
                (disk / "Downloads").mkdir(parents=True)
                if linked:
                    (disk / "x/p").mkdir(parents=True)
                    (home / "link").symlink_to(disk / "x")
                    profile = home / "link/p"
                else:
                    profile = home / ".local/share/nulavio/data/profiles/p"
                    profile.mkdir(parents=True)
                (profile / "Downloads").symlink_to(disk / "Downloads")
                (home / ".config/user-dirs.dirs").write_text(f'XDG_DOWNLOAD_DIR="{profile}/Downloads"\n')
                write = [sys.executable, "-I", "-c", WRITE, "profile", str(profile), "downloads",
                         str(profile / "Downloads")]  # fmt: skip
                args = confine.wrap(write, profile_dir=profile, engine_dir=Path(sys.executable).resolve().parent,
                                    home=home, binary=confine.bwrap())  # fmt: skip
                run = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout.split(), ["profile-ok", "downloads-ok"])
                self.assertTrue((profile.resolve() / "written").exists())
                self.assertTrue((disk / "Downloads/written").exists())

    def test_a_downloads_folder_in_a_linked_fonts_folder_is_writable(self):
        # ~/.fonts is a link put back read-only: without a writable bind at ~/.fonts/Downloads a download fails with
        # "Read-only file system"; a bind on a link there would stop the start. A plain folder, then links to others.
        for target in (None, "dl2", "/abs"):
            with self.subTest(target=target):
                tmp = Path(tempfile.mkdtemp(prefix="nv-confine-real-"))
                self.addCleanup(shutil.rmtree, tmp, True)
                home, fonts = tmp / "home", tmp / "disk/fonts"
                profile = home / ".local/share/nulavio/data/profiles/p"
                for folder in (profile, home / ".config", fonts):
                    folder.mkdir(parents=True)
                (home / ".fonts").symlink_to(fonts)
                if target is None:
                    real = fonts / "Downloads"
                    real.mkdir()
                else:
                    real = fonts / "dl2" if target == "dl2" else tmp / "disk/dl2"
                    real.mkdir()
                    (fonts / "Downloads").symlink_to("dl2" if target == "dl2" else real)
                (home / ".config/user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/.fonts/Downloads"\n')
                write = [sys.executable, "-I", "-c", WRITE, "downloads", str(home / ".fonts/Downloads")]
                args = confine.wrap(write, profile_dir=profile, engine_dir=Path(sys.executable).resolve().parent,
                                    home=home, binary=confine.bwrap())  # fmt: skip
                run = subprocess.run(args, capture_output=True, text=True, timeout=30, check=False)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout.split(), ["downloads-ok"])
                self.assertTrue((real / "written").exists())


if __name__ == "__main__":
    unittest.main()
