"""UX7 motion on the real build: reduced motion stops what moves, never what appears late on purpose.

Headless, throwaway profile.
"""

from __future__ import annotations

import time
import unittest

import harness


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class MotionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")

    @classmethod
    def tearDownClass(cls):
        cls.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")
        cls.session.cleanup()

    def open(self, page: str, ready: str) -> None:
        self.m.navigate(self.base + page)
        self.assertTrue(harness.wait_until(lambda: self.m.execute(ready), 20), page)

    def test_01_reduced_motion_keeps_the_delayed_reveals(self):
        """The reduce guard used to set animation: none, which also cancelled three 0 s animations
        that reveal content after a delay: the new tab's fallback (if its script stops), the list
        placeholders and the security moments' "still loading" line. Now they still appear."""
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 1);")
        reduced = "return matchMedia('(prefers-reduced-motion: reduce)').matches;"
        # 1. The new tab, as if its script never marked it painted.
        self.open("newtab/newtab.html", "return document.documentElement.hasAttribute('data-painted');")
        self.assertTrue(self.m.execute(reduced))
        self.m.execute("document.documentElement.removeAttribute('data-painted');")
        hidden = "return getComputedStyle(document.querySelector('.page')).visibility;"
        self.assertEqual(self.m.execute(hidden), "hidden")
        time.sleep(0.9)
        self.assertEqual(self.m.execute(hidden), "visible", "the new tab stayed invisible")
        # 2. A list still loading shows its placeholder rows after 400 ms.
        self.open("settings/settings.html#integrations", "return document.documentElement.dataset.ready === 'true';")
        probe = (
            "const ul = document.createElement('ul'); ul.className = 'list'; ul.id = 'probe';"
            "ul.setAttribute('aria-busy', 'true'); document.querySelector('#integrations .card').append(ul);"
            "return getComputedStyle(ul).visibility;"
        )
        self.assertEqual(self.m.execute(probe), "hidden")
        time.sleep(0.7)
        self.assertEqual(self.m.execute("return getComputedStyle(document.getElementById('probe')).visibility;"), "visible")
        # 3. A security moment that is still loading says so after 400 ms.
        self.open("passwords/lookalike.html", "return document.readyState === 'complete';")
        moment = (
            "const ctx = document.querySelector('.moment__context');"
            "if (!ctx) return null; ctx.dataset.loading = 'Carregando…'; document.body.dataset.state = 'loading';"
            "return getComputedStyle(ctx, '::after').visibility;"
        )
        self.assertEqual(self.m.execute(moment), "hidden")
        time.sleep(0.7)
        after = "return getComputedStyle(document.querySelector('.moment__context'), '::after').visibility;"
        self.assertEqual(self.m.execute(after), "visible")
        self.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")

    def toggle_sidebar(self):
        """Press the sidebar button once; the launcher's animations as the engine started them."""
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(
                "const done = arguments[arguments.length - 1];"
                "(async () => {"
                "  await SidebarController.waitUntilStable();"
                "  SidebarController.handleToolbarButtonClick();"
                "  let seen = null;"
                "  for (let i = 0; i < 100 && !seen; i++) {"
                "    await new Promise(r => setTimeout(r, 10));"
                "    const running = SidebarController._ongoingAnimations;"
                "    const timing = a => { const t = a.effect.getTiming(); return [t.duration, t.easing]; };"
                "    if (running.length) seen = running.map(timing);"
                "  }"
                "  await SidebarController.waitUntilStable();"
                "  done({seen, expanded: SidebarController.getUIState().launcherExpanded});"
                "})();"
            )
        finally:
            self.m.set_context("content")

    def test_02_the_sidebar_moves_on_the_motion_tokens(self):
        """UX7-B: the launcher narrows in 160 ms and widens in 220 ms on the standard curve (patch 0008 and
        firefox-branding.js); under reduced motion the engine starts no animation."""
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
        layout = (
            'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
        )
        self.m.set_context("chrome")
        try:
            self.m.execute_async(
                f"const done = arguments[arguments.length - 1]; {layout}.apply(window, 'lateral').then(() => done(true));"
            )
        finally:
            self.m.set_context("content")
        curve = "cubic-bezier(0.2, 0, 0, 1)"
        first = self.toggle_sidebar()
        second = self.toggle_sidebar()
        by_state = {first["expanded"]: first["seen"], second["expanded"]: second["seen"]}
        self.assertTrue(by_state[False], "no animation when the launcher narrowed")
        self.assertTrue(by_state[True], "no animation when the launcher widened")
        self.assertEqual({tuple(a) for a in by_state[False]}, {(160, curve)})
        self.assertEqual({tuple(a) for a in by_state[True]}, {(220, curve)})
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 1);")
        try:
            # The engine follows the system setting live (gReduceMotion); wait until it has.
            noticed = "return window.gReduceMotion === true;"
            self.assertTrue(harness.wait_until(lambda: self.m.chrome(noticed), 10))
            for _ in range(2):
                self.assertIsNone(self.toggle_sidebar()["seen"], "an animation ran under reduced motion")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")


if __name__ == "__main__":
    unittest.main()
