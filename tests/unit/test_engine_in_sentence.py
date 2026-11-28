"""#828: a sentence that names a search engine Nulavio does not curate also says where its searches go (its host).

An added engine names itself (an OpenSearch description or an add-on), and Nulavio Search refuses only C0 controls and
DEL in a name. Two engines can then have names that read the same on screen while the stored names differ (a direction
mark, a zero-width character, a look-alike letter). A sentence that carries the name alone cannot tell them apart, and
the new tab could show one provider's name while the query goes to the other engine's host. The chooser rows already
say the host of every engine that is not curated (`chooseEngineHost`, #694: a provider is known by who defined the
engine and where it sends what is typed, never by a name alone). Here `engineInSentence` (browser/shell/lib/names.js)
runs under Node and fills, in both locales, every sentence that names an engine, for two engines whose shown names are
the same: the texts differ, by the host. tests/integration/test_settings_search.py (07) and test_newtab_ui.py (09) read
the same sentences on the real pages.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from node_tool import requires_node  # noqa: E402

SHELL = ROOT / "browser" / "shell"
NAMES = SHELL / "lib" / "names.js"
PANES = SHELL / "settings" / "native" / "panes.mjs"
NEWTAB = SHELL / "newtab" / "newtab.js"

# Two engines the person added, whose names read the same: the second one's stored name ends with U+200E LEFT-TO-RIGHT
# MARK (which `inSentence` removes) and holds U+200B ZERO WIDTH SPACE (which it keeps, and which shows as nothing).
ONE = {"id": "user-1", "name": "Busca", "host": "busca.example", "provider": None}
TWO = {"id": "user-2", "name": "Bu​sca‎", "host": "other.example", "provider": None}
# A SearXNG instance: its provider key comes from its name only, so it is the person's own engine, with its host.
SEARX = {"id": "user-3", "name": "SearXNG (searx.example)", "host": "searx.example", "provider": "searxng"}
# A curated provider: known by its definition, so its name is enough.
CURATED = {"id": "ddg", "name": "DuckDuckGo", "host": "duckduckgo.com", "provider": "duckduckgo"}
CURATED_KEYS = ["brave", "duckduckgo", "ecosia", "kagi", "mojeek", "qwant", "startpage"]

# The sentences that name one engine, and how each caller fills it: the name as `engineInSentence` gives it, after the
# label for the suggestions switch, inside the list of quoted names for the "@ia" warning.
SENTENCES = ("chooseDone", "chooseDoneBoth", "chooseUseNamed", "searchWith", "searchAliasReserved", "engineSuggestLabel")

DRIVER = """
const { readFileSync } = await import("node:fs");
const source = readFileSync(process.argv[1], "utf8");
const { engineInSentence } = await import("data:text/javascript;charset=utf-8," + encodeURIComponent(source));
const [locales, engines, curatedKeys] = JSON.parse(process.argv[2]);
const curated = new Set(curatedKeys);
const out = {};
for (const [language, path] of Object.entries(locales)) {
  const messages = JSON.parse(readFileSync(path, "utf8"));
  // The WebExtension substitution: $NAME$ -> its placeholder's content ($1, $2...) -> the values.
  const msg = (key, ...subs) => {
    const entry = messages[key];
    let text = entry.message;
    for (const [name, placeholder] of Object.entries(entry.placeholders ?? {})) {
      text = text.replace(new RegExp(`\\\\$${name}\\\\$`, "gi"), () => placeholder.content);
    }
    return text.replace(/\\$(\\d)/g, (_, n) => subs[Number(n) - 1] ?? "");
  };
  const withHost = (name, host) => msg("engineNamedHost", name, host);
  out[language] = engines.map(engine => {
    const named = engineInSentence(engine, { curated, withHost });
    const quoted = engineInSentence(engine, { curated, withHost, quoted: true });
    return {
      named,
      chooseDone: msg("chooseDone", named),
      chooseDoneBoth: msg("chooseDoneBoth", named),
      chooseUseNamed: msg("chooseUseNamed", named),
      searchWith: msg("searchWith", named),
      searchAliasReserved: msg("searchAliasReserved", [quoted].join(", ")),
      engineSuggestLabel: `${msg("engineSuggestLabel")}: ${named}`,
    };
  });
}
console.log(JSON.stringify(out));
"""


def shown(text: str) -> str:
    """What the eye reads: the text without its format characters (direction marks and isolates, zero-width ones)."""
    return "".join(char for char in text if unicodedata.category(char) != "Cf")


@requires_node
class EngineInSentenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        locales = {name: str(SHELL / "_locales" / name / "messages.json") for name in ("en", "pt_BR")}
        done = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                DRIVER,
                str(NAMES),
                json.dumps([locales, [ONE, TWO, SEARX, CURATED], CURATED_KEYS]),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        cls.out = json.loads(done.stdout)

    def test_the_two_names_read_the_same(self):
        """The premise: isolated as before (#796), the two names show the same text."""
        self.assertNotEqual(ONE["name"], TWO["name"])
        self.assertEqual(shown(ONE["name"]), shown(TWO["name"]))

    def test_every_sentence_tells_the_two_engines_apart_by_their_host(self):
        for language, (one, two, _searx, _curated) in self.out.items():
            for key in SENTENCES:
                with self.subTest(locale=language, key=key):
                    self.assertNotEqual(shown(one[key]), shown(two[key]))
                    self.assertIn("busca.example", one[key])
                    self.assertIn("other.example", two[key])
                    self.assertNotIn("other.example", one[key])

    def test_the_name_stays_isolated_and_the_host_follows_it(self):
        for language, (one, two, searx, _curated) in self.out.items():
            with self.subTest(locale=language):
                self.assertEqual(one["named"], "⁨Busca⁩ (busca.example)")
                self.assertEqual(two["named"], "⁨Bu​sca⁩ (other.example)")
                self.assertEqual(searx["named"], "⁨SearXNG (searx.example)⁩ (searx.example)")
                # The "@ia" warning quotes the name only (review of #772: a name may hold ", ").
                self.assertIn("“⁨Busca⁩” (busca.example)", one["searchAliasReserved"])

    def test_a_curated_provider_is_named_alone(self):
        for language, (*_, curated) in self.out.items():
            with self.subTest(locale=language):
                self.assertEqual(curated["named"], "⁨DuckDuckGo⁩")
                self.assertNotIn("duckduckgo.com", curated["searchWith"])
                self.assertIn("“⁨DuckDuckGo⁩”", curated["searchAliasReserved"])

    def test_the_host_message_exists_in_both_locales(self):
        for language in ("en", "pt_BR"):
            with self.subTest(locale=language):
                entry = json.loads((SHELL / "_locales" / language / "messages.json").read_text(encoding="utf-8"))[
                    "engineNamedHost"
                ]
                self.assertEqual(set(entry["placeholders"]), {"name", "host"})
                self.assertIn("$NAME$", entry["message"])
                self.assertIn("$HOST$", entry["message"])


class CallersNameTheHostTest(unittest.TestCase):
    """Every place that puts an engine into one of these sentences goes through the helper, and a search still goes to
    the engine by its stored name or id, never by the text shown."""

    def test_settings_names_each_engine_with_its_host(self):
        panes = PANES.read_text(encoding="utf-8")
        self.assertRegex(
            panes, r"\bengineInSentence\b[^}]*\} = ChromeUtils\.importESModule\(\s*\"resource://[^\"]+/lib/names\.js\""
        )
        self.assertIn(
            "engineInSentence(engine, { curated: curatedKeys(), "
            'withHost: (name, host) => msg("engineNamedHost", name, host), quoted })',
            panes,
        )
        self.assertIn('msg("chooseUseNamed", rowInSentence(row))', panes)
        # The message after a choice is said once the choice is made, from the engine chosen as the list has it then
        # (review of #927): a row read before may name a host the engine no longer has.
        said = re.search(r"const said = id => \{(.*?)\n        \};", panes, re.S)
        self.assertIsNotNone(said, "the message after a choice is no longer built from the chosen engine")
        self.assertIn("const chosen = row.provider ? null : shell.NulavioSearch.namedOf(id);", said.group(1))
        self.assertIn('"chooseDoneBoth" : "chooseDone", chosen ? named(chosen) : rowInSentence(row))', said.group(1))
        self.assertIn('msg("searchAliasReserved", releasedNow().map(engine => named(engine, true)).join(", "))', panes)
        self.assertIn('"aria-label": `${msg("engineSuggestLabel")}: ${named(engine)}`', panes)
        # A row of a curated provider is named alone; any other row by its engine, with that engine's host.
        self.assertIn("named(row.provider ? { name: row.name, provider: row.provider } : row.engine)", panes)
        # No sentence of these takes the name alone any more.
        for key in ("chooseDone", "chooseDoneBoth", "chooseUseNamed", "searchAliasReserved"):
            with self.subTest(key=key):
                for call in re.findall(rf'"{key}"[^\n]*', panes):
                    self.assertNotIn("inSentence(row.name)", call)
                    self.assertNotIn("inSentence(name)", call)
        # The choice is still made by the provider's key or the engine's id.
        self.assertIn("const target = row.provider ? { provider: row.provider } : { id: row.engine.id };", panes)

    def test_settings_hears_the_host_of_an_engine_that_lost_the_keyword(self):
        module = (SHELL / "modules" / "NulavioSearch.sys.mjs").read_text(encoding="utf-8")
        body = re.search(r"async releasedAliases\(\) \{(.*?)\n  \}", module, re.S).group(1)
        self.assertIn(
            "names.push({ id: engine.id, name: engine.name, host: engine.searchUrlDomain, provider: this.#providerKey(engine) })",
            body,
        )

    def test_the_new_tab_names_the_engine_with_its_host_and_searches_by_its_stored_name(self):
        newtab = NEWTAB.read_text(encoding="utf-8")
        self.assertIn('import { engineInSentence } from "../lib/names.js";', newtab)
        self.assertEqual(
            re.findall(r't\("searchWith", [^\n]*', newtab),
            [
                't("searchWith", [engineInSentence(engine, { curated, '
                'withHost: (name, host) => t("engineNamedHost", [name, host]) })])'
            ],
        )
        # The search goes to the engine the placeholder named, by the name the engine stores.
        self.assertIn("shownEngine = engine?.name ?? null;", newtab)
        self.assertIn('browser.search.search({ query: text, engine: shownEngine, disposition: "CURRENT_TAB" });', newtab)


if __name__ == "__main__":
    unittest.main()
