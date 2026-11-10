#!/usr/bin/env python3
"""Apply browser/patches/series to a Firefox source tree, idempotently.

A source tree that already has the head of the series (from an earlier build)
keeps it, and only the rest is applied. A patch that applies neither way stops
the build, which is the signal to rebase it.

Whether patches are already applied is checked as a stack: the series is
reversed for real, last patch first, on a scratch copy of the files it touches.
Checking each patch on its own fails when two patches change neighbouring
lines of one file (0001 and 0009 in browser/moz.configure): with the later one
applied, the earlier one neither reverses nor applies. `git apply --check`
with several patches does not help either, because it checks every patch
against the unmodified files.

    python3 -I scripts/build/apply_patches.py --source ~/.cache/nulavio-build/firefox-158.0.1
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
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


def touched(patch_file: Path) -> set[str]:
    """Paths (relative to the source tree) a patch reads or writes."""
    paths = set()
    for line in patch_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(("--- a/", "+++ b/")):
            paths.add(line[6:].split("\t")[0])
    return paths


def applied_prefix(source: Path, patches: list[Path]) -> int:
    """How many patches at the head of the series the tree already has."""
    files = set().union(*(touched(p) for p in patches))
    for count in range(len(patches), 0, -1):
        with tempfile.TemporaryDirectory(prefix="nulavio-patches-") as tmp:
            scratch = Path(tmp)
            for rel in files:
                if (source / rel).is_file():
                    (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / rel, scratch / rel)
            if all(patch(scratch, p, "--reverse") for p in reversed(patches[:count])):
                return count
    return 0


def apply_series(source: Path, patches: list[Path], log=print) -> None:
    """Apply what the tree does not have yet, logging one line per patch."""
    done = applied_prefix(source, patches)
    for patch_file in patches[:done]:
        log(f"= {patch_file.name} (already applied)")
    for patch_file in patches[done:]:
        if patch(source, patch_file, "--check") and patch(source, patch_file):
            log(f"+ {patch_file.name}")
        else:
            raise SystemExit(
                f"! {patch_file.name} does not apply: rebase it on this source release"
                " (or extract a fresh source tree if the series changed under an earlier build)"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    apply_series(args.source, series())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
