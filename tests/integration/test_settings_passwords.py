"""ADR 0011: who saves and fills passwords, and the look-alike sites the person confirmed, in the settings page.

The lists are registry lists like the others; choosing a manager goes through NulavioPasswords.choose, which
pins and checks the extension it installs. No extension is installed by these tests: the test gives the module
the state to show and records what the page asks it to do. The confirmed sites use the module as it is.
"""

from __future__ import annotations

import unittest

import harness
from marionette import MarionetteError

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
W = 'const W = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPasswords.sys.mjs").NulavioPasswords;'
# A profile with the browser's manager in use, one manager not installed and one installed but off.
STATE = (
    W
    + """
window.__state = { current: "builtin", engineLogins: 2, providers: [
  { key: "builtin", extension: null, native: null },
  { key: "proton-pass", native: null,
    extension: { name: "Proton Pass", pinned: "1.41.1", installed: false, enabled: false, version: null } },
  { key: "keepassxc", native: { required: true, found: false },
    extension: { name: "KeePassXC-Browser", pinned: "1.10.4.1", installed: true, enabled: false, version: "1.10.4.1" } },
] };
window.__calls = [];
W.state = async () => structuredClone(window.__state);
W.choose = async key => {
  window.__calls.push(key);
  for (const item of window.__state.providers) {
    if (!item.extension) continue;
    const chosen = { installed: true, enabled: true, version: item.extension.pinned };
    Object.assign(item.extension, item.key === key ? chosen : { enabled: false });
  }
  window.__state.current = key;
};
"""
)
PAGE = (
    DOC
    + """
const shown = el => !!el && !el.closest("setting-control")?.hidden && el.getBoundingClientRect().height > 0;
const el = id => d.getElementById(id);
const bar = id => (shown(el(id)) ? el(id).message : null);
const rows = (id, cls) => (shown(el(id)) ? [...el(id).querySelectorAll(`moz-box-item.${cls}`)] : []);
return {
  now: rows("nulavio-passwords-providers", "nulavio-provider").filter(row => row.dataset.inUse === "true")
    .map(row => row.label).join(),
  none: shown(el("nulavio-passwords-now")),
  providers: rows("nulavio-passwords-providers", "nulavio-provider").map(row => ({
    key: row.dataset.provider, name: row.label, status: row.description,
    buttons: [...row.querySelectorAll("moz-button")].map(b => [b.dataset.action, b.label, b.ariaLabel]),
  })),
  logins: shown(el("nulavio-passwords-logins")) ? el("nulavio-passwords-logins").label : null,
  said: bar("nulavio-passwords-said"), error: bar("nulavio-passwords-error"),
  confirmed: rows("nulavio-confirmed-sites", "nulavio-confirmed").map(row => [row.label, row.description,
    row.querySelector("moz-button")?.ariaLabel ?? null]),
  noConfirmed: el("nulavio-confirmed-sites")?.querySelector("moz-box-item.nulavio-confirmed-none")?.label ?? null,
  confirmedSaid: bar("nulavio-confirmed-said"),
  focus: d.activeElement?.dataset?.action ?? null,
};
"""
)
CLICK = (
    DOC
    + """
const [list, key, action] = arguments;
const button = [...d.querySelectorAll(`#${list} moz-button[data-action="${action}"]`)]
  .find(b => (b.dataset.provider ?? b.dataset.site) === key);
if (!button) return false;
button.click();
return true;
"""
)


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsPasswordsTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def open(self) -> None:
        self.m.navigate("about:preferences#passwordsAutofill")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))

    def seen(self, wanted, timeout: float = 15) -> dict:
        harness.wait_until(lambda: wanted(self.m.chrome(PAGE)), timeout)
        now = self.m.chrome(PAGE)
        self.assertTrue(wanted(now), now)
        return now

    def alert_text(self):
        try:
            return self.m.send("WebDriver:GetAlertText")["value"]
        except MarionetteError:
            return None

    def test_01_choosing_a_manager_says_what_it_installs_and_goes_through_the_module(self):
        self.m.chrome(STATE)
        self.addCleanup(self.m.chrome, W + "delete W.state; delete W.choose;")
        self.open()
        now = self.seen(lambda n: len(n["providers"]) == 3)
        rows = {row["key"]: row for row in now["providers"]}
        self.assertEqual(now["now"], "O gerenciador de senhas do navegador (em uso)")
        self.assertFalse(now["none"])
        self.assertEqual(rows["builtin"]["name"], "O gerenciador de senhas do navegador (em uso)")
        self.assertEqual(rows["builtin"]["buttons"], [])
        self.assertEqual(rows["proton-pass"]["buttons"], [["use", "Usar este", "Usar este: Proton Pass"]])
        self.assertIn("Não instalada. Ao escolher, o Nulavio instala a extensão oficial (1.41.1", rows["proton-pass"]["status"])
        self.assertIn("instalada, mas desligada", rows["keepassxc"]["status"])
        self.assertIn("O app KeePassXC não foi encontrado", rows["keepassxc"]["status"])
        self.assertEqual(now["logins"], "O navegador guarda 2 logins neste perfil. Eles são mantidos quando você troca.")

        # A manager that is not installed: the page says what will be installed and from where, before anything.
        self.assertTrue(self.m.chrome(CLICK, ["nulavio-passwords-providers", "proton-pass", "use"]))
        body = harness.wait_until(self.alert_text, 10)
        self.assertIn(
            "instala a extensão oficial Proton Pass, versão 1.41.1, do addons.mozilla.org", body or "no confirmation shown"
        )
        self.m.send("WebDriver:DismissAlert")
        self.assertEqual(self.m.chrome("return window.__calls;"), [])
        self.m.chrome(CLICK, ["nulavio-passwords-providers", "proton-pass", "use"])
        self.assertTrue(harness.wait_until(self.alert_text, 10))
        self.m.send("WebDriver:AcceptAlert")
        chosen = self.seen(lambda n: n["said"] and n["now"] == "Proton Pass (em uso)")
        self.assertEqual(chosen["said"], "Proton Pass agora salva e preenche senhas neste perfil.")
        self.assertEqual(self.m.chrome("return window.__calls;"), ["proton-pass"])
        rows = {row["key"]: row for row in chosen["providers"]}
        self.assertEqual(rows["proton-pass"]["name"], "Proton Pass (em uso)")
        self.assertEqual(rows["proton-pass"]["buttons"][0][:2], ["off", "Desativar integração"])
        self.assertEqual(rows["builtin"]["buttons"][0][:2], ["use", "Usar este"])

        # One that is installed is chosen with no question; giving the job back to the browser asks first.
        self.m.chrome(CLICK, ["nulavio-passwords-providers", "keepassxc", "use"])
        self.seen(lambda n: n["now"] == "KeePassXC-Browser (em uso)")
        self.assertIsNone(self.alert_text())
        self.m.chrome(CLICK, ["nulavio-passwords-providers", "keepassxc", "off"])
        body = harness.wait_until(self.alert_text, 10)
        self.assertIn("O KeePassXC-Browser não é removido e o cofre dele não é tocado", body or "no confirmation shown")
        self.m.send("WebDriver:AcceptAlert")
        back = self.seen(lambda n: n["now"] == "O gerenciador de senhas do navegador (em uso)")
        self.assertEqual(back["said"], "O gerenciador de senhas do navegador agora salva e preenche senhas neste perfil.")
        self.assertEqual(self.m.chrome("return window.__calls;"), ["proton-pass", "keepassxc", "builtin"])

        # A refusal from the module is said in the Shell's words.
        self.m.chrome(W + 'W.choose = async () => { throw Object.assign(new Error("x"), { code: "install-failed" }); };')
        self.m.chrome(CLICK, ["nulavio-passwords-providers", "keepassxc", "use"])
        failed = self.seen(lambda n: n["error"])
        self.assertIn("A extensão não pôde ser instalada", failed["error"])
        self.assertEqual(failed["now"], "O gerenciador de senhas do navegador (em uso)")

    def test_02_a_confirmed_look_alike_is_removed_and_the_warning_returns(self):
        self.m.chrome(
            W + 'W.dismiss("banco-seguro.example", "banco.example"); W.dismiss("loja-oficial.example", "loja.example");'
        )
        self.open()
        now = self.seen(lambda n: len(n["confirmed"]) == 2)
        self.assertEqual(
            now["confirmed"],
            [
                ["loja-oficial.example", "Parecido com loja.example", "Remover loja-oficial.example"],
                ["banco-seguro.example", "Parecido com banco.example", "Remover banco-seguro.example"],
            ],
        )
        self.assertTrue(self.m.chrome(CLICK, ["nulavio-confirmed-sites", "loja-oficial.example", "remove"]))
        left = self.seen(lambda n: n["confirmedSaid"] and len(n["confirmed"]) == 1)
        self.assertEqual(left["confirmedSaid"], "Removido. O Nulavio volta a avisar em loja-oficial.example.")
        self.assertEqual(
            self.m.chrome(W + "return W.listConfirmed();"), [{"site": "banco-seguro.example", "similar": "banco.example"}]
        )
        self.assertEqual(self.seen(lambda n: n["focus"] == "remove")["focus"], "remove")
        self.m.chrome(CLICK, ["nulavio-confirmed-sites", "banco-seguro.example", "remove"])
        empty = self.seen(lambda n: n["noConfirmed"] and not n["confirmed"])
        self.assertEqual(empty["noConfirmed"], "Nenhum site confirmado.")
        self.assertEqual(self.m.chrome(W + "return W.listConfirmed();"), [])


if __name__ == "__main__":
    unittest.main()
