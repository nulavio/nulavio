"""`nulavio integrations`: Nulavio Connect P0 discovery (docs/adr/0004-nulavio-connect.md).

Read-only. Each integration reports what was actually checked (evidence), and
`unknown` when it cannot know; nothing is guessed and nothing is changed.
Uses only: D-Bus name ownership and properties on the session bus (busctl),
the freedesktop default-application settings (xdg-settings, xdg-mime) and the
files an integration installs itself. No network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import doctor, paths

STATES = ("available", "unavailable", "enabled", "error", "unknown")


@dataclass
class Status:
    id: str
    priority: str
    state: str
    detail: str
    evidence: list[str] = field(default_factory=list)
    reason: str = ""  # stable code for the browser's translations (P1/P2)
    params: dict = field(default_factory=dict)


def definitions() -> list[dict]:
    data = json.loads((paths.config_dir() / "integrations.json").read_text(encoding="utf-8"))
    return data["integrations"]


# -- probes (each one runs an argument list; never a shell) ---------------------


def name_owner(name: str) -> dict | None:
    """{"comm": ..., "exe": ...} for the process owning a session-bus name, or None."""
    if not shutil.which("busctl") or not doctor._dbus_has_owner(name):
        return None  # checked first: asking about an absent name must not start its service
    out = doctor._run(["busctl", "--user", "--no-pager", "status", name])
    fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if not fields:
        return None
    exe = fields.get("Exe", "")
    # Comm is cut to 15 characters by the kernel; the executable's name is not.
    return {"comm": Path(exe).name if exe else fields.get("Comm", ""), "exe": exe}


def bus_property(bus: str, path: str, interface: str, prop: str) -> str | None:
    out = doctor._run(["busctl", "--user", "--no-pager", "get-property", bus, path, interface, prop])
    match = re.fullmatch(r"[a-z]\s+(.+)", out.strip())
    return match.group(1).strip('"') if match else None


def _xdg(args: list[str]) -> str:
    tool = args[0]
    return doctor._run(args) if shutil.which(tool) else ""


def desktop_name(desktop_id: str) -> str:
    """Name= of an installed desktop entry, else the id."""
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    dirs = [data_home] + [Path(d) for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    for base in dirs:
        entry = base / "applications" / desktop_id
        try:
            for line in entry.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Name="):
                    return line[5:].strip()
        except OSError:
            continue
    return desktop_id


# -- integrations ------------------------------------------------------------------


def plasma_browser_integration(spec: dict) -> Status:
    evidence = []
    host = None
    for directory in doctor.NATIVE_MANIFEST_DIRS:
        manifest = directory / f"{spec['nativeHost']}.json"
        if manifest.is_file():
            host = manifest
            break
    if host is None:
        dirs = ", ".join(str(d) for d in doctor.NATIVE_MANIFEST_DIRS)
        return Status(
            spec["id"],
            spec["priority"],
            "unavailable",
            "Plasma Browser Integration is not installed.",
            [f"no {spec['nativeHost']}.json in {dirs}"],
        )
    try:
        data = json.loads(host.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Status(spec["id"], spec["priority"], "error", "The host manifest cannot be read.", [f"{host}: {exc}"])
    binary = Path(data.get("path", ""))
    evidence.append(f"host manifest {host}")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return Status(spec["id"], spec["priority"], "error", "The host program is missing.", [*evidence, f"missing {binary}"])
    if binary.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return Status(
            spec["id"],
            spec["priority"],
            "error",
            "The host program can be modified by other users.",
            [*evidence, f"{binary} is group/world-writable"],
        )
    if spec["extension"] not in data.get("allowed_extensions", []):
        return Status(
            spec["id"],
            spec["priority"],
            "error",
            "The host does not accept the KDE extension.",
            [*evidence, f"{spec['extension']} not in allowed_extensions"],
        )
    evidence.append(f"host program {binary}")
    owner = name_owner(spec["session"])
    if owner is None:
        return Status(
            spec["id"],
            spec["priority"],
            "unavailable",
            "Installed, but no Plasma session is running.",
            [*evidence, f"D-Bus name {spec['session']} not owned"],
        )
    evidence.append(f"D-Bus name {spec['session']} owned by {owner['comm'] or 'a process'}")
    return Status(
        spec["id"],
        spec["priority"],
        "available",
        "Ready. Install the KDE extension in a profile to use media controls and KDE Connect sharing.",
        evidence,
    )


def xdg_portals(spec: dict) -> Status:
    owner = name_owner(spec["busName"])
    if owner is None:
        return Status(
            spec["id"],
            spec["priority"],
            "unavailable",
            "No desktop portal service is running.",
            [f"D-Bus name {spec['busName']} not owned"],
        )
    evidence = [f"D-Bus name {spec['busName']} owned by {owner['comm'] or 'a process'}"]
    versions = []
    for interface in spec["interfaces"]:
        version = bus_property(spec["busName"], spec["objectPath"], f"org.freedesktop.portal.{interface}", "version")
        versions.append(f"{interface} {'v' + version if version else 'not reported'}")
    evidence.append("interfaces: " + ", ".join(versions))
    return Status(
        spec["id"],
        spec["priority"],
        "available",
        "File dialogs, screen sharing and opening links go through the desktop.",
        evidence,
    )


def secret_service(spec: dict) -> Status:
    owner = name_owner(spec["busName"])
    related = [n for n in spec.get("related", []) if name_owner(n)]
    evidence = [f"D-Bus name {n} owned" for n in related]
    if owner is None:
        return Status(
            spec["id"],
            spec["priority"],
            "unavailable",
            "No secret storage service is running.",
            [f"D-Bus name {spec['busName']} not owned", *evidence],
        )
    provider = owner["comm"] or "a process"
    return Status(
        spec["id"],
        spec["priority"],
        "available",
        f"Provided by {provider}. Nulavio does not store website passwords there.",
        [f"D-Bus name {spec['busName']} owned by {provider}", *evidence],
    )


def default_browser(spec: dict) -> Status:
    current = _xdg(["xdg-settings", "get", "default-web-browser"])
    handlers = {t: _xdg(["xdg-mime", "query", "default", t]) for t in spec["types"]}
    evidence = [f"xdg-settings default-web-browser: {current or 'not set'}"]
    evidence += [f"xdg-mime {t}: {h or 'not set'}" for t, h in handlers.items()]
    if not shutil.which("xdg-settings"):
        return Status(
            spec["id"],
            spec["priority"],
            "unknown",
            "xdg-settings is not installed, so the default browser cannot be read.",
            evidence,
        )
    ours = set(spec["nulavioDesktopIds"])
    if current in ours and all(h in ours for h in handlers.values()):
        return Status(spec["id"], spec["priority"], "enabled", "Nulavio opens web links from other apps.", evidence)
    name = desktop_name(current) if current else "no browser"
    return Status(spec["id"], spec["priority"], "available", f"Web links from other apps open in {name}.", evidence)


PROBES = {
    "plasma-browser-integration": plasma_browser_integration,
    "xdg-portals": xdg_portals,
    "secret-service": secret_service,
    "default-browser": default_browser,
}


def discover() -> list[Status]:
    from .connect_p1 import PROBES as LATER  # P1/P2 probes

    results = []
    for spec in definitions():
        probe = PROBES.get(spec["id"]) or LATER[spec["id"]]
        try:
            results.append(probe(spec))
        except Exception as exc:  # a broken probe reports itself; it never hides the others
            results.append(Status(spec["id"], spec["priority"], "error", "This check failed.", [repr(exc)]))
    return results


def to_json(statuses: list[Status]) -> str:
    return json.dumps([asdict(s) for s in statuses], indent=2)
