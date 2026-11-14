#!/usr/bin/env python3
"""What's new in each Nulavio version: the record people read, in the site and in the browser (#198).

One reviewed file per version, packaging/whats-new/<firefox>-<release>.json, written in a
pull request before the version is built. It is the editorial summary for people; the
complete technical history stays in the GitHub release and CHANGELOG.md. The site builds
its pages from it (/novidades/, /en/whats-new/) for the versions packaging/release.json
says are published, and the release refuses to publish a version that has none, so the
notes are fixed in the commit that is built and signed.

    python3 -I scripts/release/whats_new.py check                    # every record is valid
    python3 -I scripts/release/whats_new.py require <version> [--at <commit>]

A record:

    {
      "version": "160.0-0.4",            # the file's name, and the tag without its "v"
      "date": "2026-11-14",              # when it was published (or is to be)
      "channel": "alpha",
      "firefox": "160.0",                # the Firefox release inside
      "pt-BR": {"summary": "...", "new": [...], "fixed": [...], "action": [...], "breaking": [...]},
      "en-US": {... the same keys ...},
      "security": ["GHSA-xxxx-xxxx-xxxx", ...]   # optional: published advisories only
    }

Plain text only (no HTML, Markdown links or addresses): the pages and the browser escape
it and add the links themselves. Both languages say the same, by hand, not by an
unreviewed translation. "summary" is required; the lists are optional. A security entry
is a published advisory's GHSA identifier: a vulnerability that is not fixed and
released never goes here (docs/process/private-work.md).
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = Path("packaging") / "whats-new"
LOCALES = ("pt-BR", "en-US")
LISTS = ("new", "fixed", "action", "breaking")
VERSION = re.compile(r"(?P<firefox>[0-9]+(?:\.[0-9]+)+)-(?P<release>[0-9]+(?:\.[0-9]+)*)")
GHSA = re.compile(r"GHSA(?:-[23456789cfghjmpqrvwx]{4}){3}")
CHANNELS = ("alpha", "beta", "stable")
SUMMARY_MAX, ITEM_MAX, ITEMS_MAX = 500, 300, 20
# Plain text: no markup, no link syntax, no address, no control characters.
NOT_PLAIN = re.compile(r"[<>`\[\]\x00-\x08\x0b-\x1f\x7f]|https?://|www\.|\]\(|@")


class RecordError(ValueError):
    pass


def version_key(version: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    match = VERSION.fullmatch(version)
    if not match:
        raise RecordError(f"{version!r} is not <firefox>-<release>")
    return tuple(map(int, match["firefox"].split("."))), tuple(map(int, match["release"].split(".")))


def _text(value: object, where: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{where}: empty or not text")
    if value != value.strip() or "  " in value or "\n" in value:
        raise RecordError(f"{where}: one line, single spaces, nothing around it")
    if len(value) > limit:
        raise RecordError(f"{where}: longer than {limit} characters")
    if NOT_PLAIN.search(value):
        raise RecordError(f"{where}: plain text only (no markup, link, address or control character)")
    return value


def validate(data: object, name: str | None = None) -> dict:
    """The record, checked; `name` is its file name when it came from one."""
    if not isinstance(data, dict):
        raise RecordError("a record is a JSON object")
    known = {"version", "date", "channel", "firefox", "security", *LOCALES}
    if set(data) - known or {"version", "date", "channel", "firefox", *LOCALES} - set(data):
        raise RecordError(f"the keys must be {sorted(known)} (security optional)")
    version = data["version"]
    version_key(version)
    if name is not None and name != f"{version}.json":
        raise RecordError(f"{name}: the file must be named {version}.json")
    if data["firefox"] != VERSION.fullmatch(version)["firefox"]:
        raise RecordError(f"{version}: firefox {data['firefox']!r} is not the version's")
    try:
        datetime.date.fromisoformat(data["date"])
    except (TypeError, ValueError):
        raise RecordError(f"{version}: date must be YYYY-MM-DD") from None
    if data["channel"] not in CHANNELS:
        raise RecordError(f"{version}: channel must be one of {CHANNELS}")
    shapes = set()
    for locale in LOCALES:
        entry = data[locale]
        if not isinstance(entry, dict) or set(entry) - {"summary", *LISTS} or "summary" not in entry:
            raise RecordError(f"{version} {locale}: summary, and optionally {', '.join(LISTS)}")
        _text(entry["summary"], f"{version} {locale} summary", SUMMARY_MAX)
        for key in LISTS:
            items = entry.get(key, [])
            if not isinstance(items, list) or len(items) > ITEMS_MAX:
                raise RecordError(f"{version} {locale} {key}: a list of at most {ITEMS_MAX}")
            for i, item in enumerate(items):
                _text(item, f"{version} {locale} {key}[{i}]", ITEM_MAX)
        shapes.add(tuple(len(entry.get(key, [])) for key in LISTS))
    if len(shapes) != 1:
        raise RecordError(f"{version}: both languages must have the same items in each list")
    security = data.get("security", [])
    if not isinstance(security, list) or any(not isinstance(s, str) or not GHSA.fullmatch(s) for s in security):
        raise RecordError(f"{version}: security lists published advisories by GHSA identifier")
    return data


def records(repo: Path = ROOT) -> list[dict]:
    """Every record in the tree, newest version first."""
    found = []
    for path in sorted((repo / DIRECTORY).glob("*")):
        if path.name == ".gitkeep":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RecordError(f"{path.name}: {e}") from None
        found.append(validate(data, path.name))
    return sorted(found, key=lambda r: version_key(r["version"]), reverse=True)


def published(repo: Path = ROOT, through: str | None = None) -> list[dict]:
    """The records of versions up to the published one (packaging/release.json, or `through`),
    newest first. A record for a version not released yet is not shown anywhere."""
    if through is None:
        try:
            through = json.loads((repo / "packaging" / "release.json").read_text(encoding="utf-8")).get("version") or None
        except FileNotFoundError:
            through = None
    if not through:
        return []
    limit = version_key(through)
    return [r for r in records(repo) if version_key(r["version"]) <= limit]


def require(version: str, repo: Path = ROOT, at: str | None = None) -> dict:
    """The record of `version`, as committed at `at` (a commit), or in the tree."""
    version_key(version)
    path = DIRECTORY / f"{version}.json"
    if at is None:
        if not (repo / path).is_file():
            raise RecordError(f"no {path}: write what is new in {version} (both languages) before releasing it")
        text = (repo / path).read_text(encoding="utf-8")
    else:
        shown = subprocess.run(["git", "-C", str(repo), "show", f"{at}:{path.as_posix()}"], capture_output=True, text=True)
        if shown.returncode != 0:
            raise RecordError(f"no {path} at {at[:12]}: write what is new in {version} before releasing it")
        text = shown.stdout
    try:
        data = json.loads(text)
    except ValueError as e:
        raise RecordError(f"{path}: {e}") from None
    return validate(data, path.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="every record in the tree is valid")
    need = commands.add_parser("require", help="the version has a valid record")
    need.add_argument("version")
    need.add_argument("--at", help="the commit to read it from (default: the working tree)")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(f"whats_new: {len(records())} record(s) valid")
        else:
            require(args.version, at=args.at)
            print(f"whats_new: {args.version} has its record")
    except RecordError as error:
        print(f"whats_new: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
