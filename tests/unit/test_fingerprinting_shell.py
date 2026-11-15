"""What the Shell adds to the engine's fingerprinting protection (#79, ADR 0016): where it starts and what it says."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
MODULE = (SHELL / "modules" / "NulavioFingerprinting.sys.mjs").read_text(encoding="utf-8")
CHILD = (SHELL / "modules" / "NulavioFingerprintingChild.sys.mjs").read_text(encoding="utf-8")


class ScreenTest(unittest.TestCase):
    def test_the_size_is_the_one_the_documents_name(self):
        width, height = re.search(r"export const SCREEN = Object\.freeze\(\{ width: (\d+), height: (\d+) \}\);", CHILD).groups()
        size = f"{width}×{height}"
        self.assertEqual(size, "1920×1080")
        for page in (
            "docs/adr/0016-one-screen-size-and-processor-count-for-pages.md",
            "docs/research/fingerprinting.md",
            "docs/security/hardening.md",
        ):
            with self.subTest(page=page):
                self.assertIn(size, (ROOT / page).read_text(encoding="utf-8"))

    def test_it_starts_with_the_shell_and_each_page_decides_as_its_window_is_created(self):
        parent = (SHELL / "experiments" / "privacy" / "parent.js").read_text(encoding="utf-8")
        start = parent[parent.index("  onStartup() {") : parent.index("  onShutdown(")]
        self.assertIn("this.fingerprinting().watch();", start)
        # A new tab has the constant before any page; then the page's own process decides, at the two moments a
        # page comes to be shown: its window created, or the page taken back from the engine's cache.
        self.assertIn('const TOPICS = ["browsing-context-attached"];', MODULE)
        self.assertIn("events: { DOMWindowCreated: {}, pageshow: {} },", MODULE)
        self.assertIn("allFrames: false,", MODULE)
        self.assertIn('if (event.type === "pageshow" && !event.persisted) {', CHILD)

    def test_it_follows_the_engines_switch_and_the_engines_own_word_for_an_exempted_site(self):
        self.assertIn("exempted = Boolean(this.document.cookieJarSettings?.isOnContentBlockingAllowList);", CHILD)
        self.assertIn("setScreen(context, protectionOn(context.usePrivateBrowsing) && !exempted);", CHILD)
        # Nothing is taken from a page still shown: no hook on a request that is only on its way.
        for text in (MODULE, CHILD):
            self.assertNotIn("http-on-modify-request", text)
            self.assertNotIn("Services.prefs.set", text)  # it reads the engine's switches and writes none
            self.assertNotIn("sendAsyncMessage", text)  # the two halves exchange nothing


if __name__ == "__main__":
    unittest.main()
