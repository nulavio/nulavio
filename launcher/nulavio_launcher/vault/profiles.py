"""Encrypted launcher profiles: a Nulavio profile whose directory is a Vault container.

Unlocking needs a method that releases the DEK (password, recovery code, OS
keyring); it mounts the volume. Locking ends the engine instance first and
unmounts. `nulavio run` on a locked profile unlocks, runs the engine, and
locks again when the engine exits.
"""

from __future__ import annotations

import os
import signal
import time

from .. import log, profile
from .core import RECOVERY_KDF, Vault, VaultError
from .providers import Keyring, add_os_keyring, unlock_os_keyring
from .storage import Container, StorageError


def container(prof: profile.Profile) -> Container:
    return Container(prof.path)


def is_encrypted(prof: profile.Profile) -> bool:
    return container(prof).vault_path.exists()


def create(name: str, *, password: str | None, keyring: Keyring | None = None, provider: str = "builtin",
           theme: bool = True, kdf: dict | None = None,
           recovery_kdf: dict | None = None) -> tuple[profile.Profile, str]:  # fmt: skip
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
        profile.create(name, provider=provider, theme=theme, inside_container=True)
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
    except StorageError:
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
    return {
        "profile": prof.name, "encrypted": True, "locked": not mounted, "running": running,
        # Unlocked with no engine: left open by `nulavio vault unlock` or by a crash.
        "open_without_engine": mounted and not running,
        "methods": [{"id": e.id, "method": e.method, "label": e.label, "created": e.created} for e in vault.envelopes()],
        "protection": vault.protection_states(),
    }  # fmt: skip


def autolock(prof: profile.Profile, *, grace: float = 120.0, poll: float = 0.5) -> str:
    """Lock the profile once its engine instance has come and gone (browser-group profiles, S6).

    Waits up to `grace` seconds for an engine to take the profile, then until
    it exits, then unmounts. Returns what happened, for the log.
    """
    box = container(prof)
    deadline = time.monotonic() + grace
    while not prof.running_pid():
        if not box.mounted():
            return "already-locked"
        if time.monotonic() > deadline:
            box.unmount()  # nobody opened it: do not leave it unlocked
            log.event("vault.autolock", profile=prof.name, reason="unused")
            return "unused"
        time.sleep(poll)
    while prof.running_pid():
        if not box.mounted():
            return "already-locked"
        time.sleep(poll)
    box.unmount(wait=60.0, lazy_after=True)  # the engine is gone; its helpers may still be closing files
    log.event("vault.autolock", profile=prof.name, reason="closed")
    return "closed"
