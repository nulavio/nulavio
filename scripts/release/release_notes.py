#!/usr/bin/env python3
"""Generate release notes from public history, or validate a squash PR title (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from pathlib import Path

# Also accept established historical commit types. New squash titles use this same grammar.
CONVENTIONAL = re.compile(
    r"(feat|fix|security|docs|test|chore|build|ci|perf|refactor|style|revert)"
    r"(?:\(([^()\r\n]+)\))?(!)?: (\S[^\r\n]*)"
)
TAG = re.compile(r"v([0-9]+(?:\.[0-9]+)+)-([0-9]+(?:\.[0-9]+)*)")
GROUPS = {"feat": "Features", "fix": "Fixes", "security": "Security-related changes", "perf": "Performance",
          "docs": "Documentation", "test": "Tests", "chore": "Maintenance", "build": "Build and CI", "ci": "Build and CI",
          "refactor": "Maintenance", "style": "Maintenance", "revert": "Reverts"}  # fmt: skip
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import whats_new  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def version_key(tag: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    match = TAG.fullmatch(tag)
    if not match:
        raise ValueError("tag must be v<firefox>-<revision>")
    return tuple(int(n) for n in match[1].split(".")), tuple(int(n) for n in match[2].split("."))


def safe_text(text: str) -> str:
    text = html.escape(text, quote=False).replace("@", "&#64;")
    return re.sub(r"([\\`*_[\]<>])", r"\\\1", text)


def changes(repo: Path, commit: str, tag: str, repository: str) -> str:
    target_key = version_key(tag)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("release commit must be a full SHA-1")
    git(repo, "merge-base", "--is-ancestor", commit, "HEAD")
    # Only tags on this commit's first-parent line: a tag on a merged topic is not a release boundary.
    line = set(git(repo, "rev-list", "--first-parent", commit).splitlines())
    candidates = []
    for candidate in git(repo, "tag", "--merged", commit, "--list", "v*").splitlines():
        if (
            TAG.fullmatch(candidate)
            and version_key(candidate) < target_key
            and git(repo, "rev-parse", f"refs/tags/{candidate}^{{commit}}") in line
        ):
            candidates.append(candidate)
    previous = max(candidates, key=version_key) if candidates else None
    revision = f"refs/tags/{previous}..{commit}" if previous else commit
    log = git(repo, "log", "--first-parent", "--reverse", "--format=%H%x09%s", revision)
    groups: dict[str, list[str]] = {}
    url = f"https://github.com/{repository}"
    for row in log.splitlines():
        sha, subject = row.split("\t", 1)
        match = CONVENTIONAL.fullmatch(subject)
        heading = "Other changes"
        if match:
            kind, scope, breaking, message = match.groups()
            heading = "Breaking changes" if breaking else GROUPS[kind]
            subject = f"{scope}: {message}" if scope else message
        groups.setdefault(heading, []).append(f"- {safe_text(subject)} ([{sha[:12]}]({url}/commit/{sha}))")
    sections = []
    for heading in dict.fromkeys(["Breaking changes", *GROUPS.values(), "Other changes"]):
        if heading in groups:
            sections.append(f"## {heading}\n\n" + "\n".join(groups[heading]))
    if not sections:
        sections.append("No source commits since the previous release (package rebuild).")
    if previous:
        sections.append(f"[Full changelog]({url}/compare/{previous}...{commit})")
    else:
        sections.append(f"[Initial release history]({url}/commits/{commit})")
    return "\n\n".join(sections)


def notes(info: dict, repo: Path, repository: str, fingerprint: str, run_url: str, flatpak: str | None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid GitHub repository")
    version_key(info["tag"])
    if info["tag"].split("-")[0] != f"v{info['firefox']}":
        raise ValueError("tag and Firefox version disagree")
    if not re.fullmatch(r"[0-9A-F]{40}", fingerprint):
        raise ValueError("invalid signing fingerprint")
    if not re.fullmatch(rf"https://github\.com/{re.escape(repository)}/actions/runs/[0-9]+", run_url):
        raise ValueError("invalid provenance run URL")
    body = changes(repo, info["commit"], info["tag"], repository)
    # What is new for people, from the reviewed record committed with the release (#198): the same
    # text as the site and the browser. A release without one stops here, before anything is signed.
    record = whats_new.require(info["tag"][1:], repo, at=info["commit"])
    english = record["en-US"]
    lists = [
        ("Changes that need your attention", "breaking"),
        ("What to do", "action"),
        ("What is new", "new"),
        ("Fixes", "fixed"),
    ]
    summary = [safe_text(english["summary"])]
    for heading, key in lists:
        if english.get(key):
            summary.append(f"### {heading}\n\n" + "\n".join(f"- {safe_text(item)}" for item in english[key]))
    version = info["tag"][1:]
    summary.append(
        f"In Portuguese and English: https://nulavio.net/novidades/{version}/ and https://nulavio.net/en/whats-new/{version}/"
    )
    systems = "Fedora or Ubuntu" if info.get("debs") else "Fedora"
    install = f"Install or upgrade on {systems}: https://nulavio.net/en/download/"
    if info.get("debs"):
        # The download page asks Ubuntu users to compare the source file with this hash: a second place
        # to read it, outside the site.
        # The file as of the release's commit, which is what the site served when it was published.
        shown = subprocess.run(["git", "-C", str(repo), "show", f"{info['commit']}:site/apt/nulavio.sources"],
                               capture_output=True, check=True).stdout  # fmt: skip
        sources = hashlib.sha256(shown).hexdigest()
        install += f"\n\nOn Ubuntu, `nulavio.sources` from the download page has the SHA-256 `{sources}`."
    if flatpak:
        if flatpak != f"nulavio-{info['tag'][1:]}.x86_64.flatpak":
            raise ValueError("unexpected Flatpak bundle name")
        install += f"\n\nOther distributions, with Flatpak:\n\n```sh\nflatpak install --user {flatpak}\n```"
    return (
        f"Nulavio {info['tag'][1:]}, built from Firefox {info['firefox']} (commit {info['commit'][:12]}).\n\n"
        "## What's new\n\n" + "\n\n".join(summary) + "\n\n"
        f"{body}\n\n## Install and verify\n\n{install}\n\n"
        f"Every release asset is covered by `SHA256SUMS.asc` (key `{fingerprint}`) and a GitHub build-provenance attestation.\n\n"
        f"```sh\ngh attestation verify <file> --repo {repository}\n```\n\n"
        f"[Build and test run]({run_url}).\n\n"
        f"[Security changelog](https://github.com/{repository}/blob/main/docs/security/changelog.md) "
        "and [published advisories](https://github.com/" + repository + "/security/advisories). "
        "Commit categories are not a vulnerability assessment.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-title", help="read the title from GITHUB_EVENT_PATH")
    generate = sub.add_parser("notes")
    generate.add_argument("--repo", type=Path, default=ROOT)
    generate.add_argument("--release", type=Path, required=True)
    generate.add_argument("--repository", required=True)
    generate.add_argument("--fingerprint", required=True)
    generate.add_argument("--run-url", required=True)
    generate.add_argument("--flatpak")
    args = parser.parse_args()
    try:
        if args.command == "check-title":
            import os

            title = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())["pull_request"]["title"]
            if not CONVENTIONAL.fullmatch(title):
                raise ValueError("PR title must be a Conventional Commit, e.g. fix(shell): preserve the selected tab")
        else:
            print(notes(json.loads(args.release.read_text()), args.repo, args.repository,
                        args.fingerprint, args.run_url, args.flatpak), end="")  # fmt: skip
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"release_notes: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
