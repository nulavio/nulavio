"""Nulavio Horizon window theme: the rules that keep it safe to carry across Firefox releases."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "browser" / "branding" / "nulavio" / "content" / "theme"
CSS = (THEME / "horizon.css").read_text(encoding="utf-8")
SECURITY_IDS = (
    "trust-icon",
    "tracking-protection",
    "identity-",
    "permission",
    "remote-control",
    "notification-popup",
    "urlbar-label",
)


def without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


class HorizonThemeTest(unittest.TestCase):
    def test_values_come_from_tokens(self):
        code = without_comments(CSS)
        self.assertNotRegex(code, r"#[0-9a-fA-F]{3,8}\b", "literal colour: add a token to docs/brand/tokens.json")
        self.assertNotRegex(code, r"\brgba?\(|\bhsla?\(", "literal colour function")
        self.assertNotIn("!important", code, "author !important breaks user themes and accessibility overrides")

    def test_everything_is_behind_the_pref(self):
        code = without_comments(CSS)
        gate = '@media -moz-pref("nulavio.horizon.enabled") {'
        self.assertIn(gate, code)
        body = code[code.index(gate) :]
        before = code[: code.index(gate)]
        self.assertNotRegex(before, r"\{", "rules outside the nulavio.horizon.enabled gate")
        self.assertIn("@keyframes", body.split(gate, 1)[1] + body)
        prefs = (ROOT / "browser" / "branding" / "nulavio" / "pref" / "firefox-branding.js").read_text()
        self.assertIn('pref("nulavio.horizon.enabled", true);', prefs)

    def test_colours_yield_to_accessibility_and_user_themes(self):
        code = without_comments(CSS)
        guard = "@media not ((forced-colors) or (prefers-contrast)) {"
        self.assertIn(guard, code)
        colours = code[code.index(guard) :]
        self.assertIn(":root:not([lwtheme])", colours[:200])
        # Colour custom properties are only assigned inside that guard.
        outside = code[: code.index(guard)]
        self.assertNotRegex(outside, r"--[a-z-]*colou?r[a-z-]*\s*:", "colour token assigned outside the guard")

    def test_tokens_use_mozillas_last_brand_layer(self):
        # Layers declared after it (prefers-contrast, forced-colors) must keep winning.
        self.assertIn("@layer tokens-foundation-brand-nova {", CSS)
        self.assertNotRegex(without_comments(CSS), r"@layer\s+tokens-(prefers-contrast|forced-colors)")

    def test_security_ui_is_not_targeted(self):
        code = without_comments(CSS)
        for ident in SECURITY_IDS:
            with self.subTest(ident=ident):
                self.assertNotIn(f"#{ident}", code)
        self.assertNotRegex(code, r"visibility\s*:\s*hidden")
        # UX3B hides only the three unavailable native radios and adjacent labels.
        # No broad hiding rule can accidentally target browser/security controls.
        hidden = re.findall(r"([^{}]+)\{[^{}]*display\s*:\s*none[^{}]*\}", code)
        self.assertEqual(len(hidden), 1)
        swatches = ", ".join(f"#tab-group-editor-swatch-{color}" for color in ("orange", "purple", "red"))
        selector = f":root:not([lwtheme]) #tab-group-editor :is({swatches}):not(:checked)"
        self.assertEqual(re.sub(r"\s+", " ", hidden[0]).strip(), f"{selector}, {selector} + label")

    def test_rtl_safe_geometry(self):
        code = without_comments(CSS)
        self.assertNotRegex(code, r"(?<![-\w])(left|right|margin-left|margin-right|padding-left|padding-right)\s*:")

    def test_packaging_and_loading(self):
        jar = (ROOT / "browser" / "branding" / "nulavio" / "content" / "jar.mn").read_text()
        for name in ("tokens.css", "horizon.css"):
            self.assertIn(f"content/branding/theme/{name}", jar)
        patch = (ROOT / "browser" / "patches" / "0003-shell-load-the-nulavio-horizon-theme.patch").read_text()
        self.assertIn('+  <link rel="stylesheet" href="chrome://branding/content/theme/horizon.css" />', patch)
        self.assertIn('@import url("chrome://branding/content/theme/tokens.css");', CSS)

    def test_generated_tokens_define_everything_the_theme_uses(self):
        tokens = (THEME / "tokens.css").read_text(encoding="utf-8")
        defined = set(re.findall(r"(--nv-[\w-]+)\s*:", tokens))
        used = set(re.findall(r"var\((--nv-[\w-]+)", CSS))
        self.assertEqual(used - defined, set())


if __name__ == "__main__":
    unittest.main()
