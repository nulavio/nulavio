#!/usr/bin/env python3
"""Install the Nulavio branding directory into a Firefox source tree (Track B).

Text files come from browser/branding/nulavio/ (reviewed in git). Binary and
SVG assets are generated here from the Nulavio brand sources, so no Mozilla
artwork is copied and nothing binary needs to be committed.

    python3 -I scripts/build/make_branding.py --source ~/.cache/nulavio-build/firefox-158.0.1

Requires ImageMagick 7 (`magick`) with the librsvg delegate; build_nulavio.sh runs it in the
pinned Fedora image (scripts/release/base_image.sh fedora-build), so the icons do not depend on the host.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "brand"))
sys.path.insert(0, str(ROOT / "scripts" / "build"))

import build_logo as logo  # noqa: E402
import make_shell  # noqa: E402

TEMPLATES = ROOT / "browser" / "branding" / "nulavio"
ICONS = ROOT / "docs" / "brand" / "assets" / "icons" / "hicolor"
STRIP = ["-strip", "-define", "png:exclude-chunks=date,time"]


def magick(*args: str) -> None:
    subprocess.run(["magick", *args], check=True)


def render(svg: Path, size: int | str, out: Path, background: str = "none") -> None:
    w, h = (size, size) if isinstance(size, int) else map(int, size.split("x"))
    magick(
        "-background",
        background,
        "-density",
        "600",
        str(svg),
        "-resize",
        f"{w}x{h}",
        "-gravity",
        "center",
        "-extent",
        f"{w}x{h}",
        *STRIP,
        str(out),
    )


def context_fill_wordmark() -> str:
    """Wordmark whose colour follows the chrome (`-moz-context-properties: fill`)."""
    path, dots, advance = logo.wordmark_paths()
    pad = logo.W_STROKE / 2 + 1
    circles = "".join(f'<circle cx="{cx}" cy="{cy}" r="{r}"/>' for cx, cy, r in dots)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-pad} 4 {advance + 2 * pad} 64">\n'
        f"{logo.HEADER}\n"
        f'<path d="{path}" fill="none" stroke="context-fill light-dark(#0B1623, #F1F7F5)" '
        f'stroke-width="{logo.W_STROKE}" stroke-linecap="round" stroke-linejoin="round"/>\n'
        f'<g fill="context-fill light-dark(#0B1623, #F1F7F5)">{circles}</g>\n</svg>\n'
    )


def document_pdf_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">\n'
        f"{logo.HEADER}\n"
        '<path d="M14 6h26l12 12v40H14z" fill="#F1F7F5" stroke="#183746" stroke-width="2" stroke-linejoin="round"/>\n'
        '<path d="M40 6v12h12" fill="none" stroke="#183746" stroke-width="2" stroke-linejoin="round"/>\n'
        '<g transform="translate(17 30) scale(0.32)">' + logo.mark(logo.MINT_DARK) + "</g>\n"
        '<text x="33" y="54" font-family="sans-serif" font-size="9" font-weight="700" fill="#183746" '
        'text-anchor="middle">PDF</text>\n</svg>\n'
    )


def build(target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(TEMPLATES, target)
    scalable = ICONS / "scalable" / "apps" / "nulavio.svg"
    for size in (16, 22, 24, 32, 48, 64, 128, 256):
        committed = ICONS / f"{size}x{size}" / "apps" / "nulavio.png"
        if committed.exists():
            shutil.copyfile(committed, target / f"default{size}.png")
        else:
            render(scalable, size, target / f"default{size}.png")
    content = target / "content"
    shutil.copyfile(scalable, content / "about-logo.svg")
    render(scalable, 192, content / "about-logo.png")
    render(scalable, 384, content / "about-logo@2x.png")
    render(scalable, 192, content / "about-logo-private.png")
    render(scalable, 384, content / "about-logo-private@2x.png")
    with tempfile.TemporaryDirectory() as tmp:
        tile = Path(tmp) / "about-bg.png"
        render(scalable, 160, tile)
        magick(
            "-size", "300x236", "xc:#0B1623", str(tile), "-gravity", "center", "-composite", *STRIP, str(content / "about.png")
        )
    wordmark = context_fill_wordmark()
    (content / "about-wordmark.svg").write_text(wordmark, encoding="utf-8")
    (content / "firefox-wordmark.svg").write_text(wordmark, encoding="utf-8")  # path name is fixed upstream
    (content / "document_pdf.svg").write_text(document_pdf_svg(), encoding="utf-8")
    magick(*(str(target / f"default{s}.png") for s in (16, 32, 48, 256)), str(target / "document.ico"))
    make_shell.install(target)  # built-in add-on, built from the branding dir (no Mozilla file patched)
    print(f"branding installed at {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="Firefox source tree")
    args = parser.parse_args()
    if not (args.source / "browser" / "branding" / "branding-common.mozbuild").exists():
        raise SystemExit(f"{args.source} does not look like a Firefox source tree")
    build(args.source / "browser" / "branding" / "nulavio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
