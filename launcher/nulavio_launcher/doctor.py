"""`nulavio doctor` (`nulavio-doctor` from a package, #470): local environment and profile health checks.

Read-only. Reports facts the user can act on; never phones home.
"""

from __future__ import annotations

import ctypes.util
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from . import engine as engine_mod
from . import extensions, guard, paths, prefs, profile

NATIVE_MANIFEST_DIRS = [
    Path.home() / ".mozilla" / "native-messaging-hosts",
    Path("/usr/lib64/mozilla/native-messaging-hosts"),
    Path("/usr/lib/mozilla/native-messaging-hosts"),
]


@dataclass
class Check:
    area: str
    name: str
    status: str  # ok | warn | fail | info
    detail: str


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def _dbus_has_owner(name: str) -> bool:
    """Whether a name is owned right now. NameHasOwner never starts an activatable service."""
    out = _run(
        [
            "busctl",
            "--user",
            "--no-pager",
            "call",
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            "s",
            name,
        ]
    )
    return out.strip() == "b true"


def _dbus_name_owner(name: str) -> str | None:
    """Executable name owning a well-known name on the session bus, if any (never activates it)."""
    if not shutil.which("busctl") or not _dbus_has_owner(name):
        return None
    out = _run(["busctl", "--user", "--no-pager", "status", name])
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if not fields:
        return None
    return fields.get("Comm") or fields.get("Exe") or "unknown process"


def _answer(cmd: list[str]) -> str:
    """stdout of a package query that succeeded, or "": by its exit status, in the C locale, never by its wording
    (rpm says "not owned" in the person's language, on stdout, review of #507)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0, check=False,
                                env={**os.environ, "LC_ALL": "C", "LANGUAGE": "C"})  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


_DPKG_OWNER = re.compile(r"^([a-z0-9][a-z0-9+.-]*)(?::[a-z0-9-]+)?: (/.*)$")


def package_of(path: Path) -> str:
    """The package that owns `path`, from rpm or dpkg (#470: the .deb's engine has no rpm to ask), or ""."""
    if shutil.which("rpm"):
        owner = _answer(["rpm", "-qf", "--queryformat", "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\\n", str(path)])
        if owner:
            return owner.splitlines()[0]
    if shutil.which("dpkg-query"):
        for line in _answer(["dpkg-query", "-S", str(path)]).splitlines():
            # "nulavio: /usr/lib/nulavio/nulavio" (or "pkg:arch: …"); a diversion's lines ("diversion by …") are not owners.
            match = _DPKG_OWNER.match(line)
            if match and match.group(2) == str(path):
                name = match.group(1)
                version = _answer(["dpkg-query", "-W", "-f=${Version}", name])
                return f"{name} {version}".strip()
    return ""


def check_engine() -> list[Check]:
    try:
        eng = engine_mod.find_engine()
    except engine_mod.EngineError as exc:
        return [Check("engine", "binary", "fail", str(exc))]
    checks = [Check("engine", "binary", "ok", f"{eng.label} at {eng.path}")]
    try:
        engine_mod.check_supported(eng)
        checks.append(Check("engine", "version floor", "ok", f">= {engine_mod.MIN_ENGINE_MAJOR}"))
    except engine_mod.EngineError as exc:
        checks.append(Check("engine", "version floor", "fail", str(exc)))
    try:
        engine_mod.require_nulavio(eng, refusal=engine_mod.BRIDGE_NEEDS_NULAVIO)
        checks.append(Check("engine", "Nulavio build", "ok", f"{eng.vendor}: the AI Bridge can drive it"))
    except engine_mod.EngineError:
        checks.append(
            Check(
                "engine",
                "Nulavio build",
                "warn",
                f"{eng.path} is {eng.label}, not the Nulavio build: the AI Bridge will refuse it and an agent's "
                "tools will return an error. Install the Nulavio package (https://nulavio.net/en/download/), "
                "or set NULAVIO_ENGINE to a Nulavio build",
            )
        )
    owner = package_of(eng.path)
    if owner:
        checks.append(
            Check("engine", "updates", "ok", f"package {owner}: updates through the package manager, from its repository")
        )
    else:
        checks.append(Check("engine", "updates", "warn", "engine not owned by a package; make sure it auto-updates"))
    st = os.stat(eng.path)
    if st.st_uid == os.getuid() or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        checks.append(Check("engine", "binary integrity", "warn", "engine binary is writable by this user or others"))
    else:
        checks.append(
            Check(
                "engine",
                "binary integrity",
                "ok",
                "engine binary owned by another account (e.g. root) and not group/world-writable",
            )
        )
    return checks


def check_platform() -> list[Check]:
    checks = []
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
    checks.append(Check("platform", "session", "ok" if session == "wayland" else "info", f"{session} / {desktop}"))
    if shutil.which("getenforce"):
        mode = _run(["getenforce"])
        checks.append(Check("platform", "SELinux", "ok" if mode == "Enforcing" else "info", mode or "unknown"))
    try:
        userns = int(Path("/proc/sys/user/max_user_namespaces").read_text().strip())
    except (OSError, ValueError):
        userns = -1
    checks.append(
        Check(
            "sandbox",
            "user namespaces",
            "ok" if userns > 0 else "warn",
            f"max_user_namespaces={userns} (engine sandbox uses them for content isolation)",
        )
    )
    seccomp = Path("/proc/sys/kernel/seccomp/actions_avail")
    checks.append(
        Check("sandbox", "seccomp-bpf", "ok" if seccomp.exists() else "warn", "available" if seccomp.exists() else "not detected")
    )
    overrides = engine_mod.sandbox_overrides()
    detail = (
        f"set here: {', '.join(overrides)}; Nulavio removes them before it starts the engine, "
        "other programs started from this environment keep them"
        if overrides
        else "none of the variables known to switch off or weaken the engine sandbox is set here"
    )
    checks.append(Check("sandbox", "environment", "warn" if overrides else "ok", detail))
    return checks


CODEC_PACKAGES = {  # distribution (ID or ID_LIKE in /etc/os-release) -> how to install the codec library
    "fedora": "sudo dnf install libavcodec-free",
    "debian": "sudo apt install libavcodec-extra",
    "ubuntu": "sudo apt install libavcodec-extra",
}
CODEC_DIRS = ("/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/lib", "/lib64", "/usr/local/lib64", "/usr/local/lib")


def codec_library() -> str | None:
    """The system's codec library (libavcodec), which the engine loads at run time: its file name, or None."""
    name = ctypes.util.find_library("avcodec")
    if name:
        return name
    for directory in CODEC_DIRS:
        found = sorted(Path(directory).glob("libavcodec.so.*"))
        if found:
            return found[-1].name
    return None


OS_RELEASE = Path("/etc/os-release")


def _distribution() -> set[str]:
    try:
        lines = OS_RELEASE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    names: set[str] = set()
    for line in lines:
        key, _, value = line.partition("=")
        if key in ("ID", "ID_LIKE"):
            names.update(value.strip().strip('"').split())
    return names


def check_media() -> list[Check]:
    """Without the system's codec library the engine says it cannot play AAC, nor Opus and FLAC in MP4 (#377)."""
    name = codec_library()
    if name:
        return [Check("media", "codec library", "ok", f"{name} (the engine uses it for AAC and for audio in MP4)")]
    install = next((how for distro, how in CODEC_PACKAGES.items() if distro in _distribution()), None)
    how = f"Install it: {install}" if install else "Install your distribution's FFmpeg libraries (libavcodec)"
    detail = f"not found: sound in MP4 (AAC, as most video sites send it) does not play. {how}, then start Nulavio again"
    return [Check("media", "codec library", "warn", detail)]


def check_secrets() -> list[Check]:
    checks = []
    owner = _dbus_name_owner("org.freedesktop.secrets")
    if owner:
        checks.append(
            Check(
                "secrets",
                "Secret Service",
                "info",
                f"org.freedesktop.secrets provided by {owner}. Note: the engine does not store web logins there; "
                "any same-user process can usually query an unlocked collection.",
            )
        )
    else:
        checks.append(Check("secrets", "Secret Service", "info", "org.freedesktop.secrets not on the session bus"))
    kwallet = _dbus_name_owner("org.kde.kwalletd6") or _dbus_name_owner("org.kde.kwalletd5")
    checks.append(Check("secrets", "KWallet", "info", f"running ({kwallet})" if kwallet else "not running"))
    return checks


def _check_manifest(path: Path) -> Check:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Check("native-messaging", path.name, "warn", f"unreadable manifest: {exc}")
    # The file may be another program's: one of another shape is reported like one that is not JSON (#675).
    if not isinstance(data, dict):
        return Check("native-messaging", path.name, "warn", "unreadable manifest: not a JSON object")
    name = data["name"] if isinstance(data.get("name"), str) else path.stem
    if not isinstance(data.get("path", ""), str):
        return Check("native-messaging", name, "warn", "unreadable manifest: 'path' is not a string")
    listed = data.get("allowed_extensions", [])
    if not isinstance(listed, list) or not all(isinstance(item, str) for item in listed):
        return Check("native-messaging", name, "warn", "unreadable manifest: 'allowed_extensions' is not a list of strings")
    host = Path(data.get("path", ""))
    allowed = ", ".join(listed) or "none"
    if not host.is_absolute() or not host.exists():
        return Check("native-messaging", name, "warn", f"host binary missing: {host}")
    st = os.stat(host)
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return Check("native-messaging", name, "fail", f"host {host} is group/world-writable")
    return Check("native-messaging", name, "ok", f"{host} (allowed: {allowed}) [{path.parent}]")


def check_native_messaging() -> list[Check]:
    checks = []
    providers = profile.load_providers()["providers"]
    expected = {p["native_messaging"]["name"]: key for key, p in providers.items() if p.get("native_messaging")}
    seen = set()
    for directory in NATIVE_MANIFEST_DIRS:
        if not directory.is_dir():
            continue
        for manifest in sorted(directory.glob("*.json")):
            seen.add(manifest.stem)
            checks.append(_check_manifest(manifest))
    for name, provider_key in expected.items():
        if name not in seen:
            checks.append(
                Check(
                    "native-messaging",
                    name,
                    "info",
                    f"not registered (needed by provider '{provider_key}'; "
                    "the desktop app writes it when browser integration is enabled)",
                )
            )
    return checks


# 1Password's desktop app talks only to browsers it knows; any other browser's binary name goes in this file, one per
# line, written by root (support.1password.com/additional-browsers, read 2026-11-16). Nulavio never writes it (#81,
# the maintainer's decision of 2026-11-16): doctor says the exact command and the person runs it.
ONEPASSWORD_ALLOWED = Path("/etc/1password/custom_allowed_browsers")
ONEPASSWORD_APP = (Path("/opt/1Password/1password"), Path("/usr/bin/1password"))
# Browsers 1Password recognises by itself (Firefox among them): no step needed for Track A.
ONEPASSWORD_KNOWN = frozenset({"firefox", "firefox-bin", "firefox-esr"})


def _root_owned(path: Path) -> bool:
    """Whether the file and every folder above it belong to root and only root can change them (review of #478):
    the line 1Password's app is given trusts a name, so it is only offered for an engine nobody else can replace."""
    try:
        resolved = Path(path).resolve(strict=True)
    except OSError:
        return False
    for each in (resolved, *resolved.parents):
        try:
            info = os.stat(each)
        except OSError:
            return False
        if info.st_uid != 0 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return False
    return True


def check_1password(engine_path: Path | None = None) -> list[Check]:
    """When 1Password's desktop app is installed and the engine is a browser it does not know (the Nulavio build),
    whether its binary name is in custom_allowed_browsers, with the command that adds it. Nothing when the app is
    not installed. Reads only; never writes the file."""
    app = next((path for path in ONEPASSWORD_APP if path.exists()), None)
    if app is None:
        return []
    if engine_path is None:
        try:
            engine_path = engine_mod.find_engine().path
        except engine_mod.EngineError:
            return []
    name = Path(engine_path).name
    # The command below is pasted into a root shell: only a plain file name goes into it, and quoted.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        return [
            Check(
                "passwords",
                "1Password desktop app",
                "warn",
                f"the engine's file name {name!r} is not a plain name; no command given",
            )
        ]
    if name in ONEPASSWORD_KNOWN:
        return [Check("passwords", "1Password desktop app", "ok", f"{app}; it knows the engine ({name}) by itself")]
    try:
        listed = ONEPASSWORD_ALLOWED.read_text(encoding="utf-8")
    except FileNotFoundError:
        listed = ""
    except (OSError, UnicodeDecodeError) as exc:
        return [Check("passwords", "1Password desktop app", "warn", f"cannot read {ONEPASSWORD_ALLOWED}: {exc}")]
    allowed = {line.strip() for line in listed.splitlines()}
    root_only = _root_owned(Path(engine_path))
    if name in allowed:
        if not root_only:
            return [
                Check(
                    "passwords",
                    "1Password desktop app",
                    "warn",
                    f"'{name}' is in {ONEPASSWORD_ALLOWED}, but the engine ({engine_path}) can be changed without root: "
                    "the line lets any program with that name ask 1Password's app to unlock.",
                )
            ]
        return [Check("passwords", "1Password desktop app", "ok", f"'{name}' is in {ONEPASSWORD_ALLOWED}")]
    if not root_only:
        return [
            Check(
                "passwords",
                "1Password desktop app",
                "warn",
                f"the engine ({engine_path}) can be changed without root: adding '{name}' to {ONEPASSWORD_ALLOWED} would "
                "let any program with that name ask 1Password's app to unlock, so no command is given. It is given for "
                "an engine root alone can change (the RPM or DEB package, or the archive unpacked as root, e.g. under "
                "/opt); without it, the extension works with a sign-in in the browser.",
            )
        ]
    allowed_file = shlex.quote(str(ONEPASSWORD_ALLOWED))
    # A file whose last line has no line break would join the two names: one is put before ours then.
    command = f"printf '\\n%s\\n' {shlex.quote(name)}" if listed and not listed.endswith("\n") else f"echo {shlex.quote(name)}"
    command = f"{command} | sudo tee -a {allowed_file}"
    if not ONEPASSWORD_ALLOWED.parent.is_dir():
        command = f"sudo install -d -m 0755 {shlex.quote(str(ONEPASSWORD_ALLOWED.parent))} && {command}"
    return [
        Check(
            "passwords",
            "1Password desktop app",
            "info",
            f"to unlock the 1Password extension with the desktop app, add '{name}' to {ONEPASSWORD_ALLOWED}: "
            f"`{command}`, then quit 1Password (its menu > Quit) and open it again. The line trusts any program named "
            f"'{name}', so it is meant for an install root owns (RPM, DEB). Nulavio does not change that file. "
            "Without it, the extension still works with a sign-in in the browser.",
        )
    ]


def check_seeds(prof: profile.Profile) -> list[Check]:
    """A default of Nulavio whose value changed since this profile got it (#384): on its way, or kept as the
    person's. A choice is only named when the default moved after it was made; any other choice is just a choice."""
    try:
        settings = prof.load_settings()
        states = profile.seed_states(prof, settings)
    except (profile.ProfileError, paths.UnsafePathError, OSError, ValueError):
        return []  # no settings to read (a locked protected profile, one not set up, or one refused: check_profiles)
    checks = []
    for name, (state, want) in sorted(states.items()):
        if state == "follows":
            detail = "has an earlier default of Nulavio; the next start of this profile brings the current one"
            checks.append(Check("defaults", f"{prof.name}: {name}", "info", detail))
        elif state == "kept" and profile.default_moved(settings, name, want):
            detail = (
                "this profile has its own value, and Nulavio keeps it. Nulavio's default changed since and is not in"
                f" effect here. To use it, set this value in about:config: {prefs.format_value(want)}"
            )
            checks.append(Check("defaults", f"{prof.name}: {name}", "warn", detail))
    return checks


def check_profiles() -> list[Check]:
    checks = []
    for prof in profile.list_profiles():
        try:
            problems = paths.check_private(prof.path, paths.PRIVATE_DIR_MODE)
        except paths.UnsafePathError as exc:
            checks.append(Check("profile", prof.name, "fail", str(exc)))
            continue
        checks.append(
            Check(
                "profile", f"{prof.name} permissions", "fail" if problems else "ok", "; ".join(problems) or "0700, owned by you"
            )
        )
        checks += check_seeds(prof)
        for finding in guard.audit(prof.path):
            status = {"critical": "fail", "warning": "warn", "info": "info"}[finding.severity]
            checks.append(Check("guard", f"{prof.name}: {finding.pref}", status, f"{finding.message} (value: {finding.actual})"))
        locked = {e.id: e for e in extensions.load_lock().values()}
        for ext in extensions.installed_in_profile(prof.path):
            origin = "pinned in lock" if ext["id"] in locked else "installed by the user or another program"
            state = {
                "active": "active",
                "pending": "pending first start",
                "approval": "waiting for your approval (☰ menu)",
                "disabled": "disabled",
            }[extensions.state_of(ext)]
            checks.append(
                Check("extensions", f"{prof.name}: {ext['name']}", "info", f"{ext['version'] or '?'} - {state} - {origin}")
            )
    if not checks:
        checks.append(
            Check("profile", "profiles", "info", "no launcher profile; the browser's own profiles are not read by this check")
        )
    return checks


def run_all() -> list[Check]:
    return (
        check_engine()
        + check_platform()
        + check_media()
        + check_secrets()
        + check_native_messaging()
        + check_1password()
        + check_profiles()
    )


def to_json(checks: list[Check]) -> str:
    return json.dumps([asdict(c) for c in checks], indent=2, ensure_ascii=False)
