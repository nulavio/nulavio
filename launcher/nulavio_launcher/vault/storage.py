"""Encrypted profile storage (ADR 0006, decision D2): one gocryptfs container per profile.

Layout, for a profile directory P (what the engine opens with --profile):

    P            mount point: empty and read-only (0500) while locked
    P.vault/     vault.json (envelopes) and cipher/ (gocryptfs, XChaCha20-Poly1305)

The volume password is derived from the profile DEK (`storage/gocryptfs`), so
only an unlock method that releases the DEK can open it. It goes to gocryptfs
on stdin, never on the command line or disk. A locked mount point is
read-only, so an engine started on it directly cannot write plaintext there.
Inside the volume, `.nulavio-vault/state.json` mirrors the vault's generation
to detect a rolled-back vault.json (threat model U-T21).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import sodium
from .core import Vault, VaultError, kdf

LOCKED_MODE = 0o500
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
        except StorageError:
            self.unmount()
            raise

    def _check_state(self, vault: Vault) -> None:
        state_dir = self.state_path.parent
        generation = int(vault.meta.get("generation", 0))
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text())
            if state.get("profile_id") != vault.profile_id:
                raise StorageError("wrong-container")
            if int(state.get("generation", 0)) > generation:
                raise StorageError("rollback", "vault.json is older than the profile it protects")
        state_dir.mkdir(mode=0o700, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"profile_id": vault.profile_id, "generation": generation}))
        os.replace(tmp, self.state_path)

    def record_generation(self, vault: Vault) -> None:
        """After saving the vault while mounted: keep the mirror in step."""
        if self.mounted():
            self._check_state(vault)

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


def encrypt_existing(path: Path, vault: Vault) -> Container:
    """Move an existing profile directory into a new container (engine must not be using it).

    The plaintext originals are deleted afterwards; on SSDs and in backups, fragments may remain.
    """
    path = Path(path)
    if not path.is_dir():
        raise StorageError("missing", str(path))  # the caller checks that no engine is using it
    staging = path.with_name(path.name + ".plaintext-migrating")
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
    except BaseException:
        if container.mounted():
            container.unmount()
        shutil.rmtree(container.root, ignore_errors=True)
        if path.exists():
            os.chmod(path, 0o700)
            shutil.rmtree(path, ignore_errors=True)
        os.rename(staging, path)
        raise
    shutil.rmtree(staging)
    return container
