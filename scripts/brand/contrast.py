#!/usr/bin/env python3
"""WCAG 2.2 contrast checks for Nulavio design tokens.

Reads docs/brand/tokens.json (W3C Design Tokens format), resolves aliases
and checks every pair listed under ``$extensions["nulavio.contrast"]``:

    {"fg": "color.dark.text.primary", "bg": "color.dark.bg.canvas", "min": 4.5}

Composited pairs also declare ``backdrops`` (opaque token references) and
optionally ``opacity`` (surface multiplier, number or numeric-token path).
Foreground alpha is composited last, in sRGB; ratios use unrounded channels.
Exit 1 on a failed minimum, 2 on invalid declarations. ``--report`` prints
Markdown; ``--json`` exposes the exact expanded set. This is not an interface
WCAG conformance assessment.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOKENS = ROOT / "docs" / "brand" / "tokens.json"


def _channel(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgba(color: str) -> tuple[float, float, float, float]:
    if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return (*[float(int(color[i : i + 2], 16)) for i in (1, 3, 5)], 1.0)
    match = re.fullmatch(r"rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)", str(color))
    if match:
        try:
            r, g, b, a = map(float, match.groups())
            if all(math.isfinite(c) and 0 <= c <= 255 for c in (r, g, b)) and math.isfinite(a) and 0 <= a <= 1:
                return r, g, b, a
        except ValueError:
            pass
    raise ValueError(f"expected #RRGGBB or valid rgba(), got {color!r}")


def luminance(color: str | tuple[float, ...]) -> float:
    r, g, b, a = rgba(color) if isinstance(color, str) else color
    if a != 1:
        raise ValueError("translucent colour requires an explicit backdrop")
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def ratio(fg, bg) -> float:
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def composite(surface, backdrop, opacity: float = 1):
    if backdrop[3] != 1:
        raise ValueError("backdrop must be opaque")
    alpha = surface[3] * opacity
    return (*(surface[i] * alpha + backdrop[i] * (1 - alpha) for i in range(3)), 1.0)


def display(color) -> str:
    return "#" + "".join(f"{round(c):02X}" for c in color[:3])


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


def resolve(tokens: dict[str, dict], path: str, depth: int = 0, _seen: tuple[str, ...] = ()):
    if path in _seen:
        raise ValueError("alias cycle: " + " -> ".join((*_seen, path)))
    if path not in tokens:
        raise ValueError(f"unknown token reference: {path}")
    value = tokens[path]["$value"]
    if isinstance(value, str) and ("{" in value or "}" in value):
        if not (value.startswith("{") and value.endswith("}") and value.count("{") == value.count("}") == 1):
            raise ValueError(f"invalid alias at {path}: {value}")
        return resolve(tokens, value[1:-1], depth + 1, (*_seen, path))
    return value


def checked_pairs(data: dict) -> list[dict]:
    """Expand each declaration into the exact evaluated set; ratios use unrounded sRGB."""
    tokens = flatten(data)
    rows = []
    pairs = data.get("$extensions", {}).get("nulavio.contrast")
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("nulavio.contrast must be a nonempty list")
    for index, pair in enumerate(pairs):
        try:
            if not isinstance(pair, dict) or set(pair) - {"fg", "bg", "min", "backdrops", "opacity"}:
                raise ValueError("invalid pair fields")
            minimum = pair["min"]
            if (
                isinstance(minimum, bool)
                or not isinstance(minimum, (float, int))
                or not math.isfinite(minimum)
                or not 1 <= minimum <= 21
            ):
                raise ValueError("minimum must be between 1 and 21")
            fg, bg = rgba(resolve(tokens, pair["fg"])), rgba(resolve(tokens, pair["bg"]))
            opacity = pair.get("opacity", 1)
            if isinstance(opacity, str):
                opacity = resolve(tokens, opacity)
            if (
                isinstance(opacity, bool)
                or not isinstance(opacity, (int, float))
                or not math.isfinite(opacity)
                or not 0 <= opacity <= 1
            ):
                raise ValueError("invalid surface opacity")
            backdrops = pair.get("backdrops", [None])
            if (
                not isinstance(backdrops, list)
                or not backdrops
                or any(not isinstance(p, str) or not p for p in backdrops if p is not None)
            ):
                raise ValueError("backdrops must be a nonempty list of token references")
            if "backdrops" in pair and None in backdrops:
                raise ValueError("invalid backdrop reference")
            if "backdrops" not in pair and (bg[3] != 1 or opacity != 1):
                raise ValueError("surface opacity requires explicit backdrops")
            for backdrop in backdrops:
                background = composite(bg, rgba(resolve(tokens, backdrop)), opacity) if backdrop else bg
                foreground = composite(fg, background)
                value = ratio(foreground, background)
                rows.append(
                    {
                        "fg": pair["fg"],
                        "bg": pair["bg"],
                        "backdrop": backdrop,
                        "opacity": opacity,
                        "surface": resolve(tokens, pair["bg"]),
                        "backdropColor": resolve(tokens, backdrop) if backdrop is not None else None,
                        "foregroundRGBA": foreground,
                        "backgroundRGBA": background,
                        "foreground": display(foreground),
                        "background": display(background),
                        "ratio": value,
                        "min": minimum,
                        "pass": value >= minimum,
                    }
                )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"contrast pair {index}: {error}") from error
    return rows


def check(data: dict) -> list[tuple[str, str, str, str, float, float, bool]]:
    """Keep the seven-field tuple API used by existing callers."""
    return [
        (
            r["fg"],
            r["bg"] + (f" over {r['backdrop']}" if r["backdrop"] else ""),
            r["foreground"],
            r["background"],
            r["ratio"],
            r["min"],
            r["pass"],
        )
        for r in checked_pairs(data)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tokens", type=Path, default=TOKENS)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--json", action="store_true", help="print the exact expanded checked set")
    args = parser.parse_args()
    try:
        data = json.loads(args.tokens.read_text(encoding="utf-8"))
        rows = check(data)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(checked_pairs(data), indent=2, allow_nan=False))
        return int(any(not row[-1] for row in rows))
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
