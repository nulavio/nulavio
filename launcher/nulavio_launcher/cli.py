"""Command-line interface of the Nulavio preview launcher (Track A)."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

from . import __version__, confine, connect, desktop, doctor, extensions, guard, log, paths, profile, temporary
from . import engine as engine_mod
from . import prefs as prefs_mod

DEFAULT_PROFILE = "default"


def _out(message: str = "") -> None:
    print(message)


def _err(message: str) -> None:
    print(f"nulavio: {message}", file=sys.stderr)


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        _err("not a terminal; re-run with --yes to accept the plan shown above")
        return False
    answer = input(f"{question} [Y/n] ").strip().lower()
    return answer in {"", "y", "yes", "s", "sim"}


def _short_hash(digest: str) -> str:
    return f"{digest[:8]}…{digest[-8:]}"


def _launcher_path() -> Path:
    return paths.repo_root() / "bin" / "nulavio"


# -- commands -------------------------------------------------------------


def cmd_setup(args: argparse.Namespace) -> int:
    eng = engine_mod.find_engine()
    engine_mod.check_supported(eng)
    prof = profile.get(args.profile)
    if prof.exists():
        _err(f"profile '{prof.name}' already exists at {prof.path}")
        return 1
    lock = extensions.load_lock()
    ublock = lock["ublock-origin"]
    providers = profile.load_providers()["providers"]
    if args.provider not in providers:
        _err(f"unknown provider '{args.provider}' (choose: {', '.join(providers)})")
        return 2
    baseline = profile.baseline_prefs()
    _out("Nulavio Preview — setup\n")
    _out(f"  Engine     {eng.label} ({eng.path})")
    _out("             unmodified upstream engine; security updates come from its package")
    _out(f"  Profile    {prof.path}")
    _out("             new directory, mode 0700, separate from any Firefox profile")
    _out(f"  Defaults   {len(baseline)} privacy/security preferences (list: `nulavio prefs explain`)")
    if args.no_ublock:
        _out("  Filter     none (--no-ublock). Engine tracking protection (Strict) still applies.")
    else:
        _out(f"  Filter     {ublock.name} {ublock.version} from addons.mozilla.org")
        _out(f"             sha256 {_short_hash(ublock.sha256)}, Mozilla signature verified by the engine")
        _out("             removable any time in Add-ons; per-site off switch in its toolbar button")
    _out(f"  Passwords  {providers[args.provider]['label']}")
    if eng.builtin_theme:
        _out("  Theme      Nulavio Horizon, built into this engine")
    else:
        _out(f"  Theme      {'Nulavio colours for the browser chrome' if not args.no_theme else 'engine default'}")
    _out("  Network    nothing is sent to Nulavio; there is no Nulavio server\n")
    if not _confirm("Create this profile?", args.yes):
        return 1
    prof = profile.create(args.profile, provider=args.provider, theme=not args.no_theme)
    if not args.no_ublock:
        extensions.install(ublock, prof.path)
        _out(f"✓ {ublock.name} {ublock.version} verified and placed in the profile")
        _out("  Some engines (Mozilla's own builds) ask before enabling newly added extensions:")
        _out("  if so, approve it from the ☰ menu on first start. Nulavio never bypasses that prompt.")
    if args.install_provider_extension:
        _install_provider_extension(prof, args.provider)
    _out(f"✓ profile '{prof.name}' ready. Start it with: {_launcher_path()} run")
    return 0


def _install_provider_extension(prof: profile.Profile, provider_key: str) -> None:
    provider = profile.load_providers()["providers"][provider_key]
    key = provider.get("extension")
    if not key:
        return
    entry = extensions.load_lock()[key]
    extensions.install(entry, prof.path)
    _out(f"✓ official {entry.name} {entry.version} verified (sha256 {_short_hash(entry.sha256)}) and placed in the profile")


def _filter_context(prof: profile.Profile) -> dict[str, str]:
    lock = extensions.load_lock()
    ublock = lock["ublock-origin"]
    for ext in extensions.installed_in_profile(prof.path):
        if ext["id"] == ublock.id:
            return {"filter": f"{ublock.name} {ext['version'] or ublock.version}", "filter_state": extensions.state_of(ext)}
    return {"filter": "", "filter_state": "absent"}


def cmd_run(args: argparse.Namespace) -> int:
    eng = engine_mod.find_engine()
    engine_mod.check_supported(eng)
    if args.temporary:
        return _run_temporary(args, eng)
    prof = profile.get(args.profile)
    from .vault import profiles as vault_profiles

    if vault_profiles.is_encrypted(prof) and not vault_profiles.container(prof).mounted():
        return _run_encrypted(args, eng, prof)
    return _run(args, eng, prof)


def _run_encrypted(args: argparse.Namespace, eng, prof) -> int:
    """Locked profile: unlock, run the engine as a child, lock again when it exits (ADR 0006: lock)."""
    from .vault import cli as vault_cli
    from .vault import profiles as vault_profiles
    from .vault.core import VaultError
    from .vault.storage import StorageError

    try:
        vault = vault_cli.unlock_for_run(prof, password_stdin=args.password_stdin)
    except (VaultError, StorageError) as exc:
        _err(vault_cli.MESSAGES.get(exc.code, str(exc)))
        return 1
    vault.lock()  # the DEK is not needed while the volume is mounted
    try:
        return _run(args, eng, prof, supervise=True)
    finally:
        try:
            vault_profiles.lock(prof, after_exit=True)
        except Exception as exc:
            _err(f"could not lock profile '{prof.name}': {exc}")


def _run_temporary(args: argparse.Namespace, eng) -> int:
    """A new temporary profile: run the engine as a child, delete the profile when it exits."""
    temp = temporary.create()
    try:
        if not eng.builtin_theme and not args.no_ublock:
            # The Nulavio build installs uBlock Origin by policy; distribution Firefox gets the pinned copy.
            extensions.install(extensions.load_lock()["ublock-origin"], temp.path)
        where = (
            "in memory"
            if temp.in_memory and not temp.swap_on_disk
            else ("in memory (may reach swap on disk)" if temp.in_memory else "in a temporary folder on disk")
        )
        _out(f"Temporary profile, kept {where}; deleted when Nulavio closes.")
        return _run(args, eng, temp.profile, supervise=True)
    finally:
        try:
            temporary.remove(temp.path)
        except (OSError, temporary.TemporaryError) as exc:
            _err(f"could not delete the temporary profile: {exc}")
        temp.release()


def _run(args: argparse.Namespace, eng, prof, supervise: bool = False) -> int:
    if not prof.exists():
        _err(f"profile '{prof.name}' does not exist yet; run `nulavio setup` first")
        return 1
    findings = guard.audit(prof.path)
    for finding in findings:
        if finding.severity != "info":
            _err(f"guard [{finding.severity}] {finding.pref}={finding.actual!r}: {finding.message}")
    critical = [f for f in findings if f.severity == "critical"]
    if critical and not args.allow_weakened:
        _err("refusing to start a profile with critical findings; fix them or pass --allow-weakened")
        log.event("launch.refused", profile=prof.name, critical=[f.pref for f in critical])
        return 3
    command = engine_mod.build_command(eng, prof.path, url=args.url, private=args.private)
    pid = prof.running_pid()
    if getattr(args, "confined", False):
        if pid is not None:
            # The engine would hand this request to the running instance, which is not confined by this command.
            _err(f"profile '{prof.name}' is already open; close it, then start it again with --confined")
            return 1
        try:
            command = confine.wrap(command, profile_dir=prof.path, engine_dir=eng.path.resolve().parent, supervised=supervise)
        except confine.ConfineError as exc:
            _err(str(exc))
            return 1
    if pid is None:
        locale = prof.load_settings().get("locale", "en")
        if locale != "en":
            profile.sync_langpack(prof, engine_mod.langpack(eng, locale))
        applied = profile.prepare_for_launch(
            prof, {"engine": eng.label, **_filter_context(prof)}, builtin_theme=eng.builtin_theme
        )
        log.event(
            "launch", profile=prof.name, engine=eng.label, private=args.private, url_given=bool(args.url), seeded=len(applied),
            confined=bool(getattr(args, "confined", False)),
        )  # fmt: skip
    else:
        # The engine forwards the request to the instance already using this profile.
        log.event("launch.forward", profile=prof.name, private=args.private, url_given=bool(args.url))
    if args.dry_run:
        _out(" ".join(command))
        return 0
    if supervise:
        # The volume must stay mounted exactly as long as the engine runs.
        output = None if args.engine_output else subprocess.DEVNULL
        child = subprocess.Popen(command, env=engine_mod.launch_env(), stdout=output, stderr=output,
                                 start_new_session=True)  # fmt: skip
        previous = {sig: signal.signal(sig, lambda *_: child.terminate()) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            child.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        log.event("engine.exit", profile=prof.name, code=child.returncode)
        return 0
    if not args.engine_output:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    os.execve(command[0], command, engine_mod.launch_env())  # noqa: S606 - argv is allow-listed by build_command()
    return 0  # pragma: no cover


def cmd_profile(args: argparse.Namespace) -> int:
    if args.profile_cmd == "list":
        for prof in profile.list_profiles():
            settings = prof.load_settings() if prof.exists() else {}
            running = prof.running_pid()
            _out(
                f"{prof.name:16} provider={settings.get('provider', '?'):12} {'running' if running else 'stopped':8} {prof.path}"
            )
        return 0
    prof = profile.get(args.name)
    if args.profile_cmd == "path":
        _out(str(prof.path))
        return 0
    if args.profile_cmd == "delete":
        if not args.yes:
            _err(f"this permanently deletes {prof.path} (history, cookies, saved logins). Re-run with --yes")
            return 1
        profile.delete(prof)
        _out(f"deleted profile '{prof.name}'")
        return 0
    return 2


def cmd_extensions(args: argparse.Namespace) -> int:
    lock = extensions.load_lock()
    if args.ext_cmd == "list":
        prof = profile.get(args.profile)
        installed = {e["id"]: e for e in extensions.installed_in_profile(prof.path)} if prof.path.exists() else {}
        for entry in lock.values():
            state = installed.get(entry.id)
            status = "-" if not state else ("active" if state["active"] else "pending" if not state["registered"] else "disabled")
            _out(f"{entry.key:18} {entry.version:12} {entry.role:20} {status:9} sha256 {_short_hash(entry.sha256)}")
        for ext_id, state in installed.items():
            if ext_id not in {e.id for e in lock.values()}:
                _out(f"{'(unpinned)':18} {state['version'] or '?':12} {state['name']}")
        return 0
    if args.ext_cmd == "fetch":
        keys = args.keys or list(lock)
        for key in keys:
            entry = lock[key]
            path = extensions.fetch(entry)
            _out(f"✓ {entry.key} {entry.version} verified → {path}")
        return 0
    if args.ext_cmd == "install":
        prof = profile.get(args.profile)
        prof.require_not_running()
        entry = lock[args.key]
        extensions.install(entry, prof.path)
        _out(
            f"✓ {entry.name} {entry.version} verified (sha256 {_short_hash(entry.sha256)}); active on next start of '{prof.name}'"
        )
        return 0
    return 2


def cmd_provider(args: argparse.Namespace) -> int:
    prof = profile.get(args.profile)
    providers = profile.load_providers()["providers"]
    if args.provider_cmd == "show":
        settings = prof.load_settings()
        current = settings.get("provider")
        for key, provider in providers.items():
            mark = "●" if key == current else "○"
            _out(f"{mark} {key:12} {provider['priority']:8} {provider['label']}")
        return 0
    if args.provider_cmd == "set":
        provider = profile.set_provider(prof, args.provider)
        if provider["extension"]:
            _out(
                textwrap.dedent(
                    f"""\
                    Credential provider for '{prof.name}': {provider["label"]}
                    • The engine's own "save password?" and autofill prompts will be OFF
                      on next start, so only one manager offers to fill.
                    • Logins already saved in the engine are NOT deleted.
                    • Undo any time: nulavio provider set builtin --profile {prof.name}"""
                )
            )
            if args.install_extension:
                _install_provider_extension(prof, args.provider)
            else:
                _out(
                    f"• Install the official extension: nulavio extensions install {provider['extension']} --profile {prof.name}"
                )
            native = provider.get("native_messaging")
            if native:
                found = [d for d in doctor.NATIVE_MANIFEST_DIRS if (d / f"{native['name']}.json").exists()]
                if found:
                    _out(f"• Native messaging host '{native['name']}' found in {found[0]}")
                elif native.get("required"):
                    _out(
                        f"• Native messaging host '{native['name']}' is not registered yet. Enable browser "
                        "integration for Firefox in the desktop app; it writes the manifest itself."
                    )
        else:
            _out(f"Credential provider for '{prof.name}': engine built-in. Save/fill prompts return on next start.")
        return 0
    return 2


def cmd_prefs(args: argparse.Namespace) -> int:
    for pref in profile.baseline_prefs() + profile.theme_prefs():
        if args.category and pref.category != args.category:
            continue
        _out(f"{pref.name} = {prefs_mod.format_value(pref.value)}   [{pref.category}, {pref.mode}]")
        _out(f"    why: {pref.why}")
        if pref.tradeoff:
            _out(f"    trade-off: {pref.tradeoff}")
    return 0


def cmd_theme(args: argparse.Namespace) -> int:
    prof = profile.get(args.profile)
    profile.set_theme(prof, args.state == "on")
    _out(f"theme {args.state} for '{prof.name}' (takes effect on next start)")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = doctor.run_all()
    if args.json:
        _out(doctor.to_json(checks))
    else:
        icons = {"ok": "✓", "warn": "!", "fail": "✗", "info": "·"}
        area = None
        for check in checks:
            if check.area != area:
                area = check.area
                _out(f"\n[{area}]")
            _out(f"  {icons[check.status]} {check.name}: {check.detail}")
    return 1 if any(c.status == "fail" for c in checks) else 0


def cmd_integrations(args: argparse.Namespace) -> int:
    if args.integrations_cmd == "krunner-serve":
        from . import krunner

        return krunner.serve()
    if args.integrations_cmd == "api":
        from . import connect_p1

        raw = sys.stdin.read(TEMPORARY_API_LIMIT * 4 + 1)
        try:
            request = json.loads(raw) if len(raw) <= TEMPORARY_API_LIMIT * 4 else None
        except ValueError:
            request = None
        try:
            if not isinstance(request, dict):
                raise connect_p1.ConnectP1Error("bad-request")
            result = connect_p1.api_request(request)
        except connect_p1.ConnectP1Error as exc:
            result = {"error": exc.code}
        except (OSError, ValueError) as exc:
            result = {"error": "failed", "detail": type(exc).__name__}
        _out(json.dumps(result))
        return 0
    statuses = connect.discover()
    if args.json:
        _out(connect.to_json(statuses))
        return 0
    marks = {"enabled": "✓", "available": "•", "unavailable": "–", "error": "!", "unknown": "?"}
    for s in statuses:
        _out(f"{marks[s.state]} {s.id} [{s.state}] {s.detail}")
        for item in s.evidence:
            _out(f"    {item}")
    return 0


TEMPORARY_API_LIMIT = 4096


def cmd_temporary(args: argparse.Namespace) -> int:
    if args.temporary_cmd == "clean":
        removed = temporary.cleanup()
        _out(f"{removed} temporary profile(s) deleted")
        return 0
    if args.temporary_cmd == "reap":
        outcome = temporary.reap(Path(args.path), args.guard_fd, grace=args.grace)
        log.event("temporary.reap", outcome=outcome)
        return 0
    raw = sys.stdin.read(TEMPORARY_API_LIMIT + 1)
    try:
        try:
            request = json.loads(raw) if len(raw) <= TEMPORARY_API_LIMIT else None
        except ValueError:
            request = None
        if not isinstance(request, dict):
            raise temporary.TemporaryError("bad-request")
        result = temporary.api_request(request)
    except temporary.TemporaryError as exc:
        result = {"error": exc.code}
    except (profile.ProfileError, paths.UnsafePathError, ValueError, OSError) as exc:
        result = {"error": "failed", "detail": type(exc).__name__}
    print(json.dumps(result))
    return 0


def cmd_desktop(args: argparse.Namespace) -> int:
    if args.desktop_cmd == "install":
        written = desktop.install(_launcher_path())
        _out(f"installed {len(written)} files under ~/.local/share (no MimeType: never becomes the default browser)")
    else:
        removed = desktop.uninstall()
        _out(f"removed {len(removed)} files")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nulavio", description="Nulavio Preview launcher (Gecko engine, Track A)")
    parser.add_argument("--version", action="version", version=f"nulavio-launcher {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="create a Nulavio profile (shows the plan first)")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--provider", default="builtin")
    p.add_argument("--install-provider-extension", action="store_true", help="also install the provider's official extension")
    p.add_argument("--no-ublock", action="store_true")
    p.add_argument("--no-theme", action="store_true")
    p.add_argument("--yes", action="store_true", help="accept the plan without prompting")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("run", help="start Nulavio with a profile")
    p.add_argument("url", nargs="?")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--private", action="store_true", help="open a private window")
    p.add_argument("--allow-weakened", action="store_true", help="start even if Guard reports critical findings")
    p.add_argument("--engine-output", action="store_true", help="keep engine stdout/stderr (may include page console noise)")
    p.add_argument("--dry-run", action="store_true", help="prepare the profile and print the engine command")
    p.add_argument("--password-stdin", action="store_true", help="encrypted profile: read its password from stdin")
    p.add_argument("--temporary", action="store_true", help="a new profile, deleted when Nulavio closes (ignores --profile)")
    p.add_argument(
        "--confined", action="store_true",
        help="run inside bubblewrap: the browser sees only this profile and Downloads in your home folder",
    )  # fmt: skip
    p.add_argument("--no-ublock", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("profile", help="manage profiles")
    psub = p.add_subparsers(dest="profile_cmd", required=True)
    psub.add_parser("list")
    q = psub.add_parser("path")
    q.add_argument("name", nargs="?", default=DEFAULT_PROFILE)
    q = psub.add_parser("delete")
    q.add_argument("name")
    q.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("extensions", help="pinned extensions")
    esub = p.add_subparsers(dest="ext_cmd", required=True)
    q = esub.add_parser("list")
    q.add_argument("--profile", default=DEFAULT_PROFILE)
    q = esub.add_parser("fetch")
    q.add_argument("keys", nargs="*")
    q = esub.add_parser("install")
    q.add_argument("key")
    q.add_argument("--profile", default=DEFAULT_PROFILE)
    p.set_defaults(func=cmd_extensions)

    p = sub.add_parser("provider", help="choose the credential provider")
    vsub = p.add_subparsers(dest="provider_cmd", required=True)
    q = vsub.add_parser("show")
    q.add_argument("--profile", default=DEFAULT_PROFILE)
    q = vsub.add_parser("set")
    q.add_argument("provider")
    q.add_argument("--profile", default=DEFAULT_PROFILE)
    q.add_argument("--install-extension", action="store_true")
    p.set_defaults(func=cmd_provider)

    p = sub.add_parser("prefs", help="explain the privacy/security defaults")
    p.add_argument("action", choices=["explain"])
    p.add_argument("--category")
    p.set_defaults(func=cmd_prefs)

    p = sub.add_parser("theme", help="toggle the preview chrome theme")
    p.add_argument("state", choices=["on", "off"])
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.set_defaults(func=cmd_theme)

    p = sub.add_parser("doctor", help="check engine, sandbox prerequisites, secrets, native messaging, profiles")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("integrations", help="what the desktop offers (KDE, portals, secret storage, default browser); read-only")
    p.add_argument("--json", action="store_true")
    p.add_argument("integrations_cmd", nargs="?", choices=["api", "krunner-serve"], help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_integrations)

    p = sub.add_parser("desktop", help="user-level desktop entry and icons")
    p.add_argument("desktop_cmd", choices=["install", "uninstall"])
    p.set_defaults(func=cmd_desktop)

    p = sub.add_parser("temporary", help="temporary profiles (deleted on close); `nulavio run --temporary` opens one")
    tsub = p.add_subparsers(dest="temporary_cmd", required=True)
    tsub.add_parser("clean", help="delete temporary profiles left behind by a crash")
    tsub.add_parser("api", help=argparse.SUPPRESS)
    q = tsub.add_parser("reap", help=argparse.SUPPRESS)
    q.add_argument("--path", required=True)
    q.add_argument("--guard-fd", type=int)
    q.add_argument("--grace", type=float, default=120.0)
    p.set_defaults(func=cmd_temporary)

    from .ai import cli as ai_cli
    from .vault import cli as vault_cli

    ai_cli.add_parser(sub)
    vault_cli.add_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (
        engine_mod.EngineError,
        profile.ProfileError,
        extensions.IntegrityError,
        paths.UnsafePathError,
        prefs_mod.PrefFileError,
    ) as exc:
        _err(str(exc))
        return 1
    except KeyError as exc:
        _err(f"unknown item: {exc}")
        return 2
    except OSError as exc:
        _err(f"{exc.__class__.__name__}: {exc}")
        return 1
