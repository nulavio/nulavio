"""#527: the side panel opposite the tabs. The engine patch, the option, the default and both sheets name the same pref
and the same root attribute, so a rename in one place cannot leave the setting doing nothing. What the window draws is
tests/integration/test_panel_opposite.py, against a build."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "0013-sidebar-the-side-panel-can-open-opposite-the-tabs.patch"
PATCH = (ROOT / "browser" / "patches" / NAME).read_text(encoding="utf-8")
PREF = "nulavio.sidebar.panelOpposite"
ATTRIBUTE = "nulavio-panel-opposite"


def added(patch: str) -> str:
    return "\n".join(line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))


class PanelOppositeTest(unittest.TestCase):
    def test_the_patch_is_in_the_series_and_changes_one_file(self):
        lines = (ROOT / "browser" / "patches" / "series").read_text(encoding="utf-8").splitlines()
        series = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        self.assertIn(NAME, series)
        files = set(re.findall(r"(?m)^\+\+\+ b/(\S+)", PATCH))
        self.assertEqual(files, {"browser/components/sidebar/browser-sidebar.js"})
        # Only additions: the engine's own lines stay as they are.
        self.assertNotRegex(PATCH, r"(?m)^-(?!--)")

    def test_the_engine_reads_the_pref_and_marks_the_root(self):
        code = added(PATCH)
        self.assertIn(f'"{PREF}",\n  false,', code)  # the lazy getter's default: off
        self.assertIn(f'"{ATTRIBUTE}"', code)
        self.assertIn("SidebarController.setPosition();", code)  # applied again when the setting changes

    def test_the_option_writes_that_pref_and_is_off_by_default(self):
        options = json.loads((ROOT / "browser" / "shell" / "shared" / "options.json").read_text(encoding="utf-8"))["options"]
        option = next(o for o in options if o["id"] == "panelOpposite")
        self.assertEqual(
            (option["prefs"], option["default"], option["prefValues"], option["writer"]),
            ([PREF], False, [None, True], "NulavioPersonalise"),
        )
        branding = (ROOT / "browser" / "branding" / "nulavio" / "pref" / "firefox-branding.js").read_text(encoding="utf-8")
        self.assertIn(f'pref("{PREF}", false);', branding)

    def test_both_sheets_read_the_attribute(self):
        for sheet in ("browser/branding/nulavio/content/theme/horizon.css", "browser/shell/shared/window-band.css"):
            with self.subTest(sheet=sheet):
                self.assertIn(f"&[{ATTRIBUTE}]", (ROOT / sheet).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
