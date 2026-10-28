#!/usr/bin/env python3
"""Download, verify and extract an official Firefox source release (Track B).

The expected SHA-256 comes from Mozilla's SHA256SUMS, whose signature is
checked against the pinned release key (verify_firefox_release.py). When
browser/build/engine.json pins this version, its reviewed "source_sha256" must
be that same digest, or nothing is downloaded. The tarball is hashed while
streaming and extracted only if it matches; a cached tarball that does not match
is downloaded again. The source tree records the digest it was extracted from
(<tree>/.nulavio-source-sha256, written before the tree appears) and is reused
only when that is the digest Mozilla signs now; otherwise it is moved aside to
<dest>/firefox-<v>.stale-*/ (with anything built in it; never deleted) and
extracted again.

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
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_firefox_release import signed_source_digest

URL = "https://archive.mozilla.org/pub/firefox/releases/{v}/source/firefox-{v}.source.tar.xz"
CHUNK = 1 << 20
ENGINE = Path(__file__).resolve().parents[2] / "browser" / "build" / "engine.json"
MARKER = ".nulavio-source-sha256"  # in the source tree: the verified tarball digest it was extracted from


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


def tree_digest(tree: Path) -> str | None:
    """The tarball digest `tree` was extracted from (None when unknown)."""
    try:
        return (tree / MARKER).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None


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
    actual = sha256_file(tarball) if tarball.exists() else None
    if actual != expected:
        if actual is not None:
            print(f"cached {tarball.name} is not the signed one ({actual}): downloading again")
        actual = download(URL.format(v=args.version), tarball)
    if actual != expected:
        tarball.unlink(missing_ok=True)
        raise SystemExit(f"SHA-256 mismatch: got {actual}")
    print(f"verified {tarball}")
    tree = args.dest / f"firefox-{args.version}"
    if tree.exists():
        if tree_digest(tree) == expected:
            print(f"source tree already present: {tree}")
            return 0
        # Extracted from another tarball (or nobody knows): never build on it. Kept for you to delete.
        aside = Path(tempfile.mkdtemp(prefix=f"firefox-{args.version}.stale-", dir=args.dest)) / tree.name
        tree.replace(aside)
        print(f"source tree was not extracted from {expected}: moved to {aside} (delete it when done); extracting again")
    staging = args.dest / f".extract-{args.version}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    # --no-same-owner/--no-same-permissions: never trust archive ownership/modes.
    subprocess.run(["tar", "-xJf", str(tarball), "-C", str(staging), "--no-same-owner", "--no-same-permissions"], check=True)
    (extracted,) = list(staging.iterdir())
    (extracted / MARKER).write_text(expected + "\n", encoding="ascii")  # before the tree appears under its name
    extracted.replace(tree)
    staging.rmdir()
    print(f"extracted to {tree}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
