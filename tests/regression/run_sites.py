#!/usr/bin/env python3
"""Real-site regression run (roadmap phase 3): Nulavio's protections against stock defaults.

Opens every page of sites.json twice in an engine profile of the Nulavio
build (headless, throwaway HOME): first as Nulavio ships it (Strict tracking
protection, uBlock Origin installed by policy), then as a stock engine would
(Standard tracking protection, uBlock Origin off). For each page it records
the final address, title, amount of text, links and images, how many
origins the engine blocked, and a screenshot. Pages where the protected run
loses much of the content, fails, or looks very different are flagged for
triage by a person; ads and trackers removed are expected differences.

Public landing pages only: no sign-in, no forms. Nothing is sent anywhere
but the sites themselves. Opt-in, needs the network:

    NULAVIO_ENGINE=<nulavio build> python3 tests/regression/run_sites.py --out tests/artifacts/sites
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
import harness  # noqa: E402
import pngdiff  # noqa: E402
from marionette import MarionetteError  # noqa: E402

UBLOCK = "uBlock0@raymondhill.net"
COLLECT = (
    "return {url: location.href, title: document.title,"
    " text: (document.body && document.body.innerText || '').length,"
    " links: document.links.length, images: document.images.length,"
    " frames: document.querySelectorAll('iframe').length};"
)
BLOCKED = (
    "const log = JSON.parse(gBrowser.selectedBrowser.getContentBlockingLog());"
    "return Object.values(log).filter(events => events.some(e => e[1])).length;"
)


def visit(m, site: dict, shots: Path, phase: str, settle: float) -> dict:
    result: dict = {"error": None}
    try:
        m.navigate(site["url"])
    except MarionetteError as exc:  # a timeout still leaves a page to look at; an error page is recorded
        result["error"] = str(exc.args[0].get("error") if exc.args and isinstance(exc.args[0], dict) else exc)[:120]
    time.sleep(settle)
    try:
        result.update(m.execute(COLLECT))
        result["blocked"] = m.chrome(BLOCKED)
        png = m.screenshot_png(full=False)
        (shots / f"{site['id']}-{phase}.png").write_bytes(png)
    except (MarionetteError, OSError) as exc:
        result["error"] = result["error"] or f"collect: {str(exc)[:100]}"
    return result


def flags(protected: dict, stock: dict, visual: dict | None) -> list[str]:
    out = []
    if protected.get("error") and not stock.get("error"):
        out.append(f"error only with protections: {protected['error']}")
    if str(protected.get("url", "")).startswith(("about:neterror", "about:certerror", "about:blocked")):
        out.append("error page with protections")
    if stock.get("text", 0) > 500 and protected.get("text", 0) < 0.5 * stock["text"]:
        out.append(f"text {protected.get('text', 0)} vs {stock['text']}")
    if stock.get("links", 0) > 20 and protected.get("links", 0) < 0.5 * stock["links"]:
        out.append(f"links {protected.get('links', 0)} vs {stock['links']}")
    if visual and visual["changed"] > 0.35:
        out.append(f"looks different ({int(visual['changed'] * 100)}% of the screen)")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sites", type=Path, default=HERE / "sites.json")
    parser.add_argument("--out", type=Path, default=harness.artifacts_dir() / "sites")
    parser.add_argument("--only", nargs="*", help="site ids")
    parser.add_argument("--settle", type=float, default=4.0, help="seconds to wait after load")
    args = parser.parse_args()
    sites = json.loads(args.sites.read_text())["sites"]
    if args.only:
        sites = [s for s in sites if s["id"] in args.only]
    shots = args.out / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)

    session = harness.GeckoProfileSession(name="Regressao")
    try:
        m = session.start()
        m.send("WebDriver:SetWindowRect", {"width": 1366, "height": 900})
        m.send("WebDriver:SetTimeouts", {"pageLoad": 25000})
        if not harness.wait_until(lambda: m.chrome(f"return Boolean(WebExtensionPolicy.getByID('{UBLOCK}')?.active);"), 120):
            print("uBlock Origin was not installed by policy (network?)", file=sys.stderr)
            return 2
        category = m.chrome("return Services.prefs.getStringPref('browser.contentblocking.category');")
        results: dict = {s["id"]: {"url": s["url"], "category": s["category"]} for s in sites}
        for site in sites:
            print(f"nulavio  {site['id']}", flush=True)
            results[site["id"]]["nulavio"] = visit(m, site, shots, "nulavio", args.settle)
        # Stock defaults: the engine's Standard category, no content filter.
        m.set_context("chrome")
        try:
            m.execute_async(
                "const done = arguments[arguments.length - 1];"
                "ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs').AddonManager"
                f".getAddonByID('{UBLOCK}').then(a => a.disable()).then(() => done(true), e => done(String(e)));"
            )
        finally:
            m.set_context("content")
        m.chrome("Services.prefs.setStringPref('browser.contentblocking.category', 'standard');")
        for site in sites:
            print(f"stock    {site['id']}", flush=True)
            results[site["id"]]["stock"] = visit(m, site, shots, "stock", args.settle)
    finally:
        session.cleanup()

    flagged = 0
    for site in sites:
        entry = results[site["id"]]
        visual = None
        a, b = shots / f"{site['id']}-nulavio.png", shots / f"{site['id']}-stock.png"
        if a.exists() and b.exists():
            try:
                visual = pngdiff.difference(a.read_bytes(), b.read_bytes())
            except ValueError:
                visual = None
        entry["visual"] = visual
        entry["flags"] = flags(entry["nulavio"], entry["stock"], visual)
        flagged += bool(entry["flags"])
    report = {"protected_category": category, "sites": results, "flagged": flagged}
    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(sites)} sites, {flagged} flagged for triage; report: {args.out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
