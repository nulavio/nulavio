"""perf.yml's gate (#367): which measures of a release got worse than the runner's own noise allows.

A measure fails when its 95 % interval against the release before it excludes 0 on the worse side **and** its median
change is worse than its threshold. The thresholds are two to three times the largest change seen between runs of the
same comparison on GitHub's runner (docs/architecture/performance.md, "Thresholds"). Prints one line per measure for the
job summary and exits 1 when one fails; the release is already published, and the maintainer reads the result.

    python3 -I scripts/perf/gate.py perf/perf.json
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

# measure -> (worse when it goes "up" or "down", threshold as a fraction of the release before)
THRESHOLDS = {
    "startup_first_ms": ("up", 0.15),
    "startup_second_ms": ("up", 0.15),
    "pss_mib_1_tabs": ("up", 0.10),
    "pss_mib_10_tabs": ("up", 0.10),
    "speedometer3_score": ("down", 0.10),
}


def verdicts(results: dict) -> list[tuple[str, str, str]]:
    """(measure, "fail" | "pass" | "missing", the line said about it), in THRESHOLDS' order."""
    out = []
    for name, (worse, limit) in THRESHOLDS.items():
        values = results.get("metrics", {}).get(name, {})
        build, baseline = values.get("build") or [], values.get("baseline") or []
        bounds = results.get("intervals", {}).get(name)
        if not build or not baseline or not bounds or not statistics.median(baseline):
            out.append((name, "missing", f"{name}: not measured, or too few runs for an interval: not judged"))
            continue
        change = statistics.median(build) / statistics.median(baseline) - 1
        low, high = bounds
        beyond_noise = low > 0 if worse == "up" else high < 0
        past_limit = change > limit if worse == "up" else change < -limit
        words = (
            f"{name}: {change:+.1%} (interval {low:+.1%} … {high:+.1%}; fails past {'+' if worse == 'up' else '-'}{limit:.0%})"
        )
        out.append((name, "fail" if beyond_noise and past_limit else "pass", words))
    return out


def main(argv: list[str]) -> int:
    results = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    found = verdicts(results)
    for _name, verdict, words in found:
        print(f"- {'**worse**' if verdict == 'fail' else verdict}: {words}")
    return 1 if any(verdict == "fail" for _name, verdict, _words in found) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
