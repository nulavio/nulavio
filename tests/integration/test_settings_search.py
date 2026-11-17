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
    row.querySelector("moz-button")?.label ?? null,
    row.querySelector("moz-button")?.shadowRoot?.querySelector("button")?.getAttribute("aria-label") ?? null]),
  none: el("nulavio-search-providers")?.querySelector("moz-box-item.nulavio-search-provider-none")?.label ?? null,
  searxng: shown(el("nulavio-search-searxng-url")) ? el("nulavio-search-searxng-url").value : null,
  opensearch: shown(el("nulavio-search-opensearch-url")) ? el("nulavio-search-opensearch-url").value : null,
  said: bar("nulavio-search-said"), error: bar("nulavio-search-error"),
  choices: rows("nulavio-search-choose", "nulavio-search-choice").map(row => ({ key: row.dataset.choice, name: row.label,
    says: row.description, buttons: [...row.querySelectorAll("moz-button")].map(b => [b.dataset.action, b.label]) })),
  privateToo: shown(el("nulavio-search-choose-privateToo")) ? el("nulavio-search-choose-privateToo").checked : null,
  suggest: shown(el("nulavio-search-choose-suggest")) ? el("nulavio-search-choose-suggest").checked : null,
  chose: bar("nulavio-search-choose-said"), choseError: bar("nulavio-search-choose-error"),
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
        key, name, button, named = now["providers"][0]
        # The button says "Adicionar"; its accessible name says which (#486: the full words broke the row's name).
        self.assertEqual(button, "Adicionar")
        self.assertEqual(named, f"Adicionar {name}")
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

    def test_03_a_provider_is_chosen_in_one_step(self):
        """#151: every engine and every provider Nulavio knows, by name in alphabetical order, none marked; "Usar"
        makes one the profile's search, for private windows too unless that box is unticked; a provider with accounts
        says whether the profile is signed in and offers to sign in."""
        self.open()
        now = self.seen(lambda n: n["choices"])
        names = [row["name"] for row in now["choices"]]
        self.assertEqual(names, sorted(names))
        self.assertTrue({"Brave Search", "DuckDuckGo", "Ecosia", "Kagi", "Mojeek", "Qwant", "Startpage"} <= set(names), names)
        self.assertEqual((now["privateToo"], now["suggest"]), (True, False))
        kagi = next(row for row in now["choices"] if row["name"] == "Kagi")
        self.assertEqual(
            kagi["says"],
            "Ainda não está neste perfil: entra quando você escolher."
            # #152: said before Kagi is chosen, with the providers that need no account.
            " Nas janelas privadas e nos perfis temporários este perfil não estará conectado."
            " Sem conta: Brave Search, DuckDuckGo, Ecosia, Mojeek, Qwant, Startpage."
            " Precisa de conta. Este perfil não está conectado em kagi.com.",
        )
        self.assertEqual(kagi["buttons"], [["signin", "Entrar"], ["choose", "Usar"]])
        in_use = [row["name"] for row in now["choices"] if row["says"].startswith("Em uso")]
        self.assertEqual(len(in_use), 1, now["choices"])
        # Mojeek for normal windows only: the box unticked, then "Usar".
        self.m.chrome(CLICK, ["#nulavio-search-choose-privateToo"])
        self.seen(lambda n: n["privateToo"] is False)
        mojeek = next(row for row in now["choices"] if row["name"] == "Mojeek")
        self.m.chrome(CLICK, [f'#nulavio-search-choose moz-button[data-action="choose"][data-choice="{mojeek["key"]}"]'])
        # The message comes before the list is read again: wait for both.
        done = self.seen(
            lambda n: (
                n["chose"]
                and any(row["name"] == "Mojeek" and row["says"] == "Em uso nas janelas normais." for row in n["choices"])
            )
        )
        self.assertEqual(done["chose"], "Mojeek é a pesquisa deste perfil nas janelas normais.")
        self.assertEqual(next(row for row in done["choices"] if row["name"] == "Mojeek")["says"], "Em uso nas janelas normais.")
        defaults = self.m.chrome(
            S + "return S.list().then(list => [list.find(e => e.isDefault).name, list.find(e => e.isDefaultPrivate).name]);"
        )
        self.assertEqual(defaults[0], "Mojeek")
        self.assertNotEqual(defaults[1], "Mojeek")
        self.assertEqual(self.state()["optIn"], [], "choosing is not consent to send typed text")
        # With the suggestions box ticked: the message names the host that now receives what is typed, and the box is
        # clear again for the next choice (consent is for one provider at a time).
        self.m.chrome(CLICK, ["#nulavio-search-choose-suggest"])
        self.seen(lambda n: n["suggest"] is True)
        brave = next(row for row in now["choices"] if row["name"] == "Brave Search")
        self.m.chrome(CLICK, [f'#nulavio-search-choose moz-button[data-action="choose"][data-choice="{brave["key"]}"]'])
        told = self.seen(lambda n: (n["chose"] or "").startswith("Brave Search") and n["suggest"] is False)
        self.assertEqual(
            told["chose"],
            "Brave Search é a pesquisa deste perfil nas janelas normais."
            " Ligado: o que você digita é enviado a search.brave.com enquanto você digita.",
        )
        self.assertIs(told["suggest"], False)
        self.assertEqual(len(self.state()["optIn"]), 1)

    def run_async(self, body: str, *args):
        """Privileged async JS in the window; returns its value, or the error's text."""
        self.m.set_context("chrome")
        try:
            script = "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
            return self.m.execute_async(script + "(async () => {" + body + "})().then(done, e => done(String(e)));", list(args))
        finally:
            self.m.set_context("content")

    def test_04_a_new_profile_starts_with_the_search_chosen_for_it(self):
        """#151: a new profile can be created with its search, in a file its own Shell applies at its first start
        (test_search 16); without a choice it gets none, and an unknown provider is refused before any profile is made."""
        P = 'const P = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles;'
        create = (
            P
            + "await P.create({name: args[0], ...(args[1] ? {search: args[1]} : {})});"
            + ("return (await P.list()).profiles.find(p => p.name === args[0]);")
        )
        pending = "return IOUtils.readJSON(PathUtils.join(args[0], 'nulavio-search-choice.json')).catch(e => e.name);"
        work = self.run_async(create, "Trabalho", {"provider": "qwant"})
        study = self.run_async(create, "Estudo", None)
        self.assertIsInstance(work, dict, work)
        self.assertIsInstance(study, dict, study)
        self.assertEqual(self.run_async(pending, work["path"]), {"provider": "qwant", "privateToo": True})
        mode = "return (await IOUtils.stat(PathUtils.join(args[0], 'nulavio-search-choice.json'))).permissions;"
        self.assertEqual(self.run_async(mode, work["path"]), 0o600, "the choice file is the owner's only")
        self.assertEqual(self.run_async(pending, study["path"]), "NotFoundError", "no choice: ADR 0002's default")
        # A provider Nulavio does not offer is refused before any profile is made.
        refused = self.run_async(P + "return P.create({name: 'Outro', search: {provider: 'nope'}}).catch(e => e.code);")
        self.assertEqual(refused, "unknown-provider")
        self.assertNotIn("Outro", [p["name"] for p in self.run_async(P + "return (await P.list()).profiles;")])
        # #152, review of #484: the new profile's picker says it too, before anything is picked.
        self.m.navigate("about:preferences#nulavioProfiles")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        note = DOC + 'return d.getElementById("nulavio-profile-new-search")?.description ?? null;'
        harness.wait_until(lambda: "Kagi" in (self.m.chrome(note) or ""), 15)
        self.assertEqual(
            self.m.chrome(note),
            "O mecanismo do novo perfil. Pode mudar depois em Configurações › Pesquisa."
            " Com conta: Kagi. Nas janelas privadas e nos perfis temporários o perfil não estará conectado a eles."
            " Sem conta: Brave Search, DuckDuckGo, Ecosia, Mojeek, Qwant, Startpage.",
        )


if __name__ == "__main__":
    unittest.main()
