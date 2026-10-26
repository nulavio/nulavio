"""`nulavio vault …`: encrypted profiles from the command line (the Shell UI comes in S6)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys

from pathlib import Path

from .. import profile
from . import profiles, sodium
from .core import Vault, VaultError
from .providers import Keyring, add_os_keyring, remove_os_keyring
from .storage import Container, StorageError, encrypt_existing, tools_available

MESSAGES = {
    "wrong-secret": "that did not unlock the profile",
    "wrong-key": "the profile's storage did not accept the key",
    "no-such-method": "this profile has no such unlock method",
    "keyring-unavailable": "the system keyring is not available",
    "keyring-missing": "the system keyring has no key for this profile",
    "metadata-tampered": "the profile's key file was changed outside Nulavio; nothing was opened",
    "rollback": "the profile's key file is older than the profile (restored from a backup?); nothing was opened",
    "busy": "files in the profile are still in use",
    "mountpoint-not-empty": "unexpected files appeared in the locked profile directory; nothing was opened",
    "recovery-code-malformed": "a recovery code has 28 letters and digits (7 groups of 4)",
    "password-too-short": "use at least 8 characters",
    "last-method": "a profile needs at least one way to unlock it",
}


def _err(message: str) -> None:
    print(f"nulavio: {message}", file=sys.stderr)


def keyring() -> Keyring:
    # NULAVIO_SECRET_TOOL lets tests use a stand-in; it never weakens anything (same user either way).
    return Keyring(os.environ.get("NULAVIO_SECRET_TOOL") or None)


def read_secret(prompt: str, *, from_stdin: bool, confirm: bool = False) -> str | None:
    """A secret from stdin (scripts), the terminal, or a KDE dialog; None when there is no way to ask."""
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    if sys.stdin.isatty():
        first = getpass.getpass(f"{prompt}: ")
        if confirm and getpass.getpass("Again: ") != first:
            raise VaultError("mismatch", "the two entries differ")
        return first
    kdialog = shutil.which("kdialog")
    if kdialog and (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        result = subprocess.run([kdialog, "--title", "Nulavio", "--password", prompt], capture_output=True, text=True,
                                timeout=300, check=False)  # fmt: skip
        return result.stdout.rstrip("\n") if result.returncode == 0 else None
    return None


def target(args) -> profile.Profile:
    """A launcher profile by name, or any engine profile directory by --path (e.g. one the browser created)."""
    if getattr(args, "path", None):
        path = Path(args.path).expanduser().resolve()
        return profile.Profile(name=path.name, path=path)
    if not args.name:
        raise profile.ProfileError("give a profile name or --path")
    return profile.get(args.name)


def unlock_for_run(prof: profile.Profile, *, password_stdin: bool = False):
    """Unlock with the profile's own methods: the OS keyring if the user chose it, else ask for the password."""
    box = profiles.container(prof)
    methods = {e.method for e in box.load_vault().envelopes()}
    if "os-keyring" in methods and not password_stdin:
        try:
            return profiles.unlock(prof, keyring=keyring())
        except VaultError as exc:
            if "password" not in methods:
                raise
            _err(f"{MESSAGES.get(exc.code, exc.code)}; asking for the password instead")
    if "password" not in methods:
        raise VaultError("no-such-method", "unlock with `nulavio vault unlock --recovery`")
    secret = read_secret(f"Password for profile '{prof.name}'", from_stdin=password_stdin)
    if secret is None:
        raise VaultError("cannot-ask", f"profile '{prof.name}' is locked; run `nulavio vault unlock {prof.name}` in a terminal")
    return profiles.unlock(prof, password=secret)


def cmd(args: argparse.Namespace) -> int:
    if not tools_available() and args.vault_cmd not in ("status",):
        _err("encrypted profiles need gocryptfs and FUSE (Fedora: dnf install gocryptfs)")
        return 1
    if not sodium.available():
        _err("encrypted profiles need libsodium (Fedora: dnf install libsodium)")
        return 1
    try:
        return HANDLERS[args.vault_cmd](args)
    except (VaultError, StorageError) as exc:
        _err(MESSAGES.get(exc.code, f"{exc.code}: {exc}"))
        return 1
    except profile.ProfileError as exc:
        _err(str(exc))
        return 1


def _create(args) -> int:
    password = None
    if not args.no_password:
        password = read_secret("New profile password", from_stdin=args.password_stdin, confirm=True)
        if password is None:
            _err("no terminal to ask for a password; use --password-stdin")
            return 1
    prof, code = profiles.create(args.name, password=password, keyring=keyring() if args.keyring else None,
                                 provider=args.provider, theme=not args.no_theme)  # fmt: skip
    print(f"Encrypted profile '{prof.name}' created: {prof.path}")
    print("\nRecovery code (shown once; write it down and keep it away from this computer):\n")
    print(f"    {code}\n")
    print("Without your password, keyring or this code the profile cannot be opened. Nulavio has no master key.")
    return 0


def _encrypt(args) -> int:
    """Encrypt an existing profile in place (it must be closed)."""
    prof = target(args)
    if profiles.is_encrypted(prof):
        _err(f"profile '{prof.name}' is already encrypted")
        return 1
    if not prof.path.is_dir():
        _err(f"no profile directory at {prof.path}")
        return 1
    if prof.running_pid():
        raise profile.ProfileInUse(f"profile '{prof.name}' is open; close it first")
    password = None if args.no_password else read_secret("New profile password", from_stdin=args.password_stdin, confirm=True)
    if not args.no_password and password is None:
        _err("no terminal to ask for a password; use --password-stdin")
        return 1
    box = Container(prof.path)
    vault = Vault.create(box.vault_path)
    try:
        if password:
            vault.add_password(password)
        if args.keyring:
            add_os_keyring(vault, keyring(), label="computer login")
        if not vault.envelopes():
            raise VaultError("no-method", "choose a password, the OS keyring, or both")
        code = vault.add_recovery_code()
        vault.save()
        encrypt_existing(prof.path, vault)
    finally:
        vault.lock()
    print(f"Profile '{prof.name}' is now encrypted and locked.")
    print("The old unencrypted files were deleted; on SSDs and in backups, fragments may remain.")
    print(f"\nRecovery code (shown once):\n\n    {code}\n")
    return 0


def _unlock(args) -> int:
    prof = target(args)
    if not profiles.is_encrypted(prof):
        _err(f"profile '{prof.name}' is not encrypted")
        return 1
    if args.recovery:
        code = read_secret("Recovery code", from_stdin=args.password_stdin)
        vault = profiles.unlock(prof, recovery_code=code or "")
    elif args.keyring:
        vault = profiles.unlock(prof, keyring=keyring())
    else:
        password = read_secret(f"Password for profile '{prof.name}'", from_stdin=args.password_stdin)
        vault = profiles.unlock(prof, password=password or "")
    vault.lock()  # the volume stays mounted; the DEK is not kept by the CLI
    print(f"Profile '{prof.name}' is unlocked until `nulavio vault lock {prof.name}`.")
    return 0


def _lock(args) -> int:
    prof = target(args)
    profiles.lock(prof, force=args.force)
    print(f"Profile '{prof.name}' is locked.")
    return 0


def _status(args) -> int:
    targets = [target(args)] if (args.name or args.path) else profile.list_profiles()
    items = [profiles.status(t) for t in targets]
    if args.json:
        print(json.dumps(items, indent=2))
        return 0
    for item in items:
        if not item["encrypted"]:
            print(f"{item['profile']:16} not encrypted")
            continue
        state = "locked" if item["locked"] else "OPEN (no engine running)" if item["open_without_engine"] else "unlocked"
        methods = ", ".join(m["method"] for m in item["methods"])
        print(f"{item['profile']:16} {state:26} methods: {methods}   protection: {', '.join(item['protection'])}")
    return 0


def _change(args) -> int:
    """Add or remove a method: re-authenticate with an existing one first (ADR 0006)."""
    prof = target(args)
    box = profiles.container(prof)
    vault = box.load_vault()
    current = read_secret(f"Current password or recovery code for '{prof.name}'", from_stdin=args.password_stdin)
    if current is None:
        _err("no way to ask for the current password; use --password-stdin")
        return 1
    try:
        vault.unlock_password(current)
    except VaultError:
        try:
            vault.unlock_recovery_code(current)
        except VaultError:
            raise VaultError("wrong-secret") from None
    try:
        if args.vault_cmd == "add-password":
            new = read_secret("New password", from_stdin=args.password_stdin, confirm=True)
            vault.add_password(new or "")
        elif args.vault_cmd == "new-recovery-code":
            code = vault.replace_recovery_code()
            print(f"New recovery code (the old one no longer works):\n\n    {code}\n")
        elif args.vault_cmd == "add-keyring":
            add_os_keyring(vault, keyring(), label="computer login")
        elif args.vault_cmd == "remove-method":
            env = next((e for e in vault.envelopes() if e.id == args.envelope), None)
            if env is None:
                _err("no such method; see `nulavio vault status`")
                return 1
            if env.method == "os-keyring":
                remove_os_keyring(vault, keyring(), env.id)
            else:
                vault.remove(env.id)
        vault.save()
        box.record_generation(vault)
    finally:
        vault.lock()
    print(f"Profile '{prof.name}': {args.vault_cmd.replace('-', ' ')} done.")
    return 0


HANDLERS = {"create": _create, "encrypt": _encrypt, "unlock": _unlock, "lock": _lock, "status": _status, "add-password": _change,
            "new-recovery-code": _change, "add-keyring": _change, "remove-method": _change}  # fmt: skip


def add_parser(sub) -> None:
    p = sub.add_parser("vault", help="encrypted profiles: create, unlock, lock, recovery")
    vsub = p.add_subparsers(dest="vault_cmd", required=True)
    q = vsub.add_parser("create", help="create a new encrypted profile")
    q.add_argument("name")
    q.add_argument("--keyring", action="store_true", help="also unlock with your computer login (system keyring)")
    q.add_argument("--no-password", action="store_true", help="no profile password (needs --keyring)")
    q.add_argument("--provider", default="builtin")
    q.add_argument("--no-theme", action="store_true")
    q.add_argument("--password-stdin", action="store_true", help="read secrets from stdin, one per line")
    q = vsub.add_parser("encrypt", help="encrypt an existing, closed profile in place")
    q.add_argument("name", nargs="?")
    q.add_argument("--path", help="an engine profile directory instead of a launcher profile name")
    q.add_argument("--keyring", action="store_true")
    q.add_argument("--no-password", action="store_true")
    q.add_argument("--password-stdin", action="store_true")
    q = vsub.add_parser("unlock", help="unlock an encrypted profile until you lock it")
    q.add_argument("name", nargs="?")
    q.add_argument("--path")
    q.add_argument("--recovery", action="store_true")
    q.add_argument("--keyring", action="store_true")
    q.add_argument("--password-stdin", action="store_true")
    q = vsub.add_parser("lock", help="lock an encrypted profile")
    q.add_argument("name", nargs="?")
    q.add_argument("--path")
    q.add_argument("--force", action="store_true", help="close the profile's browser window first")
    q = vsub.add_parser("status", help="which profiles are encrypted, locked, and how they unlock")
    q.add_argument("name", nargs="?")
    q.add_argument("--path")
    q.add_argument("--json", action="store_true")
    for name, text in (("add-password", "add a password"), ("new-recovery-code", "replace the recovery code"),
                       ("add-keyring", "also unlock with your computer login")):  # fmt: skip
        q = vsub.add_parser(name, help=text)
        q.add_argument("name", nargs="?")
        q.add_argument("--path")
        q.add_argument("--password-stdin", action="store_true")
    q = vsub.add_parser("remove-method", help="remove one unlock method (see status for ids)")
    q.add_argument("name", nargs="?")
    q.add_argument("--path")
    q.add_argument("envelope")
    q.add_argument("--password-stdin", action="store_true")
    p.set_defaults(func=cmd)
