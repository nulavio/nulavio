#!/usr/bin/env python3
"""Copy the Nulavio command-line tools next to a Track B build.

The browser's Shell calls `nulavio vault api` for encrypted profiles (S6): the
Vault's cryptography lives in one place, the launcher package, and runs as a
separate process that receives secrets on stdin. This puts that package where
the Shell looks for it: <install-dir>/nulavio-tools/{bin,launcher,browser/config}.

    python3 -I scripts/build/make_tools.py --out ~/.cache/nulavio-build/install/nulavio/nulavio-tools
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARTS = ("bin/nulavio", "launcher/nulavio_launcher", "browser/config")


def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    for part in PARTS:
        source, target = ROOT / part, out / part
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, target)
    (out / "bin" / "nulavio").chmod(0o755)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    build(parser.parse_args().out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
