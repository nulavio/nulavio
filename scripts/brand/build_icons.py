#!/usr/bin/env python3
"""Rasterise the Nulavio icon SVGs into the freedesktop hicolor layout.

  16 px  <- icons/masters/nulavio-16.svg   (pixel-tuned, 2 px stems on pixel centres)
  24 px  <- icons/masters/nulavio-24.svg   (heavier stroke, single dot)
  32-512 <- icons/hicolor/scalable/apps/nulavio.svg

Also writes favicon/favicon.ico (16, 32, 48) and a contact sheet used to
review legibility at small sizes. Requires ImageMagick 7 (`magick`) with the
librsvg delegate, or `rsvg-convert`. Metadata chunks are stripped so the
output does not change between runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "brand" / "assets"
ICONS = ASSETS / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def source_for(size: int) -> tuple[Path, int]:
    if size == 16:
        return ICONS / "masters" / "nulavio-16.svg", 16
    if size == 24:
        return ICONS / "masters" / "nulavio-24.svg", 24
    return ICONS / "hicolor" / "scalable" / "apps" / "nulavio.svg", 512


def rasterise(svg: Path, native: int, size: int, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsvg-convert"):
        cmd = ["rsvg-convert", "-w", str(size), "-h", str(size), "-o", str(out), str(svg)]
    elif shutil.which("magick"):
        density = 96 * size / native
        cmd = [
            "magick",
            "-background",
            "none",
            "-density",
            f"{density:.4f}",
            str(svg),
            "-resize",
            f"{size}x{size}!",
            "-strip",
            "-define",
            "png:exclude-chunks=date,time",
            str(out),
        ]
    else:
        sys.exit("need rsvg-convert or ImageMagick 'magick' to rasterise icons")
    subprocess.run(cmd, check=True)


def review_sheets() -> list[Path]:
    """Studies side by side and the lockups on light/dark, for the brand docs."""
    logo = ASSETS / "logo"
    review = ASSETS / "review"
    review.mkdir(parents=True, exist_ok=True)
    strip = ["-strip", "-define", "png:exclude-chunks=date,time"]
    studies = review / "logo-studies.png"
    cmd = ["magick"]
    for name in ("study-a-null-course", "study-b-vanishing-route", "study-c-null-disc"):
        cmd += [
            "(",
            "-background",
            "none",
            "-density",
            "400",
            str(logo / "studies" / f"{name}.svg"),
            "-resize",
            "240x240",
            "-bordercolor",
            "#F1F7F5",
            "-border",
            "20",
            ")",
        ]
    cmd += ["-background", "#F1F7F5", "+append", *strip, str(studies)]
    subprocess.run(cmd, check=True)
    lockups = review / "lockups.png"
    cmd = ["magick"]
    for name, bg in (
        ("nulavio-lockup-horizontal", "#F1F7F5"),
        ("nulavio-lockup-horizontal-on-dark", "#0B1623"),
        ("nulavio-lockup-horizontal-tile", "#FFFFFF"),
    ):
        cmd += [
            "(",
            "-background",
            bg,
            "-density",
            "300",
            str(logo / f"{name}.svg"),
            "-resize",
            "640x",
            "-bordercolor",
            bg,
            "-border",
            "32",
            ")",
        ]
    cmd += ["-append", *strip, str(lockups)]
    subprocess.run(cmd, check=True)
    return [studies, lockups]


def main() -> int:
    written = []
    for size in SIZES:
        svg, native = source_for(size)
        out = ICONS / "hicolor" / f"{size}x{size}" / "apps" / "nulavio.png"
        rasterise(svg, native, size, out)
        written.append(out)
    if shutil.which("magick"):
        fav = ASSETS / "favicon" / "favicon.ico"
        fav.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["magick"] + [str(ICONS / "hicolor" / f"{s}x{s}" / "apps" / "nulavio.png") for s in (16, 32, 48)] + [str(fav)],
            check=True,
        )
        written.append(fav)
        # Contact sheet: each size at 1:1 and magnified 4x (nearest neighbour) on light and dark.
        sheet = ASSETS / "review" / "small-size-review.png"
        sheet.parent.mkdir(parents=True, exist_ok=True)
        tiles = []
        for size in (16, 24, 32, 48):
            png = ICONS / "hicolor" / f"{size}x{size}" / "apps" / "nulavio.png"
            tiles.append(str(png))
        cmd = ["magick"]
        for bg in ("#F1F7F5", "#0B1623"):
            row = ["("]
            for t in tiles:
                row += ["(", t, "-filter", "point", "-resize", "400%", "-bordercolor", bg, "-border", "16", ")"]
            row += ["-background", bg, "-gravity", "center", "+append", ")"]
            cmd += row
        cmd += ["-append", "-strip", "-define", "png:exclude-chunks=date,time", str(sheet)]
        subprocess.run(cmd, check=True)
        written.append(sheet)
        written += review_sheets()
    for path in written:
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
