"""Optional outer confinement of the engine with bubblewrap (docs/security/phase5-spikes.md).

`nulavio run --confined` starts the engine inside a bubblewrap mount
namespace where the home folder is an empty in-memory folder with only these
put back: the profile and the Downloads folder (read-write), and the few
read-only settings a desktop browser needs (fonts, themes, the desktop's
folder names, registered native-messaging hosts). The rest of the system is
visible read-only, as for any program; /tmp, /var/tmp and removable media
are empty.

It limits what a compromised browser can reach (SSH keys, cloud credentials,
documents, other profiles and apps). It does not stop a program running as
the user outside the browser from reading the profile, and it does not
filter the session bus (the browser needs portals, notifications and media
keys there). The engine's own sandboxes are untouched: no PID namespace (the
profile lock and the launcher see real PIDs), user namespaces stay available
so the engine still sandboxes its content processes (seccomp and namespaces;
checked by tests/integration/test_confined.py).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

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
    ".Xauthority",
    ".mozilla/native-messaging-hosts",
)
EMPTY_DIRS = ("/tmp", "/var/tmp", "/mnt", "/media", "/run/media")  # noqa: S108 - hidden, not used


class ConfineError(RuntimeError):
    pass


def bwrap() -> str | None:
    return shutil.which("bwrap", path=SEARCH_PATH)


def check() -> str:
    """The bwrap binary, after proving it can create the namespaces it needs here."""
    binary = bwrap()
    if not binary:
        raise ConfineError("bubblewrap (bwrap) is not installed; install it, or run without --confined")
    probe = subprocess.run(
        [binary, "--ro-bind", "/", "/", "--dev", "/dev", "--", "/bin/true"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if probe.returncode != 0:
        detail = probe.stderr.strip().splitlines()[-1:] or ["unknown error"]
        raise ConfineError(f"bubblewrap cannot run here ({detail[0]}); run without --confined")
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


def wrap(command: list[str], *, profile_dir: Path, engine_dir: Path, supervised: bool = False,
         home: Path | None = None, binary: str | None = None) -> list[str]:  # fmt: skip
    """The engine command inside bubblewrap. Paths must exist; the Downloads folder is created if missing."""
    home = (home or Path.home()).resolve()
    binary = binary or check()
    downloads = download_dir(home)
    downloads.mkdir(parents=True, exist_ok=True)
    # Writable /proc: the engine maps user ids for its own content sandboxes there.
    args = [binary, "--ro-bind", "/", "/", "--dev-bind", "/dev", "/dev", "--bind", "/proc", "/proc"]
    for folder in ("/home", str(home)):
        if Path(folder).is_dir() and not Path(folder).is_symlink():  # /home is a link on some systems
            args += ["--tmpfs", folder]
    for folder in EMPTY_DIRS:
        if Path(folder).is_dir() and not Path(folder).is_symlink():
            args += ["--tmpfs", folder]
    x11 = "/tmp/.X11-unix"  # noqa: S108 - the X server's sockets (X11 sessions), shown read-only
    if Path(x11).is_dir():
        args += ["--ro-bind", x11, x11]
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime.startswith("/") and Path(runtime).is_dir():
        args += ["--bind", runtime, runtime]  # Wayland, PipeWire, the session bus, portals
    for relative in READ_ONLY_HOME:
        path = home / relative
        if path.exists():
            args += ["--ro-bind", str(path), str(path)]
    engine_dir = Path(engine_dir).resolve()
    args += ["--ro-bind", str(engine_dir), str(engine_dir)]  # it may live under a hidden folder
    for path in (Path(profile_dir).resolve(), downloads.resolve()):
        args += ["--bind", str(path), str(path)]
    args += ["--chdir", str(home), "--new-session"]
    if supervised:
        args.append("--die-with-parent")
    return [*args, "--", *command]
