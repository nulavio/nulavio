"""ADR 0011: the sites where a protection is off or relaxed, inside the engine's settings page.

The list is read by NulavioPrivacy from the engine's own permission store; removing a row removes the
permission, so the protection applies to that site again. The tests add and read permissions through the
engine's permission manager and act on the page as a person does.
"""

from __future__ import annotations

import unittest

import harness
from marionette import MarionetteError

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
N = 'const N = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs").NulavioPrivacy;'
ALLOW = """
const [origin, type, capability, session] = arguments;
const principal = Services.scriptSecurityManager.createContentPrincipalFromOrigin(origin);
const expire = session ? Ci.nsIPermissionManager.EXPIRE_SESSION : Ci.nsIPermissionManager.EXPIRE_NEVER;
Services.perms.addFromPrincipal(principal, type, capability, expire);
"""
HAS = """
const principal = Services.scriptSecurityManager.createContentPrincipalFromOrigin(arguments[0]);
return Services.perms.testExactPermissionFromPrincipal(principal, arguments[1]);
"""
LIST = (
    DOC
    + """
const list = d.getElementById("nulavio-exceptions");
if (!list || list.closest("setting-control")?.hidden) return null;
const shown = el => !!el && !el.closest("setting-control")?.hidden && el.getBoundingClientRect().height > 0;
const bar = id => (shown(d.getElementById(id)) ? d.getElementById(id).message : null);
const door = d.getElementById("nulavio-filter-trusted");
return {
  rows: [...list.querySelectorAll("moz-box-item.nulavio-exception")].map(row => ({
    site: row.label, what: row.description, type: row.dataset.type, origin: row.dataset.origin,
    remove: row.querySelector('moz-button[data-action="remove"]')?.ariaLabel ?? null,
  })),
  none: list.querySelector("moz-box-item.nulavio-exception-none")?.label ?? null,
  said: bar("nulavio-exceptions-said"), error: bar("nulavio-exceptions-error"),
  door: shown(door) ? [door.label, door.description] : null,
  focus: [d.activeElement?.dataset?.action ?? null, d.activeElement?.dataset?.origin ?? null],
};
"""
)
REMOVE = (
    DOC
    + """
const [type, origin] = arguments;
const button = [...d.querySelectorAll('#nulavio-exceptions moz-button[data-action="remove"]')]
  .find(b => b.dataset.type === type && b.dataset.origin === origin);
if (!button) return false;
button.click();
return true;
"""
)
ALLOW_ACTION, DENY_ACTION = 1, 2


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsExceptionsTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def open(self) -> dict:
        self.m.navigate("about:preferences#privacy")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        return self.seen(lambda now: now["rows"] or now["none"])

    def seen(self, wanted, timeout: float = 15) -> dict:
        harness.wait_until(lambda: (now := self.m.chrome(LIST)) is not None and wanted(now), timeout)
        now = self.m.chrome(LIST)
        self.assertIsNotNone(now, "the list of exceptions is not on the page")
        self.assertTrue(wanted(now), now)
        return now

    def alert_text(self):
        try:
            return self.m.send("WebDriver:GetAlertText")["value"]
        except MarionetteError:
            return None

    def test_01_an_exception_is_listed_in_words_and_removing_it_puts_the_protection_back(self):
        first = self.open()
        mine = lambda now: [row for row in now["rows"] if row["origin"].endswith(".example")]  # noqa: E731
        self.assertEqual(mine(first), [])
        # Two the person made (from a site's own panel, as the engine stores them), one only until the browser closes.
        self.m.chrome(ALLOW, ["https://loja.example", "cookie", ALLOW_ACTION, False])
        self.m.chrome(ALLOW, ["http://antigo.example", "https-only-load-insecure", ALLOW_ACTION, True])
        two = self.seen(lambda now: len(mine(now)) == 2)
        rows = {row["site"]: row for row in mine(two)}
        self.assertEqual(rows["loja.example"]["what"], "Cookies sempre permitidos")
        self.assertEqual(rows["antigo.example"]["what"], "Modo somente HTTPS desligado · até você fechar o navegador")
        self.assertEqual(rows["loja.example"]["remove"], "Remover: loja.example — Cookies sempre permitidos")
        self.assertIsNone(two["none"])
        # Removing one: the engine no longer has it, the page says so, and the keyboard is not lost with the row.
        self.assertTrue(self.m.chrome(REMOVE, ["cookie", "https://loja.example"]))
        left = self.seen(lambda now: now["said"] and len(mine(now)) == 1)
        self.assertEqual(left["said"], "Removido.")
        self.assertEqual(self.m.chrome(HAS, ["https://loja.example", "cookie"]), 0)
        self.assertEqual(self.m.chrome(HAS, ["http://antigo.example", "https-only-load-insecure"]), ALLOW_ACTION)
        self.assertEqual(self.seen(lambda now: now["focus"][0] == "remove")["focus"][0], "remove")
        # One that is gone before the click lands: said in words, nothing else touched.
        gone = 'N.remove = () => { throw Object.assign(new Error("x"), { code: "not-found" }); };'
        self.m.chrome(N + gone)
        self.addCleanup(self.m.chrome, N + "delete N.remove;")
        self.m.chrome(REMOVE, ["https-only-load-insecure", "http://antigo.example"])
        self.assertEqual(self.seen(lambda now: now["error"])["error"], "Não encontrado. A lista foi atualizada.")
        self.m.chrome(N + "delete N.remove;")
        self.m.chrome(REMOVE, ["https-only-load-insecure", "http://antigo.example"])
        self.seen(lambda now: not mine(now))

    def test_02_a_browser_default_asks_first_and_none_left_says_so(self):
        now = self.open()
        built_in = [row for row in now["rows"] if "Padrão do navegador" in row["what"]]
        if built_in:
            row = built_in[0]
            self.assertTrue(self.m.chrome(REMOVE, [row["type"], row["origin"]]))
            body = harness.wait_until(self.alert_text, 10)
            self.assertIn("O navegador mantém esta exceção", body or "no confirmation was shown")
            self.assertIn(row["site"], body)
            # Closing the prompt keeps the default.
            self.m.send("WebDriver:DismissAlert")
            self.assertTrue(any(r["origin"] == row["origin"] and r["type"] == row["type"] for r in self.m.chrome(LIST)["rows"]))
            self.assertIsNone(self.m.chrome(LIST)["said"])
            self.assertTrue(self.m.chrome(REMOVE, [row["type"], row["origin"]]))
            self.assertTrue(harness.wait_until(self.alert_text, 10))
            self.m.send("WebDriver:AcceptAlert")
            same = lambda r: r["origin"] == row["origin"] and r["type"] == row["type"]  # noqa: E731
            self.seen(lambda n: n["said"] == "Removido." and not any(same(r) for r in n["rows"]))
        # With every exception removed, the list says that every protection applies everywhere.
        self.m.chrome(
            N + "return N.exceptions().then(list => { for (const e of list) N.remove(e.type, e.origin); return true; });"
        )
        empty = self.seen(lambda n: n["none"])
        self.assertEqual(empty["none"], "Nenhuma exceção: todas as proteções valem para todos os sites.")
        self.assertEqual(empty["rows"], [])


if __name__ == "__main__":
    unittest.main()
