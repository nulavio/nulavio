"""Pages for a held-back link act only on what the Shell's modules hold. Nulavio build only.

Another installed extension can open any Shell page as a top-level tab, with any query string
(the engine allows a tab to load another extension's page). So the routing pages (ask, blocked)
and the unlock page take no link, rule or site from their address, and the look-alike warning
only the address it checks: the routing and unlock pages get an id the routing module made when
it held the link, and the look-alike page has the passwords module check the address again.

Each test installs a throwaway extension that opens one Shell page with its own parameters, the
way such an extension would, and checks that the page offers nothing it did not get from a module.
The module calls that would open another profile are replaced by recorders, so nothing is started.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from marionette import MarionetteError

SHELL = "resource://builtin-addons/nulavio-shell/modules"
PRELUDE = (
    f'const R = ChromeUtils.importESModule("{SHELL}/NulavioRouting.sys.mjs").NulavioRouting;'
    f'const P = ChromeUtils.importESModule("{SHELL}/NulavioProfiles.sys.mjs").NulavioProfiles;'
    f'const W = ChromeUtils.importESModule("{SHELL}/NulavioPasswords.sys.mjs").NulavioPasswords;'
)
ELSEWHERE = "https://elsewhere.example/landing?id=from-the-other-extension"

PAGE = """
const seen = e => e && !e.hidden && e.checkVisibility();
return {
  ready: document.documentElement.dataset.ready === 'true',
  state: document.body.dataset.state ?? null,
  title: document.title,
  text: document.querySelector('main').textContent,
  url: (seen(document.getElementById('url')) && document.getElementById('url').textContent) || null,
  buttons: [...document.querySelectorAll('button')].filter(seen).map(b => [b.id || b.className, b.textContent.trim()]),
};
"""


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        f"(async () => {{ {PRELUDE} {body} }})().then(v => done({{ok: v ?? null}}), e => done({{error: e?.code ?? String(e)}}));"
    )
    m.set_context("chrome")
    try:
        return m.execute_async(script, list(args))
    finally:
        m.set_context("content")


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class HeldLinksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        cls.home = cls.m.window_handles()[0]
        cls.other = cls.call("return P.create({name: 'Bancos'});")
        cls.current = cls.call("return (await P.current()).id;")
        cls.addons = tempfile.TemporaryDirectory(prefix="nulavio-held-")
        cls.count = 0

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.addons.cleanup()

    @classmethod
    def call(cls, body: str, *args):
        result = chrome_async(cls.m, body, args)
        if "error" in result:
            raise AssertionError(f"call failed: {result['error']}")
        return result["ok"]

    def setUp(self):
        # Recorders instead of what would open another profile or switch to one.
        self.call(
            "R.__calls = []; R.openIn = async (...a) => { R.__calls.push(['openIn', ...a]); return {action: 'delivered'}; };"
            "P.__calls = []; P.switchTo = async (...a) => { P.__calls.push(['switchTo', ...a]); return {action: 'delivered'}; };"
        )

    def tearDown(self):
        self.m.switch_to(self.home)
        self.call("delete R.openIn; delete R.__calls; delete P.switchTo; delete P.__calls;")

    def message(self, key: str) -> str:
        return self.m.execute("return browser.i18n.getMessage(arguments[0]);", [key])

    def calls(self) -> list:
        return self.call("return [...R.__calls, ...P.__calls];")

    def open_from_another_extension(self, page: str) -> dict:
        """Install an extension that opens `page` (a Shell path with its query) in a new tab, and go to that tab."""
        type(self).count += 1
        directory = Path(self.addons.name) / f"opener-{self.count}"
        directory.mkdir()
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "manifest_version": 2,
                    "name": "Opener",
                    "version": "1.0",
                    "browser_specific_settings": {"gecko": {"id": f"opener-{self.count}@example.invalid"}},
                    "background": {"scripts": ["background.js"]},
                }
            )
        )
        (directory / "background.js").write_text(f"browser.tabs.create({{url: {json.dumps(self.base + page)}}});\n")
        before = set(self.m.window_handles())
        self.m.install_addon(str(directory), temporary=True)
        opened = harness.wait_until(lambda: set(self.m.window_handles()) - before, timeout=20)
        self.assertTrue(opened, "the other extension opened no tab")
        self.m.switch_to(next(iter(opened)))
        path = page.split("?", 1)[0]
        # The engine loads the Shell's page for the other extension: the scenario these pages must withstand.
        self.assertTrue(harness.wait_until(lambda: self.m.current_url().startswith(self.base + path), 20), self.m.current_url())
        state = harness.wait_until(lambda: (s := self.m.execute(PAGE))["ready"] and s, timeout=20)
        self.assertTrue(state, self.m.execute(PAGE))
        return state

    def press_every_button(self) -> None:
        """Click each button that could open something elsewhere (not "open here", "don't open" or "close"). A page
        that closes its tab after a click has done what the click asked: what it called is in the recorders."""
        for index in range(len(self.m.execute(PAGE)["buttons"])):
            try:
                self.m.execute(
                    "const b = [...document.querySelectorAll('#actions button, #alternatives button, #go-real')]"
                    ".filter(e => !e.hidden && e.checkVisibility() && !e.disabled"
                    " && !/Abrir aqui|Open here|Não abrir|Don.t open|Fechar|Close/.test(e.textContent))[arguments[0]];"
                    "b?.click();",
                    [index],
                )
            except MarionetteError:
                return  # the tab was closed

    def test_01_the_blocked_page_offers_no_other_profile_from_its_address(self):
        page = self.open_from_another_extension(
            f"routing/blocked.html?by=default&why=launch&p={self.other}&u={ELSEWHERE.replace('&', '%26')}"
        )
        self.press_every_button()
        self.assertFalse(harness.wait_until(self.calls, timeout=3), self.calls())
        self.assertNotIn("Bancos", page["text"], page)
        self.assertIsNone(page["url"], page)

    def test_02_the_ask_page_takes_no_rule_and_address_from_its_address(self):
        rule = self.call(
            "return R.addRule({site: 'banco.example', match: 'host', action: 'ask', profileId: args[0]});", self.other
        )
        try:
            page = self.open_from_another_extension(f"routing/ask.html?u={ELSEWHERE.replace('&', '%26')}&r={rule}")
            self.press_every_button()
            self.assertFalse(harness.wait_until(self.calls, timeout=3), self.calls())
            self.assertNotIn("Bancos", page["text"], page)
            self.assertIsNone(page["url"], page)
            rules = self.call("return (await R.state()).rules;")
            self.assertEqual([r["action"] for r in rules if r["id"] == rule], ["ask"], "the rule was changed")
        finally:
            self.call("await R.removeRule(args[0]);", rule)

    def test_03_the_unlock_page_opens_no_address_from_its_address(self):
        page = self.open_from_another_extension(f"vault/unlock.html?p={self.other}&u={ELSEWHERE.replace('&', '%26')}")
        self.press_every_button()
        harness.wait_until(self.calls, timeout=3)
        self.assertEqual([c for c in self.calls() if c[0] == "openIn"], [], "an address from the page's own address was opened")
        self.assertNotIn("elsewhere.example", page["text"], page)
        self.assertIsNone(page["url"], page)

    def test_04_the_look_alike_warning_names_only_what_the_module_finds(self):
        page = self.open_from_another_extension(
            "passwords/lookalike.html?url=https%3A%2F%2Fbanco.example%2Flogin&site=banco.example&similar=elsewhere.example"
        )
        self.assertEqual(page["state"], "invalid", page)  # no saved login in this profile: nothing to compare
        self.assertNotIn("elsewhere.example", page["text"], page)
        # The tab's title is the page's one title, as with a pair: another extension can read a tab's title.
        self.assertEqual(page["title"], self.message("lookalikeTitle"), page)
        self.assertEqual(self.call("return W.listConfirmed();"), [])

    def test_05_a_held_link_is_shown_only_on_its_own_page_and_for_its_own_profile(self):
        held = self.call(
            "return R.hold('vault/unlock.html', {u: args[0], p: args[1]});", "https://held.example/page", self.current
        )
        # The unlock page's own `p` names another profile: the held record decides.
        page = self.open_from_another_extension(f"vault/unlock.html?p={self.other}&h={held}")
        self.assertEqual(page["url"], "https://held.example/page", page)
        self.assertEqual(page["state"], "not-locked", page)
        self.m.execute("document.querySelector('#alternatives button').click();")
        self.assertTrue(harness.wait_until(self.calls, timeout=10))
        self.assertEqual(self.calls(), [["openIn", self.current, "https://held.example/page"]])
        self.m.switch_to(self.home)
        self.call("R.__calls.length = 0;")
        # The same id on another kind of page shows nothing it could act on.
        page = self.open_from_another_extension(f"routing/blocked.html?h={held}")
        self.assertIsNone(page["url"], page)
        self.press_every_button()
        self.assertFalse(harness.wait_until(self.calls, timeout=3), self.calls())

    def test_06_with_a_saved_login_the_warning_shows_and_remembers_only_the_modules_pair(self):
        real, fake = "https://paypal.example", "https://paypa1.example/login"  # the pair test_passwords uses
        self.call(
            "const info = Cc['@mozilla.org/login-manager/loginInfo;1'].createInstance(Ci.nsILoginInfo);"
            "info.init(args[0], args[0], null, 'tester', 'artificial-pass-1', 'username', 'password');"
            "await Services.logins.addLoginAsync(info);",
            real,
        )
        try:
            self.assertEqual(
                self.call("return W.checkLogin(args[0]);", fake),
                {"suspicious": True, "site": "paypa1.example", "similar": "paypal.example"},
            )
            # The page's own `site` and `similar` name another pair.
            page = self.open_from_another_extension(
                f"passwords/lookalike.html?url={quote(fake, safe='')}&site=elsewhere.example&similar=elsewhere.example"
            )
            self.assertEqual(page["state"], "ready", page)
            self.assertIn("paypal.example", page["text"], page)
            self.assertNotIn("elsewhere.example", page["text"], page)
            self.assertEqual(page["title"], self.message("lookalikeTitle"), page)  # the same title as with nothing to compare
            self.m.execute("document.getElementById('continue').click();")
            self.m.switch_to(self.home)  # the tab goes on to the address it was opened for
            confirmed = harness.wait_until(lambda: self.call("return W.listConfirmed();"), timeout=10)
            self.assertEqual(confirmed, [{"site": "paypa1.example", "similar": "paypal.example"}])
        finally:
            self.m.switch_to(self.home)
            self.call(
                "W.removeConfirmed('paypa1.example', 'paypal.example');"
                "for (const login of await Services.logins.getAllLogins()) { await Services.logins.removeLoginAsync(login); }"
            )

    def test_07_the_default_destination_page_tries_again_only_the_profile_it_held(self):
        held = self.call(
            "return R.hold('routing/blocked.html', {u: args[0], p: args[1], why: 'launch', by: 'default'});",
            "https://held.example/default",
            self.other,
        )
        page = self.open_from_another_extension(f"routing/blocked.html?h={held}&p={self.current}")
        self.assertEqual(page["url"], "https://held.example/default", page)
        self.assertIn("Bancos", page["buttons"][0][1], page)  # "try again" names the held link's profile
        self.m.execute("document.querySelector('#actions button').click();")
        self.m.switch_to(self.home)  # the page closes its tab after the call
        self.assertTrue(harness.wait_until(self.calls, timeout=10))
        self.assertEqual(self.calls(), [["openIn", self.other, "https://held.example/default"]])


if __name__ == "__main__":
    unittest.main()
