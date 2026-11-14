"""Experience rules of 2026-11 (design-system.md, "Experience 2026-11"), read from the sources: one main action
per group, the band never hidden by a mode, no sound outside the one sound module, and the same words in both languages."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from test_motion_sheet import declarations

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
sys.path.insert(0, str(ROOT / "scripts" / "build"))

import make_distribution  # noqa: E402

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

    def test_settings_links_go_to_the_one_page(self):
        # ADR 0008: "the settings" is about:preferences. A link of a Shell page to the old page as a whole, or to a
        # section the settings page draws itself, goes through the bridge (data-settings names the pane or section).
        gone = "layout|appearance|shortcuts|search|profiles|routing|passwords|exceptions|dns"
        moved = re.compile(rf"settings/settings\.html(#({gone})\b[\w-]*)?[\"']")
        for page in sorted(SHELL.rglob("*.html")):
            for line in page.read_text(encoding="utf-8").splitlines():
                if "<a " in line and moved.search(line):
                    with self.subTest(page=str(page.relative_to(SHELL)), line=line.strip()[:80]):
                        self.assertIn("data-settings=", line)
        sections = set(
            re.findall(r'<section class="section" id="([a-z]+)"', (SHELL / "settings/settings.html").read_text(encoding="utf-8"))
        )
        host = (SHELL / "modules/NulavioSettings.sys.mjs").read_text(encoding="utf-8")
        mapped = set(re.findall(r"^  ([a-z]+): \"", host.split("export const SECTIONS")[1].split("});")[0], flags=re.M))
        self.assertLessEqual(sections, mapped, "every section of the old page names the pane it belongs to")
        # A section the settings page draws itself is gone from the old page; its address still opens the right pane.
        nav = (SHELL / "settings/nav.js").read_text(encoding="utf-8")
        redirected = set(re.findall(r'"([a-z]+)"', nav.split("export const MOVED = [")[1].split("]")[0]))
        self.assertEqual(redirected, mapped - sections)
        self.assertFalse(redirected & sections, "a section is either in the old page or sent to the settings page")

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

    def test_the_settings_page_says_the_shells_own_words_and_builds_no_markup(self):
        """ADR 0011: the profile actions in the engine's settings page reuse the Shell's messages (one set of
        words for an action, wherever it is offered) and are built from the engine's widgets, never from text."""
        panes = (SHELL / "settings/native/panes.mjs").read_text(encoding="utf-8")
        keys = set(re.findall(r'\bmsg\("(\w+)"', panes))
        self.assertGreater(len(keys), 20)
        # Keys built from a value: every value the code can give has its message.
        names = (SHELL / "lib/names.js").read_text(encoding="utf-8")
        profiles = (SHELL / "modules/NulavioProfiles.sys.mjs").read_text(encoding="utf-8")
        keys |= set(re.findall(r'"(template\w+|profiles\w+)"', names))
        colors = re.search(r"export const COLORS = Object\.freeze\(\[([^\]]+)\]", profiles).group(1)
        avatars = re.search(r"export const AVATARS = Object\.freeze\(\[([^\]]+)\]", profiles).group(1)
        keys |= {f"color_{name}" for name in re.findall(r'"([a-z-]+)"', colors)}
        keys |= {f"avatar_{name.replace('-', '_')}" for name in re.findall(r'"([a-z-]+)"', avatars)}
        keys |= {f"err_{code.replace('-', '_')}" for code in re.findall(r'fail\("([a-z-]+)"', profiles)}
        for locale in ("en", "pt_BR"):
            have = set(json.loads((SHELL / "_locales" / locale / "messages.json").read_text(encoding="utf-8")))
            self.assertEqual(keys - have, set(), f"{locale}: the settings page asks for words that do not exist")
        self.assertNotRegex(panes, r"innerHTML|outerHTML|insertAdjacentHTML|createContextualFragment|document\.write")
        # A destructive confirmation keeps "Cancelar" as the default button, as on the Shell's own pages.
        ask = panes[panes.index("const ask = async (title, body, confirm, danger)") :].split("    };", 1)[0]
        self.assertIn("BUTTON_POS_1 * prompt.BUTTON_TITLE_CANCEL", ask)
        self.assertIn("(danger ? prompt.BUTTON_POS_1_DEFAULT : prompt.BUTTON_POS_0_DEFAULT)", ask)
        self.assertIn("const confirmDanger = (title, body, confirm) => ask(title, body, confirm, true);", panes)
        # Deleting a profile, locking the one in use and removing a browser default are dangers, never plain steps.
        for words in ("profilesDeleteTitle", "vaultLockCurrentTitle", "exceptionRemoveBuiltInTitle"):
            self.assertRegex(panes, r"confirmDanger\(\s*msg\(\"" + words)

    def test_a_group_that_reaches_beyond_this_profile_says_so(self):
        """The settings page is the profile's own: a setting there is this profile's unless its group says otherwise.
        (The Shell's old page said how far each section reached with a label; what is left of it still does,
        test_settings_ui 03.) The groups whose settings are kept for the computer or for every profile say so in
        their own description, in both languages."""
        reach = {
            "nulavio-routing-group": {"pt-BR": "neste computador", "en-US": "on this computer"},
            "nulavio-integrations-group": {"pt-BR": "neste computador", "en-US": "on this computer"},
            "nulavio-assistant-group": {"pt-BR": "todos os perfis", "en-US": "every profile"},
        }
        for language in ("pt-BR", "en-US"):
            text = (SHELL / "l10n" / language / "nulavio" / "settings.ftl").read_text(encoding="utf-8")
            for group, words in reach.items():
                entry = re.search(rf"^{group} =\n((?:    .*\n)+)", text, re.M)
                self.assertIsNotNone(entry, f"{language}: {group} is gone")
                description = re.search(r"^    \.description = (.*)$", entry.group(1), re.M)
                self.assertIsNotNone(description, f"{language}: {group} has no description")
                self.assertIn(words[language], description.group(1), f"{language}: {group} does not say how far it reaches")

    def test_the_cookie_notice_lists_are_ublock_origins_own(self):
        """The Shell reads one thing of uBlock Origin's data: which lists are on. "A list that hides them is on"
        needs one of the registry's cookie-notice lists; "none is on" needs every list that is on to be one the
        registry names."""
        privacy = (SHELL / "modules/NulavioPrivacy.sys.mjs").read_text(encoding="utf-8")
        # Read with the storage's own reader and closed; nothing in the module writes to another extension's storage.
        self.assertEqual(privacy.count("ExtensionStorageIDB.open("), 1)
        self.assertNotRegex(privacy, r"store\.(set|remove|clear)\(")
        # The names come from the registry of the pinned version, written into the Shell: none is typed in the module.
        self.assertIn('"resource://builtin-addons/nulavio-shell/shared/filter-lists.json"', privacy)
        self.assertNotRegex(privacy, r"fanboy-cookiemonster|adguard-cookies|ublock-cookies")
        names = make_distribution.filter_lists()
        self.assertEqual(
            make_distribution.FILTER_LISTS.read_text(encoding="utf-8"),
            make_distribution.filter_lists_text(),
            "browser/shell/shared/filter-lists.json is not current: run scripts/build/make_distribution.py --filter-lists",
        )
        registry = json.loads((ROOT / "browser" / "distribution" / "ublock-origin" / "assets.json").read_text(encoding="utf-8"))
        lists = {key for key, entry in registry.items() if entry.get("content") == "filters"}
        self.assertEqual(set(names["cookies"]), {key for key in lists if registry[key].get("group2") == "cookies"})
        self.assertEqual(len(names["cookies"]), 4)
        self.assertEqual(set(names["cookies"]) | set(names["others"]), lists)
        self.assertEqual(set(names["cookies"]) & set(names["others"]), set())
        # The lists a new profile starts with are all known by name, or Settings would say nothing from the first day.
        content = json.loads((ROOT / "browser" / "distribution" / "content-filter.json").read_text(encoding="utf-8"))
        self.assertLessEqual(set(content["default_on"]), lists)
        self.assertNotIn("user-filters", lists, "uBlock Origin's entry for the person's own filters became a list")
        # A registry without the group stops the build: every selection would read as having no such list on.
        with tempfile.TemporaryDirectory() as tmp:
            bare = {key: {k: v for k, v in entry.items() if k != "group2"} for key, entry in registry.items()}
            (Path(tmp) / "assets.json").write_text(json.dumps(bare), encoding="utf-8")
            with mock.patch.object(make_distribution, "REGISTRY_DIR", Path(tmp)), self.assertRaises(SystemExit):
                make_distribution.filter_lists()


if __name__ == "__main__":
    unittest.main()
