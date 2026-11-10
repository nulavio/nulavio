#!/usr/bin/env python3
"""Check a rehearsal's manifest.json before anything is signed or published.

    python3 -I scripts/release/release_manifest.py verify <rehearsal-out> [--repo DIR] [--on REF]
    python3 -I scripts/release/release_manifest.py packages <manifest.json> <packages-dir>
    python3 -I scripts/release/release_manifest.py next-release <firefox-version> [--repo DIR]

``verify`` refuses a rehearsal that is not fit to publish: not finished, built
from a tree with uncommitted or untracked changes, an engine pin that differs
from the source it built, a listed file missing or with another SHA-256, a base
commit that is not on ``--on`` (default origin/main). On success it prints JSON:
the release tag (``v<version>-<release>`` from the RPM), the RPMs, the SBOMs.

``packages`` refuses a packages directory holding any Nulavio RPM or .deb that
the manifest does not list with the same SHA-256. sign_repo.sh runs it when
NULAVIO_RELEASE_MANIFEST is set, so only what the rehearsal checked is signed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EMPTY_DIFF = hashlib.sha256(b"").hexdigest()
RPM = re.compile(r"^nulavio-(?P<version>\d+(?:\.\d+)+)-(?P<release>[0-9.]+)\.[a-z0-9_]+\.x86_64\.rpm$")


class ManifestError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def load(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ManifestError(f"{path}: cannot read the manifest ({e})") from None
    for key in ("firefox", "source_sha256", "engine_json", "nulavio_base_commit", "worktree_diff_sha256",
                "untracked", "packages", "sboms", "rehearsal"):  # fmt: skip
        if key not in manifest:
            raise ManifestError(f"{path}: no {key!r}: not a complete rehearsal manifest")
    return manifest


def check_tree(manifest: dict) -> None:
    if manifest["rehearsal"] != "ok":
        raise ManifestError("the rehearsal did not finish")
    if manifest["worktree_diff_sha256"] != EMPTY_DIFF:
        raise ManifestError("built from a tree with uncommitted changes: commit them and rehearse again")
    if manifest["untracked"]:
        raise ManifestError(f"built with untracked files: {manifest['untracked'][:3]}")
    engine = manifest["engine_json"]
    if engine.get("firefox") != manifest["firefox"] or engine.get("source_sha256") != manifest["source_sha256"]:
        raise ManifestError("engine.json does not pin the Firefox source this rehearsal built")


def check_files(manifest: dict, out: Path) -> None:
    for entry in [*manifest["packages"], *manifest["sboms"]]:
        path = out / entry["file"]
        if not path.is_file():
            raise ManifestError(f"{entry['file']} is listed but missing")
        if sha256(path) != entry["sha256"]:
            raise ManifestError(f"{entry['file']} changed since the rehearsal (SHA-256 differs)")


def check_base(commit: str, repo: Path, ref: str) -> None:
    result = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, ref], capture_output=True)
    if result.returncode != 0:
        raise ManifestError(f"base commit {commit[:12]} is not on {ref}: publish only from reviewed history")


def tag(manifest: dict) -> tuple[str, list[str]]:
    rpms = [e["file"] for e in manifest["packages"] if e["file"].endswith(".rpm")]
    if not rpms:
        raise ManifestError("the manifest lists no RPM")
    versions = set()
    for name in rpms:
        match = RPM.match(Path(name).name)
        if not match:
            raise ManifestError(f"{name}: not a Nulavio RPM file name")
        if match["version"] != manifest["firefox"]:
            raise ManifestError(f"{name}: version {match['version']} is not Firefox {manifest['firefox']}")
        versions.add(f"v{match['version']}-{match['release']}")
    if len(versions) != 1:
        raise ManifestError(f"the RPMs carry different versions: {sorted(versions)}")
    return versions.pop(), rpms


def _numbers(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def published(repo: Path) -> tuple[str, str] | None:
    """The (Firefox version, package release) of the published release, if any."""
    try:
        data = json.loads((repo / "packaging" / "release.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise ManifestError(f"cannot read packaging/release.json ({e})") from None
    version = data.get("version")
    if not version:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)+)-([0-9]+(?:\.[0-9]+)*)", version)
    if not match:
        raise ManifestError(f"packaging/release.json: version {version!r} is not <firefox>-<release>")
    return match[1], match[2]


def check_newer(release_tag: str, repo: Path) -> None:
    version, _, release = release_tag[1:].partition("-")
    current = published(repo)
    if current and (_numbers(version), _numbers(release)) <= (_numbers(current[0]), _numbers(current[1])):
        raise ManifestError(
            f"{release_tag} is not newer than the published {current[0]}-{current[1]}: dnf would not upgrade "
            "to it; rebuild with a higher NULAVIO_RELEASE"
        )
    exists = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/tags/{release_tag}"],
                            capture_output=True)  # fmt: skip
    if exists.returncode == 0:
        raise ManifestError(f"the tag {release_tag} already exists")


def next_release(firefox: str, repo: Path) -> str:
    current = published(repo)
    if not current or current[0] != firefox:
        return "0.1"
    parts = list(_numbers(current[1]))
    parts[-1] += 1
    return ".".join(map(str, parts))


def verify(out: Path, repo: Path, ref: str) -> dict:
    manifest = load(out / "manifest.json")
    check_tree(manifest)
    check_files(manifest, out)
    check_base(manifest["nulavio_base_commit"], repo, ref)
    release_tag, rpms = tag(manifest)
    check_newer(release_tag, repo)
    return {
        "tag": release_tag,
        "firefox": manifest["firefox"],
        "commit": manifest["nulavio_base_commit"],
        "rpms": rpms,
        "sboms": [e["file"] for e in manifest["sboms"]],
    }


def check_packages(manifest_path: Path, packages: Path) -> list[str]:
    manifest = load(manifest_path)
    listed = {e["sha256"] for e in manifest["packages"]}
    found = sorted([*packages.rglob("nulavio-*.rpm"), *packages.rglob("nulavio_*.deb")])
    if not found:
        raise ManifestError(f"{packages}: no Nulavio packages")
    extra = [str(p.relative_to(packages)) for p in found if sha256(p) not in listed]
    if extra:
        raise ManifestError(f"not in the manifest (or changed since): {extra}")
    return [str(p.relative_to(packages)) for p in found]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify", help="a rehearsal output directory is fit to sign and publish")
    v.add_argument("out", type=Path)
    v.add_argument("--repo", type=Path, default=ROOT)
    v.add_argument("--on", default="origin/main", help="the base commit must be an ancestor of this ref")
    p = sub.add_parser("packages", help="every package in a directory is listed in the manifest")
    p.add_argument("manifest", type=Path)
    p.add_argument("packages", type=Path)
    n = sub.add_parser("next-release", help="the package release to build for a Firefox version")
    n.add_argument("firefox")
    n.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            print(json.dumps(verify(args.out, args.repo, args.on), indent=2))
        elif args.command == "next-release":
            print(next_release(args.firefox, args.repo))
        else:
            print("\n".join(check_packages(args.manifest, args.packages)))
    except ManifestError as e:
        print(f"release_manifest: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
