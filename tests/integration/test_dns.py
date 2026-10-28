"""DNS choice on the Nulavio build (S15): the new tab asks once, Settings applies it, the engine obeys.

A local DNS-over-HTTPS resolver (tests/lib/doh_server.py) answers a name that
exists nowhere else, so a successful lookup proves the browser asked it.
Test-only prefs in the throwaway profile: trust the test CA, connect to the
resolver at 127.0.0.1 (bootstrap address) and accept its loopback answers.
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from doh_server import DohServer

PRIVACY = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs").NulavioPrivacy'
NAME = "lookup.nulavio-dns.example"


def resolve(m, name: str) -> list[str] | str:
    """Addresses for `name` through the engine's own resolver, or the error name."""
    script = (
        "const done = arguments[arguments.length - 1];"
        "Services.dns.clearCache(true);"
        "const listener = { onLookupComplete(req, rec, status) {"
        "  if (!Components.isSuccessCode(status)) { done(ChromeUtils.getXPCOMErrorName(status)); return; }"
        "  rec.QueryInterface(Ci.nsIDNSAddrRecord); const out = [];"
        "  while (rec.hasMore()) { out.push(rec.getNextAddrAsString()); } done(out); },"
        "  QueryInterface: ChromeUtils.generateQI(['nsIDNSListener']) };"
        "Services.dns.asyncResolve(arguments[0], Ci.nsIDNSService.RESOLVE_TYPE_DEFAULT,"
        "  Ci.nsIDNSService.RESOLVE_BYPASS_CACHE | Ci.nsIDNSService.RESOLVE_DISABLE_IPV6, null, listener,"
        "  Services.tm.currentThread, {});"
    )
    m.set_context("chrome")
    try:
        return m.execute_async(script, [name])
    finally:
        m.set_context("content")


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class DnsChoiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.doh = DohServer(Path(cls.tmp.name), {NAME}).start()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.m.chrome(
            "Cc['@mozilla.org/security/x509certdb;1'].getService(Ci.nsIX509CertDB).addCertFromBase64(arguments[0], 'C,,');"
            "Services.prefs.setStringPref('network.trr.bootstrapAddr', '127.0.0.1');"
            "Services.prefs.setBoolPref('network.trr.allow-rfc1918', true);"
            "Services.prefs.setStringPref('network.trr.confirmationNS', 'skip');",
            [cls.doh.ca_base64()],
        )
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        cls.shots = harness.artifacts_dir() / "dns"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
            cls.doh.stop()
        finally:
            cls.tmp.cleanup()

    def open(self, page: str) -> None:
        self.m.navigate(self.base + page)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 15)
        )

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

    def state(self) -> dict:
        self.m.set_context("chrome")
        try:
            return self.m.execute(f"return {PRIVACY}.dns();")
        finally:
            self.m.set_context("content")

    def test_01_new_tab_asks_once_and_keeping_the_system_resolver_is_explicit(self):
        self.assertEqual(self.state()["choice"], "default")
        self.open("newtab/newtab.html")
        self.assertFalse(self.m.execute("return document.getElementById('dns-choice').hidden;"))
        self.shoot("newtab-choice")
        self.m.execute("document.getElementById('dns-keep-system').click();")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.getElementById('dns-choice').hidden;"), 10))
        self.assertEqual(
            self.m.execute("return document.querySelector('[data-status=dns]').textContent;"), "Resolvedor do computador"
        )
        state = self.state()
        self.assertEqual((state["choice"], state["chosen"]), ("system", True))
        self.assertEqual(self.m.chrome("return Services.prefs.getIntPref('network.trr.mode');"), 5)  # off by choice
        self.open("newtab/newtab.html")
        self.assertTrue(self.m.execute("return document.getElementById('dns-choice').hidden;"))  # asked once

    def test_02_encrypted_only_uses_the_chosen_resolver_and_fails_closed(self):
        self.open("settings/settings.html#dns")
        self.m.execute(
            "const f = document.getElementById('dns-form'); f.elements.choice.value = 'strict';"
            "f.elements.provider.value = 'custom'; f.dispatchEvent(new Event('change'));"
            "f.elements.uri.value = arguments[0]; f.requestSubmit();",
            [self.doh.uri],
        )
        self.assertTrue(harness.wait_until(lambda: self.state()["choice"] == "strict", 10))
        self.assertEqual(self.state()["uri"], self.doh.uri)
        self.assertIn(self.doh.uri, self.m.execute("return document.getElementById('dns-current').textContent;"))
        self.shoot("settings", keep="dns")
        before = len(self.doh.queries)
        self.assertEqual(resolve(self.m, NAME), ["127.0.0.1"])  # only this resolver knows the name
        self.assertIn(NAME, self.doh.queries[before:])
        self.assertEqual(resolve(self.m, "localhost.nulavio-unknown.example"), "NS_ERROR_UNKNOWN_HOST")

    def test_03_back_to_the_system_resolver_sends_nothing_to_it(self):
        self.open("settings/settings.html#dns")
        self.m.execute("const f = document.getElementById('dns-form'); f.elements.choice.value = 'system'; f.requestSubmit();")
        self.assertTrue(harness.wait_until(lambda: self.state()["choice"] == "system", 10))
        before = len(self.doh.queries)
        self.assertNotEqual(resolve(self.m, NAME), ["127.0.0.1"])
        time.sleep(0.5)
        self.assertEqual(self.doh.queries[before:], [])

    def test_04_bad_resolver_addresses_are_refused(self):
        self.m.set_context("chrome")
        try:
            for uri in ("http://doh.example/dns-query", "https://user:pw@doh.example/dns-query", "not a url"):
                with self.subTest(uri=uri):
                    error = self.m.execute_async(
                        "const done = arguments[arguments.length - 1];"
                        f"try {{ {PRIVACY}.setDns({{choice: 'strict', provider: 'custom', uri: arguments[0]}});"
                        " done('accepted'); } catch (e) { done(e.code); }",
                        [uri],
                    )
                    self.assertIn(error, ("resolver-needs-https", "invalid-url"))
        finally:
            self.m.set_context("content")
        self.assertEqual(self.state()["choice"], "system")  # nothing changed

    def card(self) -> dict:
        return self.m.execute(
            "const card = document.getElementById('dns-choice');"
            "const shown = [...card.querySelectorAll('button, a.button')].filter(b => !b.closest('[hidden]'));"
            "return {hidden: card.hidden, encrypted: card.dataset.encrypted,"
            " buttons: shown.map(b => [b.id, b.textContent.trim(), b.classList.contains('button--primary')])};"
        )

    def test_05_when_dns_is_already_encrypted_keep_keeps_it_and_the_downgrade_says_so(self):
        # The engine's regional roll-out (doh-rollout.mode) encrypts lookups under the "default" choice (SPA-03).
        self.m.chrome(
            "for (const p of ['network.trr.mode', 'nulavio.dns.chosen']) Services.prefs.clearUserPref(p);"
            "Services.prefs.setIntPref('doh-rollout.mode', 2);"
        )
        try:
            self.assertTrue(harness.wait_until(lambda: self.state()["encryptedNow"], 10), self.state())
            self.assertEqual((self.state()["choice"], self.state()["chosen"]), ("default", False))
            self.open("newtab/newtab.html")
            card = self.card()
            self.assertEqual((card["hidden"], card["encrypted"]), (False, "true"))
            ids = [b[0] for b in card["buttons"]]
            self.assertEqual(ids, ["dns-keep-encrypted", "dns-choose-other", "dns-use-system"])
            labels = dict((b[0], b[1]) for b in card["buttons"])
            self.assertEqual(labels["dns-keep-encrypted"], "Manter criptografado (padrão atual)")
            self.assertEqual(labels["dns-choose-other"], "Escolher outro resolvedor…")
            self.assertEqual(labels["dns-use-system"], "Usar o resolvedor do computador (sem criptografia)")
            self.assertEqual([b[0] for b in card["buttons"] if b[2]], ["dns-keep-encrypted"], "keeping is the primary action")
            for button_id, label in labels.items():
                if button_id != "dns-keep-encrypted":
                    self.assertNotIn("manter", label.lower(), "a change is never labelled as keeping")
            self.shoot("newtab-choice-encrypted")
            self.m.execute("document.getElementById('dns-keep-encrypted').click();")
            self.assertTrue(
                harness.wait_until(lambda: self.m.execute("return document.getElementById('dns-choice').hidden;"), 10)
            )
            state = self.state()
            self.assertEqual((state["choice"], state["chosen"], state["encryptedNow"]), ("default", True, True))
            self.assertFalse(self.m.chrome("return Services.prefs.prefHasUserValue('network.trr.mode');"), "nothing changed")
            # The downgrade, when the person picks it, is the computer's resolver, off by choice.
            self.m.chrome("Services.prefs.clearUserPref('nulavio.dns.chosen');")
            self.open("newtab/newtab.html")
            self.m.execute("document.getElementById('dns-use-system').click();")
            self.assertTrue(harness.wait_until(lambda: self.state()["choice"] == "system", 10))
            self.assertEqual(self.m.chrome("return Services.prefs.getIntPref('network.trr.mode');"), 5)
        finally:
            self.m.chrome("Services.prefs.clearUserPref('doh-rollout.mode');")


if __name__ == "__main__":
    unittest.main()
