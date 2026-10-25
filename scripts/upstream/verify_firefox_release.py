#!/usr/bin/env python3
"""Verify a Firefox release's checksums against Mozilla's pinned release key.

Track B (source build) starts from the official source tarball. This script
downloads only the small SHA256SUMS, SHA256SUMS.asc and KEY files, verifies
the signature in a throwaway GnuPG home, checks that the signing key's
*primary fingerprint* equals the pinned one (so a swapped KEY file on the
server cannot pass), and prints the expected SHA-256 of the source tarball.

    python3 -I scripts/upstream/verify_firefox_release.py 158.0.1

Pinned key: "Mozilla Software Releases <release@mozilla.com>",
primary fingerprint 14F2 6682 D091 6CDD 81E3 7B6D 61B7 B526 D98F 0353
(cross-checked on 2026-10-24; see docs/architecture/update-policy.md).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

PINNED_PRIMARY = "14F26682D0916CDD81E37B6D61B7B526D98F0353"
BASE = "https://archive.mozilla.org/pub/firefox/releases/{version}/{name}"
VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?(esr)?$")


def fetch(url: str, dest: Path, limit: int = 4 * 1024 * 1024) -> None:
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise SystemExit(f"{url}: unexpectedly large")
    dest.write_bytes(data)


def signed_source_digest(version: str) -> tuple[str, str]:
    """Return (sha256, signing subkey) of the source tarball listed in a verified SHA256SUMS."""
    if not VERSION_RE.match(version):
        raise SystemExit("version must look like 158.0.1 or 140.4.0esr")
    with tempfile.TemporaryDirectory(prefix="nulavio-verify-") as tmp:
        work = Path(tmp)
        for name in ("KEY", "SHA256SUMS", "SHA256SUMS.asc"):
            fetch(BASE.format(version=version, name=name), work / name)
        gnupg = work / "gnupg"
        gnupg.mkdir(mode=0o700)
        env = {**os.environ, "GNUPGHOME": str(gnupg), "LC_ALL": "C"}
        subprocess.run(
            ["gpg", "--batch", "--quiet", "--import", str(work / "KEY")],
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        status = subprocess.run(
            ["gpg", "--batch", "--status-fd", "1", "--verify", str(work / "SHA256SUMS.asc"), str(work / "SHA256SUMS")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        valid = [line.split() for line in status.splitlines() if line.startswith("[GNUPG:] VALIDSIG")]
        if "[GNUPG:] GOODSIG" not in status or not valid:
            raise SystemExit("signature verification FAILED")
        primary = valid[0][-1]
        if primary != PINNED_PRIMARY:
            raise SystemExit(f"signed by unexpected primary key {primary}")
        wanted = f"source/firefox-{version}.source.tar.xz"
        for line in (work / "SHA256SUMS").read_text().splitlines():
            digest, _, name = line.partition("  ")
            if name == wanted:
                return digest, valid[0][2]
    raise SystemExit(f"{wanted} not listed in SHA256SUMS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    args = parser.parse_args()
    digest, subkey = signed_source_digest(args.version)
    print(f"OK  signature by {PINNED_PRIMARY} (subkey {subkey})")
    print(f"{digest}  source/firefox-{args.version}.source.tar.xz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
