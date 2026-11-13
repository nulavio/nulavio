"""ADR 0011: what Nulavio adds to the engine's Search pane, inside the settings page.

Which engines may receive what the person types (suggestions, engine by engine) and the engines Nulavio knows
how to add. Every change goes through NulavioSearch; the tests act on the page and read the result from the
module and from the engine's own search service. Nothing is downloaded: adding from an OpenSearch description
is checked with the module's entry replaced.
"""

from __future__ import annotations

import unittest

import harness

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
S = 'const S = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSearch.sys.mjs").NulavioSearch;'
STATE = (
    S
    + """return S.state().then(state => ({
  engines: state.engines.map(e => ({
    id: e.id, name: e.name, can: e.canSuggest, on: e.suggestOptIn, host: e.suggestHost, provider: e.provider,
  })),
  providers: state.providers.map(p => p.key), optIn: S.optInIds(),
  master: Services.prefs.getBoolPref("browser.search.suggest.enabled", false),
}));"""
)
PAGE = (
    DOC
    + """
const shown = el => !!el && !el.closest("setting-control")?.hidden && el.getBoundingClientRect().height > 0;
const el = id => d.getElementById(id);
const bar = id => (shown(el(id)) ? el(id).message : null);
const rows = (id, cls) => (shown(el(id)) ? [...el(id).querySelectorAll(`moz-box-item.${cls}`)] : []);
return {
  engines: rows("nulavio-suggest-engines", "nulavio-engine").map(row => {
    const toggle = row.querySelector("moz-toggle");
    return { id: row.dataset.engine, name: row.label, says: row.description, on: Boolean(toggle?.pressed),
             named: toggle?.ariaLabel ?? null };
  }),
  providers: rows("nulavio-search-providers", "nulavio-search-provider").map(row => [row.dataset.provider, row.label,
    row.querySelector("moz-button")?.label ?? null]),
  none: el("nulavio-search-providers")?.querySelector("moz-box-item.nulavio-search-provider-none")?.label ?? null,
  searxng: shown(el("nulavio-search-searxng-url")) ? el("nulavio-search-searxng-url").value : null,
  opensearch: shown(el("nulavio-search-opensearch-url")) ? el("nulavio-search-opensearch-url").value : null,
  said: bar("nulavio-search-said"), error: bar("nulavio-search-error"),
};
"""
)
TOGGLE = (
    DOC
    + """
const toggle = [...d.querySelectorAll("#nulavio-suggest-engines moz-toggle")].find(t => t.dataset.engine === arguments[0]);
if (!toggle) return false;
toggle.click();
return true;
"""
)
CLICK = DOC + "const el = d.querySelector(arguments[0]); if (!el) return false; el.click(); return true;"
CHANGE = (
    DOC
    + """
const el = d.getElementById(arguments[0]);
if (!el) return false;
el.value = arguments[1];
el.dispatchEvent(new Event("change", { bubbles: true }));
return true;
"""
)


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsSearchTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def open(self) -> dict:
        self.m.navigate("about:preferences#search")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        return self.seen(lambda now: now["engines"] and now["searxng"] is not None)

    def seen(self, wanted, timeout: float = 15) -> dict:
        harness.wait_until(lambda: wanted(self.m.chrome(PAGE)), timeout)
        now = self.m.chrome(PAGE)
        self.assertTrue(wanted(now), now)
        return now

    def state(self) -> dict:
        return self.m.chrome(STATE)

    def test_01_an_engine_receives_what_is_typed_only_when_switched_on_here(self):
        now = self.open()
        before = self.state()
        can = [engine for engine in before["engines"] if engine["can"]]
        # Every engine that offers suggestions has its switch, as the module says it is: off in a new profile.
        self.assertEqual([row["id"] for row in now["engines"]], [engine["id"] for engine in can])
        self.assertEqual(before["optIn"], [])
        self.assertFalse(before["master"])
        self.assertTrue(
            all(not row["on"] and row["says"] == "Desligado: nada é enviado até você pesquisar." for row in now["engines"])
        )
        engine = can[0]
        row = next(r for r in now["engines"] if r["id"] == engine["id"])
        self.assertEqual(row["named"], f"Sugestões enquanto você digita: {engine['name']}")
        # On: the module's list has it, the engine's own switch follows, and the row says where typed text goes.
        self.assertTrue(self.m.chrome(TOGGLE, [engine["id"]]))
        on = self.seen(lambda n: next(r for r in n["engines"] if r["id"] == engine["id"])["on"] and n["said"])
        self.assertEqual(self.state()["optIn"], [engine["id"]])
        self.assertTrue(self.state()["master"])
        says = next(r for r in on["engines"] if r["id"] == engine["id"])["says"]
        self.assertEqual(says, f"Ligado: o que você digita é enviado a {engine['host']} enquanto você digita.")
        self.assertEqual(sum(r["on"] for r in on["engines"]), 1, "another engine was switched on with it")
        # Off again: the last one off turns the engine's own switch off too.
        self.m.chrome(TOGGLE, [engine["id"]])
        self.seen(lambda n: not next(r for r in n["engines"] if r["id"] == engine["id"])["on"])
        self.assertEqual(self.state()["optIn"], [])
        self.assertFalse(self.state()["master"])
        # Switched on in the engine's own group (its "show suggestions" box): the default engine's row follows.
        self.m.chrome('Services.prefs.setBoolPref("browser.search.suggest.enabled", true);')
        followed = self.seen(lambda n: any(r["on"] for r in n["engines"]))
        self.assertEqual([r["id"] for r in followed["engines"] if r["on"]], self.state()["optIn"])
        # A refusal is said in the Shell's words, and the switch shows what is true.
        refuse = 'S.setSuggestOptIn = async () => { throw Object.assign(new Error("x"), { code: "no-suggestions" }); };'
        self.m.chrome(S + refuse)
        self.addCleanup(self.m.chrome, S + "delete S.setSuggestOptIn;")
        other = next(r for r in followed["engines"] if not r["on"])
        self.m.chrome(TOGGLE, [other["id"]])
        refused = self.seen(lambda n: n["error"])
        self.assertEqual(refused["error"], "Este mecanismo não oferece sugestões.")
        self.assertFalse(next(r for r in refused["engines"] if r["id"] == other["id"])["on"])

    def test_02_engines_nulavio_knows_how_to_add(self):
        now = self.open()
        before = self.state()
        have = {engine["provider"] for engine in before["engines"] if engine["provider"]}
        missing = [key for key in before["providers"] if key not in have]
        self.assertEqual([row[0] for row in now["providers"]], missing)
        self.assertTrue(missing, "a new profile should not have every provider yet")
        key, name, button = now["providers"][0]
        self.assertEqual(button, f"Adicionar {name}")
        # A known provider, one click: it joins the engine's own list and leaves this one.
        self.m.chrome(CLICK, [f'#nulavio-search-providers moz-button[data-provider="{key}"]'])
        added = self.seen(lambda n: n["said"] and key not in [row[0] for row in n["providers"]])
        self.assertEqual(added["said"], "Adicionado.")
        self.assertIn(key, {engine["provider"] for engine in self.state()["engines"]})
        # An instance of the person's own: an address that is not one, then http, then a good one.
        count = len(self.state()["engines"])
        self.m.chrome(CHANGE, ["nulavio-search-searxng-url", "not an address"])
        self.m.chrome(CLICK, ["#nulavio-search-searxng-add"])
        self.assertEqual(self.seen(lambda n: n["error"])["error"], "Esse endereço não é válido.")
        self.m.chrome(CHANGE, ["nulavio-search-searxng-url", "http://searx.example.org/"])
        self.m.chrome(CLICK, ["#nulavio-search-searxng-add"])
        http = self.seen(lambda n: n["error"] and "https://" in n["error"])
        self.assertEqual(http["error"], "Use um endereço https:// (http:// só para este computador).")
        self.assertEqual(http["searxng"], "http://searx.example.org/")
        self.assertEqual(len(self.state()["engines"]), count)
        self.m.chrome(CHANGE, ["nulavio-search-searxng-url", "https://searx.example.org/"])
        self.m.chrome(CLICK, ["#nulavio-search-searxng-add"])
        done = self.seen(lambda n: n["said"] == "Adicionado." and n["searxng"] == "")
        names = [engine["name"] for engine in self.state()["engines"]]
        self.assertIn("SearXNG (searx.example.org)", names)
        # Its suggestions are off like any other's: adding an engine never switches them on.
        self.assertFalse(next(r for r in done["engines"] if r["name"] == "SearXNG (searx.example.org)")["on"])
        # From a site's description: the module is asked with the address typed; a failed download is said in words.
        record = "window.__asked = []; S.addOpenSearch = async details => { window.__asked.push(details.url);"
        self.m.chrome(S + record + ' throw Object.assign(new Error("x"), { code: "opensearch-failed" }); };')
        self.addCleanup(self.m.chrome, S + "delete S.addOpenSearch;")
        self.m.chrome(CHANGE, ["nulavio-search-opensearch-url", "https://example.org/opensearch.xml"])
        self.m.chrome(CLICK, ["#nulavio-search-opensearch-add"])
        failed = self.seen(lambda n: n["error"] and "descrição" in n["error"])
        self.assertEqual(failed["error"], "Não foi possível ler essa descrição.")
        self.assertEqual(failed["opensearch"], "https://example.org/opensearch.xml")
        self.assertEqual(self.m.chrome("return window.__asked;"), ["https://example.org/opensearch.xml"])


if __name__ == "__main__":
    unittest.main()
