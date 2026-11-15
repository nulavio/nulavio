"""What the Shell adds to the engine's fingerprinting protection (#79, ADR 0016): where it starts and what it says."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
MODULE = (SHELL / "modules" / "NulavioFingerprinting.sys.mjs").read_text(encoding="utf-8")


class ScreenTest(unittest.TestCase):
    def test_the_size_is_the_one_the_documents_name(self):
        width, height = re.search(r"export const SCREEN = Object\.freeze\(\{ width: (\d+), height: (\d+) \}\);", MODULE).groups()
        size = f"{width}×{height}"
        self.assertEqual(size, "1920×1080")
        for page in (
            "docs/adr/0016-one-screen-size-and-processor-count-for-pages.md",
            "docs/research/fingerprinting.md",
            "docs/security/hardening.md",
        ):
            with self.subTest(page=page):
                self.assertIn(size, (ROOT / page).read_text(encoding="utf-8"))

    def test_it_starts_with_the_shell_and_follows_the_engines_switch_and_the_shield(self):
        parent = (SHELL / "experiments" / "privacy" / "parent.js").read_text(encoding="utf-8")
        start = parent[parent.index("  onStartup() {") : parent.index("  onShutdown(")]
        self.assertIn("this.fingerprinting().watch();", start)
        # On only while the engine's protection is on, and never for a site the person exempted.
        self.assertIn("if (protectionOn(top.usePrivateBrowsing) && !exempted(uri, top.usePrivateBrowsing)) {", MODULE)
        self.assertIn('const type = isPrivate ? "trackingprotection-pb" : "trackingprotection";', MODULE)
        # Before a page is asked for, when a tab gets a new context, and for pages that ask for nothing.
        for hook in ('"http-on-modify-request"', '"browsing-context-attached"', "onLocationChange("):
            self.assertIn(hook, MODULE)
        self.assertNotIn("Services.prefs.set", MODULE)  # it reads the engine's switches and writes none


if __name__ == "__main__":
    unittest.main()
