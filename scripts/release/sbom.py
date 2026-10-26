#!/usr/bin/env python3
"""Generate a CycloneDX 1.6 SBOM for the Nulavio preview distribution.

Covers what Nulavio itself pins or ships: the launcher (this repo), the
pinned extensions (with SHA-256), and the engine and libsodium as external
dependencies (distribution packages; not redistributed). Brand
fonts are referenced, not bundled, so they are not listed.

    python3 -I scripts/release/sbom.py > sbom/nulavio-preview.cdx.json
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import __version__  # noqa: E402

LOCK = ROOT / "browser" / "distribution" / "extensions.lock.json"


def git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> int:
    lock = json.loads(LOCK.read_text())
    components = [
        {
            "type": "application",
            "bom-ref": "engine:firefox",
            "name": "firefox",
            "supplier": {"name": "Mozilla"},
            "version": ">=140 (distribution package, not redistributed in Track A)",
            "licenses": [{"license": {"id": "MPL-2.0"}}],
            "scope": "required",
            "externalReferences": [{"type": "website", "url": "https://www.mozilla.org/firefox/"}],
        },
        {
            "type": "library",
            "bom-ref": "system:libsodium",
            "name": "libsodium",
            "version": ">=1.0.18 (distribution package, loaded through ctypes, not redistributed)",
            "licenses": [{"license": {"id": "ISC"}}],
            "scope": "optional",
            "externalReferences": [{"type": "website", "url": "https://libsodium.org/"}],
            "properties": [{"name": "nulavio:role", "value": "Nulavio Vault cryptography (decision D1)"}],
        },
    ]
    for entry in lock["extensions"]:
        license_id = entry["license"] if entry["license"] in {"GPL-3.0-only", "MPL-2.0"} else None
        component = {
            "type": "library",
            "bom-ref": f"xpi:{entry['id']}",
            "name": entry["name"],
            "version": entry["version"],
            "hashes": [{"alg": "SHA-256", "content": entry["sha256"]}],
            "scope": "required" if entry.get("default_install") else "optional",
            "externalReferences": [{"type": "distribution", "url": entry["url"]}, {"type": "website", "url": entry["homepage"]}],
            "properties": [{"name": "nulavio:role", "value": entry["role"]}],
        }
        component["licenses"] = [{"license": {"id": license_id}}] if license_id else [{"license": {"name": entry["license"]}}]
        components.append(component)
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'nulavio:' + (git_revision() or __version__))}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": "nulavio-preview",
                "name": "nulavio-preview",
                "version": __version__,
                "licenses": [{"license": {"id": "MPL-2.0"}}],
                "properties": [{"name": "nulavio:git-revision", "value": git_revision() or "uncommitted"}],
            }
        },
        "components": components,
        "dependencies": [{"ref": "nulavio-preview", "dependsOn": [c["bom-ref"] for c in components]}],
    }
    json.dump(bom, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
