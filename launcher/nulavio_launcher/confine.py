"""Optional outer confinement of the engine with bubblewrap (docs/security/phase5-spikes.md).

`nulavio run --confined` starts the engine inside a bubblewrap mount
namespace where the home folder is an empty in-memory folder with only these
put back: the profile and the Downloads folder (read-write), and the few
read-only settings a desktop browser needs (fonts, themes, the desktop's
folder names, registered native-messaging hosts). The profile and Downloads
are put back at the paths the browser is given too, when those go through a
symlink in a hidden folder (a `~/Downloads` link to another disk, a data
folder reached through a link), since that link is not there inside (#711).
A home folder that is itself such a link is not handled yet: Downloads and the
read-only settings are bound under the resolved home only (#722).
The rest of the system is
visible read-only, as for any program; /tmp, /var/tmp, /dev/shm and removable
media are empty, and so are the user's runtime folder and Nulavio's own
folders wherever they are, except for what is put back. /dev is bubblewrap's
own minimal one (null, zero, random, its own terminals) with only the GPU and
the cameras put back: no input devices, terminals of the session, HID or other
hardware nodes (the terminal `nulavio run` was started from stays the engine's
standard input; --new-session keeps it from typing into it). System V IPC is
its own too.

From the runtime folder only the display and sound sockets are put back
(Wayland, PipeWire, PulseAudio) and KeePassXC's browser socket when it is
there: not the session bus, the user's service manager, agents or other
programs' sockets. The session bus is therefore not reachable inside (no
portals, desktop notifications or media keys), and an X server is not offered:
on a session with X11 only, the confined start is refused, since any X client
can read and type into the other windows.

It limits what a compromised browser can reach (SSH keys, cloud credentials,
documents, other profiles and apps). It does not stop a program running as
the user outside the browser from reading the profile. The engine's own
sandboxes are untouched: no PID namespace (the profile lock and the launcher
see real PIDs), no network namespace (the browser needs the network), user
namespaces stay available so the engine still sandboxes its content processes
(seccomp and namespaces; checked by tests/integration/test_confined.py).

Where the engine could not build those namespaces inside bubblewrap (Ubuntu's
`bwrap-userns-restrict` AppArmor profile takes the capabilities away, #282),
the confined start is refused: hiding the home folder is not bought with the
engine's own sandbox (SEC-19).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths

SEARCH_PATH = "/usr/bin:/bin"
# Read-only, when present: what the browser reads from the home folder to look like the desktop.
READ_ONLY_HOME = (
    ".config/fontconfig",
    ".local/share/fonts",
    ".fonts",
    ".config/gtk-3.0",
    ".config/gtk-4.0",
    ".config/kdeglobals",
    ".config/user-dirs.dirs",
    ".config/mimeapps.list",
    ".icons",
    ".local/share/icons",
    ".mozilla/native-messaging-hosts",
)
EMPTY_DIRS = ("/tmp", "/var/tmp", "/dev/shm", "/mnt", "/media", "/run/media")  # noqa: S108 - hidden, not used
# Put back from the runtime folder, read-only (a socket stays usable): sound and KeePassXC's browser socket, which
# its native-messaging proxy connects to. The Wayland socket is added by name ($WAYLAND_DISPLAY).
RUNTIME_SOCKETS = ("pipewire-0", "pulse/native", "app/org.keepassxc.KeePassXC")
# Not passed inside: the session bus is not there, and no X server is offered.
UNSET_ENV = ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "XAUTHORITY")
# Device nodes put back from the host's /dev, when present, as they are at the start: the GPU (rendering, video
# decoding) and the cameras (which PipeWire offers too). Nothing else: not input devices, the session's terminals, HID
# devices (security keys among them) or other hardware. A node that appears later (a camera plugged in) is not there.
DEVICE_DIRS = ("dri", "nvidia-caps")
DEVICE_GLOBS = ("nvidia*", "video[0-9]*")


# Run inside bubblewrap: new user, PID, network, IPC and UTS namespaces in one call, as the engine's content
# sandbox makes them, then a capability used inside them (sethostname in the new UTS namespace). Creating them is
# not enough: a policy can let a namespace be made and deny its capabilities afterwards (Ubuntu's
# unprivileged_userns profile does). Exit 3 when refused.
NAMESPACE_PROBE = (
    "import ctypes, os, sys\n"
    "libc = ctypes.CDLL(None, use_errno=True)\n"
    "if libc.unshare(0x10000000 | 0x20000000 | 0x40000000 | 0x08000000 | 0x04000000) != 0"
    " or libc.sethostname(b'nulavio-probe', 13) != 0:\n"
    "    sys.stderr.write(os.strerror(ctypes.get_errno()) + '\\n')\n"
    "    sys.exit(3)\n"
)
NAMESPACES_REFUSED = 3


class ConfineError(RuntimeError):
    pass


def bwrap() -> str | None:
    return shutil.which("bwrap", path=SEARCH_PATH)


def check() -> str:
    """The bwrap binary, after proving it runs here and the engine could still sandbox its content inside it."""
    binary = bwrap()
    if not binary:
        raise ConfineError("bubblewrap (bwrap) is not installed; install it, or run without --confined")
    probe = subprocess.run(
        [binary, "--ro-bind", "/", "/", "--dev", "/dev", "--", sys.executable, "-I", "-c", NAMESPACE_PROBE],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    detail = (probe.stderr.strip().splitlines()[-1:] or ["unknown error"])[0]
    if probe.returncode == NAMESPACES_REFUSED:
        raise ConfineError(
            f"not starting: inside bubblewrap the engine could not give its content processes their own "
            f"user, PID and network namespaces here ({detail}; on Ubuntu, AppArmor's bwrap-userns-restrict does this), "
            "so --confined would weaken the engine's own sandbox. Without --confined, an engine installed from "
            "Nulavio's package keeps that sandbox, but the browser can read your whole home folder"
        )
    if probe.returncode != 0:
        raise ConfineError(f"bubblewrap cannot run here ({detail}); run without --confined")
    return binary


def download_dir(home: Path | None = None) -> Path:
    """The desktop's Downloads folder (XDG user dirs), else ~/Downloads; never the home folder itself."""
    home = home or Path.home()
    try:
        text = (home / ".config" / "user-dirs.dirs").read_text(encoding="utf-8")
    except OSError:
        text = ""
    match = re.search(r'^XDG_DOWNLOAD_DIR="([^"\n]+)"', text, re.M)
    value = match.group(1).replace("$HOME", str(home)) if match else ""
    folder = Path(value) if value.startswith("/") else home / "Downloads"
    if folder.resolve() == home.resolve():
        folder = home / "Downloads"  # some desktops point Downloads at $HOME: never expose all of it
    return folder


def runtime_dirs() -> list[Path]:
    """The user's runtime folders: $XDG_RUNTIME_DIR and /run/user/<uid>, when they exist."""
    found: list[Path] = []
    for value in (os.environ.get("XDG_RUNTIME_DIR", ""), f"/run/user/{os.getuid()}"):
        if value.startswith("/") and Path(value).is_dir() and Path(value).resolve() not in found:
            found.append(Path(value).resolve())
    return found


def wayland_socket(runtime: Path | None) -> Path | None:
    """The compositor's socket named by $WAYLAND_DISPLAY (a name in the runtime folder, or a path), if it is one."""
    name = os.environ.get("WAYLAND_DISPLAY", "")
    if not name:
        return None
    path = Path(name) if name.startswith("/") else (runtime / name if runtime else None)
    return path if path is not None and path.is_socket() else None


def device_nodes(dev: Path = Path("/dev")) -> list[Path]:
    """The host's device nodes put back inside (DEVICE_DIRS, DEVICE_GLOBS); never a symlink."""
    found = [dev / name for name in DEVICE_DIRS if (dev / name).is_dir() and not (dev / name).is_symlink()]
    for pattern in DEVICE_GLOBS:
        found += [p for p in sorted(dev.glob(pattern)) if p.is_char_device() and not p.is_symlink()]
    return found


def nulavio_dirs() -> list[Path]:
    """Nulavio's own folders (profiles, Vault, AI Bridge settings, temporary profiles), wherever they are."""
    found: list[Path] = []
    for folder in (paths.data_home(), paths.state_home(), paths.cache_home(), paths.runtime_home()):
        if folder is not None and folder.is_dir() and folder.resolve() not in found:
            found.append(folder.resolve())
    return found


def _inside_hidden(path: Path, hidden: list[Path]) -> bool:
    # `path` has every link resolved; a hidden folder may be written under a linked parent (/var/tmp, /var a link).
    folders = {form for folder in hidden for form in (folder, folder.resolve())}
    return any(path != folder and path.is_relative_to(folder) for folder in folders)


def seen_inside(path: Path, hidden: list[Path], restored: list[tuple[Path, bool]] = ()) -> Path | None:
    """Where a folder must also be bound so that `path` reaches it writable inside, or None when it already does.

    `restored` lists the destinations of the binds made before, each with whether it is writable. A hidden folder is
    empty inside, so a symlink in it is not there, except where one of those binds puts it back. `path` is followed as
    the kernel would follow it inside:
    - a destination is a mount point inside, a folder, even where the host has a link at that path;
    - a link that is still visible, or put back, is followed;
    - a hidden link above a destination is the plain folder bubblewrap made there on the way to it, holding nothing
      else;
    - the first link met in a hidden folder ends the walk, and the path from there on is returned (bubblewrap makes
      plain folders for it in the empty one).
    A walk that ends outside every writable destination (in a read-only put-back such as ~/.fonts) returns where it
    ends, so the folder is bound writable there too; that holds because every writable bind comes after the
    read-only ones. bubblewrap refuses to mount on a link, so a link that is there inside is never returned.
    """
    if not path.is_absolute():
        raise ConfineError(f"not starting: {path} is not an absolute path")
    destinations = [d for d, _ in restored]
    pending = list(reversed(path.parts[1:]))
    current, links = Path("/"), 0
    while pending:
        name = pending.pop()
        if name in ("", "."):
            continue
        if name == "..":
            current = current.parent
            continue
        candidate = current / name
        if candidate in destinations:
            current = candidate  # a mount point: never a link inside, whatever the host has there
            continue
        if _inside_hidden(candidate, hidden) and not any(candidate.is_relative_to(d) for d in destinations):
            if any(d.is_relative_to(candidate) for d in destinations):
                current = candidate  # a folder bubblewrap made on the way to an earlier bind
                continue
            # A link, or anything in such a made folder (`current` then still goes through the link outside).
            if candidate.is_symlink() or current.resolve() != current:
                rest = list(reversed(pending))
                if ".." in rest:
                    raise ConfineError(f"not starting: {path} goes through a link and then '..'; give a plain path")
                return candidate.joinpath(*rest)
        if not candidate.is_symlink():
            current = candidate
            continue
        links += 1
        if links > 40:  # the kernel's own limit
            raise ConfineError(f"not starting: too many levels of symbolic links in {path}")
        target = Path(os.readlink(candidate))
        if target.is_absolute():
            current = Path("/")
        pending.extend(reversed(target.parts[1:] if target.is_absolute() else target.parts))
    return None if any(current.is_relative_to(d) for d, writable in restored if writable) else current


def wrap(command: list[str], *, profile_dir: Path, engine_dir: Path, supervised: bool = False,
         home: Path | None = None, binary: str | None = None) -> list[str]:  # fmt: skip
    """The engine command inside bubblewrap. Paths must exist; the Downloads folder is created if missing.

    Everything is hidden first and put back after, so a folder put back is never covered by a later empty one.
    """
    home = (home or Path.home()).resolve()
    runtime = runtime_dirs()
    env_runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    socket_dir = Path(env_runtime) if env_runtime.startswith("/") else (runtime[0] if runtime else None)
    wayland = wayland_socket(socket_dir)
    if wayland is None and os.environ.get("DISPLAY"):
        raise ConfineError(
            "not starting: this session has no Wayland display, only X11, where any program with a window can read "
            "and type into the others, so --confined would not keep a compromised browser in. Log in to a Wayland "
            "session, or run without --confined"
        )
    binary = binary or check()
    profile_dir = Path(profile_dir)
    if not profile_dir.is_absolute() or not profile_dir.is_dir():
        raise ConfineError(f"not starting: the profile folder {profile_dir} is not there")
    downloads = download_dir(home)
    try:
        downloads.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfineError(
            f"not starting: the Downloads folder {downloads} is not a folder and cannot be made ({exc.strerror}); "
            "if it is a link, the folder it points to is missing. Make that folder, or run without --confined"
        ) from None
    # Writable /proc: the engine maps user ids for its own content sandboxes there. bubblewrap's own /dev, with
    # only the GPU and cameras put back (--dev-bind: device nodes work only on such a mount); its own System V IPC.
    args = [binary, "--ro-bind", "/", "/", "--dev", "/dev", "--bind", "/proc", "/proc", "--unshare-ipc"]
    for node in device_nodes():
        args += ["--dev-bind", str(node), str(node)]
    # Hidden: empty in-memory folders. A socket under a read-only mount still accepts connections, so the runtime
    # folder is hidden whole rather than left read-only.
    hidden = [Path("/home"), home, *(Path(f) for f in EMPTY_DIRS), *runtime, *nulavio_dirs()]
    emptied: list[Path] = []
    for folder in sorted(hidden, key=lambda f: len(f.parts)):  # a folder before those inside it
        if folder.is_dir() and not folder.is_symlink():  # /home is a link on some systems
            # A runtime folder stays private (0700), as programs that use it check.
            args += ["--perms", "0700"] if folder in runtime else []
            args += ["--tmpfs", str(folder)]
            emptied.append(folder)
    # Put back.
    sockets = [wayland] if wayland else []
    if socket_dir is not None:
        sockets += [socket_dir / name for name in RUNTIME_SOCKETS if (socket_dir / name).exists()]
    for path in sockets:
        args += ["--ro-bind", str(path.resolve()), str(path)]
    for relative in READ_ONLY_HOME:
        path = home / relative
        if path.exists():
            args += ["--ro-bind", str(path), str(path)]
    engine_dir = Path(engine_dir).resolve()
    args += ["--ro-bind", str(engine_dir), str(engine_dir)]  # it may live under a hidden folder
    # Writable: the profile and Downloads, at their resolved paths, and also at the paths the browser is given when
    # those go through a link that is hidden inside: otherwise the engine would make an empty folder there, in
    # memory, and a download or a whole profile would be lost when it closes (#711). A link that an earlier writable
    # bind puts back (a Downloads link inside the profile) is there inside and needs nothing more. Downloads is found
    # from the resolved home, so a home folder that is itself such a link still loses it (#722).
    # A link put back read-only (a Downloads folder in a linked ~/.fonts) is there but not writable: bound there too.
    binds = ("--bind", "--ro-bind")
    restored = [(Path(args[i + 2]), a == "--bind") for i, a in enumerate(args) if a in binds and args[i + 2] != "/"]
    for path in (profile_dir, downloads):
        real = path.resolve()
        args += ["--bind", str(real), str(real)]
        restored.append((real, True))
        seen = seen_inside(path, emptied, restored)
        if seen is not None and seen != real:
            args += ["--bind", str(real), str(seen)]
            restored.append((seen, True))
    for name in UNSET_ENV:
        args += ["--unsetenv", name]
    args += ["--chdir", str(home), "--new-session"]
    if supervised:
        args.append("--die-with-parent")
    return [*args, "--", *command]
