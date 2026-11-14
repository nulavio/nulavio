"""Encrypted profile storage (ADR 0006, decision D2): one gocryptfs container per profile.

Layout, for a profile directory P (what the engine opens with --profile):

    P            mount point: empty and read-only (0500) while locked
    P.vault/     vault.json (envelopes) and cipher/ (gocryptfs, XChaCha20-Poly1305)

The volume password is derived from the profile DEK (`storage/gocryptfs`), so
only an unlock method that releases the DEK can open it. It goes to gocryptfs
on stdin, never on the command line or disk. A locked mount point is
read-only, so an engine started on it directly cannot write plaintext there.
Inside the volume, `.nulavio-vault/state.json` mirrors the vault's generation
to detect a rolled-back vault.json (threat model U-T21). A change to the unlock
methods records the new generation there even while the profile is locked
(`Container.recording`), through a mount of its own that no profile path sees.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .. import log
from . import sodium
from .core import Vault, VaultError, kdf

LOCKED_MODE = 0o500
# What reading or writing the record inside the volume can raise besides a StorageError: the
# volume gone, or a record that is not what this program wrote.
RECORD_ERRORS = (OSError, ValueError, TypeError, AttributeError)
STATE_DIR = ".nulavio-vault"
TIMEOUT = 60


class StorageError(VaultError):
    pass


def tools_available() -> bool:
    return (
        bool(shutil.which("gocryptfs"))
        and bool(shutil.which("fusermount3") or shutil.which("fusermount"))
        and os.access("/dev/fuse", os.R_OK | os.W_OK)
    )


def storage_password(vault: Vault) -> str:
    """64 hex characters derived from the DEK; gocryptfs wraps its own master key with it."""
    if not vault.unlocked:
        raise StorageError("locked")
    key = kdf(vault.dek, "storage/gocryptfs", vault.profile_id)
    try:
        return bytes(key).hex()
    finally:
        sodium.memzero(key)


def _unescape(field: str) -> str:
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


def mounted_paths() -> set[str]:
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return set()
    return {_unescape(line.split()[4]) for line in lines if len(line.split()) > 4}


class Container:
    def __init__(self, mountpoint: Path):
        self.mountpoint = Path(mountpoint)

    @property
    def root(self) -> Path:
        return self.mountpoint.with_name(self.mountpoint.name + ".vault")

    @property
    def cipher(self) -> Path:
        return self.root / "cipher"

    @property
    def vault_path(self) -> Path:
        return self.root / "vault.json"

    @property
    def state_path(self) -> Path:
        return self.mountpoint / STATE_DIR / "state.json"

    def exists(self) -> bool:
        return self.vault_path.exists() and (self.cipher / "gocryptfs.conf").exists()

    def mounted(self) -> bool:
        return str(self.mountpoint.resolve()) in mounted_paths()

    def load_vault(self) -> Vault:
        return Vault.load(self.vault_path)

    def secure_if_locked(self) -> None:
        """Make the mount point read-only again when the volume is not mounted.

        unmount() does it after a clean lock; a crash, a reboot, a killed gocryptfs or its
        -idle timer leave it writable, and an engine started on it directly would write a
        new profile there in the clear (audit V6).
        """
        try:
            if self.exists() and self.mountpoint.is_dir() and not self.mounted():
                os.chmod(self.mountpoint, LOCKED_MODE)
        except OSError:
            pass
        self._clear_maintenance()

    def _clear_maintenance(self) -> None:
        """Unmount and remove what a change to the unlock methods left behind when its process was
        killed: the volume mounted at P.vault/maintenance-*, readable by the user while the profile
        counts as locked. Only when no change is running (the state lock is free)."""
        try:
            leftovers = list(self.root.glob("maintenance-*"))
        except OSError:
            return
        if not leftovers:
            return
        try:
            with self._state_lock(wait=0):
                for path in leftovers:
                    with contextlib.suppress(OSError, StorageError, subprocess.SubprocessError):
                        self._unmount_path(path, wait=2.0)
                        path.rmdir()
        except StorageError:
            pass  # a change is running: its own

    # -- lifecycle ----------------------------------------------------------------

    def _gocryptfs(self, args: list[str], password: str, timeout: float = TIMEOUT) -> None:
        # Not pipes for the output: the mounting daemon inherits them and would keep them open.
        with tempfile.TemporaryFile() as err:
            try:
                result = subprocess.run(["gocryptfs", *args], input=(password + "\n").encode(), stdout=subprocess.DEVNULL,
                                        stderr=err, timeout=timeout, check=False)  # fmt: skip
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise StorageError("storage-unavailable", type(exc).__name__) from None
            if result.returncode != 0:
                err.seek(0)
                message = err.read().decode(errors="replace").strip().splitlines()
                # gocryptfs exit codes: 12 = wrong password; 10, 19 = mount problems.
                raise StorageError("wrong-key" if result.returncode == 12 else "storage-failed", (message or [""])[-1][:200])

    def init(self, vault: Vault) -> None:
        """Create the encrypted volume for a vault (new, empty profile)."""
        if self.cipher.exists() or (self.mountpoint.exists() and any(self.mountpoint.iterdir())):
            raise StorageError("exists", str(self.mountpoint))
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.cipher.mkdir(mode=0o700)
        self.mountpoint.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.mountpoint, LOCKED_MODE)
        # The password is 256 bits of key material, so gocryptfs's own scrypt can be cheap.
        self._gocryptfs(["-init", "-q", "-xchacha", "-scryptn", "10", str(self.cipher)], storage_password(vault))

    def mount(self, vault: Vault, idle_minutes: int | None = None) -> None:
        if not self.exists():
            raise StorageError("not-encrypted")
        if self.mounted():
            return
        if any(self.mountpoint.iterdir()):
            raise StorageError("mountpoint-not-empty", "plaintext files appeared in a locked profile")
        # The state lock before the volume is mounted: if it cannot be had, nothing is opened.
        with self._state_lock():
            if not self._same_as_on_disk(vault):
                # A change to the unlock methods finished while this waited for the lock: what was
                # read is no longer the key file (checking it would look like a rollback).
                raise StorageError("changed", "the profile's key file changed since it was read; try again")
            os.chmod(self.mountpoint, 0o700)  # fusermount needs write access to the mount point
            args = ["-q", "-nosyslog"]
            if idle_minutes:
                args += ["-idle", f"{int(idle_minutes)}m"]
            try:
                self._gocryptfs([*args, str(self.cipher), str(self.mountpoint)], storage_password(vault))
            except StorageError:
                os.chmod(self.mountpoint, LOCKED_MODE)
                raise
            try:
                self._check_state(vault)
            except BaseException as exc:
                # Whatever went wrong with the check (a rollback, a damaged record, an I/O error):
                # a volume whose generation was not checked does not stay open, also when a file
                # in it is held open (it is then detached), and the reason given is the check's.
                with contextlib.suppress(StorageError, subprocess.SubprocessError, OSError):
                    self.unmount(wait=2.0, lazy_after=True)
                if isinstance(exc, RECORD_ERRORS):
                    raise StorageError("storage-failed", type(exc).__name__) from None
                raise
            self._settle_recovery_code(vault)

    def _settle_recovery_code(self, vault: Vault) -> None:
        """A recovery code replacement nobody confirmed (#187), settled now that the profile opened:
        kept if this unlock used the new code, undone otherwise. Under the state lock, recorded like
        any change. Not settled is no reason to stay locked: both codes still open the profile."""
        if vault.pending_recovery_code() is None:
            return

        # A handle on the volume from before the save to the record, as in recording(): the record goes into
        # this volume or nowhere, also if the volume goes away in between (#187 review).
        # Whatever stops it is said (`vault.settled`, `vault.settle_warning`), never only logged: until it is
        # settled, the code it was to replace still opens the profile (#187 review).
        def unsettled(code: str) -> None:
            vault.settled = "unsettled"
            log.event("vault.recovery-code-not-settled", code=code)

        try:
            volume = os.open(self.mountpoint, os.O_RDONLY | os.O_DIRECTORY)
        except OSError as exc:
            unsettled(type(exc).__name__)
            return
        try:
            if os.fstat(volume).st_dev == os.stat(self.mountpoint.parent).st_dev:
                unsettled("not-mounted")
                return
            before = json.loads(json.dumps(vault.meta))
            outcome = vault.settle_recovery_code()
            if outcome is None:
                return
            try:
                vault.save()
            except (VaultError, OSError) as exc:
                # A save can fail after the key file was already replaced (syncing its directory): what is said is
                # what is on disk, read again, not what was meant (#187 review, round 3).
                try:
                    disk = json.loads(vault.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    disk = before
                if disk.get("pending_recovery") or disk.get("generation") == before.get("generation"):
                    vault.meta = before  # still waiting: both codes still open it; tried again at the next unlock
                    unsettled(getattr(exc, "code", type(exc).__name__))
                    return
                vault.meta = disk  # it was saved: settled, and said so; its record is tried below
                log.event("vault.recovery-code-saved-with-error", code=getattr(exc, "code", type(exc).__name__))
            vault.settled = outcome
            log.event("vault.recovery-code-settled", outcome=outcome)
            try:
                self._check_state(vault, volume)  # saved: a record left behind is written at the next unlock
            except (VaultError, *RECORD_ERRORS) as exc:
                vault.settle_warning = "not-recorded"
                log.event("vault.change-not-recorded", code=getattr(exc, "code", type(exc).__name__))
        finally:
            os.close(volume)

    @contextlib.contextmanager
    def _state_lock(self, wait: float = 120.0):
        """One process at a time checks and writes the generation, or changes the unlock methods:
        two that each started from the same key file would otherwise both save "the next"
        generation, and the second would bring back what the first removed."""
        try:
            fd = os.open(self.root / "state.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError as exc:  # something else sits where the lock file goes: nothing is opened on that
            raise StorageError("storage-failed", f"state lock: {type(exc).__name__}") from None
        try:
            deadline = time.monotonic() + wait
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise StorageError("busy", "another change to this profile is in progress") from None
                    time.sleep(0.2)
                except OSError as exc:  # a file system that does not lock
                    raise StorageError("storage-failed", f"state lock: {type(exc).__name__}") from None
            yield
        finally:
            os.close(fd)  # releases the lock, also when the process dies

    def _check_state(self, vault: Vault, volume_fd: int | None = None) -> None:
        """Compare the generation recorded inside the volume with the vault's, then record the
        vault's. `volume_fd`: an open handle on the volume's root; everything is done relative to
        it, so the record goes into that volume or nowhere, whatever happened to its mount point."""
        if volume_fd is None:
            volume_fd = os.open(self.mountpoint, os.O_RDONLY | os.O_DIRECTORY)
            try:
                return self._check_state(vault, volume_fd)
            finally:
                os.close(volume_fd)
        generation = int(vault.meta.get("generation", 0))
        flags = os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        with contextlib.suppress(FileExistsError):
            os.mkdir(STATE_DIR, 0o700, dir_fd=volume_fd)
        state_dir = os.open(STATE_DIR, os.O_RDONLY | os.O_DIRECTORY | flags, dir_fd=volume_fd)
        try:
            try:
                fd = os.open("state.json", os.O_RDONLY | flags, dir_fd=state_dir)
            except FileNotFoundError:
                state = None
            else:
                with os.fdopen(fd, encoding="utf-8") as handle:
                    state = json.load(handle)
            if state is not None:
                if state.get("profile_id") != vault.profile_id:
                    raise StorageError("wrong-container")
                if int(state.get("generation", 0)) > generation:
                    raise StorageError("rollback", "vault.json is older than the profile it protects")
            # Its own name: the profile's mount and a maintenance mount are two views of one directory.
            tmp = f"state.{os.getpid()}.tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | flags, 0o600, dir_fd=state_dir)
            try:
                os.write(fd, json.dumps({"profile_id": vault.profile_id, "generation": generation}).encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp, "state.json", src_dir_fd=state_dir, dst_dir_fd=state_dir)
            os.fsync(state_dir)
        finally:
            os.close(state_dir)

    def record_generation(self, vault: Vault) -> None:
        """After saving the vault while mounted: keep the mirror in step."""
        if self.mounted():
            with self._state_lock():
                self._check_state(vault)

    def _same_as_on_disk(self, vault: Vault) -> bool:
        path = vault.path.with_suffix(vault.path.suffix + ".bak") if vault.from_backup else vault.path
        try:
            return json.loads(path.read_text(encoding="utf-8")) == vault.meta
        except (OSError, ValueError):
            return False

    @contextlib.contextmanager
    def recording(self, vault: Vault):
        """Around a change to the unlock methods: yields what records the saved vault's generation
        inside the volume, whether or not the profile is unlocked.

        Entered with the vault unlocked, after every question this program asks and before
        anything changes. It holds the profile's state lock to the end, and refuses a vault that
        is no longer what is on disk: another change got there first, and saving this one would
        undo it. It keeps a handle on the volume for the whole change and writes the record
        through it, so the record lands in the volume or raises ("not-recorded"), never on a bare
        directory. A locked profile is mounted for this alone, at a private directory under
        P.vault/ (never at P: the browser and the launcher read "mounted at P" as "unlocked").
        Without the record, a method removed or replaced while the profile was locked left the
        mirror behind, and the earlier vault.json, put back, still opened the profile through the
        launcher (threat model U-T21). If the volume cannot be mounted the change does not happen.
        A rolled-back vault.json is refused here as it is at unlock.

        What it does not do: make the two writes one. The key file is saved first and the record
        written next; a process killed between them leaves the change without its record until
        the profile is next unlocked (which writes it). And while a locked profile's change runs,
        its files are readable at the maintenance directory by the user's own processes.
        """
        with self._state_lock():
            if not self._same_as_on_disk(vault):
                raise StorageError("changed", "the profile's key file changed since it was read; try again")
            if not self.exists():
                raise StorageError("not-encrypted")
            mount = None
            try:
                if self.mounted():
                    where = self.mountpoint
                else:
                    self._clear_stale_dirs()
                    where = mount = Path(tempfile.mkdtemp(prefix="maintenance-", dir=self.root))
                    # -idle: should this process die here, gocryptfs unmounts by itself a minute later.
                    self._gocryptfs(["-q", "-nosyslog", "-idle", "1m", str(self.cipher), str(mount)], storage_password(vault))
                # In use from here on: the idle timer and an ordinary unmount leave it alone.
                try:
                    volume = os.open(where, os.O_RDONLY | os.O_DIRECTORY)
                except OSError as exc:
                    raise StorageError("storage-failed", type(exc).__name__) from None
                try:
                    # The handle is on the volume, not on the directory it was mounted on a moment ago.
                    if os.fstat(volume).st_dev == os.stat(where.parent).st_dev:
                        raise StorageError("storage-failed", "the volume is not mounted")

                    def record() -> None:
                        try:
                            self._check_state(vault, volume)
                        except RECORD_ERRORS as exc:  # the volume went away under the handle, or its record is damaged
                            raise StorageError("not-recorded", type(exc).__name__) from None

                    try:
                        self._check_state(vault, volume)  # before anything changes: a failure here changed nothing
                    except RECORD_ERRORS as exc:
                        raise StorageError("storage-failed", type(exc).__name__) from None
                    yield record
                finally:
                    os.close(volume)
            finally:
                if mount is not None:
                    try:
                        self._unmount_path(mount)
                    except (StorageError, subprocess.SubprocessError, OSError):
                        pass  # the change itself stands; the next use of the profile unmounts what is left
                    with contextlib.suppress(OSError):
                        mount.rmdir()

    def _clear_stale_dirs(self) -> None:
        for stale in self.root.glob("maintenance-*"):  # left by a process that died; empty once gocryptfs let go
            with contextlib.suppress(OSError):
                stale.rmdir()

    @staticmethod
    def _is_mounted(path: Path) -> bool:
        return str(path.resolve()) in mounted_paths()

    def _unmount_path(self, path: Path, wait: float = 15.0) -> None:
        tool = shutil.which("fusermount3") or shutil.which("fusermount") or "fusermount3"
        deadline = time.monotonic() + wait
        while self._is_mounted(path):
            result = subprocess.run([tool, "-u", str(path)], capture_output=True, timeout=30, check=False)
            if result.returncode == 0:
                break
            if time.monotonic() > deadline:
                # Nothing but this process opened a file there: detach it rather than leave it.
                subprocess.run([tool, "-u", "-z", str(path)], capture_output=True, timeout=30, check=False)
                if self._is_mounted(path):
                    raise StorageError("busy", "the profile could not be locked again after the change")
                break
            time.sleep(0.3)

    def unmount(self, wait: float = 15.0, lazy_after: bool = False) -> None:
        """Unmount; while files are still open, retry for `wait` seconds.

        `lazy_after`: then detach anyway (the volume disappears from the file
        system at once; files already open stay usable until closed). Used when
        the engine has exited and only its helpers are still closing files.
        """
        tool = shutil.which("fusermount3") or shutil.which("fusermount") or "fusermount3"
        deadline = time.monotonic() + wait
        while self.mounted():
            result = subprocess.run([tool, "-u", str(self.mountpoint)], capture_output=True, timeout=30, check=False)
            if result.returncode == 0:
                break
            if time.monotonic() > deadline:
                if lazy_after:
                    subprocess.run([tool, "-u", "-z", str(self.mountpoint)], capture_output=True, timeout=30, check=False)
                    if not self.mounted():
                        break
                raise StorageError("busy", result.stderr.decode(errors="replace").strip()[:200])
            time.sleep(0.3)  # engine helper processes still closing files
        os.chmod(self.mountpoint, LOCKED_MODE)

    def destroy(self) -> None:
        """Delete the profile and its container (unmounted first)."""
        if self.mounted():
            self.unmount()
        for top in (self.mountpoint, self.root):
            if top.exists():
                for dirpath, _dirs, _files in os.walk(top):
                    os.chmod(dirpath, 0o700)
                shutil.rmtree(top)


MIGRATED = "migrated"  # in P.vault/: the copy into the volume is complete


class _Interrupted(BaseException):
    pass


@contextlib.contextmanager
def _signals_as_exceptions():
    """SIGTERM and SIGHUP (a closed terminal) end the migration through its clean-up path."""

    def interrupted(signum, _frame):
        raise _Interrupted(signal.Signals(signum).name)

    previous = {}
    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            previous[sig] = signal.signal(sig, interrupted)
    except ValueError:  # not the main thread: the caller's own handling applies
        pass
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _migration_lock(path: Path, *, wait: bool) -> int | None:
    """An exclusive lock held for the whole migration; released by the kernel if the process dies."""
    fd = os.open(path.with_name(path.name + ".migrating.lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _release(path: Path, fd: int) -> None:
    path.with_name(path.name + ".migrating.lock").unlink(missing_ok=True)
    os.close(fd)


def _mark_complete(root: Path) -> None:
    """Record, durably, that the copy is complete, before any plaintext original is deleted:
    recovery after a power loss during the clean-up must finish it, never undo it."""
    os.sync()  # the copy itself (written through the volume) reaches the disk first
    fd = os.open(root / MIGRATED, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    dir_fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _undo(path: Path, staging: Path) -> None:
    container = Container(path)
    if container.mounted():
        container.unmount(lazy_after=True)
    shutil.rmtree(container.root, ignore_errors=True)
    if path.exists():
        for dirpath, _dirs, _files in os.walk(path):
            os.chmod(dirpath, 0o700)
        shutil.rmtree(path, ignore_errors=True)
    os.rename(staging, path)


def recover_interrupted(path: Path) -> str | None:
    """Finish or undo a migration that a crash, SIGKILL or power loss interrupted (audit V5).

    Without this the plaintext copy stayed next to the profile, unnoticed, while the
    profile was reported as protected. A complete copy is finished (the plaintext is
    deleted); anything else is undone (the profile is back as it was, unprotected).
    Returns "finished", "undone", or None (nothing to do, or a migration is running).
    """
    path = Path(path)
    staging = path.with_name(path.name + ".plaintext-migrating")
    if not staging.exists():
        return None
    fd = _migration_lock(path, wait=False)
    if fd is None:
        return None  # another process is migrating it now
    try:
        if not staging.exists():
            return None
        marker = Container(path).root / MIGRATED
        if marker.exists():
            shutil.rmtree(staging)
            marker.unlink()
            return "finished"
        _undo(path, staging)
        return "undone"
    finally:
        _release(path, fd)


def encrypt_existing(path: Path, vault: Vault) -> Container:
    """Move an existing profile directory into a new container (engine must not be using it).

    The plaintext originals are deleted afterwards; on SSDs and in backups, fragments may remain.
    An interruption the clean-up below cannot catch (SIGKILL, power loss) is finished or
    undone by recover_interrupted() the next time the profile is used.
    """
    path = Path(path)
    if not path.is_dir():
        raise StorageError("missing", str(path))  # the caller checks that no engine is using it
    staging = path.with_name(path.name + ".plaintext-migrating")
    if staging.exists():
        raise StorageError("exists", str(staging))
    fd = _migration_lock(path, wait=True)
    try:
        with _signals_as_exceptions():
            os.rename(path, staging)
            container = Container(path)
            try:
                container.init(vault)
                container.mount(vault)
                for item in staging.iterdir():
                    target = path / item.name
                    if item.is_dir() and not item.is_symlink():
                        shutil.copytree(item, target, symlinks=True)
                    else:
                        shutil.copy2(item, target, follow_symlinks=False)
                container.unmount()
                _mark_complete(container.root)
            except BaseException:
                _undo(path, staging)
                raise
            shutil.rmtree(staging)
            (container.root / MIGRATED).unlink()
    finally:
        _release(path, fd)
    return container
