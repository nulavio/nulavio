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

# The new tab's own functions for the line (show, showFilter, readFilter, summarise), cut from newtab.js and run on a
# small stand-in for its page: readings that end out of order, a person who closed the details, the first run's copy
# of the line, and what the polite status line says (OpenCodeReview on #939).
PAGE = r"""
const source = process.argv[1];
const cut = (from, to) => source.slice(source.indexOf(from), source.indexOf(to, source.indexOf(from)));
const code = [cut("function show(", "async function setting("), cut("let filterAgain", "// A tab opened before"),
  cut("let warned", '// "Você está em')].join("\n");
const el = (text = "", name = null) =>
  ({ textContent: text, dataset: {}, closest: () => null, previousElementSibling: name && { textContent: name } });
const rows = { gpc: el("…", "GPC"), filter: el("…", "Content filter"), tracking: el("…", "Tracking protection") };
const byId = { "filter-now": el(), "here-summary": el(), "here-details": { open: false } };
const copy = el();
const document = {
  getElementById: id => byId[id],
  querySelector: sel => rows[/data-status="(\w+)"/.exec(sel)[1]],
  querySelectorAll: sel => (sel === "#status [data-status]" ? Object.values(rows) : sel === '[data-copy="filter"]' ? [copy] : []),
};
// Each reading takes the next answer; a case decides when each answer comes, so in which order readings end.
const pending = [];
let current;
const answer = () => { let done; const promise = new Promise(r => (done = r)); pending.push(done); return promise; };
const extension = () => { current = answer(); return current.then(a => a.ublock); };
const filtering = () => current.then(a => a.ready);
const page = new Function("document", "t", "extension", "filtering", "setTimeout", "UBLOCK_ID",
  `${code}\nreturn { show, readFilter, summarise };`)(
  document, (key, args = []) => [key, ...args].join(" "), extension, filtering, () => 1, "uBlock0@raymondhill.net");
const ublock = { enabled: true, version: "1.77.4" };
const settle = () => new Promise(r => setTimeout(r, 0));
const state = () => ({ line: rows.filter.textContent, said: byId["filter-now"].textContent, copy: copy.textContent,
  open: byId["here-details"].open, summary: byId["here-summary"].textContent });
const out = {};

// First reading: loading. It is not said; the summary names the filter and opens the details.
let first = page.readFilter();
pending.shift()({ ublock, ready: false });
await first;
page.show("gpc", "off", "warn");
page.show("tracking", "on", "ok");
page.summarise();
out.first = state();

// The person closes the details. A slow reading (asked first, still loading) ends after a newer one that says active.
byId["here-details"].open = false;
const slow = page.readFilter();
const fast = page.readFilter();
const [answerSlow, answerFast] = pending.splice(0);
answerFast({ ublock, ready: true });
await fast;
out.fast = state();
answerSlow({ ublock, ready: false });
await slow;
await settle();
out.after_slow = state();

// A fact that comes to need attention opens the details again.
page.show("tracking", "off", "warn");
page.summarise();
out.new_warning = state();
console.log(JSON.stringify(out));
"""


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


@requires_node
class FilterLineBehaviourTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        newtab = (SHELL / "newtab" / "newtab.js").read_text(encoding="utf-8")
        done = subprocess.run(["node", "--input-type=module", "-e", PAGE, newtab],
                              capture_output=True, text=True, timeout=60, check=True)  # fmt: skip
        cls.out = json.loads(done.stdout)

    def test_the_first_reading_is_not_announced(self):
        first = self.out["first"]
        self.assertEqual(first["line"], "filterLoading 1.77.4")
        self.assertEqual(first["said"], "", "the first reading is not a change (SPA-23)")
        self.assertTrue(first["open"], "a fact that needs attention opens the details")

    def test_a_reading_that_ends_late_does_not_put_loading_back(self):
        self.assertEqual(self.out["fast"]["line"], "filterActive 1.77.4")
        self.assertEqual(self.out["after_slow"]["line"], "filterActive 1.77.4")

    def test_the_change_to_active_is_announced_and_copied(self):
        after = self.out["after_slow"]
        self.assertEqual(after["said"], "Content filter: filterActive 1.77.4")
        self.assertEqual(after["copy"], "filterActive 1.77.4", "the first run's 'Tudo pronto' says it too")
        self.assertEqual(after["summary"], "protectionsAttention GPC")

    def test_details_the_person_closed_stay_closed_until_something_new_needs_attention(self):
        self.assertFalse(self.out["after_slow"]["open"], "GPC was already named: the details stay closed")
        self.assertTrue(self.out["new_warning"]["open"], "tracking protection is new: the details open")


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
        self.assertIn("filtering()", newtab.split("async function readFilter()")[1].split("showFilter(")[0])
        self.assertIn("readFilter()", newtab.split("async function refresh()")[1].split("Promise.all(PROVIDERS")[0])

    def test_a_tab_open_before_the_install_reads_the_line_again(self):
        newtab = (SHELL / "newtab" / "newtab.js").read_text(encoding="utf-8")
        listen = newtab.split("// A tab opened before")[1].split("async function refresh()")[0]
        for event in ("onInstalled", "onEnabled", "onDisabled", "onUninstalled"):
            self.assertIn(f'"{event}"', listen)
        self.assertIn("info?.id === UBLOCK_ID", listen)
        self.assertIn("readFilter()", listen)

    def test_the_polite_status_line_is_outside_the_details(self):
        html = (SHELL / "newtab" / "newtab.html").read_text(encoding="utf-8")
        here = html.split('id="here"')[1].split("</section>")[0]
        status = re.search(r'<p class="visually-hidden" id="filter-now" role="status"></p>', here)
        self.assertIsNotNone(status)
        self.assertLess(status.start(), here.index('<details class="more here__details"'), "closed details hide it")
        self.assertNotIn("aria-live", here.split('<dl class="facts" id="status">')[1].split("</dl>")[0])

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
