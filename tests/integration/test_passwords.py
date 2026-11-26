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
import settings_page
from marionette import MarionetteError

PASSWORDS = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPasswords.sys.mjs")'
REAL, FAKE = "paypal.example", "paypa1.example"
PRIMARY = "artificial-primary-1"  # a throwaway profile's Primary Password (test_07)
TOKEN = "const token = Cc['@mozilla.org/security/internalkeytoken;1'].createInstance(Ci.nsIPKCS11Token);"


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

    def on_warning(self) -> bool:
        return self.m.current_url().startswith(self.base + "passwords/lookalike.html")

    def script_focus(self, origin: str) -> None:
        """The look-alike page focuses its own password field, with no input from the person."""
        self.m.navigate(origin + "/login")
        focused = self.m.execute("document.getElementById('password').focus(); return document.activeElement.id;")
        self.assertEqual(focused, "password")
        time.sleep(1.5)  # as long as focus_password gives the check; nothing may happen in it
        self.assertFalse(self.on_warning(), "checked on a focus the page gave itself")

    def slow_check(self, ms: int) -> None:
        """Until the test ends, each check waits `ms` first, as the first read of the saved logins can."""
        chrome_async(
            self.m,
            f"const p = {PASSWORDS}.NulavioPasswords; const real = Object.getPrototypeOf(p).checkLogin;"
            "const { setTimeout } = ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');"
            "p.checkLogin = async function (url) {"
            " await new Promise(r => setTimeout(r, args[0])); return real.call(this, url); };"
            "return true;",
            [ms],
        )
        self.addCleanup(chrome_async, self.m, f"delete {PASSWORDS}.NulavioPasswords.checkLogin; return true;")

    def test_01b_a_focus_the_page_gives_itself_is_not_checked_the_persons_key_is(self):
        self.script_focus(self.fake)
        self.m.send("WebDriver:ElementSendKeys", {"id": self.m.find_element("#password"), "text": "a"})
        self.assertTrue(harness.wait_until(self.on_warning, 10), self.m.current_url())

    def test_01c_a_click_in_a_field_the_page_focused_is_checked(self):
        self.script_focus(self.fake)
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#password")})
        self.assertTrue(harness.wait_until(self.on_warning, 10), self.m.current_url())

    def test_01d_a_change_of_address_inside_the_page_does_not_cancel_the_warning(self):
        self.slow_check(1500)
        self.m.navigate(self.fake + "/login")
        self.m.execute(
            "document.getElementById('password').addEventListener('focus', () =>"
            " setTimeout(() => history.replaceState(null, '', '/login?moved#elsewhere'), 100));"
        )
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#password")})
        self.assertTrue(harness.wait_until(self.on_warning, 10), self.m.current_url())
        # The page asks the module again which saved site the address imitates (as slow here as the first check).
        ready = "return document.documentElement?.dataset.ready === 'true';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(ready), 10))
        self.assertIn(self.fake + "/login", self.m.execute("return document.getElementById('address').textContent;"))

    def test_01e_a_page_the_tab_left_during_the_check_is_not_replaced_and_is_checked_on_return(self):
        self.slow_check(2000)
        self.m.navigate(self.fake + "/login")
        self.m.execute(
            "window.addEventListener('pageshow', e => { document.documentElement.dataset.restored = String(e.persisted); });"
        )
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#password")})
        self.m.navigate(self.real + "/login")  # while the check of the look-alike waits
        time.sleep(3)  # past the end of that check
        self.assertTrue(self.m.current_url().startswith(self.real), f"the warning replaced another page: {self.m.current_url()}")
        chrome_async(self.m, f"delete {PASSWORDS}.NulavioPasswords.checkLogin; return true;")
        self.m.send("WebDriver:Back")
        self.assertTrue(harness.wait_until(lambda: self.m.current_url().startswith(self.fake), 10), self.m.current_url())
        # Whether the page came back from the back-forward cache (the same document, told it was not decided)
        # or was loaded again: either way it is checked. Printed for the record of the run.
        restored = self.m.execute("return document.documentElement.dataset.restored ?? 'loaded again';")
        print(f"test_01e: back-forward cache restored the page: {restored}", file=sys.stderr)
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#password")})
        self.assertTrue(harness.wait_until(self.on_warning, 10), f"not checked after coming back: {self.m.current_url()}")

    def to_top(self) -> bool:
        try:
            self.m.send("WebDriver:SwitchToFrame", {})  # neither element nor id: the tab's page
            return True
        except MarionetteError:
            return False  # the tab was changing documents: try again

    def click_in_frame(self, page: str, setup: str) -> None:
        """Opens `page`, adds a frame to it (`setup`, in the page's script, sets up `f`) and clicks the frame's
        password field (#password), as the person would."""
        self.m.navigate(page)
        self.m.execute(
            "const f = document.createElement('iframe'); f.id = 'f';"
            "f.addEventListener('load', () => { document.documentElement.dataset.framed = 'yes'; }, { once: true });"
            + setup
            + "document.body.append(f);"
        )
        framed = "return document.documentElement.dataset.framed === 'yes';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(framed), 10), "the frame did not load")
        self.m.send("WebDriver:SwitchToFrame", {"element": self.m.find_element("#f")})
        try:
            self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#password")})
        finally:
            self.assertTrue(harness.wait_until(self.to_top, 10), "could not go back to the tab's page")

    def warning_params(self) -> dict:
        return self.m.execute(
            "const p = new URLSearchParams(location.search);"
            "return { url: p.get('url'), page: p.has('page') ? p.get('page') : null };"
        )

    def test_01f_a_lookalike_frame_in_another_sites_page_shows_the_warning_and_continue_goes_back_to_that_page(self):
        home = self.real + "/page/home"
        self.click_in_frame(home, f"f.src = {self.fake + '/login'!r};")
        self.assertTrue(harness.wait_until(self.on_warning, 10), self.m.current_url())
        ready = "return document.documentElement?.dataset.ready === 'true';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(ready), 10))
        self.assertEqual(self.warning_params(), {"url": self.fake + "/login", "page": home})
        shown = self.m.execute(
            "return { address: document.getElementById('address').textContent,"
            " text: document.querySelector('main').textContent, onward: document.getElementById('continue').checkVisibility() };"
        )
        self.assertEqual(shown["address"], self.fake + "/login")  # the frame's site is the one named
        self.assertIn(REAL, shown["text"])
        self.assertTrue(shown["onward"])
        forget = f"{PASSWORDS}.NulavioPasswords.removeConfirmed(args[0], args[1]); return true;"
        self.addCleanup(chrome_async, self.m, forget, [FAKE, REAL])  # test_02 and test_06 expect no pair before them
        self.m.execute("document.getElementById('continue').click();")
        self.assertTrue(harness.wait_until(lambda: self.m.current_url() == home, 10), self.m.current_url())

    def test_01g_password_fields_in_srcdoc_data_and_blob_frames_of_a_lookalike_page_are_checked(self):
        field = "<!doctype html><input id=password type=password>"
        setups = {
            "srcdoc": f"f.srcdoc = {field!r};",
            "data": f"f.src = 'data:text/html,' + encodeURIComponent({field!r});",
            "blob": f"f.src = URL.createObjectURL(new Blob([{field!r}], {{ type: 'text/html' }}));",
        }
        for kind, setup in setups.items():
            with self.subTest(kind):
                self.click_in_frame(self.fake + "/page/" + kind, setup)
                self.assertTrue(harness.wait_until(self.on_warning, 10), f"{kind}: {self.m.current_url()}")
                params = self.warning_params()
                self.assertTrue(params["url"].startswith(self.fake + "/"), params)

    def test_01h_a_frame_of_another_site_in_the_real_sites_page_is_not_warned(self):
        home = self.real + "/page/home"
        self.click_in_frame(home, f"f.src = {'http://localhost:' + str(self.server.port) + '/login'!r};")
        time.sleep(1.5)  # as long as focus_password gives the check; nothing may happen in it
        self.assertEqual(self.m.current_url(), home)

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
        # The settings page shows the same (ADR 0011: "Quem guarda as senhas", in Senhas e preenchimento).
        settings_page.open_pane(self.m, "passwordsAutofill")
        rows = settings_page.wait_rows(self.m, "nulavio-passwords-providers", len, "moz-box-item.nulavio-provider")
        self.assertEqual(
            [[row["data"]["provider"], row["data"]["inUse"]] for row in rows],
            [
                ["builtin", "true"],
                ["proton-pass", "false"],
                ["keepassxc", "false"],
                ["bitwarden", "false"],
                ["1password", "false"],
            ],
        )
        self.assertIn("1 login", settings_page.wait_control(self.m, "nulavio-passwords-logins")["label"])
        settings_page.shoot(self.m, self.shots, "settings")

    def test_06_confirmed_sites_are_listed_in_settings_and_removing_one_brings_the_warning_back(self):
        settings_page.open_pane(self.m, "passwordsAutofill")
        pairs, none = "moz-box-item.nulavio-confirmed", "moz-box-item.nulavio-confirmed-none"
        rows = settings_page.wait_rows(self.m, "nulavio-confirmed-sites", len, pairs)
        self.assertEqual(
            [[row["data"]["site"], row["data"]["similar"], row["buttons"][0]["named"]] for row in rows],
            [[FAKE, REAL, f"Remover {FAKE}"]],
        )
        self.assertEqual(settings_page.rows(self.m, "nulavio-confirmed-sites", none), [])
        settings_page.shoot(self.m, self.shots, "settings-confirmed")
        settings_page.click_row(self.m, "nulavio-confirmed-sites", FAKE, "remove", pairs)
        emptied = settings_page.wait_rows(self.m, "nulavio-confirmed-sites", len, none)  # the pair is no longer listed
        self.assertEqual(emptied[0]["label"], "Nenhum site confirmado.")
        self.assertEqual(settings_page.rows(self.m, "nulavio-confirmed-sites", pairs), [])
        self.assertIn(FAKE, settings_page.wait_control(self.m, "nulavio-confirmed-said")["message"])
        self.assertEqual(chrome_async(self.m, f"return {PASSWORDS}.NulavioPasswords.listConfirmed();"), [])
        url = self.focus_password(self.fake)
        self.assertTrue(url.startswith(self.base + "passwords/lookalike.html"), f"the warning did not come back: {url}")

    def test_07_a_primary_password_not_entered_is_not_asked_for_and_is_waited_for(self):
        """#708: reading the saved logins decrypts them, which asks for a Primary Password not yet entered, and
        the check runs on any site with a password field. So nothing is read, and nothing asked, until the person
        enters it; then their next input in the field is checked (R41)."""
        other = f"http://other.example:{self.server.port}"
        locked = chrome_async(
            self.m,
            TOKEN + "await token.changePassword('', args[0]);"
            # A change to the saved logins, so the module reads them again rather than keep what it read before.
            "const info = Cc['@mozilla.org/login-manager/loginInfo;1'].createInstance(Ci.nsILoginInfo);"
            "info.init(args[1], args[1], null, 'tester', 'artificial-pass-2', 'username', 'password');"
            "await Services.logins.addLoginAsync(info); await token.logout();"
            "return token.hasPassword && !Services.logins.isLoggedIn;",
            [PRIMARY, other],
        )
        self.addCleanup(
            chrome_async,
            self.m,
            TOKEN + "await token.changePassword(args[0], '');"
            "for (const l of await Services.logins.searchLoginsAsync({ origin: args[1] })) {"
            " await Services.logins.removeLoginAsync(l); } return true;",
            [PRIMARY, other],
        )
        self.assertTrue(locked, "the Primary Password was not set, or the token not locked")
        url = self.focus_password(self.fake)
        self.assertFalse(self.m.chrome("return Services.logins.uiBusy;"), "the Primary Password was asked for")
        self.assertTrue(url.startswith(self.fake), f"warned without reading the saved logins: {url}")
        # The person enters it elsewhere (the token's own check logs it in, with no prompt here).
        unlock = "await token.changePassword(args[0], args[0]); return Services.logins.isLoggedIn;"
        entered = chrome_async(self.m, TOKEN + unlock, [PRIMARY])
        self.assertTrue(entered)
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#password")})  # the same page
        self.assertTrue(harness.wait_until(self.on_warning, 10), f"not checked once entered: {self.m.current_url()}")

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
