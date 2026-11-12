"""Nulavio Search (docs/adr/0002-nulavio-search.md).

What typing in the address bar sends, measured on the real engine: every HTTP
request the browser starts is recorded (``http-on-modify-request``) while
keys are typed into the address bar with real key events. A local fixture
engine is the positive control: it receives suggestion requests only after
the user opts in for it, which proves the measurement sees them.

Track A (distribution Firefox + launcher) gets the seed prefs only, so only
the "nothing is sent" tests run there; the per-provider consent, the curated
providers, the private default and the settings page need the Nulavio build.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
import settings_page


MODULE = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSearch.sys.mjs").NulavioSearch'
NET_START = """
const seen = [];
const observer = { observe(subject) {
  try { seen.push(subject.QueryInterface(Ci.nsIChannel).URI.spec); } catch (e) {}
} };
Services.obs.addObserver(observer, "http-on-modify-request");
window.nulavioTestNet = { seen, observer };
"""
NET_STOP = """
const net = window.nulavioTestNet;
Services.obs.removeObserver(net.observer, "http-on-modify-request");
delete window.nulavioTestNet;
return net.seen;
"""
ENTER = "\n"
TYPE_JS = """
const [text, select] = arguments;
if (select) {
  gURLBar.select();
}
const tip = Cc["@mozilla.org/text-input-processor;1"].createInstance(Ci.nsITextInputProcessor);
if (!tip.beginInputTransactionForTests(window)) {
  throw new Error("could not start an input transaction");
}
for (const ch of text) {
  const event = ch === "\\n"
    ? new KeyboardEvent("", {key: "Enter", code: "Enter", keyCode: 13})
    : new KeyboardEvent("", {key: ch});
  tip.keydown(event);
  tip.keyup(event);
}
"""
SEARCH_HOSTS = (
    "google.com",
    "bing.com",
    "duckduckgo.com",
    "search.brave.com",
    "mojeek.com",
    "perplexity.ai",
    "wikipedia.org",
    "kagi.com",
    "kagisuggest.com",
    "mercadolivre.com.br",
)


def chrome_async(m, body: str, args=()):
    """Run privileged async JS; returns {"ok": value} or {"error": code}."""
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        return m.execute_async(script, list(args))
    finally:
        m.set_context("content")


@unittest.skipUnless(harness.engine_available(), "no supported Gecko engine installed")
class SearchPrivacyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.Session(profile="search")
        cls.m = cls.session.start()
        cls.nulavio = harness.nulavio_engine() is not None
        if cls.nulavio:
            # The Shell migrates search after first paint; wait for it.
            harness.wait_until(lambda: cls.pref("nulavio.search.migration", 0) == 1, timeout=30)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    # -- helpers -----------------------------------------------------------

    @classmethod
    def pref(cls, name, default=None):
        return cls.m.chrome(
            "const [n, d] = arguments; const t = Services.prefs.getPrefType(n);"
            "return t === 128 ? Services.prefs.getBoolPref(n) : t === 64 ? Services.prefs.getIntPref(n)"
            " : t === 32 ? Services.prefs.getStringPref(n) : d;",
            [name, default],
        )

    def search(self, body: str, *args):
        result = chrome_async(self.m, f"const S = {MODULE}; {body}", args)
        if "error" in result:
            raise AssertionError(f"NulavioSearch failed: {result['error']}")
        return result["ok"]

    def search_error(self, body: str, *args) -> str | None:
        return chrome_async(self.m, f"const S = {MODULE}; {body}", args).get("error")

    def type_keys(self, keys: str, select: bool = True) -> None:
        """Type into the address bar with trusted key events (as Firefox's own tests do).

        nsITextInputProcessor dispatches keydown/keypress/keyup to the focused
        field, so the address bar handles them exactly like a user's typing.
        WebDriver's element typing is not used: it refuses the address bar in
        some headless setups ("not reachable by keyboard").
        """
        if select:
            self.focus_urlbar()
        self.m.chrome(TYPE_JS, [keys, select])

    def focus_urlbar(self) -> None:
        # Mozilla's own builds open a first-run modal (Terms of Use) that holds
        # the window's focus; a user closes it before typing, and so do we.
        self.m.chrome("if (window.gDialogBox?.isOpen) { window.gDialogBox.dialog?.close(); }")
        focused = harness.wait_until(lambda: self.m.chrome("gURLBar.focus(); return gURLBar.focused;"), timeout=10)
        self.assertTrue(focused, "the address bar did not take focus")

    def type_in_urlbar(self, text: str, settle: float = 2.0) -> list[str]:
        """Type `text` as a search; return every HTTP request the browser started meanwhile."""
        self.m.chrome("gURLBar.blur();")
        self.m.chrome(NET_START)
        try:
            self.type_keys(text)
            time.sleep(settle)  # remote suggestions time out after 500 ms upstream
            typed = self.m.chrome("return [gURLBar.value, gURLBar.searchMode?.engineName ?? null];")
        finally:
            seen = self.m.chrome(NET_STOP)
            self.m.chrome("gURLBar.searchMode = null; gURLBar.view.close(); gURLBar.handleRevert(); gURLBar.blur();")
        # An alias puts the address bar in that engine's search mode and keeps only the terms.
        expected = text.split(" ", 1)[1] if text.startswith("@") else text
        self.assertEqual(typed[0], expected, "the keys did not land in the address bar as typed")
        if text.startswith("@"):
            self.assertTrue(typed[1], f"{text.split()[0]} did not select its engine")
        return seen

    def assert_nothing_about(self, seen: list[str], marker: str, hosts=SEARCH_HOSTS):
        carrying = [u for u in seen if marker in u]
        self.assertEqual(carrying, [], "typed text left the browser")

        def host(url: str) -> str:
            return (urlsplit(url).hostname or "").lower()

        to_search = [u for u in seen if any(host(u) == h or host(u).endswith(f".{h}") for h in hosts)]
        self.assertEqual(to_search, [], "a search provider was contacted while typing")

    # -- tests -------------------------------------------------------------

    def test_01_seed_prefs(self):
        self.assertIs(self.pref("browser.search.suggest.enabled"), False)
        self.assertIs(self.pref("browser.urlbar.suggest.trending"), False)
        self.assertIs(self.pref("browser.search.separatePrivateDefault.enabled"), True)
        self.assertIs(self.pref("browser.search.separatePrivateDefault.featureGate"), True)

    def test_02_typing_and_focus_send_nothing(self):
        seen = self.type_in_urlbar("nvtypedmarker")
        self.assert_nothing_about(seen, "nvtypedmarker")

    def test_03_aliases_send_nothing_while_typing(self):
        for alias in ("@google", "@bing") + (("@ddg", "@brave") if self.nulavio else ()):
            with self.subTest(alias=alias):
                marker = f"nvalias{alias[1:]}marker"
                self.assert_nothing_about(self.type_in_urlbar(f"{alias} {marker}"), marker)

    # -- Nulavio build only --------------------------------------------------

    def require_nulavio(self):
        if not self.nulavio:
            self.skipTest("per-provider consent and curated providers need the Nulavio build")

    def test_04_first_run_defaults_and_providers(self):
        self.require_nulavio()
        state = self.search("return S.state();")
        by_name = {e["name"]: e for e in state["engines"]}
        self.assertTrue(by_name["DuckDuckGo"]["isDefault"])
        self.assertTrue(by_name["DuckDuckGo"]["isDefaultPrivate"])
        self.assertIn("@ddg", by_name["DuckDuckGo"]["aliases"])
        self.assertEqual(by_name["Brave Search"]["alias"], "@brave")
        self.assertEqual(by_name["Mojeek"]["alias"], "@mojeek")
        self.assertNotIn("Kagi", by_name, "Kagi is added only on request")
        self.assertFalse(any(e["name"].startswith("SearXNG") for e in state["engines"]), "no public SearXNG instance")
        self.assertFalse(any(e["suggestOptIn"] for e in state["engines"]))
        self.assertEqual(self.pref("nulavio.search.suggest.optin", ""), "")
        submissions = self.search(
            "const {SearchService} = ChromeUtils.importESModule('moz-src:///toolkit/components/search/SearchService.sys.mjs');"
            "const out = {}; for (const a of ['@ddg', '@brave', '@mojeek']) {"
            " out[a] = (await SearchService.getEngineByAlias(a)).getSubmission('nulavio').uri.host; } return out;"
        )
        self.assertEqual(submissions, {"@ddg": "duckduckgo.com", "@brave": "search.brave.com", "@mojeek": "www.mojeek.com"})

    def test_05_consent_is_per_provider(self):
        """Positive control: a local engine gets typed text only after opting in, and only it."""
        self.require_nulavio()
        fixture = self.search(
            "return S.addCustom({name: 'Fixture', url: args[0], suggestUrl: args[1], alias: '@fixture'});",
            self.server.url("/search?q=%s"),
            self.server.url("/suggest?q=%s"),
        )
        previous = self.search("return (await S.list()).find(e => e.isDefault).id;")
        self.search("await S.setDefault(args[0]);", fixture)
        try:
            seen = self.type_in_urlbar("nvbeforeoptin")
            self.assertEqual(self.server.requests_to("/suggest"), [], "suggestions without consent")
            self.assert_nothing_about(seen, "nvbeforeoptin", hosts=SEARCH_HOSTS)

            self.search("await S.setSuggestOptIn(args[0], true);", fixture)
            self.assertIs(self.pref("browser.search.suggest.enabled"), True)
            self.type_in_urlbar("nvafteroptin")
            hits = self.server.requests_to("/suggest")
            self.assertTrue(any("nvafteroptin" in h for h in hits), f"positive control failed: {hits}")

            # Consent for one engine does not cover the others, even through an alias.
            self.assert_nothing_about(self.type_in_urlbar("@brave nvotherengine"), "nvotherengine")
            self.assert_nothing_about(self.type_in_urlbar("@google nvotherengine2"), "nvotherengine2")

            self.search("await S.setSuggestOptIn(args[0], false);", fixture)
            self.assertIs(self.pref("browser.search.suggest.enabled"), False)
            before = len(self.server.requests_to("/suggest"))
            self.type_in_urlbar("nvafteroptout")
            self.assertEqual(len(self.server.requests_to("/suggest")), before, "suggestions after opting out")
        finally:
            self.search("await S.setDefault(args[0]);", previous)
            self.search("await S.remove(args[0]);", fixture)

    def test_05b_text_after_the_assistant_keyword_never_reaches_suggestions(self):
        """UX5-H gate: with remote suggestions allowed for the default engine, what follows "@ia" (the
        Nulavio Assistant's keyword) never reaches a suggestion service or any other request. The engine
        skips suggestions for "@" text that names no engine (bug 1551049); this pins it. The same setup
        does send ordinary typing, which proves the measurement sees it."""
        self.require_nulavio()
        fixture = self.search(
            "return S.addCustom({name: 'Fixture', url: args[0], suggestUrl: args[1], alias: '@fixture'});",
            self.server.url("/search?q=%s"),
            self.server.url("/suggest?q=%s"),
        )
        previous = self.search("return (await S.list()).find(e => e.isDefault).id;")
        self.search("await S.setDefault(args[0]);", fixture)
        self.search("await S.setSuggestOptIn(args[0], true);", fixture)
        try:
            self.m.chrome("gURLBar.blur();")
            self.m.chrome(NET_START)
            try:
                self.type_keys("@ia nvassistantsecret")
                time.sleep(2.0)
                typed = self.m.chrome("return gURLBar.value;")
            finally:
                seen = self.m.chrome(NET_STOP)
                self.m.chrome("gURLBar.view.close(); gURLBar.handleRevert(); gURLBar.blur();")
            self.assertEqual(typed, "@ia nvassistantsecret")
            self.assertFalse([h for h in self.server.requests_to("/suggest") if "nvassistantsecret" in h])
            self.assert_nothing_about(seen, "nvassistantsecret")
            self.type_in_urlbar("nvcontrolafteria")  # the positive control, with the same consent
            self.assertTrue(any("nvcontrolafteria" in h for h in self.server.requests_to("/suggest")))
        finally:
            self.search("await S.setSuggestOptIn(args[0], false);", fixture)
            self.search("await S.setDefault(args[0]);", previous)
            self.search("await S.remove(args[0]);", fixture)

    def test_06_alias_search_goes_straight_to_its_engine(self):
        self.require_nulavio()
        fixture = self.search(
            "return S.addCustom({name: 'Fixture Go', url: args[0], alias: '@fixgo'});", self.server.url("/search?q=%s")
        )
        try:
            self.m.chrome(NET_START)
            self.type_keys("@fixgo nvaliassearch")
            # The alias switches the address bar to that engine first; then Enter searches.
            harness.wait_until(lambda: self.m.chrome("return gURLBar.searchMode?.engineName ?? null;") == "Fixture Go", timeout=5)
            self.type_keys(ENTER, select=False)
            harness.wait_until(lambda: self.server.requests_to("/search"), timeout=15)
            seen = self.m.chrome(NET_STOP)
            self.assertTrue(any("q=nvaliassearch" in h for h in self.server.requests_to("/search")))
            elsewhere = [u for u in seen if "nvaliassearch" in u and f"127.0.0.1:{self.server.port}" not in u]
            self.assertEqual(elsewhere, [], "the search went somewhere else too")
        finally:
            self.search("await S.remove(args[0]);", fixture)

    def test_07_private_default_is_independent(self):
        self.require_nulavio()
        brave = self.search("return (await S.list()).find(e => e.alias === '@brave').id;")
        ddg = self.search("return (await S.list()).find(e => e.isDefault).id;")
        self.search("await S.setDefault(args[0], {private: true});", brave)
        try:
            state = self.search("return (await S.list()).map(e => [e.id, e.isDefault, e.isDefaultPrivate]);")
            self.assertIn([ddg, True, False], state)
            self.assertIn([brave, False, True], state)
            engines = self.m.chrome(
                "const {UrlbarSearchUtils} = ChromeUtils.importESModule('moz-src:///browser/components/urlbar/UrlbarSearchUtils.sys.mjs');"
                "return [UrlbarSearchUtils.getDefaultEngine(false).id, UrlbarSearchUtils.getDefaultEngine(true).id];"
            )
            self.assertEqual(engines, [ddg, brave])
        finally:
            self.search("await S.setDefault(args[0], {private: true});", ddg)

    def test_08_validation(self):
        self.require_nulavio()
        cases = {
            "needs-https": "return S.addSearxng({url: 'http://searx.example.org/'});",
            "credentials-in-url": "return S.addSearxng({url: 'https://u:p@searx.example.org/'});",
            "invalid-url": "return S.addSearxng({url: 'not a url'});",
            "missing-terms": "return S.addCustom({name: 'X', url: 'https://example.org/search'});",
            "suggest-other-host": "return S.addCustom({name: 'X', url: 'https://example.org/?q=%s', suggestUrl: 'https://other.example/?q=%s'});",
            "alias-taken": "return S.addCustom({name: 'X', url: 'https://example.org/?q=%s', alias: '@brave'});",
            "invalid-alias": "return S.addCustom({name: 'X', url: 'https://example.org/?q=%s', alias: '@no spaces'});",
            "name-taken": "return S.addCustom({name: 'Mojeek', url: 'https://example.org/?q=%s'});",
            "no-suggestions": "return S.setSuggestOptIn((await S.list()).find(e => e.alias === '@mojeek').id, true);",
        }
        for code, body in cases.items():
            with self.subTest(code=code):
                self.assertEqual(self.search_error(body), code)
        names = [e["name"] for e in self.search("return S.list();")]
        self.assertNotIn("X", names, "a rejected engine was added")

    def test_09_searxng_kagi_add_and_remove(self):
        self.require_nulavio()
        searx = self.search("return S.addSearxng({url: 'https://searx.example.org/search'});")
        engine = self.search(
            "const e = (await S.list()).find(x => x.id === args[0]);"
            "const {SearchService} = ChromeUtils.importESModule('moz-src:///toolkit/components/search/SearchService.sys.mjs');"
            "const raw = SearchService.getEngineById(args[0]);"
            "return {...e, search: raw.getSubmission('q1').uri.spec,"
            " suggest: raw.getSubmission('q1', 'application/x-suggestions+json').uri.spec};",
            searx,
        )
        self.assertEqual(engine["name"], "SearXNG (searx.example.org)")
        self.assertEqual(engine["alias"], "@searx")
        self.assertEqual(engine["search"], "https://searx.example.org/search?q=q1")
        self.assertEqual(engine["suggest"], "https://searx.example.org/autocompleter?q=q1")
        self.assertFalse(engine["suggestOptIn"])

        self.search("await S.setSuggestOptIn(args[0], true);", searx)
        self.assertIn(searx, self.pref("nulavio.search.suggest.optin"))
        self.search("await S.remove(args[0]);", searx)
        self.assertNotIn(searx, [e["id"] for e in self.search("return S.list();")])
        self.assertNotIn(searx, self.pref("nulavio.search.suggest.optin", ""), "consent outlived the engine")
        self.assertIs(self.pref("browser.search.suggest.enabled"), False)

        kagi = self.search("return S.addProvider('kagi');")
        self.assertEqual(self.search("return (await S.list()).find(e => e.id === args[0]).alias;", kagi), "@kagi")
        self.search("await S.remove(args[0]);", kagi)

    def test_10_migration_runs_once_and_keeps_a_choice(self):
        self.require_nulavio()
        bing = "bing"
        ddg = self.search("return (await S.list()).find(e => e.isDefault).id;")
        self.search("await S.setDefault(args[0]);", bing)
        try:
            self.assertEqual(self.search("return S.migrate();"), {"migrated": False})
            self.m.chrome("Services.prefs.clearUserPref('nulavio.search.migration');")
            result = self.search("return S.migrate();")
            self.assertTrue(result["migrated"])
            self.assertFalse(result["defaultChanged"], "migration replaced a default the user chose")
            self.assertEqual(self.search("return (await S.list()).find(e => e.isDefault).id;"), bing)
            names = [e["name"] for e in self.search("return S.list();")]
            self.assertEqual(names.count("Brave Search"), 1, "migration duplicated a provider")
        finally:
            self.search("await S.setDefault(args[0]);", ddg)

    def test_11_upstream_switch_is_consent_for_the_default_only(self):
        self.require_nulavio()
        ddg = self.search("return (await S.list()).find(e => e.isDefault).id;")
        self.m.chrome("Services.prefs.setBoolPref('browser.search.suggest.enabled', true);")
        try:
            harness.wait_until(lambda: ddg in self.pref("nulavio.search.suggest.optin", ""), timeout=5)
            self.assertEqual(self.pref("nulavio.search.suggest.optin"), ddg)
        finally:
            self.search("await S.setSuggestOptIn(args[0], false);", ddg)
        self.assertIs(self.pref("browser.search.suggest.enabled"), False)

    def test_12_settings_page_adds_through_the_ui(self):
        self.require_nulavio()
        # ADR 0011: the engines Nulavio knows how to add are a list in the settings page's own Search pane.
        settings_page.open_pane(self.m, "search")
        each = "moz-box-item.nulavio-search-provider"
        offered = settings_page.wait_rows(self.m, "nulavio-search-providers", len, each)
        self.assertIn("kagi", [row["data"]["provider"] for row in offered])
        self.assertEqual(self.search("return (await S.list()).find(e => e.isDefault).name;"), "DuckDuckGo")
        self.assertGreaterEqual(len(self.search("return S.list();")), 7)

        settings_page.click_row(self.m, "nulavio-search-providers", "kagi", None, each)
        kagi = lambda: [e["id"] for e in self.search("return S.list();") if e["name"].startswith("Kagi")]  # noqa: E731
        self.assertTrue(harness.wait_until(kagi, timeout=10), "Kagi was not added")
        try:
            # It joined the engine's own list, so it is no longer offered here.
            settings_page.wait_rows(
                self.m, "nulavio-search-providers", lambda rows: "kagi" not in [row["data"]["provider"] for row in rows], each
            )
            # The settings page itself must not reach the network.
            loaded = settings_page.DOC + "return w.performance.getEntriesByType('resource').map(e => e.name);"
            external = [name for name in self.m.chrome(loaded) if name.startswith(("http:", "https:", "ws:", "wss:"))]
            self.assertEqual(external, [])
        finally:
            # Removing an engine is the engine's own list in this pane; the service does what its button does.
            for engine in kagi():
                self.search("await S.remove(args[0]);", engine)
        self.assertNotIn("Kagi", [e["name"] for e in self.search("return S.list();")])

    def test_13_an_alias_is_stored_in_one_form(self):
        """Review UX7: an alias is kept as "@pato" however it was typed, and that is what every list shows."""
        self.require_nulavio()
        ddg = self.search("return (await S.list()).find(e => e.name.startsWith('DuckDuckGo')).id;")
        alias = lambda: self.search("return (await S.list()).find(e => e.id === args[0]).alias;", ddg)  # noqa: E731
        before = alias()
        try:
            for typed, stored in (("Pato", "@pato"), ("  @PATO ", "@pato"), (before, before)):
                self.search("await S.setAlias(args[0], args[1]); return true;", ddg, typed or "")
                self.assertEqual(alias() or "", stored or "")
        finally:
            self.search("await S.setAlias(args[0], args[1]); return true;", ddg, before or "")


if __name__ == "__main__":
    unittest.main()
