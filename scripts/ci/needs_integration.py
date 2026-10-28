#!/usr/bin/env python3
"""Does this push or pull request need the engine integration run? (job `changes` of ci.yml)

The integration matrix is the most expensive part of CI (two images, about ten
minutes each), and the repository's Actions minutes are limited. It is skipped
only when every changed file is Markdown: no integration test reads a Markdown
file's content (test_confined only checks that README.md is readable through
the sandbox, whatever it says). Anything else, an unknown event, a missing or
unreadable base, or an empty list of changes, means the run happens. The unit
tests, which do read the docs, always run; so does the weekly scheduled run.

Reads EVENT, BEFORE (push) and BASE (pull request) from the environment, never
from expressions inside the workflow script. Prints `integration=true|false`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}")


def needs_integration(changed: list[str] | None) -> bool:
    if not changed:
        return True
    return not all(path.lower().endswith(".md") for path in changed)


def changed_files(event: str, before: str, base: str) -> list[str] | None:
    ref = {"push": before, "pull_request": base}.get(event, "")
    if not SHA.fullmatch(ref) or set(ref) == {"0"}:
        return None  # a new branch, a forced push without history, another event: run everything
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", f"{ref}...HEAD"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    env = os.environ
    changed = changed_files(env.get("EVENT", ""), env.get("BEFORE", ""), env.get("BASE", ""))
    decision = needs_integration(changed)
    shown = "unknown" if changed is None else f"{len(changed)} file(s)"
    print(f"changes: {shown}; integration needed: {decision}", file=sys.stderr)
    print(f"integration={'true' if decision else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
