#!/usr/bin/env python3
"""Render and score the three Nulavio Shell UI directions (docs/design/visual-directions.md).

The same slice of the main window (tab strip, toolbar, address bar, extension
buttons, the top of a page) is drawn for each direction in light and dark, so
the directions differ only by their tokens and geometry. Contrast is measured
on the pairs the chrome actually uses (WCAG 2.2: 4.5:1 text, 3:1 non-text).

    python3 -I scripts/brand/ui_directions.py            # PNGs + docs/design/assets/directions/contrast.json
    python3 -I scripts/brand/ui_directions.py --html-only

Rendering uses the system Firefox in headless mode with a throwaway profile.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contrast import ratio  # noqa: E402

OUT = ROOT / "docs" / "design" / "assets" / "directions"
FIREFOX = Path("/usr/lib64/firefox/firefox")

# Each theme: toolbox (tab strip), toolbar, tab (selected), field, text levels,
# icon, accent (non-text indicator), focus ring, border.
DIRECTIONS = {
    "horizon": {
        "name": "Horizon (ocean and mint)",
        "geometry": {"tab_h": 34, "tab_r": 10, "bar_h": 44, "field_h": 38, "field_r": 12, "btn_r": 10, "indicator": "route"},
        "light": {
            "toolbox": "#E2EBEE",
            "toolbar": "#F1F7F5",
            "tab": "#FFFFFF",
            "field": "#FFFFFF",
            "text": "#0B1623",
            "text2": "#23495A",
            "muted": "#4F7383",
            "icon": "#23495A",
            "accent": "#0F7A68",
            "focus": "#0F7A68",
            "border": "#BFD0D6",
        },
        "dark": {
            "toolbox": "#070F18",
            "toolbar": "#0B1623",
            "tab": "#183746",
            "field": "#112432",
            "text": "#F1F7F5",
            "text2": "#BFD0D6",
            "muted": "#8FAAB5",
            "icon": "#BFD0D6",
            "accent": "#6FE0C5",
            "focus": "#6FE0C5",
            "border": "#23495A",
        },
    },
    "graphite": {
        "name": "Graphite and copper (no blue or green)",
        "geometry": {"tab_h": 34, "tab_r": 4, "bar_h": 44, "field_h": 36, "field_r": 6, "btn_r": 4, "indicator": "top"},
        "light": {
            "toolbox": "#E9E6E1",
            "toolbar": "#F7F5F1",
            "tab": "#FFFFFF",
            "field": "#FFFFFF",
            "text": "#1F1C19",
            "text2": "#4A443D",
            "muted": "#6A635A",
            "icon": "#4A443D",
            "accent": "#9C4A22",
            "focus": "#9C4A22",
            "border": "#CFC8BE",
        },
        "dark": {
            "toolbox": "#141210",
            "toolbar": "#1C1A17",
            "tab": "#2A2622",
            "field": "#24211D",
            "text": "#F3EFE9",
            "text2": "#D3CBC0",
            "muted": "#ABA295",
            "icon": "#D3CBC0",
            "accent": "#E79A69",
            "focus": "#E79A69",
            "border": "#3D3832",
        },
    },
    "monoline": {
        "name": "Monoline (dense, neutral, accent only on focus)",
        "geometry": {"tab_h": 30, "tab_r": 0, "bar_h": 38, "field_h": 30, "field_r": 4, "btn_r": 4, "indicator": "hairline"},
        "light": {
            "toolbox": "#F4F4F5",
            "toolbar": "#FFFFFF",
            "tab": "#FFFFFF",
            "field": "#F4F4F5",
            "text": "#18181B",
            "text2": "#3F3F46",
            "muted": "#5E5E66",
            "icon": "#3F3F46",
            "accent": "#18181B",
            "focus": "#0F7A68",
            "border": "#D4D4D8",
        },
        "dark": {
            "toolbox": "#121214",
            "toolbar": "#1A1A1D",
            "tab": "#1A1A1D",
            "field": "#232327",
            "text": "#F4F4F5",
            "text2": "#D4D4D8",
            "muted": "#A1A1AA",
            "icon": "#D4D4D8",
            "accent": "#F4F4F5",
            "focus": "#6FE0C5",
            "border": "#34343A",
        },
    },
}

# (label, fg, bg, minimum)
PAIRS = [
    ("Selected tab label", "text", "tab", 4.5),
    ("Background tab label", "text2", "toolbox", 4.5),
    ("Toolbar text", "text", "toolbar", 4.5),
    ("Address text", "text", "field", 4.5),
    ("Address placeholder", "muted", "field", 4.5),
    ("Toolbar icons", "icon", "toolbar", 3.0),
    ("Focus ring on toolbar", "focus", "toolbar", 3.0),
    ("Focus ring on field", "focus", "field", 3.0),
    ("Selected-tab indicator on tab", "accent", "tab", 3.0),
]

PROPOSED = {"Deep Ocean": "#0C1822", "Slate": "#193946", "Mint": "#7BE5D0", "Cloud": "#F1F7F8", "Amber": "#E4AC68"}
BRAND = {
    "Deep Ocean": ("navy.900", "#0B1623"),
    "Slate": ("navy.800", "#183746"),
    "Mint": ("mint.400", "#6FE0C5"),
    "Cloud": ("navy.50", "#F1F7F5"),
    "Amber": ("amber.400", "#E7AE61"),
}

ICONS = {
    "back": "M15 6 9 12l6 6",
    "forward": "M9 6l6 6-6 6",
    "reload": "M19 12a7 7 0 1 1-2-5M19 4v4h-4",
    "star": "M12 4l2.4 5 5.4.6-4 3.7 1.1 5.3L12 16l-4.9 2.6L8.2 13.3l-4-3.7 5.4-.6z",
    "puzzle": "M9 5h4v2a2 2 0 1 0 0 0V5h4v4h-2a2 2 0 1 0 0 4h2v4h-4v-2a2 2 0 1 0-4 0v2H5v-4h2a2 2 0 1 0 0-4H5V5z",
    "menu": "M5 7h14M5 12h14M5 17h14",
    "shield": "M12 4l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V7z",
    "lock": "M8 11V8a4 4 0 0 1 8 0v3M7 11h10v8H7z",
    "plus": "M12 6v12M6 12h12",
    "close": "M8 8l8 8M16 8l-8 8",
    "globe": "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16M4 12h16M12 4c3 3 3 13 0 16M12 4c-3 3-3 13 0 16",
    "muted": "M5 10h3l4-3v10l-4-3H5zM16 10l4 4M20 10l-4 4",
    "key": "M14 10a3 3 0 1 1-3 3l-6 0v2h2v2",
}


def icon(name: str, color: str, size: int = 16) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" '
        f'stroke-linecap="round" stroke-linejoin="round"><path d="{ICONS[name]}"/></svg>'
    )


def html(direction: dict, theme: str) -> str:
    c, g = direction[theme], direction["geometry"]
    ind = {
        "route": "position:absolute;left:50%;bottom:3px;width:16px;height:2px;margin-left:-8px;border-radius:2px;"
        f"background:{c['accent']}",
        "top": f"position:absolute;left:{g['tab_r'] + 6}px;right:{g['tab_r'] + 6}px;top:0;height:2px;background:{c['accent']}",
        "hairline": f"position:absolute;left:0;right:0;bottom:0;height:2px;background:{c['accent']}",
    }[g["indicator"]]
    shadow = "0 1px 2px rgba(7,15,24,.18)" if theme == "light" else "0 1px 2px rgba(0,0,0,.5)"
    sep = f"border-bottom:1px solid {c['border']};" if direction is DIRECTIONS["monoline"] else ""
    tab_bg_sel = (
        f"background:{c['tab']};box-shadow:{shadow};" if direction is not DIRECTIONS["monoline"] else f"background:{c['tab']};"
    )

    def tab(label: str, *, selected=False, pinned=False, muted=False, fav="globe") -> str:
        style = tab_bg_sel if selected else ""
        width = "40px" if pinned else "200px"
        color = c["text"] if selected else c["text2"]
        weight = "600" if selected else "400"
        inner = (
            icon(fav, c["accent"] if fav == "n" else color, 16)
            if fav != "n"
            else f'<span style="font-weight:700;color:{c["accent"]};font-size:13px">N</span>'
        )
        if not pinned:
            inner += f'<span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{label}</span>'
            if muted:
                inner += icon("muted", c["text2"], 14)
            inner += icon("close", c["text2"], 14)
        indicator = f'<span style="{ind}"></span>' if selected else ""
        return (
            f'<div style="position:relative;display:flex;align-items:center;gap:8px;height:{g["tab_h"]}px;width:{width};'
            f'padding:0 10px;border-radius:{g["tab_r"]}px;{style}color:{color};font-weight:{weight};box-sizing:border-box">'
            f"{inner}{indicator}</div>"
        )

    def button(name: str, color=None) -> str:
        return (
            f'<div style="width:32px;height:32px;border-radius:{g["btn_r"]}px;display:grid;place-items:center">'
            f"{icon(name, color or c['icon'], 16)}</div>"
        )

    ext = (
        '<div style="width:32px;height:32px;display:grid;place-items:center"><span style="width:16px;height:16px;'
        'border-radius:4px;background:#800000;display:block"></span></div>'
        '<div style="width:32px;height:32px;display:grid;place-items:center"><span style="width:16px;height:16px;'
        'border-radius:50%;background:#6D4AFF;display:block"></span></div>'
    )
    field_border = f"2px solid {c['focus']}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;font:13px/1.2 'Noto Sans',system-ui,sans-serif;background:{c["toolbar"]}}}
</style></head><body>
<div style="background:{c["toolbox"]};padding:6px 8px 0 8px;display:flex;align-items:center;gap:4px;
     height:44px;box-sizing:border-box">
  {tab("", pinned=True)}{tab("Inbox")}{tab("Research", muted=True)}{tab("Weather")}{tab("New tab", selected=True, fav="n")}
  <div style="width:32px;height:32px;display:grid;place-items:center">{icon("plus", c["icon"], 16)}</div>
</div>
<div style="background:{c["toolbar"]};display:flex;align-items:center;gap:4px;height:{g["bar_h"]}px;padding:0 8px;{sep}">
  {button("back")}{button("forward", c["muted"])}{button("reload")}
  <div style="flex:1;max-width:860px;margin:0 auto;height:{g["field_h"]}px;box-sizing:border-box;border-radius:{g["field_r"]}px;
       background:{c["field"]};border:{field_border};display:flex;align-items:center;gap:8px;padding:0 12px;color:{c["muted"]}">
    {icon("shield", c["icon"], 16)}{icon("lock", c["icon"], 16)}<span>Search or enter address</span>
    <span style="flex:1"></span>{icon("star", c["icon"], 16)}
  </div>
  {ext}{button("puzzle")}{button("key")}{button("menu")}
</div>
<div style="height:132px;background:{c["toolbar"] if theme == "light" else c["toolbox"]};display:grid;place-items:center;
     color:{c["text"]};font-size:22px;font-weight:600;border-top:1px solid {c["border"]}">{direction["name"]}</div>
</body></html>"""


def delta_e(a: str, b: str) -> float:
    """CIE76 distance in CIELAB (D65): enough to tell 'same colour' from 'different colour'."""

    def lab(hex_color: str):
        rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in rgb]
        x = (lin[0] * 0.4124 + lin[1] * 0.3576 + lin[2] * 0.1805) / 0.95047
        y = lin[0] * 0.2126 + lin[1] * 0.7152 + lin[2] * 0.0722
        z = (lin[0] * 0.0193 + lin[1] * 0.1192 + lin[2] * 0.9505) / 1.08883
        f = [t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in (x, y, z)]
        return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])

    return math.dist(lab(a), lab(b))


def scores() -> dict:
    out = {}
    for key, d in DIRECTIONS.items():
        rows = []
        for theme in ("light", "dark"):
            for label, fg, bg, minimum in PAIRS:
                r = ratio(d[theme][fg], d[theme][bg])
                rows.append(
                    {
                        "theme": theme,
                        "pair": label,
                        "fg": d[theme][fg],
                        "bg": d[theme][bg],
                        "ratio": round(r, 2),
                        "min": minimum,
                        "pass": r >= minimum,
                    }
                )
        out[key] = {"name": d["name"], "pairs": rows, "passing": sum(r["pass"] for r in rows), "total": len(rows)}
    out["proposed_palette"] = [
        {
            "name": n,
            "proposed": PROPOSED[n],
            "brand_token": BRAND[n][0],
            "brand": BRAND[n][1],
            "deltaE76": round(delta_e(PROPOSED[n], BRAND[n][1]), 1),
        }
        for n in PROPOSED
    ]
    return out


def render(page: Path, png: Path) -> None:
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [
                str(FIREFOX),
                "--headless",
                "--no-remote",
                "--profile",
                profile,
                "--window-size=1366,220",
                "--screenshot",
                str(png),
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--html-only", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for key, d in DIRECTIONS.items():
            for theme in ("light", "dark"):
                page = Path(tmp) / f"{key}-{theme}.html"
                page.write_text(html(d, theme), encoding="utf-8")
                if args.html_only:
                    shutil.copy(page, OUT / page.name)
                else:
                    render(page, OUT / f"{key}-{theme}.png")
    result = scores()
    (OUT / "contrast.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for key in DIRECTIONS:
        print(f"{key}: {result[key]['passing']}/{result[key]['total']} pairs pass")
        for row in result[key]["pairs"]:
            if not row["pass"]:
                print("   FAIL", row)
    for row in result["proposed_palette"]:
        print(f"{row['name']}: proposed {row['proposed']} vs {row['brand_token']} {row['brand']} -> dE76 {row['deltaE76']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
