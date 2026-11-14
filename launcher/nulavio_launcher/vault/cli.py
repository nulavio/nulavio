"""`nulavio vault …`: encrypted profiles from the command line (the Shell UI comes in S6)."""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import resource
import shutil
import subprocess
import sys

from pathlib import Path

from .. import profile
from ..log import event as log_event
from . import profiles, sodium
from .core import Vault, VaultError, normalize_recovery_code
from .providers import Keyring, add_os_keyring, remove_os_keyring
from .storage import Container, StorageError, encrypt_existing, tools_available

PR_SET_DUMPABLE = 4

MESSAGES = {
    "wrong-secret": "that did not unlock the profile",
    "wrong-key": "the profile's storage did not accept the key",
    "no-such-method": "this profile has no such unlock method",
    "keyring-unavailable": "the system keyring is not available",
    "keyring-missing": "the system keyring has no key for this profile",
    "metadata-tampered": "the profile's key file was changed outside Nulavio; nothing was opened",
    "rollback": "the profile's key file is older than the profile (restored from a backup?); nothing was opened",
    "busy": "files in the profile are still in use",
    "changed": "the profile's key file changed while this was being done (another change?); nothing was done, try again",
    "storage-failed": "the profile's encrypted storage could not be opened or checked; nothing was changed",
    "not-recorded": "the change was saved, but could not be recorded inside the profile; "
    "lock the profile if it is open, then unlock it once to record it",
    "mountpoint-not-empty": "unexpected files appeared in the locked profile directory; nothing was opened",
    "recovery-code-malformed": "a recovery code has 28 letters and digits (7 groups of 4)",
    "password-too-short": "use at least 8 characters",
    "last-method": "a profile needs at least one way to unlock it",
    "replacement-pending": "a new recovery code is waiting to be typed back; replace the recovery code again "
    "(and type the new one back) before removing this one",
    "not-confirmed": "the new recovery code was not confirmed by this command. A replacement that is still waiting is "
    "finished by unlocking the profile with the new code, and undone by unlocking it any other way; "
    "`nulavio vault status` shows whether one is waiting",
    "first-not-confirmed": "that is not the recovery code shown above; it was not confirmed",
}

# What an unlock did with a recovery code replacement that was never confirmed (#187).
SETTLED = {
    "finished": "the recovery code replacement left unfinished earlier is now finished: the new code opens "
    "this profile, the previous one no longer does",
    "undone": "the recovery code replacement left unfinished earlier was undone: the previous code still opens "
    "this profile, the new one does not",
    "unsettled": "a recovery code replacement left unfinished earlier could not be settled now: both codes still "
    "open this profile; it is tried again the next time the profile is unlocked from locked",
    "unknown": "a recovery code replacement left unfinished earlier may or may not have been settled (the key file "
    "could not be written or read back); `nulavio vault status` shows which recovery codes the profile has",
}


def no_core_dumps() -> tuple[int, int] | None:
    """Keep key material out of core dumps (threat model U-T13, audit V8).

    A crash would otherwise write the password, the DEK or gocryptfs's key (gocryptfs
    inherits the limit) to systemd-coredump. Not dumpable also stops other processes
    of the same user from attaching a debugger. Returns the previous core limit.
    """
    previous = None
    try:
        previous = resource.getrlimit(resource.RLIMIT_CORE)
        resource.setrlimit(resource.RLIMIT_CORE, (0, previous[1]))
    except (OSError, ValueError):
        pass
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
    except (OSError, AttributeError):
        pass
    return previous


def restore_core_limit(previous: tuple[int, int] | None) -> None:
    if previous is not None:
        try:
            resource.setrlimit(resource.RLIMIT_CORE, previous)
        except (OSError, ValueError):
            pass


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
        result = subprocess.run(
            [kdialog, "--title", "Nulavio", "--password", prompt], capture_output=True, text=True, timeout=300, check=False
        )
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
    if args.vault_cmd == "api" and not (tools_available() and sodium.available()):
        try:
            request = json.loads(sys.stdin.read(API_LIMIT) or "{}")
        except ValueError:
            request = {}
        if request.get("op") == "capabilities":
            print(json.dumps({"storage": tools_available(), "sodium": sodium.available(), "keyring": keyring().available()}))
        else:
            print(json.dumps({"error": "storage-unavailable"}))
        return 0
    if not tools_available() and args.vault_cmd not in ("status",):
        _err("encrypted profiles need gocryptfs and FUSE (Fedora: dnf install gocryptfs)")
        return 1
    if not sodium.available():
        _err("encrypted profiles need libsodium (Fedora: dnf install libsodium)")
        return 1
    no_core_dumps()
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
    prof, code = profiles.create(
        args.name, password=password, keyring=keyring() if args.keyring else None, provider=args.provider, theme=not args.no_theme
    )
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
    if vault.settled:
        print(f"Note: {SETTLED[vault.settled]}.")
    if vault.settle_warning:
        _err(MESSAGES["not-recorded"])
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
        methods = ", ".join(m["method"] + (" (new, not confirmed)" if m.get("unconfirmed") else "") for m in item["methods"])
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
    _reauth(vault, current)
    code = None
    try:
        # Every question first: nothing waits for an answer while the volume is mounted.
        new = (
            read_secret("New password", from_stdin=args.password_stdin, confirm=True)
            if args.vault_cmd == "add-password"
            else None
        )
        # Before anything changes: the volume must be there to record the change in (a locked
        # profile is mounted for that alone), or the old key file would open it again.
        with box.recording(vault) as record:
            if args.vault_cmd == "add-password":
                vault.add_password(new or "")
            elif args.vault_cmd == "new-recovery-code":
                code = vault.replace_recovery_code()
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
            unrecorded = _record(record)
    finally:
        vault.lock()
    replaced = bool(code and vault.pending_recovery_code())
    if code:  # shown once the change is saved (it is the only copy), whether or not it was recorded
        print("New recovery code (shown once; write it down and keep it away from this computer):")
        print(f"\n    {code}\n")
        if replaced:
            print("Until you type it back, the previous code still opens this profile.")
    if unrecorded:
        _err(MESSAGES["not-recorded"])
    if code:
        sys.stdout.flush()  # the code reaches the person before anything waits for an answer
        typed = read_secret("Type the new recovery code to confirm it", from_stdin=args.password_stdin)
        recorded = _confirm_recovery_code(box, typed, code) if typed else None
        if recorded is None:
            _err(MESSAGES["not-confirmed"] if replaced else MESSAGES["first-not-confirmed"])
            return 1
        if not recorded:
            _err(MESSAGES["not-recorded"])
        if replaced:
            print("The previous recovery code no longer opens this profile through Nulavio; a copy of the")
            print("profile's files made before now can still be opened with it.")
    print(f"Profile '{prof.name}': {args.vault_cmd.replace('-', ' ')} done.")
    return 0


def _confirm_recovery_code(box, typed: str, shown: str) -> bool | None:
    """The second phase of a replacement: the new code typed back opens it, and the old code goes.
    Returns whether that was recorded, or None when what was typed is not the code this command showed
    (another code that opens the profile is not a confirmation of this one), or that code no longer opens it
    (its replacement was withdrawn meanwhile)."""
    try:
        if normalize_recovery_code(typed) != normalize_recovery_code(shown):
            raise VaultError("wrong-secret", "not the code that was shown")
    except VaultError as exc:
        log_event("vault.recovery-code-not-confirmed", code=exc.code)
        return None
    vault = box.load_vault()
    try:
        vault.unlock_recovery_code(typed)
        if vault.tampered:
            raise VaultError("metadata-tampered")
        with box.recording(vault) as record:
            vault.confirm_recovery_code()
            vault.save()
            return not _record(record)
    except VaultError as exc:
        log_event("vault.recovery-code-not-confirmed", code=exc.code)
        return None
    finally:
        vault.lock()


def _record(record) -> bool:
    """Record a saved change inside the volume. The change is already made: a failure here is
    reported next to its result (a new recovery code must still reach the person), not instead."""
    try:
        record()
    except VaultError as exc:
        log_event("vault.change-not-recorded", code=exc.code)
        return True
    return False


# -- helper API for the browser (Shell) ------------------------------------------------------

API_LIMIT = 64 * 1024


def spawn_autolock(prof: profile.Profile) -> None:
    """A detached watcher that locks the profile when its browser instance closes."""
    launcher_dir = Path(__file__).resolve().parents[2]
    bootstrap = "import sys; sys.path.insert(0, sys.argv[1]); from nulavio_launcher.cli import main; sys.exit(main(sys.argv[2:]))"
    subprocess.Popen(
        [sys.executable, "-I", "-c", bootstrap, str(launcher_dir), "vault", "autolock", "--path", str(prof.path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def spawn_phone_session(request: dict, timeout: float = 20.0) -> dict:
    """Start a pairing or phone-unlock helper; return its first answer (the QR payload, or an error)."""
    launcher_dir = Path(__file__).resolve().parents[2]
    bootstrap = "import sys; sys.path.insert(0, sys.argv[1]); from nulavio_launcher.cli import main; sys.exit(main(sys.argv[2:]))"
    helper = subprocess.Popen(
        [sys.executable, "-I", "-c", bootstrap, str(launcher_dir), "vault", "phone-session"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # it outlives this API call; it ends by itself
        close_fds=True,
    )
    helper.stdin.write(json.dumps(request).encode())  # secrets travel on a pipe, never in argv
    helper.stdin.close()
    import selectors

    with selectors.DefaultSelector() as selector:
        selector.register(helper.stdout, selectors.EVENT_READ)
        ready = selector.select(timeout)
    line = helper.stdout.readline() if ready else b""
    helper.stdout.close()
    try:
        answer = json.loads(line)
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        helper.kill()
        raise VaultError("failed", "the phone session did not start")
    return answer


def _reauth(vault, current: str) -> None:
    try:
        vault.unlock_password(current)
    except VaultError:
        try:
            vault.unlock_recovery_code(current)
        except VaultError:
            raise VaultError("wrong-secret") from None
    if vault.tampered:
        # Before any change, and before anything outside the file (the system keyring, a phone):
        # save() refuses a tampered vault too, but a removed keyring secret cannot be put back.
        vault.lock()
        raise VaultError("metadata-tampered", "the profile's key file was changed outside Nulavio")


def api_request(request: dict) -> dict:
    """One operation for the Shell. Secrets arrive in the request body (stdin), never in argv."""
    op = request.get("op")
    if op == "capabilities":
        from . import link

        return {"storage": tools_available(), "sodium": sodium.available(), "keyring": keyring().available(),
                "phone": link.avahi_available()}  # fmt: skip
    if op == "phone-session":
        from . import phone_session

        action = request.get("action")
        if action not in ("status", "confirm", "cancel"):
            raise VaultError("bad-request", "action")
        return phone_session.control(str(request.get("session") or ""),
                                     {"action": action, "match": bool(request.get("match"))})  # fmt: skip
    path = request.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise VaultError("bad-request", "path")
    prof = profile.Profile(name=Path(path).name, path=Path(path))
    if op == "status":
        return profiles.status(prof)
    if op == "unlock":
        method = request.get("method")
        secret = request.get("secret")
        if method == "password":
            vault = profiles.unlock(prof, password=str(secret or ""))
        elif method == "recovery-code":
            vault = profiles.unlock(prof, recovery_code=str(secret or ""))
        elif method == "os-keyring":
            vault = profiles.unlock(prof, keyring=keyring())
        else:
            raise VaultError("no-such-method")
        vault.lock()
        if request.get("autolock", True):
            try:
                spawn_autolock(prof)
            except OSError:
                profiles.lock(prof)  # no watcher would lock it again: fail closed (audit V7)
                raise
        return {"unlocked": True, **({"recovery_code": vault.settled} if vault.settled else {}),
                **({"warning": vault.settle_warning} if vault.settle_warning else {})}  # fmt: skip
    if op == "lock":
        profiles.lock(prof)
        return {"locked": True}
    if op == "lock-on-exit":
        # "Bloquear agora" for the profile that is open in this browser (UX4): the Shell quits the
        # browser next; this watcher locks the volume once the engine is gone, even if none was
        # started at unlock. A second watcher finds it already locked and stops.
        if not profiles.is_encrypted(prof):
            raise VaultError("not-encrypted")
        spawn_autolock(prof)
        return {"watching": True}
    if op == "phone-pair-start":
        return spawn_phone_session({"kind": "pair", "path": str(prof.path), "current": str(request.get("current") or "")})
    if op == "phone-unlock-start":
        if not profiles.is_encrypted(prof):
            raise VaultError("not-encrypted")
        return spawn_phone_session({
            "kind": "unlock", "path": str(prof.path), "envelope": request.get("envelope"),
            "password": request.get("password"), "autolock": request.get("autolock", True),
        })  # fmt: skip
    if op == "forget":
        # Before the browser deletes a protected profile: drop its keys, so what is left is unreadable.
        box = profiles.container(prof)
        if box.mounted() or prof.running_pid():
            raise VaultError("unlocked", "lock the profile first")
        if any(prof.path.iterdir()):
            raise VaultError("mountpoint-not-empty")
        for dirpath, _dirs, _files in os.walk(box.root):
            os.chmod(dirpath, 0o700)
        shutil.rmtree(box.root)
        os.chmod(prof.path, 0o700)
        log_event("vault.forget", profile=prof.name)
        return {"forgotten": True}
    if op == "encrypt":
        if profiles.is_encrypted(prof):
            raise VaultError("exists")
        if prof.running_pid():
            raise profile.ProfileInUse("in-use")
        box = Container(prof.path)
        vault = Vault.create(box.vault_path)
        try:
            if request.get("password"):
                vault.add_password(str(request["password"]))
            if request.get("keyring"):
                add_os_keyring(vault, keyring(), label="computer login")
            if not vault.envelopes():
                raise VaultError("no-method")
            code = vault.add_recovery_code()
            vault.save()
            encrypt_existing(prof.path, vault)
        finally:
            vault.lock()
        return {"recovery_code": code}
    if op in ("new-recovery-code", "confirm-recovery-code", "add-password", "add-keyring", "remove-method"):
        box = profiles.container(prof)
        vault = box.load_vault()
        _reauth(vault, str(request.get("current") or ""))
        try:
            result: dict = {"done": True}
            with box.recording(vault) as record:  # as in _change: the volume first, locked or not
                if op == "new-recovery-code":
                    result["recovery_code"] = vault.replace_recovery_code()
                elif op == "confirm-recovery-code":
                    vault.confirm_recovery_code()  # `current` was the new code: the old one goes
                elif op == "add-password":
                    vault.add_password(str(request.get("password") or ""))
                elif op == "add-keyring":
                    add_os_keyring(vault, keyring(), label="computer login")
                else:
                    env = next((e for e in vault.envelopes() if e.id == request.get("envelope")), None)
                    if env is None:
                        raise VaultError("not-found")
                    if env.method == "os-keyring":
                        remove_os_keyring(vault, keyring(), env.id)
                    else:
                        vault.remove(env.id)
                vault.save()
                if _record(record):
                    result["warning"] = "not-recorded"
        finally:
            vault.lock()
        return result
    raise VaultError("bad-request", "op")


def _api(args) -> int:
    raw = sys.stdin.read(API_LIMIT + 1)
    try:
        if len(raw) > API_LIMIT:
            raise VaultError("bad-request", "too large")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise VaultError("bad-request")
        result = api_request(request)
    except (VaultError, StorageError) as exc:
        result = {"error": exc.code}
    except profile.ProfileInUse:
        result = {"error": "in-use"}
    except (profile.ProfileError, ValueError, OSError) as exc:
        result = {"error": "failed", "detail": type(exc).__name__}
    print(json.dumps(result))
    return 0


def _phone_session(args) -> int:
    from . import phone_session

    return phone_session.main()


def _autolock(args) -> int:
    prof = target(args)
    profiles.autolock(prof, grace=args.grace)
    return 0


HANDLERS = {
    "api": _api,
    "autolock": _autolock,
    "phone-session": _phone_session,
    "create": _create,
    "encrypt": _encrypt,
    "unlock": _unlock,
    "lock": _lock,
    "status": _status,
    "add-password": _change,
    "new-recovery-code": _change,
    "add-keyring": _change,
    "remove-method": _change,
}


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
    for name, text in (
        ("add-password", "add a password"),
        ("new-recovery-code", "replace the recovery code"),
        ("add-keyring", "also unlock with your computer login"),
    ):
        q = vsub.add_parser(name, help=text)
        q.add_argument("name", nargs="?")
        q.add_argument("--path")
        q.add_argument("--password-stdin", action="store_true")
    q = vsub.add_parser("remove-method", help="remove one unlock method (see status for ids)")
    q.add_argument("name", nargs="?")
    q.add_argument("--path")
    q.add_argument("envelope")
    q.add_argument("--password-stdin", action="store_true")
    vsub.add_parser("api", help=argparse.SUPPRESS)  # JSON on stdin/stdout, used by the browser
    vsub.add_parser("phone-session", help=argparse.SUPPRESS)  # one pairing or phone unlock; started by `api`
    q = vsub.add_parser("autolock", help=argparse.SUPPRESS)
    q.add_argument("name", nargs="?")
    q.add_argument("--path")
    q.add_argument("--grace", type=float, default=120.0)
    p.set_defaults(func=cmd)
