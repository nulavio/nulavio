#!/usr/bin/env python3
"""Verify a Firefox release's checksums against Mozilla's pinned release key.

Track B (source build) starts from the official source tarball. This script
downloads only the small SHA256SUMS and SHA256SUMS.asc files and verifies the
signature with the key kept in this repository (keys/mozilla-release-signing.asc,
never the KEY file next to the release, which the same server serves). Every
signature must be good and made by a pinned signing subkey of the pinned
primary key; an expired or revoked subkey fails (signatures.py). It prints the
expected SHA-256 of the source tarball.

    python3 -I scripts/upstream/verify_firefox_release.py 158.0.1

Pinned key: "Mozilla Software Releases <release@mozilla.com>",
primary fingerprint 14F2 6682 D091 6CDD 81E3 7B6D 61B7 B526 D98F 0353
(cross-checked on 2026-10-24; see docs/architecture/update-policy.md), signing
subkey 827E 6586 0867 9618 CD34 9F93 678E 455D 7676 7AA3 (keys/README.md).
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signatures

PINNED_PRIMARY = "14F26682D0916CDD81E37B6D61B7B526D98F0353"
# Mozilla's signing subkeys this repository trusts; a new one needs review (keys/README.md).
SIGNING_SUBKEYS = frozenset({"827E658608679618CD349F93678E455D76767AA3"})
KEY_FILE = signatures.KEYS / "mozilla-release-signing.asc"
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
        for name in ("SHA256SUMS", "SHA256SUMS.asc"):
            fetch(BASE.format(version=version, name=name), work / name)
        try:
            subkey = signatures.verify(work / "SHA256SUMS", work / "SHA256SUMS.asc", KEY_FILE, PINNED_PRIMARY, SIGNING_SUBKEYS)
        except signatures.SignatureError as exc:
            raise SystemExit(f"signature verification FAILED: {exc}") from None
        wanted = f"source/firefox-{version}.source.tar.xz"
        for line in (work / "SHA256SUMS").read_text().splitlines():
            digest, _, name = line.partition("  ")
            if name == wanted:
                return digest, subkey
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
