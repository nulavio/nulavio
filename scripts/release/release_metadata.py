#!/usr/bin/env python3
"""Update published download metadata and CHANGELOG.md; never publish or approve a release."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_manifest

ROOT = Path(__file__).resolve().parents[2]
TAG = re.compile(r"v([0-9]+(?:\.[0-9]+)+)-([0-9]+(?:\.[0-9]+)*)")


def version_key(version: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    match = TAG.fullmatch("v" + version)
    if not match:
        raise ValueError("invalid Nulavio release version")
    return tuple(int(n) for n in match[1].split(".")), tuple(int(n) for n in match[2].split("."))


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def update(repo: Path, release: dict, repository: str, manifest: dict) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid GitHub repository")
    tag = release["tag_name"]
    commit = manifest["nulavio_base_commit"]
    match = TAG.fullmatch(tag)
    if not match or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid release tag or verified commit")
    manifest_tag, _rpms = release_manifest.tag(manifest)
    if manifest_tag != tag:
        raise ValueError("published release revision differs from the attested manifest packages")
    if release["draft"] is not False or not release.get("published_at"):
        raise ValueError("release is not published")
    published = dt.datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
    if published.tzinfo is None:
        raise ValueError("publication timestamp needs a timezone")
    url = f"https://github.com/{repository}/releases/tag/{tag}"
    if release["html_url"] != url:
        raise ValueError("release URL does not match repository and tag")
    body = release.get("body")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("published release has no notes")
    target = git(repo, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if target != commit:
        raise ValueError("release tag differs from the attested build commit")
    git(repo, "merge-base", "--is-ancestor", target, "HEAD")
    engine = json.loads(git(repo, "show", f"{target}:browser/build/engine.json"))
    if engine["firefox"] != match[1]:
        raise ValueError("release tag differs from the built Firefox pin")
    metadata_path = repo / "packaging/release.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    version = tag[1:]
    if metadata.get("version") and version_key(metadata["version"]) > version_key(version):
        print("Older release: current download metadata is newer; no changes.")
        return False
    # A stable channel is a maintainer decision, not a side effect of publishing an event.
    if release.get("prerelease") is not True and metadata.get("channel") == "alpha":
        raise ValueError("stable release requires an explicit channel change first")
    changelog_path = repo / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8")
    marker = f"<!-- release:{tag} -->"
    if marker not in changelog:
        anchor = "<!-- releases -->"
        if anchor not in changelog:
            raise ValueError("CHANGELOG.md has no releases insertion marker")
        # Public notes are copied as text, never evaluated as a template or a shell command.
        notes = re.sub(r"(?m)^(#{1,5}) ", r"\1# ", body.strip())
        entry = f"{marker}\n## [{version}]({url}) — {published.date()}\n\n{notes}\n"
        changelog = changelog.replace(anchor, f"{anchor}\n\n{entry}", 1)
    metadata["version"] = version
    # The download pages show Ubuntu from the first release published with the APT repository on.
    # Every rehearsal lists a .deb, also those of releases published before the APT repository
    # existed: what tells them apart is the .deb among the release's assets, which only the
    # publish_release.sh that signs the APT repository uploads. It refuses a release without its
    # .deb, so every release after that one has both.
    assets = {a.get("name") for a in release.get("assets") or [] if isinstance(a, dict)}
    if f"nulavio_{version}_amd64.deb" in assets and release_manifest.debs(manifest, manifest_tag):
        metadata["apt_sources"] = "https://nulavio.net/apt/nulavio.sources"
    serialized = json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    changed = serialized != metadata_path.read_text(encoding="utf-8") or changelog != changelog_path.read_text(encoding="utf-8")
    if changed:
        metadata_path.write_text(serialized, encoding="utf-8")
        changelog_path.write_text(changelog, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--event", type=Path, required=True, help="JSON with a release object")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--manifest", type=Path, required=True, help="manifest whose build-provenance attestation was verified")
    args = parser.parse_args()
    try:
        changed = update(
            args.repo, json.loads(args.event.read_text())["release"], args.repository, json.loads(args.manifest.read_text())
        )
        print("Published metadata updated." if changed else "No metadata changes.")
    except (ValueError, OSError, KeyError, TypeError, release_manifest.ManifestError, subprocess.CalledProcessError) as error:
        print(f"release_metadata: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
