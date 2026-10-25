#!/usr/bin/env python3
"""WCAG 2.2 contrast checks for Nulavio design tokens.

Reads docs/brand/tokens.json (W3C Design Tokens format), resolves aliases
and checks every pair listed under ``$extensions["nulavio.contrast"]``:

    {"fg": "color.dark.text.primary", "bg": "color.dark.bg.canvas", "min": 4.5}

Exit status 1 if any pair is below its minimum. ``--report`` prints a
Markdown table used in docs/brand/guidelines.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / "docs" / "brand" / "tokens.json"


def _channel(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_color}")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def ratio(fg: str, bg: str) -> float:
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def flatten(tree: dict, prefix: str = "") -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key, value in tree.items():
        if key.startswith("$"):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and "$value" in value:
            out[path] = value
        elif isinstance(value, dict):
            out.update(flatten(value, path))
    return out


def resolve(tokens: dict[str, dict], path: str, depth: int = 0) -> str:
    if depth > 10:
        raise ValueError(f"alias loop at {path}")
    value = tokens[path]["$value"]
    if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        return resolve(tokens, value[1:-1], depth + 1)
    return value


def check(data: dict) -> list[tuple[str, str, str, str, float, float, bool]]:
    tokens = flatten(data)
    rows = []
    for pair in data["$extensions"]["nulavio.contrast"]:
        fg, bg = resolve(tokens, pair["fg"]), resolve(tokens, pair["bg"])
        value = ratio(fg, bg)
        rows.append((pair["fg"], pair["bg"], fg, bg, value, pair["min"], value >= pair["min"]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tokens", type=Path, default=TOKENS)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    rows = check(json.loads(args.tokens.read_text(encoding="utf-8")))
    if args.report:
        print("| Foreground | Background | Ratio | Required | Result |")
        print("|---|---|---:|---:|---|")
    failures = 0
    for fg_name, bg_name, fg, bg, value, minimum, ok in rows:
        failures += not ok
        if args.report:
            level = "AAA" if value >= 7 else "AA" if value >= 4.5 else "AA large/UI" if value >= 3 else "fail"
            print(f"| `{fg_name}` {fg} | `{bg_name}` {bg} | {value:.2f}:1 | {minimum}:1 | {'✅' if ok else '❌'} {level} |")
        elif not ok:
            print(f"FAIL {fg_name} ({fg}) on {bg_name} ({bg}): {value:.2f} < {minimum}", file=sys.stderr)
    if not args.report:
        print(f"{len(rows) - failures}/{len(rows)} contrast pairs pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
