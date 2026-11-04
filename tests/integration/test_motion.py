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

    # -- UX7-C: calm surfaces arrive; warnings and critical consent never move ---------------------

    ANIMATIONS = (
        "return (arguments[0] ? [...document.querySelectorAll(arguments[0])] : [document])"
        ".flatMap(e => e.getAnimations({subtree: true}))"
        ".map(a => [a.constructor.name, (a.effect.pseudoElement || '') + (a.transitionProperty || a.animationName),"
        " a.effect.getComputedTiming().duration,"
        # A CSS animation's curve is on its keyframes: read it from the element's computed style.
        " a.animationName ? getComputedStyle(a.effect.target).animationTimingFunction : a.effect.getTiming().easing]);"
    )

    def animations(self, selector: str = "") -> list:
        return self.m.execute(self.ANIMATIONS, [selector])

    def test_03_calm_surfaces_arrive_on_the_tokens_and_warnings_never_move(self):
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
        self.open("settings/settings.html", "return document.documentElement.dataset.ready === 'true';")
        dialog = (
            "const d = document.createElement('dialog'); d.className = arguments[0]; d.id = 'probe-dialog';"
            "d.innerHTML = '<form class=\"dialog__form\"><p>Teste</p></form>'; document.body.append(d); d.showModal();"
        )
        enter = "cubic-bezier(0, 0, 0, 1)"
        self.m.execute(dialog, ["dialog"])
        moving = sorted(map(tuple, self.animations("#probe-dialog")))
        self.assertEqual(
            moving,
            [
                ("CSSTransition", "::backdropopacity", 180, enter),
                ("CSSTransition", "opacity", 180, enter),
                ("CSSTransition", "translate", 180, enter),
            ],
        )
        self.m.execute("document.getElementById('probe-dialog').remove();")
        for kind in ("dialog dialog--critical", "dialog dialog--danger"):
            with self.subTest(kind=kind):
                self.m.execute(dialog, [kind])
                self.assertEqual(self.animations("#probe-dialog"), [])
                self.m.execute("document.getElementById('probe-dialog').remove();")
        toast = (
            "const s = document.getElementById('status'); s.removeAttribute('data-inline');"
            "s.dataset.level = arguments[0]; s.textContent = ''; s.offsetWidth; s.textContent = 'Salvo.';"
        )
        self.m.execute(toast, ["ok"])
        self.assertEqual(
            sorted(map(tuple, self.animations("#status"))),
            [("CSSTransition", "opacity", 120, enter), ("CSSTransition", "translate", 120, enter)],
        )
        for level in ("warn", "error"):
            with self.subTest(level=level):
                self.m.execute("document.getElementById('status').textContent = '';")
                self.m.execute(toast, [level])
                self.assertEqual(self.animations("#status"), [])
        self.m.execute("document.getElementById('status').textContent = '';")

    def test_04_the_profile_arrives_on_the_new_tab_and_nothing_moves_under_reduce(self):
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
        self.open("newtab/newtab.html", "return document.documentElement.hasAttribute('data-painted');")
        chip = self.animations(".here__who > .chip")
        self.assertEqual([tuple(a) for a in chip], [("CSSAnimation", "nv-chip-in", 180, "cubic-bezier(0, 0, 0, 1)")])
        self.assertEqual(self.animations(".here__who .badge"), [])
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 1);")
        try:
            self.open("newtab/newtab.html", "return document.documentElement.hasAttribute('data-painted');")
            self.assertTrue(all(a[2] == 0 for a in self.animations()), self.animations())
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")

    def test_05_the_create_sheet_enters_and_leaves_at_once(self):
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
        self.open("profiles/popup.html", "return document.documentElement.dataset.ready === 'true';")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#new-profile")})
        self.assertIn(
            ("CSSTransition", "opacity", 180, "cubic-bezier(0, 0, 0, 1)"), [tuple(a) for a in self.animations("#sheet")]
        )
        closed = self.m.execute(
            "document.getElementById('sheet-back').click();"
            "return [document.getElementById('sheet').hidden, getComputedStyle(document.getElementById('sheet')).display,"
            " document.activeElement.id];"
        )
        self.assertEqual(closed, [True, "none", "new-profile"])


if __name__ == "__main__":
    unittest.main()
