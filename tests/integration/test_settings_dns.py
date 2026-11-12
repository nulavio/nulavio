"""ADR 0011: who answers when this profile looks up a site (DNS), inside the engine's own DNS group.

Three choices in plain words where the engine showed a one-line summary; the engine's advanced screen stays
behind its button. Nothing is written before "Salvar escolha"; NulavioPrivacy.setDns checks the choice. The
tests act on the page and read the engine's own prefs.
"""

from __future__ import annotations

import unittest

import harness

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
PREFS = """
return { mode: Services.prefs.getIntPref("network.trr.mode", 0), uri: Services.prefs.getStringPref("network.trr.uri", ""),
         chosen: Services.prefs.getBoolPref("nulavio.dns.chosen", false) };
"""
PAGE = (
    DOC
    + """
const shown = el => !!el && !el.closest("setting-control")?.hidden && el.getBoundingClientRect().height > 0;
const el = id => d.getElementById(id);
const bar = id => (shown(el(id)) ? el(id).message : null);
const choice = el("nulavio-dns-choice");
if (!shown(choice)) return null;
return {
  heading: choice.closest("setting-group")?.querySelector("moz-fieldset")?.label ?? null,
  says: choice.description, value: choice.value,
  options: [...choice.querySelectorAll("moz-radio")].map(o => [o.value, o.label]),
  provider: shown(el("nulavio-dns-provider")) ? el("nulavio-dns-provider").value : null,
  providers: shown(el("nulavio-dns-provider"))
    ? [...el("nulavio-dns-provider").querySelectorAll("moz-option")].map(o => o.value) : null,
  warns: shown(el("nulavio-dns-provider")) ? el("nulavio-dns-provider").description : null,
  uri: shown(el("nulavio-dns-uri")) ? el("nulavio-dns-uri").value : null,
  save: shown(el("nulavio-dns-save")) ? !el("nulavio-dns-save").disabled : null,
  said: bar("nulavio-dns-said"), error: bar("nulavio-dns-error"),
  // The engine's own part of the group: its summary line gave way, its advanced button stays.
  engine: { summary: shown(el("dohModeBoxItem")), advanced: shown(el("dohAdvancedButton")) },
};
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
QUAD9 = "https://dns.quad9.net/dns-query"


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsDnsTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def open(self) -> dict:
        self.m.navigate("about:preferences#privacy")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        return self.seen(lambda now: now["options"])

    def seen(self, wanted, timeout: float = 15) -> dict:
        harness.wait_until(lambda: (now := self.m.chrome(PAGE)) is not None and wanted(now), timeout)
        now = self.m.chrome(PAGE)
        self.assertIsNotNone(now, "the DNS choices are not on the page")
        self.assertTrue(wanted(now), now)
        return now

    def prefs(self) -> dict:
        return self.m.chrome(PREFS)

    def choose(self, value: str) -> None:
        pick = (
            DOC
            + """
          const radio = [...d.querySelectorAll("#nulavio-dns-choice moz-radio")].find(r => r.value === arguments[0]);
          if (!radio) return false;
          radio.click();
          return true;
        """
        )
        self.assertTrue(self.m.chrome(pick, [value]), value)

    def test_01_nothing_is_written_before_the_choice_is_saved(self):
        now = self.open()
        before = self.prefs()
        self.assertEqual((before["mode"], before["chosen"]), (0, False))
        self.assertEqual(now["heading"], "DNS: quem responde quando você procura um site")
        # Nothing chosen yet: the browser's default is listed, marked, and says what it does right now.
        self.assertEqual([option[0] for option in now["options"]], ["default", "system", "fallback", "strict"])
        self.assertEqual(now["value"], "default")
        self.assertIn("Agora: o padrão do navegador", now["says"])
        self.assertFalse(now["save"], "there is nothing to save yet")
        self.assertEqual(now["engine"], {"summary": False, "advanced": True})
        self.assertEqual(now["options"][1][1], "A sua rede responde")
        # A choice in the form is not a choice in effect: the prefs stay until it is saved.
        self.choose("system")
        picked = self.seen(lambda n: n["value"] == "system" and n["save"])
        self.assertIsNone(picked["provider"])
        self.assertEqual(self.prefs(), before)
        self.m.chrome(CLICK, ["#nulavio-dns-save"])
        saved = self.seen(lambda n: n["said"])
        self.assertEqual(saved["said"], "DNS alterado neste perfil.")
        self.assertEqual(saved["says"], "Agora: o resolvedor do computador.")
        self.assertEqual((self.prefs()["mode"], self.prefs()["chosen"]), (5, True))
        # Once something was chosen, "the browser's default" is no longer offered, and there is nothing to save.
        self.assertEqual([option[0] for option in saved["options"]], ["system", "fallback", "strict"])
        self.assertFalse(saved["save"])

    def test_02_an_encrypted_service_is_named_and_a_bad_address_is_refused(self):
        self.open()
        self.choose("fallback")
        now = self.seen(lambda n: n["provider"])
        self.assertEqual(now["providers"], ["cloudflare", "quad9", "mullvad", "custom"])
        self.assertIn("vê quais sites você procura", now["warns"])
        self.assertIsNone(now["uri"])
        self.m.chrome(CHANGE, ["nulavio-dns-provider", "quad9"])
        self.seen(lambda n: n["provider"] == "quad9" and n["save"])
        self.m.chrome(CLICK, ["#nulavio-dns-save"])
        saved = self.seen(lambda n: n["said"])
        self.assertEqual(saved["says"], "Agora: DNS criptografado pelo Quad9, com o resolvedor do computador como reserva.")
        self.assertEqual((self.prefs()["mode"], self.prefs()["uri"]), (2, QUAD9))
        # Only encrypted DNS, at an address of the person's own: one that is not https is refused, in words.
        self.choose("strict")
        self.m.chrome(CHANGE, ["nulavio-dns-provider", "custom"])
        self.seen(lambda n: n["uri"] is not None)
        self.m.chrome(CHANGE, ["nulavio-dns-uri", "http://dns.example/dns-query"])
        self.seen(lambda n: n["save"])
        self.m.chrome(CLICK, ["#nulavio-dns-save"])
        refused = self.seen(lambda n: n["error"])
        self.assertIn("precisa começar com https://", refused["error"])
        self.assertEqual((self.prefs()["mode"], self.prefs()["uri"]), (2, QUAD9), "a refused choice changed something")
        self.assertEqual(refused["uri"], "http://dns.example/dns-query")
        self.m.chrome(CHANGE, ["nulavio-dns-uri", "https://dns.example/dns-query"])
        self.m.chrome(CLICK, ["#nulavio-dns-save"])
        strict = self.seen(lambda n: n["said"] and "somente" in n["says"])
        self.assertEqual(strict["says"], "Agora: somente DNS criptografado, pelo https://dns.example/dns-query.")
        self.assertEqual((self.prefs()["mode"], self.prefs()["uri"]), (3, "https://dns.example/dns-query"))
        # Changed on the engine's own advanced screen (its prefs): this form follows what is in effect.
        self.m.chrome('Services.prefs.setIntPref("network.trr.mode", 5);')
        followed = self.seen(lambda n: n["value"] == "system")
        self.assertEqual(followed["says"], "Agora: o resolvedor do computador.")
        self.assertFalse(followed["save"])


if __name__ == "__main__":
    unittest.main()
