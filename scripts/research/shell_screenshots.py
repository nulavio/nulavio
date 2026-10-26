#!/usr/bin/env python3
"""Capture the Nulavio main window for design QA (before/after evidence).

Matrix: light/dark x 100/125/150 % scale x 1366x768 and 1920x1080 (physical
pixels). Each shot starts the engine on a throwaway profile (test harness,
never a user profile) with five tabs: one pinned, one muted, the Nulavio new
tab selected. A second scene opens the address bar results.

    NULAVIO_ENGINE=~/.cache/nulavio-build/install/nulavio/nulavio \\
        python3 -I scripts/research/shell_screenshots.py --out /tmp/shots --label after

Writes <out>/<label>-<theme>-<w>x<h>@<scale>.png, <label>-urlbar-<theme>.png and
metrics.json (first paint and new-tab timings measured in the same runs).
"""

from __future__ import annotations

import argparse
import base64
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "launcher"), str(ROOT / "tests" / "lib")]

import harness  # noqa: E402

SIZES = [(1366, 768), (1920, 1080)]
SCALES = [1.0, 1.25, 1.5]
THEMES = {"light": 0, "dark": 1}
PAGES = ["Documentation", "Inbox", "Research", "Weather"]

NEW_TAB_TIMING = """
const [done] = [arguments[arguments.length - 1]];
const t0 = performance.now();
const tab = gBrowser.addTrustedTab(BROWSER_NEW_TAB_URL);
gBrowser.selectedTab = tab;
const check = () => {
  const doc = tab.linkedBrowser.contentDocument;
  // Cross-process: ask the page for readiness through the browser's title.
  if (tab.linkedBrowser.contentTitle && !tab.hasAttribute("busy")) done(performance.now() - t0);
  else setTimeout(check, 5);
};
check();
"""


def shot(m, target: Path) -> None:
    m.set_context("chrome")
    # Automation (Marionette) stripes the address bar to warn the user. These
    # captures show what a user sees, so the test-only indicator is removed
    # from the captured window only.
    m.execute("document.documentElement.removeAttribute('remotecontrol');")
    data = m.send("WebDriver:TakeScreenshot", {"full": False})["value"]
    target.write_bytes(base64.b64decode(data))


def scene(m, server) -> None:
    """Pinned tab, muted tab, a few pages, the Nulavio new tab selected."""
    m.set_context("chrome")
    m.execute(
        """
        const [base, names] = arguments;
        const first = gBrowser.selectedTab;
        for (const name of names) gBrowser.addTrustedTab(base + name);
        gBrowser.pinTab(gBrowser.tabs[1]);
        gBrowser.tabs[3].toggleMuteAudio();
        gBrowser.removeTab(first);
        """,
        [server.url("/page/"), PAGES],
    )
    m.execute("window.BrowserCommands.openTab();")
    time.sleep(2.5)


def capture(engine_label: str, out: Path, theme: str, size: tuple[int, int], scale: float, server, urlbar: bool) -> dict:
    harness.TEST_PREFS.update({"ui.systemUsesDarkTheme": THEMES[theme], "layout.css.devPixelsPerPx": str(scale)})
    session = harness.Session(profile="shots")
    m = session.start()
    try:
        info = m.chrome(
            "const s = Services.startup.getStartupInfo();"
            "return {firstPaint: s.firstPaint2 - s.process, sessionRestored: s.sessionRestored - s.process,"
            " name: Services.appinfo.name, version: Services.appinfo.version};"
        )
        width, height = size
        m.send("WebDriver:SetWindowRect", {"width": round(width / scale), "height": round(height / scale)})
        scene(m, server)
        name = f"{engine_label}-{theme}-{width}x{height}@{int(scale * 100)}.png"
        shot(m, out / name)
        if urlbar:
            m.set_context("chrome")
            m.execute("gURLBar.focus(); gURLBar.value = 'nul'; gURLBar.startQuery();")
            time.sleep(1.5)
            shot(m, out / f"{engine_label}-urlbar-{theme}.png")
            m.execute("gURLBar.view.close(); gURLBar.blur();")
        m.set_context("chrome")
        newtab = [m.execute_async(NEW_TAB_TIMING) for _ in range(3)]
        return {"shot": name, **info, "newTabMs": newtab}
    finally:
        session.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--quick", action="store_true", help="only 1366x768 at 100%%, both themes")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    results = []
    with harness.FixtureServer() as server:
        for theme in THEMES:
            for size in SIZES[:1] if args.quick else SIZES:
                for scale in SCALES[:1] if args.quick else SCALES:
                    first = size == SIZES[0] and scale == 1.0
                    results.append(capture(args.label, args.out, theme, size, scale, server, urlbar=first))
                    print(results[-1]["shot"], f"firstPaint={results[-1]['firstPaint']}ms", flush=True)
    paints = [r["firstPaint"] for r in results]
    newtabs = [t for r in results for t in r["newTabMs"]]
    summary = {
        "label": args.label,
        "engine": f"{results[0]['name']} {results[0]['version']}",
        "runs": len(results),
        "firstPaintMs": {"median": statistics.median(paints), "min": min(paints), "max": max(paints)},
        "sessionRestoredMs": {"median": statistics.median(r["sessionRestored"] for r in results)},
        "newTabMs": {
            "median": round(statistics.median(newtabs), 1),
            "min": round(min(newtabs), 1),
            "max": round(max(newtabs), 1),
        },
        "shots": results,
    }
    (args.out / f"{args.label}-metrics.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "shots"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
