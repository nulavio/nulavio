#!/usr/bin/env python3
"""The Companion's version moves with the app between releases (#286).

    python3 -I scripts/release/companion_version.py [--repo DIR] [--ref REF]

Two releases must not attach `nulavio-companion-<versionName>.apk` with
different bytes and the same name, nor the same `versionCode`: Android refuses
the update, and people take one build for the other. So, against the newest
release tag (`v<firefox>-<release>`) that shipped the APK (its tree has
build_companion.sh, which the release job runs since #281) and is not on the
commit being built:

- when what goes into the APK changed under android/ (anything but `*.md`,
  tests under `src/test/` and the F-Droid metadata), `versionCode` must be
  higher and `versionName` different;
- `versionCode` never goes down.

With no such tag (a fresh clone without tags, the first release with the APK),
there is nothing to compare and the check passes. build_companion.sh runs it
before it builds; the release job fetches the tags for it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_manifest import RELEASE_TAG, _numbers  # noqa: E402

GRADLE = "android/app/build.gradle.kts"
# What changes the APK: android/, without these.
IGNORED = (":(glob,exclude)android/**/*.md", ":(glob,exclude)android/**/src/test/**", ":(glob,exclude)android/fdroid/**")


class VersionError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def version(text: str, where: str) -> tuple[int, str]:
    code = re.search(r"^\s*versionCode\s*=\s*([0-9]+)\s*$", text, re.M)
    name = re.search(r'^\s*versionName\s*=\s*"([0-9]+(?:\.[0-9]+)+)"\s*$', text, re.M)
    if not code or not name:
        raise VersionError(f"no versionCode and versionName in {GRADLE} at {where}")
    return int(code[1]), name[1]


def previous_release(repo: Path, ref: str) -> str | None:
    """The newest release tag by version that shipped the APK and is not on `ref`'s commit (a rerun)."""
    head = git(repo, "rev-parse", f"{ref}^{{commit}}").stdout.strip()
    tags = []
    for tag in git(repo, "tag", "--list", "v*").stdout.split():
        match = RELEASE_TAG.fullmatch(tag)
        shipped = git(repo, "cat-file", "-e", f"{tag}:scripts/release/build_companion.sh", check=False).returncode == 0
        if match and shipped and git(repo, "rev-parse", f"{tag}^{{commit}}").stdout.strip() != head:
            tags.append((_numbers(match[1]), _numbers(match[2]), tag))
    return max(tags)[2] if tags else None


def check(repo: Path, ref: str = "HEAD") -> str:
    now = version(git(repo, "show", f"{ref}:{GRADLE}").stdout, ref)
    tag = previous_release(repo, ref)
    if tag is None:
        return f"no earlier release shipped the Companion: it is {now[1]} ({now[0]})"
    before = version(git(repo, "show", f"{tag}:{GRADLE}").stdout, tag)
    if now[0] < before[0]:
        raise VersionError(f"versionCode went down from {before[0]} ({tag}) to {now[0]}")
    changed = git(repo, "diff", "--quiet", tag, ref, "--", "android", *IGNORED, check=False).returncode != 0
    if changed and (now[0] == before[0] or now[1] == before[1]):
        raise VersionError(
            f"android/ changed since {tag}, which shipped the Companion {before[1]} ({before[0]}), and the version "
            f"did not: raise versionCode and change versionName in {GRADLE}"
        )
    return f"the Companion is {now[1]} ({now[0]}); {tag} had {before[1]} ({before[0]})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--ref", default="HEAD")
    args = parser.parse_args(argv)
    try:
        print(check(args.repo, args.ref))
    except VersionError as exc:
        print(f"companion_version: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
