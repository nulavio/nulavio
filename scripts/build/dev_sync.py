#!/usr/bin/env python3
"""Copy the Nulavio Shell, branding theme, branding prefs and modules into an
installed Track B build, for fast iteration without rebuilding the engine.

    python3 -I scripts/build/dev_sync.py --install ~/.cache/nulavio-ux/install/nulavio
    python3 -I scripts/build/dev_sync.py --install <dir> --reset   # back to the build's own files

Development only: the result is checked again with a real build
(scripts/build/build_nulavio.sh) before anything ships. It rewrites
<install>/browser/omni.ja, keeping the original as omni.ja.orig, and refreshes
the distribution files and the Nulavio tools next to it. Test profiles are fresh,
so no startup cache needs purging; for a long-lived profile start the engine
with -purgecaches.
"""

from __future__ import annotations

import argparse
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
        replaced, added = rewrite(omni, replacements(Path(tmp) / "shell"))
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
