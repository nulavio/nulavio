#!/usr/bin/env python3
"""Propose updates to browser/distribution/extensions.lock.json from the AMO API.

Prints a reviewable diff of version/URL/hash/size changes and permission
changes. Writes nothing unless --write is given. A permission increase is
flagged so reviewers re-check the extension before merging.

    python3 -I scripts/upstream/refresh_extensions_lock.py           # dry run
    python3 -I scripts/upstream/refresh_extensions_lock.py --write   # update the lock
    python3 -I scripts/upstream/refresh_extensions_lock.py --registry   # only re-copy uBlock Origin's list registry
    python3 -I scripts/upstream/refresh_extensions_lock.py --check-registry   # is the copy the pinned package's?

uBlock Origin's list registry (browser/distribution/ublock-origin/) is copied from the pinned package, because
new profiles start from it with Nulavio's default lists on (browser/distribution/content-filter.json). `--write`
re-copies it when uBlock Origin's pin changes and says when a default list is gone or already on upstream.

`--check-registry` is the gate CI and the release rehearsal run: it gets the pinned package (from the local cache
or from AMO, checked against the lock's SHA-256 either way) and compares the copy with it byte for byte. The
checksum in content-filter.json only says that the copy and that file agree with each other; someone who edits
the copy can edit the checksum too. Exit 1 when the copy is not the package's, 2 when the package could not be
had: a copy that was not compared is not a copy that passed.
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


# What the default lists rest on inside uBlock Origin (scripts/build/make_distribution.py, `registry_address`): the
# code that reads the registry's address from the managed settings, the rule for what counts as an external address,
# and the two places that decide from `off` which lists a new profile selects and which a registry update reconciles.
# Read as text from the package, so a new version that changed one of them is seen before anything is built.
BOOTSTRAP_MARKERS = {
    "managed_storage.json": ['"adminSettings"'],
    "js/storage.js": [
        "µb.assetsBootstrapLocation = data.assetsBootstrapLocation;",
        "if ( list.off !== true ) {",
        "const newDefaultListset = new Set(newDict['assets.json'].defaultListset || []);",
    ],
    "js/assets.js": [
        "µb.assetsBootstrapLocation || µb.assetsJsonPath",
        "const reIsExternalPath = /^(?:[a-z-]+):\\/\\//;",
        ".filter(a => a[1].content === 'filters' && a[1].off === undefined)",
    ],
}


def bootstrap_report(package: zipfile.ZipFile) -> list[str]:
    """What the default lists rest on and this package no longer has, as "file: text". Empty when all is there."""
    missing = []
    for name, markers in BOOTSTRAP_MARKERS.items():
        try:
            text = package.read(name).decode("utf-8")
        except KeyError:
            missing.append(f"{name}: the file is gone")
            continue
        missing += [f"{name}: {marker}" for marker in markers if marker not in text]
    return missing


def registry_report(package: zipfile.ZipFile, registry_dir: Path = REGISTRY_DIR) -> list[str]:
    """How the copy in the repository differs from this package, one line per difference. Empty when it is its."""
    report = []
    for inside, name in (("assets/assets.json", "assets.json"), ("LICENSE.txt", "LICENSE.txt")):
        try:
            theirs = package.read(inside)
        except KeyError:
            report.append(f"{inside}: not in the package")
            continue
        ours = (registry_dir / name).read_bytes()
        if ours == theirs:
            continue
        report.append(f"{name}: not the package's {inside}")
        if name == "assets.json":
            try:
                mine, upstream = json.loads(ours), json.loads(theirs)
            except ValueError:
                continue
            report += [f"    {key}: only in the package" for key in upstream if key not in mine]
            report += [f"    {key}: only in the copy" for key in mine if key not in upstream]
            report += [f"    {key}: differs" for key in mine if key in upstream and mine[key] != upstream[key]]
    return report + [f"{line} (what the default lists rest on)" for line in bootstrap_report(package)]


def check_registry() -> int:
    """Compare the copy with the pinned, hash-verified package: 0 the same, 1 not the same, 2 no package to compare with."""
    config = json.loads(CONTENT_FILTER.read_text(encoding="utf-8"))
    entry = extensions.load_lock()[config["extension"]]
    try:
        path = extensions.fetch(entry)
    except (OSError, extensions.IntegrityError) as error:
        print(f"uBlock Origin {entry.version} could not be had, so the list registry was not compared: {error}", file=sys.stderr)
        return 2
    with zipfile.ZipFile(path) as package:
        report = registry_report(package, REGISTRY_DIR)
    for line in report:
        print(line, file=sys.stderr)
    if report:
        print(f"the list registry is not uBlock Origin {entry.version}'s: run with --registry and read the diff", file=sys.stderr)
        return 1
    print(f"the list registry is uBlock Origin {entry.version}'s (package sha256 {entry.sha256})")
    return 0


def refresh_registry() -> None:
    """Copy the list registry and the licence out of the pinned, hash-verified uBlock Origin package."""
    config = json.loads(CONTENT_FILTER.read_text(encoding="utf-8"))
    entry = extensions.load_lock()[config["extension"]]
    with zipfile.ZipFile(extensions.fetch(entry)) as package:
        raw, licence = package.read("assets/assets.json"), package.read("LICENSE.txt")
        for line in bootstrap_report(package):
            print(f"    ! THE DEFAULT LISTS MAY NO LONGER APPLY in {entry.version}: {line}")
            print("      see docs/security/dependency-updates.md (uBlock Origin's default lists) and run test_content_filter.py")
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
    parser.add_argument("--check-registry", action="store_true", help="compare the list registry with the pinned package")
    args = parser.parse_args()
    if args.check_registry:
        return check_registry()
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
