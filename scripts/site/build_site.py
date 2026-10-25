#!/usr/bin/env python3
"""Assemble the static nulavio.net site (site/) with the brand tokens and logo.

    python3 -I scripts/site/build_site.py --out dist/site

The output is plain files for Cloudflare Pages (direct upload): no build
tool, no JavaScript, no third-party resources.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "site"
ASSETS = {
    "assets/tokens.css": ROOT / "browser" / "startpage" / "tokens.css",
    "assets/nulavio-symbol.svg": ROOT / "docs" / "brand" / "assets" / "logo" / "nulavio-symbol.svg",
    "assets/nulavio-symbol-dark-on-light.svg": ROOT / "docs" / "brand" / "assets" / "logo" / "nulavio-symbol-dark-on-light.svg",
    "assets/favicon.svg": ROOT / "docs" / "brand" / "assets" / "favicon" / "favicon.svg",
    "favicon.ico": ROOT / "docs" / "brand" / "assets" / "favicon" / "favicon.ico",
}


def build(out: Path) -> list[str]:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SOURCE, out)
    (out / "assets").mkdir(exist_ok=True)
    shutil.move(out / "site.css", out / "assets" / "site.css")
    for relative, source in ASSETS.items():
        shutil.copyfile(source, out / relative)
    return sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "site")
    args = parser.parse_args()
    files = build(args.out)
    print(f"{len(files)} files in {args.out}:", ", ".join(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
