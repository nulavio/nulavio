"""#175: the brand where the build shows it. The About dialog writes the name with the symbol as its initial
("N" + "ulavio", the lockup of docs/brand/guidelines.md), and the Settings privacy status draws its "on guard"
shield in the neutral secure colours, never in mint (mint never means "safe").

Screenshots of both go to NULAVIO_TEST_ARTIFACTS/brand/ as evidence; the assertions read what the engine
resolves (its chrome overrides and the page's own elements), so a build without the new branding fails."""

from __future__ import annotations

import json
import re
import sys
import unittest

import harness

sys.path.insert(0, str(harness.ROOT / "scripts" / "brand"))

import build_logo
from contrast import flatten, resolve

TOKENS = flatten(json.loads((harness.ROOT / "docs" / "brand" / "tokens.json").read_text(encoding="utf-8")))
MINT_SCALE = {resolve(TOKENS, f"color.primitive.mint.{step}").upper() for step in ("100", "200", "400", "700", "900")}
SECURE = {
    resolve(TOKENS, f"color.{theme}.status.{name}").upper() for theme in ("light", "dark") for name in ("secure", "secureTint")
}
WARNING = {resolve(TOKENS, f"color.{theme}.status.warning").upper() for theme in ("light", "dark")}
LOWERCASE_N = build_logo.wordmark_paths()[0].split(" M41.0 ")[0]  # the wordmark's own first letter

FETCH = """
const [url, done] = arguments;
fetch(url).then(r => r.text()).then(done, e => done("ERROR " + e));
"""
CARD = """
const d = gBrowser.selectedBrowser.contentDocument;
const card = d?.querySelector("security-privacy-card");
const img = card?.shadowRoot?.querySelector("img.status-image");
if (!img || !img.complete) return null;
card.scrollIntoView({ block: "center" });
return { src: img.getAttribute("src"), width: img.naturalWidth, shown: img.getBoundingClientRect().width > 0 };
"""


def colours(text: str) -> set[str]:
    return {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", text)}


@unittest.skipUnless(harness.nulavio_engine(), "the branding is part of the Nulavio build")
class BrandSurfacesTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="BrandSurfaces")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()
        self.out = harness.artifacts_dir() / "brand"
        self.out.mkdir(parents=True, exist_ok=True)

    def fetch(self, url: str) -> str:
        self.m.set_context("chrome")
        try:
            text = self.m.execute_async(FETCH, [url])
        finally:
            self.m.set_context("content")
        self.assertFalse(text.startswith("ERROR"), (url, text))
        return text

    def test_01_status_illustrations_are_neutral_and_warning(self):
        # The engine's own addresses, as the card asks for them: the chrome overrides of jar.mn answer.
        ok = self.fetch("chrome://global/skin/illustrations/shield-check.svg")
        self.assertEqual(colours(ok) & MINT_SCALE, set(), "the secure shield must not be drawn in mint")
        self.assertTrue(colours(ok) >= SECURE, colours(ok))
        alert = self.fetch("chrome://global/skin/illustrations/shield-alert.svg")
        self.assertTrue(colours(alert) >= WARNING, colours(alert))

    def test_02_settings_privacy_status_shows_a_nulavio_shield(self):
        self.m.chrome('gBrowser.selectedTab = gBrowser.addTrustedTab("about:preferences#privacy");')
        card = harness.wait_until(lambda: self.m.chrome(CARD), 30)
        self.assertTrue(card, "the privacy status card did not render its illustration")
        self.assertIn(
            card["src"],
            ("chrome://global/skin/illustrations/shield-check.svg", "chrome://global/skin/illustrations/shield-alert.svg"),
        )
        self.assertEqual(card["width"], 100, card)  # Nulavio's 100 x 106 artwork, not the engine's
        self.assertTrue(card["shown"], card)
        shown = colours(self.fetch(card["src"]))
        self.assertEqual(shown & MINT_SCALE, set(), (card, shown))
        (self.out / "settings-privacy-status.png").write_bytes(self.window_png())

    def test_03_about_dialog_writes_the_name_with_the_symbol_as_initial(self):
        for url in ("chrome://branding/content/about-wordmark.svg", "chrome://branding/content/firefox-wordmark.svg"):
            with self.subTest(url=url):
                name = self.fetch(url)
                self.assertIn(f'd="{build_logo.initial_route()}"', name)
                self.assertNotIn(LOWERCASE_N, name, "the lowercase n would show the initial twice")
        self.m.chrome("window.openAboutDialog();")
        state = harness.wait_until(
            lambda: self.m.chrome(
                'const w = Services.wm.getMostRecentWindow("Browser:About");'
                'if (!w || w.document.readyState !== "complete") return null;'
                'const box = w.document.getElementById("rightBox");'
                "return box && { image: w.getComputedStyle(box).backgroundImage };"
            ),
            20,
        )
        self.assertTrue(state, "the About dialog did not open")
        self.assertIn("about-wordmark.svg", state["image"])
        self.capture_about()
        self.m.chrome('Services.wm.getMostRecentWindow("Browser:About")?.close();')

    def window_png(self) -> bytes:
        """The whole browser window (chrome context), so the selected tab is what is captured."""
        self.m.set_context("chrome")
        try:
            return self.m.screenshot_png()
        finally:
            self.m.set_context("content")

    def capture_about(self):
        """Evidence only: the About window's pixels. In chrome context the window handles are the
        top-level windows; the About dialog is the one whose windowtype is Browser:About."""
        self.m.set_context("chrome")
        try:
            before = self.m.send("WebDriver:GetWindowHandle")["value"]
            for handle in self.m.window_handles():
                self.m.switch_to(handle)
                if self.m.execute("return document.documentElement.getAttribute('windowtype');") == "Browser:About":
                    (self.out / "about-dialog.png").write_bytes(self.m.screenshot_png())
                    break
            self.m.switch_to(before)
        finally:
            self.m.set_context("content")


if __name__ == "__main__":
    unittest.main()
