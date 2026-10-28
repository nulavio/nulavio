#!/usr/bin/env python3
"""Generate CSS custom properties from docs/brand/tokens.json.

Semantic colours switch with the system colour scheme (light by default,
dark under ``prefers-color-scheme: dark``) and can be forced with
``data-theme="light|dark"`` on the root element or on any subtree.

A second file serves the browser window (Nulavio Shell, Track B): the same
tokens with colours as ``light-dark(light, dark)``, which follow the
colour scheme the engine sets on its chrome. A third, a JavaScript module,
gives the Shell the profile identity colours it draws into the toolbar icon.

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
IDENTITY_OUTPUT = ROOT / "browser" / "shell" / "lib" / "identity-colors.js"
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


class TokenError(ValueError):
    pass


def one_theme_tokens(data: dict) -> list[str]:
    """Semantic colours defined for one theme only (e.g. color.light.x without color.dark.x)."""
    names: dict[str, set[str]] = {"light": set(), "dark": set()}
    for path in flatten(data):
        if path.startswith(("color.light.", "color.dark.")):
            theme, _, name = path[len("color.") :].partition(".")
            names[theme].add(name)
    missing = [
        f"color.{other}.{name}" for theme, other in (("light", "dark"), ("dark", "light")) for name in names[theme] - names[other]
    ]
    return sorted(missing)


def require_both_themes(data: dict) -> None:
    """A colour missing in one theme would fall back to an unrelated value there (the light critical
    text once rendered navy, and the chrome file got the dark value in light): refuse to generate."""
    missing = one_theme_tokens(data)
    if missing:
        raise TokenError("semantic colour defined for one theme only; add: " + ", ".join(missing))


def build(data: dict) -> str:
    require_both_themes(data)
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
    require_both_themes(data)
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
    lines = [f"  {var_name(name)}: light-dark({v['light']}, {v['dark']});" for name, v in colors.items()]
    note = "/* Nulavio Shell tokens for the browser window. Colours follow the engine's colour scheme. */\n"
    return HEADER + note + ":root {\n" + "\n".join(shared + lines) + "\n}\n"


def build_identity(data: dict) -> str:
    """Profile identity colours (same in both themes) for canvas drawing in the Shell."""
    tokens = flatten(data)
    prefix = "color.light.identity."
    colors = {path[len(prefix) :]: resolve(tokens, path) for path in tokens if path.startswith(prefix)}
    body = ",\n".join(f'  {name}: "{value}"' for name, value in colors.items())
    return (
        HEADER.replace("/*", "//", 1).replace(" */", "", 1)
        + "export const IDENTITY_COLORS = Object.freeze({\n"
        + body
        + ",\n});\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    try:
        require_both_themes(data)
    except TokenError as error:
        print(f"{TOKENS.relative_to(ROOT)}: {error}", file=sys.stderr)
        return 2
    status = 0
    for out, css in ((OUTPUT, build(data)), (CHROME_OUTPUT, build_chrome(data)), (IDENTITY_OUTPUT, build_identity(data))):
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
