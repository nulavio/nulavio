"""Farol identity migration on a real, disposable engine profile group."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from test_profiles import MODULE, SERVICE, chrome_async

COLORS_PREF = "nulavio.profiles.colors"
MIGRATION_PREF = "nulavio.profiles.colors.farol"


@unittest.skipUnless(harness.nulavio_engine(), "identity migration needs the Nulavio build")
class ProfileColorsTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Estudos")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def profiles(self, script, *args):
        result = chrome_async(self.m, f"const P = {MODULE}; const SPS = {SERVICE}; {script}", args)
        self.assertNotIn("error", result, result)
        return result["ok"]

    def seed_legacy(self):
        return self.profiles(
            "const mint = await P.create({name:'Pessoal', color:'sky', avatar:'heart'});"
            "const rose = await P.create({name:'Pesquisa', color:'sky', avatar:'book'});"
            "const sand = await P.create({name:'Banco', color:'sand', avatar:'diamond'});"
            "const current = (await P.current()).id;"
            "const before = (await P.list()).profiles.map(({id,name,avatar,path}) => ({id,name,avatar,path}));"
            "Services.prefs.clearUserPref(args[0]);"
            "Services.prefs.setStringPref(args[1], JSON.stringify({[mint]:'mint', [rose]:'rose', [sand]:'sand', future:'kept'}));"
            "await SPS.trackPref(args[1]);"
            "return {current,mint,rose,sand,before};",
            MIGRATION_PREF,
            COLORS_PREF,
        )

    def test_a_new_group_starts_with_the_new_palette_without_a_migration_notice(self):
        self.profiles("await P.create({name:'Novo', templateId:'personal'});")
        state = self.profiles("return P.list();")
        self.assertTrue(all(p["color"] == "lima" for p in state["profiles"]))
        self.assertTrue(all(p.get("colorMigration") is None for p in state["profiles"]))

    def test_malformed_or_newer_preferences_are_not_rewritten(self):
        pid = self.profiles("return P.create({name:'Outro'});")
        cases = [
            ("{broken", "{}"),
            ("[]", "{}"),
            (json.dumps({str(pid): "mint"}), '{"version":3,"mint":[],"future":"kept"}'),
        ]
        for raw, marker in cases:
            with self.subTest(raw=raw, marker=marker):
                result = self.profiles(
                    "Services.prefs.setStringPref(args[0], args[1]);"
                    "Services.prefs.setStringPref(args[2], args[3]);"
                    "await P.list();"
                    "return [Services.prefs.getStringPref(args[0]), Services.prefs.getStringPref(args[2])];",
                    COLORS_PREF,
                    raw,
                    MIGRATION_PREF,
                    marker,
                )
                self.assertEqual(result, [raw, marker])

    def test_retry_finishes_legacy_keys_after_the_notice_was_recorded(self):
        pid = self.profiles("return P.create({name:'Retomada'});")
        result = self.profiles(
            "Services.prefs.setStringPref(args[0], JSON.stringify({version:2,mint:[args[2]]}));"
            "Services.prefs.setStringPref(args[1], JSON.stringify({[args[2]]:'mint'}));"
            "return (await P.list()).profiles.find(p => p.id === args[2]);",
            MIGRATION_PREF,
            COLORS_PREF,
            pid,
        )
        self.assertEqual((result["color"], result["colorMigration"]), ("lima", "mint-to-lima"))
        self.profiles("await P.update(args[0], {color:'lima'});", pid)
        result = self.profiles("return (await P.list()).profiles.find(p => p.id === args[0]);", pid)
        self.assertIsNone(result.get("colorMigration"))

    def test_migrates_legacy_colours_and_keeps_later_choices_after_restart(self):
        old = self.seed_legacy()
        state = self.profiles("return P.list();")
        by_id = {p["id"]: p for p in state["profiles"]}
        self.assertEqual(by_id[old["current"]]["color"], "lima")  # old implicit mint
        self.assertEqual(by_id[old["mint"]]["color"], "lima")
        self.assertEqual(by_id[old["rose"]]["color"], "coral")
        self.assertEqual(by_id[old["sand"]]["color"], "sand")
        for pid in (old["current"], old["mint"]):
            self.assertEqual(by_id[pid]["colorMigration"], "mint-to-lima")
        self.assertEqual([{k: p[k] for k in ("id", "name", "avatar", "path")} for p in state["profiles"]], old["before"])
        raw = self.profiles("return SPS.getDBPref(args[0]);", COLORS_PREF)
        self.assertEqual(json.loads(raw)["future"], "kept")
        self.assertNotIn("mint", self.profiles("return P.options().colors;"))
        self.assertNotIn("rose", self.profiles("return P.options().colors;"))

        # A person's later selection wins, including after a new process reads the group store.
        self.profiles("await P.update(args[0], {color:'violet'});", old["mint"])
        self.m = self.session.restart()
        again = self.profiles("await P.list(); return P.list();")
        by_id = {p["id"]: p for p in again["profiles"]}
        self.assertEqual(by_id[old["mint"]]["color"], "violet")
        self.assertIsNone(by_id[old["mint"]].get("colorMigration"))
        self.assertEqual(by_id[old["current"]]["colorMigration"], "mint-to-lima")
        self.assertEqual(json.loads(self.profiles("return SPS.getDBPref(args[0]);", COLORS_PREF))["future"], "kept")

    def test_settings_explains_the_change_and_focuses_the_real_colour_picker(self):
        old = self.seed_legacy()
        self.profiles("await P.list();")
        shell_url = self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        self.m.navigate(shell_url + "settings/settings.html#profiles")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';")))
        row = f'#profile-list > li[data-profile-id="{old["current"]}"]'
        action = row + " [data-color-migration] button"
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return Boolean(document.querySelector(arguments[0]));", [action]))
        )
        for theme, dark in (("light", 0), ("dark", 1)):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            self.m.execute("document.documentElement.dataset.theme = arguments[0];", [theme])
            # Capture the real row with its note and actual production styles, before opening the editor.
            (harness.artifacts_dir() / f"profile-colour-migration-{theme}.png").write_bytes(
                self.m.screenshot_png(element=self.m.find_element(row))
            )
            self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(action)})
            focus = self.m.execute(
                "return {name:document.activeElement.name, value:document.activeElement.value,"
                " open:Boolean(document.activeElement.closest('details[open]'))};"
            )
            self.assertEqual(focus, {"name": "color", "value": "lima", "open": True})
            self.m.execute("document.querySelector(arguments[0] + ' details').open = false;", [row])


if __name__ == "__main__":
    unittest.main()
