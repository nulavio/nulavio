"""Encrypted launcher profiles: a Nulavio profile whose directory is a Vault container.

Unlocking needs a method that releases the DEK (password, recovery code, OS
keyring); it mounts the volume. Locking ends the engine instance first and
unmounts. `nulavio run` on a locked profile unlocks, runs the engine, and
locks again when the engine exits.
"""

from __future__ import annotations

import ctypes
import os
import signal
import stat
import struct
import sys
import time

from .. import log, profile
from . import storage
from .core import RECOVERY_KDF, Vault, VaultError
from .providers import Keyring, add_os_keyring, unlock_os_keyring
from .storage import Container, recover_interrupted, recover_rekey


# What a person reads when protecting a profile was cut short (a kill, a power cut) and the next use
# of the profile settled it (storage.recover_interrupted).
RECOVERED = {
    "finished": (
        "protecting profile '{name}' was interrupted after its files were encrypted: "
        "it is finished now, and the profile is protected"
    ),
    "undone": (
        "protecting profile '{name}' was interrupted before its files were encrypted: "
        "it is back as it was, not protected; protect it again"
    ),
}


def container(prof: profile.Profile) -> Container:
    # Every launcher path that touches a protected profile comes here first.
    outcome = recover_interrupted(prof.path)
    if outcome:
        log.event("vault.migration-recovered", profile=prof.name, outcome=outcome)
        print("nulavio: " + RECOVERED[outcome].format(name=prof.name), file=sys.stderr)  # never stdout: a helper's protocol
    outcome = recover_rekey(prof.path)
    if outcome:
        log.event("vault.rekey-recovered", profile=prof.name, outcome=outcome)
    box = Container(prof.path)
    box.secure_if_locked()
    return box


def is_encrypted(prof: profile.Profile) -> bool:
    return container(prof).vault_path.exists()


def create(name: str, *, password: str | None, keyring: Keyring | None = None, provider: str = "builtin",
           kdf: dict | None = None, recovery_kdf: dict | None = None) -> tuple[profile.Profile, str]:  # fmt: skip
    """A new encrypted profile. Returns (profile, recovery code); the code is shown once."""
    if not password and keyring is None:
        raise VaultError("no-method", "choose a password, the OS keyring, or both")
    prof = profile.get(name)
    box = container(prof)
    if prof.path.exists() or box.root.exists():
        raise profile.ProfileError(f"profile '{name}' already exists")
    from .. import paths

    paths.ensure_private_dir(paths.profiles_root())
    box.root.mkdir(mode=0o700)
    vault = Vault.create(box.vault_path)
    try:
        if password:
            vault.add_password(password, kdf)
        if keyring is not None:
            add_os_keyring(vault, keyring, label="computer login")
        code = vault.add_recovery_code(recovery_kdf or RECOVERY_KDF)
        vault.save()
        box.init(vault)
        box.mount(vault)
        profile.create(name, provider=provider, inside_container=True)
        box.unmount()
    except BaseException:
        box.destroy()
        raise
    finally:
        vault.lock()
    log.event("vault.create", profile=name, methods=[e.method for e in vault.envelopes()])
    return prof, code


def unlock(prof: profile.Profile, *, password: str | None = None, recovery_code: str | None = None,
           keyring: Keyring | None = None, idle_minutes: int | None = None) -> Vault:  # fmt: skip
    """Release the DEK with one method and mount the profile. The caller locks the returned vault."""
    box = container(prof)
    vault = box.load_vault()
    if password is not None:
        vault.unlock_password(password)
    elif recovery_code is not None:
        vault.unlock_recovery_code(recovery_code)
    elif keyring is not None:
        unlock_os_keyring(vault, keyring)
    else:
        raise VaultError("no-method")
    if vault.tampered:
        vault.lock()
        raise VaultError("metadata-tampered", "the profile's key file was changed outside Nulavio")
    try:
        box.mount(vault, idle_minutes)
    except BaseException:  # whatever stopped it: the key does not stay in memory
        vault.lock()
        raise
    log.event("vault.unlock", profile=prof.name, method="password" if password is not None else
              "recovery-code" if recovery_code is not None else "os-keyring")  # fmt: skip
    return vault


def lock(prof: profile.Profile, *, force: bool = False, wait: float = 30.0, after_exit: bool = False) -> None:
    """End the profile's engine instance (only with force) and unmount.

    `after_exit`: the engine has just exited (supervised run); give its helper
    processes time to close files, then detach the volume regardless.
    """
    box = container(prof)
    if not box.mounted():
        return
    pid = prof.running_pid()
    if pid:
        if not force:
            raise profile.ProfileInUse(f"profile '{prof.name}' is open (pid {pid}); close it or use --force")
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + wait
        while prof.running_pid() and time.monotonic() < deadline:
            time.sleep(0.3)
        if prof.running_pid():
            raise profile.ProfileInUse(f"profile '{prof.name}' did not close in {wait:.0f} s")
    box.unmount(wait=60.0, lazy_after=True) if after_exit else box.unmount()
    log.event("vault.lock", profile=prof.name, forced=bool(pid))


def status(prof: profile.Profile) -> dict:
    box = container(prof)
    if not box.vault_path.exists():
        return {"profile": prof.name, "encrypted": False}
    vault = box.load_vault()
    mounted = box.mounted()
    running = bool(mounted and prof.running_pid())
    pending = vault.pending_recovery_code()
    unconfirmed = pending["new"] if pending else None  # a new recovery code not typed back yet (#187)
    return {
        "profile": prof.name, "encrypted": True, "locked": not mounted, "running": running,
        # Unlocked with no engine: left open by `nulavio vault unlock` or by a crash.
        "open_without_engine": mounted and not running,
        "methods": [{"id": e.id, "method": e.method, "label": e.label, "created": e.created,
                     **({"unconfirmed": True} if e.id == unconfirmed else {})} for e in vault.envelopes()],
        "protection": vault.protection_states(),
        # When the profile's key was made, and when a method was last removed or replaced since (ADR 0015).
        "key": vault.key_info(),
    }  # fmt: skip


def reauthenticate(vault: Vault, current: str) -> str:
    """Unlock `vault` with a password or a recovery code; returns which. Before any change to the methods."""
    try:
        vault.unlock_password(current)
        method = "password"
    except VaultError:
        try:
            vault.unlock_recovery_code(current)
            method = "recovery-code"
        except VaultError:
            raise VaultError("wrong-secret") from None
    if vault.tampered:
        # Before any change, and before anything outside the file (the system keyring, a phone):
        # save() refuses a tampered vault too, but a removed keyring secret cannot be put back.
        vault.lock()
        raise VaultError("metadata-tampered", "the profile's key file was changed outside Nulavio")
    return method


def _carry(old: Vault, new: Vault, method: str, current: str, keyring: Keyring | None) -> tuple[list, list, list, list]:
    """Make again, in `new`, every unlock method of `old` whose key this program has now: the secret that was
    typed, this computer's login (a new keyring key), connected phones (from their public keys). The others
    cannot be wrapped again without their secret. Returns (carried, dropped, undo, after): what each list of
    envelopes became, what to call if the new key is undone, and what to call once it is in place."""
    from . import phone as phones  # here: phone.py is not needed by profiles that have none

    carried, dropped, undo, after = [], [], [], []
    for env in old.envelopes():
        made = None
        try:
            if env.id == old.opened_with:
                # The secret that was typed must open the profile afterwards: if it cannot be wrapped again,
                # nothing is changed (never a profile left to the methods the person did not use just now).
                params = {"ops": env.data["ops"], "mem": env.data["mem"]}
                if method == "password":
                    made = new.add_password(current, params, env.label)
                else:
                    made = new.add_known_recovery_code(current, params)
            elif env.method == "os-keyring" and keyring is not None:
                made = add_os_keyring(new, keyring, label=env.label)
                was = env.data.get("attributes")
                undo.append(lambda attributes=made.data["attributes"]: keyring.clear(attributes))
                after.append(lambda attributes=was: keyring.clear(attributes) if attributes else None)
            elif env.method == "phone":
                made = phones.add_phone(new, phones.PairedPhone.from_fields(env.data), env.label)
        except (VaultError, KeyError, TypeError, ValueError) as exc:
            if env.id == old.opened_with:
                _each(undo)
                raise VaultError("failed", "the method that was typed could not be carried over") from None
            log.event("vault.rekey-not-carried", method=env.method, code=getattr(exc, "code", type(exc).__name__))
        (carried if made else dropped).append({"method": env.method, "label": env.label})
    if not any(env.id == old.opened_with for env in old.envelopes()):
        _each(undo)
        raise VaultError("failed", "the method that was typed is not one of the profile's")
    return carried, dropped, undo, after


def _each(steps: list) -> None:
    """Run every step; one that fails does not stop the others (keyring entries to take back)."""
    for step in steps:
        try:
            step()
        except (VaultError, OSError) as exc:
            log.event("vault.rekey-keyring-left", code=getattr(exc, "code", type(exc).__name__))


def rekey(prof: profile.Profile, *, current: str, keyring: Keyring | None = None) -> dict:
    """A new key for the profile's volume (ADR 0015): after it, no key file from before opens anything, with
    any secret. The profile must be closed. Returns what became of each unlock method."""
    box = container(prof)
    if not box.vault_path.exists():
        raise VaultError("not-encrypted")
    if box.mounted() or prof.running_pid():
        raise VaultError("unlocked", "lock the profile first")
    old = box.load_vault()
    method = reauthenticate(old, current)
    result: dict = {}
    new = None
    try:

        def carry(vault: Vault):
            carried, dropped, undo, after = _carry(old, vault, method, current, keyring)
            result.update(carried=carried, dropped=dropped, after=after)
            return lambda: _each(undo)

        new = storage.rekey(box, old, carry)
    finally:
        old.lock()
        if new is not None:
            new.lock()
    _each(result.pop("after"))  # the old keyring keys: they wrap nothing that exists now
    log.event("vault.rekey", profile=prof.name, carried=[m["method"] for m in result["carried"]],
              dropped=[m["method"] for m in result["dropped"]])  # fmt: skip
    return result


_IN_CREATE, _IN_MOVED_TO, _IN_NONBLOCK, _IN_CLOEXEC = 0x100, 0x80, 0o4000, 0o2000000
_EVENT = struct.Struct("iIII")  # struct inotify_event: wd, mask, cookie, len (then the name)


class _LockSeen:
    """Whether an engine took the profile's lock since this was made, even if it is gone again (#277).

    The watcher looks twice a second; an engine that takes the lock and dies, or is stopped, in between
    is never seen running. inotify (through libc, standard library only) keeps the creation of `lock`
    in the profile folder until it is read. Where inotify is not available, a lock left behind that was
    not there when this started and was made after it (a crash or a kill leaves it) says the same; a
    clean exit that fast then goes unseen, and the grace ends the wait as before.
    """

    def __init__(self, folder):
        self.folder = folder
        self.started = time.time()
        self.before = self._lock()  # a lock already there (an earlier session's) is not one that came now
        self.fd = -1
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            fd = libc.inotify_init1(_IN_NONBLOCK | _IN_CLOEXEC)
            if fd >= 0 and libc.inotify_add_watch(fd, os.fsencode(folder), _IN_CREATE | _IN_MOVED_TO) < 0:
                os.close(fd)
                fd = -1
            self.fd = fd
        except (OSError, AttributeError):
            self.fd = -1

    def __call__(self) -> bool:
        if self.fd >= 0:
            try:
                data = os.read(self.fd, 64 * 1024)
            except BlockingIOError:
                data = b""
            at = 0
            while at + _EVENT.size <= len(data):
                _wd, _mask, _cookie, size = _EVENT.unpack_from(data, at)
                name = data[at + _EVENT.size : at + _EVENT.size + size].split(b"\0", 1)[0]
                at += _EVENT.size + size
                if name == b"lock":
                    return True
        now = self._lock()
        # A second of slack: the kernel stamps files with a coarse clock that can read a little behind time.time()
        # (CI saw a lock made after the start stamped before it). A lock that was already there is ruled out by
        # `before`, not by the time.
        return now is not None and now != self.before and now[1] >= self.started - 1.0

    def _lock(self) -> tuple[int, float] | None:
        """The engine's lock symlink as (inode, mtime), or None."""
        try:
            made = os.lstat(self.folder / "lock")
        except OSError:
            return None
        return (made.st_ino, made.st_mtime) if stat.S_ISLNK(made.st_mode) else None

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def autolock(prof: profile.Profile, *, grace: float = 120.0, poll: float = 0.5) -> str:
    """Lock the profile once its engine instance has come and gone (browser-group profiles, S6).

    Waits up to `grace` seconds for an engine to take the profile, then until
    it exits, then unmounts. An engine that took the lock and was gone again
    between two looks ends the wait too (#277). Returns what happened, for the log.
    """
    box = container(prof)
    deadline = time.monotonic() + grace
    seen = _LockSeen(prof.path)
    try:
        while not prof.running_pid():
            if not box.mounted():
                return "already-locked"
            if seen():
                break  # an engine came and went between two looks: it is gone, so lock now
            if time.monotonic() > deadline:
                box.unmount(lazy_after=True)  # nobody opened it: do not leave it unlocked, even with a file open
                log.event("vault.autolock", profile=prof.name, reason="unused")
                return "unused"
            time.sleep(poll)
    finally:
        seen.close()
    while prof.running_pid():
        if not box.mounted():
            return "already-locked"
        time.sleep(poll)
    box.unmount(wait=60.0, lazy_after=True)  # the engine is gone; its helpers may still be closing files
    log.event("vault.autolock", profile=prof.name, reason="closed")
    return "closed"
