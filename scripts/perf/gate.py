"""perf.yml's gate (#367): which measures of a release got worse than the runner's own noise allows.

A measure fails when its 95 % interval against the release before it excludes 0 on the worse side **and** its median
change is worse than its threshold. The thresholds are two to four times the largest change seen between runs of the
same comparison on GitHub's runner (docs/architecture/performance.md, "Thresholds"). Prints one line per measure for the
job summary and exits 1 when one fails; the release is already published, and the maintainer reads the result.

    python3 -I scripts/perf/gate.py [--strict] perf/perf.json

--strict (perf.yml): a measure that was not measured, has no interval, or (memory) had processes that could not be
read (unreadable_*_tabs), fails too: a sum missing a process reads too low. perf.yml always measures all of
them, so a missing one means the measuring broke or a name changed, which must not leave the gate silent.
"""

from __future__ import annotations

import json
import statistics
import sys
from fractions import Fraction
from pathlib import Path

# measure -> (worse when it goes "up" or "down", threshold as a fraction of the release before). Exact fractions: an
# exact +10 % is at the threshold, not past it, whatever float arithmetic makes of 1.1 * 500.
THRESHOLDS = {
    "startup_first_ms": ("up", Fraction(15, 100)),
    "startup_second_ms": ("up", Fraction(15, 100)),
    "pss_mib_1_tabs": ("up", Fraction(10, 100)),
    "pss_mib_10_tabs": ("up", Fraction(10, 100)),
    "speedometer3_score": ("down", Fraction(10, 100)),
}


def unreadable_runs(metrics: dict, name: str) -> bool | None:
    """Whether a PSS measure had processes whose memory could not be read (run.py's unreadable_<n>_tabs, per side and
    run). Their memory is missing from the sum, so the reading is too low: on the release it would look like an
    improvement, on the baseline like a regression. True, or None (the count is absent), means it is not judged."""
    if not name.startswith("pss_mib_"):
        return False
    counts = metrics.get(name.replace("pss_mib_", "unreadable_", 1), {})
    sides = [counts.get("build"), counts.get("baseline")]
    if not all(isinstance(side, list) and side for side in sides):
        return None
    return any(count for side in sides for count in side)


def past_limit(build: float, baseline: float, worse: str, limit: Fraction) -> bool:
    """Whether the build's median is worse than the baseline's by more than `limit`, compared exactly."""
    new, old = Fraction(build), Fraction(baseline)
    return new > old * (1 + limit) if worse == "up" else new < old * (1 - limit)


def shown_change(change: float, limit: Fraction, failed: bool) -> str:
    """The change as a percentage; a failure shows the digits it takes to be seen past the limit (+10.0 % would
    read as at it)."""
    for digits in range(1, 7):
        text = f"{change:+.{digits}%}"
        if not failed or abs(Fraction(text[:-1]) / 100) > limit:
            break
    return text


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
        if unreadable_runs(results.get("metrics", {}), name) is not False:
            out.append((name, "missing", f"{name}: processes whose memory could not be read, or not counted: not judged"))
            continue
        median_build, median_baseline = statistics.median(build), statistics.median(baseline)
        change = median_build / median_baseline - 1
        low, high = bounds
        beyond_noise = low > 0 if worse == "up" else high < 0
        failed = beyond_noise and past_limit(median_build, median_baseline, worse, limit)
        words = (
            f"{name}: {shown_change(change, limit, failed)} (interval {low:+.1%} … {high:+.1%}; "
            f"fails past {'+' if worse == 'up' else '-'}{float(limit):.0%})"
        )
        out.append((name, "fail" if failed else "pass", words))
    return out


def main(argv: list[str]) -> int:
    strict = "--strict" in argv[1:]
    paths = [a for a in argv[1:] if a != "--strict"]
    if len(paths) != 1:
        print("usage: gate.py [--strict] perf.json", file=sys.stderr)
        return 2
    results = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
    found = verdicts(results)
    failing = {"fail", "missing"} if strict else {"fail"}
    for _name, verdict, words in found:
        print(
            f"- {'**worse**' if verdict == 'fail' else '**not judged**' if verdict == 'missing' and strict else verdict}: {words}"
        )
    return 1 if any(verdict in failing for _name, verdict, _words in found) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
