#!/usr/bin/env python3
"""Is the Nulavio build behind Mozilla's Firefox releases, and how long is left? (update SLA)

Compares browser/build/engine.json with Mozilla's public release history
(product-details.mozilla.org, the same data mozilla.org uses) and applies the
update policy: a Nulavio build within 72 hours of any newer Firefox release.
Every Firefox release can carry security fixes, so the stricter target is used
for all of them; Mozilla's advisory for the release says which.

    python3 -I scripts/release/watch_upstream.py [--summary FILE] [--json]

Exit status: 0 up to date or within the deadline, 1 overdue, 2 data unavailable.
Only public release data is fetched; nothing is sent.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = "https://product-details.mozilla.org/1.0/"
SOURCES = ("firefox_history_major_releases.json", "firefox_history_stability_releases.json")
SLA_HOURS = 72
ADVISORIES = "https://www.mozilla.org/security/advisories/"


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.replace("esr", "").split("."))


def fetch(name: str) -> dict[str, str]:
    with urllib.request.urlopen(PRODUCT + name, timeout=30) as response:  # noqa: S310 - fixed https URL
        return json.load(response)


def status(pinned: str, history: dict[str, str], now: _dt.datetime) -> dict:
    """Newer releases than `pinned`, the earliest one's deadline, and the verdict."""
    newer = sorted((v for v in history if version_key(v) > version_key(pinned)), key=lambda v: (history[v], version_key(v)))
    if not newer:
        return {"pinned": pinned, "state": "up-to-date", "newer": []}
    first = newer[0]
    released = _dt.datetime.fromisoformat(history[first]).replace(tzinfo=_dt.UTC)
    deadline = released + _dt.timedelta(hours=SLA_HOURS)
    left = (deadline - now).total_seconds() / 3600
    return {
        "pinned": pinned,
        "state": "overdue" if left < 0 else "pending",
        "newer": newer,
        "first": first,
        "released": history[first],
        "deadline": deadline.isoformat(),
        "hours_left": round(left, 1),
        "advisories": ADVISORIES,
    }


def describe(result: dict) -> str:
    if result["state"] == "up-to-date":
        return f"Nulavio ships Firefox {result['pinned']}, the latest release."
    head = f"Firefox {result['first']} was released on {result['released']}; Nulavio ships {result['pinned']}."
    if result["state"] == "overdue":
        return f"{head} OVERDUE: the {SLA_HOURS}-hour target passed at {result['deadline']}."
    return f"{head} Deadline {result['deadline']} ({result['hours_left']} hours left). Newer: {', '.join(result['newer'])}."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, help="append a Markdown summary (GitHub job summary)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    pinned = json.loads((ROOT / "browser" / "build" / "engine.json").read_text())["firefox"]
    try:
        history: dict[str, str] = {}
        for name in SOURCES:
            history.update(fetch(name))
    except (OSError, ValueError) as exc:
        print(f"watch_upstream: release data unavailable: {exc}", file=sys.stderr)
        return 2
    result = status(pinned, history, _dt.datetime.now(_dt.UTC))
    text = describe(result)
    print(json.dumps(result, indent=2) if args.json else text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Upstream Firefox\n\n{text}\n\nAdvisories: {ADVISORIES}\n")
    return 1 if result["state"] == "overdue" else 0


if __name__ == "__main__":
    raise SystemExit(main())
