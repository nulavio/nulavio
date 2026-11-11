#!/usr/bin/env python3
"""Write the Flatpak build directory (net.nulavio.Nulavio) for one release's portable archive.

    python3 -I scripts/release/flatpak_manifest.py --archive <nulavio-<v>-<r>.linux-x86_64.tar.xz> --out DIR
        [--url URL] [--date YYYY-MM-DD]

The Flatpak packages the same signed build as the RPM: the portable archive that
rehearse_release.sh makes and publish_release.sh attaches to the GitHub release. With
--url (the release asset's address) the manifest downloads it and checks its SHA-256:
that is the manifest for Flathub. Without it, the manifest points at the local file, for
a test build (release.yml builds one for every release).

DIR gets net.nulavio.Nulavio.json, flathub.json (x86_64 only: the build is), the desktop entry (from packaging/linux/nulavio.desktop,
renamed to the app ID), the AppStream metadata with this release, the entry point and the
Flatpak-only preferences. Runtime: org.freedesktop.Platform, whose codecs-extra extension
(installed with it) brings the patented codecs. Permissions: docs/architecture/build.md.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "net.nulavio.Nulavio"
RUNTIME_VERSION = "26.08"
ARCHIVE = re.compile(r"^nulavio-(?P<version>\d+(?:\.\d+)+-[0-9]+(?:\.[0-9]+)*)\.linux-x86_64\.tar\.xz$")
RELEASE_URL = "https://github.com/nulavio/nulavio/releases/download/v{version}/{name}"

FINISH_ARGS = [
    "--share=ipc",
    "--share=network",
    "--socket=wayland",
    "--socket=fallback-x11",
    "--socket=pulseaudio",
    "--socket=pcsc",  # smart cards
    "--device=all",  # cameras and FIDO2 security keys (WebAuthn), as Mozilla's Flatpak
    "--persist=.nulavio",  # profiles kept under ~/.var/app/net.nulavio.Nulavio
    "--filesystem=xdg-download",
    "--talk-name=org.freedesktop.FileManager1",  # "show in folder" for downloads
    "--talk-name=org.freedesktop.NativeMessagingProxy",  # password-manager apps (flatpak-prefs.js)
    "--talk-name=org.a11y.Bus",
    "--own-name=org.mozilla.nulavio.*",  # remoting: a second start opens a window in the running one
    "--system-talk-name=org.freedesktop.NetworkManager",  # online/offline state
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def desktop_entry() -> str:
    text = (ROOT / "packaging" / "linux" / "nulavio.desktop").read_text(encoding="utf-8")
    if "\nIcon=nulavio\n" not in text:
        raise SystemExit("flatpak_manifest: packaging/linux/nulavio.desktop changed: Icon=nulavio expected")
    return text.replace("\nIcon=nulavio\n", f"\nIcon={APP_ID}\n")


def metainfo(version: str, date: str) -> str:
    text = (ROOT / "packaging" / "flatpak" / f"{APP_ID}.metainfo.xml").read_text(encoding="utf-8")
    release = (
        f'<release version="{version}" date="{date}">\n'
        f"      <url>https://github.com/nulavio/nulavio/releases/tag/v{version}</url>\n"
        "    </release>"
    )
    if text.count("<!-- releases -->") != 1:
        raise SystemExit("flatpak_manifest: the metainfo template has no <!-- releases --> marker")
    return text.replace("<!-- releases -->", release)


def manifest(archive_source: dict) -> dict:
    icons = " ".join(str(size) for size in (16, 32, 48, 64, 128))
    return {
        "id": APP_ID,
        "runtime": "org.freedesktop.Platform",
        "runtime-version": RUNTIME_VERSION,
        "sdk": "org.freedesktop.Sdk",
        "command": "nulavio",
        "finish-args": FINISH_ARGS,
        "modules": [
            {
                "name": "nulavio",
                "buildsystem": "simple",
                "build-commands": [
                    "mkdir -p /app/lib",
                    "cp -a nulavio /app/lib/nulavio",
                    "install -Dm644 flatpak-prefs.js /app/lib/nulavio/browser/defaults/preferences/flatpak.js",
                    "install -Dm755 nulavio.sh /app/bin/nulavio",
                    f"install -Dm644 {APP_ID}.desktop /app/share/applications/{APP_ID}.desktop",
                    f"install -Dm644 {APP_ID}.metainfo.xml /app/share/metainfo/{APP_ID}.metainfo.xml",
                    f"for size in {icons}; do install -Dm644 /app/lib/nulavio/browser/chrome/icons/default/default$size.png"
                    f' "/app/share/icons/hicolor/${{size}}x${{size}}/apps/{APP_ID}.png"; done',
                ],
                "sources": [
                    {**archive_source, "dest": "nulavio"},
                    {"type": "file", "path": "nulavio.sh"},
                    {"type": "file", "path": "flatpak-prefs.js"},
                    {"type": "file", "path": f"{APP_ID}.desktop"},
                    {"type": "file", "path": f"{APP_ID}.metainfo.xml"},
                ],
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, required=True, help="the release's portable archive")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--url", action="store_true", help="download the archive from the GitHub release (Flathub)")
    parser.add_argument("--date", default=datetime.date.today().isoformat())
    args = parser.parse_args(argv)
    match = ARCHIVE.match(args.archive.name)
    if not match or not args.archive.is_file():
        print(f"flatpak_manifest: {args.archive} is not a Nulavio portable archive", file=sys.stderr)
        return 2
    version = match["version"]
    args.out.mkdir(parents=True, exist_ok=True)
    if args.url:
        source = {"type": "archive", "url": RELEASE_URL.format(version=version, name=args.archive.name)}
    else:
        shutil.copy2(args.archive, args.out / args.archive.name)
        source = {"type": "archive", "path": args.archive.name}
    source["sha256"] = sha256(args.archive)
    (args.out / f"{APP_ID}.json").write_text(json.dumps(manifest(source), indent=2) + "\n", encoding="utf-8")
    # The build is x86_64 only; Flathub would otherwise also build aarch64 with this binary.
    (args.out / "flathub.json").write_text(json.dumps({"only-arches": ["x86_64"]}, indent=2) + "\n", encoding="utf-8")
    (args.out / f"{APP_ID}.desktop").write_text(desktop_entry(), encoding="utf-8")
    (args.out / f"{APP_ID}.metainfo.xml").write_text(metainfo(version, args.date), encoding="utf-8")
    for name in ("nulavio.sh", "flatpak-prefs.js"):
        shutil.copy2(ROOT / "packaging" / "flatpak" / name, args.out / name)
    print(f"flatpak_manifest: {args.out / f'{APP_ID}.json'} ({version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
