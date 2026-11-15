#!/usr/bin/env python3
"""A published release and the one before it, for scripts/perf/run.py to compare (#80, perf.yml).

    python3 -I scripts/perf/fetch_releases.py [<tag>] <dir>

For each of the two (the given tag, or the latest published release, and the published release before it): the
portable archive, SHA256SUMS and SHA256SUMS.asc from the GitHub release (gh), the signature checked with
site/keys/nulavio-packages.asc and its primary key's fingerprint required to be the release key's, the archive's
SHA-256 required to be its line in SHA256SUMS, then unpacked into <dir>/new or <dir>/previous (the engine is
<dir>/<side>/nulavio/nulavio). Draft releases are never measured. Prints the two tags.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY = ROOT / "site" / "keys" / "nulavio-packages.asc"
FINGERPRINT = "298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1"  # the release key (release.yml, publish_release.sh)


class FetchError(RuntimeError):
    pass


# -- pure (tests/unit/test_perf_fetch_releases.py) ---------------------------------------------------


def pair(releases: list[dict], tag: str | None) -> tuple[str, str]:
    """(the release to measure, the published release before it) from `gh release list --json` rows, newest first."""
    published = [r["tagName"] for r in releases if not r.get("isDraft")]
    if tag is None:
        if not published:
            raise FetchError("no published release")
        tag = published[0]
    if tag not in published:
        raise FetchError(f"{tag} is not a published release")
    index = published.index(tag)
    if index + 1 >= len(published):
        raise FetchError(f"{tag} has no published release before it")
    return tag, published[index + 1]


def signer(status: str) -> str | None:
    """The primary key fingerprint of a good signature, from gpg's --status-fd output (VALIDSIG's last field)."""
    for line in status.splitlines():
        fields = line.split()
        if fields[:2] == ["[GNUPG:]", "VALIDSIG"] and len(fields) >= 12:
            return fields[-1]
    return None


def listed(sums: str, name: str) -> str | None:
    """The SHA-256 SHA256SUMS lists for `name`, or None."""
    for line in sums.splitlines():
        digest, _, listed_name = line.partition("  ")
        if listed_name.strip().lstrip("*") == name:
            return digest.strip()
    return None


# -- fetching ----------------------------------------------------------------------------------------


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def fetch(tag: str, target: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="nulavio-release-") as work:
        files = Path(work)
        repo = os.environ.get("GITHUB_REPOSITORY", "nulavio/nulavio")
        version = tag.removeprefix("v")
        archive = f"nulavio-{version}.linux-x86_64.tar.xz"
        for name in (archive, "SHA256SUMS", "SHA256SUMS.asc"):
            gh("release", "download", tag, "--repo", repo, "--pattern", name, "--dir", str(files))
        home = files / "gnupg"
        home.mkdir(mode=0o700)
        env = {**os.environ, "GNUPGHOME": str(home)}
        subprocess.run(["gpg", "--batch", "--quiet", "--import", str(KEY)], check=True, env=env, capture_output=True)
        verified = subprocess.run(
            ["gpg", "--batch", "--status-fd", "1", "--verify", str(files / "SHA256SUMS.asc"), str(files / "SHA256SUMS")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if verified.returncode != 0 or signer(verified.stdout) != FINGERPRINT:
            raise FetchError(f"{tag}: SHA256SUMS is not signed by the release key")
        want = listed((files / "SHA256SUMS").read_text(encoding="utf-8"), archive)
        if want is None or hashlib.sha256((files / archive).read_bytes()).hexdigest() != want:
            raise FetchError(f"{tag}: {archive} is not the one SHA256SUMS lists")
        target.mkdir(parents=True)
        with tarfile.open(files / archive) as tar:
            tar.extractall(target, filter="data")


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    tag, out = (argv[1] or None, Path(argv[2])) if len(argv) == 3 else (None, Path(argv[1]))
    releases = json.loads(gh("release", "list", "--repo", os.environ.get("GITHUB_REPOSITORY", "nulavio/nulavio"),
                             "--limit", "50", "--json", "tagName,isDraft"))  # fmt: skip
    new, previous = pair(releases, tag)
    for side, each in (("new", new), ("previous", previous)):
        fetch(each, out / side)
    print(new, previous)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
