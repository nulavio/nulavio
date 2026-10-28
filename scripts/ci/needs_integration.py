#!/usr/bin/env python3
"""Does this push or pull request need the engine integration run? (job `changes` of ci.yml)

The integration matrix is the most expensive part of CI (two images, about ten
minutes each), and the repository's Actions minutes are limited. It is skipped
only when every file changed since the last tested tree is Markdown: no
integration test reads a Markdown file's content (test_confined only checks
that README.md is readable through the sandbox, whatever it says).

The last tested tree:
- pull request: its base (BASE...HEAD covers the whole pull request, so a
  cancelled earlier run of the same pull request loses nothing);
- push to main: the head of the newest successful ci run on main (push or
  schedule), read from the Actions API. Not the previous push: a newer push
  cancels the run still testing the previous one, so that one may never have
  been tested. A successful run either ran the integration matrix or skipped it
  because its own changes were Markdown only, so by induction its head is as
  tested as the last full run.
Anything else, an unknown event, an API or git error, a base that is not an
ancestor of HEAD, or an empty list of changes, means the run happens. The unit
tests, which do read the docs, always run; so does the weekly scheduled run.

Reads EVENT, BASE (pull request), GITHUB_REPOSITORY and GH_TOKEN (push) from
the environment, never from expressions inside the workflow script. Prints
`integration=true|false` and `base=<sha or empty>` (shown in the job log).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable

SHA = re.compile(r"[0-9a-f]{40}")
REPO = re.compile(r"[\w.-]+/[\w.-]+")


def needs_integration(changed: list[str] | None) -> bool:
    if not changed:
        return True
    return not all(path.lower().endswith(".md") for path in changed)


def _gh(args: list[str]) -> str | None:
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def last_green(repo: str, gh: Callable[[list[str]], str | None] = _gh) -> str | None:
    """Head of the newest successful ci run on main from a push or the schedule, in this repository."""
    if not REPO.fullmatch(repo):
        return None
    out = gh(["api", f"repos/{repo}/actions/workflows/ci.yml/runs?branch=main&status=success&per_page=30"])
    try:
        runs = json.loads(out or "")["workflow_runs"]
    except (ValueError, KeyError, TypeError):
        return None
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict) or run.get("event") not in ("push", "schedule"):
            continue
        if (run.get("head_repository") or {}).get("full_name") != repo or run.get("head_branch") != "main":
            continue  # a pull request from a fork's own "main" branch is not this repository's main
        head = run.get("head_sha")
        return head if isinstance(head, str) and SHA.fullmatch(head) else None
    return None


def base_for(event: str, pr_base: str, repo: str, gh: Callable[[list[str]], str | None] = _gh) -> str | None:
    ref = {"pull_request": lambda: pr_base, "push": lambda: last_green(repo, gh)}.get(event, lambda: None)() or ""
    if not SHA.fullmatch(ref) or set(ref) == {"0"}:
        return None
    if _git(["merge-base", "--is-ancestor", ref, "HEAD"]).returncode != 0:
        return None  # not in this clone, or main was rewritten: run everything
    return ref


def changed_files(base: str | None) -> list[str] | None:
    if base is None:
        return None
    result = _git(["diff", "--name-only", "--no-renames", f"{base}...HEAD"])
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    env = os.environ
    base = base_for(env.get("EVENT", ""), env.get("BASE", ""), env.get("GITHUB_REPOSITORY", ""))
    changed = changed_files(base)
    decision = needs_integration(changed)
    shown = "unknown" if changed is None else f"{len(changed)} file(s) since {base[:12]}"
    print(f"changes: {shown}; integration needed: {decision}", file=sys.stderr)
    print(f"integration={'true' if decision else 'false'}")
    print(f"base={base or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
