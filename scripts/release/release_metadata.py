#!/usr/bin/env python3
"""Update published download metadata, CHANGELOG.md and the READMEs' status; never publish or approve a release."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_manifest

ROOT = Path(__file__).resolve().parents[2]
TAG = re.compile(r"v([0-9]+(?:\.[0-9]+)+)-([0-9]+(?:\.[0-9]+)*)")
# The READMEs' status names the latest release between these markers (#857).
READMES = ("README.md", "README.pt-BR.md")
# Matched as bytes, across line breaks: a README is never decoded, and a wrapped link is still one pair.
README_RELEASE = re.compile(rb"<!--release-->.*?<!--/release-->", re.S)


def version_key(version: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    match = TAG.fullmatch("v" + version)
    if not match:
        raise ValueError("invalid Nulavio release version")
    return tuple(int(n) for n in match[1].split(".")), tuple(int(n) for n in match[2].split("."))


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def replace(path: Path, data: bytes) -> None:
    """Write beside the file and rename over it: an interrupted write leaves the old file whole, with its mode."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


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
    # No Flatpak bundle on the download pages until Flathub (#467): it never updated itself (R75). A bundle among an
    # older release's assets is not offered either.
    metadata.pop("flatpak_bundle", None)
    # The download pages offer the Companion from the first release that carries its signed APK
    # (ADR 0014); publish_release.sh refuses a release that offers pairing without it.
    companion = sorted(a for a in assets if a and re.fullmatch(r"nulavio-companion-[0-9]+(?:\.[0-9]+)+\.apk", a))
    if companion:
        metadata["companion_apk"] = companion[-1]
    serialized = json.dumps(metadata, indent=2, ensure_ascii=False) + "\n"
    # Built only from the checked tag and URL; a README without the markers is left as it is.
    link = f"<!--release-->[{tag}]({url})<!--/release-->".encode()
    outputs = {
        metadata_path: (metadata_path.read_text(encoding="utf-8"), serialized),
        changelog_path: (changelog_path.read_text(encoding="utf-8"), changelog),
    }
    for name in READMES:
        path = repo / name
        if path.is_symlink() or path.is_file():
            # Bytes, so the README keeps its line endings outside the markers.
            text = path.read_bytes()
            outputs[path] = (text, README_RELEASE.sub(lambda _: link, text))
    # A link would have its target rewritten, outside the paths the workflow stages: refused before any write.
    for path in outputs:
        if path.is_symlink():
            raise ValueError(f"{path.relative_to(repo)} is a symbolic link")
    # Only the files that differ are written: a README-only repair leaves the metadata and the changelog alone.
    changed = [(path, new) for path, (old, new) in outputs.items() if old != new]
    for path, new in changed:
        replace(path, new if isinstance(new, bytes) else new.encode("utf-8"))
    return bool(changed)


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
