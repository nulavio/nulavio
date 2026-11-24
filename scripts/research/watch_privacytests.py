#!/usr/bin/env python3
"""Has PrivacyTests.org changed the fingerprinting probes this repository runs a pinned copy of (#79)?

    python3 -I scripts/research/watch_privacytests.py [--ref master] [--summary FILE]

tests/fixtures/privacytests/ holds their probe pages at one commit, and tests/integration/test_privacytests.py
mirrors their pass rule. They add probes and change the rule; a pinned copy would go on passing without them.
This compares what their repository has now with tests/fixtures/privacytests/pinned.json:

- each copied file, whole, by SHA-256;
- their two scoring scripts for the Settings and Screen groups, whole;
- the two functions that score the Device group, cut out of larger files that change for other reasons;
- every line of their harness that says "fingerprint", which is where a new group of probes would be wired in.

It also says when PrivacyTests.org's published results moved (#437): nulavio.net's comparison is built from
tests/fixtures/privacytests/published.json, which keeps the SHA-256 of their page and of their data file. When
either differs, `python3 -I scripts/site/privacytests_pages.py refresh` brings the comparison up to date.

It reads raw.githubusercontent.com and privacytests.org only, sends nothing, and runs nothing it downloads.
Exit: 0 nothing changed; 1 something changed (the list says what); 2 their repository or site could not be read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PINNED = ROOT / "tests" / "fixtures" / "privacytests" / "pinned.json"
PUBLISHED = ROOT / "tests" / "fixtures" / "privacytests" / "published.json"
RAW = "https://raw.githubusercontent.com/privacytests/privacytests"
LIMIT = 2 * 1024 * 1024  # no file of their repository that is read here comes near it
PUBLISHED_LIMIT = 64 * 1024 * 1024  # their published data file was 5.5 MB on 2026-11-20


class WatchError(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def function_body(source: str, name: str) -> str | None:
    """`const <name> = … };` as their scripts write a top-level function: from its `const` to the first line
    that is `};` alone. None when the name is not there."""
    match = re.search(rf"^const {re.escape(name)} = .*?^\}};$", source, re.S | re.M)
    return match.group(0) if match else None


def mentions(source: str) -> str:
    """The lines that say "fingerprint", without their indentation: a new group of probes adds or changes one."""
    return "\n".join(line.strip() for line in source.splitlines() if "fingerprint" in line.lower())


def fetch(ref: str, path: str) -> bytes:
    return fetch_url(f"{RAW}/{ref}/{path}", LIMIT, path)


def fetch_url(url: str, limit: int, name: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "nulavio-watch-privacytests"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # a fixed https address
            data = response.read(limit + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise WatchError(f"{name}: {error}") from None
    if len(data) > limit:
        raise WatchError(f"{name}: larger than {limit} bytes")
    return data


def published_moved(published: dict, read) -> list[str]:
    """Which of PrivacyTests.org's published files differ from the ones the comparison was built from.
    `read(url)` returns the file's bytes now."""
    moved = []
    for kind in ("page", "data"):
        source = published["sources"][kind]
        if digest(read(source["url"])) != source["sha256"]:
            moved.append(f"{source['url']} changed (it was {source['last_modified']}, SHA-256 {source['sha256'][:12]}…)")
    return moved


def compare(pinned: dict, read) -> list[str]:
    """What differs from the pins, in words. `read(path)` returns the file's bytes now, or None when it is gone."""
    changed = []
    for path, want in sorted(pinned["files"].items()):
        data = read(path)
        if data is None:
            changed.append(f"`{path}` is gone")
        elif digest(data) != want:
            changed.append(f"`{path}` changed")
    for path, functions in sorted(pinned["functions"].items()):
        data = read(path)
        source = data.decode("utf-8", "replace") if data is not None else ""
        for name, want in sorted(functions.items()):
            body = function_body(source, name)
            if body is None:
                changed.append(f"`{name}` is no longer in `{path}`")
            elif digest(body.encode()) != want:
                changed.append(f"`{name}` in `{path}` changed")
    for path, want in sorted(pinned["mentions"].items()):
        data = read(path)
        if data is None:
            changed.append(f"`{path}` is gone")
        elif digest(mentions(data.decode("utf-8", "replace")).encode()) != want:
            changed.append(f'the lines of `{path}` that say "fingerprint" changed (a new group of probes?)')
    return changed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="master", help="their branch, tag or commit (default: master, their default branch)")
    parser.add_argument("--summary", type=Path, help="append the verdict to this file (a job summary)")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", args.ref) or ".." in args.ref:
        parser.error("--ref: a branch, tag or commit name")
    pinned = json.loads(PINNED.read_text(encoding="utf-8"))

    def read(path: str) -> bytes | None:
        try:
            return fetch(args.ref, path)
        except WatchError as error:
            if "HTTP Error 404" in str(error):
                return None
            raise

    try:
        changed = compare(pinned, read)
    except WatchError as error:
        lines, code = [f"PrivacyTests' repository could not be read: {error}. No verdict."], 2
    else:
        if changed:
            lines = [
                f"PrivacyTests' fingerprinting probes differ from the copy pinned at `{pinned['commit'][:12]}`:",
                "",
                *[f"- {item}" for item in changed],
                "",
                "Read what changed, copy the files again, update `tests/fixtures/privacytests/pinned.json` and the",
                "pass rule in `tests/integration/test_privacytests.py` (tests/fixtures/privacytests/README.md).",
            ]
            code = 1
        else:
            lines, code = [f"PrivacyTests' fingerprinting probes are the ones pinned at `{pinned['commit'][:12]}`."], 0
    # Their published results, apart: a change there is not a change of the probes, and the other way round.
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    try:
        moved = published_moved(published, lambda url: fetch_url(url, PUBLISHED_LIMIT, url))
    except WatchError as error:
        results, code = [f"PrivacyTests.org's published results could not be read: {error}. No verdict."], max(code, 2)
    else:
        if moved:
            results = [
                f"PrivacyTests.org's published results moved since No. {published['issue']} ({published['updated']}), "
                "the one nulavio.net's comparison shows:",
                "",
                *[f"- {item}" for item in moved],
                "",
                "Run `python3 -I scripts/site/privacytests_pages.py refresh`, read the diff and open a pull request.",
            ]
            code = max(code, 1)
        else:
            results = [f"PrivacyTests.org's published results are No. {published['issue']}, the ones nulavio.net shows."]
    text, published_text = "\n".join(lines), "\n".join(results)
    print(text)
    print(published_text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as out:
            out.write(f"## PrivacyTests' probes against the pinned copy\n\n{text}\n")
            out.write(f"\n## PrivacyTests.org's published results\n\n{published_text}\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
