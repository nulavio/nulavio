#!/usr/bin/env python3
"""Download, verify and extract an official Firefox source release (Track B).

The expected SHA-256 comes from Mozilla's SHA256SUMS, whose signature is
checked against the pinned release key (verify_firefox_release.py). When
browser/build/engine.json pins this version, its reviewed "source_sha256" must
be that same digest, or nothing is downloaded. The tarball is hashed while
streaming and extracted only if it matches.

    python3 -I scripts/upstream/fetch_firefox_source.py 158.0.1 --dest ~/.cache/nulavio-build
    -> <dest>/firefox-158.0.1/ (source tree)  and  <dest>/downloads/<tarball>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_firefox_release import signed_source_digest

URL = "https://archive.mozilla.org/pub/firefox/releases/{v}/source/firefox-{v}.source.tar.xz"
CHUNK = 1 << 20
ENGINE = Path(__file__).resolve().parents[2] / "browser" / "build" / "engine.json"


def check_pin(version: str, signed: str, engine: Path = ENGINE) -> None:
    """When engine.json pins `version`, its reviewed digest must equal the one Mozilla signed."""
    pin = json.loads(engine.read_text(encoding="utf-8"))
    if pin.get("firefox") == version and "source_sha256" in pin and pin["source_sha256"] != signed:
        raise SystemExit(
            f"engine.json pin differs from Mozilla's signed SHA256SUMS: refusing (pinned {pin['source_sha256']}, signed {signed})"
        )


def download(url: str, target: Path) -> str:
    digest = hashlib.sha256()
    partial = target.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=120) as response, open(partial, "wb") as out:
        for chunk in iter(lambda: response.read(CHUNK), b""):
            digest.update(chunk)
            out.write(chunk)
    partial.replace(target)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    expected, subkey = signed_source_digest(args.version)
    print(f"signed SHA-256 (subkey {subkey}): {expected}")
    check_pin(args.version, expected)
    downloads = args.dest / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    tarball = downloads / f"firefox-{args.version}.source.tar.xz"
    actual = sha256_file(tarball) if tarball.exists() else download(URL.format(v=args.version), tarball)
    if actual != expected:
        tarball.unlink(missing_ok=True)
        raise SystemExit(f"SHA-256 mismatch: got {actual}")
    print(f"verified {tarball}")
    tree = args.dest / f"firefox-{args.version}"
    if tree.exists():
        print(f"source tree already present: {tree}")
        return 0
    staging = args.dest / f".extract-{args.version}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    # --no-same-owner/--no-same-permissions: never trust archive ownership/modes.
    subprocess.run(["tar", "-xJf", str(tarball), "-C", str(staging), "--no-same-owner", "--no-same-permissions"], check=True)
    (extracted,) = list(staging.iterdir())
    extracted.replace(tree)
    staging.rmdir()
    print(f"extracted to {tree}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
