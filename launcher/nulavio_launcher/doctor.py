"""`nulavio doctor`: local environment and profile health checks.

Read-only. Reports facts the user can act on; never phones home.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from . import engine as engine_mod
from . import extensions, guard, paths, profile

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
    owner = _run(["rpm", "-qf", str(eng.path)]) if shutil.which("rpm") else ""
    if owner and "not owned" not in owner:
        checks.append(Check("engine", "updates", "ok", f"package {owner}: security updates via the distribution"))
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
    return checks


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
    host = Path(data.get("path", ""))
    allowed = ", ".join(data.get("allowed_extensions", [])) or "none"
    if not host.is_absolute() or not host.exists():
        return Check("native-messaging", data.get("name", path.stem), "warn", f"host binary missing: {host}")
    st = os.stat(host)
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return Check("native-messaging", data.get("name", path.stem), "fail", f"host {host} is group/world-writable")
    return Check("native-messaging", data.get("name", path.stem), "ok", f"{host} (allowed: {allowed}) [{path.parent}]")


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
        checks.append(Check("profile", "profiles", "info", "no Nulavio profile yet (run `nulavio setup`)"))
    return checks


def run_all() -> list[Check]:
    return check_engine() + check_platform() + check_secrets() + check_native_messaging() + check_profiles()


def to_json(checks: list[Check]) -> str:
    return json.dumps([asdict(c) for c in checks], indent=2, ensure_ascii=False)
