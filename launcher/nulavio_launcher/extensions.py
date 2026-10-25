"""Pinned extension sources: fetch with integrity checks, install into a profile.

Trust chain for an extension installed by Nulavio:

1. ``browser/distribution/extensions.lock.json`` pins id, version, URL,
   size and SHA-256 (reviewed in git).
2. Downloads are HTTPS-only, restricted to addons.mozilla.org, size-capped
   and hash-verified before they are cached.
3. The engine verifies the Mozilla (AMO) signature when it loads the XPI;
   unsigned or tampered files are refused by Firefox itself.
4. After install, the engine's normal extension updates apply (security
   fixes keep flowing); the pin only governs the *first* install.

Installation copies ``<id>.xpi`` into ``<profile>/extensions/``. What the
engine does next depends on its build: Fedora's package sets
``extensions.autoDisableScopes=0`` and enables the file at next start;
Mozilla's own builds (default 15) keep it disabled until the user approves
it from the menu. Nulavio never bypasses that prompt. The launcher only
places files on an explicit user action and the CLI says so.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import log, paths

ALLOWED_HOSTS = {"addons.mozilla.org"}
_CHUNK = 1 << 16


class IntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class LockedExtension:
    key: str
    id: str
    name: str
    role: str
    default_install: bool
    version: str
    url: str
    sha256: str
    size: int
    license: str

    @property
    def xpi_name(self) -> str:
        return f"{self.id}.xpi"


def load_lock(path: Path | None = None) -> dict[str, LockedExtension]:
    path = path or paths.repo_root() / "browser" / "distribution" / "extensions.lock.json"
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = {}
    for raw in data["extensions"]:
        entry = LockedExtension(
            key=raw["key"],
            id=raw["id"],
            name=raw["name"],
            role=raw["role"],
            default_install=bool(raw.get("default_install", False)),
            version=raw["version"],
            url=raw["url"],
            sha256=raw["sha256"].lower(),
            size=int(raw["size"]),
            license=raw.get("license", ""),
        )
        validate_entry(entry)
        entries[entry.key] = entry
    return entries


def validate_entry(entry: LockedExtension) -> None:
    parsed = urllib.parse.urlparse(entry.url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise IntegrityError(f"{entry.key}: URL must be https on {sorted(ALLOWED_HOSTS)}")
    if len(entry.sha256) != 64 or any(c not in "0123456789abcdef" for c in entry.sha256):
        raise IntegrityError(f"{entry.key}: sha256 must be 64 hex characters")
    if not 0 < entry.size <= 64 * 1024 * 1024:
        raise IntegrityError(f"{entry.key}: implausible size {entry.size}")
    if "/" in entry.id or entry.id.startswith("."):
        raise IntegrityError(f"{entry.key}: invalid extension id")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cached_path(entry: LockedExtension) -> Path:
    return paths.cache_home() / "xpi" / f"{entry.sha256}.xpi"


class _NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise IntegrityError(f"refusing redirect to {parsed.scheme}://{parsed.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(entry: LockedExtension, timeout: float = 60.0) -> Path:
    """Return a verified cached XPI, downloading it if needed."""
    validate_entry(entry)
    target = cached_path(entry)
    if target.exists():
        if sha256_file(target) == entry.sha256:
            return target
        target.unlink()  # corrupted or tampered cache entry; refetch
    paths.ensure_private_dir(target.parent)
    partial = target.with_suffix(".part")
    opener = urllib.request.build_opener(_NoCrossHostRedirect())
    request = urllib.request.Request(entry.url, headers={"User-Agent": "nulavio-launcher/0 (+preview)"})
    digest = hashlib.sha256()
    received = 0
    with opener.open(request, timeout=timeout) as response, open(partial, "wb") as out:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ALLOWED_HOSTS:
            raise IntegrityError(f"unexpected final URL host {final.hostname}")
        for chunk in iter(lambda: response.read(_CHUNK), b""):
            received += len(chunk)
            if received > entry.size:
                raise IntegrityError(f"{entry.key}: download larger than pinned size")
            digest.update(chunk)
            out.write(chunk)
    if received != entry.size or digest.hexdigest() != entry.sha256:
        partial.unlink(missing_ok=True)
        raise IntegrityError(f"{entry.key}: integrity mismatch (size {received}/{entry.size}, sha256 {digest.hexdigest()})")
    partial.chmod(paths.PRIVATE_FILE_MODE)
    partial.replace(target)
    log.event("extension.fetch", key=entry.key, version=entry.version, sha256=entry.sha256)
    return target


def install(entry: LockedExtension, profile_dir: Path) -> Path:
    """Copy the verified XPI into the profile; the engine activates it at start."""
    source = fetch(entry)
    if sha256_file(source) != entry.sha256:
        raise IntegrityError(f"{entry.key}: cache changed during install")
    ext_dir = paths.ensure_private_dir(Path(profile_dir) / "extensions")
    destination = ext_dir / entry.xpi_name
    tmp = destination.with_suffix(".xpi.tmp")
    shutil.copyfile(source, tmp)
    tmp.chmod(paths.PRIVATE_FILE_MODE)
    tmp.replace(destination)
    log.event("extension.install", key=entry.key, version=entry.version, profile=Path(profile_dir).name)
    return destination


def state_of(ext: dict) -> str:
    """One of: active, pending (not started yet), approval (engine asks the user), disabled."""
    if not ext.get("registered"):
        return "pending"
    if ext.get("active"):
        return "active"
    return "approval" if ext.get("awaiting_approval") else "disabled"


def installed_in_profile(profile_dir: Path) -> list[dict]:
    """Describe extensions the engine registered (extensions.json) or that wait in extensions/."""
    profile_dir = Path(profile_dir)
    found: dict[str, dict] = {}
    registry = profile_dir / "extensions.json"
    if registry.exists():
        try:
            data = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        for addon in data.get("addons", []):
            if addon.get("type") != "extension" or addon.get("location") != "app-profile":
                continue
            found[addon["id"]] = {
                "id": addon["id"],
                "name": (addon.get("defaultLocale") or {}).get("name", addon["id"]),
                "version": addon.get("version"),
                "active": bool(addon.get("active")),
                "registered": True,
                # Engines with autoDisableScopes covering the profile (Mozilla's own builds)
                # keep sideloaded extensions off until the user approves them.
                "awaiting_approval": bool(addon.get("userDisabled")) and not addon.get("seen", True),
            }
    ext_dir = profile_dir / "extensions"
    if ext_dir.is_dir():
        for xpi in sorted(ext_dir.glob("*.xpi")):
            ext_id = xpi.name[: -len(".xpi")]
            if ext_id.startswith("langpack-"):
                continue  # language packs are engine resources, not extensions
            found.setdefault(
                ext_id,
                {"id": ext_id, "name": ext_id, "version": None, "active": None, "registered": False, "awaiting_approval": False},
            )
    return sorted(found.values(), key=lambda item: item["id"])
