#!/usr/bin/env python3
"""UX7 frame-time scene: how smoothly Nulavio's motion runs, against a written budget.

Runs on a real Track B build in a throwaway profile, headful on a private Xvfb (software WebRender):

    env -u WAYLAND_DISPLAY xvfb-run -a -s "-screen 0 1920x1080x24" env GDK_BACKEND=x11 MOZ_ENABLE_WAYLAND=0 \\
      NULAVIO_TEST_HEADFUL=1 NULAVIO_ENGINE=<build>/nulavio/nulavio \\
      python3 -I scripts/research/frame_scene.py [--baseline-engine <previous>/nulavio/nulavio] --runs 5 --out <dir>

Each run uses a fresh profile with reduced motion off, and alternates the build and the baseline.
Both must install the same extensions (a package's distribution/; the script refuses otherwise):
an extracted package without one is compared after copying the build's distribution/ next to it.
Scenes: the sidebar launcher collapsing and expanding, switching tabs, Ctrl+T to the new tab's
`nv-painted` mark, a Settings dialog opening, and 60 s idle on a page (chrome reflows, frames
constructed, paints). Frame intervals come from the compositor's frame-time recording; when it
records nothing (some Xvfb set-ups), from requestAnimationFrame in the window. The JSON names the
source of each scene (the dialog is always timed by requestAnimationFrame in the page) and keeps a
failed sample's error; a transition scene with no samples fails its budget line.
Xvfb timings are a regression gate, not a measure of real hardware.
"""

from __future__ import annotations

import argparse
import configparser
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

# The budget (design-system.md, "UX7: motion and performance budget").
BUDGET = {
    "transition_p95_ms": 20.0,
    "transition_max_ms": 50.0,
    "new_tab_p95_ms": 150.0,
    "idle_reflows": 0,
    "idle_frames_constructed": 0,
    "regression_ratio": 1.10,
}
TRANSITIONS = ("sidebar_collapse", "sidebar_expand", "tab_switch", "dialog_open")


# -- statistics (pure; tests/unit/test_frame_scene.py) ---------------------------------------------


def intervals_after_first(samples: list[float]) -> list[float]:
    """Frame intervals of one sample with the first dropped (it spans the trigger, not the motion)."""
    return [float(x) for x in samples[1:]]


def nearest_rank(values: list[float], percentile: float) -> float | None:
    """The nearest-rank percentile: the smallest value with at least `percentile` % of the values at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[rank - 1]


def summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "p50": nearest_rank(values, 50),
        "p95": nearest_rank(values, 95),
        "max": max(values) if values else None,
    }


def regression(build_runs: list[float], baseline_runs: list[float], ratio: float = BUDGET["regression_ratio"]) -> bool:
    """A median more than `ratio` worse, flagged only when the two sets of runs do not overlap."""
    if not build_runs or not baseline_runs:
        return False
    worse = statistics.median(build_runs) > ratio * statistics.median(baseline_runs)
    return worse and min(build_runs) > max(baseline_runs)


def verdict(scenes: dict) -> dict:
    """Pass or fail of each budget line for one build's pooled scenes."""
    out = {}
    for name in TRANSITIONS:
        stats = scenes.get(name)
        # A scene that recorded nothing failed to run: no data is not a pass.
        out[name] = (
            bool(stats and stats["n"])
            and stats["p95"] <= BUDGET["transition_p95_ms"]
            and stats["max"] <= BUDGET["transition_max_ms"]
        )
    if scenes.get("new_tab", {}).get("n"):
        out["new_tab"] = scenes["new_tab"]["p95"] <= BUDGET["new_tab_p95_ms"]
    idle = scenes.get("idle")
    if idle:
        out["idle"] = idle["reflows"] <= BUDGET["idle_reflows"] and idle["framesConstructed"] <= BUDGET["idle_frames_constructed"]
    return out


# -- the scene -------------------------------------------------------------------------------------

# One sample: the action's code is put in the script itself (the parent process allows no eval).
RECORD = """
const done = arguments[arguments.length - 1];
const settleMs = arguments[0];
let stop = false;
(async () => {
  const utils = window.windowUtils;
  await (async () => { PREPARE })(); // outside the recording: only the measured motion is in it
  const raf = [];
  const tick = t => { raf.push(t); if (!stop) requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  const start = utils.startFrameTimeRecording();
  await (async () => { ACTION })();
  await new Promise(r => setTimeout(r, settleMs));
  const frames = Array.from(utils.stopFrameTimeRecording(start) || []);
  stop = true;
  done({frames, raf: raf.slice(1).map((t, i) => t - raf[i])});
})().catch(e => { stop = true; done({error: String(e)}); });
"""

# name -> (prepare, outside the recording; the measured action; how long to record after it, ms)
ACTIONS = {
    "sidebar_collapse": (
        "await SidebarController.waitUntilStable();"
        "if (!SidebarController.getUIState().launcherExpanded) { SidebarController.handleToolbarButtonClick();"
        " await SidebarController.waitUntilStable(); }",
        "SidebarController.handleToolbarButtonClick();",
        420,
    ),
    "sidebar_expand": (
        "await SidebarController.waitUntilStable();"
        "if (SidebarController.getUIState().launcherExpanded) { SidebarController.handleToolbarButtonClick();"
        " await SidebarController.waitUntilStable(); }",
        "SidebarController.handleToolbarButtonClick();",
        480,
    ),
    "tab_switch": ("", "gBrowser.tabContainer.advanceSelectedTab(1, true);", 300),
}


def provenance(engine: Path) -> dict:
    """What the build says about itself (its application.ini), and the extensions its distribution
    installs (None: no distribution). Builds compared must install the same ones: an extension's
    first-run work (uBlock Origin downloads and compiles its lists) weighs on every scene."""
    ini = configparser.ConfigParser()
    ini.read(engine.parent / "application.ini")
    app = ini["App"] if ini.has_section("App") else {}
    policies = engine.parent / "distribution" / "policies.json"
    extensions = None
    if policies.is_file():
        extensions = sorted(json.loads(policies.read_text()).get("policies", {}).get("ExtensionSettings", {}))
    return {
        "engine": str(engine),
        "buildID": app.get("BuildID"),
        "sourceStamp": app.get("SourceStamp"),
        "version": app.get("Version"),
        "distributionExtensions": extensions,
    }


def checkout() -> dict:
    """The checkout this script ran from (not the builds': each build's Shell is in its omni.ja)."""
    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", "browser", "scripts"], capture_output=True, text=True
    )
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True)
    return {"git": head.stdout.strip(), "gitDirty": bool(dirty.stdout.strip())}


def one_run(engine: Path, samples: int) -> dict:
    os.environ["NULAVIO_ENGINE"] = str(engine)
    import harness  # reads NULAVIO_ENGINE at session start

    session = harness.GeckoProfileSession(name="Pessoal")
    m = session.start()
    out: dict = {"sources": {}, "errors": {}}
    try:
        m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
        m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 768})
        out["layerManager"] = m.chrome("return window.windowUtils.layerManagerType;")
        base = m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        with harness.FixtureServer() as server:
            m.navigate(server.url("/page/Scene"))
            for i in range(4):
                m.chrome(
                    "gBrowser.addTab(arguments[0], {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});",
                    [server.url(f"/page/Tab{i}")],
                )
            time.sleep(1.5)
            raw: dict[str, list[list[float]]] = {}
            m.set_context("chrome")
            try:
                for name, (prepare, action, settle) in ACTIONS.items():
                    script = RECORD.replace("PREPARE", prepare).replace("ACTION", action)
                    m.execute_async(script, [settle])  # warm-up
                    raw[name] = []
                    for _ in range(samples):
                        got = m.execute_async(script, [settle])
                        if got.get("error"):  # a failed sample is reported, never read as a fallback
                            out["errors"].setdefault(name, []).append(got["error"])
                            continue
                        frames = got.get("frames") or []
                        source = "frame-time recording"
                        if not frames:
                            source = "requestAnimationFrame (frame-time recording returned nothing)"
                            frames = got.get("raf") or []
                        out["sources"].setdefault(name, set()).add(source)
                        raw[name].append(intervals_after_first(frames))
                # Ctrl+T: from the command to the new tab's nv-painted mark (epoch ms on both sides).
                new_tab, new_tab_poll = [], []
                for _ in range(samples + 1):
                    m.set_context("content")
                    handles = set(m.window_handles())
                    m.set_context("chrome")
                    began = m.execute("const t = Date.now(); BrowserCommands.openTab(); return t;")
                    m.set_context("content")
                    harness.wait_until(lambda before=handles: set(m.window_handles()) - before, 10, interval=0.01)
                    m.switch_to((set(m.window_handles()) - handles).pop())
                    # The build's nv-painted mark (exact), and for both builds the moment the page is seen
                    # painted (polled: an upper bound, the same method on both, used for the comparison).
                    seen = harness.wait_until(
                        lambda: m.execute(
                            "if (!document.documentElement?.hasAttribute('data-painted')) return null;"
                            "const e = performance.getEntriesByName('nv-painted')[0];"
                            "return {seen: Date.now(), mark: e ? performance.timeOrigin + e.startTime : null};"
                        ),
                        10,
                        interval=0.005,
                    )
                    m.set_context("chrome")
                    if seen:
                        new_tab_poll.append(seen["seen"] - began)
                        if seen["mark"]:
                            new_tab.append(seen["mark"] - began)
                    m.execute("gBrowser.removeTab(gBrowser.selectedTab);")
                    time.sleep(0.3)
                out["new_tab_ms"] = new_tab[1:]  # the first warms the Shell
                out["new_tab_poll_ms"] = new_tab_poll[1:]
                # Idle: 60 s on a page with the band, counted in the chrome window.
                count = (
                    "const u = window.windowUtils;"
                    "return {reflows: u.framesReflowed, framesConstructed: u.framesConstructed, paints: u.paintCount ?? null};"
                )
                m.execute("gBrowser.selectedTab = gBrowser.tabs[0];")
                time.sleep(2)
                before = m.execute(count)
                time.sleep(60)
                after = m.execute(count)
                out["idle"] = {
                    k: (after[k] - before[k]) if before[k] is not None and after[k] is not None else None for k in before
                }
            finally:
                m.set_context("content")
            # A dialog in Settings (plain confirmation, the calm surface), in a tab that still exists.
            m.switch_to(m.window_handles()[0])
            m.navigate(base + "settings/settings.html")
            harness.wait_until(lambda: m.execute("return document.documentElement.dataset.ready === 'true';"), 20)
            raw["dialog_open"] = []
            open_dialog = (
                "const d = document.createElement('dialog'); d.className = 'dialog';"
                "d.innerHTML = '<form class=dialog__form><p>Teste</p></form>'; document.body.append(d); d.showModal();"
                "await new Promise(r => setTimeout(r, 260)); d.remove();"
            )
            for _ in range(samples + 1):
                got = m.execute_async(
                    "const done = arguments[arguments.length - 1]; const raf = []; let stop = false;"
                    "const tick = t => { raf.push(t); if (!stop) requestAnimationFrame(tick); }; requestAnimationFrame(tick);"
                    f"(async () => {{ {open_dialog} }})()"
                    ".then(() => { stop = true; done(raf.slice(1).map((t, i) => t - raf[i])); });"
                )
                raw["dialog_open"].append(intervals_after_first(got or []))
            raw["dialog_open"] = raw["dialog_open"][1:]
            out["sources"]["dialog_open"] = {"requestAnimationFrame in the page"}
        out["raw"] = raw
        out["sources"] = {name: sorted(found) for name, found in out["sources"].items()}
    finally:
        session.cleanup()
    return out


def pooled(runs: list[dict]) -> dict:
    scenes = {}
    for name in TRANSITIONS:
        values = [x for run in runs for sample in run["raw"].get(name, []) for x in sample]
        scenes[name] = summary(values)
    scenes["new_tab"] = summary([x for run in runs for x in run.get("new_tab_ms", [])])
    scenes["new_tab_polled"] = summary([x for run in runs for x in run.get("new_tab_poll_ms", [])])
    idles = [run["idle"] for run in runs if run.get("idle")]
    if idles:
        scenes["idle"] = {k: max(i[k] for i in idles if i.get(k) is not None) for k in ("reflows", "framesConstructed")}
    return scenes


def run_medians(runs: list[dict], name: str) -> list[float]:
    out = []
    for run in runs:
        values = (
            run.get("new_tab_poll_ms", []) if name == "new_tab" else [x for sample in run["raw"].get(name, []) for x in sample]
        )
        if values:
            out.append(statistics.median(values))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-engine", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    engine = Path(os.environ["NULAVIO_ENGINE"])
    builds = {"build": engine, **({"baseline": args.baseline_engine} if args.baseline_engine else {})}
    results = {
        "budget": BUDGET,
        "checkout": checkout(),
        "builds": {k: provenance(v) for k, v in builds.items()},
        "runs": {k: [] for k in builds},
    }
    found = {label: build["distributionExtensions"] for label, build in results["builds"].items()}
    if len({json.dumps(v) for v in found.values()}) > 1:
        parser.error(f"the builds install different extensions, so they cannot be compared: {found}")
    args.out.mkdir(parents=True, exist_ok=True)
    for i in range(args.runs):
        order = list(builds.items()) if i % 2 == 0 else list(reversed(builds.items()))
        for label, path in order:
            results["runs"][label].append(one_run(path, args.samples))
            (args.out / "perf.json").write_text(json.dumps(results, indent=1))
    results["scenes"] = {label: pooled(runs) for label, runs in results["runs"].items()}
    results["verdict"] = {label: verdict(scenes) for label, scenes in results["scenes"].items()}
    if "baseline" in builds:
        results["regressions"] = {
            name: regression(run_medians(results["runs"]["build"], name), run_medians(results["runs"]["baseline"], name))
            for name in (*TRANSITIONS, "new_tab")
        }
    (args.out / "perf.json").write_text(json.dumps(results, indent=1))
    print(json.dumps({"verdict": results["verdict"], "regressions": results.get("regressions")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
