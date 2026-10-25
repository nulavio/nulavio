#!/usr/bin/env python3
"""Propose updates to browser/distribution/extensions.lock.json from the AMO API.

Prints a reviewable diff of version/URL/hash/size changes and permission
changes. Writes nothing unless --write is given. A permission increase is
flagged so reviewers re-check the extension before merging.

    python3 -I scripts/upstream/refresh_extensions_lock.py           # dry run
    python3 -I scripts/upstream/refresh_extensions_lock.py --write   # update the lock
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "browser" / "distribution" / "extensions.lock.json"
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text())
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
    if changed and args.write:
        lock["verified_on"] = dt.date.today().isoformat()
        LOCK.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {LOCK.relative_to(ROOT)}; run the unit and integration tests before committing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
