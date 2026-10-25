"""User-level desktop integration (no root): .desktop entry and icons.

Installs into ``$XDG_DATA_HOME/applications`` and ``$XDG_DATA_HOME/icons``.
The entry deliberately declares no MimeType: the preview never registers as
a URL handler or default browser. Every written file is recorded so that
``nulavio desktop uninstall`` removes exactly what was installed.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

from . import log, paths

ICON_NAME = "nulavio-preview"
DESKTOP_FILE = "nulavio-preview.desktop"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def _xdg_data_home() -> Path:
    value = os.environ.get("XDG_DATA_HOME", "")
    return Path(value) if value and os.path.isabs(value) else Path.home() / ".local" / "share"


def _manifest_path() -> Path:
    return paths.state_home() / "desktop-install.json"


def _quote_exec(path: Path) -> str:
    text = str(path)
    if any(c in text for c in " \t\n\"'\\><~|&;$*?#()`"):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        return f'"{escaped}"'
    return text


def render_entry(launcher: Path) -> str:
    template = (paths.repo_root() / "packaging" / "linux" / "nulavio-preview.desktop.in").read_text(encoding="utf-8")
    return template.replace("@EXEC@", _quote_exec(launcher))


def install(launcher: Path) -> list[Path]:
    data_home = _xdg_data_home()
    written: list[Path] = []
    apps = data_home / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / DESKTOP_FILE
    entry.write_text(render_entry(launcher), encoding="utf-8")
    entry.chmod(0o644)
    written.append(entry)
    icons = paths.assets_dir() / "icons" / "hicolor"
    for size in SIZES:
        source = icons / f"{size}x{size}" / "apps" / "nulavio.png"
        if not source.exists():
            continue
        target = data_home / "icons" / "hicolor" / f"{size}x{size}" / "apps" / f"{ICON_NAME}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        written.append(target)
    svg = icons / "scalable" / "apps" / "nulavio.svg"
    if svg.exists():
        target = data_home / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON_NAME}.svg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(svg.read_bytes())
        written.append(target)
    paths.ensure_private_dir(paths.state_home())
    paths.write_private_file(_manifest_path(), json.dumps([str(p) for p in written], indent=2) + "\n")
    log.event("desktop.install", files=len(written))
    return written


def uninstall() -> list[Path]:
    manifest = _manifest_path()
    if not manifest.exists():
        return []
    removed = []
    data_home = _xdg_data_home().resolve()
    for raw in json.loads(manifest.read_text(encoding="utf-8")):
        target = Path(raw)
        # Only remove files we could have written: inside XDG_DATA_HOME and named for Nulavio.
        if data_home not in target.resolve().parents or not target.name.startswith("nulavio-preview"):
            continue
        if target.exists():
            target.unlink()
            removed.append(target)
    manifest.unlink()
    log.event("desktop.uninstall", files=len(removed))
    return removed


def describe_command(launcher: Path) -> str:
    return shlex.join([str(launcher), "run"])
