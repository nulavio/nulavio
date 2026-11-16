"""#152: a search provider's own extensions, installed from Settings only on a click.

What this proves: each pinned file installs through the Shell (its SHA-256 checked by the engine, then Mozilla's
signature), turns on, and is allowed in private windows; nothing is installed before the click; with Nulavio's Kagi
in the profile, Kagi's own extension leaves that engine in place and the default unchanged.
What it does not prove: signing in, Privacy Pass tokens, a Session Link (no account is ever used by the tests).
Downloads from addons.mozilla.org: runs with NULAVIO_NETWORK_TESTS=1.
"""

from __future__ import annotations

import os
import unittest

import harness

S = 'const S = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioSearch.sys.mjs").NulavioSearch;'


@unittest.skipUnless(
    harness.nulavio_engine() and os.environ.get("NULAVIO_NETWORK_TESTS") == "1",
    "the Nulavio build, and NULAVIO_NETWORK_TESTS=1 (downloads from addons.mozilla.org)",
)
class SearchExtensionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def run_async(self, body: str, *args):
        self.m.set_context("chrome")
        try:
            script = "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);" + S
            return self.m.execute_async(
                script
                + "(async () => {"
                + body
                + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));",
                list(args),
            )
        finally:
            self.m.set_context("content")

    def test_01_kagis_extensions_install_on_request_and_run_in_private_windows(self):
        before = self.run_async("return (await S.accountExtensions()).kagi;")["ok"]
        self.assertEqual([(e["key"], e["installed"]) for e in before], [("kagi-privacy-pass", False), ("kagi-search", False)])
        self.run_async("return S.choose({provider: 'kagi', privateToo: false});")
        engines = "return (await S.list()).map(e => [e.name, e.kind, e.isDefault]);"
        with_kagi = self.run_async(engines)["ok"]
        for key in ("kagi-privacy-pass", "kagi-search"):
            with self.subTest(key=key):
                done = self.run_async("return S.installAccountExtension('kagi', args[0]);", key)
                self.assertEqual(done.get("ok", {}).get("installed"), True, done)
                self.assertTrue(done["ok"]["active"] and done["ok"]["inPrivate"], done)
        # Nulavio's Kagi is still the one in the list, and still the default.
        self.assertEqual(self.run_async(engines)["ok"], with_kagi)
        self.assertEqual(
            self.run_async("return S.installAccountExtension('kagi', 'ublock-origin');")["error"], "unknown-extension"
        )
