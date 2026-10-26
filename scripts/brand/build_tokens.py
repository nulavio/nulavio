#!/usr/bin/env python3
"""Generate CSS custom properties from docs/brand/tokens.json.

Semantic colours switch with the system colour scheme (light by default,
dark under ``prefers-color-scheme: dark``) and can be forced with
``data-theme="light|dark"`` on the root element or on any subtree.

A second file serves the browser window (Nulavio Shell, Track B): the same
tokens with colours as ``light-dark(light, dark)``, which follow the
colour scheme the engine sets on its chrome.

    python3 -I scripts/brand/build_tokens.py            # write both files
    python3 -I scripts/brand/build_tokens.py --check    # fail if either file is stale (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contrast import flatten, resolve  # noqa: E402

TOKENS = ROOT / "docs" / "brand" / "tokens.json"
OUTPUT = ROOT / "browser" / "startpage" / "tokens.css"
CHROME_OUTPUT = ROOT / "browser" / "branding" / "nulavio" / "content" / "theme" / "tokens.css"
HEADER = "/* Generated from docs/brand/tokens.json by scripts/brand/build_tokens.py. Do not edit. */\n"


def css_value(token: dict, tokens: dict[str, dict], path: str) -> str:
    value = resolve(tokens, path)
    kind = token.get("$type")
    if kind == "fontFamily":
        return ", ".join(f'"{v}"' if " " in v else v for v in value)
    if kind == "cubicBezier":
        return "cubic-bezier({})".format(", ".join(str(v) for v in value))
    return str(value)


def var_name(path: str) -> str:
    return "--nv-" + path.replace(".", "-")


def build(data: dict) -> str:
    tokens = flatten(data)
    lines = [HEADER]
    shared = []
    themes: dict[str, list[str]] = {"light": [], "dark": []}
    for path, token in tokens.items():
        if path.startswith("color.primitive."):
            continue
        if path.startswith(("color.light.", "color.dark.")):
            theme = path.split(".")[1]
            semantic = "color." + ".".join(path.split(".")[2:])
            themes[theme].append(f"  {var_name(semantic)}: {css_value(token, tokens, path)};")
        else:
            shared.append(f"  {var_name(path)}: {css_value(token, tokens, path)};")
    lines.append(":root {\n  color-scheme: light dark;\n" + "\n".join(shared + themes["light"]) + "\n}\n")
    dark = "\n".join("  " + line for line in themes["dark"])
    lines.append('@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {\n' + dark + "\n  }\n}\n")
    # Element-level selectors let a subtree force a theme (mockups, previews).
    lines.append('[data-theme="dark"] {\n  color-scheme: dark;\n' + "\n".join(themes["dark"]) + "\n}\n")
    lines.append('[data-theme="light"] {\n  color-scheme: light;\n' + "\n".join(themes["light"]) + "\n}\n")
    return "\n".join(lines)


def build_chrome(data: dict) -> str:
    """Tokens for the browser window: one :root block, colours as light-dark()."""
    tokens = flatten(data)
    shared, colors = [], {}
    for path, token in tokens.items():
        if path.startswith("color.primitive."):
            continue
        if path.startswith(("color.light.", "color.dark.")):
            theme, semantic = path.split(".")[1], "color." + ".".join(path.split(".")[2:])
            colors.setdefault(semantic, {})[theme] = css_value(token, tokens, path)
        else:
            shared.append(f"  {var_name(path)}: {css_value(token, tokens, path)};")
    lines = [
        f"  {var_name(name)}: light-dark({v['light']}, {v['dark']});"
        if len(v) == 2
        else f"  {var_name(name)}: {next(iter(v.values()))};"  # defined for one theme only
        for name, v in colors.items()
    ]
    note = "/* Nulavio Shell tokens for the browser window. Colours follow the engine's colour scheme. */\n"
    return HEADER + note + ":root {\n" + "\n".join(shared + lines) + "\n}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    status = 0
    for out, css in ((OUTPUT, build(data)), (CHROME_OUTPUT, build_chrome(data))):
        if args.check:
            current = out.read_text(encoding="utf-8") if out.exists() else ""
            if current != css:
                print(f"{out.relative_to(ROOT)} is stale; run scripts/brand/build_tokens.py", file=sys.stderr)
                status = 1
            else:
                print(f"{out.relative_to(ROOT)} is up to date")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(css, encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
