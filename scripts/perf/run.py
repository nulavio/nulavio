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

With --speedometer, also Speedometer 3.1 (BrowserBench), pinned to a commit of WebKit/Speedometer's release/3.1
branch, downloaded once into the cache and checked against its SHA-256, served from this machine (no network
round-trip is part of the score), run in a third start of the profile after the memory is read, so neither
measure carries the other's processes: its mean score over --speedometer-iterations (3; the benchmark's own
default is 10, so this is not an official score). Without a window (headless) and with software rendering it is
a regression signal, not a real-hardware number. GitHub does not promise the same bytes for an archive it makes
from a commit: if they change, the run stops at the digest check and the pin needs updating.

With --jetstream, JetStream 3.0 (JavaScript and WebAssembly), and with --motionmark, MotionMark 1.3.2 (graphics),
pinned and served the same way, each in a start of its own after the ones before it, with the benchmark's own
defaults: JetStream's overall score (the geometric mean of its benchmarks' scores, as its page computes it) and
MotionMark's score. MotionMark measures how much the engine draws at the frame rate it detects; without a window and
a GPU here, its number says more about software rendering than about a person's screen.

The JSON keeps every run and is written after each one; the table gives each side's median and the build's
change against the baseline. What it does not measure yet (#80): frame time
(scripts/research/frame_scene.py), the fingerprinting cost, the tools CLI, a cold start, and stock Firefox
as a second baseline (GeckoProfileSession needs a Nulavio build).
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import http.server
import json
import math
import os
import shutil
import statistics
import sys
import tarfile
import threading
import time
import urllib.request
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


# Benchmarks, pinned: a commit of the upstream repository, the archive GitHub serves for it, and its digest.
PINNED = {
    "speedometer": {
        "commit": "1386415be8fef2f6b6bbdbe1828872471c5d802a",  # WebKit/Speedometer, branch release/3.1
        "url": "https://codeload.github.com/WebKit/Speedometer/tar.gz/1386415be8fef2f6b6bbdbe1828872471c5d802a",
        "sha256": "cfefa818d7789ed2f2b9f3f1bf608cc35e4e8241489eef47049296ce92791313",
        "size": 12358793,
    },
    "jetstream": {
        "commit": "06785cf861ac44855f168cbbe829278c2802e6de",  # WebKit/JetStream, branch JetStream3.0
        "url": "https://codeload.github.com/WebKit/JetStream/tar.gz/06785cf861ac44855f168cbbe829278c2802e6de",
        "sha256": "0361851eb2ddeb003e06be74239c3f7ce437c64e774a29ba446faaed9ab16fa9",
        "size": 194407750,
    },
    "motionmark": {
        "commit": "0e740d50f2321d255f6176e2f57493574c735996",  # WebKit/MotionMark, tag release/MotionMark1.3.2
        "url": "https://codeload.github.com/WebKit/MotionMark/tar.gz/0e740d50f2321d255f6176e2f57493574c735996",
        "sha256": "14b746f05b388a382d315186efd6e19017f7f67b3846d20759ab30fe83c2f985",
        "size": 576485,
    },
}
# The benchmark's state: how many iterations it measured, whether it ended (its last iteration, or an error), and the
# mean of the iterations' scores, the number its own page shows (resources/main.mjs, _computeResults).
SPEEDOMETER = (
    "const client = globalThis.benchmarkClient, runs = client?._measuredValuesList ?? [];"
    " return { done: runs.length, ended: !!client?._hasResults && !client._isRunning,"
    " score: runs.length ? runs.reduce((sum, r) => sum + r.score, 0) / runs.length : null };"
)
SPEEDOMETER_ITERATION_S = 600  # the longest one iteration may take here (headless, software rendering)
# JetStream: whether it ended (all its benchmarks, or an error). Its benchmarks' `isSuccess` getter assigns the
# state it should compare in this version, so it is never read here.
JETSTREAM = (
    "const j = globalThis.JetStream;"
    " return j ? { ended: j.isDone || j.errors.length > 0, errors: j.errors.map(e => String(e.error ?? e)) } : { ended: false };"
)
JETSTREAM_SCORE = (
    "const scores = globalThis.JetStream.benchmarks.map(b => b.score);"
    " return Math.exp(scores.reduce((sum, x) => sum + Math.log(x), 0) / scores.length);"
)
JETSTREAM_S = 3600
# MotionMark: ready once it has detected the frame rate; ended when its results are shown. Its score is read only
# then: the dashboard's getter throws while no iteration is done.
MOTIONMARK = (
    "const start = document.getElementById('start-button'), ended = document.body.classList.contains('showing-results');"
    " return { ready: !!start && !start.disabled, ended,"
    " score: ended ? globalThis.benchmarkRunnerClient?.results?.score ?? null : null };"
)
MOTIONMARK_S = 1800


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


def cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "nulavio" / "perf"


def pinned(name: str, cache: Path | None = None) -> Path:
    """The pinned benchmark's files: downloaded once, checked against the pin's size and SHA-256, unpacked."""
    pin = PINNED[name]
    cache = cache or cache_dir()
    tree = cache / f"{name}-{pin['commit']}-{pin['sha256'][:16]}"  # a new digest for the same commit is a new tree
    if (tree / ".verified").exists():
        return tree
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{name}-{pin['commit']}-{pin['sha256'][:16]}.tar.gz"
    if not archive.exists():
        partial = archive.with_suffix(".part")
        with urllib.request.urlopen(pin["url"], timeout=120) as response, partial.open("wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out)
        partial.replace(archive)
    data = archive.read_bytes()
    if len(data) != pin["size"] or hashlib.sha256(data).hexdigest() != pin["sha256"]:
        archive.unlink()
        raise MeasureError(f"{name}: the download is not the pinned archive (size or SHA-256)")
    shutil.rmtree(tree, ignore_errors=True)
    tree.mkdir()
    with tarfile.open(archive) as tar:
        members = []
        for member in tar.getmembers():
            inner = member.name.split("/", 1)[1] if "/" in member.name else ""
            if inner:
                member.name = inner
                members.append(member)
        tar.extractall(tree, members=members, filter="data")
    (tree / ".verified").touch()
    return tree


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # hundreds of requests an iteration would bury the run lines on stderr
        pass


class StaticServer:
    """A benchmark's files served from this machine, on a free port."""

    def __init__(self, root: Path):
        handler = functools.partial(QuietHandler, directory=str(root))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"


def speedometer_score(m, server: StaticServer, iterations: int) -> float:
    import harness

    m.navigate(server.url(f"/index.html?startAutomatically&iterationCount={iterations}"))
    limit = SPEEDOMETER_ITERATION_S * iterations
    if not harness.wait_until(lambda: m.execute(SPEEDOMETER)["ended"], limit, interval=5.0):
        raise MeasureError(f"Speedometer did not end {iterations} iterations in {limit} s: {m.execute(SPEEDOMETER)}")
    state = m.execute(SPEEDOMETER)
    score = state["score"]
    # An error ends it early; a score that is not a number comes back as null.
    if state["done"] < iterations or not isinstance(score, (int, float)) or not math.isfinite(score):
        raise MeasureError(f"Speedometer ended without a score for {iterations} iterations: {state}")
    return float(score)


def finite(name: str, value) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise MeasureError(f"{name} ended without a score: {value}")
    return float(value)


def jetstream_score(m, server: StaticServer) -> float:
    import harness

    m.navigate(server.url("/index.html?startAutomatically"))
    if not harness.wait_until(lambda: m.execute(JETSTREAM)["ended"], JETSTREAM_S, interval=5.0):
        raise MeasureError(f"JetStream did not end in {JETSTREAM_S} s")
    errors = m.execute(JETSTREAM)["errors"]
    if errors:
        raise MeasureError(f"JetStream stopped on errors: {errors[:3]}")
    return finite("JetStream", m.execute(JETSTREAM_SCORE))


def motionmark_score(m, server: StaticServer) -> float:
    import harness

    m.navigate(server.url("/MotionMark/index.html"))
    if not harness.wait_until(lambda: m.execute(MOTIONMARK)["ready"], 120):
        raise MeasureError("MotionMark did not detect the frame rate in 120 s")
    m.execute("benchmarkController.startBenchmark();")
    if not harness.wait_until(lambda: m.execute(MOTIONMARK)["ended"], MOTIONMARK_S, interval=5.0):
        raise MeasureError(f"MotionMark did not end in {MOTIONMARK_S} s")
    return finite("MotionMark", m.execute(MOTIONMARK)["score"])


def startup_ms(m) -> float:
    import harness

    if not harness.wait_until(lambda: m.chrome(STARTUP)["restored"], 60):
        raise MeasureError("the engine did not report its session restored within 60 s")
    info = m.chrome(STARTUP)
    return float(info["restored"] - info["process"])


def one_run(engine: str, tabs: list[int], server, benchmarks: tuple = ()) -> dict:
    """One fresh profile: its two starts, the tabs' memory, then each of `benchmarks` ((name, score of a Marionette
    session)) in a start of its own."""
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
        for name, score in benchmarks:  # in a start of its own: no measure carries another's processes
            session.stop()
            m = session.restart()
            out[name] = score(m)
        return out
    finally:
        session.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-engine", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--tabs", type=int, nargs="+", default=[1, 10])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--speedometer", action="store_true", help="also Speedometer 3.1, pinned and served locally")
    parser.add_argument("--speedometer-iterations", type=int, default=3)
    parser.add_argument("--jetstream", action="store_true", help="also JetStream 3.0, pinned and served locally")
    parser.add_argument("--motionmark", action="store_true", help="also MotionMark 1.3.2, pinned and served locally")
    args = parser.parse_args(argv)
    build = os.environ.get("NULAVIO_ENGINE")
    if not build:
        parser.error("NULAVIO_ENGINE names the build to measure")
    if args.runs < 1 or any(count < 1 for count in args.tabs) or len(set(args.tabs)) != len(args.tabs):
        parser.error("--runs and each of --tabs must be at least 1, and --tabs without repeats")
    if args.speedometer and args.speedometer_iterations < 1:
        parser.error("--speedometer-iterations must be at least 1")
    import harness

    results = {"build": build, "baseline": args.baseline_engine, "runs": [], "metrics": {}}

    def write() -> None:
        if args.out:  # after each run: a failure late in the series keeps what was measured before it
            args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")

    try:
        with contextlib.ExitStack() as stack:
            server = stack.enter_context(harness.FixtureServer())
            benchmarks = []  # a server for each benchmark's own files, only for the ones that run

            def serve(name: str):
                return stack.enter_context(StaticServer(pinned(name)))

            if args.speedometer:
                speedometer = functools.partial(
                    speedometer_score, server=serve("speedometer"), iterations=args.speedometer_iterations
                )
                benchmarks.append(("speedometer3_score", speedometer))
            if args.jetstream:
                benchmarks.append(("jetstream3_score", functools.partial(jetstream_score, server=serve("jetstream"))))
            if args.motionmark:
                benchmarks.append(("motionmark_score", functools.partial(motionmark_score, server=serve("motionmark"))))
            for run in range(args.runs):
                for side, engine in (("build", build), ("baseline", args.baseline_engine)):
                    measured = one_run(engine, args.tabs, server, tuple(benchmarks))
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
