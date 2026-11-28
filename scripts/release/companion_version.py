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

With no such tag (a clone without tags, the first release with the APK),
there is nothing to compare and the check passes; a shallow clone is refused,
since it would pass blind. build_companion.sh runs it
before it builds; the release job fetches the tags for it.

    python3 -I scripts/release/companion_version.py --changed-since BASE

checks only when what goes into the APK changed between BASE and `--ref` (from
their merge base, as a pull request's diff), and passes otherwise: ci.yml's
Companion job runs it on every pull request with the base branch's commit, so a
change to android/ that needs a new version fails before it merges, not in the
release run (#906), and a pull request that leaves the app alone is never held
up by one. A base, or a `--ref`, that is not a commit, or a range git cannot
compare (no merge base), is refused, never taken as a change or as none. CI
does not run again when a pull request only changes its base (no `edited`
trigger, so a body edit does not restart it): the release run's refusal stays
the backstop.
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


def commit(repo: Path, rev: str, what: str) -> str:
    """`rev`'s commit id, or a VersionError: an empty or unknown one, or one that git would read as an option."""
    refused = VersionError(f"the {what} {rev!r} is not a commit in this clone")
    if not rev or rev.startswith("-"):
        raise refused
    found = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
    if found.returncode != 0:
        raise refused
    return found.stdout.strip()


def apk_changed(repo: Path, *revs: str) -> bool:
    """Whether what goes into the APK differs between `revs` (two commits, or `A...B`: from their merge base to B)."""
    diff = git(repo, "diff", "--quiet", *revs, "--", "android", *IGNORED, check=False)
    if diff.returncode not in (0, 1):
        # An error (no merge base, a missing object) is no answer either way, not a change.
        raise VersionError(f"git diff failed for {' '.join(revs)}: {diff.stderr.strip()}")
    return diff.returncode == 1


def check(repo: Path, ref: str = "HEAD", since: str | None = None) -> str:
    if git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        # A shallow clone has no tags to compare with, and passing then would be passing blind.
        raise VersionError("this is a shallow clone: fetch the whole history and the tags (fetch-depth: 0) first")
    # Both resolved first: `--ref=` would make the range `BASE...`, which git reads as `BASE...HEAD`.
    head = commit(repo, ref, "ref")
    if since is not None and not apk_changed(repo, f"{commit(repo, since, 'base')}...{head}"):
        return f"android/ did not change since {since}: no new Companion version needed"
    now = version(git(repo, "show", f"{head}:{GRADLE}").stdout, ref)
    tag = previous_release(repo, head)
    if tag is None:
        return f"no earlier release shipped the Companion: it is {now[1]} ({now[0]})"
    before = version(git(repo, "show", f"{tag}:{GRADLE}").stdout, tag)
    if now[0] < before[0]:
        raise VersionError(f"versionCode went down from {before[0]} ({tag}) to {now[0]}")
    if apk_changed(repo, tag, head) and (now[0] == before[0] or now[1] == before[1]):
        raise VersionError(
            f"android/ changed since {tag}, which shipped the Companion {before[1]} ({before[0]}), and the version "
            f"did not: raise versionCode and change versionName in {GRADLE}"
        )
    return f"the Companion is {now[1]} ({now[0]}); {tag} had {before[1]} ({before[0]})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--changed-since", metavar="BASE", help="check only if the APK's files changed since BASE")
    args = parser.parse_args(argv)
    try:
        print(check(args.repo, args.ref, args.changed_since))
    except VersionError as exc:
        print(f"companion_version: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
