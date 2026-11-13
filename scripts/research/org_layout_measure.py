#!/usr/bin/env python3
"""Measurements for the repository layout decision (issue #97, ADR 0013).

    python3 -I scripts/research/org_layout_measure.py [--ref origin/main] > evidence.json

Reads only git: the tree and the history of one ref. Sizes, how much of the pack is media,
what an agent has to read per area, and how often a change to one component also changes
another. CI numbers and clone times are measured separately (see the evidence document).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import PurePosixPath

MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".webm", ".mp4", ".woff2", ".jar"}

# Component a path belongs to once build scripts, CI files and tests are counted with what they
# build, deploy or test. First match wins. "shared" is what every component leans on.
COMPONENTS = (
    ("site", ("site/", "scripts/site/", "ci/site/", ".github/workflows/site.yml", "tests/unit/test_site.py")),
    (
        "android",
        (
            "android/",
            "tests/unit/test_companion_build.py",
            "tests/integration/test_companion_emulator.py",
            "scripts/upstream/review_gradle_verification.py",
        ),
    ),
    (
        "release",
        (
            "scripts/release/",
            "packaging/",
            "ci/aws/",
            "ci/containers/",
            "sbom/",
            ".github/workflows/release.yml",
            ".github/workflows/release-signing-check.yml",
            ".github/workflows/repeatable.yml",
            ".github/workflows/asan.yml",
            ".github/workflows/upstream.yml",
            "contrib/",
            "tests/unit/test_release_",
            "tests/unit/test_sbom.py",
            "tests/unit/test_flatpak.py",
            "tests/unit/test_kms_import_key.py",
            "tests/unit/test_openpgp_sign.py",
            "tests/unit/test_upstream_fast_path.py",
            "tests/unit/test_dependency_pins.py",
        ),
    ),
    (
        "process",
        (
            ".github/",
            "scripts/ci/",
            "scripts/security/",
            "scripts/git-hooks/",
            "scripts/review/",
            "ci/sast/",
            "tests/fixtures/sast/",
            "tests/fixtures/claude-code/",
            "tests/unit/test_ai_review.py",
            "tests/unit/test_post_ai_review.py",
            "tests/unit/test_repo_hygiene.py",
            "tests/unit/test_security_tooling.py",
            "tests/unit/test_ci_changes.py",
            "AGENTS.md",
            "CLAUDE.md",
            "CONTRIBUTING.md",
            "GOVERNANCE.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
            "docs/process/",
        ),
    ),
    ("design-media", ("docs/design/", "docs/brand/")),
    ("docs", ("docs/", "README", "CHANGELOG.md", "LICENSE", "LICENSES.md")),
    ("launcher", ("launcher/", "bin/")),
    ("browser", ("browser/", "scripts/build/", "scripts/upstream/", "scripts/brand/", "scripts/research/")),
    ("tests", ("tests/",)),
)
# The product: components that ship in one package and are tested by the same suites.
PRODUCT = {"browser", "launcher", "tests"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, check=True, text=True).stdout


def component(path: str) -> str:
    for name, prefixes in COMPONENTS:
        if any(path == p or path.startswith(p) for p in prefixes):
            return name
    return "shared"


def tree(ref: str) -> list[tuple[str, int]]:
    out = git("ls-tree", "-r", "-l", "-z", ref)
    files = []
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        size = meta.split()[3]
        files.append((path, int(size) if size != "-" else 0))
    return files


def text_lines(ref: str, paths: list[str]) -> dict[str, int]:
    """Line count per text file, read from the object store in one pass."""
    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        input="".join(f"{ref}:{p}\n" for p in paths).encode(),
        capture_output=True,
        check=True,
    )
    data, lines, pos = proc.stdout, {}, 0
    for path in paths:
        end = data.index(b"\n", pos)
        size = int(data[pos:end].split()[2])
        body = data[end + 1 : end + 1 + size]
        lines[path] = body.count(b"\n")
        pos = end + 1 + size + 1
    return lines


def history_blobs(ref: str) -> dict[str, list[int]]:
    """Top-level area -> [bytes on disk in the pack, uncompressed bytes] over every blob the ref reaches."""
    objects = git("rev-list", "--objects", ref)
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objecttype) %(objectsize) %(objectsize:disk) %(rest)"],
        input=objects.encode(),
        capture_output=True,
        check=True,
    )
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for line in proc.stdout.decode().splitlines():
        kind, size, disk, *rest = line.split(" ", 3)
        if kind != "blob" or not rest:
            continue
        path = rest[0]
        bucket = "media" if PurePosixPath(path).suffix.lower() in MEDIA else "text"
        for key in (f"{component(path)}:{bucket}", f"all:{bucket}"):
            totals[key][0] += int(disk)
            totals[key][1] += int(size)
    return dict(totals)


def coupling(ref: str) -> dict:
    """Per commit on the ref's first-parent line: which components it changes."""
    log = git("log", "--first-parent", "--name-only", "--format=%x00%H%x09%an%x09%s", ref)
    commits = []
    for chunk in log.split("\0")[1:]:
        head, *paths = chunk.strip("\n").split("\n")
        sha, author, subject = head.split("\t", 2)
        touched = Counter(component(p) for p in paths if p)
        commits.append({"sha": sha[:9], "author": author, "subject": subject, "components": touched})
    human = [c for c in commits if "dependabot" not in c["author"]]
    code = {"site", "android", "release", "process", "launcher", "browser"}
    per_component = {}
    for name in sorted(code):
        touching = [c for c in human if name in c["components"]]
        others = Counter()
        alone = 0
        for c in touching:
            rest = (set(c["components"]) & code) - {name}
            if name in PRODUCT:
                rest -= PRODUCT
            if not rest:
                alone += 1
            others.update(rest)
        per_component[name] = {
            "commits": len(touching),
            "without_another_code_component": alone,
            "also_changes": dict(others.most_common()),
        }
    product_code = {"browser", "launcher"}
    return {
        "commits_first_parent": len(commits),
        "commits_not_dependabot": len(human),
        "touching_more_than_one_code_component": sum(1 for c in human if len(set(c["components"]) & code) > 1),
        "touching_product_and_site": sum(1 for c in human if "site" in c["components"] and set(c["components"]) & product_code),
        "touching_product_and_android": sum(
            1 for c in human if "android" in c["components"] and set(c["components"]) & product_code
        ),
        "per_component": per_component,
        "site_with_product": [
            f"{c['sha']} {c['subject']}" for c in human if "site" in c["components"] and set(c["components"]) & product_code
        ],
        "android_with_product": [
            f"{c['sha']} {c['subject']}" for c in human if "android" in c["components"] and set(c["components"]) & product_code
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="origin/main")
    args = parser.parse_args()

    files = tree(args.ref)
    text_paths = [p for p, _ in files if PurePosixPath(p).suffix.lower() not in MEDIA]
    lines = text_lines(args.ref, text_paths)
    areas: dict[str, dict[str, int]] = defaultdict(lambda: Counter())
    for path, size in files:
        area = areas[component(path)]
        area["files"] += 1
        if path in lines:
            area["text_files"] += 1
            area["text_lines"] += lines[path]
            area["text_bytes"] += size
        else:
            area["media_files"] += 1
            area["media_bytes"] += size
    for area in areas.values():
        # A rough guide only: about four bytes of source or English prose per model token.
        area["text_tokens_estimate"] = area["text_bytes"] // 4

    result = {
        "ref": args.ref,
        "commit": git("rev-parse", args.ref).strip(),
        "commit_date": git("log", "-1", "--format=%cI", args.ref).strip(),
        "tree": {name: dict(area) for name, area in sorted(areas.items())},
        "tree_total": {
            "files": len(files),
            "text_bytes": sum(a["text_bytes"] for a in areas.values()),
            "media_bytes": sum(a["media_bytes"] for a in areas.values()),
        },
        "history_blob_bytes_packed_and_raw": history_blobs(args.ref),
        "coupling": coupling(args.ref),
    }
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
