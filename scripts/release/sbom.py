#!/usr/bin/env python3
"""Generate a CycloneDX 1.6 SBOM for the Nulavio preview distribution.

Covers what Nulavio itself pins or ships: the launcher (this repo), the
pinned extensions (with SHA-256), and the engine and libsodium as external
dependencies (distribution packages; not redistributed). Brand
fonts are referenced, not bundled, so they are not listed.

    python3 -I scripts/release/sbom.py > sbom/nulavio-preview.cdx.json

With --package, the SBOM of a Nulavio package (RPM or .deb) instead: the
engine is then redistributed, built from Mozilla's source release with the
patches in browser/patches (each listed with its SHA-256 in the pedigree),
and the package file's own SHA-256 identifies what it describes.

    python3 -I scripts/release/sbom.py --package dist/packages/x86_64/nulavio-158.0.1-0.1.fc44.x86_64.rpm \
        --engine-version 158.0.1 > nulavio-158.0.1-0.1.fc44.x86_64.rpm.cdx.json

With --companion, the SBOM of the Android Companion app: every library in its
release build as Gradle resolved it (with the version Gradle chose), each with
a Maven purl and the SHA-256 that android/gradle/verification-metadata.xml pins,
and the dependency graph. Gradle writes the report, this script only reads it:

    android/gradlew -p android -q :app:dependencies --configuration releaseRuntimeClasspath > deps.txt
    python3 -I scripts/release/sbom.py --companion --gradle-dependencies deps.txt [--apk app.apk] > companion.cdx.json

Components carry a purl and, where the NVD CPE dictionary has the product, a CPE,
so vulnerability scanners can match them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

from nulavio_launcher import __version__  # noqa: E402

LOCK = ROOT / "browser" / "distribution" / "extensions.lock.json"
PATCHES = ROOT / "browser" / "patches"
ANDROID = ROOT / "android"
VERIFICATION = ANDROID / "gradle" / "verification-metadata.xml"
APP_GRADLE = ANDROID / "app" / "build.gradle.kts"
MPL = [{"license": {"id": "MPL-2.0"}}]

# Vendor and product as the NVD CPE dictionary names them (checked 2026-10-27). Bitwarden's
# entries there are its desktop app and Proton Pass has none, so those get no CPE.
ENGINE_CPE = ("mozilla", "firefox")
EXTENSION_CPE = {
    "uBlock0@raymondhill.net": ("ublockorigin", "ublock_origin"),
    "keepassxc-browser@keepassxc.org": ("keepassxc", "keepassxc-browser"),
}

# One line of `gradlew :app:dependencies`: "|    +--- group:name:1.0 -> 1.1 (*)".
GRADLE_LINE = re.compile(r"^(?P<indent>(?:[| ]    )*)[+\\]--- (?P<item>.+?)(?: \((?P<mark>[*cn])\))?$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cpe(vendor_product: tuple[str, str], version: str) -> str | None:
    """CPE 2.3 name of one release, or None when the version is not a plain release number."""
    if not re.fullmatch(r"[0-9][0-9A-Za-z._-]*", version):
        return None
    vendor, product = vendor_product
    return f"cpe:2.3:a:{vendor}:{product}:{version}:*:*:*:*:*:*:*"


def purl(kind: str, namespace: str, name: str, version: str, qualifiers: str = "") -> str:
    """A package URL (https://github.com/package-url/purl-spec), each part percent-encoded."""
    parts = "/".join(urllib.parse.quote(part, safe="") for part in namespace.split("/"))
    return f"pkg:{kind}/{parts}/{urllib.parse.quote(name, safe='')}@{urllib.parse.quote(version, safe='')}{qualifiers}"


def engine_built(version: str) -> dict:
    """The engine as a Nulavio package redistributes it: Mozilla's source release plus Nulavio's patches."""
    names = [line.strip() for line in (PATCHES / "series").read_text().splitlines() if line.strip() and not line.startswith("#")]
    identity = {"purl": purl("generic", "mozilla", "firefox", version)}
    if engine_cpe := cpe(ENGINE_CPE, version):
        identity["cpe"] = engine_cpe
    return {
        "type": "application",
        "bom-ref": "engine:firefox",
        "name": "firefox",
        "supplier": {"name": "Mozilla"},
        "version": version,
        **identity,
        "licenses": [{"license": {"id": "MPL-2.0"}}],
        "scope": "required",
        "externalReferences": [
            {"type": "distribution", "url": f"https://archive.mozilla.org/pub/firefox/releases/{version}/source/"},
        ],
        "properties": [{"name": "nulavio:role", "value": "redistributed, built by scripts/build/build_nulavio.sh"}],
        "pedigree": {
            "patches": [
                {
                    "type": "unofficial",
                    "diff": {"url": f"browser/patches/{name}"},
                    "resolves": [],
                }
                | {"properties": [{"name": "sha256", "value": sha256(PATCHES / name)}]}
                for name in names
            ]
        },
    }


def git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def gradle_node(item: str) -> str:
    """ "group:name:version" with the version Gradle resolved, or "project:<name>" for a module of this build."""
    if project := re.fullmatch(r"project '?:([\w.-]+)'?", item):
        return f"project:{project[1]}"
    requested, _, resolved = item.partition(" -> ")
    parts = requested.split(":")
    version = resolved.strip() or (parts[2] if len(parts) == 3 else "")
    if len(parts) not in (2, 3) or not re.fullmatch(r"[\w.+-]+", version):
        raise SystemExit(f"sbom: no resolved module version in the Gradle report: {item!r}")
    return f"{parts[0]}:{parts[1]}:{version}"


def parse_gradle_dependencies(text: str) -> tuple[list[str], dict[str, list[str]]]:
    """The direct dependencies and the graph ({node: [its dependencies]}) of one configuration in a
    `gradlew :app:dependencies --configuration ...` report."""
    top: list[str] = []
    graph: dict[str, list[str]] = {}
    ancestors: list[str] = []
    for line in text.splitlines():
        match = GRADLE_LINE.match(line)
        if not match or match["mark"] in ("c", "n"):  # not a dependency line; a constraint; not resolved
            continue
        if "FAILED" in match["item"]:
            raise SystemExit(f"sbom: Gradle could not resolve {match['item']}")
        depth = len(match["indent"]) // 5
        if depth > len(ancestors):
            raise SystemExit(f"sbom: unexpected indentation in the Gradle report: {line!r}")
        del ancestors[depth:]
        node = gradle_node(match["item"])
        siblings = graph[ancestors[-1]] if ancestors else top
        if node not in siblings:
            siblings.append(node)
        graph.setdefault(node, [])
        ancestors.append(node)
    if not top:
        raise SystemExit(
            "sbom: no dependencies in the Gradle report (run :app:dependencies --configuration releaseRuntimeClasspath)"
        )
    return top, graph


def maven_artifacts(verification: Path) -> dict[str, tuple[str, str]]:
    """{"group:name:version": (file, SHA-256)} for the jar or aar of each component Gradle verifies."""
    root = ET.parse(verification).getroot()  # noqa: S314 -- this repository's own Gradle file
    ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""
    found = {}
    for component in root.iter(f"{ns}component"):
        group, name, version = (component.get(key) for key in ("group", "name", "version"))
        for artifact in component.iter(f"{ns}artifact"):
            sha = artifact.find(f"{ns}sha256")
            if artifact.get("name") in (f"{name}-{version}.jar", f"{name}-{version}.aar") and sha is not None:
                found[f"{group}:{name}:{version}"] = (artifact.get("name"), sha.get("value"))
    return found


def companion_bom(report: str, verification: Path, app_gradle: Path, apk: Path | None = None) -> dict:
    """CycloneDX for the Companion app: the libraries of its release build and how they depend on each other."""
    gradle = app_gradle.read_text()
    app_id = re.search(r'applicationId = "([^"]+)"', gradle)[1]
    version_name = re.search(r'versionName = "([^"]+)"', gradle)[1]
    version_code = re.search(r"versionCode = (\d+)", gradle)[1]
    top, graph = parse_gradle_dependencies(report)
    artifacts = maven_artifacts(verification)
    refs, components = {}, []
    for node in graph:
        kind, _, rest = node.partition(":")
        if kind == "project":
            component = {
                "type": "library",
                "bom-ref": node,
                "group": "net.nulavio",
                "name": rest,
                "version": version_name,
                "licenses": MPL,
                "properties": [{"name": "nulavio:role", "value": f"module of this repository (android/{rest})"}],
            }
        else:
            if node not in artifacts:
                raise SystemExit(f"sbom: {node} has no jar or aar in {verification.name}; update the verification metadata")
            group, name, version = node.split(":")
            file_name, digest = artifacts[node]
            package = purl("maven", group, name, version, "?type=aar" if file_name.endswith(".aar") else "")
            component = {
                "type": "library",
                "bom-ref": package,
                "group": group,
                "name": name,
                "version": version,
                "purl": package,
                "hashes": [{"alg": "SHA-256", "content": digest}],
                "scope": "required",
                "properties": [{"name": "nulavio:artifact", "value": file_name}],
            }
        refs[node] = component["bom-ref"]
        components.append(component)
    app = {
        "type": "application",
        "bom-ref": f"app:{app_id}",
        "name": app_id,
        "version": version_name,
        "licenses": MPL,
        "properties": [
            {"name": "nulavio:android-version-code", "value": version_code},
            {"name": "nulavio:git-revision", "value": git_revision() or "uncommitted"},
        ],
    }
    if apk:
        app["hashes"] = [{"alg": "SHA-256", "content": sha256(apk)}]
        app["properties"].insert(0, {"name": "nulavio:package-file", "value": apk.name})
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'nulavio-companion:' + (git_revision() or version_name))}",
        "version": 1,
        "metadata": {"component": app},
        "components": components,
        "dependencies": [{"ref": app["bom-ref"], "dependsOn": [refs[node] for node in top]}]
        + [{"ref": refs[node], "dependsOn": [refs[child] for child in children]} for node, children in graph.items()],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", type=Path, help="describe this RPM or .deb instead of the preview")
    parser.add_argument("--engine-version", help="engine version inside the package")
    parser.add_argument("--companion", action="store_true", help="describe the Android Companion app instead")
    parser.add_argument("--gradle-dependencies", type=Path, help="with --companion: the Gradle report of releaseRuntimeClasspath")
    parser.add_argument("--apk", type=Path, help="with --companion: the APK this SBOM describes")
    args = parser.parse_args()
    if args.package and not args.engine_version:
        parser.error("--package needs --engine-version")
    if args.companion:
        if args.package or not args.gradle_dependencies:
            parser.error("--companion needs --gradle-dependencies and no --package")
        bom = companion_bom(args.gradle_dependencies.read_text(), VERIFICATION, APP_GRADLE, args.apk)
        json.dump(bom, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if args.gradle_dependencies or args.apk:
        parser.error("--gradle-dependencies and --apk need --companion")
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
        component["purl"] = purl("generic", "addons.mozilla.org", entry["key"], entry["version"])
        if entry["id"] in EXTENSION_CPE and (extension_cpe := cpe(EXTENSION_CPE[entry["id"]], entry["version"])):
            component["cpe"] = extension_cpe
        component["licenses"] = [{"license": {"id": license_id}}] if license_id else [{"license": {"name": entry["license"]}}]
        components.append(component)
    if args.package:
        components[0] = engine_built(args.engine_version)
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
    if args.package:
        bom["metadata"]["component"] = {
            "type": "application",
            "bom-ref": "nulavio-preview",
            "name": "nulavio",
            "version": args.engine_version,
            "licenses": [{"license": {"id": "MPL-2.0"}}],
            "hashes": [{"alg": "SHA-256", "content": sha256(args.package)}],
            "properties": [
                {"name": "nulavio:package-file", "value": args.package.name},
                {"name": "nulavio:git-revision", "value": git_revision() or "uncommitted"},
            ],
        }
    json.dump(bom, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
