#!/usr/bin/env python3
"""Does tonight's rehearsal need to build? (job `changes` of rehearsal.yml, #378)

A rehearsal is an hour of a paid 16-processor runner (about US$3), so a night with nothing new to
test builds nothing:

- main is at the commit of the last green rehearsal: nothing changed;
- every file changed since then is Markdown: the same rule as ci.yml's integration gate
  (needs_integration.py), for the same reason.

The last green rehearsal is the newest successful run of rehearsal.yml on main, by the schedule or
by hand, read from the Actions API. A night that skipped the build is green too, so by induction its
commit is as tested as the last night that built. A night that failed is not, so the next night
builds again even with nothing new: that is how a test that only fails sometimes shows.
A run started by hand always builds. So does anything that cannot be read: an API or git error, or
a last green commit that is not an ancestor of HEAD.

Reads EVENT, GITHUB_REPOSITORY and GH_TOKEN from the environment, never from expressions inside the
workflow script. Prints `build=true|false` and `base=<sha or empty>`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import needs_integration as ci

WORKFLOW = "rehearsal.yml"
EVENTS = ("schedule", "workflow_dispatch")


def needed(event: str, base: str | None, head: str | None, changed: list[str] | None) -> bool:
    if event != "schedule" or base is None or head is None or changed is None:
        return True
    if base == head:
        return False
    return ci.needs_integration(changed)


def main() -> int:
    env = os.environ
    event = env.get("EVENT", "")
    base = head = changed = None
    if event == "schedule":
        base = ci.usable(ci.last_green(env.get("GITHUB_REPOSITORY", ""), workflow=WORKFLOW, events=EVENTS))
        result = ci._git(["rev-parse", "HEAD"])
        head = result.stdout.strip() if result.returncode == 0 and ci.SHA.fullmatch(result.stdout.strip()) else None
        changed = ci.changed_files(base)
    decision = needed(event, base, head, changed)
    shown = "not asked" if event != "schedule" else "unknown" if changed is None else f"{len(changed)} file(s) since {base[:12]}"
    print(f"changes: {shown}; build needed: {decision}", file=sys.stderr)
    print(f"build={'true' if decision else 'false'}")
    print(f"base={base or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
