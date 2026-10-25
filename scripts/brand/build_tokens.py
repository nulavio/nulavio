#!/usr/bin/env python3
"""Generate CSS custom properties from docs/brand/tokens.json.

Semantic colours switch with the system colour scheme (light by default,
dark under ``prefers-color-scheme: dark``) and can be forced with
``data-theme="light|dark"`` on the root element or on any subtree.

    python3 -I scripts/brand/build_tokens.py            # write browser/startpage/tokens.css
    python3 -I scripts/brand/build_tokens.py --check    # fail if the file is stale (CI)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", type=Path, default=OUTPUT)
    args = parser.parse_args()
    css = build(json.loads(TOKENS.read_text(encoding="utf-8")))
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != css:
            print(f"{args.out} is stale; run scripts/brand/build_tokens.py", file=sys.stderr)
            return 1
        print(f"{args.out.relative_to(ROOT)} is up to date")
        return 0
    args.out.write_text(css, encoding="utf-8")
    print(f"wrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
