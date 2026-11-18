"""Nulavio Connect P1/P2 (docs/adr/0004-nulavio-connect.md): more desktop facts, and two explicit actions.

Discovery stays read-only and evidence-based, as in P0:

* kde-connect: the KDE Connect daemon and the devices it can reach now;
* screen-cast: the portal's ScreenCast interface and a running PipeWire;
* security-keys: FIDO2/U2F keys plugged in (HID usage page 0xF1D0) and whether
  this user may open them (passkeys and Nulavio's planned security-key unlock);
* notifications: the desktop's notification service and portal;
* activities: Plasma activities (P2; Nulavio does not use them yet).

Actions, each only on the user's request:

* send a link to a KDE Connect device (`kdeconnect-cli --share`), one link at a time.

The KRunner plugin was removed (#461): KDE's own runners open a typed address or a web-search keyword in the
default browser.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from . import connect

DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TIMEOUT = 10


class ConnectP1Error(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, check=False)


# -- discovery ---------------------------------------------------------------------------


def devices() -> list[dict]:
    """KDE Connect devices reachable now (id and name), from its own command-line tool."""
    tool = shutil.which("kdeconnect-cli")
    if not tool:
        return []
    out = _run([tool, "--list-available", "--id-name-only"]).stdout
    found = []
    for line in out.splitlines():
        device, _, name = line.strip().partition(" ")
        if DEVICE_RE.match(device):
            found.append({"id": device, "name": name.strip() or device})
    return found


def _status(spec: dict, state: str, reason: str, detail: str, evidence: list[str], **params) -> connect.Status:
    return connect.Status(spec["id"], spec["priority"], state, detail, evidence, reason, params)


def _owner_line(spec: dict, owner: dict) -> str:
    return f"D-Bus name {spec['busName']} owned by {owner['comm'] or 'a process'}"


def kde_connect(spec: dict) -> connect.Status:
    owner = connect.name_owner(spec["busName"])
    if owner is None:
        return _status(
            spec, "unavailable", "not-running", "KDE Connect is not running.", [f"D-Bus name {spec['busName']} not owned"]
        )
    reachable = devices()
    evidence = [_owner_line(spec, owner), f"kdeconnect-cli --list-available: {len(reachable)} device(s)"]
    if not reachable:
        return _status(spec, "available", "no-device", "Running, but no paired device is reachable now.", evidence)
    names = ", ".join(d["name"] for d in reachable)
    return _status(spec, "available", "devices", f"Send a link to {names} from the link menu.", evidence, devices=names)


def screen_cast(spec: dict) -> connect.Status:
    owner = connect.name_owner(spec["busName"])
    interface = "org.freedesktop.portal.ScreenCast"
    version = connect.bus_property(spec["busName"], spec["objectPath"], interface, "version") if owner else None
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    pipewire = bool(runtime) and Path(runtime, "pipewire-0").exists()
    evidence = [
        f"portal ScreenCast {'v' + version if version else 'not reported'}",
        f"PipeWire socket {'present' if pipewire else 'absent'}",
    ]
    if version and pipewire:
        detail = "Sites can ask to share a screen or window; the desktop asks you which one, every time."
        return _status(spec, "available", "ready", detail, evidence)
    return _status(spec, "unavailable", "missing", "Screen sharing through the desktop is not available.", evidence)


FIDO_USAGE_PAGE = bytes([0x06, 0xD0, 0xF1])  # HID Usage Page (FIDO Alliance), 0xF1D0


def security_keys(spec: dict, sysfs: Path = Path("/sys/class/hidraw"), dev: Path = Path("/dev")) -> connect.Status:
    keys = []
    for node in sorted(sysfs.glob("hidraw*")) if sysfs.is_dir() else []:
        try:
            descriptor = (node / "device" / "report_descriptor").read_bytes()
        except OSError:
            continue
        if FIDO_USAGE_PAGE in descriptor:
            keys.append((node.name, os.access(dev / node.name, os.R_OK | os.W_OK)))
    evidence = [f"{name}: FIDO usage page, {'readable' if ok else 'not accessible to this user'}" for name, ok in keys]
    if not keys:
        detail = "No security key is plugged in. Passkeys stored in a password manager still work."
        return _status(spec, "unavailable", "none", detail, ["no hidraw device with the FIDO usage page"])
    if any(ok for _, ok in keys):
        return _status(spec, "available", "usable", "A security key is plugged in and usable.", evidence)
    detail = "A security key is plugged in, but this user cannot use it (the system's udev rules do not allow it)."
    return _status(spec, "error", "no-permission", detail, evidence)


def notifications(spec: dict) -> connect.Status:
    owner = connect.name_owner(spec["busName"])
    if owner is None:
        return _status(
            spec, "unavailable", "not-running", "No notification service is running.", [f"D-Bus name {spec['busName']} not owned"]
        )
    portal = connect.bus_property(
        "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Notification", "version"
    )
    evidence = [_owner_line(spec, owner), f"portal Notification {'v' + portal if portal else 'not reported'}"]
    return _status(
        spec, "available", "ready", "Site notifications you allow appear in the desktop's notification area.", evidence
    )


def activities(spec: dict) -> connect.Status:
    owner = connect.name_owner(spec["busName"])
    if owner is None:
        return _status(
            spec, "unavailable", "not-running", "Plasma activities are not running.", [f"D-Bus name {spec['busName']} not owned"]
        )
    detail = "Plasma activities are running. Nulavio does not use them yet (planned: a profile per activity, only if you choose)."
    return _status(spec, "available", "not-used", detail, [_owner_line(spec, owner)])


# -- KDE Connect: one link, on request ----------------------------------------------------------


def send_link(url: str, device: str) -> dict:
    """Share one web address with one reachable device (KDE Connect opens it there)."""
    if not isinstance(url, str) or not re.match(r"^https?://[^\s]{1,8000}$", url):
        raise ConnectP1Error("bad-url")
    if not isinstance(device, str) or not DEVICE_RE.match(device):
        raise ConnectP1Error("bad-device")
    if device not in {d["id"] for d in devices()}:
        raise ConnectP1Error("device-unreachable")
    tool = shutil.which("kdeconnect-cli")
    result = _run([tool, "--device", device, "--share", url])
    if result.returncode != 0:
        raise ConnectP1Error("send-failed")
    return {"sent": True, "device": device}


PROBES = {
    "kde-connect": kde_connect,
    "screen-cast": screen_cast,
    "security-keys": security_keys,
    "notifications": notifications,
    "activities": activities,
}


def api_request(request: dict) -> dict:
    """The browser's requests (Settings -> Integrations, the link menu), one per call."""
    op = request.get("op")
    if op == "discover":
        later = [d for d in connect.definitions() if d["priority"] != "P0"]
        items = []
        for spec in later:
            try:
                items.append(PROBES[spec["id"]](spec))
            except Exception as exc:  # a broken probe reports itself
                items.append(_status(spec, "error", "check-failed", "This check failed.", [repr(exc)]))
        return {"items": [asdict(i) for i in items]}
    if op == "devices":
        return {"devices": devices()}
    if op == "send-link":
        return send_link(request.get("url"), request.get("device"))
    raise ConnectP1Error("bad-request")
