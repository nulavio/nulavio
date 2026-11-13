"""ADR 0011: which site opens in which profile, inside the engine's settings page.

The rules are a list of the page's own registry, like the profiles above them; every change goes through
NulavioRouting, which checks each rule as it always did. The tests act as a person does and read the result
from the module.
"""

from __future__ import annotations

import unittest

import harness

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
MODULES = "resource://builtin-addons/nulavio-shell/modules/"
P = f'const P = ChromeUtils.importESModule("{MODULES}NulavioProfiles.sys.mjs").NulavioProfiles;'
R = f'const R = ChromeUtils.importESModule("{MODULES}NulavioRouting.sys.mjs").NulavioRouting;'
IDS = P + "return P.list().then(list => Object.fromEntries(list.profiles.map(p => [p.name, p.id])));"
STATE = R + "return R.state().then(s => ({ enabled: s.enabled, inPage: s.inPage, fallback: s.fallback, rules: s.rules }));"
# The group as the person sees it.
GROUP = (
    DOC
    + """
const group = d.querySelector('setting-group[groupid="nulavioRouting"]');
if (!group) return null;
const shown = el => !!el && !el.closest("setting-control")?.hidden && el.getBoundingClientRect().height > 0;
const el = id => d.getElementById(id);
const bar = id => (shown(el(id)) ? el(id).message : null);
const field = id => (shown(el(id))
  ? { value: el(id).value ?? null, pressed: el(id).pressed ?? null, disabled: Boolean(el(id).disabled) } : null);
const list = el("nulavio-routing-rules");
return {
  rows: shown(list) ? [...list.querySelectorAll("moz-box-item[data-rule]")].map(row => ({
    site: row.label, does: row.description, icon: row.iconSrc ?? null,
    remove: row.querySelector('moz-button[data-action="remove"]')?.ariaLabel ?? null,
  })) : null,
  none: shown(list) ? (list.querySelector("moz-box-item.nulavio-rule-none")?.label ?? null) : null,
  enabled: field("nulavio-routing-enabled"), inPage: field("nulavio-routing-in-page"),
  fallback: field("nulavio-routing-fallback"),
  choices: shown(el("nulavio-routing-fallback"))
    ? [...el("nulavio-routing-fallback").querySelectorAll("moz-option")].map(o => [o.value, o.label, Boolean(o.disabled)]) : null,
  fresh: { site: field("nulavio-routing-site")?.value ?? null, match: field("nulavio-routing-match")?.value ?? null,
           action: field("nulavio-routing-action")?.value ?? null, profile: field("nulavio-routing-profile")?.value ?? null },
  add: shown(el("nulavio-routing-add")),
  alone: bar("nulavio-routing-alone"), missing: bar("nulavio-routing-fallback-missing"),
  error: bar("nulavio-routing-error"), said: bar("nulavio-routing-said"),
  focus: d.activeElement?.id || null,
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


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsRoutingTest(unittest.TestCase):
    profiles = ("Trabalho", "Bancos")

    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()
        for template, name in zip(("work", "banking"), self.profiles, strict=False):
            self.m.chrome(
                P + "return P.create({ templateId: arguments[0], name: arguments[1] }).then(() => true);", [template, name]
            )
        self.ids = self.m.chrome(IDS)

    def open(self) -> dict:
        self.m.navigate("about:preferences#nulavioProfiles")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        return self.seen(lambda now: now["enabled"] is not None)

    def seen(self, wanted, timeout: float = 15) -> dict:
        harness.wait_until(lambda: (now := self.m.chrome(GROUP)) is not None and wanted(now), timeout)
        now = self.m.chrome(GROUP)
        self.assertIsNotNone(now, "the routing group is not on the page")
        self.assertTrue(wanted(now), now)
        return now

    def state(self) -> dict:
        return self.m.chrome(STATE)

    def test_01_a_rule_is_added_and_removed_through_the_module(self):
        now = self.open()
        self.assertEqual(now["rows"], [])
        self.assertIn("Nenhuma regra ainda", now["none"])
        self.assertEqual(now["fresh"], {"site": "", "match": "domain", "action": "open-in", "profile": str(self.ids["Pessoal"])})
        # Something that is not a site: said in words, nothing written, what was typed stays.
        self.m.chrome(CHANGE, ["nulavio-routing-site", "not a site !"])
        self.m.chrome(CLICK, ["#nulavio-routing-add"])
        refused = self.seen(lambda n: n["error"])
        self.assertEqual(refused["error"], "Esse endereço de site não é válido.")
        self.assertEqual(refused["fresh"]["site"], "not a site !")
        self.assertEqual(self.state()["rules"], [])
        # A domain that opens in Bancos.
        self.m.chrome(CHANGE, ["nulavio-routing-site", "https://www.Banco.example/login"])
        self.m.chrome(CHANGE, ["nulavio-routing-profile", str(self.ids["Bancos"])])
        self.m.chrome(CLICK, ["#nulavio-routing-add"])
        added = self.seen(lambda n: n["said"] and n["rows"])
        self.assertEqual(added["said"], "Adicionado.")
        self.assertEqual(added["fresh"]["site"], "")
        rules = self.state()["rules"]
        self.assertEqual([(r["match"], r["action"], r["profileId"]) for r in rules], [("domain", "open-in", self.ids["Bancos"])])
        row = added["rows"][0]
        self.assertEqual(row["site"], f"{rules[0]['display']} (todo o domínio)")
        self.assertEqual(row["does"], "Bancos · Abrir nele")
        self.assertEqual(row["icon"], "chrome://browser/content/profiles/assets/16_diamond.svg")  # the target profile's icon
        self.assertEqual(row["remove"], f"Remover {rules[0]['display']}")
        # "Never switch" names no profile: the choice leaves the form, and the rule has none.
        self.m.chrome(CHANGE, ["nulavio-routing-site", "intranet.example"])
        self.m.chrome(CHANGE, ["nulavio-routing-match", "host"])
        self.m.chrome(CHANGE, ["nulavio-routing-action", "stay"])
        self.assertIsNone(self.seen(lambda n: n["fresh"]["action"] == "stay")["fresh"]["profile"])
        self.m.chrome(CLICK, ["#nulavio-routing-add"])
        two = self.seen(lambda n: len(n["rows"] or []) == 2)
        stay = next(r for r in self.state()["rules"] if r["action"] == "stay")
        self.assertEqual((stay["match"], stay["profileId"]), ("host", None))
        self.assertEqual([r["does"] for r in two["rows"]], ["Bancos · Abrir nele", "Nunca trocar de perfil"])
        self.assertEqual(two["rows"][1]["site"], "intranet.example")
        # A rule made elsewhere (the profile menu, another window) joins the list without a reload.
        self.m.chrome(
            R
            + 'return R.addRule({ site: "docs.example.org", match: "host", action: "ask", profileId: arguments[0] })'
            + ".then(() => true);",
            [self.ids["Trabalho"]],
        )
        three = self.seen(lambda n: len(n["rows"] or []) == 3)
        self.assertIn("Trabalho · Perguntar antes", [r["does"] for r in three["rows"]])
        # Removing one: gone from the module, said, and the keyboard is not lost with the row.
        self.m.chrome(CLICK, ['#nulavio-routing-rules moz-box-item[data-rule] moz-button[data-action="remove"]'])
        left = self.seen(lambda n: n["said"] == "Removido." and len(n["rows"] or []) == 2)
        self.assertEqual(len(self.state()["rules"]), 2)
        self.assertNotIn("Bancos · Abrir nele", [r["does"] for r in left["rows"]])
        self.assertEqual(self.seen(lambda n: n["focus"] == "nulavio-routing-site")["focus"], "nulavio-routing-site")
        # A rule whose profile was deleted says so.
        self.m.chrome(P + "return P.remove(arguments[0]).then(() => true);", [self.ids["Trabalho"]])
        orphan = self.seen(lambda n: "O perfil desta regra não existe mais" in [r["does"] for r in n["rows"] or []])
        self.assertIsNone(next(r for r in orphan["rows"] if r["does"].startswith("O perfil desta regra"))["icon"])

    def test_02_the_switches_and_the_default_destination(self):
        now = self.open()
        before = self.state()
        self.assertEqual(now["enabled"]["pressed"], before["enabled"])
        self.assertEqual(now["inPage"]["pressed"], before["inPage"])
        self.assertFalse(before["inPage"], "links clicked in pages follow the rules only when the person turns that on")
        # Off: the rules are not used, and what depends on them cannot be changed.
        self.assertTrue(before["enabled"])
        self.m.chrome(CLICK, ["#nulavio-routing-enabled"])
        off = self.seen(lambda n: n["enabled"]["pressed"] is False and n["inPage"]["disabled"])
        self.assertFalse(self.state()["enabled"])
        self.assertTrue(off["fallback"]["disabled"])
        self.m.chrome(CLICK, ["#nulavio-routing-enabled"])
        self.seen(lambda n: n["enabled"]["pressed"] is True and not n["inPage"]["disabled"])
        self.assertTrue(self.state()["enabled"])
        self.m.chrome(CLICK, ["#nulavio-routing-in-page"])
        self.seen(lambda n: n["inPage"]["pressed"] is True)
        self.assertTrue(self.state()["inPage"])

        # Links from other apps with no rule: the last profile used, or always one profile.
        on = self.seen(lambda n: n["choices"])
        self.assertEqual(on["fallback"]["value"], "0")
        self.assertEqual(
            on["choices"],
            [
                ["0", "Último perfil usado (padrão)", False],
                [str(self.ids["Pessoal"]), "Sempre em Pessoal", False],
                [str(self.ids["Bancos"]), "Sempre em Bancos", False],
                [str(self.ids["Trabalho"]), "Sempre em Trabalho", False],
            ],
        )
        self.m.chrome(CHANGE, ["nulavio-routing-fallback", str(self.ids["Bancos"])])
        self.seen(lambda n: n["fallback"]["value"] == str(self.ids["Bancos"]) and n["said"])
        self.assertEqual(self.state()["fallback"]["profileId"], self.ids["Bancos"])
        # That profile is deleted: the page says links stop at a warning, and offers no profile in its place.
        self.m.chrome(P + "return P.remove(arguments[0]).then(() => true);", [self.ids["Bancos"]])
        gone = self.seen(lambda n: n["missing"])
        self.assertIn("não existe mais", gone["missing"])
        self.assertEqual(gone["fallback"]["value"], "missing")
        self.assertIn(["missing", "Um perfil que não existe mais", True], gone["choices"])
        self.assertTrue(self.state()["fallback"]["missing"])
        self.m.chrome(CHANGE, ["nulavio-routing-fallback", "0"])
        back = self.seen(lambda n: n["fallback"]["value"] == "0" and not n["missing"])
        self.assertNotIn("missing", [choice[0] for choice in back["choices"]])
        self.assertFalse(self.state()["fallback"]["missing"])


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsRoutingAloneTest(SettingsRoutingTest):
    profiles = ()

    def test_01_a_rule_is_added_and_removed_through_the_module(self):
        """With one profile there is nowhere to send a site: the group says so and offers no empty form."""
        now = self.open()
        self.assertIn("pelo menos dois perfis", now["alone"])
        self.assertIsNone(now["rows"])
        self.assertFalse(now["add"])
        self.assertIsNone(now["fallback"])
        self.assertEqual(now["fresh"], {"site": None, "match": None, "action": None, "profile": None})
        # A second profile, made in the list above: the rules open up without a reload.
        self.m.chrome(P + 'return P.create({ templateId: "work", name: "Trabalho" }).then(() => true);')
        two = self.seen(lambda n: n["add"] and not n["alone"])
        self.assertEqual(two["rows"], [])

    def test_02_the_switches_and_the_default_destination(self):
        self.skipTest("covered with three profiles")


if __name__ == "__main__":
    unittest.main()
