#!/usr/bin/env python3
"""Apply browser/patches/series to a Firefox source tree, idempotently.

A patch already applied (its reverse applies cleanly) is skipped; a patch
that applies neither way stops the build, which is the signal to rebase it.

    python3 -I scripts/build/apply_patches.py --source ~/.cache/nulavio-build/firefox-158.0.1
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCHES = ROOT / "browser" / "patches"


def patch(source: Path, patch_file: Path, *extra: str) -> bool:
    # `git apply` works on plain directories (no repository needed) and refuses
    # patches that touch paths outside the tree.
    result = subprocess.run(
        ["git", "apply", "-p1", *extra, str(patch_file.resolve())],
        cwd=source,
        env={"GIT_DIR": "/nonexistent", "PATH": "/usr/bin:/bin", "HOME": str(source)},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def series() -> list[Path]:
    names = []
    for line in (PATCHES / "series").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.append(PATCHES / line)
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    for patch_file in series():
        if patch(args.source, patch_file, "--reverse", "--check"):
            print(f"= {patch_file.name} (already applied)")
        elif patch(args.source, patch_file, "--check") and patch(args.source, patch_file):
            print(f"+ {patch_file.name}")
        else:
            raise SystemExit(f"! {patch_file.name} does not apply: rebase it on this source release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
