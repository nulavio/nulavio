"""ADR 0011: the profiles of the group, and what can be done with them, inside the engine's settings page.

The list is one setting of the page's own registry, drawn with the engine's rows, buttons and fields. Every
change goes through NulavioProfiles and NulavioVault, the modules the Shell's pages use. The tests act as a
person does (a click on a row's button, a field changed, the engine's own confirmation answered) and read the
result from the module, not from the page.

No protected profile is created here (that needs the Vault's tools): the rows of a protected profile are
drawn from a list the test gives the module, and the test checks which entry of the Vault each button calls.
"""

from __future__ import annotations

import unittest

import harness
from marionette import MarionetteError

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
MODULES = "resource://builtin-addons/nulavio-shell/modules/"
P = f'const P = ChromeUtils.importESModule("{MODULES}NulavioProfiles.sys.mjs").NulavioProfiles;'
V = f'const V = ChromeUtils.importESModule("{MODULES}NulavioVault.sys.mjs").NulavioVault;'
COLORS = ("lima", "sky", "violet", "coral", "sand", "slate")
PROFILES = P + "return P.list().then(list => list.profiles.map(p => [p.name, p.avatar, p.color]));"
# The list as the person sees it: each profile's row with its buttons, the editor when open, the bars.
LIST = (
    DOC
    + """
const list = d.querySelector("#nulavio-profile-list");
if (!list || list.closest("setting-control")?.hidden) return null;
const shown = el => !!el && !el.closest("setting-control")?.hidden && el.getBoundingClientRect().height > 0;
const bar = id => { const el = d.getElementById(id); return shown(el) ? el.message : null; };
const field = id => { const el = d.getElementById(id); return shown(el) ? el.value : null; };
return {
  rows: [...list.querySelectorAll("moz-box-item.nulavio-profile")].map(row => ({
    name: row.label, state: row.description, color: [...row.classList].find(c => c.startsWith("nulavio-profile-")),
    icon: row.iconSrc ?? null, disc: getComputedStyle(row).getPropertyValue("--box-icon-fill").trim(),
    buttons: [...row.querySelectorAll("moz-button")].map(b => b.dataset.action),
    names: [...row.querySelectorAll("moz-button")].map(b => b.ariaLabel),
  })),
  editor: list.querySelector(".nulavio-profile-editor")?.dataset.editor ?? null,
  edit: { name: field("nulavio-profile-name"), avatar: field("nulavio-profile-avatar"), color: field("nulavio-profile-color") },
  fresh: { name: field("nulavio-profile-new-name"), template: field("nulavio-profile-new-template") },
  create: shown(d.getElementById("nulavio-profile-new-create")),
  error: bar("nulavio-profile-error"), said: bar("nulavio-profile-said"), unavailable: bar("nulavio-profiles-unavailable"),
  doors: ["nulavio-profile-temporary", "nulavio-profile-protected", "nulavio-profile-manager"]
    .filter(id => shown(d.getElementById(id))),
};
"""
)
# A click on a row's button, on a button of the editor, or on a control by its id.
CLICK_ROW = (
    DOC
    + """
const [name, action] = arguments;
const row = [...d.querySelectorAll("#nulavio-profile-list moz-box-item.nulavio-profile")].find(r => r.label === name);
const button = row?.querySelector(`moz-button[data-action="${action}"]`);
if (!button) return false;
button.click();
return true;
"""
)
CLICK = DOC + "const el = d.querySelector(arguments[0]); if (!el) return false; el.click(); return true;"
# What a person does to a field: change its value; the engine's control tells its setting.
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
class SettingsProfilesTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()
        self.m.chrome(P + 'return P.create({ templateId: "work", name: "Trabalho" }).then(() => true);')
        self.m.chrome(P + 'return P.create({ templateId: "banking", name: "Bancos" }).then(() => true);')

    def open(self) -> dict:
        # In the session's own tab: the engine's confirmation is then the one the test driver answers.
        self.m.navigate("about:preferences#nulavioProfiles")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        return self.seen(lambda now: len(now["rows"]) == 3 and all(row["name"] and row["state"] for row in now["rows"]))

    def seen(self, wanted, timeout: float = 15) -> dict:
        harness.wait_until(lambda: (now := self.m.chrome(LIST)) is not None and wanted(now), timeout)
        now = self.m.chrome(LIST)
        self.assertIsNotNone(now, "the list of profiles is not on the page")
        self.assertTrue(wanted(now), now)
        return now

    def row(self, now: dict, name: str) -> dict:
        return next(row for row in now["rows"] if row["name"] == name)

    def profiles(self) -> dict:
        return {name: (avatar, color) for name, avatar, color in self.m.chrome(PROFILES)}

    def stub(self, module: str, method: str, body: str) -> None:
        """Replace one entry of a Shell module for this test; `window.__calls` gets what it was called with."""
        target = {"P": P, "V": V}[module]
        self.m.chrome(
            f"{target} window.__calls ??= [];"
            f"{module}.{method} = (...args) => {{ window.__calls.push([{method!r}, ...args]); {body} }};"
        )
        self.addCleanup(self.m.chrome, f"{target} delete {module}.{method};")

    def calls(self) -> list:
        return self.m.chrome("return window.__calls ?? [];")

    def test_01_each_row_has_the_actions_its_profile_can_take(self):
        now = self.open()
        self.assertEqual([row["name"] for row in now["rows"]], ["Pessoal", "Bancos", "Trabalho"])
        self.assertEqual(self.row(now, "Pessoal")["buttons"], ["edit", "delete-here"])
        self.assertEqual(self.row(now, "Pessoal")["state"], "Este perfil. Sem senha.")
        self.assertEqual(self.row(now, "Trabalho")["buttons"], ["open", "edit", "delete"])
        # Each button says whose it is, for someone who cannot see the row it sits in.
        self.assertEqual(
            self.row(now, "Trabalho")["names"], ["Abrir Trabalho", "Editar nome, ícone e cor: Trabalho", "Excluir… Trabalho"]
        )
        # The profile's own icon in its own colours (the engine's icon; the tile and glyph of the design tokens).
        work = self.row(now, "Trabalho")
        self.assertEqual(work["icon"], "chrome://browser/content/profiles/assets/16_briefcase.svg")
        self.assertEqual(work["color"], "nulavio-profile-sky")
        self.assertTrue(work["disc"], "the row's icon has no colour from the profile")
        self.assertNotEqual(work["disc"], self.row(now, "Bancos")["disc"])
        self.assertEqual(now["doors"], ["nulavio-profile-temporary", "nulavio-profile-protected", "nulavio-profile-manager"])

        # "Abrir" goes through the module, which says what happened; a refusal is said in the Shell's words.
        self.stub("P", "switchTo", 'return Promise.resolve({ action: "launched" });')
        self.assertTrue(self.m.chrome(CLICK_ROW, ["Trabalho", "open"]))
        self.assertEqual(self.seen(lambda n: n["said"])["said"], "Abrindo Trabalho…")
        ids = self.m.chrome(P + "return P.list().then(list => Object.fromEntries(list.profiles.map(p => [p.name, p.id])));")
        self.assertEqual(self.calls(), [["switchTo", ids["Trabalho"]]])
        self.stub("P", "switchTo", 'return Promise.reject(Object.assign(new Error("locked"), { code: "locked" }));')
        self.m.chrome(CLICK_ROW, ["Bancos", "open"])
        refused = self.seen(lambda n: n["error"])
        self.assertEqual(refused["error"], "Esse perfil está bloqueado. Desbloqueie primeiro.")
        self.assertIsNone(refused["said"])

        # The doors around the list.
        self.stub("P", "openTemporary", "return Promise.resolve();")
        self.stub("P", "openManager", "return Promise.resolve();")
        self.m.chrome(CLICK, ["#nulavio-profile-temporary"])
        self.assertEqual(self.seen(lambda n: n["said"])["said"], "Abrindo uma janela temporária…")
        self.m.chrome(CLICK, ["#nulavio-profile-manager"])
        self.assertTrue(harness.wait_until(lambda: ["openManager"] in self.calls(), 10), self.calls())
        tabs = self.m.chrome("return gBrowser.tabs.length;")
        self.m.chrome(CLICK, ["#nulavio-profile-protected"])
        where = "return gBrowser.selectedBrowser.currentURI.spec;"
        # A protected profile is created on the Vault's own page (its recovery code is shown there, once).
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(where).endswith("/vault/create.html"), 15), self.m.chrome(where))
        self.assertEqual(self.m.chrome("return gBrowser.tabs.length;"), tabs + 1)

    def test_02_a_profile_is_edited_under_its_row_and_saved_through_the_module(self):
        self.open()
        self.m.chrome(CLICK_ROW, ["Trabalho", "edit"])
        now = self.seen(lambda n: n["editor"])
        self.assertEqual(now["edit"], {"name": "Trabalho", "avatar": "briefcase", "color": "sky"})
        # The keyboard follows: into the editor when it opens, back to the row's button when it closes.
        focus = DOC + "const el = d.activeElement; return [el?.id || null, el?.dataset?.action ?? null, el?.ariaLabel ?? null];"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(focus)[0] == "nulavio-profile-name", 5), self.m.chrome(focus))
        # Icon and colour are chosen by looking at them; each choice has a name for who cannot see it.
        choices = (
            DOC
            + """
          const named = id => [...d.querySelectorAll(`#${id} moz-visual-picker-item`)].map(item => [item.value, item.ariaLabel]);
          const image = d.querySelector("#nulavio-profile-color moz-visual-picker-item").shadowRoot.querySelector("img");
          return { avatars: named("nulavio-profile-avatar"), colors: named("nulavio-profile-color"),
                   drawn: [image.src, w.getComputedStyle(image).fill !== "rgb(0, 0, 0)"] };
        """
        )
        offered = self.m.chrome(choices)
        self.assertEqual(len(offered["avatars"]), 14)
        self.assertIn(["briefcase", "Maleta"], offered["avatars"])
        self.assertEqual(
            offered["colors"],
            [[c, n] for c, n in zip(COLORS, ("Lima", "Céu", "Violeta", "Coral", "Areia", "Ardósia"), strict=True)],
        )
        # A colour is shown as this profile's icon in that colour.
        self.assertEqual(offered["drawn"], ["chrome://browser/content/profiles/assets/16_briefcase.svg", True])
        # A name another profile has: said in words, nothing written, the editor stays with what was typed.
        self.m.chrome(CHANGE, ["nulavio-profile-name", "bancos"])
        self.m.chrome(CLICK, ['#nulavio-profile-editor-buttons moz-button[data-action="save"]'])
        taken = self.seen(lambda n: n["error"])
        self.assertEqual(taken["error"], "Esse nome já está em uso.")
        self.assertEqual(taken["edit"]["name"], "bancos")
        self.assertIn("Trabalho", self.profiles())
        # Name, icon and colour, saved together; the row follows without a reload.
        self.m.chrome(CHANGE, ["nulavio-profile-name", "  Estudos  "])
        self.m.chrome(CHANGE, ["nulavio-profile-avatar", "book"])
        self.m.chrome(CHANGE, ["nulavio-profile-color", "violet"])
        self.m.chrome(CLICK, ['#nulavio-profile-editor-buttons moz-button[data-action="save"]'])
        saved = self.seen(lambda n: n["said"] and not n["editor"])
        self.assertEqual(saved["said"], "Salvo.")
        back = harness.wait_until(lambda: self.m.chrome(focus)[1] == "edit" and self.m.chrome(focus), 5)
        self.assertEqual(back, [None, "edit", "Editar nome, ícone e cor: Estudos"], self.m.chrome(focus))
        self.assertIsNone(saved["error"])
        self.assertEqual(self.profiles()["Estudos"], ("book", "violet"))
        self.assertNotIn("Trabalho", self.profiles())
        row = self.row(self.seen(lambda n: any(r["name"] == "Estudos" for r in n["rows"])), "Estudos")
        self.assertEqual(
            (row["color"], row["icon"]), ("nulavio-profile-violet", "chrome://browser/content/profiles/assets/16_book.svg")
        )
        # "Cancelar" writes nothing.
        self.m.chrome(CLICK_ROW, ["Bancos", "edit"])
        self.seen(lambda n: n["editor"])
        self.m.chrome(CHANGE, ["nulavio-profile-name", "Outro"])
        self.m.chrome(CLICK, ['#nulavio-profile-editor-buttons moz-button[data-action="cancel"]'])
        self.seen(lambda n: not n["editor"])
        self.assertIn("Bancos", self.profiles())
        self.assertNotIn("Outro", self.profiles())
        # Only what changed is written: a new colour alone does not send the name or the icon again.
        self.stub("P", "update", "return Promise.resolve();")
        self.m.chrome(CLICK_ROW, ["Bancos", "edit"])
        self.seen(lambda n: n["editor"])
        self.m.chrome(CHANGE, ["nulavio-profile-color", "coral"])
        self.m.chrome(CLICK, ['#nulavio-profile-editor-buttons moz-button[data-action="save"]'])
        self.seen(lambda n: not n["editor"])
        self.assertEqual([call[2] for call in self.calls() if call[0] == "update"], [{"color": "coral"}])

    def test_03_deleting_a_profile_asks_first_in_the_engines_own_prompt(self):
        self.open()
        self.m.chrome(CLICK_ROW, ["Bancos", "delete"])
        body = harness.wait_until(self.alert_text, 10)
        self.assertIn("Isto apaga de vez, deste computador", body or "no confirmation was shown")
        # Closing the prompt without choosing is "Cancelar": nothing is deleted.
        self.m.send("WebDriver:DismissAlert")
        self.assertIn("Bancos", self.profiles())
        self.assertIsNone(self.m.chrome(LIST)["said"])
        self.m.chrome(CLICK_ROW, ["Bancos", "delete"])
        self.assertTrue(harness.wait_until(self.alert_text, 10))
        self.m.send("WebDriver:AcceptAlert")
        gone = self.seen(lambda n: n["said"] and all(row["name"] != "Bancos" for row in n["rows"]))
        self.assertEqual(gone["said"], "Perfil excluído.")
        # The deleted row took the focused button with it: the keyboard is on the profile before it, not lost.
        focus = DOC + "const el = d.activeElement; return [el?.dataset?.action ?? null, el?.ariaLabel ?? null];"
        kept = harness.wait_until(lambda: self.m.chrome(focus)[0] == "edit" and self.m.chrome(focus), 5)
        self.assertEqual(kept, ["edit", "Editar nome, ícone e cor: Pessoal"], self.m.chrome(focus))
        self.assertNotIn("Bancos", self.profiles())
        # The profile in use is deleted on the engine's own page, which closes this instance safely.
        self.stub("P", "openCurrentPage", "return Promise.resolve();")
        self.m.chrome(CLICK_ROW, ["Pessoal", "delete-here"])
        self.assertTrue(harness.wait_until(lambda: ["openCurrentPage", "delete"] in self.calls(), 10), self.calls())
        self.assertIn("Pessoal", self.profiles())

    def alert_text(self):
        try:
            return self.m.send("WebDriver:GetAlertText")["value"]
        except MarionetteError:
            return None

    def test_04_a_new_profile_from_the_last_row_of_the_list(self):
        now = self.open()
        self.assertEqual(now["fresh"], {"name": "", "template": ""})
        self.assertTrue(now["create"])
        # No name: said in words, nothing created.
        self.m.chrome(CLICK, ["#nulavio-profile-new-create"])
        self.assertEqual(self.seen(lambda n: n["error"])["error"], "Informe um nome (até 60 caracteres).")
        self.assertEqual(len(self.profiles()), 3)
        # A template fills a name that is free; the person's own name is never replaced by a template.
        self.m.chrome(CHANGE, ["nulavio-profile-new-template", "work"])
        self.assertEqual(self.seen(lambda n: n["fresh"]["name"])["fresh"], {"name": "Trabalho 2", "template": "work"})
        self.m.chrome(CHANGE, ["nulavio-profile-new-template", "research"])
        self.assertEqual(self.seen(lambda n: n["fresh"]["template"] == "research")["fresh"]["name"], "Pesquisa")
        self.m.chrome(CHANGE, ["nulavio-profile-new-name", "Leituras"])
        self.m.chrome(CHANGE, ["nulavio-profile-new-template", "banking"])
        self.assertEqual(self.seen(lambda n: n["fresh"]["template"] == "banking")["fresh"]["name"], "Leituras")
        self.m.chrome(CHANGE, ["nulavio-profile-new-template", "research"])
        self.m.chrome(CLICK, ["#nulavio-profile-new-create"])
        made = self.seen(lambda n: n["said"] and any(row["name"] == "Leituras" for row in n["rows"]))
        self.assertEqual(made["said"], "Perfil criado.")
        self.assertEqual(self.profiles()["Leituras"], ("book", "violet"))  # the template's icon and colour
        self.assertEqual(made["fresh"], {"name": "", "template": ""})
        self.assertEqual(self.row(made, "Leituras")["buttons"], ["open", "edit", "delete"])

    def test_05_a_protected_profile_has_the_vaults_actions(self):
        # A list as the module gives it for a group with protected profiles (none can be made here).
        fake = """
          const real = Object.getPrototypeOf(P).list.bind(P);
          P.list = async () => {
            const list = await real();
            const [here, ...others] = list.profiles;
            return { ...list, profiles: [
              { ...here, encrypted: true, locked: false },
              { ...others[0], encrypted: true, locked: true },
              { ...others[1], encrypted: true, locked: false },
            ] };
          };
        """
        self.m.chrome(P + fake)
        self.addCleanup(self.m.chrome, P + "delete P.list;")
        now = self.open()
        self.assertEqual(self.row(now, "Pessoal")["buttons"], ["lock-here", "methods", "edit", "delete-here"])
        self.assertEqual(self.row(now, "Pessoal")["state"], "Este perfil. Protegido e desbloqueado.")
        self.assertEqual(self.row(now, "Bancos")["buttons"], ["unlock", "methods", "edit", "delete"])
        self.assertEqual(self.row(now, "Bancos")["state"], "Protegido e bloqueado: criptografado no disco.")
        self.assertEqual(self.row(now, "Bancos")["names"][0], "Bancos, bloqueado, desbloquear…")
        self.assertEqual(self.row(now, "Trabalho")["buttons"], ["open", "lock", "methods", "edit", "delete"])
        ids = self.m.chrome(P + "return P.list().then(list => Object.fromEntries(list.profiles.map(p => [p.name, p.id])));")

        self.stub("V", "openUnlockPage", "return Promise.resolve();")
        self.stub("V", "lock", "return Promise.resolve();")
        self.stub("V", "lockCurrent", "return Promise.resolve({ quit: false });")
        # Unlocking is the Vault's own page; this page never asks for a password.
        self.m.chrome(CLICK_ROW, ["Bancos", "unlock"])
        self.assertTrue(harness.wait_until(lambda: ["openUnlockPage", ids["Bancos"], None, "selector"] in self.calls(), 10))
        self.m.chrome(CLICK_ROW, ["Trabalho", "lock"])
        self.assertEqual(self.seen(lambda n: n["said"])["said"], "Trabalho está bloqueado.")
        self.assertIn(["lock", ids["Trabalho"]], self.calls())
        # Locking the profile in use closes its windows: it asks first, and "Cancelar" locks nothing.
        self.m.chrome(CLICK_ROW, ["Pessoal", "lock-here"])
        body = harness.wait_until(self.alert_text, 10)
        self.assertIn("Todas as janelas deste perfil fecham", body or "no confirmation was shown")
        self.m.send("WebDriver:DismissAlert")
        self.assertNotIn(["lockCurrent"], self.calls())
        self.m.chrome(CLICK_ROW, ["Pessoal", "lock-here"])
        self.assertTrue(harness.wait_until(self.alert_text, 10))
        self.m.send("WebDriver:AcceptAlert")
        kept = self.seen(lambda n: n["said"] and "janelas" in n["said"])
        self.assertEqual(kept["said"], "As janelas continuam abertas. O perfil bloqueia quando você fechar a última.")
        self.assertIn(["lockCurrent"], self.calls())
        # The ways a profile unlocks are the Vault's own page too.
        tabs = self.m.chrome("return gBrowser.tabs.length;")
        self.m.chrome(CLICK_ROW, ["Bancos", "methods"])
        where = "return gBrowser.selectedBrowser.currentURI.spec;"
        wanted = f"/vault/methods.html?p={ids['Bancos']}"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(where).endswith(wanted), 15), self.m.chrome(where))
        self.assertEqual(self.m.chrome("return gBrowser.tabs.length;"), tabs + 1)

    def test_06_a_group_that_cannot_be_used_says_why_and_offers_nothing(self):
        self.m.chrome(P + 'P.list = async () => ({ available: false, reason: "disabled", profiles: [] });')
        self.addCleanup(self.m.chrome, P + "delete P.list;")
        self.m.navigate("about:preferences#nulavioProfiles")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        bar = (
            DOC
            + 'const el = d.getElementById("nulavio-profiles-unavailable");'
            + 'return el && !el.closest("setting-control").hidden ? el.message : null;'
        )
        said = harness.wait_until(lambda: self.m.chrome(bar), 15)
        self.assertEqual(said, "Os perfis estão desligados neste navegador (browser.profiles.enabled).")
        shown = (
            DOC
            + """
          return ["nulavio-profile-list", "nulavio-profile-temporary", "nulavio-profile-protected", "nulavio-profile-manager"]
            .filter(id => { const el = d.getElementById(id); return el && !el.closest("setting-control")?.hidden; });
        """
        )
        self.assertEqual(self.m.chrome(shown), [])


if __name__ == "__main__":
    unittest.main()
