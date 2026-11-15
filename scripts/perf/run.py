#!/usr/bin/env python3
"""Nulavio's own performance measurements against a baseline build, from one command (#80, first part).

    NULAVIO_ENGINE=<build>/nulavio/nulavio python3 -I scripts/perf/run.py \\
        --baseline-engine <previous>/nulavio/nulavio [--runs 5] [--tabs 1 10] [--out perf.json]

Each run uses a fresh profile (harness.GeckoProfileSession, as the integration suite does) and the runs
alternate the build and the baseline, so a machine that slows down slows both. Measured per run:

- startup: from the process to the engine's "session restored", its start-up done (Services.startup.
  getStartupInfo; the suite runs without a window, so there is no first paint to time), on the profile's
  first start and on its second. Neither is a cold start: the session ran the binary to make the
  profile, so its files are in the page cache both times;
- memory: the proportional memory of every process of the instance (PSS, /proc/<pid>/smaps_rollup,
  summed over the process tree of its main process) and how many processes there are, with 1 and 10 tabs
  of a local page open (--tabs; the first tab is navigated to a local page too), once every tab shows its
  page, after a 5 s settle and the engine's own "Minimize memory usage" (about:memory) in every process.
  A process whose memory could not be read is counted in the JSON (unreadable_*), never silently left out
  of the sum.

The JSON keeps every run and is written after each one; the table gives each side's median and the build's
change against the baseline. What it does not measure yet (#80): BrowserBench (Speedometer, JetStream,
MotionMark), frame time (scripts/research/frame_scene.py), the fingerprinting cost, the tools CLI, a cold
start, and stock Firefox as a second baseline (GeckoProfileSession needs a Nulavio build).
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
# Every tab shows its own local page, loaded: [count, how many are done].
SHOWN = (
    "const done = gBrowser.browsers.filter(b => b.currentURI.spec.startsWith(arguments[0])"
    " && !b.webProgress?.isLoadingDocument && b.browsingContext?.currentWindowGlobal?.documentURI?.spec === b.currentURI.spec);"
    " return [gBrowser.browsers.length, done.length];"
)
SETTLE_S = 5.0  # memory is read after the tabs have settled, not while they load
# The engine's own "Minimize memory usage" (about:memory), in every process: garbage and caches the engine would
# drop by itself in a while are not what one run happened to hold at that second.
MINIMIZE = (
    "const done = arguments[arguments.length - 1];"
    " Cc['@mozilla.org/memory-reporter-manager;1'].getService(Ci.nsIMemoryReporterManager)"
    ".minimizeMemoryUsage(() => done(true));"
)


class MeasureError(RuntimeError):
    pass


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


def instance_pids(root: int) -> list[int]:
    """The instance's main process and everything it started (content, GPU, utility, the fork server and its
    children), from the process tree."""
    import harness

    return sorted({root, *harness.descendants(root)})


def pss_kib(pids: list[int]) -> tuple[int, int]:
    """(PSS summed over `pids` in KiB, how many still-running processes could not be read). PSS divides shared
    pages among the processes that share them; summed RSS would count shared libraries many times. A process
    that ended while it was read is neither."""
    total = unreadable = 0
    for pid in pids:
        try:
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                if line.startswith("Pss:"):
                    total += int(line.split()[1])
        except FileNotFoundError:
            continue  # it ended
        except (OSError, ValueError):
            if Path(f"/proc/{pid}").exists():
                unreadable += 1
    return total, unreadable


def startup_ms(m) -> float:
    import harness

    if not harness.wait_until(lambda: m.chrome(STARTUP)["restored"], 60):
        raise MeasureError("the engine did not report its session restored within 60 s")
    info = m.chrome(STARTUP)
    return float(info["restored"] - info["process"])


def one_run(engine: str, tabs: list[int], server) -> dict:
    import harness

    os.environ["NULAVIO_ENGINE"] = engine
    session = harness.GeckoProfileSession(name="Perf")
    try:
        m = session.start()
        out = {"engine": str(session.engine.path), "version": session.engine.version, "startup_first_ms": startup_ms(m)}
        session.stop()
        m = session.restart()
        out["startup_second_ms"] = startup_ms(m)
        local = server.url("/page/perf-")
        m.navigate(server.url("/page/perf-0"))  # the first tab too: a local page, not the start page
        opened = 1
        for count in sorted(tabs):
            for n in range(opened, count):
                m.chrome(ADD_TAB, [server.url(f"/page/perf-{n}")])
            opened = max(opened, count)
            if not harness.wait_until(lambda want=count: m.chrome(SHOWN, [local]) == [want, want], 60):
                raise MeasureError(f"not every tab showed its page in 60 s: {m.chrome(SHOWN, [local])} (tabs, shown)")
            time.sleep(SETTLE_S)
            m.set_context("chrome")
            try:
                m.execute_async(MINIMIZE)
            finally:
                m.set_context("content")
            pids = instance_pids(session.process.pid)
            pss, unreadable = pss_kib(pids)
            out[f"pss_mib_{count}_tabs"] = pss / 1024
            out[f"processes_{count}_tabs"] = len(pids)
            out[f"unreadable_{count}_tabs"] = unreadable
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
    if args.runs < 1 or any(count < 1 for count in args.tabs) or len(set(args.tabs)) != len(args.tabs):
        parser.error("--runs and each of --tabs must be at least 1, and --tabs without repeats")
    import harness

    results = {"build": build, "baseline": args.baseline_engine, "runs": [], "metrics": {}}

    def write() -> None:
        if args.out:  # after each run: a failure late in the series keeps what was measured before it
            args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")

    try:
        with harness.FixtureServer() as server:
            for run in range(args.runs):
                for side, engine in (("build", build), ("baseline", args.baseline_engine)):
                    measured = one_run(engine, args.tabs, server)
                    results["runs"].append({"run": run, "side": side, **measured})
                    print(f"run {run} {side}: {measured}", file=sys.stderr)
                    write()
    finally:
        os.environ["NULAVIO_ENGINE"] = build
    numbers = [key for key, value in results["runs"][0].items() if key not in ("run", "side") and isinstance(value, (int, float))]
    for name in numbers:
        results["metrics"][name] = {
            side: [r[name] for r in results["runs"] if r["side"] == side] for side in ("build", "baseline")
        }
    write()
    print(table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
