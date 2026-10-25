#!/usr/bin/env python3
"""Capture branding evidence from a Nulavio (Track B) build, headless.

Screenshots: the About dialog, the main browser window (chrome) and the
private-browsing page, plus the brand strings the engine reports. Uses a
throwaway profile through the test harness (never a user profile).

    NULAVIO_ENGINE=~/.cache/nulavio-build/install/nulavio/nulavio \
        python3 -I scripts/research/trackb_branding_screenshots.py --out docs/brand/assets/review/trackb
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "launcher"), str(ROOT / "tests" / "lib")]

import harness  # noqa: E402

BRAND = """
const l10n = new Localization(["branding/brand.ftl"], true);
const ids = ["-brand-short-name", "-brand-full-name", "-brand-product-name", "-vendor-short-name"];
return {
  appName: Services.appinfo.name, vendor: Services.appinfo.vendor, appId: Services.appinfo.ID,
  brand: Object.fromEntries(ids.map(id => [id, l10n.formatValueSync("trademarkInfo") && null])),
  trademarkInfo: l10n.formatValueSync("trademarkInfo"),
  shortName: Services.strings.createBundle("chrome://branding/locale/brand.properties").GetStringFromName("brandShortName"),
};
"""


def shot(m, target: Path) -> None:
    data = m.send("WebDriver:TakeScreenshot", {"full": False})["value"]
    target.write_bytes(base64.b64decode(data))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    session = harness.Session(profile="brand")
    m = session.start()
    try:
        m.send("WebDriver:SetWindowRect", {"width": 1280, "height": 800})
        report = m.chrome(BRAND)
        report.pop("brand", None)
        # Main window chrome (tabs, toolbar) with the start page loaded.
        m.set_context("chrome")
        main = m.send("WebDriver:GetWindowHandle")["value"]
        time.sleep(2)
        shot(m, args.out / "main-window.png")
        # About dialog.
        before = set(m.send("WebDriver:GetWindowHandles"))
        m.execute("window.openAboutDialog();")
        time.sleep(3)
        dialogs = [h for h in m.send("WebDriver:GetWindowHandles") if h not in before]
        if dialogs:
            m.send("WebDriver:SwitchToWindow", {"handle": dialogs[0], "focus": False})
            time.sleep(1)
            shot(m, args.out / "about-dialog.png")
            report["about_dialog_text"] = m.execute("return document.documentElement.innerText || document.title;")[:400]
            m.send("WebDriver:CloseChromeWindow")
            m.send("WebDriver:SwitchToWindow", {"handle": main, "focus": False})
        m.set_context("content")
        # Private browsing page (logo + wordmark from the branding dir).
        m.navigate("about:privatebrowsing")
        time.sleep(2)
        shot(m, args.out / "private-browsing.png")
        (args.out / "branding-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(json.dumps(report, indent=2, ensure_ascii=False))
    finally:
        session.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
