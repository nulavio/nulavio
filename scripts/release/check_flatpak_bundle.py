#!/usr/bin/env python3
"""The Flatpak bundle holds the attested portable archive, and nothing it should not (#324).

    python3 -I scripts/release/check_flatpak_bundle.py --bundle nulavio-<v>.x86_64.flatpak \\
        --archive nulavio-<v>.linux-x86_64.tar.xz

The release workflow's flatpak job builds the bundle with Flathub's builder and runtime, in a job
with no attestation. Before publish signs its hash, this imports it into a temporary OSTree
repository (`flatpak build-import-bundle`, `ostree checkout`) and requires:

- one ref, app/net.nulavio.Nulavio/x86_64/master, with no other file in it than those below;
- files/lib/nulavio: the archive's nulavio/ file for file (the same bytes, the same executable
  bit, no link), plus the Flatpak preferences of packaging/flatpak/;
- files/bin/nulavio, the desktop entry and the metainfo as flatpak_manifest.py writes them for this
  archive (the metainfo with the release date the bundle carries), and the icons the archive's own;
- export/: the same desktop entry, metainfo and icons;
- under files/share/app-info only what Flathub's metadata step adds (its catalogue, icons and
  screenshots), and files/manifest.json (the builder's record): data, none of it executable;
- metadata: the runtime and SDK flatpak_manifest.py names, the command, and exactly its permissions;
- the bundle's header (read as the GVariant it is): exactly the keys `flatpak build-bundle` writes with
  `--runtime-repo` alone (no `origin` or `gpg-keys`, which would give the app an update channel and keys of
  their own, and an empty `collection-id`), its ref, Flathub as the runtime's source, and the same metadata
  as the app's.

What it cannot check: the runtime, which `flatpak install` takes from Flathub, signed by Flathub.
Needs flatpak and ostree. Exit 0 when the bundle passes, 1 with each difference, 2 for bad input.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import flatpak_manifest  # noqa: E402

APP = flatpak_manifest.APP_ID
REF = f"app/{APP}/x86_64/master"
RUNTIME_REPO = "https://dl.flathub.org/repo/flathub.flatpakrepo"
PREFS = "browser/defaults/preferences/flatpak.js"
ICON_SIZES = (16, 32, 48, 64, 128)
# What Flathub's metadata step writes (appstream compose, with the media mirrored): data files only.
APP_INFO = re.compile(
    rf"files/share/app-info/(xmls/{re.escape(APP)}\.xml\.gz|icons/flatpak/\d+x\d+/{re.escape(APP)}\.png"
    r"|media/[\w./@-]+\.png)"
)
# The keyfile sections and keys of `metadata` that the finish arguments become.
CONTEXT = {"--share": ("Context", "shared"), "--socket": ("Context", "sockets"), "--device": ("Context", "devices"),
           "--filesystem": ("Context", "filesystems"), "--persist": ("Context", "persistent")}  # fmt: skip
BUS = {"--talk-name": ("Session Bus Policy", "talk"), "--own-name": ("Session Bus Policy", "own"),
       "--system-talk-name": ("System Bus Policy", "talk")}  # fmt: skip


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def tree(root: Path) -> dict[str, tuple[str, bool] | str]:
    """Every entry under `root`: a file as (SHA-256, executable), anything else by its kind."""
    found: dict[str, tuple[str, bool] | str] = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        name = path.relative_to(root).as_posix()
        if stat.S_ISREG(mode):
            found[name] = (digest(path), bool(mode & 0o111))
        elif not stat.S_ISDIR(mode):
            found[name] = "link" if stat.S_ISLNK(mode) else "special"
    return found


def expected_files(archive_root: Path, metainfo_date: str, version: str) -> dict[str, tuple[str, bool]]:
    """What the checkout must hold, path by path, besides the app-info data and the builder's record."""
    want: dict[str, tuple[str, bool]] = {}
    for name, entry in tree(archive_root / "nulavio").items():
        if isinstance(entry, str):
            raise ValueError(f"the archive itself has a {entry}: nulavio/{name}")
        want[f"files/lib/nulavio/{name}"] = entry
    sha = lambda data: hashlib.sha256(data).hexdigest()  # noqa: E731
    packaging = ROOT / "packaging" / "flatpak"
    want[f"files/lib/nulavio/{PREFS}"] = (digest(packaging / "flatpak-prefs.js"), False)
    want["files/bin/nulavio"] = (digest(packaging / "nulavio.sh"), True)
    desktop = sha(flatpak_manifest.desktop_entry().encode())
    meta = sha(flatpak_manifest.metainfo(version, metainfo_date).encode())
    for top in ("files/share", "export/share"):
        want[f"{top}/applications/{APP}.desktop"] = (desktop, False)
        want[f"{top}/metainfo/{APP}.metainfo.xml"] = (meta, False)
        for size in ICON_SIZES:
            icon = want[f"files/lib/nulavio/browser/chrome/icons/default/default{size}.png"][0]
            want[f"{top}/icons/hicolor/{size}x{size}/apps/{APP}.png"] = (icon, False)
    return want


def compare_checkout(checkout: Path, archive_root: Path, version: str) -> list[str]:
    """The differences between the checked-out ref and what the archive and flatpak_manifest.py make."""
    found = tree(checkout)
    problems = []
    meta = checkout / "files" / "share" / "metainfo" / f"{APP}.metainfo.xml"
    dates = re.findall(rf'<release version="{re.escape(version)}" date="(\d{{4}}-\d{{2}}-\d{{2}})"', meta.read_text(
        encoding="utf-8", errors="replace")) if meta.is_file() else []  # fmt: skip
    want = expected_files(archive_root, dates[0] if len(dates) == 1 else "0000-00-00", version)
    for name, entry in want.items():
        if name not in found:
            problems.append(f"missing: {name}")
        elif found[name] != entry:
            problems.append(f"not what the archive and flatpak_manifest.py make: {name}")
    for name, entry in found.items():
        if name in want or name == "metadata":
            continue
        if isinstance(entry, str):
            problems.append(f"a {entry} that should not be there: {name}")
        elif name == "files/manifest.json" or APP_INFO.fullmatch(name):
            if entry[1]:
                problems.append(f"executable data: {name}")
        else:
            problems.append(f"not from the archive or the manifest: {name}")
    return problems


def expected_permissions() -> dict[tuple[str, str], set[str]]:
    want: dict[tuple[str, str], set[str]] = {}
    for arg in flatpak_manifest.FINISH_ARGS:
        option, _, value = arg.partition("=")
        if option in CONTEXT:
            want.setdefault(CONTEXT[option], set()).add(value)
        elif option in BUS:
            want.setdefault((BUS[option][0], value), set()).add(BUS[option][1])
        else:
            raise ValueError(f"no metadata key known for {arg}")
    return want


def compare_metadata(text: str) -> list[str]:
    """The app's metadata: its runtime, SDK and command, and exactly the permissions of FINISH_ARGS."""
    keyfile = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    keyfile.optionxform = str  # keys are case-sensitive (D-Bus names)
    try:
        keyfile.read_string(text)
    except configparser.Error as exc:
        return [f"metadata does not parse: {exc}"]
    problems = []
    version = flatpak_manifest.RUNTIME_VERSION
    application = dict(keyfile["Application"]) if keyfile.has_section("Application") else {}
    want_app = {"name": APP, "runtime": f"org.freedesktop.Platform/x86_64/{version}",
                "sdk": f"org.freedesktop.Sdk/x86_64/{version}", "command": "nulavio"}  # fmt: skip
    if application != want_app:
        problems.append(f"metadata [Application] is {application}, not {want_app}")
    found: dict[tuple[str, str], set[str]] = {}
    for section in keyfile.sections():
        if section == "Application":
            continue
        for key, value in keyfile[section].items():
            if section == "Context":
                found[(section, key)] = {part for part in value.split(";") if part}
            else:
                found.setdefault((section, key), set()).add(value)
    want = expected_permissions()
    for place in sorted(set(found) | set(want)):
        if found.get(place, set()) != want.get(place, set()):
            problems.append(
                f"metadata [{place[0]}] {place[1]}: {sorted(found.get(place, set()))}, not {sorted(want.get(place, set()))}"
            )
    return problems


def _offset_size(size: int) -> int:
    """How wide a GVariant container's framing offsets are, from the container's size."""
    return 0 if size == 0 else 1 if size <= 0xFF else 2 if size <= 0xFFFF else 4 if size <= 0xFFFFFFFF else 8


def _offset(data: bytes, at: int, width: int) -> int:
    return int.from_bytes(data[at : at + width], "little")


def header(data: bytes) -> dict[str, tuple[str, bytes]]:
    """The bundle's header: the a{sv} that opens the static-delta superblock a bundle is, as {key: (type, value)}.

    GVariant keeps a container's framing offsets at its end: the superblock's last one is where its first member
    (the dictionary) ends; the dictionary's are where each of its entries ends; an entry's is where its key ends.
    A value is its bytes, a zero byte and its type string."""
    width = _offset_size(len(data))
    if width == 0 or len(data) < width:
        raise ValueError("not a Flatpak bundle (empty)")
    table = data[: _offset(data, len(data) - width, width)]
    width = _offset_size(len(table))
    if not table:
        raise ValueError("not a Flatpak bundle (its header is empty)")
    first = _offset(table, len(table) - width, width)
    if not 0 <= first <= len(table) - width or (len(table) - first) % width:
        raise ValueError("not a Flatpak bundle (its header does not parse)")
    entries: dict[str, tuple[str, bytes]] = {}
    start = 0
    for k in range((len(table) - first) // width):
        end = _offset(table, first + k * width, width)
        start = (start + 7) & ~7  # a {sv} entry is aligned to 8
        entry = table[start:end]
        start = end
        size = _offset_size(len(entry))
        if size == 0 or len(entry) < size:
            raise ValueError("not a Flatpak bundle (an empty header entry)")
        key_end = _offset(entry, len(entry) - size, size)
        value = entry[(key_end + 7) & ~7 : len(entry) - size]
        if not 0 < key_end <= len(entry) or b"\x00" not in value:
            raise ValueError("not a Flatpak bundle (a header entry does not parse)")
        cut = value.rindex(b"\x00")
        key = entry[:key_end].rstrip(b"\x00").decode("utf-8", "replace")
        if key in entries:
            raise ValueError(f"the bundle's header has {key} twice")
        entries[key] = (value[cut + 1 :].decode("ascii", "replace"), value[:cut])
    if not entries:
        raise ValueError("not a Flatpak bundle (its header is empty)")
    return entries


# What `flatpak build-bundle --runtime-repo=…` writes into the header, beside the delta parts (deltas/…).
HEADER_KEYS = {"flatpak", "ref", "metadata", "appdata", "icon-64", "icon-128", "runtime-repo", "collection-id",
               "ostree.endianness"}  # fmt: skip


def compare_header(entries: dict[str, tuple[str, bytes]], metadata: str) -> list[str]:
    """The header's keys and the strings that decide what installing the bundle does."""
    problems = []
    unknown = sorted(key for key in entries if key not in HEADER_KEYS and not key.startswith("deltas/"))
    if unknown:
        problems.append(f"the bundle's header has keys build-bundle --runtime-repo does not write: {unknown}")

    def text(key: str) -> str | None:
        kind, raw = entries.get(key, ("", b""))
        # A string ends with one zero byte; without it GLib reads it as empty, so it is not taken as anything.
        if kind != "s" or not raw.endswith(b"\x00") or b"\x00" in raw[:-1]:
            return None
        return raw[:-1].decode("utf-8", "replace")

    for key, want in (("ref", REF), ("runtime-repo", RUNTIME_REPO), ("collection-id", ""), ("metadata", metadata)):
        if text(key) != want:
            shown = "the app's metadata" if key == "metadata" else repr(want)
            problems.append(f"the bundle's header says {key} = {text(key)!r}, not {shown}")
    return problems


def run(*command: str) -> str:
    return subprocess.run(command, capture_output=True, text=True, check=True).stdout


def check(bundle: Path, archive: Path) -> list[str]:
    version = flatpak_manifest.ARCHIVE.match(archive.name)
    if not version or bundle.name != f"nulavio-{version['version']}.x86_64.flatpak":
        raise ValueError(f"{bundle.name} is not the bundle of {archive.name}")
    problems = []
    entries = header(bundle.read_bytes())
    work = Path(tempfile.mkdtemp(prefix="nulavio-flatpak-check-"))
    try:
        with tarfile.open(archive) as tar:
            tar.extractall(work / "archive", filter="data")
        repo = work / "repo"
        run("ostree", "init", "--mode=archive-z2", f"--repo={repo}")
        run("flatpak", "build-import-bundle", str(repo), str(bundle))
        refs = run("ostree", "refs", f"--repo={repo}").split()
        if refs != [REF]:
            problems.append(f"the bundle's refs are {refs}, not [{REF}]")
            return problems
        run("ostree", "checkout", f"--repo={repo}", "-U", REF, str(work / "checkout"))
        metadata = (work / "checkout" / "metadata").read_text(encoding="utf-8")
        problems += compare_checkout(work / "checkout", work / "archive", version["version"])
        problems += compare_metadata(metadata)
        problems += compare_header(entries, metadata)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        problems = check(args.bundle, args.archive)
    except (ValueError, OSError, tarfile.TarError) as exc:
        print(f"check_flatpak_bundle: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"check_flatpak_bundle: {' '.join(exc.cmd[:2])} failed: {(exc.stderr or '').strip()[-300:]}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"check_flatpak_bundle: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"check_flatpak_bundle: {args.bundle.name} is {args.archive.name}, with what flatpak_manifest.py adds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
