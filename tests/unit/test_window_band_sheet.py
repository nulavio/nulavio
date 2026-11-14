"""UX3H A-1: the band in the navigation row has a fixed width, so the row never slides."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEET = (ROOT / "browser" / "shell" / "shared" / "window-band.css").read_text(encoding="utf-8")
WINDOW = (ROOT / "browser" / "shell" / "modules" / "NulavioWindow.sys.mjs").read_text(encoding="utf-8")


def fused_block() -> str:
    code = re.sub(r"/\*.*?\*/", "", SHEET, flags=re.S)
    start = code.index('@media -moz-pref("sidebar.verticalTabs") and (min-width: 64rem)')
    return code[start:]


class FusedBandTest(unittest.TestCase):
    def test_first_column_is_the_launcher_width_not_the_content(self):
        block = fused_block()
        columns = re.findall(r"grid-template-columns:\s*([^;]+);", block)
        self.assertEqual(columns, ["var(--nv-size-sidebar-launcherExpanded, 224px) minmax(0, 1fr)"])
        self.assertNotIn("auto minmax", block)

    def test_page_name_hidden_only_in_the_fused_row(self):
        block = fused_block()
        self.assertRegex(block, r"#nulavio-band\[nv-neutral\]:not\(\[nv-named\]\) \.nv-band-header \{\s*display: none;")
        # Outside the fused row the header keeps its normal rules.
        self.assertNotRegex(SHEET[: SHEET.index("UX3G A1: with tabs")], r"\.nv-band-header \{[^}]*display: none")

    def test_protection_state_is_never_truncated(self):
        block = fused_block()
        rule = re.search(r"\.nv-band-protection \{([^}]*)\}", block).group(1)
        self.assertIn("flex: none", rule)
        self.assertNotIn("ellipsis", rule)

    def test_trust_surfaces_keep_their_name_on_screen(self):
        plain = re.search(r"PLAIN_SURFACES = Object\.freeze\(new Set\(\[([^\]]*)\]\)\)", WINDOW).group(1)
        self.assertEqual(sorted(re.findall(r'"(\w+)"', plain)), ["newtabTitle", "profilesButton", "settingsTitle"])
        self.assertIn('bar.toggleAttribute("nv-named", trust)', WINDOW)
        self.assertIn('bar.removeAttribute("nv-named")', WINDOW)


class PrivateWindowMenuTest(unittest.TestCase):
    """#138: the assistant's page-menu item is hidden in a private window by the window's own sheet."""

    BACKGROUND = (ROOT / "browser" / "shell" / "background.js").read_text(encoding="utf-8")
    MANIFEST = (ROOT / "browser" / "shell" / "manifest.json").read_text(encoding="utf-8")

    def test_the_rule_names_the_engines_id_for_the_item(self):
        ask = re.search(r'const ASK_MENU = "([^"]+)";', self.BACKGROUND).group(1)
        shell_id = re.search(r'"id":\s*"([^"]+)"', self.MANIFEST).group(1)
        widget = re.sub(r"[^a-z0-9_-]", "_", shell_id.lower())  # ExtensionCommon.makeWidgetId
        code = re.sub(r"/\*.*?\*/", "", SHEET, flags=re.S)
        rule = re.search(r":root\[privatebrowsingmode\] #contentAreaContextMenu #(\S+) \{\s*display: none;\s*\}", code)
        self.assertIsNotNone(rule, "no private-window rule for the item")
        self.assertEqual(rule.group(1), f"{widget}-menuitem-_{ask}")

    def test_the_background_never_changes_the_items_visibility(self):
        # menus.update() changes an item in every window, and only after the menu is shown.
        self.assertNotRegex(self.BACKGROUND, r"menus\.update\(ASK_MENU")
        self.assertRegex(self.BACKGROUND, r"info\.menuItemId === ASK_MENU && tab && !tab\.incognito")


if __name__ == "__main__":
    unittest.main()
