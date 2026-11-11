#!/usr/bin/env python3
"""Propose updates to browser/distribution/extensions.lock.json from the AMO API.

Prints a reviewable diff of version/URL/hash/size changes and permission
changes. Writes nothing unless --write is given. A permission increase is
flagged so reviewers re-check the extension before merging.

    python3 -I scripts/upstream/refresh_extensions_lock.py           # dry run
    python3 -I scripts/upstream/refresh_extensions_lock.py --write   # update the lock
    python3 -I scripts/upstream/refresh_extensions_lock.py --registry   # only re-copy uBlock Origin's list registry

uBlock Origin's list registry (browser/distribution/ublock-origin/) is copied from the pinned package, because
new profiles start from it with Nulavio's default lists on (browser/distribution/content-filter.json). `--write`
re-copies it when uBlock Origin's pin changes and says when a default list is gone or already on upstream.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import extensions  # noqa: E402

LOCK = ROOT / "browser" / "distribution" / "extensions.lock.json"
CONTENT_FILTER = ROOT / "browser" / "distribution" / "content-filter.json"
REGISTRY_DIR = CONTENT_FILTER.parent / "ublock-origin"
API = "https://addons.mozilla.org/api/v5/addons/addon/{guid}/"


def query(guid: str) -> dict:
    url = API.format(guid=urllib.parse.quote(guid, safe=""))
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "nulavio-lock-refresh"}), timeout=60) as resp:
        data = json.load(resp)
    current = data["current_version"]
    file = current["file"]
    algo, _, digest = file["hash"].partition(":")
    if algo != "sha256":
        raise SystemExit(f"{guid}: AMO returned {algo} hash")
    return {
        "version": current["version"],
        "url": file["url"],
        "sha256": digest,
        "size": file["size"],
        "permissions": sorted(file.get("permissions", []) + file.get("host_permissions", [])),
    }


def refresh_registry() -> None:
    """Copy the list registry and the licence out of the pinned, hash-verified uBlock Origin package."""
    config = json.loads(CONTENT_FILTER.read_text(encoding="utf-8"))
    entry = extensions.load_lock()[config["extension"]]
    with zipfile.ZipFile(extensions.fetch(entry)) as package:
        raw, licence = package.read("assets/assets.json"), package.read("LICENSE.txt")
    registry = json.loads(raw)
    for key in config["default_on"]:
        listed = registry.get(key)
        if not isinstance(listed, dict) or listed.get("content") != "filters":
            print(f"    ! DEFAULT LIST GONE in {entry.version}: {key} (edit content-filter.json before building)")
        elif listed.get("off") is not True:
            print(f"    ! {key} is on by default in {entry.version}: remove it from content-filter.json")
    (REGISTRY_DIR / "assets.json").write_bytes(raw)
    (REGISTRY_DIR / "LICENSE.txt").write_bytes(licence)
    config["registry"] = {"version": entry.version, "sha256": hashlib.sha256(raw).hexdigest()}
    CONTENT_FILTER.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"copied uBlock Origin {entry.version}'s list registry to {REGISTRY_DIR.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--registry", action="store_true", help="re-copy uBlock Origin's list registry from the pinned package")
    args = parser.parse_args()
    if args.registry:
        refresh_registry()
        return 0
    lock = json.loads(LOCK.read_text())
    registry_owner = json.loads(CONTENT_FILTER.read_text(encoding="utf-8"))["extension"]
    stale_registry = False
    changed = False
    for entry in lock["extensions"]:
        latest = query(entry["id"])
        if latest["version"] == entry["version"]:
            print(f"= {entry['key']} {entry['version']}")
            continue
        changed = True
        print(f"~ {entry['key']}: {entry['version']} -> {latest['version']}")
        print(f"    sha256 {entry['sha256']} -> {latest['sha256']}")
        added = set(latest["permissions"]) - set(entry.get("reviewed_permissions", []))
        if added:
            print(f"    ! NEW PERMISSIONS (review before merging): {sorted(added)}")
        entry.update({k: latest[k] for k in ("version", "url", "sha256", "size")})
        entry["reviewed_permissions"] = latest["permissions"]
        stale_registry = stale_registry or entry["key"] == registry_owner
    if changed and args.write:
        lock["verified_on"] = dt.date.today().isoformat()
        LOCK.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
        if stale_registry:
            refresh_registry()
        print(f"wrote {LOCK.relative_to(ROOT)}; run the unit and integration tests before committing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
