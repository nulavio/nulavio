"""Filesystem layout and private-directory helpers.

Everything Nulavio writes lives under XDG base directories in a ``nulavio``
sub-directory, never under ``~/.mozilla`` or ``~/.config/mozilla`` (which
belong to the user's regular Firefox). ``NULAVIO_HOME`` relocates all of it,
which the test-suite uses for throwaway environments.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

APP = "nulavio"
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


class UnsafePathError(RuntimeError):
    """A path we are about to trust is a symlink or belongs to someone else."""


def repo_root() -> Path:
    """Root of the source checkout (launcher/nulavio_launcher/paths.py -> ../..)."""
    return Path(__file__).resolve().parents[2]


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "")
    # The XDG spec says relative paths must be ignored.
    if value and os.path.isabs(value):
        return Path(value)
    return Path.home() / fallback


def _home_override() -> Path | None:
    value = os.environ.get("NULAVIO_HOME", "")
    return Path(value) if value and os.path.isabs(value) else None


def data_home() -> Path:
    override = _home_override()
    return override / "data" if override else _xdg("XDG_DATA_HOME", ".local/share") / APP


def state_home() -> Path:
    override = _home_override()
    return override / "state" if override else _xdg("XDG_STATE_HOME", ".local/state") / APP


def cache_home() -> Path:
    override = _home_override()
    return override / "cache" if override else _xdg("XDG_CACHE_HOME", ".cache") / APP


def runtime_home() -> Path | None:
    """Per-session directory for short-lived files ($XDG_RUNTIME_DIR/nulavio), or None.

    The XDG directory must be an absolute path, owned by the user and private
    (0700, as the spec requires); otherwise it is not used.
    """
    override = _home_override()
    if override:
        return override / "runtime"
    value = os.environ.get("XDG_RUNTIME_DIR", "")
    if not value or not os.path.isabs(value):
        return None
    try:
        if check_private(Path(value), PRIVATE_DIR_MODE):
            return None
    except (OSError, UnsafePathError):
        return None
    return Path(value) / APP


def profiles_root() -> Path:
    return data_home() / "profiles"


def config_dir() -> Path:
    return repo_root() / "browser" / "config"


def assets_dir() -> Path:
    return repo_root() / "docs" / "brand" / "assets"


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` (and missing parents) with mode 0700.

    Refuses symlinks and directories owned by another user, then tightens
    permissions if they are broader than 0700. Returns the path.
    """
    path = Path(path)
    missing = []
    probe = path
    while not probe.exists() and not probe.is_symlink():
        missing.append(probe)
        probe = probe.parent
    for directory in reversed(missing):
        try:
            os.mkdir(directory, PRIVATE_DIR_MODE)
        except FileExistsError:
            pass  # created meanwhile by another thread or process; checked below
    check_private(path, PRIVATE_DIR_MODE, fix=True)
    return path


def check_private(path: Path, mode: int, fix: bool = False) -> list[str]:
    """Return problems with ``path``'s ownership/mode; optionally fix the mode."""
    problems: list[str] = []
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        raise UnsafePathError(f"refusing to use symlink: {path}")
    if st.st_uid != os.getuid():
        raise UnsafePathError(f"not owned by the current user: {path}")
    current = stat.S_IMODE(st.st_mode)
    if current & ~mode:
        problems.append(f"{path}: mode {current:04o} broader than {mode:04o}")
        if fix:
            os.chmod(path, mode)
    return problems


def write_private_file(path: Path, data: str | bytes) -> None:
    """Atomically write ``data`` to ``path`` with mode 0600."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data.encode("utf-8") if isinstance(data, str) else data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
