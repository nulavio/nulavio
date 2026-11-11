"""Experience rules of 2026-11 (design-system.md, "Experience 2026-11"), read from the sources: one main action
per group, the band never hidden by a mode, no sound outside the one sound module, and the same words in both languages."""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from test_motion_sheet import declarations

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
BAND_SHEET = SHELL / "shared" / "window-band.css"
SOUND_MODULE = "NulavioSound.sys.mjs"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
# States in which the toolbar and the tabs may leave the window (ADR 0009, ADR 0010).
MODES = ("nulavio-immersive", "nulavio-stage")
HIDES = {
    "display": ("none",),
    "visibility": ("hidden", "collapse"),
    "opacity": ("0",),
    "block-size": ("0", "0px"),
    "height": ("0", "0px"),
}


class ActionGroups(HTMLParser):
    """Counts the primary buttons inside every `.actions` group of a page."""

    def __init__(self):
        super().__init__()
        self.open: list[list | None] = []
        self.groups: list[list] = []

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        group = [0, self.getpos()[0]] if "actions" in classes else None
        if group:
            self.groups.append(group)
        if "button--primary" in classes:
            for enclosing in [*self.open, group]:
                if enclosing:
                    enclosing[0] += 1
        if tag not in VOID:
            self.open.append(group)

    def handle_endtag(self, tag):
        if tag not in VOID and self.open:
            self.open.pop()


class ExperienceRulesTest(unittest.TestCase):
    def test_one_main_action_per_group(self):
        for page in sorted(SHELL.rglob("*.html")):
            if "dev" in page.relative_to(SHELL).parts:  # the component gallery shows every variant side by side
                continue
            parser = ActionGroups()
            parser.feed(page.read_text(encoding="utf-8"))
            for count, line in parser.groups:
                with self.subTest(page=str(page.relative_to(SHELL)), line=line):
                    self.assertLessEqual(count, 1, "two primary buttons compete in one group of actions")

    def test_no_mode_hides_the_band(self):
        for stack, prop, value in declarations(BAND_SHEET):
            if not any(mode in prelude for prelude in stack for mode in MODES):
                continue
            # The band as the subject of the rule; `toolbar:not(#nulavio-band)` is every toolbar except it.
            subject = re.sub(r":not\([^()]*\)", "", stack[-1])
            if "#nulavio-band" not in subject:
                continue
            with self.subTest(rule=stack[-1][:80], prop=prop):
                self.assertNotIn(
                    value.replace("!important", "").strip(), HIDES.get(prop, ()), "a mode may hide the toolbar, never the band"
                )

    def test_no_sound_outside_the_sound_module(self):
        for script in [*SHELL.rglob("*.js"), *SHELL.rglob("*.mjs"), *SHELL.rglob("*.html")]:
            if script.name == SOUND_MODULE:
                continue
            with self.subTest(file=str(script.relative_to(SHELL))):
                self.assertNotRegex(
                    script.read_text(encoding="utf-8"),
                    r"new Audio\(|AudioContext|<audio\b|nsISound|playEventSound|mozilla\.org/sound",
                    f"sounds are played only by {SOUND_MODULE}, which follows the system's setting",
                )

    def test_fluent_words_exist_in_both_languages(self):
        ids = {}
        for locale in ("en-US", "pt-BR"):
            base = SHELL / "l10n" / locale
            ids[locale] = {
                f"{file.relative_to(base)}:{match}"
                for file in base.rglob("*.ftl")
                for match in re.findall(r"^([a-z][\w-]*)\s*=", file.read_text(encoding="utf-8"), flags=re.M)
            }
        self.assertTrue(ids["en-US"], "no Fluent messages found")
        self.assertEqual(ids["en-US"] ^ ids["pt-BR"], set())


if __name__ == "__main__":
    unittest.main()
