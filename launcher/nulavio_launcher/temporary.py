"""Temporary profiles: a fresh engine profile that is deleted when its browser closes.

Where it lives: ``$XDG_RUNTIME_DIR/nulavio/temporary/tmp-<random>/``. On
systemd desktops that directory is a per-user tmpfs, so the profile is kept
in memory and also disappears at logout or reboot. Memory pages can still
reach a swap device; :func:`storage` reports which case applies, and the UI
only says "kept in memory" when no swap on disk is active. Without a private
runtime directory the profile goes to the cache directory on disk and is
reported as such.

Lifecycle: :func:`create` makes the directory and takes an exclusive
``flock`` on its guard file. Whoever holds that lock deletes the profile:
the supervising ``nulavio run --temporary`` process, or a detached reaper
started for the browser (:func:`spawn_reaper`), which waits for the engine
to take the profile and then for it to exit. A directory whose guard lock is
free and whose engine is gone is an orphan (the reaper was killed); the next
:func:`create` removes it.

Deletion is limited to directories directly under the temporary root that
carry the marker file, never through a symlink.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import log, paths, profile

MARKER = "nulavio-temporary.json"
GUARD = "nulavio-temporary.lock"
PREFIX = "tmp-"
SCHEMA = 1

# Written into the new profile's prefs.js. Each one follows from "deleted on close".
PREFS: dict[str, bool | str] = {
    "nulavio.profile.temporary": True,  # the Shell shows the temporary identity
    "browser.download.manager.addToRecentDocs": False,  # downloads stay out of the desktop's recent files
    "signon.rememberSignons": False,  # a password saved here would be deleted with the profile
    "browser.sessionstore.resume_from_crash": False,  # nothing to restore after a crash
    "browser.shell.checkDefaultBrowser": False,  # not the place to ask
    "browser.startup.homepage_override.mstone": "ignore",  # no "what's new" page on every start
}


class TemporaryError(RuntimeError):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


@dataclass
class Temporary:
    path: Path
    in_memory: bool
    swap_on_disk: bool
    guard_fd: int

    @property
    def profile(self) -> profile.Profile:
        return profile.Profile(name="temporary", path=self.path)

    def release(self) -> None:
        try:
            os.close(self.guard_fd)
        except OSError:
            pass


# -- where ---------------------------------------------------------------------------


def root() -> Path:
    runtime = paths.runtime_home()
    base = runtime / "temporary" if runtime else paths.cache_home() / "temporary"
    return paths.ensure_private_dir(base)


def _unescape(field: str) -> str:
    # /proc/self/mountinfo escapes space, tab, newline and backslash as octal.
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def filesystem_type(path: Path, mountinfo: str | None = None) -> str | None:
    """Type of the filesystem holding `path` (longest matching mount point)."""
    if mountinfo is None:
        try:
            mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        except OSError:
            return None
    target = os.path.realpath(path)
    best, best_type = "", None
    for line in mountinfo.splitlines():
        before, sep, after = line.partition(" - ")
        fields = before.split()
        if not sep or len(fields) < 5 or not after:
            continue
        mount_point = _unescape(fields[4])
        inside = target == mount_point or target.startswith(mount_point.rstrip("/") + "/")
        if inside and len(mount_point) >= len(best):
            best, best_type = mount_point, after.split()[0]
    return best_type


def swap_on_disk(swaps: str | None = None) -> bool:
    """True if a swap area other than compressed RAM (zram) is active."""
    if swaps is None:
        try:
            swaps = Path("/proc/swaps").read_text(encoding="utf-8")
        except OSError:
            return True  # unknown: do not claim memory only
    for line in swaps.splitlines()[1:]:
        name = line.split()[0] if line.split() else ""
        if name and not name.startswith("/dev/zram"):
            return True
    return False


def storage(path: Path) -> tuple[bool, bool]:
    """(in_memory, swap_on_disk) for a profile at `path`."""
    in_memory = filesystem_type(path) in ("tmpfs", "ramfs")
    return in_memory, swap_on_disk() if in_memory else False


# -- create and delete -------------------------------------------------------------


def _hold(path: Path) -> int:
    fd = os.open(path / GUARD, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, paths.PRIVATE_FILE_MODE)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise
    return fd


def create() -> Temporary:
    """A new, empty temporary profile; the caller holds its guard lock until it deletes it."""
    base = root()
    cleanup(base)
    path = base / f"{PREFIX}{secrets.token_hex(6)}"
    os.mkdir(path, paths.PRIVATE_DIR_MODE)
    fd = _hold(path)
    in_memory, swap = storage(path)
    now = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
    marker = {"schema": SCHEMA, "created": now, "in_memory": in_memory, "swap_on_disk": swap}
    paths.write_private_file(path / MARKER, json.dumps(marker, indent=2) + "\n")
    prof = profile.Profile(name="temporary", path=path)
    prof.save_settings(
        {
            "schema": profile.SETTINGS_SCHEMA,
            "created": now,
            "baseline_version": profile.BASELINE_VERSION,
            "provider": "builtin",
            "theme": True,
            "locale": profile.ui_language(),
            "seeded": {},
            "pending_prefs": {},
            "temporary": True,
        }
    )
    lines = ["// Nulavio: temporary profile, deleted when its browser closes"]
    lines += [f"user_pref({json.dumps(name)}, {json.dumps(value)});" for name, value in PREFS.items()]
    paths.write_private_file(path / "prefs.js", "\n".join(lines) + "\n")
    log.event("temporary.create", in_memory=in_memory, swap_on_disk=swap)
    return Temporary(path=path, in_memory=in_memory, swap_on_disk=swap, guard_fd=fd)


def _checked(path: Path) -> Path:
    """`path` if it is a temporary profile directory Nulavio may delete; raises otherwise."""
    base = root().resolve()
    path = Path(path)
    if path.is_symlink() or path.parent.resolve() != base or not path.name.startswith(PREFIX):
        raise TemporaryError("not-temporary", f"not a temporary profile: {path}")
    if not (path / MARKER).is_file():
        raise TemporaryError("not-temporary", f"no marker in {path}")
    return path


def remove(path: Path, *, attempts: int = 20, pause: float = 0.5) -> None:
    """Delete a temporary profile. Its engine must be gone (helper processes may still be closing files)."""
    path = _checked(path)
    if profile.Profile(name="temporary", path=path).running_pid():
        raise TemporaryError("in-use", "the temporary profile is still open")
    if not shutil.rmtree.avoids_symlink_attacks:  # Linux has the fd-based version, which never follows links
        raise TemporaryError("unsafe-platform")
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            break
        except FileNotFoundError:
            break
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause)  # a closing helper process was still writing a file
    log.event("temporary.delete")


def cleanup(base: Path | None = None) -> int:
    """Delete orphaned temporary profiles: nobody holds the guard lock and no engine uses them."""
    base = base or root()
    removed = 0
    for entry in base.iterdir():
        if not entry.name.startswith(PREFIX) or entry.is_symlink() or not entry.is_dir():
            continue
        if not (entry / MARKER).is_file():
            continue  # half-created a moment ago, or not ours
        try:
            fd = _hold(entry)
        except BlockingIOError:
            continue  # its supervisor or reaper is alive
        except OSError:
            continue
        try:
            if profile.Profile(name="temporary", path=entry).running_pid():
                continue
            remove(entry)
            removed += 1
        except (OSError, TemporaryError):
            continue
        finally:
            os.close(fd)
    if removed:
        log.event("temporary.cleanup", removed=removed)
    return removed


# -- the reaper (profiles opened by the browser) ------------------------------------


def reap(path: Path, guard_fd: int | None = None, *, grace: float = 120.0, poll: float = 0.5) -> str:
    """Delete the profile once its engine has come and gone. Returns what happened, for the log."""
    path = _checked(path)
    if guard_fd is not None:
        fcntl.flock(guard_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # inherited: already ours; fails loudly otherwise
    prof = profile.Profile(name="temporary", path=path)
    deadline = time.monotonic() + grace
    while not prof.running_pid():
        if time.monotonic() > deadline:
            remove(path)
            return "unused"
        time.sleep(poll)
    while prof.running_pid():
        time.sleep(poll)
    remove(path)
    return "closed"


def spawn_reaper(temp: Temporary, *, grace: float = 120.0) -> subprocess.Popen:
    """A detached process that inherits the guard lock and deletes the profile after its browser closes."""
    launcher_dir = Path(__file__).resolve().parents[1]
    bootstrap = "import sys; sys.path.insert(0, sys.argv[1]); from nulavio_launcher.cli import main; sys.exit(main(sys.argv[2:]))"
    os.set_inheritable(temp.guard_fd, True)
    try:
        return subprocess.Popen(
            [sys.executable, "-I", "-c", bootstrap, str(launcher_dir), "temporary", "reap",
             "--path", str(temp.path), "--guard-fd", str(temp.guard_fd), "--grace", str(grace)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            pass_fds=(temp.guard_fd,),
        )  # fmt: skip
    finally:
        os.set_inheritable(temp.guard_fd, False)


# -- helper API for the browser (Shell) --------------------------------------------


def api_request(request: dict) -> dict:
    op = request.get("op")
    if op == "create":
        temp = create()
        try:
            spawn_reaper(temp)
        except OSError:
            remove(temp.path)
            raise
        finally:
            temp.release()  # the reaper holds the lock now
        return {"path": str(temp.path), "inMemory": temp.in_memory, "swapOnDisk": temp.swap_on_disk}
    raise TemporaryError("bad-request", "op")
