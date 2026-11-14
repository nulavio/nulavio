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

A new key for the volume (`rekey`, ADR 0015): a second volume under P.vault/rekey/, made for a new
DEK, takes a checked copy of the files and then the first one's place.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
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
            # A new key that was interrupted is finished or undone first (ADR 0015): never the old volume
            # opened while the new one waits to take its place. If it was finished, the key file changed.
            self._settle_new_key()
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

    def _settle_new_key(self) -> str | None:
        """Under the state lock: finish ("finished") or undo ("undone") what an interrupted new key left
        (ADR 0015); None when there was nothing, or when what an undone one left could not be removed yet
        (the profile itself is untouched by it, and it is tried again next time). A switch that was begun
        and cannot be finished now raises: until it is, the volume and the key file may not match."""
        begun = lambda: (self.root / REKEY / REKEY_COMPLETE).exists() or (self.root / "cipher.old").exists()  # noqa: E731
        try:
            return _rekey_settle(self)
        except StorageError as exc:
            if begun():
                raise
            log.event("vault.rekey-leftover", code=exc.code)
        except (OSError, subprocess.SubprocessError) as exc:
            if begun():
                raise StorageError("rekey-unfinished", type(exc).__name__) from None
            log.event("vault.rekey-leftover", code=type(exc).__name__)
        return None

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
                    # Neither the save nor the file says what happened: not known, and said so (round 3).
                    vault.meta = before
                    vault.settled = "unknown"
                    log.event("vault.recovery-code-not-settled", code="unknown")
                    return
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
            self._refuse_older(vault, state_dir)
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

    @staticmethod
    def _refuse_older(vault: Vault, state_dir: int) -> None:
        """Read the record in the volume (`state_dir`: an open handle on its directory) and refuse a
        vault that is another profile's, or older than the record."""
        flags = os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open("state.json", os.O_RDONLY | flags, dir_fd=state_dir)
        except FileNotFoundError:
            return
        with os.fdopen(fd, encoding="utf-8") as handle:
            state = json.load(handle)
        if state.get("profile_id") != vault.profile_id:
            raise StorageError("wrong-container")
        if int(state.get("generation", 0)) > int(vault.meta.get("generation", 0)):
            raise StorageError("rollback", "vault.json is older than the profile it protects")

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
            self._settle_new_key()  # as in mount(): an interrupted new key first
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


# -- a new key for the volume (ADR 0015) ---------------------------------------------------------
#
# P.vault/rekey/ while it runs:
#
#     vault.json(.bak)   the new key file: a new DEK, the methods that could be carried over
#     cipher/            the new volume, made for that DEK (its own gocryptfs master key)
#     old/, new/         where the two volumes are mounted for the copy (old/ read-only)
#     complete           written once the copy is whole, checked and on disk
#
# Before `complete` exists nothing outside rekey/ has changed: an interruption is undone by removing
# rekey/. Once it exists the new volume and key file take the old ones' place, step by step, and an
# interruption is finished from where it stopped. recover_rekey() does either the next time the
# profile is used. The old volume is only ever read, and never deleted before the new one is in place.

REKEY = "rekey"
REKEY_COMPLETE = "complete"
REKEY_MARGIN = 64 * 1024 * 1024  # free space asked for beyond the volume's own size


def _tree_size(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, name)).st_size
    return total


def rekey_space(box: Container) -> dict:
    """What a new key needs: the volume's size (a second copy exists while it runs) and the free space."""
    size = _tree_size(box.cipher)
    free = shutil.disk_usage(box.root).free
    return {"size": size, "free": free, "enough": free >= size + REKEY_MARGIN}


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _listing(root: Path) -> dict[str, tuple]:
    """Every entry under `root` by its relative path: kind, and what must be equal in a copy."""
    out: dict[str, tuple] = {}
    for dirpath, dirs, files in os.walk(root):
        for name in dirs + files:
            full = os.path.join(dirpath, name)
            info = os.lstat(full)
            rel = os.path.relpath(full, root)
            if os.path.islink(full):
                out[rel] = ("link", os.readlink(full))
            elif os.path.isdir(full):
                out[rel] = ("dir",)
            else:
                out[rel] = ("file", info.st_size, _file_digest(full))
    return out


def _copy_checked(source: Path, target: Path) -> None:
    """Copy a volume's files into another and read both back: same names, kinds, sizes and contents.
    `source` and `target` are reached through open handles on the two volumes (/proc/self/fd/N), not
    through their mount points: a volume detached under this process is still the one read and written,
    never the empty directory it was mounted on."""
    if not (source / STATE_DIR / "state.json").is_file():
        # Every volume has its record from its first mount: without it this is not the profile's volume.
        raise StorageError("storage-failed", "the profile's volume is not there to copy")
    for item in source.iterdir():
        dest = target / item.name
        if item.is_dir() and not item.is_symlink():
            shutil.copytree(item, dest, symlinks=True)
        else:
            shutil.copy2(item, dest, follow_symlinks=False)
    original = _listing(source)
    if os.path.join(STATE_DIR, "state.json") not in original or original != _listing(target):
        raise StorageError("copy-mismatch", "the copy into the new volume is not the same as the original")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _rekey_remove_staging(box: Container) -> None:
    """Take rekey/ away. The marker goes first, durably: what is left half removed is never taken for a
    complete copy. The two mount directories are unmounted first and only ever removed empty: nothing
    here can reach the profile's files through a volume that is still mounted."""
    staging = box.root / REKEY
    if not staging.is_dir():
        return
    if (staging / REKEY_COMPLETE).exists():
        (staging / REKEY_COMPLETE).unlink()
        _fsync_dir(staging)
    for name in ("old", "new"):
        where = staging / name
        if where.is_dir():
            box._unmount_path(where, wait=5.0)
            if Container._is_mounted(where):
                raise StorageError("busy", "a volume is still mounted for a new key")
            os.rmdir(where)  # empty, or this stops here
    cipher = staging / "cipher"
    if cipher.exists():
        for dirpath, _dirs, _files in os.walk(cipher):
            os.chmod(dirpath, 0o700)
        shutil.rmtree(cipher)
    for leftover in staging.iterdir():
        leftover.unlink()  # the new key file, its copy, a temporary one
    with contextlib.suppress(FileNotFoundError):
        staging.rmdir()


def _volume_in_use(box: Container) -> bool:
    """Whether the profile's volume is mounted anywhere: at the profile's own directory, or from its
    encrypted directory (also under the name it gets while the new one takes its place)."""
    if box.mounted():
        return True
    sources = {str(path.resolve()) for path in (box.cipher, box.root / "cipher.old")}
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return False
    for line in lines:
        _, _, after = line.partition(" - ")
        fields = after.split()
        if len(fields) > 1 and fields[0].startswith("fuse") and _unescape(fields[1]) in sources:
            return True
    return False


def _rekey_finish(box: Container) -> None:
    """The new volume and key file take the old ones' place. Every step can be repeated: started again
    after an interruption, it goes on from what it finds. Never while the profile's volume is mounted:
    its encrypted directory is renamed and deleted here."""
    if _volume_in_use(box):
        raise StorageError("busy", "the profile's volume is mounted; the new key is put in place once it is not")
    staging, old_cipher = box.root / REKEY, box.root / "cipher.old"
    if (staging / "cipher").exists():
        if box.cipher.exists():
            os.rename(box.cipher, old_cipher)
        os.rename(staging / "cipher", box.cipher)
        _fsync_dir(box.root)
    # The copy first, as Vault.save() does: at no point does a key file from before lie next to the new volume
    # as the only one that loads.
    for name in ("vault.json.bak", "vault.json"):
        if (staging / name).exists():
            os.replace(staging / name, box.root / name)
    _fsync_dir(box.root)
    if old_cipher.exists():
        for dirpath, _dirs, _files in os.walk(old_cipher):
            os.chmod(dirpath, 0o700)
        shutil.rmtree(old_cipher)
    _rekey_remove_staging(box)  # the marker first
    _fsync_dir(box.root)


def _rekey_settle(box: Container) -> str | None:
    """Under the profile's state lock: finish ("finished") or undo ("undone") what an interrupted new key
    left; None when there is nothing. Once the marker exists it is only ever finished."""
    staging = box.root / REKEY
    if not staging.exists():
        return None
    if (staging / REKEY_COMPLETE).exists():
        _rekey_finish(box)
        return "finished"
    _rekey_remove_staging(box)
    return "undone"


def recover_rekey(path: Path) -> str | None:
    """Finish or undo a new key that was interrupted (a crash, SIGKILL, power loss). "finished": the copy
    was whole, and the new volume and key file are now in place. "undone": it was not, and the profile is as
    it was before, its unlock methods included. None: nothing to do, one is running now, the profile's volume
    is still mounted, or what an undone one left could not be removed yet."""
    box = Container(Path(path))
    if not (box.root / REKEY).exists():
        return None
    try:
        with box._state_lock(wait=0):
            return box._settle_new_key()
    except StorageError as exc:
        if exc.code == "busy":
            return None  # a new key is being made now, or a volume is still mounted: left for the next time
        raise


def rekey(box: Container, old: Vault, carry) -> Vault:
    """Give a locked profile a new key: a new DEK and a new volume, the files copied and checked, the old
    volume and key file gone. `old`: the profile's vault, unlocked. `carry(new)`: adds to the new vault
    (unlocked, empty) every unlock method that can be made again, and returns what to call if this is
    undone. Returns the new vault, unlocked and saved; the caller locks it.

    Nothing of the profile changes before the copy is whole and checked; from then on the switch is
    finished even if this process dies (recover_rekey), and is never undone: an error after that point is
    "rekey-unfinished". While it runs, the files are readable at P.vault/rekey/old and rekey/new by the
    user's own processes, as during any change to a locked profile.
    """
    with box._state_lock():
        box._settle_new_key()  # what an earlier one left; if it was finished, the key file is no longer `old`
        if not box._same_as_on_disk(old):
            raise StorageError("changed", "the profile's key file changed since it was read; try again")
        if not box.exists():
            raise StorageError("not-encrypted")
        if _volume_in_use(box):
            raise StorageError("unlocked", "lock the profile first")
        staging = box.root / REKEY
        if not rekey_space(box)["enough"]:
            raise StorageError("no-space", "not enough free space for a second copy of the profile")
        undo = lambda: None  # noqa: E731
        fds: list[int] = []
        with _signals_as_exceptions():
            try:
                staging.mkdir(mode=0o700)
                new = Vault.create(staging / "vault.json", old.profile_id)
                for field in ("created", "policy"):
                    if field in old.meta:
                        new.meta[field] = json.loads(json.dumps(old.meta[field]))
                new.meta["generation"] = int(old.meta.get("generation", 0))  # save() makes it the next one
                undo = carry(new) or undo
                new.save()
                for name in ("cipher", "old", "new"):
                    (staging / name).mkdir(mode=0o700)
                box._gocryptfs(["-init", "-q", "-xchacha", "-scryptn", "10", str(staging / "cipher")], storage_password(new))
                # -idle: should this process die here, gocryptfs unmounts by itself a minute later.
                box._gocryptfs(
                    ["-q", "-nosyslog", "-ro", "-idle", "1m", str(box.cipher), str(staging / "old")], storage_password(old)
                )
                box._gocryptfs(
                    ["-q", "-nosyslog", "-idle", "1m", str(staging / "cipher"), str(staging / "new")], storage_password(new)
                )
                for name in ("old", "new"):
                    fds.append(os.open(staging / name, os.O_RDONLY | os.O_DIRECTORY))
                    if os.fstat(fds[-1]).st_dev == os.stat(staging).st_dev:
                        raise StorageError("storage-failed", "the volume is not mounted")
                # A rolled-back key file is refused here as it is at unlock.
                state_dir = os.open(STATE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[0])
                try:
                    Container._refuse_older(old, state_dir)
                finally:
                    os.close(state_dir)
                # Through the handles, not the mount points: what is copied and compared is the two volumes.
                _copy_checked(Path(f"/proc/self/fd/{fds[0]}"), Path(f"/proc/self/fd/{fds[1]}"))
                box._check_state(new, fds[1])  # the new key file's generation, recorded in the new volume
                for fd in fds:
                    os.close(fd)
                fds.clear()
                for name in ("old", "new"):
                    box._unmount_path(staging / name)
                    os.rmdir(staging / name)
                _mark_complete_at(staging / REKEY_COMPLETE)
            except BaseException as exc:
                for fd in fds:
                    with contextlib.suppress(OSError):
                        os.close(fd)
                if (staging / REKEY_COMPLETE).exists():
                    # The copy is whole and marked: from here it is only finished, by the next use of the
                    # profile if not by this process. The new keyring key and the new volume stay.
                    if isinstance(exc, (OSError, StorageError)):
                        raise StorageError("rekey-unfinished", type(exc).__name__) from None
                    raise
                with contextlib.suppress(Exception):
                    undo()
                with contextlib.suppress(StorageError, subprocess.SubprocessError, OSError):
                    _rekey_remove_staging(box)  # what cannot be removed now is removed the next time (recover_rekey)
                if isinstance(exc, (*RECORD_ERRORS, shutil.Error)):
                    raise StorageError("storage-failed", type(exc).__name__) from None
                raise
            try:
                _rekey_finish(box)
            except (OSError, StorageError, subprocess.SubprocessError) as exc:
                raise StorageError("rekey-unfinished", getattr(exc, "code", type(exc).__name__)) from None
        new.path = box.vault_path
        return new


def _mark_complete_at(marker: Path) -> None:
    """The copy is whole: on disk first, then the marker, durably. After this the new key is finished, never undone."""
    os.sync()
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(marker.parent)
