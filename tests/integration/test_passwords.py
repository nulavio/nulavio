"""Passwords on the Nulavio build (S17): provider chooser (flows B, H) and look-alike login warning (flow D).

Artificial data only: one throwaway login for a fixture site, served from
127.0.0.1 under two names (the real one and a look-alike) through the engine's
own local-domains pref, test profile only. Installing the pinned Proton Pass
from addons.mozilla.org runs only with NULAVIO_NETWORK_TESTS=1.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

PASSWORDS = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPasswords.sys.mjs")'
REAL, FAKE = "paypal.example", "paypa1.example"


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise AssertionError(result["error"])
    return result["ok"]


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class PasswordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        port = cls.server.port
        cls.real = f"http://{REAL}:{port}"
        cls.fake = f"http://{FAKE}:{port}"
        # Test profile only: both names reach the fixture server; HTTPS-Only exceptions for them.
        chrome_async(
            cls.m,
            "Services.prefs.setStringPref('network.dns.localDomains', args[2]);"
            "for (const origin of [args[0], args[1]]) {"
            " const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin(origin);"
            " Services.perms.addFromPrincipal(p, 'https-only-load-insecure', Ci.nsIPermissionManager.ALLOW_ACTION); }"
            "const info = Cc['@mozilla.org/login-manager/loginInfo;1'].createInstance(Ci.nsILoginInfo);"
            "info.init(args[0], args[0], null, 'tester', 'artificial-pass-1', 'username', 'password');"
            "await Services.logins.addLoginAsync(info); return true;",
            [cls.real, cls.fake, f"{REAL},{FAKE}"],
        )
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        cls.shots = harness.artifacts_dir() / "passwords"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def focus_password(self, origin: str) -> str:
        self.m.navigate(origin + "/login")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#password")})
        time.sleep(1.5)
        return self.m.current_url()

    def shoot(self, name: str, keep: str | None = None) -> None:
        for scheme in ("light", "dark"):
            self.m.execute(
                "document.documentElement.dataset.theme = arguments[0]; document.body.style.display = 'none';"
                "document.body.offsetHeight; document.body.style.display = '';"
                "for (const s of arguments[1] ? document.querySelectorAll('section.section') : []) {"
                " s.hidden = s.id !== arguments[1]; }",
                [scheme, keep],
            )
            time.sleep(0.3)
            (self.shots / f"{name}-{scheme}.png").write_bytes(self.m.screenshot_png(full=True))
        self.m.execute("delete document.documentElement.dataset.theme;")

    def test_01_lookalike_rules(self):
        cases = {
            "paypa1.com": "paypal.com",
            "pаypal.com": "paypal.com",  # Cyrillic а
            "paypal-secure-login.com": "paypal.com",
            "paypal.com.account-check.net": "paypal.com",
            "paypall.com": "paypal.com",
            "www.paypal.com": None,
            "example.com": None,
            "github.com": None,
            "nubank.com.br": None,
            "nubnak.com.br": "nubank.com.br",
            "bb-login.com.br": None,  # "bb" is too short to compare
        }
        saved = ["paypal.com", "nubank.com.br", "bb.com.br"]
        got = chrome_async(
            self.m,
            f"const {{ lookalikeOf }} = {PASSWORDS}; const out = {{}};"
            "for (const host of Object.keys(args[0])) { out[host] = lookalikeOf(host, args[1]); } return out;",
            [cases, saved],
        )
        self.assertEqual(got, cases)

    def test_02_lookalike_site_shows_the_warning_and_continue_is_remembered(self):
        url = self.focus_password(self.fake)
        self.assertTrue(url.startswith(self.base + "passwords/lookalike.html"), url)
        text = self.m.execute("return document.querySelector('main').textContent;")
        self.assertIn(REAL, text)
        self.assertIn(FAKE, text)
        # What "continue" does is on the button and right next to it, with where to undo it (SB-10).
        page = self.m.execute(
            "const b = document.getElementById('continue');"
            "const note = document.getElementById(b.getAttribute('aria-describedby'));"
            "return {label: b.textContent.trim(), note: note?.textContent ?? '', focused: document.activeElement.id};"
        )
        self.assertEqual(page["label"], "Continuar e não avisar de novo para este par")
        for words in (FAKE, REAL, "Configurações › Senhas"):
            self.assertIn(words, page["note"])
        self.assertEqual(page["focused"], "go-real")
        self.shoot("lookalike")
        # If the choice cannot be saved, the site does not open as if it had been.
        chrome_async(self.m, f"{PASSWORDS}.NulavioPasswords.dismiss = () => {{ throw new Error('disk full'); }}; return true;")
        try:
            self.m.execute("document.getElementById('continue').click();")
            failed = harness.wait_until(
                lambda: self.m.execute("return document.getElementById('status').dataset.level;") == "error", 10
            )
            self.assertTrue(failed, "no error shown")
            self.assertTrue(self.m.current_url().startswith(self.base + "passwords/lookalike.html"))
            self.assertIn("Nada foi alterado", self.m.execute("return document.getElementById('status').textContent;"))
        finally:
            chrome_async(self.m, f"delete {PASSWORDS}.NulavioPasswords.dismiss; return true;")
        self.m.execute("document.getElementById('continue').click();")
        self.assertTrue(harness.wait_until(lambda: self.m.current_url().startswith(self.fake), 10))
        self.assertTrue(self.focus_password(self.fake).startswith(self.fake))  # not asked again for this pair

    def test_02b_the_warning_page_without_a_site_offers_only_the_way_out(self):
        """Audit 2026-11 S-01: opened without a site to compare, the page says so. No warning, no empty
        address, no button without a name and none that would do nothing."""
        self.m.navigate(self.base + "passwords/lookalike.html")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.body.dataset.state === 'invalid';"), 10))
        shown = self.m.execute(
            "const seen = s => [...document.querySelectorAll(s)].filter(e => e.checkVisibility());"
            "return {buttons: seen('button').map(b => b.textContent.trim()),"
            " callouts: seen('.callout--warning, .callout svg').length,"
            " address: seen('#address').length, headline: document.getElementById('headline').textContent,"
            " said: seen('.callout--info[role=status]').map(e => e.textContent.trim()), focus: document.activeElement.id};"
        )
        msg = lambda key: self.m.execute("return browser.i18n.getMessage(arguments[0]);", [key])  # noqa: E731
        self.assertEqual(shown["buttons"], [msg("warnCloseTab")], shown)
        self.assertEqual((shown["callouts"], shown["address"]), (0, 0), shown)
        self.assertEqual(shown["headline"], msg("lookalikeInvalidHeadline"))
        self.assertEqual(shown["said"], [msg("lookalikeInvalid")])
        self.assertEqual(shown["focus"], "go-real")
        self.assertIsNone(self.m.execute("return document.querySelector('.moment__severity');"), "no warning: no level")

    def test_03_the_real_site_is_never_warned(self):
        self.assertTrue(self.focus_password(self.real).startswith(self.real))

    def test_04_provider_chooser_shows_real_state(self):
        state = chrome_async(self.m, f"return await {PASSWORDS}.NulavioPasswords.state();")
        self.assertEqual(state["current"], "builtin")
        self.assertEqual(state["engineLogins"], 1)
        keepass = next(p for p in state["providers"] if p["key"] == "keepassxc")
        self.assertEqual(keepass["native"], {"required": True, "found": False})  # no KeePassXC in this HOME
        self.m.navigate(self.base + "settings/settings.html#passwords")
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 15)
        )
        rows = self.m.execute(
            "return [...document.querySelectorAll('#provider-list > li')].map(li => [li.dataset.provider, li.dataset.inUse]);"
        )
        self.assertEqual(rows, [["builtin", "true"], ["proton-pass", "false"], ["keepassxc", "false"], ["bitwarden", "false"]])
        self.assertIn("1 login", self.m.execute("return document.getElementById('engine-logins').textContent;"))
        self.shoot("settings", keep="passwords")

    def test_06_confirmed_sites_are_listed_in_settings_and_removing_one_brings_the_warning_back(self):
        self.m.navigate(self.base + "settings/settings.html#passwords")
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 15)
        )
        rows = self.m.execute(
            "return [...document.querySelectorAll('#confirmed-list > li')].map(li => [li.dataset.site, li.dataset.similar,"
            " li.querySelector('button').getAttribute('aria-label')]);"
        )
        self.assertEqual(rows, [[FAKE, REAL, f"Remover {FAKE}"]])
        self.assertTrue(self.m.execute("return document.getElementById('confirmed-empty').hidden;"))
        self.shoot("settings-confirmed", keep="passwords")
        self.m.execute("document.querySelector('#confirmed-list button').click();")
        emptied = harness.wait_until(lambda: self.m.execute("return !document.getElementById('confirmed-empty').hidden;"), 10)
        self.assertTrue(emptied, "the pair is still listed")
        after = self.m.execute(
            "return {rows: document.querySelectorAll('#confirmed-list > li').length, focused: document.activeElement.id,"
            " status: document.getElementById('status').textContent, level: document.getElementById('status').dataset.level};"
        )
        self.assertEqual((after["rows"], after["focused"], after["level"]), (0, "confirmed-heading", "ok"))
        self.assertIn(FAKE, after["status"])
        self.assertEqual(chrome_async(self.m, f"return {PASSWORDS}.NulavioPasswords.listConfirmed();"), [])
        url = self.focus_password(self.fake)
        self.assertTrue(url.startswith(self.base + "passwords/lookalike.html"), f"the warning did not come back: {url}")

    @unittest.skipUnless(os.environ.get("NULAVIO_NETWORK_TESTS") == "1", "downloads Proton Pass from addons.mozilla.org")
    def test_05_choosing_proton_pass_installs_the_pinned_version_and_switching_back_keeps_it(self):
        state = chrome_async(self.m, f"return await {PASSWORDS}.NulavioPasswords.choose('proton-pass');")
        self.assertEqual(state["current"], "proton-pass")
        proton = next(p for p in state["providers"] if p["key"] == "proton-pass")["extension"]
        self.assertTrue(proton["enabled"])
        self.assertEqual(proton["version"], proton["pinned"])
        self.assertFalse(self.m.chrome("return Services.prefs.getBoolPref('signon.rememberSignons');"))
        state = chrome_async(self.m, f"return await {PASSWORDS}.NulavioPasswords.choose('builtin');")
        self.assertEqual(state["current"], "builtin")
        proton = next(p for p in state["providers"] if p["key"] == "proton-pass")["extension"]
        self.assertTrue(proton["installed"])  # flow H: the extension is not removed
        self.assertEqual(state["engineLogins"], 1)  # saved logins are kept


if __name__ == "__main__":
    unittest.main()
