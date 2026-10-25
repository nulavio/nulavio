#!/usr/bin/env python3
"""Fetch Firefox translations for a verified source tree (Track B).

Each locale is taken from github.com/mozilla-l10n/firefox-l10n at the
revision Mozilla signed off for this release. That revision is read from
<source>/browser/locales/l10n-changesets.json, which is part of the
signature-verified source tarball, and git checks every fetched object
against it. Only the requested locale directories are downloaded (partial,
sparse fetch). Nulavio's own translations (browser/l10n/<locale>/, e.g. the
brand names) are then laid over them.

    python3 -I scripts/upstream/fetch_firefox_l10n.py --source <firefox-src> \
        --dest ~/.cache/nulavio-build/mozbuild/l10n-central --git-dir ~/.cache/nulavio-build/l10n-git pt-BR
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "browser" / "l10n"
REMOTE = "https://github.com/mozilla-l10n/firefox-l10n.git"
STAMP = ".nulavio-l10n-revision"
LOCALE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2}|-[a-zA-Z]+)*$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def revisions(source: Path, locales: list[str]) -> dict[str, str]:
    """Map each locale to its signed-off firefox-l10n revision."""
    changesets = json.loads((source / "browser" / "locales" / "l10n-changesets.json").read_text(encoding="utf-8"))
    out = {}
    for locale in locales:
        if not LOCALE_RE.match(locale):
            raise SystemExit(f"invalid locale name: {locale!r}")
        entry = changesets.get(locale)
        if not entry or "linux64" not in entry.get("platforms", []):
            raise SystemExit(f"{locale} is not shipped by Mozilla for linux64 in this release")
        revision = entry["revision"]
        if not REVISION_RE.match(revision):
            raise SystemExit(f"unexpected revision for {locale}: {revision!r}")
        out[locale] = revision
    return out


def git(git_dir: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(["git", "-C", str(git_dir), *args], check=True, capture_output=True, text=True, env=env)
    return result.stdout.strip()


def fetch(git_dir: Path, locale: str, revision: str) -> Path:
    if not (git_dir / ".git").exists():
        git_dir.mkdir(parents=True, exist_ok=True)
        git(git_dir, "init", "-q")
        git(git_dir, "remote", "add", "origin", REMOTE)
    git(git_dir, "sparse-checkout", "set", "--no-cone", f"/{locale}/")
    git(git_dir, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", revision)
    git(git_dir, "-c", "advice.detachedHead=false", "checkout", "-q", "--force", revision)
    head = git(git_dir, "rev-parse", "HEAD")
    if head != revision:
        raise SystemExit(f"checked out {head}, expected {revision}")
    return git_dir / locale


def install(git_dir: Path, dest: Path, locale: str, revision: str) -> None:
    target = dest / locale
    stamp = target / STAMP
    if not (stamp.exists() and stamp.read_text().strip() == revision):
        checkout = fetch(git_dir, locale, revision)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(checkout, target, ignore=shutil.ignore_patterns(".git"))
        stamp.write_text(revision + "\n")
    overlay = OVERLAY / locale
    if overlay.is_dir():
        shutil.copytree(overlay, target, dirs_exist_ok=True)
    print(f"{locale}: firefox-l10n {revision[:12]}" + (" + Nulavio overlay" if overlay.is_dir() else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, required=True, help="verified Firefox source tree")
    parser.add_argument("--dest", type=Path, required=True, help="L10NBASEDIR (one directory per locale)")
    parser.add_argument("--git-dir", type=Path, required=True, help="working repository for the sparse fetch")
    parser.add_argument("locales", nargs="+")
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    for locale, revision in revisions(args.source, args.locales).items():
        install(args.git_dir, args.dest, locale, revision)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
