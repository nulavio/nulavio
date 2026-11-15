#!/usr/bin/env python3
"""Nulavio's own performance measurements against a baseline build, from one command (#80, first part).

    NULAVIO_ENGINE=<build>/nulavio/nulavio python3 -I scripts/perf/run.py \\
        --baseline-engine <previous>/nulavio/nulavio [--runs 5] [--tabs 1 10] [--out perf.json]

Each run uses a fresh profile (harness.GeckoProfileSession, as the integration suite does) and the runs
alternate the build and the baseline, so a machine that slows down slows both. Measured per run:

- startup: from the process to the engine's "session restored", its start-up done (Services.startup.
  getStartupInfo; the suite runs without a window, so there is no first paint to time), on the profile's
  first start and on its second (the files already on disk and in the page cache);
- memory: the proportional memory of every process of the instance (PSS, /proc/<pid>/smaps_rollup,
  summed) and how many there are, with 1 and 10 tabs of a local page open (--tabs), after the tabs have loaded and
  settled.

The JSON keeps every run; the table gives each side's median and the build's change against the baseline.
What it does not measure yet (#80): BrowserBench (Speedometer, JetStream, MotionMark), frame time
(scripts/research/frame_scene.py), the fingerprinting cost, the tools CLI, and stock Firefox as a second
baseline (GeckoProfileSession needs a Nulavio build).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

STARTUP = (
    "const i = Services.startup.getStartupInfo();"
    " return { process: +i.process, restored: i.sessionRestored ? +i.sessionRestored : null };"
)
ADD_TAB = "gBrowser.addTab(arguments[0], { triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal() });"
LOADED = "return gBrowser.browsers.every(b => !b.webProgress?.isLoadingDocument);"
SETTLE_S = 5.0  # memory is read after the tabs have settled, not while they load


# -- statistics (pure; tests/unit/test_perf_run.py) -------------------------------------------------


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def change(build: list[float], baseline: list[float]) -> float | None:
    """The build's median against the baseline's, as a fraction (+0.10: 10 % more)."""
    b, a = median(build), median(baseline)
    if b is None or not a:
        return None
    return b / a - 1


def table(results: dict) -> str:
    rows = [("measure", "build (median)", "baseline (median)", "change")]
    for name, sides in results["metrics"].items():
        build, baseline = sides["build"], sides["baseline"]
        delta = change(build, baseline)
        fmt = lambda v: "-" if v is None else f"{v:.1f}"  # noqa: E731
        rows.append((name, fmt(median(build)), fmt(median(baseline)), "-" if delta is None else f"{delta * 100:+.1f} %"))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    return "\n".join("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in rows)


# -- measuring --------------------------------------------------------------------------------------


def parent_of(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return int(stat[stat.rindex(")") + 2 :].split()[1])  # the field after the state, past the name in parentheses


def instance_pids(session) -> list[int]:
    """Every process of the session's engine instance: its main process and all it started (content, GPU,
    utility and the fork server's children), read from the process tree."""
    root = session.process.pid
    parents = {int(e.name): parent_of(int(e.name)) for e in Path("/proc").iterdir() if e.name.isdigit()}
    found, frontier = {root}, [root]
    while frontier:
        current = frontier.pop()
        for pid, parent in parents.items():
            if parent == current and pid not in found:
                found.add(pid)
                frontier.append(pid)
    return sorted(found)


def pss_kib(pids: list[int]) -> int:
    """The instance's memory: each process's proportional set size (shared pages divided among the processes
    that share them, /proc/<pid>/smaps_rollup), summed. Summed RSS would count shared libraries many times."""
    total = 0
    for pid in pids:
        try:
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    total += int(line.split()[1])
        except (OSError, ValueError):
            pass  # a process that ended while it was read
    return total


def startup_ms(m) -> float:
    """From the process to the engine's "session restored": its start-up done, window and Shell included. The
    first paint is not used: the suite runs without a window (headless), where nothing is painted."""
    import harness

    harness.wait_until(lambda: m.chrome(STARTUP)["restored"], 60)
    info = m.chrome(STARTUP)
    return float(info["restored"] - info["process"])


def one_run(engine: str, tabs: list[int], server) -> dict:
    import harness

    os.environ["NULAVIO_ENGINE"] = engine
    session = harness.GeckoProfileSession(name="Perf")
    try:
        m = session.start()
        out = {"startup_first_ms": startup_ms(m)}
        session.stop()
        m = session.restart()
        out["startup_second_ms"] = startup_ms(m)
        opened = 1
        for count in sorted(tabs):
            for n in range(opened, count):
                m.chrome(ADD_TAB, [server.url(f"/page/perf-{n}")])
            opened = max(opened, count)
            harness.wait_until(lambda: m.chrome(LOADED), 30)
            time.sleep(SETTLE_S)
            pids = instance_pids(session)
            out[f"pss_mib_{count}_tabs"] = pss_kib(pids) / 1024
            out[f"processes_{count}_tabs"] = len(pids)
        return out
    finally:
        session.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-engine", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--tabs", type=int, nargs="+", default=[1, 10])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    build = os.environ.get("NULAVIO_ENGINE")
    if not build:
        parser.error("NULAVIO_ENGINE names the build to measure")
    import harness

    results = {"build": build, "baseline": args.baseline_engine, "runs": [], "metrics": {}}
    with harness.FixtureServer() as server:
        for run in range(args.runs):
            for side, engine in (("build", build), ("baseline", args.baseline_engine)):
                measured = one_run(engine, args.tabs, server)
                results["runs"].append({"run": run, "side": side, **measured})
                print(f"run {run} {side}: {measured}", file=sys.stderr)
    os.environ["NULAVIO_ENGINE"] = build
    for name in [key for key in results["runs"][0] if key not in ("run", "side")]:
        results["metrics"][name] = {
            side: [r[name] for r in results["runs"] if r["side"] == side] for side in ("build", "baseline")
        }
    if args.out:
        args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    print(table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
