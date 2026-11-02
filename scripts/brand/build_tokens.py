#!/usr/bin/env python3
"""Generate CSS custom properties from docs/brand/tokens.json.

Semantic colours switch with the system colour scheme (light by default,
dark under ``prefers-color-scheme: dark``) and can be forced with
``data-theme="light|dark"`` on the root element or on any subtree.

A second file serves the browser window (Nulavio Shell, Track B): the same
tokens with colours as ``light-dark(light, dark)``, which follow the
colour scheme the engine sets on its chrome. A third, a JavaScript module,
gives the Shell the profile identity colours it draws into the toolbar icon.

    python3 -I scripts/brand/build_tokens.py            # write generated files
    python3 -I scripts/brand/build_tokens.py --check    # fail if any generated file is stale (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contrast import flatten, resolve, rgba  # noqa: E402

TOKENS = ROOT / "docs" / "brand" / "tokens.json"
OUTPUT = ROOT / "browser" / "startpage" / "tokens.css"
CHROME_OUTPUT = ROOT / "browser" / "branding" / "nulavio" / "content" / "theme" / "tokens.css"
IDENTITY_OUTPUT = ROOT / "browser" / "shell" / "lib" / "identity-colors.js"
SIDEBAR_OUTPUT = ROOT / "browser" / "shell" / "shared" / "sidebar-focus.css"
IN_CONTENT_OUTPUT = ROOT / "browser" / "shell" / "shared" / "in-content.css"
# Internal pages that use the engine's design tokens (UX3F A2). Exact about: URLs only.
IN_CONTENT_PAGES = (
    "about:preferences",
    "about:settings",
    "about:addons",
    "about:home",
    "about:newtab",
    "about:profiles",
    "about:editprofile",
    "about:newprofile",
    "about:deleteprofile",
)
# The engine's Nova palette re-valued with Nulavio's: violet (its accent) -> mint,
# desaturated violet (its tinted neutrals) -> navy, and its violet-tinted light/dark
# surfaces. Each value is a primitive token or a mix of two (weight of the first).
NOVA_TO_NULAVIO = {
    "--color-violet-0": ("mint.100", "navy.0", 0.5),
    "--color-violet-10": "mint.100",
    "--color-violet-20": "mint.200",
    "--color-violet-30": "mint.400",
    "--color-violet-40": ("mint.400", "mint.700", 0.5),
    "--color-violet-50": "mint.700",
    "--color-violet-60": ("mint.700", "mint.900", 0.6),
    "--color-violet-70": ("mint.700", "mint.900", 0.3),
    "--color-violet-80": "mint.900",
    "--color-violet-90": ("mint.900", "navy.1000", 0.5),
    "--color-violet-desaturated-0": "navy.50",
    "--color-violet-desaturated-10": "navy.100",
    "--color-violet-desaturated-20": "navy.200",
    "--color-violet-desaturated-30": "navy.300",
    "--color-violet-desaturated-40": "navy.400",
    "--color-violet-desaturated-50": "navy.500",
    "--color-violet-desaturated-60": "navy.600",
    "--color-violet-desaturated-70": "navy.700",
    "--color-violet-desaturated-80": "navy.800",
    "--color-violet-desaturated-90": "navy.900",
    "--color-gray-0": "navy.50",
    "--color-gray-05": ("navy.50", "navy.100", 0.5),
    "--color-gray-10": "navy.100",
    "--color-gray-80": "navy.850",
    "--color-gray-85": "navy.875",
    "--color-gray-90": "navy.900",
}
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


def themed_path(path: str) -> tuple[str | None, str]:
    parts = path.split(".")
    themes = [part for part in parts if part in ("light", "dark")]
    if not themes:
        return None, path
    if len(themes) != 1:
        raise TokenError(f"ambiguous theme in {path}")
    return themes[0], ".".join(part for part in parts if part not in ("light", "dark"))


def one_theme_tokens(data: dict) -> list[str]:
    tokens = flatten(data)
    missing = []
    for path in tokens:
        theme, _ = themed_path(path)
        if theme:
            other = "dark" if theme == "light" else "light"
            counterpart = ".".join(other if p == theme else p for p in path.split("."))
            if counterpart not in tokens:
                missing.append(counterpart)
    return sorted(missing)


def require_both_themes(data: dict) -> None:
    missing = one_theme_tokens(data)
    if missing:
        raise TokenError("token defined for one theme only; add: " + ", ".join(missing))
    tokens = flatten(data)
    names = {}
    for path, token in tokens.items():
        try:
            resolve(tokens, path)
        except ValueError as error:
            raise TokenError(str(error)) from error
        theme, semantic = themed_path(path)
        key = (theme or "shared", semantic)
        if key in names:
            raise TokenError(f"duplicate CSS token: {path} and {names[key]}")
        names[key] = path
        if theme:
            other = "dark" if theme == "light" else "light"
            counterpart = ".".join(other if p == theme else p for p in path.split("."))
            if token.get("$type") != tokens[counterpart].get("$type"):
                raise TokenError(f"theme type mismatch: {path} and {counterpart}")
        elif any(themed_path(p)[1] == semantic and themed_path(p)[0] for p in tokens):
            raise TokenError(f"shared token conflicts with themed token: {path}")

    if "translucency.frost.light.opacityFloor" in tokens:
        for theme in ("light", "dark"):
            floor = resolve(tokens, f"translucency.frost.{theme}.opacityFloor")
            opacity = resolve(tokens, f"translucency.frost.{theme}.opacity")
            alpha = rgba(resolve(tokens, f"color.{theme}.surface.frost"))[3]
            if not (0 <= floor <= opacity <= 1 and alpha == opacity):
                raise TokenError(f"frost opacity violates floor or differs from surface alpha: {theme}")
            if rgba(resolve(tokens, f"color.{theme}.surface.frostFallback"))[3] != 1:
                raise TokenError(f"frost fallback must be solid: {theme}")


def build(data: dict) -> str:
    require_both_themes(data)
    tokens = flatten(data)
    lines = [HEADER]
    shared = []
    themes: dict[str, list[str]] = {"light": [], "dark": []}
    for path, token in tokens.items():
        if path.startswith("color.primitive."):
            continue
        theme, semantic = themed_path(path)
        if theme:
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
    """Colours follow engine scheme; non-colours switch through engine media queries."""
    require_both_themes(data)
    tokens = flatten(data)
    shared, colors = [], {}
    themes: dict[str, list[str]] = {"light": [], "dark": []}
    for path, token in tokens.items():
        if path.startswith("color.primitive."):
            continue
        theme, semantic = themed_path(path)
        value = css_value(token, tokens, path)
        if theme and token.get("$type") == "color":
            colors.setdefault(semantic, {})[theme] = value
        elif theme:
            themes[theme].append(f"  {var_name(semantic)}: {value};")
        else:
            shared.append(f"  {var_name(path)}: {value};")
    lines = [f"  {var_name(name)}: light-dark({v['light']}, {v['dark']});" for name, v in colors.items()]
    css = HEADER + ":root {\n" + "\n".join(shared + lines + themes["light"]) + "\n}\n"
    if themes["dark"]:
        css += "@media (prefers-color-scheme: dark) {\n  :root {\n" + "\n".join(themes["dark"]) + "\n  }\n}\n"
    return css


def build_identity(data: dict) -> str:
    """Profile identity colours (same in both themes) for canvas drawing in the Shell."""
    tokens = flatten(data)
    prefix = "color.light.identity."
    require_both_themes(data)
    colors = {
        path[len(prefix) :]: resolve(tokens, path)
        for path in tokens
        if path.startswith(prefix) and "." not in path[len(prefix) :] and path[len(prefix) :] != "ring"
    }
    for name, value in colors.items():
        if resolve(tokens, f"color.dark.identity.{name}") != value:
            raise TokenError(f"drawing identity must match both themes: {name}")
    body = ",\n".join(f'  {name}: "{value}"' for name, value in colors.items())
    return (
        HEADER.replace("/*", "//", 1).replace(" */", "", 1)
        + "export const IDENTITY_COLORS = Object.freeze({\n"
        + body
        + ",\n});\n"
    )


# UX3G N3: the launcher's tools and its settings button share one row at the
# 224px width: an 8px gap (the engine's Nova gap is 12.5px, which pushed the
# gear to a second row). The footer lives in sidebar-main's shadow tree, which
# only an agent sheet reaches; geometry only, in every theme.
SIDEBAR_FOOTER = (
    '@-moz-document url("chrome://browser/content/browser.xhtml") {{\n'
    '  @media -moz-pref("nulavio.horizon.enabled") {{\n'
    '    .tools-and-extensions[orientation="horizontal"] {{\n'
    "      gap: {gap} !important;\n"
    "    }}\n"
    "  }}\n"
    "}}\n"
)


def build_sidebar_focus(data: dict) -> str:
    """Only native sidebar documents: restore focus contrast without styling web pages."""
    require_both_themes(data)
    tokens = flatten(data)
    light = resolve(tokens, "color.light.focus")
    dark = resolve(tokens, "color.dark.focus")
    return (
        HEADER
        + '@-moz-document url-prefix("chrome://browser/content/sidebar/"),\n'
        + '  url("chrome://browser/content/places/bookmarksSidebar.xhtml"),\n'
        + '  url("chrome://browser/content/places/historySidebar.xhtml"),\n'
        + '  url("chrome://browser/content/webext-panels.xhtml") {\n'
        + '  @media -moz-pref("nulavio.horizon.enabled") {\n'
        + '    @media -moz-pref("extensions.activeThemeID", "default-theme@mozilla.org") or\n'
        + '      -moz-pref("extensions.activeThemeID", "firefox-compact-light@mozilla.org") or\n'
        + '      -moz-pref("extensions.activeThemeID", "firefox-compact-dark@mozilla.org") {\n'
        + "    @media not ((forced-colors) or (prefers-contrast)) {\n"
        + f"      :root:not([lwtheme]) {{ --focus-outline-color: light-dark({light}, {dark}) !important; }}\n"
        + "    }\n    }\n  }\n}\n"
        + SIDEBAR_FOOTER.format(gap=resolve(tokens, "space.3"))
    )


def _mix(a: str, b: str, weight: float) -> str:
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * weight + y * (1 - weight)):02X}" for x, y in zip(ca, cb, strict=True))


# UX3G N2: Mozilla's own experiments and products are not part of Nulavio's
# Settings. The panes still open by URL; only their navigation entries are hidden
# (the browser.preferences.experimental.hidden pref alone did not hide Labs).
# Independent of the theme: this is naming, not colour.
BRAND_RULES = (
    '@-moz-document url-prefix("about:preferences"), url-prefix("about:settings") {\n'
    "  #category-experimental,\n"
    "  #category-more-from-mozilla {\n"
    "    display: none !important;\n"
    "  }\n"
    "}\n"
)


def build_in_content(data: dict) -> str:
    """Internal about: pages: the engine's accent, focus, link and canvas in Nulavio's colours.

    An agent sheet scoped by exact about: URLs: web pages never see --nv-* or any of these
    values (no fingerprinting surface). It steps aside for forced colours, a contrast
    preference, an installed theme and nulavio.horizon.enabled=false, like sidebar-focus.css.
    """
    require_both_themes(data)
    tokens = flatten(data)

    def prim(name: str) -> str:
        return resolve(tokens, f"color.primitive.{name}")

    def pair(path: str) -> str:
        return f"light-dark({resolve(tokens, f'color.light.{path}')}, {resolve(tokens, f'color.dark.{path}')})"

    lines = []
    for var, spec in NOVA_TO_NULAVIO.items():
        value = prim(spec) if isinstance(spec, str) else _mix(prim(spec[0]), prim(spec[1]), spec[2])
        lines.append(f"{var}: {value}")
    accent = pair("accent.default")
    lines += [
        f"--color-accent-primary: {accent}",
        f"--color-accent-primary-hover: light-dark({_mix(prim('mint.700'), prim('mint.900'), 0.6)}, {prim('mint.200')})",
        f"--color-accent-primary-active: light-dark({_mix(prim('mint.700'), prim('mint.900'), 0.3)}, {prim('mint.100')})",
        f"--focus-outline-color: {pair('focus')}",
        f"--link-color: {accent}",
        f"--link-color-hover: {accent}",
        f"--link-color-active: {accent}",
        f"--background-color-canvas: {pair('bg.canvas')}",
        f"--background-color-box: {pair('bg.surface')}",
        # UX3G N2: about:profiles and the other info pages (tables, the "Restart" box).
        f"--table-background-color: {pair('bg.surface')}",
        f"--border-color: {pair('border.subtle')}",
        f"--border-color-card: {pair('border.subtle')}",
        # UX3G polish: the active Settings entry is the accent in light, and in dark
        # a tint with accent text (7.8:1) instead of the brightest block on screen.
        f"--page-nav-button-background-color-selected: light-dark({resolve(tokens, 'color.light.accent.default')}, "
        f"{resolve(tokens, 'color.dark.accent.tint')})",
        f"--page-nav-button-text-color-selected: light-dark({resolve(tokens, 'color.light.accent.on')}, "
        f"{resolve(tokens, 'color.dark.accent.default')})",
    ]
    body = "".join(f"        {line} !important;\n" for line in lines)
    urls = ",\n  ".join(f'url-prefix("{page}")' for page in IN_CONTENT_PAGES)
    return (
        HEADER
        + f"@-moz-document {urls} {{\n"
        + '  @media -moz-pref("nulavio.horizon.enabled") {\n'
        + '    @media -moz-pref("extensions.activeThemeID", "default-theme@mozilla.org") or\n'
        + '      -moz-pref("extensions.activeThemeID", "firefox-compact-light@mozilla.org") or\n'
        + '      -moz-pref("extensions.activeThemeID", "firefox-compact-dark@mozilla.org") {\n'
        + "    @media not ((forced-colors) or (prefers-contrast)) {\n"
        + "      :root:not([lwtheme]) {\n"
        + body
        + "      }\n    }\n    }\n  }\n}\n"
        + BRAND_RULES
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    try:
        outputs = (
            (OUTPUT, build(data)),
            (CHROME_OUTPUT, build_chrome(data)),
            (IDENTITY_OUTPUT, build_identity(data)),
            (SIDEBAR_OUTPUT, build_sidebar_focus(data)),
            (IN_CONTENT_OUTPUT, build_in_content(data)),
        )
    except ValueError as error:
        print(f"{TOKENS.relative_to(ROOT)}: {error}", file=sys.stderr)
        return 2
    status = 0
    for out, css in outputs:
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
