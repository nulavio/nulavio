#!/usr/bin/env python3
"""Verify a Claude Code release manifest against Anthropic's pinned release key.

The AI review workflow (.github/workflows/ai-review.yml) downloads one Claude
Code binary and checks it against a SHA-256 pinned in the workflow. This script
gives that pin a signature: it downloads the small manifest.json and
manifest.json.sig, verifies the signature with the key kept in this repository
(keys/claude-code-release-signing.asc, never a key file from the same server;
every signature must be good and made by the pinned key, signatures.py), and
prints the binary's SHA-256 and size for one platform.

    python3 -I scripts/upstream/verify_claude_code_release.py 2.1.311
    python3 -I scripts/upstream/verify_claude_code_release.py 2.1.311 --platform linux-arm64

Pinned key: "Anthropic Claude Code Release Signing <security@anthropic.com>",
primary fingerprint 31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE
(published at https://code.claude.com/docs/en/setup and served at
https://downloads.claude.ai/keys/claude-code.asc; cross-checked 2026-10-27).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signatures

PINNED_PRIMARY = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
SIGNING_KEYS = frozenset({PINNED_PRIMARY})  # the manifest is signed by the primary key itself
KEY_FILE = signatures.KEYS / "claude-code-release-signing.asc"
RELEASES = "https://downloads.claude.ai/claude-code-releases/{version}/{name}"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PLATFORM_RE = re.compile(r"^[a-z0-9-]{3,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def fetch(url: str, dest: Path, limit: int = 1024 * 1024) -> None:
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise SystemExit(f"{url}: unexpectedly large")
    dest.write_bytes(data)


def verify_manifest(manifest: Path, signature: Path, key: Path, version: str, platform: str) -> tuple[str, int, str]:
    """Return (sha256, size, signing key) for the platform's binary in a signature-verified manifest."""
    if not VERSION_RE.match(version) or not PLATFORM_RE.match(platform):
        raise SystemExit("version must look like 2.1.311 and platform like linux-x64")
    try:
        signer = signatures.verify(manifest, signature, key, PINNED_PRIMARY, SIGNING_KEYS)
    except signatures.SignatureError as exc:
        raise SystemExit(f"signature verification FAILED: {exc}") from None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("version") != version:
        raise SystemExit(f"the manifest is for version {data.get('version')!r}, not {version}")
    entry = (data.get("platforms") or {}).get(platform) or {}
    digest, size = entry.get("checksum"), entry.get("size")
    if not isinstance(digest, str) or not SHA256_RE.match(digest) or not isinstance(size, int) or size <= 0:
        raise SystemExit(f"{platform}: no valid checksum and size in the manifest")
    return digest, size, signer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    parser.add_argument("--platform", default="linux-x64")
    args = parser.parse_args(argv)
    if not VERSION_RE.match(args.version) or not PLATFORM_RE.match(args.platform):
        raise SystemExit("version must look like 2.1.311 and platform like linux-x64")
    with tempfile.TemporaryDirectory(prefix="nulavio-claude-code-") as tmp:
        work = Path(tmp)
        for name in ("manifest.json", "manifest.json.sig"):
            fetch(RELEASES.format(version=args.version, name=name), work / name)
        manifest, signature = work / "manifest.json", work / "manifest.json.sig"
        digest, size, key = verify_manifest(manifest, signature, KEY_FILE, args.version, args.platform)
    print(f"OK  manifest signed by {PINNED_PRIMARY} (signing key {key})")
    print(f"{digest}  {args.platform}/claude ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
