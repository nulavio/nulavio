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


def private_block(css: str) -> str:
    """The UX3G private-window block: from its media query to the matching close brace."""
    start = css.index('@media not ((forced-colors) or (prefers-contrast)) {\n    :root[privatebrowsingmode="temporary"]')
    depth = 0
    for i in range(start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[start : i + 1]
    raise AssertionError("unbalanced private block")


class HorizonThemeTest(unittest.TestCase):
    def test_values_come_from_tokens(self):
        code = without_comments(CSS)
        self.assertNotRegex(code, r"#[0-9a-fA-F]{3,8}\b", "literal colour: add a token to docs/brand/tokens.json")
        self.assertNotRegex(code, r"\brgba?\(|\bhsla?\(", "literal colour function")
        outside = code.replace(private_block(code), "")
        self.assertNotIn("!important", outside, "author !important breaks user themes and accessibility overrides")

    def test_private_window_override_is_scoped_to_the_engine_substitute(self):
        """UX3G N2: the only !important rules repaint the engine's own private theme (inline
        variables), never a theme the person installed, forced colours or a contrast preference."""
        block = private_block(without_comments(CSS))
        self.assertIn("@media not ((forced-colors) or (prefers-contrast))", block)
        selectors = re.findall(r"^\s*([^{}\n]+)\{", block, flags=re.M)
        self.assertEqual(selectors[1].strip(), ':root[privatebrowsingmode="temporary"][lwtheme][theme-in-app]')
        self.assertTrue(all(":root" not in s or "[theme-in-app]" in s for s in selectors), selectors)
        values = re.findall(r"!important", block)
        self.assertGreater(len(values), 10)
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")

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


class InContentPagesTest(unittest.TestCase):
    """UX3F A2: the engine's internal pages in Nulavio's colours, never reaching web pages."""

    SHEET = (ROOT / "browser" / "shell" / "shared" / "in-content.css").read_text(encoding="utf-8")

    def test_scoped_to_exact_internal_pages(self):
        code = without_comments(self.SHEET)
        head = code[: code.index("{")]
        self.assertTrue(head.strip().startswith("@-moz-document"), head)
        targets = re.findall(r'url-prefix\("([^"]+)"\)', head)
        self.assertTrue(targets)
        self.assertTrue(all(t.startswith("about:") and t[6:].isalpha() for t in targets), targets)
        self.assertNotRegex(head, r"url\(|domain\(|regexp\(", "only about: prefixes")
        self.assertEqual(code.count("@-moz-document"), 1)

    def test_no_nulavio_variables_and_steps_aside(self):
        code = without_comments(self.SHEET)
        self.assertNotIn("--nv-", code, "Nulavio token names would be visible to the page")
        self.assertIn('@media -moz-pref("nulavio.horizon.enabled")', code)
        self.assertIn("@media not ((forced-colors) or (prefers-contrast))", code)
        self.assertIn(":root:not([lwtheme])", code)
        self.assertIn('"default-theme@mozilla.org"', code)

    def test_registered_like_the_sidebar_focus_sheet(self):
        window = (ROOT / "browser" / "shell" / "modules" / "NulavioWindow.sys.mjs").read_text(encoding="utf-8")
        self.assertIn("shared/in-content.css", window)
        self.assertEqual(window.count("for (const uri of [sidebarFocus, inContent])"), 2)

    def test_kit_artwork_is_replaced_by_nulavio_artwork(self):
        jar = (ROOT / "browser" / "branding" / "nulavio" / "content" / "jar.mn").read_text(encoding="utf-8")
        art = ROOT / "browser" / "branding" / "nulavio" / "content" / "illustration-promo.svg"
        self.assertTrue(art.is_file())
        for kit in ("kit-happy", "kit-concerned"):
            self.assertIn(
                f"% override chrome://global/skin/illustrations/{kit}.svg chrome://branding/content/illustration-promo.svg",
                jar,
            )
