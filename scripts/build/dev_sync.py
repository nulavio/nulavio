#!/usr/bin/env python3
"""Copy the Nulavio Shell, branding, branding prefs and modules into an
installed Track B build, for fast iteration without rebuilding the engine.

    python3 -I scripts/build/dev_sync.py --install ~/.cache/nulavio-ux/install/nulavio
    python3 -I scripts/build/dev_sync.py --install <dir> --reset   # back to the build's own files

Development only: the result is checked again with a real build
(scripts/build/build_nulavio.sh) before anything ships. It rewrites
<install>/browser/omni.ja, keeping the original as omni.ja.orig, and refreshes
the distribution files and the Nulavio tools next to it. With ImageMagick
(`magick`) it also replaces the branding that scripts/build/make_branding.py
generates (the About dialog's name and logo, the Settings status illustrations,
the window icons); without it the build's own branding files stay. Test profiles are fresh,
so no startup cache needs purging; for a long-lived profile start the engine
with -purgecaches.
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
ICON_SIZES = (16, 32, 48, 64, 128)


def branding_content(work: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """(omni.ja entries, window icons by file name) of the branding as make_branding.py builds it.
    Empty without ImageMagick, which make_branding needs to render the PNGs."""
    if not shutil.which("magick"):
        return {}, {}
    import make_branding

    target = work / "nulavio"
    make_branding.build(target)
    jar = (target / "content" / "jar.mn").read_text(encoding="utf-8")
    entries = {}
    for match in JAR_ENTRY.finditer(jar):
        name, source = match.group(1), match.group(2) or match.group(1)
        entries[f"chrome/browser/content/branding/{name}"] = (target / "content" / source).resolve().read_bytes()
    icons = {f"default{size}.png": (target / f"default{size}.png").read_bytes() for size in ICON_SIZES}
    return entries, icons


def rewrite(omni: Path, new: dict[str, bytes]) -> tuple[int, int]:
    original = omni.with_name("omni.ja.orig")
    if not original.exists():
        shutil.copy2(omni, original)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--install", type=Path, required=True, help="the installed build directory (contains nulavio, browser/omni.ja)"
    )
    parser.add_argument("--reset", action="store_true", help="restore the build's own omni.ja")
    args = parser.parse_args()
    install = args.install.expanduser().resolve()
    omni = install / "browser" / "omni.ja"
    if not omni.is_file():
        parser.error(f"{omni} not found")
    if args.reset:
        original = omni.with_name("omni.ja.orig")
        if original.exists():
            shutil.copy2(original, omni)
        print(f"reset {omni}")
        return 0
    with tempfile.TemporaryDirectory(prefix="nulavio-dev-sync-") as tmp:
        new = replacements(Path(tmp) / "shell")
        branding, icons = branding_content(Path(tmp) / "branding")
        new.update(branding)
        replaced, added = rewrite(omni, new)
    icon_dir = install / "browser" / "chrome" / "icons" / "default"
    if icons and icon_dir.is_dir():
        for name, data in icons.items():
            (icon_dir / name).write_bytes(data)
    for script, target in (("make_distribution.py", "distribution"), ("make_tools.py", "nulavio-tools")):
        subprocess.run(
            [sys.executable, "-I", str(ROOT / "scripts" / "build" / script), "--out", str(install / target)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    print(f"synced {install}: {replaced} entries replaced, {added} added; distribution and tools refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
