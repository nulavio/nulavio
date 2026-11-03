"""The new tab says where you are (UX4, audit SPA-14/23). Nulavio build only.

"Você está em {perfil}" with its state in words, one line of facts (what needs attention, by
name), the rules that open sites here, and the rest one click away in "Detalhes" and "Atalhos
e ajuda". Nothing on the page is a live region at load. Captures go to the test artifacts.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

PROFILES = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles'
ROUTING = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs").NulavioRouting'

STATE = """
const who = document.getElementById('here-who');
const facts = [...document.querySelectorAll('#status [data-status]')].filter(d => !d.closest('[hidden]'));
const summary = document.getElementById('here-summary');
return {
  painted: document.documentElement.dataset.painted,
  who: who.hidden ? null : {
    label: who.querySelector('.here__label')?.textContent,
    name: who.querySelector('.here__name')?.textContent,
    states: [...who.querySelectorAll('.badge--security')].map(b => b.dataset.state),
    text: who.textContent,
  },
  summary: {level: summary.dataset.level, text: summary.textContent},
  warn: facts.filter(d => d.dataset.level === 'warn').map(d => d.previousElementSibling.textContent),
  detailsOpen: document.getElementById('here-details').open,
  helpOpen: document.getElementById('help').open,
  live: [...document.querySelectorAll('#here [aria-live], #here [role=status], #here [role=alert]')].map(e => e.id),
  routes: document.getElementById('here-routes').hidden ? null : document.getElementById('here-routes').textContent,
  sites: [...document.querySelectorAll('#here-sites li')].map(li => li.textContent),
  settings: !document.getElementById('open-settings').hidden && document.getElementById('open-settings').getAttribute('href'),
  headline: document.querySelector('h1').className,
};
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class NewTabHereTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.url = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('newtab/newtab.html');")
        cls.shots = harness.artifacts_dir() / "newtab-ux4"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")
        cls.session.cleanup()

    def chrome_async(self, body: str, *args):
        script = (
            "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
            f"(async () => {{ const P = {PROFILES}; const R = {ROUTING}; {body} }})()"
            ".then(done, e => done({error: String(e)}));"
        )
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(script, list(args))
        finally:
            self.m.set_context("content")

    def open(self) -> dict:
        self.m.navigate(self.url)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 15)
        )
        return self.m.execute(STATE)

    def message(self, key: str, *args: str) -> str:
        return self.m.execute("return browser.i18n.getMessage(arguments[0], arguments[1]);", [key, list(args)])

    def shoot(self, name: str) -> None:
        for dark in (0, 1):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            time.sleep(0.4)
            (self.shots / f"{name}-{'dark' if dark else 'light'}.png").write_bytes(self.m.screenshot_png(full=True))
        self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")

    def test_01_says_where_you_are_in_one_line(self):
        here = self.chrome_async("return P.here();")
        state = self.open()
        self.assertEqual(state["painted"], "true")
        self.assertEqual(state["who"]["label"], self.message("whereLabel"))
        self.assertEqual(state["who"]["name"], here["name"])
        self.assertEqual(state["who"]["states"], [])  # a plain profile: no state badge, the words instead…
        self.assertIn(self.message("profileUnprotected"), state["who"]["text"])
        self.assertEqual(here["protection"], "plain")
        self.assertEqual(state["headline"], "visually-hidden")  # …and no slogan
        self.assertEqual(state["settings"], "../settings/settings.html")
        if state["warn"]:
            # What needs attention is named in the line, and the details open by themselves.
            self.assertEqual(state["summary"]["level"], "warn")
            self.assertEqual(state["summary"]["text"], self.message("protectionsAttention", ", ".join(state["warn"])))
            self.assertTrue(state["detailsOpen"])
        else:
            self.assertEqual(state["summary"], {"level": "ok", "text": self.message("protectionsOn")})
            self.assertFalse(state["detailsOpen"])
        self.assertFalse(state["helpOpen"])
        self.assertEqual(state["live"], [], "a live region at load would read the whole status aloud")
        self.shoot("here")

    def test_02_rules_that_open_sites_here(self):
        # A rule needs the profile group (the first extra profile creates it); this also gives
        # this profile its id, which the cached summary must pick up at once.
        current = self.chrome_async("await P.ensureStore(); return (await P.list()).profiles.find(p => p.isCurrent).id;")
        self.assertIsInstance(current, int)
        rule = self.chrome_async(
            "return await R.addRule({site: 'docs.example.org', match: 'host', action: 'open-in', profileId: args[0]});",
            current,
        )
        self.assertIsInstance(rule, str, rule)
        try:
            state = self.open()
            self.assertEqual(state["routes"], self.message("routesHere", "1"))
            self.assertEqual(state["sites"], ["docs.example.org"])
            self.m.execute("document.getElementById('here-details').open = true;")
            self.shoot("routes")
        finally:
            self.chrome_async("await R.removeRule(args[0]);", rule)
        self.assertIsNone(self.open()["routes"])

    def test_03_help_keeps_the_engine_note_one_click_away(self):
        self.open()
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#help > summary")})
        self.assertTrue(self.m.execute("return document.getElementById('help').open;"))
        footer = self.m.execute("return document.querySelector('#help .footer').innerText;")
        self.assertIn(self.message("footer"), footer)  # the engine is named together with "not affiliated"
        self.assertTrue(self.m.execute("return document.querySelectorAll('#help .keys li').length;") >= 5)
        self.shoot("help")

    def test_04_a_private_window_says_so(self):
        handles = set(self.m.window_handles())
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, timeout=20))
        private = (set(self.m.window_handles()) - handles).pop()
        self.m.switch_to(private)
        try:
            harness.wait_until(lambda: self.m.current_url() == "about:privatebrowsing", timeout=20)
            state = self.open()
            self.assertEqual(state["who"]["states"], ["private"])
            self.assertNotIn("null", state["who"]["text"])
            self.assertNotIn(self.message("profileUnprotected"), state["who"]["text"])  # one state: private
            self.shoot("private")
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)


if __name__ == "__main__":
    unittest.main()
