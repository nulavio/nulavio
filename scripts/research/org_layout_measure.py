#!/usr/bin/env python3
"""Measurements for the repository layout decision (issue #97, ADR 0013).

    python3 -I scripts/research/org_layout_measure.py --ref <commit> > evidence.json

At each release (the publish job of .github/workflows/release.yml), only the media in the
history, against the budget of ADR 0013, point 3:

    python3 -I scripts/research/org_layout_measure.py --budget --ref HEAD [--summary FILE]

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
            ".agents/skills/",
            ".mwgrc",
            ".github/",
            "scripts/dev/",
            "scripts/ci/",
            "scripts/security/",
            "scripts/git-hooks/",
            "scripts/review/",
            "ci/sast/",
            "ci/modern-web-guidance/",
            "tests/fixtures/sast/",
            "tests/fixtures/claude-code/",
            "tests/unit/test_ai_review.py",
            "tests/unit/test_post_ai_review.py",
            "tests/unit/test_repo_hygiene.py",
            "tests/unit/test_security_tooling.py",
            "tests/unit/test_ci_changes.py",
            "tests/unit/test_modern_web_guidance.py",
            "tests/unit/test_agent_skills.py",
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
# Policy text that "process" holds besides CI and review tooling. Counting an edit to CONTRIBUTING.md
# as a change to a code component is a choice; the coupling is also reported without it.
POLICY_TEXT = ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "GOVERNANCE.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "docs/process/")
SCREENSHOTS = "docs/design/screenshots/"


def git(*args: str) -> str:
    # quotePath off: a path with a non-ASCII character comes as it is, not quoted and escaped,
    # so it is counted with its component.
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], capture_output=True, check=True, text=True).stdout


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
        keys = [f"{component(path)}:{bucket}", f"all:{bucket}"]
        if path.startswith(SCREENSHOTS):
            keys.append("screenshots:all")
        for key in keys:
            totals[key][0] += int(disk)
            totals[key][1] += int(size)
    return dict(totals)


CODE = {"site", "android", "release", "process", "launcher", "browser"}


def _reading(paths: list[str], *, policy_is_docs: bool) -> set[str]:
    """The code components a commit changes, with or without policy text counted as "process"."""
    out = set()
    for path in paths:
        name = component(path)
        if policy_is_docs and name == "process" and any(path == p or path.startswith(p) for p in POLICY_TEXT):
            name = "docs"
        out.add(name)
    return out & CODE


def coupling(ref: str) -> dict:
    """Per commit on the ref's first-parent line: which components it changes."""
    log = git("log", "--first-parent", "--name-only", "--format=%x00%H%x09%an%x09%s", ref)
    commits = []
    for chunk in log.split("\0")[1:]:
        head, *paths = chunk.strip("\n").split("\n")
        sha, author, subject = head.split("\t", 2)
        paths = [p for p in paths if p]
        commits.append({
            "sha": sha[:9], "author": author, "subject": subject, "components": Counter(component(p) for p in paths),
            "strict": _reading(paths, policy_is_docs=True), "pull_request": subject.rstrip().endswith(")") and "(#" in subject,
        })  # fmt: skip
    human = [c for c in commits if "dependabot" not in c["author"]]
    per_component = {}
    for name in sorted(CODE):
        touching = [c for c in human if name in c["components"]]
        others = Counter()
        alone = 0
        for c in touching:
            rest = (set(c["components"]) & CODE) - {name}
            if name in PRODUCT:
                rest -= PRODUCT
            if not rest:
                alone += 1
            others.update(rest)
        strict = [c for c in human if name in c["strict"]]
        per_component[name] = {
            "commits": len(touching),
            "without_another_code_component": alone,
            "also_changes": dict(others.most_common()),
            # The same with policy text (CONTRIBUTING.md and the like) not counted as "process".
            "policy_text_apart": {
                "commits": len(strict),
                "without_another_code_component": sum(
                    1 for c in strict if not (c["strict"] - {name} - (PRODUCT if name in PRODUCT else set()))
                ),
            },
        }
    product_code = {"browser", "launcher"}

    def more_than_one(
        group: list[dict], key: str = "components", *, merge_product: bool = False, drop: frozenset = frozenset()
    ) -> int:
        count = 0
        for c in group:
            names = (set(c[key]) & CODE) - drop
            if merge_product and names & product_code:
                names = (names - product_code) | {"product"}
            count += len(names) > 1
        return count

    pull_requests = [c for c in human if c["pull_request"]]
    direct = [c for c in human if not c["pull_request"]]
    return {
        "commits_first_parent": len(commits),
        "commits_not_dependabot": len(human),
        "touching_more_than_one_code_component": more_than_one(human),
        # How much that count depends on what is called a component.
        "sensitivity": {
            "as_defined": more_than_one(human),
            "policy_text_not_process": more_than_one(human, "strict"),
            "policy_text_not_process_and_browser_launcher_as_one": more_than_one(human, "strict", merge_product=True),
            "without_process": more_than_one(human, drop=frozenset({"process"})),
        },
        # Two kinds of commit on main: squash-merged pull requests ("(#N)" in the subject) and what was pushed before them.
        "pull_request_commits": {"commits": len(pull_requests), "more_than_one": more_than_one(pull_requests)},
        "direct_commits": {"commits": len(direct), "more_than_one": more_than_one(direct)},
        "touching_product_and_site": sum(1 for c in human if "site" in c["components"] and set(c["components"]) & product_code),
        "touching_product_and_android": sum(
            1 for c in human if "android" in c["components"] and set(c["components"]) & product_code
        ),
        "touching_launcher_and_android": sum(1 for c in human if {"android", "launcher"} <= set(c["components"])),
        "per_component": per_component,
        "site_with_product": [
            f"{c['sha']} {c['subject']}" for c in human if "site" in c["components"] and set(c["components"]) & product_code
        ],
        "android_with_product": [
            f"{c['sha']} {c['subject']}" for c in human if "android" in c["components"] and set(c["components"]) & product_code
        ],
    }


# ADR 0013, point 3: above this much media in the history, as packed (three times 2026-11-13's),
# new capture sets go to a repository of their own. No history is rewritten either way.
MEDIA_BUDGET_BYTES = 250_000_000


def media_budget(ref: str, budget: int = MEDIA_BUDGET_BYTES) -> dict:
    """The media every clone downloads, against the budget."""
    media = history_blobs(ref).get("all:media", [0, 0])[0]
    return {
        "commit": git("rev-parse", ref).strip(),
        "media_bytes_packed": media,
        "budget_bytes": budget,
        "over_budget": media > budget,
    }


def budget_summary(result: dict) -> str:
    """Markdown for the release run's summary; over the budget, what ADR 0013 says to do."""
    mb = lambda n: f"{n / 1e6:.1f} MB"  # noqa: E731
    line = (f"Media in the history of {result['commit'][:12]}: {mb(result['media_bytes_packed'])}, "
            f"budget {mb(result['budget_bytes'])} (ADR 0013, point 3).")  # fmt: skip
    if not result["over_budget"]:
        return f"{line}\n"
    return (
        f"{line}\n\n**Over the budget.** New capture sets go to a repository of their own (public, no CI, no "
        "secrets, no Dependabot), linked from the documents by commit, as docs/adr/0013-repository-layout.md "
        "says. No history is rewritten.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--budget", action="store_true", help="only the media in the history, against the budget")
    parser.add_argument("--summary", help="with --budget: append a Markdown line to this file ($GITHUB_STEP_SUMMARY)")
    args = parser.parse_args()
    if args.budget:
        result = media_budget(args.ref)
        json.dump(result, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as summary:
                summary.write(budget_summary(result))
        if result["over_budget"]:
            print("::warning title=Media budget::the history holds more media than ADR 0013 allows (see the summary)",
                  file=sys.stderr)  # fmt: skip
        return 0

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
