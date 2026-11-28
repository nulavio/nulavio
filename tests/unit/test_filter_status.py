"""The new tab's content-filter line on a new profile's first start (#898, R91).

uBlock Origin is active seconds before it filters: on the first start the requests it holds while it loads its lists
are let through unfiltered when it releases them (docs/security/residual-risks.md, R91). The Shell tells the two apart
by uBlock Origin's own toolbar button, whose icon is its loading one until its request listener takes over
(NulavioPrivacy.filterReady). Here that reading runs under Node on the engine's data shapes, and the new tab's words are
read from the sources; tests/integration/test_first_start_filter.py checks the line on a real first start.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "browser" / "shell"
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from node_tool import requires_node  # noqa: E402

READY = """
globalThis.ChromeUtils = { defineESModuleGetters() {}, generateQI() { return () => {}; } };
globalThis.Ci = { nsIDNSService: {} }; // the module reads the DNS modes when it loads
const { filterReady } = await import(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(Object.fromEntries(Object.entries(cases).map(([name, globals]) => {
  // The engine's global data inherits the manifest's icon from its defaults: only an icon the extension set is its own.
  const data = Object.create({ icon: { 16: "moz-extension://u/img/icon_16.png" } });
  return [name, filterReady(globals === null ? null : Object.assign(data, globals))];
}))));
"""

BASE = "moz-extension://5d1c2a9e/img/"


def icon(flavour: str) -> dict:
    return {size: f"{BASE}icon_{size}{flavour}.png" for size in ("16", "32", "64")}


@requires_node
class FilterReadyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = {
            "no_button": None,
            "manifest_icon_only": {},  # its background has not set an icon yet
            "loading": {"icon": icon("-loading"), "badgeText": ""},
            "loading_with_warning": {"icon": icon("-loading"), "badgeText": "!"},  # requests went out unfiltered
            "filtering": {"icon": icon(""), "badgeText": ""},
            "theme_icons_loading": {
                "icon": {"16": {"light": f"{BASE}icon_16-loading.png", "dark": f"{BASE}icon_16-loading.png"}}
            },
            "theme_icons": {"icon": {"16": {"light": f"{BASE}icon_16.png", "dark": f"{BASE}icon_16.png"}}},
        }
        module = (SHELL / "modules" / "NulavioPrivacy.sys.mjs").as_uri()
        done = subprocess.run(["node", "--input-type=module", "-e", READY, module, json.dumps(cases)],
                              capture_output=True, text=True, timeout=60, check=True)  # fmt: skip
        cls.ready = json.loads(done.stdout)

    def test_it_filters_only_once_its_own_icon_is_back(self):
        self.assertEqual(self.ready["filtering"], True)
        self.assertEqual(self.ready["theme_icons"], True)

    def test_while_it_loads_its_lists_it_does_not_filter(self):
        for name in ("loading", "loading_with_warning", "theme_icons_loading"):
            self.assertIs(self.ready[name], False, name)

    def test_before_its_background_sets_an_icon_it_does_not_filter(self):
        self.assertIs(self.ready["manifest_icon_only"], False)
        self.assertIs(self.ready["no_button"], False)


class FilterLineTest(unittest.TestCase):
    def test_the_new_tab_says_loading_and_not_active_until_it_filters(self):
        newtab = (SHELL / "newtab" / "newtab.js").read_text(encoding="utf-8")
        line = re.search(r"function showFilter\(ublock, ready\) \{\n(.*?)\n\}\n", newtab, re.S).group(1)
        branches = [b.strip() for b in line.split("\n") if b.strip().startswith(("if", "else"))][:4]
        self.assertEqual(
            branches,
            [
                'if (!ublock) show("filter", t("filterMissing"), "warn");',
                'else if (!ublock.enabled) show("filter", t("filterDisabled"), "warn");',
                'else if (ready === false) show("filter", t("filterLoading", [ublock.version]), "warn");',
                'else show("filter", t("filterActive", [ublock.version]), "ok");',
            ],
        )
        self.assertIn("setTimeout(", line)  # read again until it filters: a tab left open does not keep "loading"
        self.assertIn("filtering()", newtab.split("async function refresh()")[1].split("showFilter(")[0])

    def test_the_shell_api_gives_the_new_tab_the_module_s_reading(self):
        schema = json.loads((SHELL / "experiments" / "privacy" / "schema.json").read_text(encoding="utf-8"))[0]
        self.assertIn("filter", [f["name"] for f in schema["functions"]])
        parent = (SHELL / "experiments" / "privacy" / "parent.js").read_text(encoding="utf-8")
        self.assertIn("filter: call(() => NulavioPrivacy.filter()),", parent)
        privacy = (SHELL / "modules" / "NulavioPrivacy.sys.mjs").read_text(encoding="utf-8")
        self.assertIn("filterReady(action.getContextData(null))", privacy)

    def test_both_languages_say_it_loads_its_lists(self):
        words = {"en": "is loading its lists", "pt_BR": "carregando as listas"}
        for language, said in words.items():
            messages = json.loads((SHELL / "_locales" / language / "messages.json").read_text(encoding="utf-8"))
            self.assertIn(said, messages["filterLoading"]["message"], language)
            self.assertIn("$VERSION$", messages["filterLoading"]["message"], language)
            self.assertNotIn("ativo", messages["filterLoading"]["message"].lower(), language)


if __name__ == "__main__":
    unittest.main()
