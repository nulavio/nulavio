"""Nulavio Profiles (docs/adr/0003-nulavio-profiles-and-routing.md), Nulavio build only.

Runs a *registered* profile in a disposable HOME (harness.GeckoProfileSession),
like a user's menu entry, because the engine's profile management is off for
the ``--profile <dir>`` profiles the launcher uses. Switching starts a second,
real engine instance; the test drives it too (Marionette, test-only prefs) to
prove that cookies and site storage do not cross profiles, that a second
switch does not start a duplicate instance, and that a running profile cannot
be deleted.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from marionette import MarionetteError

MODULE = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles'
SERVICE = 'ChromeUtils.importESModule("resource:///modules/profiles/SelectableProfileService.sys.mjs").SelectableProfileService'
ACTION_BUTTON = "shell_nulavio_net-BAP"
ACTION_WIDGET = "shell_nulavio_net-browser-action"


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        return m.execute_async(script, list(args))
    finally:
        m.set_context("content")


GRID = """
const grid = document.querySelector(arguments[0]);
const radios = [...grid.querySelectorAll('input[type=radio][name=avatar]')];
const tone = name => {
  const probe = document.createElement('span');
  probe.style.background = `var(--nv-color-identityTile-${name})`;
  document.body.append(probe);
  const value = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return value;
};
const checked = grid.querySelector('input:checked + .swatch__tile');
const other = grid.querySelector('input:not(:checked) + .swatch__tile');
return {
  legend: grid.querySelector('legend').textContent,
  count: radios.length,
  named: radios.every(r => r.closest('label').querySelector('.visually-hidden').textContent.trim().length > 0),
  glyphs: grid.querySelectorAll('.swatch__tile svg').length,
  chosen: grid.querySelector('input:checked')?.value ?? null,
  tinted: getComputedStyle(checked).backgroundColor === tone(arguments[1]),
  quiet: getComputedStyle(other).backgroundColor !== tone(arguments[1]),
};
"""


@unittest.skipUnless(harness.nulavio_engine(), "engine profiles need the Nulavio build (NULAVIO_ENGINE)")
class ProfilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.shell_url = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    # -- helpers -----------------------------------------------------------

    def profiles(self, body: str, *args):
        result = chrome_async(self.m, f"const P = {MODULE}; const SPS = {SERVICE}; {body}", args)
        if "error" in result:
            raise AssertionError(f"NulavioProfiles failed: {result['error']}")
        return result["ok"]

    def profiles_error(self, body: str, *args):
        return chrome_async(self.m, f"const P = {MODULE}; {body}", args).get("error")

    def listed(self):
        return {p["name"]: p for p in self.profiles("return (await P.list()).profiles;")}

    def path_of(self, profile_id: int) -> Path:
        return Path(self.profiles("return (await SPS.getProfile(args[0])).path;", profile_id))

    def ready(self, m=None) -> bool:
        m = m or self.m
        try:
            return m.execute("return document.documentElement && document.documentElement.dataset.ready === 'true';")
        except MarionetteError:
            return False

    def open_instance(self, path: Path, launch) -> harness.Marionette:
        """Launch another profile through the UI or the module and connect to it."""
        harness.GeckoProfileSession.enable_marionette(path)
        launch()
        self.assertTrue(harness.wait_until(lambda: self.session.processes_for(path), timeout=60), "no instance started")
        return harness.GeckoProfileSession.connect(path, timeout=90)

    def close_instance(self, client, path: Path) -> None:
        client.quit()
        self.assertTrue(harness.wait_until(lambda: not self.session.processes_for(path), timeout=30), "instance did not exit")
        (path / "MarionetteActivePort").unlink(missing_ok=True)

    # -- tests -------------------------------------------------------------

    def test_01_selector_in_the_toolbar_with_shortcut(self):
        state = self.m.chrome(
            "const {CustomizableUI} = ChromeUtils.importESModule('moz-src:///browser/components/customizableui/CustomizableUI.sys.mjs');"
            "const keys = [...document.querySelectorAll('key')].filter(k => k.getAttribute('key') === 'P'"
            " && k.getAttribute('modifiers') === 'alt,shift');"
            f"return {{area: CustomizableUI.getPlacementOfWidget('{ACTION_WIDGET}')?.area,"
            f" tooltip: document.getElementById('{ACTION_BUTTON}')?.getAttribute('tooltiptext'),"
            " keysets: keys.map(k => k.closest('keyset')?.id ?? '')};"
        )
        self.assertEqual(state["area"], "nav-bar", "the profile selector is not on the toolbar")
        self.assertIn("Pessoal", state["tooltip"])
        self.assertTrue(any("shell_nulavio_net" in k for k in state["keysets"]), state["keysets"])

    def test_02_create_from_template(self):
        self.assertTrue(self.profiles("return (await P.list()).available;"))
        work = self.profiles("return P.create({templateId: 'work', name: 'Trabalho'});")
        profiles = self.listed()
        self.assertEqual(profiles["Trabalho"]["avatar"], "briefcase")
        self.assertEqual(profiles["Trabalho"]["color"], "sky")
        self.assertFalse(profiles["Trabalho"]["isCurrent"])
        self.assertEqual(sum(p["isCurrent"] for p in profiles.values()), 1)
        self.assertTrue(self.path_of(work).is_dir())
        shared = json.loads(self.profiles("return SPS.getDBPref('nulavio.profiles.colors');"))
        self.assertEqual(shared.get(str(work)), "sky", "the colour is not shared with the other profiles")
        type(self).work = work

    def test_03_validation(self):
        cases = {
            "invalid-name": "return P.create({name: '   '});",
            "name-taken": "return P.create({name: 'trabalho'});",
            "invalid-color": "return P.create({name: 'X1', color: 'red'});",
            "invalid-avatar": "return P.create({name: 'X2', avatar: '../../etc/passwd'});",
            "unknown-template": "return P.create({name: 'X3', templateId: 'temporary'});",
        }
        for code, body in cases.items():
            with self.subTest(code=code):
                self.assertEqual(self.profiles_error(body), code)
        self.assertEqual(self.profiles_error("return P.create({name: 'a/b'});"), "invalid-name")
        self.assertFalse({"X1", "X2", "X3"} & set(self.listed()), "a rejected profile was created")

    def test_04_update(self):
        self.profiles("await P.update(args[0], {name: 'Trabalho cliente', color: 'violet', avatar: 'star'});", self.work)
        updated = self.listed()["Trabalho cliente"]
        self.assertEqual((updated["color"], updated["avatar"]), ("violet", "star"))
        self.profiles("await P.update(args[0], {name: 'Trabalho'});", self.work)

    def test_05_switch_isolates_and_never_duplicates(self):
        path = self.path_of(self.work)
        # Site data in the current profile.
        self.m.navigate(self.server.url("/page/isolation-a"))
        self.m.execute("document.cookie = 'nv_iso=1; path=/'; localStorage.setItem('nv_iso', '1');")
        self.assertIn("nv_iso=1", self.m.execute("return document.cookie;"))

        other = self.open_instance(
            path, lambda: self.assertEqual(self.profiles("return P.switchTo(args[0]);", self.work), {"action": "launched"})
        )
        try:
            other.navigate(self.server.url("/page/isolation-b"))
            self.assertNotIn("nv_iso", other.execute("return document.cookie;"), "a cookie crossed profiles")
            self.assertIsNone(other.execute("return localStorage.getItem('nv_iso');"), "site storage crossed profiles")

            # A second switch reaches the running instance instead of starting another one.
            first = self.session.processes_for(path)
            self.profiles("return P.switchTo(args[0]);", self.work)
            time.sleep(6)
            self.assertEqual(self.session.processes_for(path), first, "a second instance of the profile is running")

            # The engine's profile lock: a running profile is not deleted.
            self.assertEqual(self.profiles_error("return P.remove(args[0]);", self.work), "in-use")
            self.assertTrue(path.is_dir())
        finally:
            self.close_instance(other, path)

    def test_06_current_profile_is_not_deleted_here(self):
        current = self.profiles("return (await P.current()).id;")
        self.assertEqual(self.profiles_error("return P.remove(args[0]);", current), "is-current")

    def test_07_popup_switches_with_one_click(self):
        self.m.navigate(self.shell_url + "profiles/popup.html")
        self.assertTrue(harness.wait_until(self.ready, timeout=15))
        page = self.m.execute(
            "return {current: document.querySelector('#current .popup__name')?.textContent,"
            " others: [...document.querySelectorAll('#others .popup__item')]"
            ".map(b => [b.querySelector('.popup__name').textContent, b.getAttribute('aria-keyshortcuts')]),"
            " templates: document.querySelectorAll('#templates button').length,"
            " unavailable: !document.getElementById('unavailable').hidden};"
        )
        self.assertFalse(page["unavailable"])
        self.assertTrue(page["current"])
        self.assertEqual(page["templates"], 5)
        self.assertIn(["Trabalho", "1"], page["others"])

        path = self.path_of(self.work)
        item = self.m.find_element(f'#others .popup__item[data-profile-id="{self.work}"]')
        other = self.open_instance(path, lambda: self.m.send("WebDriver:ElementClick", {"id": item}))
        # UX4: an open profile says so, in words and in its name (the engine's lock names its process).
        self.assertEqual(self.popup_row(self.work), {"running": "true", "label": "Abrir Trabalho, aberto", "mark": "aberto"})
        self.close_instance(other, path)
        self.assertEqual(self.popup_row(self.work), {"running": "false", "label": "Abrir Trabalho", "mark": None})

    def popup_row(self, profile_id: int) -> dict:
        self.m.navigate(self.shell_url + "profiles/popup.html")
        self.assertTrue(harness.wait_until(self.ready, timeout=15))
        return self.m.execute(
            "const b = document.querySelector(`#others .popup__item[data-profile-id='${arguments[0]}']`);"
            "return {running: b.dataset.running, label: b.getAttribute('aria-label'),"
            " mark: b.querySelector('.popup__running')?.textContent ?? null};",
            [profile_id],
        )

    def test_08_settings_page_edits_and_deletes_with_confirmation(self):
        research = self.profiles("return P.create({templateId: 'research', name: 'Pesquisa'});")
        self.m.navigate(self.shell_url + "settings/settings.html#profiles")
        self.assertTrue(harness.wait_until(self.ready, timeout=15))
        harness.wait_until(
            lambda: self.m.execute("return document.querySelectorAll('#profile-list > li').length;") == 3, timeout=10
        )
        rows = self.m.execute(
            "return [...document.querySelectorAll('#profile-list > li')].map(li => ({id: li.dataset.profileId,"
            " current: Boolean(li.querySelector('.row__title .badge')),"
            " buttons: [...li.querySelectorAll('.row__end button')].map(b => b.textContent)}));"
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(r["current"] for r in rows), 1, "the current profile is not marked")

        # Delete asks first; cancelling keeps the profile.
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f'[data-focus-key="delete-{research}"]')})
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element('dialog button[value="cancel"]')})
        time.sleep(0.5)
        self.assertIn("Pesquisa", self.listed())
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f'[data-focus-key="delete-{research}"]')})
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element('dialog button[value="confirm"]')})
        harness.wait_until(lambda: "Pesquisa" not in self.listed(), timeout=10)
        self.assertNotIn("Pesquisa", self.listed())
        self.assertNotIn(str(research), json.loads(self.profiles("return SPS.getDBPref('nulavio.profiles.colors');")))

    def test_09_toolbar_follows_a_rename(self):
        current = self.profiles("return (await P.current()).id;")
        self.profiles("await P.update(args[0], {name: 'Casa'});", current)
        tooltip = lambda: self.m.chrome(f"return document.getElementById('{ACTION_BUTTON}').getAttribute('tooltiptext');")  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: "Casa" in tooltip(), timeout=10), tooltip())

    def test_10_delete_after_close(self):
        path = self.path_of(self.work)
        self.assertEqual(self.session.processes_for(path), [])
        self.profiles("await P.remove(args[0]);", self.work)
        self.assertNotIn("Trabalho", self.listed())
        self.assertTrue(harness.wait_until(lambda: not path.exists(), timeout=10), "profile files were kept")

    def test_11_sensitive_sites_profile_clears_on_close(self):
        """The "Sensitive sites" template (docs/security/phase5-spikes.md): its own profile, cleared when it closes."""
        sensitive = self.profiles("return P.create({templateId: 'sensitive', name: 'Sites sensíveis'});")
        path = self.path_of(sensitive)
        user_js = (path / "user.js").read_text()
        for line in (
            'user_pref("privacy.sanitize.sanitizeOnShutdown", true);',
            'user_pref("privacy.clearOnShutdown_v2.cookiesAndStorage", true);',
            'user_pref("xpinstall.enabled", false);',
        ):
            self.assertIn(line, user_js)
        listed = self.listed()
        self.assertEqual(listed["Sites sensíveis"]["kind"], "sensitive")
        self.assertEqual([p["kind"] for p in listed.values() if p["isCurrent"]], [None])

        def launch():
            self.profiles("return P.switchTo(args[0]);", sensitive)

        other = self.open_instance(path, launch)
        try:
            other.navigate(self.server.url("/page/sensitive"))
            other.execute("document.cookie = 'nv_s=1; path=/; max-age=86400'; localStorage.setItem('nv_s', '1');")
            self.assertIn("nv_s=1", other.execute("return document.cookie;"))
            prefs = other.chrome(
                "return [Services.prefs.getBoolPref('xpinstall.enabled'),"
                " Services.prefs.getBoolPref('privacy.sanitize.sanitizeOnShutdown')];"
            )
            self.assertEqual(prefs, [False, True])
        finally:
            self.close_instance(other, path)

        other = self.open_instance(path, launch)
        try:
            other.navigate(self.server.url("/page/sensitive-again"))
            self.assertNotIn("nv_s", other.execute("return document.cookie;"), "a cookie survived closing")
            self.assertIsNone(other.execute("return localStorage.getItem('nv_s');"), "site storage survived closing")
            visits = chrome_async(
                other,
                "const {PlacesUtils} = ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');"
                "return (await PlacesUtils.history.fetch(args[0])) !== null;",
                [self.server.url("/page/sensitive")],
            )
            self.assertEqual(visits, {"ok": False}, "history survived closing")
        finally:
            self.close_instance(other, path)

        self.m.navigate(self.shell_url + "settings/settings.html#profiles")
        self.assertTrue(harness.wait_until(self.ready, timeout=15))
        hint = f'#profile-list > li[data-profile-id="{sensitive}"] [data-kind="sensitive"]'
        self.assertTrue(harness.wait_until(lambda: self.m.execute(f"return Boolean(document.querySelector('{hint}'));"), 10))

    def test_12_create_sheet_fills_and_creates_only_on_submit(self):
        """UX4 (audit SPA-09): "Novo perfil…" opens a sheet; a template only fills it."""
        before = set(self.listed())
        self.m.navigate(self.shell_url + "profiles/popup.html")
        self.assertTrue(harness.wait_until(self.ready, timeout=15))
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#new-profile")})
        self.assertEqual(
            self.m.execute(
                "const $ = id => document.getElementById(id);"
                "return [$('menu').hidden, $('sheet').hidden, document.activeElement.id];"
            ),
            [True, False, "sheet-name"],
        )
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element('#templates button[data-template="research"]')})
        filled = self.m.execute(
            "const f = document.getElementById('sheet');"
            "return {name: f.elements.name.value, avatar: f.elements.avatar.value, color: f.elements.color.value,"
            " pressed: [...document.querySelectorAll('#templates button[aria-pressed=true]')].map(b => b.dataset.template)};"
        )
        self.assertEqual(filled, {"name": "Pesquisa", "avatar": "book", "color": "violet", "pressed": ["research"]})
        # The icon is a grid of glyph tiles; only the chosen one wears the template's colour.
        grid = self.m.execute(GRID, ["#sheet-avatars .swatches--glyphs", "violet"])
        self.assertEqual(
            grid, {"legend": "Ícone", "count": 14, "named": True, "glyphs": 14, "chosen": "book", "tinted": True, "quiet": True}
        )
        time.sleep(0.5)
        self.assertEqual(set(self.listed()), before, "a template created a profile before Criar")
        # Back returns to the menu with nothing created.
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#sheet-back")})
        self.assertEqual(
            self.m.execute("return [document.getElementById('menu').hidden, document.activeElement.id];"), [False, "new-profile"]
        )
        # "Proteger com senha" continues in the Vault's own steps, prefilled; nothing is created here.
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#new-profile")})
        self.m.execute(
            "const f = document.getElementById('sheet');"
            "f.elements.name.value = 'Banco seguro'; f.elements.protect.checked = true;"
        )
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#sheet-create")})
        vault = harness.wait_until(
            lambda: next(
                (u for u in self.m.chrome("return gBrowser.browsers.map(b => b.currentURI.spec);") if "/vault/create.html?" in u),
                None,
            ),
            timeout=10,
        )
        self.assertTrue(vault, "the protected steps did not open")
        self.assertIn("name=Banco+seguro", vault)
        self.assertEqual(set(self.listed()), before)
        self.m.navigate(vault)
        harness.wait_until(lambda: self.m.execute("return document.querySelectorAll('#templates button').length;"), timeout=10)
        self.assertEqual(self.m.execute("return document.getElementById('name').value;"), "Banco seguro")
        # The name is not asked twice: the Vault starts at the protection step, showing the profile (FR-06).
        settled = "const s = document.body.dataset.step; return s === 'protection' || s === 'unavailable' ? s : null;"
        step = harness.wait_until(lambda: self.m.execute(settled), timeout=10)
        if step == "protection":
            self.assertIn("Banco seguro", self.m.execute("return document.getElementById('summary').textContent;"))
            self.assertEqual(self.m.execute("return document.getElementById('progress').textContent;")[-6:], "1 de 2")

    def test_13_typing_filters_the_profile_menu(self):
        """UX4 (audit SPA-17): letters filter the list by name (accents ignored), Escape clears it."""
        made = [self.profiles("return P.create({name: args[0]});", name) for name in ("Álbum", "Bolsa")]
        try:
            self.m.navigate(self.shell_url + "profiles/popup.html")
            self.assertTrue(harness.wait_until(self.ready, timeout=15))
            self.m.execute("document.querySelector('#others .popup__item').focus();")
            self.m.send("WebDriver:ElementSendKeys", {"id": self.m.find_element("#others .popup__item"), "text": "alb"})
            shown = lambda: self.m.execute(  # noqa: E731
                "return [...document.querySelectorAll('#others li:not([hidden]) .popup__name')].map(n => n.textContent);"
            )
            self.assertTrue(harness.wait_until(lambda: shown() == ["Álbum"], 5), shown())
            self.assertEqual(
                self.m.execute("return [document.activeElement.id, document.getElementById('filter').value];"), ["filter", "alb"]
            )
            self.m.send("WebDriver:ElementSendKeys", {"id": self.m.find_element("#filter"), "text": "zz"})
            self.assertTrue(
                harness.wait_until(lambda: not self.m.execute("return document.getElementById('filter-none').hidden;"), 5)
            )
            self.m.send("WebDriver:ElementSendKeys", {"id": self.m.find_element("#filter"), "text": "\ue00c"})  # Escape
            self.assertTrue(
                harness.wait_until(
                    lambda: len(shown()) >= 2 and self.m.execute("return document.getElementById('filter').hidden;"), 5
                )
            )
        finally:
            for profile_id in made:
                self.profiles("await P.remove(args[0]);", profile_id)

    def test_14_the_icon_grid_follows_the_colour_and_saves(self):
        """Visual audit (icons): a profile's icon is chosen on a grid of glyph tiles; the chosen tile wears the
        colour chosen next to it, before saving, and "Salvar" keeps both."""
        made = self.profiles("return P.create({name: 'Grade', avatar: 'leaf', color: 'sky'});")
        try:
            self.m.navigate(self.shell_url + "settings/settings.html#profiles")
            self.assertTrue(harness.wait_until(self.ready, timeout=15))
            row = f'#profile-list > li[data-profile-id="{made}"]'
            found = f"return Boolean(document.querySelector('{row} details'));"
            self.assertTrue(harness.wait_until(lambda: self.m.execute(found), 10))
            self.m.execute(f"document.querySelector('{row} details').open = true;")
            grid = f"{row} .swatches--glyphs"
            self.assertEqual(
                self.m.execute(GRID, [grid, "sky"]),
                {"legend": "Ícone", "count": 14, "named": True, "glyphs": 14, "chosen": "leaf", "tinted": True, "quiet": True},
            )
            click = lambda selector: self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f"{row} {selector}")})  # noqa: E731
            click('label:has(> input[name="color"][value="coral"])')
            self.assertTrue(self.m.execute(GRID, [grid, "coral"])["tinted"], "the chosen icon kept the old colour")
            click('label:has(> input[name="avatar"][value="star"])')
            self.assertEqual(self.m.execute(GRID, [grid, "coral"])["chosen"], "star")
            click('form button[type="submit"]')
            saved = lambda: {k: self.listed()["Grade"][k] for k in ("avatar", "color")}  # noqa: E731
            self.assertTrue(harness.wait_until(lambda: saved() == {"avatar": "star", "color": "coral"}, 10), saved())
        finally:
            self.profiles("await P.remove(args[0]);", made)


if __name__ == "__main__":
    unittest.main()
