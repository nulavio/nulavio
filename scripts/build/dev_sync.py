#!/usr/bin/env python3
"""Copy the Nulavio Shell, branding, branding prefs and modules into an
installed Track B build, for fast iteration without rebuilding the engine.

    python3 -I scripts/build/dev_sync.py --install ~/.cache/nulavio-ux/install/nulavio
    python3 -I scripts/build/dev_sync.py --install <dir> --no-branding   # the build's own branding stays
    python3 -I scripts/build/dev_sync.py --install <dir> --reset         # omni.ja and the window icons as built

Development only: the result is checked again with a real build
(scripts/build/build_nulavio.sh) before anything ships. It rewrites
<install>/browser/omni.ja, keeping the original as omni.ja.orig, and refreshes
the distribution files and the Nulavio tools next to it.

The branding that scripts/build/make_branding.py generates (the About dialog's
name and logo, the Settings status illustrations, the window icons) is replaced
in one of three ways, and the last line printed says which:

  rendered    with ImageMagick (`magick`) on the host: everything, as a build
              makes it, including the five window icons under
              browser/chrome/icons/default (each kept as <name>.orig)
  text only   without ImageMagick: the files that need no rasteriser (the SVG
              and CSS files); the PNG and ICO files and the window icons are
              the build's own
  left alone  with --no-branding: the build's own branding, on any host

--reset puts omni.ja and the window icons back from their .orig copies. The
distribution files and the tools are generated in place and are not put back:
unpack the package again for those.

Test profiles are fresh, so no startup cache needs purging; for a long-lived
profile start the engine with -purgecaches.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_shell  # noqa: E402

BRANDING = ROOT / "browser" / "branding" / "nulavio"


def replacements(shell_dir: Path) -> dict[str, bytes]:
    """omni.ja entry name -> new content."""
    out: dict[str, bytes] = {}
    for rel in make_shell.assemble(shell_dir):
        out[f"chrome/browser/{make_shell.JAR_DIR}/{rel}"] = (shell_dir / rel).read_bytes()
    for path in (BRANDING / "content" / "theme").glob("*.css"):
        out[f"chrome/browser/content/branding/theme/{path.name}"] = path.read_bytes()
    out["defaults/preferences/firefox-branding.js"] = (BRANDING / "pref" / "firefox-branding.js").read_bytes()
    for path in BRANDING.glob("*.sys.mjs"):
        out[f"modules/nulavio/{path.name}"] = path.read_bytes()
    return out


JAR_ENTRY = re.compile(r"^\s+content/branding/(\S+)(?:\s+\((\S+)\))?", re.M)
ICON_NAMES = tuple(f"default{size}.png" for size in (16, 32, 48, 64, 128))
RENDERED, TEXT_ONLY, LEFT_ALONE = "rendered", "text only", "left alone"


def have_magick() -> bool:
    return shutil.which("magick") is not None


def jar_entries(content: Path) -> dict[str, Path]:
    """omni.ja entry name -> source file, for every branding file content/jar.mn packs."""
    out = {}
    for match in JAR_ENTRY.finditer((content / "jar.mn").read_text(encoding="utf-8")):
        name, source = match.group(1), match.group(2) or match.group(1)
        out[f"chrome/browser/content/branding/{name}"] = (content / source).resolve()
    return out


def rendered_branding(work: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """(omni.ja entries, window icons by file name) of the branding as make_branding.py builds it.
    Needs ImageMagick, which make_branding renders the PNG and ICO files with."""
    import make_branding

    target = work / "nulavio"
    make_branding.build(target)
    entries = {name: source.read_bytes() for name, source in jar_entries(target / "content").items()}
    return entries, {name: (target / name).read_bytes() for name in ICON_NAMES}


def text_branding() -> dict[str, bytes]:
    """The branding files that need no rasteriser: the text files committed under browser/branding/nulavio/content
    and the SVG files make_branding.py writes from the brand sources. The PNG and ICO entries are left out."""
    import make_branding

    wordmark = make_branding.context_fill_wordmark().encode()
    generated = {
        "about-logo.svg": (make_branding.ICONS / "scalable" / "apps" / "nulavio.svg").read_bytes(),
        "about-wordmark.svg": wordmark,
        "firefox-wordmark.svg": wordmark,
        "document_pdf.svg": make_branding.document_pdf_svg().encode(),
    }
    out = {}
    for name, source in jar_entries(BRANDING / "content").items():
        if source.is_file():
            out[name] = source.read_bytes()
        elif source.name in generated:
            out[name] = generated[source.name]
    return out


def original_of(path: Path) -> Path:
    return path.with_name(path.name + ".orig")


def copy_into_place(source: Path, target: Path) -> None:
    """`target` becomes a copy of `source`, whole or not at all: written beside it, then renamed."""
    tmp = target.with_name(target.name + ".tmp")
    shutil.copy2(source, tmp)
    tmp.replace(target)


def write_into_place(target: Path, data: bytes) -> None:
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)


def keep_original(path: Path) -> Path:
    """The build's own copy of `path`, made the first time it is about to be replaced and never again."""
    original = original_of(path)
    if not original.exists():
        copy_into_place(path, original)
    return original


def restore(path: Path) -> bool:
    """Put the build's own `path` back, when a copy of it was kept."""
    original = original_of(path)
    if not original.is_file():
        return False
    copy_into_place(original, path)
    return True


def rewrite(omni: Path, new: dict[str, bytes]) -> tuple[int, int]:
    original = keep_original(omni)
    tmp = omni.with_name("omni.ja.tmp")
    replaced = added = 0
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(tmp, "w") as dst:
        seen = set()
        for info in src.infolist():
            data = new.get(info.filename)
            if data is None:
                data = src.read(info.filename)
            else:
                replaced += 1
            seen.add(info.filename)
            dst.writestr(info, data, compress_type=info.compress_type)
        for name in sorted(set(new) - seen):
            dst.writestr(name, new[name], compress_type=zipfile.ZIP_DEFLATED)
            added += 1
    tmp.replace(omni)
    return replaced, added


def sync_icons(icon_dir: Path, icons: dict[str, bytes]) -> int:
    """The window icons the package has become those of `icons`; one that `icons` does not hold goes
    back to the build's own, so that an earlier rendered sync does not outlast a run that says it
    left them alone. Returns how many were replaced."""
    replaced = 0
    for name in ICON_NAMES:
        path = icon_dir / name
        if name in icons and path.is_file():
            keep_original(path)
            write_into_place(path, icons[name])
            replaced += 1
        else:
            restore(path)
    return replaced


def refresh(install: Path) -> None:
    """The distribution files and the Nulavio tools, generated again next to the engine."""
    for script, target in (("make_distribution.py", "distribution"), ("make_tools.py", "nulavio-tools")):
        subprocess.run(
            [sys.executable, "-I", str(ROOT / "scripts" / "build" / script), "--out", str(install / target)],
            check=True,
            stdout=subprocess.DEVNULL,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--install", type=Path, required=True, help="the installed build directory (contains nulavio, browser/omni.ja)"
    )
    parser.add_argument("--reset", action="store_true", help="restore the build's own omni.ja and window icons")
    parser.add_argument(
        "--no-branding",
        action="store_true",
        help="leave the build's own branding (About dialog, status illustrations, window icons), with or without ImageMagick",
    )
    args = parser.parse_args()
    install = args.install.expanduser().resolve()
    omni = install / "browser" / "omni.ja"
    icon_dir = install / "browser" / "chrome" / "icons" / "default"
    if not omni.is_file():
        parser.error(f"{omni} not found")
    if args.reset:
        restored = [path.name for path in (omni, *(icon_dir / name for name in ICON_NAMES)) if restore(path)]
        if restored:
            print(f"reset {install}: {', '.join(restored)} restored from the .orig copies")
        else:
            print(f"reset {install}: nothing to restore, no .orig copy was kept")
        return 0
    mode = LEFT_ALONE if args.no_branding else RENDERED if have_magick() else TEXT_ONLY
    with tempfile.TemporaryDirectory(prefix="nulavio-dev-sync-") as tmp:
        new = replacements(Path(tmp) / "shell")
        branding, icons = {}, {}
        if mode == RENDERED:
            branding, icons = rendered_branding(Path(tmp) / "branding")
        elif mode == TEXT_ONLY:
            branding = text_branding()
        new.update(branding)
        replaced, added = rewrite(omni, new)
    icon_count = sync_icons(icon_dir, icons)
    refresh(install)
    print(f"synced {install}: {replaced} entries replaced, {added} added; distribution and tools refreshed")
    print(
        {
            RENDERED: f"branding: rendered with ImageMagick, {len(branding)} files and {icon_count} window icons replaced",
            TEXT_ONLY: f"branding: text only, {len(branding)} SVG and CSS files replaced; the PNG and ICO files and the "
            "window icons are the build's own, because there is no `magick` on this host",
            LEFT_ALONE: "branding: left alone, the build's own (--no-branding)",
        }[mode]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
