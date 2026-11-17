"""#156: web services used on a click, for translation.

Translation stays on the device by default; a web service is used only after the person adds it, from a menu item
that names it, and only on that click (page summaries, #154, are After 1.0). The tests check the addresses
each known service gets, what is refused, that the menu offers nothing before a service is added and sends nothing
before the click, private windows, and the settings page. Every request that is not to the local fixture server is
recorded and cancelled, so nothing reaches a real service. On-device translation needs the engine's models from
Mozilla's servers: that test runs only with NULAVIO_NETWORK_TESTS=1.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from urllib.parse import quote, urlsplit

import harness

SV = 'const SV = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioServices.sys.mjs");'
# The services' hosts and the linked page's: what a click could send to. The engine's own background traffic
# (Remote Settings and the like, docs/security/new-profile-connections.md) is left alone.
WATCHED = ("deepl.com", "translate.google.com", "kagi.com", "lt.example.org", "tr.example.net", "r.example.net", "example.org")
GUARD_START = """
const watched = arguments[0];
const seen = [];
const observer = { observe(subject) {
  try {
    const channel = subject.QueryInterface(Ci.nsIHttpChannel);
    const host = channel.URI.host;
    if (watched.some(h => host === h || host.endsWith('.' + h))) {
      seen.push(channel.URI.spec);
      channel.cancel(Cr.NS_BINDING_ABORTED);
    }
  } catch (e) {}
} };
Services.obs.addObserver(observer, "http-on-modify-request");
window.nulavioServicesNet = { seen, observer };
"""
GUARD_SEEN = "return window.nulavioServicesNet.seen.slice();"
GUARD_STOP = (
    "const net = window.nulavioServicesNet; Services.obs.removeObserver(net.observer, 'http-on-modify-request');"
    "delete window.nulavioServicesNet; return net.seen;"
)
MENU = """
const open = [...Services.wm.getEnumerator('navigator:browser')].map(w => w.document)
  .find(d => d.getElementById('contentAreaContextMenu').state === 'open');
if (!open) return null;
return [...open.querySelectorAll("#contentAreaContextMenu [id*='-menuitem-_nulavio-svc-']")].map(item => ({
  label: item.getAttribute('label'), disabled: item.disabled,
  shown: !item.hidden && item.ownerDocument.defaultView.getComputedStyle(item).display !== 'none' }));
"""
ACTIVATE = """
const d = [...Services.wm.getEnumerator('navigator:browser')].map(w => w.document)
  .find(d => d.getElementById('contentAreaContextMenu').state === 'open');
// The drawn one: after a refresh of the menu the engine may keep a hidden copy of an item next to the new one.
// With more than one item of the Shell in the menu, the engine puts them in a submenu named after the Shell (as a
// person sees it): open that submenu first, then click the item. False until the item can be clicked.
const item = [...d.querySelectorAll("#contentAreaContextMenu [id*='-menuitem-_nulavio-svc-']")]
  .find(i => i.getAttribute('label') === arguments[0] && !i.hidden && !i.disabled);
if (!item) return false;
const popup = item.parentNode;
const submenu = popup.parentNode?.localName === 'menu' ? popup.parentNode : null;
if (submenu && popup.state !== 'open') {
  submenu.openMenu(true);
  return false;
}
try {
  popup.activateItem(item);
} catch (e) {
  return false;
}
return true;
"""
CLOSE_MENU = (
    "for (const w of Services.wm.getEnumerator('navigator:browser')) {"
    " const m = w.document.getElementById('contentAreaContextMenu'); if (m.state === 'open') m.hidePopup(); }"
)


def enc(value: str) -> str:
    """As encodeURIComponent."""
    return quote(value, safe="-_.!~*'()")


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class WebServicesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.server = harness.FixtureServer()
        cls.server.__enter__()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.__exit__(None, None, None)
        finally:
            cls.session.cleanup()

    def setUp(self):
        self.addCleanup(
            self.m.chrome,
            "for (const p of ['nulavio.services.translate', 'nulavio.services.translate.language',"
            " 'nulavio.services.private']) Services.prefs.clearUserPref(p);",
        )

    def sv(self, body: str, *args):
        self.m.set_context("chrome")
        try:
            script = "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);" + SV
            return self.m.execute_async(
                script
                + "(async () => {"
                + body
                + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));",
                list(args),
            )
        finally:
            self.m.set_context("content")

    def ok(self, body: str, *args):
        result = self.sv(body, *args)
        self.assertNotIn("error", result, result)
        return result["ok"]

    def error(self, body: str, *args):
        return self.sv(body, *args).get("error")

    def open_menu_on_text(self, path: str = "/service-links", expect: str | None = None) -> list[dict]:
        """The menu on the selected text. With `expect`, the item with that label: the background page draws its
        items a moment after the settings change (one drawing for several changes), so a menu opened before that is
        closed and opened again, a few times."""
        self.m.navigate(self.server.url(path))
        self.m.execute(
            "const p = document.getElementById('text'); const r = document.createRange(); r.selectNodeContents(p);"
            "getSelection().removeAllRanges(); getSelection().addRange(r);"
        )
        self.addCleanup(self.m.chrome, CLOSE_MENU)
        for _ in range(5):
            self.m.context_click("#text")
            self.assertTrue(harness.wait_until(self.m.menu_open, 10))
            harness.wait_until(lambda: self.m.chrome(MENU) is not None, 5)
            if expect is None or harness.wait_until(lambda: any(i["label"] == expect for i in self.m.chrome(MENU) or []), 2):
                break
            self.m.chrome(CLOSE_MENU)
        return self.m.chrome(MENU)

    def open_menu_on_page(self, path: str = "/service-links") -> list[dict]:
        """The page's own menu: nothing selected, the pointer on the page's text (the engine's "page" context
        excludes a selection)."""
        self.m.navigate(self.server.url(path))
        self.m.execute("getSelection().removeAllRanges();")
        self.m.context_click("#text")
        self.assertTrue(harness.wait_until(self.m.menu_open, 10))
        self.addCleanup(self.m.chrome, CLOSE_MENU)
        harness.wait_until(lambda: self.m.chrome(MENU) is not None, 5)
        return self.m.chrome(MENU)

    def activate(self, label: str, reopen) -> None:
        """Click the item with this label in the open menu. The background page draws its items again a moment after
        the settings change; if that happened while the menu was open, the item is gone from it: open it again once."""
        for attempt in (1, 2):
            if harness.wait_until(lambda: self.m.chrome(ACTIVATE, [label]), 5):
                return
            if attempt == 2:
                self.fail(f"{label!r} could not be activated: {self.m.chrome(MENU)}")
            self.m.chrome(CLOSE_MENU)
            reopen()
            ready = lambda: any(i["label"] == label and i["shown"] for i in self.m.chrome(MENU) or [])  # noqa: E731
            self.assertTrue(harness.wait_until(ready, 5), self.m.chrome(MENU))

    def test_01_nothing_is_offered_before_a_service_is_chosen(self):
        state = self.ok("return SV.NulavioServices.state();")
        self.assertEqual((state["translators"], state["privateToo"]), ([], False))
        names = [service["name"] for service in state["known"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(self.open_menu_on_text(), [])

    def test_02_addresses_and_templates_are_checked(self):
        refused = {
            "https://example.org/": None,
            "http://example.org/x": None,
            "https://93.184.216.34/": None,
            "https://[2001:db8::1]/": None,
            "http://localhost:8080/": "private-address",
            "http://app.localhost/": "private-address",
            "http://127.0.0.1/": "private-address",
            "http://10.1.2.3/": "private-address",
            "http://172.20.0.1/": "private-address",
            "http://192.168.1.1/": "private-address",
            "http://169.254.1.1/": "private-address",
            "http://100.64.0.1/": "private-address",
            "http://[::1]/": "private-address",
            "http://[fd00::1]/": "private-address",
            "http://[fe80::1]/": "private-address",
            "http://printer.local/": "private-address",
            "http://intranet/": "private-address",
            "http://nas.home.arpa/": "private-address",
            "http://fritz.box/": "private-address",
            "http://server.localdomain/": "private-address",
            "http://[::127.0.0.1]/": "private-address",
            "http://[::ffff:10.0.0.1]/": "private-address",
            "http://[64:ff9b::a00:1]/": "private-address",
            "http://[2002:a00:1::]/": "private-address",
            "http://192.0.0.8/": "private-address",
            "http://198.18.0.1/": "private-address",
            "http://203.0.113.5/": "private-address",
            "https://user:pass@example.org/": "private-address",
            "file:///etc/passwd": "not-web",
            "about:preferences": "not-web",
            "not an address": "not-web",
        }
        self.assertEqual(self.ok("return args[0].map(u => SV.refusedAddress(u));", list(refused)), list(refused.values()))
        cases = [
            ("https://t.example.org/?q={text}&to={lang}", "selection", None),
            ("https://t.example.org/?q=%s", "selection", None),
            ("https://t.example.org/page?u={url}", "page", None),
            ("http://t.example.org/?q={text}", "selection", "service-needs-https"),
            ("https://u:p@t.example.org/?q={text}", "selection", "credentials-in-url"),
            ("https://t.example.org/?q=", "selection", "missing-text"),
            ("https://t.example.org/?u=", "page", "missing-url"),
            ("https://t.example.org/?q={text}&u={url}", "selection", "bad-placeholder"),
            ("https://t.example.org/?q={text}&x={other}", "selection", "bad-placeholder"),
            ("https://s.example.org/?url={url}", "summary", "invalid-kind"),
            ("https://{url}", "page", "invalid-url"),
            ("https://t.example.org/ {text}", "selection", "invalid-url"),
            ("not a url {text}", "selection", "invalid-url"),
        ]
        for template, kind, code in cases:
            with self.subTest(template=template):
                got = self.error("return SV.validateServiceTemplate(args[0], args[1]);", template, kind)
                self.assertEqual(got, code)
        for bad, code in (("http://lt.example.org/", "service-needs-https"), ("https://lt.example.org/?x=1", "invalid-url")):
            self.assertEqual(self.error("return SV.validateInstance(args[0]);", bad), code)
        self.assertEqual(self.ok("return SV.validateInstance('https://lt.example.org');"), "https://lt.example.org/")

    def test_03_each_service_gets_its_own_address(self):
        text = "Olá & mundo/?#"
        page = "https://example.org/a%20b?x=1#y"
        sent = "https://example.org/a%20b?x=1"  # the fragment never goes to a service
        S = "const S = SV.NulavioServices;"
        for key in ("deepl", "google", "kagi-translate"):
            self.ok(S + "return S.addTranslator({key: args[0]});", key)
        self.ok(S + "return S.addTranslator({key: 'libretranslate', base: 'https://lt.example.org'});")
        self.ok(
            S
            + "return S.addTranslator({key: 'custom', name: 'Meu tradutor', selection: 'https://tr.example.net/?q={text}&to={lang}'});"
        )
        build = S + "return S.build(args[0], {text: args[1], target: args[2]});"
        lang = self.ok("return Services.locale.appLocaleAsBCP47;")
        self.assertEqual(lang, "pt-BR")
        expected = {
            "translate-selection|deepl": f"https://www.deepl.com/translator#xx/pt-BR/{enc(text)}",
            "translate-selection|google": f"https://translate.google.com/?sl=auto&tl=pt&text={enc(text)}&op=translate",
            "translate-page|google": f"https://translate.google.com/translate?sl=auto&tl=pt&u={enc(sent)}",
            "translate-selection|kagi-translate": f"https://translate.kagi.com/?from=auto&to=pt&text={enc(text)}",
            "translate-page|kagi-translate": "https://translate.kagi.com/example.org/a%20b%3Fx=1?to=pt",
            "translate-selection|libretranslate:https://lt.example.org/": f"https://lt.example.org/?source=auto&target=pt#q={enc(text)}",
            "translate-selection|custom:Meu tradutor": f"https://tr.example.net/?q={enc(text)}&to=pt-BR",
        }
        menu = self.ok(S + "return S.menu();")
        self.assertEqual(sorted(item["id"] for item in menu), sorted(expected))
        self.assertEqual(
            {item["id"]: item["name"] for item in menu}["translate-selection|libretranslate:https://lt.example.org/"],
            "LibreTranslate (lt.example.org)",
        )
        for item, address in expected.items():
            with self.subTest(item=item):
                self.assertEqual(self.ok(build, item, text, page), {"open": address})
        # Another target language, chosen in the setting: each service in its own form of it.
        self.ok(S + "return S.setLanguage('en-US');")
        self.assertEqual(
            self.ok(build, "translate-selection|deepl", text, page)["open"],
            f"https://www.deepl.com/translator#xx/en-US/{enc(text)}",
        )
        self.assertEqual(
            self.ok(build, "translate-page|google", text, page)["open"],
            f"https://translate.google.com/translate?sl=auto&tl=en&u={enc(sent)}",
        )
        self.assertEqual(self.error(S + "return S.setLanguage('xx');"), "unknown-language")
        # A page this computer or a local network serves is never handed to a service that fetches it.
        self.assertEqual(self.error(build, "translate-page|google", "", "http://192.168.0.10/doc"), "private-address")
        self.assertEqual(self.error(build, "translate-selection|deepl", "   ", page), "nothing-selected")
        # A hand-edited entry that the module would not have written is dropped, never used.
        self.m.chrome(
            "Services.prefs.setStringPref('nulavio.services.translate', JSON.stringify("
            "[{key: 'custom', name: 'X', selection: 'http://evil.example/?q={text}'}, {key: 'deepl'}]));"
        )
        self.assertEqual([t["id"] for t in self.ok(S + "return S.translators();")], ["deepl"])

    def test_04_a_menu_item_opens_its_address_and_nothing_goes_before_the_click(self):
        self.ok("return SV.NulavioServices.addTranslator({key: 'deepl'});")
        self.ok("return SV.NulavioServices.addTranslator({key: 'google'});")
        self.m.chrome(GUARD_START, [list(WATCHED)])
        self.addCleanup(self.m.chrome, GUARD_STOP)
        tabs = self.m.chrome("return gBrowser.tabs.length;")
        items = self.open_menu_on_text(expect="Traduzir seleção com DeepL")
        by_label = {item["label"]: item for item in items}
        self.assertIn("Traduzir seleção com DeepL", by_label, items)
        self.assertTrue(
            by_label["Traduzir seleção com DeepL"]["shown"] and not by_label["Traduzir seleção com DeepL"]["disabled"]
        )
        self.assertEqual(self.m.chrome(GUARD_SEEN), [], "something left before the click")
        self.activate("Traduzir seleção com DeepL", self.open_menu_on_text)
        want = f"https://www.deepl.com/translator#xx/pt-BR/{enc('Olá & mundo/?#')}"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return gBrowser.tabs.length;") == tabs + 1, 10))
        # Whatever else fails below, the service's tab goes (the next tests read the page's tab).
        self.addCleanup(
            self.m.chrome, "while (gBrowser.tabs.length > arguments[0]) gBrowser.removeTab(gBrowser.tabs.at(-1));", [tabs]
        )
        opened = self.m.chrome("return [gBrowser.selectedBrowser.currentURI.spec, gBrowser.tabs.indexOf(gBrowser.selectedTab)];")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(GUARD_SEEN), 10))
        seen = self.m.chrome(GUARD_SEEN)
        # The request carries what the address does (the text is in the fragment, which a request never carries).
        self.assertEqual([url.split("#")[0] for url in seen], [want.split("#")[0]], seen)
        self.assertIn(opened[0], (want, "about:blank"), opened)
        self.assertEqual(opened[1], 1, "the service's tab opens next to the page's")
        self.m.chrome("gBrowser.removeTab(gBrowser.selectedTab);")
        # The page is on this computer: its translation by address is offered and refused, with the reason in its words.
        self.m.chrome(CLOSE_MENU)
        self.open_menu_on_page()
        refused = "Traduzir página com Google Translate — não para endereços deste computador ou da rede local"
        self.assertTrue(
            harness.wait_until(lambda: any(i["label"] == refused for i in self.m.chrome(MENU) or []), 5), self.m.chrome(MENU)
        )
        self.assertTrue(next(i for i in self.m.chrome(MENU) if i["label"] == refused)["disabled"])
        google = [url for url in self.m.chrome(GUARD_SEEN) if urlsplit(url).hostname == "translate.google.com"]
        self.assertEqual(google, [], "the page went to a service without a click")
        # On a public page the same item is offered and usable: the page's address is the tab's own (the menu's data
        # has none for a page the Shell holds no host permission for). The page itself is not fetched: the request
        # guard cancels it, and the tab keeps its address.
        self.m.chrome(CLOSE_MENU)
        self.m.chrome(
            "gBrowser.selectedBrowser.fixupAndLoadURIString('https://example.org/artigo',"
            " {triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal()});"
        )
        here = "return gBrowser.selectedBrowser.currentURI.spec;"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(here) == "https://example.org/artigo", 10), self.m.chrome(here))
        usable = "Traduzir página com Google Translate"
        shown = self.menu_until(lambda items: any(i["label"] == usable and not i["disabled"] for i in items), on="body")
        self.assertTrue(any(i["label"] == usable and not i["disabled"] for i in shown), shown)

    def menu_until(self, wanted, tries: int = 5, on: str = "#text") -> list[dict]:
        """Open the menu on `on` until what it shows satisfies `wanted` (the background page draws again a moment after
        a setting changes), and return what it showed last."""
        for _ in range(tries):
            self.m.context_click(on)
            self.assertTrue(harness.wait_until(self.m.menu_open, 10))
            if harness.wait_until(lambda: wanted(self.m.chrome(MENU) or []), 2):
                return self.m.chrome(MENU)
            self.m.chrome(CLOSE_MENU)
        return self.m.chrome(MENU) or []

    def private_window(self) -> list[str]:
        """A private window, Marionette switched to it; returns the handles before it."""
        handles = self.m.window_handles()
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: len(self.m.window_handles()) > len(handles), 10))
        self.m.switch_to(next(h for h in self.m.window_handles() if h not in handles))
        return handles

    def test_06_private_windows_offer_them_only_when_allowed(self):
        self.ok("return SV.NulavioServices.addTranslator({key: 'deepl'});")
        label = "Traduzir seleção com DeepL"
        # Drawn first, as a normal window shows: what follows is about private windows, not about a late drawing.
        self.assertIn(label, [i["label"] for i in self.open_menu_on_text(expect=label)])
        self.m.chrome(CLOSE_MENU)
        handles = self.private_window()
        self.addCleanup(self.m.switch_to, handles[0])
        self.addCleanup(self.m.chrome, "window.close();")
        self.open_menu_on_text()
        # Hidden: the engine does not draw an item that is not visible, so none is shown.
        self.assertTrue(
            harness.wait_until(lambda: not any(i["shown"] for i in self.m.chrome(MENU) or []), 5), self.m.chrome(MENU)
        )
        self.m.chrome(CLOSE_MENU)
        self.ok("return SV.NulavioServices.setPrivateToo(true);")
        shown = self.menu_until(lambda items: any(i["label"] == label and i["shown"] and not i["disabled"] for i in items))
        self.assertTrue(any(i["label"] == label and i["shown"] for i in shown), shown)

    def test_06b_an_item_hidden_in_a_private_window_is_back_in_a_normal_one(self):
        """The engine draws no item that is not visible: one hidden in a private window (test 06) is drawn again in a
        normal window's menu."""
        self.ok("return SV.NulavioServices.addTranslator({key: 'deepl'});")
        label = "Traduzir seleção com DeepL"
        self.assertIn(label, [i["label"] for i in self.open_menu_on_text(expect=label)])
        self.m.chrome(CLOSE_MENU)
        handles = self.private_window()
        self.open_menu_on_text()
        self.assertTrue(harness.wait_until(lambda: not any(i["shown"] for i in self.m.chrome(MENU) or []), 5))
        self.m.chrome(CLOSE_MENU)
        self.m.chrome("window.close();")
        self.m.switch_to(handles[0])
        self.open_menu_on_text()
        shown = lambda: any(i["label"] == label and i["shown"] for i in self.m.chrome(MENU) or [])  # noqa: E731
        self.assertTrue(harness.wait_until(shown, 5), self.m.chrome(MENU))

    def test_07_the_settings_page_adds_and_removes(self):
        DOC = "const d = gBrowser.selectedBrowser.contentDocument;"
        self.m.navigate("about:preferences#languages")
        rows = DOC + (
            "if (!d) return null; const g = d.getElementById(arguments[0]);"
            "if (!g || !g.getBoundingClientRect().height) return null;"
            "return [...g.querySelectorAll('moz-box-item')].map(r => [r.dataset.service ?? null, r.label]);"
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(rows, ["nulavio-translate-known"]), 20))
        known = self.m.chrome(rows, ["nulavio-translate-known"])
        self.assertEqual([name for _, name in known], sorted(name for _, name in known))
        self.assertEqual(
            self.m.chrome(rows, ["nulavio-translate-added"]),
            [[None, "Nenhum serviço na web: a tradução fica no seu computador."]],
        )
        click = DOC + "const el = d.querySelector(arguments[0]); if (!el) return false; el.click(); return true;"
        self.assertTrue(self.m.chrome(click, ['#nulavio-translate-known moz-button[data-service="google"]']))
        self.assertTrue(
            harness.wait_until(
                lambda: ["google", "Google Translate"] in (self.m.chrome(rows, ["nulavio-translate-added"]) or []), 10
            )
        )
        self.assertEqual([t["id"] for t in self.ok("return SV.NulavioServices.translators();")], ["google"])
        self.assertTrue(self.m.chrome(click, ['#nulavio-translate-added moz-button[data-service="google"]']))
        self.assertTrue(harness.wait_until(lambda: self.ok("return SV.NulavioServices.translators();") == [], 10))


@unittest.skipUnless(
    harness.nulavio_engine() and os.environ.get("NULAVIO_NETWORK_TESTS") == "1",
    "on-device translation downloads its models from Mozilla's servers (NULAVIO_NETWORK_TESTS=1)",
)
class OnDeviceTranslationTest(unittest.TestCase):
    """#156: the engine's own translation, on the device, works on the Nulavio build, English to Portuguese and back,
    and what it downloads comes from the hosts docs/security/new-profile-connections.md lists."""

    def test_01_english_to_portuguese_and_back(self):
        session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(session.cleanup)
        m = session.start()
        server = harness.FixtureServer()
        server.__enter__()
        self.addCleanup(server.__exit__, None, None, None)
        m.chrome(
            "window.nulavioHosts = new Set(); Services.obs.addObserver({ observe(s) {"
            " try { window.nulavioHosts.add(s.QueryInterface(Ci.nsIChannel).URI.host); } catch (e) {} } },"
            " 'http-on-modify-request');"
        )
        m.navigate(server.url("/english-page"))
        before = m.execute("return document.getElementById('text').textContent;")
        translate = (
            "gBrowser.selectedBrowser.browsingContext.currentWindowGlobal.getActor('Translations')"
            ".translate({sourceLanguage: arguments[0], targetLanguage: arguments[1]}, false); return true;"
        )
        m.chrome(translate, ["en", "pt"])
        changed = harness.wait_until(lambda: m.execute("return document.getElementById('text').textContent;") != before, 240)
        self.assertTrue(changed, "the page was not translated")
        print("pt:", m.execute("return document.getElementById('text').textContent;"))
        hosts = set(m.chrome("return [...window.nulavioHosts];")) - {"127.0.0.1", "localhost"}
        # The models come from Remote Settings; the engine's other background traffic of the same minutes (the
        # content filter's lists, for one) is on the documented list too. Nothing else may appear.
        doc = Path(__file__).resolve().parents[2] / "docs" / "security" / "new-profile-connections.json"
        listed = {host for c in json.loads(doc.read_text(encoding="utf-8"))["connections"] for host in c["hosts"]}
        self.assertIn("firefox-settings-attachments.cdn.mozilla.net", hosts, "the models did not come from Remote Settings")
        self.assertLessEqual(hosts, listed, hosts - listed)


if __name__ == "__main__":
    unittest.main()
