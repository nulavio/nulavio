"""UX7 motion on the real build: reduced motion stops what moves, never what appears late on purpose.

Headless, throwaway profile.
"""

from __future__ import annotations

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
        # Waited for, not slept through: on a busy machine the reveal can start later than its delay (a release
        # run's whole suite failed here once on a 0.7 s sleep and passed three times alone).
        self.assertTrue(harness.wait_until(lambda: self.m.execute(hidden) == "visible", 8), "the new tab stayed invisible")
        # 2. A list still loading shows its placeholder rows after 400 ms.
        self.open("settings/settings.html#integrations", "return document.documentElement?.dataset.ready === 'true';")
        probe = (
            "const ul = document.createElement('ul'); ul.className = 'list'; ul.id = 'probe';"
            "ul.setAttribute('aria-busy', 'true'); document.querySelector('#integrations .card').append(ul);"
            "return getComputedStyle(ul).visibility;"
        )
        self.assertEqual(self.m.execute(probe), "hidden")
        shown = "return getComputedStyle(document.getElementById('probe')).visibility;"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(shown) == "visible", 8), "the placeholder rows never showed")
        # 3. A security moment that is still loading says so after 400 ms.
        self.open("passwords/lookalike.html", "return document.readyState === 'complete';")
        moment = (
            "const ctx = document.querySelector('.moment__context');"
            "if (!ctx) return null; ctx.dataset.loading = 'Carregando…'; document.body.dataset.state = 'loading';"
            "return getComputedStyle(ctx, '::after').visibility;"
        )
        self.assertEqual(self.m.execute(moment), "hidden")
        after = "return getComputedStyle(document.querySelector('.moment__context'), '::after').visibility;"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(after) == "visible", 8), "the loading line never showed")
        self.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")

    def toggle_sidebar(self):
        """Press the sidebar button once; the timing of the engine's view transition (its groups' animations)."""
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(
                "const done = arguments[arguments.length - 1];"
                "(async () => {"
                "  await SidebarController.waitUntilStable();"
                "  SidebarController.handleToolbarButtonClick();"
                "  let seen = null;"
                "  for (let i = 0; i < 200 && !seen; i++) {"
                "    await new Promise(r => requestAnimationFrame(r));"
                "    const groups = document.getAnimations()"
                "      .filter(a => (a.effect.pseudoElement || '').startsWith('::view-transition-group('));"
                "    const timing = a => [a.effect.getComputedTiming().duration,"
                "      getComputedStyle(document.documentElement, a.effect.pseudoElement).animationTimingFunction];"
                "    if (groups.length) seen = groups.map(timing);"
                "  }"
                "  await SidebarController.waitUntilStable();"
                "  done({seen, expanded: SidebarController.getUIState().launcherExpanded});"
                "})();"
            )
        finally:
            self.m.set_context("content")

    def test_02_the_sidebar_moves_on_the_motion_tokens(self):
        """UX7-B: the launcher narrows in 160 ms and widens in 220 ms on the standard curve (Horizon on the
        engine's view transition); under reduced motion the engine starts no transition."""
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

    def animations(self, selector: str = "", trigger: str = "", value: str = "") -> list:
        """The animations under `selector`, read in the same script that runs `trigger` (its argument is
        arguments[1]): under load a separate read can land after a 120 ms transition is over."""
        return self.m.execute(trigger + self.ANIMATIONS, [selector, value])

    def test_03_calm_surfaces_arrive_on_the_tokens_and_warnings_never_move(self):
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
        self.open("settings/settings.html", "return document.documentElement?.dataset.ready === 'true';")
        dialog = (
            "{ const d = document.createElement('dialog'); d.className = arguments[1]; d.id = 'probe-dialog';"
            "d.innerHTML = '<form class=\"dialog__form\"><p>Teste</p></form>'; document.body.append(d); d.showModal(); }"
        )
        enter = "cubic-bezier(0, 0, 0, 1)"
        moving = sorted(map(tuple, self.animations("#probe-dialog", dialog, "dialog")))
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
                self.assertEqual(self.animations("#probe-dialog", dialog, kind), [])
                self.m.execute("document.getElementById('probe-dialog').remove();")
        toast = (
            "{ const s = document.getElementById('status'); s.removeAttribute('data-inline');"
            "s.dataset.level = arguments[1]; s.textContent = ''; s.offsetWidth; s.textContent = 'Salvo.'; }"
        )
        self.assertEqual(
            sorted(map(tuple, self.animations("#status", toast, "ok"))),
            [("CSSTransition", "opacity", 120, enter), ("CSSTransition", "translate", 120, enter)],
        )
        for level in ("warn", "error"):
            with self.subTest(level=level):
                self.m.execute("document.getElementById('status').textContent = '';")
                self.assertEqual(self.animations("#status", toast, level), [])
        self.m.execute("document.getElementById('status').textContent = '';")

    # The page paints again in the same script that reads (the 180 ms entrance has no fill: a separate
    # read under load can land after it is over).
    REPAINT = (
        "{ const r = document.documentElement; r.removeAttribute('data-painted');"
        " getComputedStyle(document.querySelector('.here__who > .chip')).animationName;"
        " r.setAttribute('data-painted', 'true'); }"
    )

    def test_04_the_profile_arrives_on_the_new_tab_and_nothing_moves_under_reduce(self):
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
        self.open("newtab/newtab.html", "return document.documentElement.hasAttribute('data-painted');")
        chip = self.animations(".here__who > .chip", self.REPAINT)
        self.assertEqual([tuple(a) for a in chip], [("CSSAnimation", "nv-chip-in", 180, "cubic-bezier(0, 0, 0, 1)")])
        self.assertEqual(self.animations(".here__who .badge", self.REPAINT), [])
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 1);")
        try:
            self.open("newtab/newtab.html", "return document.documentElement.hasAttribute('data-painted');")
            self.assertEqual(self.animations(".here__who > .chip", self.REPAINT), [])
            name = "return getComputedStyle(document.querySelector('.here__who > .chip')).animationName;"
            self.assertEqual(self.m.execute(name), "none")
            self.assertTrue(all(a[2] == 0 for a in self.animations("", self.REPAINT)), self.animations())
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")

    def test_05_the_create_sheet_enters_and_leaves_at_once(self):
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', 0);")
        self.open("profiles/popup.html", "return document.documentElement?.dataset.ready === 'true';")
        # Opened and read in one script: under load a separate read can land after the 180 ms are over.
        entering = self.m.execute(
            "document.getElementById('new-profile').click();"
            "return document.getElementById('sheet').getAnimations()"
            ".map(a => [a.constructor.name, a.transitionProperty,"
            " a.effect.getComputedTiming().duration, a.effect.getTiming().easing]);"
        )
        self.assertIn(("CSSTransition", "opacity", 180, "cubic-bezier(0, 0, 0, 1)"), [tuple(a) for a in entering])
        closed = self.m.execute(
            "document.getElementById('sheet-back').click();"
            "return [document.getElementById('sheet').hidden, getComputedStyle(document.getElementById('sheet')).display,"
            " document.activeElement.id];"
        )
        self.assertEqual(closed, [True, "none", "new-profile"])

    # -- The motion map (#319, docs/design/motion-map.md): tabs -------------------------------------

    LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
    # A tab opened in the background, and what moves in it, read in the script that opens it (frame by frame until
    # something moves, as the sidebar's reading above). Then the tab moved in the list, and closed.
    TAB = (
        "const done = arguments[arguments.length - 1];"
        "(async () => {"
        "  const frame = () => new Promise(r => requestAnimationFrame(r));"
        "  const read = tab => tab.getAnimations({subtree: true}).map(a => ["
        "    a.constructor.name, a.effect.target.className, a.transitionProperty || a.animationName,"
        "    a.effect.getComputedTiming().duration,"
        "    a.animationName ? getComputedStyle(a.effect.target).animationTimingFunction : a.effect.getTiming().easing]);"
        "  const strip = getComputedStyle(gBrowser.tabContainer);"
        "  const system = Services.scriptSecurityManager.getSystemPrincipal();"
        "  const tab = gBrowser.addTab('about:blank', {triggeringPrincipal: system});"
        "  const marked = tab.hasAttribute('nulavio-arriving');"
        "  let opening = [];"
        "  for (let i = 0; i < 30 && !opening.length; i++) { await frame(); opening = read(tab); }"
        "  await Promise.allSettled(tab.getAnimations({subtree: true}).map(a => a.finished));"
        "  for (let i = 0; i < 30 && tab.hasAttribute('nulavio-arriving'); i++) { await frame(); }"
        "  const markedAfter = tab.hasAttribute('nulavio-arriving');"
        "  gBrowser.moveTabTo(tab, {tabIndex: 0});"
        "  await frame(); await frame();"
        "  const moved = read(tab);"
        "  gBrowser.removeTab(tab, {animate: true});"
        "  const closing = read(tab);"
        "  const goneAtOnce = !tab.isConnected;"
        "  for (let i = 0; i < 120 && tab.isConnected; i++) { await frame(); }"
        "  done({vertical: gBrowser.tabContainer.verticalMode, marked, opening, markedAfter, moved, closing, goneAtOnce,"
        "    gone: !tab.isConnected,"
        "    room: strip.getPropertyValue('--tab-dragover-transition').replace(/\\s+/g, ' ').trim()});"
        "})().catch(e => done({error: String(e)}));"
    )

    def tab_in(self, preset: str) -> dict:
        """Open, move and close one tab in the window, with that layout; what moved at each step."""
        self.m.set_context("chrome")
        try:
            applied = self.m.execute_async(
                f"const done = arguments[arguments.length - 1]; {self.LAYOUT}.apply(window, arguments[0]).then(() => done(1));",
                [preset],
            )
            self.assertTrue(applied)
            got = self.m.execute_async(self.TAB)
        finally:
            self.m.set_context("content")
        self.assertNotIn("error", got, got)
        return got

    def reduced(self, on: bool) -> None:
        self.m.chrome("Services.prefs.setIntPref('ui.prefersReducedMotion', arguments[0]);", [1 if on else 0])
        # The engine follows the system setting live (gReduceMotion); wait until it has.
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return window.gReduceMotion === arguments[0];", [on]), 10))

    def test_06_a_tab_arrives_in_the_vertical_list_once(self):
        """The motion map: in the vertical list the engine shows a new tab at once, and Nulavio lets its content
        arrive (opacity and a 4px step, 120 ms on the enter curve). Only an opening does it: the engine puts a moved
        tab back as the same node, which does not arrive again. Closing is instant. Nothing under reduced motion."""
        enter = "cubic-bezier(0, 0, 0, 1)"
        try:
            self.reduced(False)
            got = self.tab_in("lateral")
            self.assertTrue(got["vertical"])
            self.assertTrue(got["marked"], "the Shell did not mark the opening tab")
            self.assertEqual([tuple(a) for a in got["opening"]], [("CSSAnimation", "tab-stack", "nulavio-tab-in", 120, enter)])
            self.assertFalse(got["markedAfter"], "the mark stayed after the movement")
            self.assertEqual(got["moved"], [], "a moved tab arrived again")
            self.assertEqual(got["closing"], [])
            self.assertTrue(got["goneAtOnce"], "closing waited in the vertical list")
            self.reduced(True)
            got = self.tab_in("lateral")
            self.assertEqual((got["opening"], got["moved"], got["closing"]), ([], [], []))
            self.assertFalse(got["marked"] or got["markedAfter"], "a tab was marked under reduced motion")
            self.assertTrue(got["goneAtOnce"])
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")

    def test_07_with_the_tabs_on_top_the_engine_moves_the_tab_and_nulavio_adds_nothing(self):
        """The motion map: with the tabs on top the engine opens and closes a tab by its width, and that keeps the
        engine's own 100 ms (on the tokens it measured worse). The arrival of the vertical list does not run here.
        The room the other tabs make for a dragged one is on the tokens. Under reduced motion the engine moves nothing."""
        width = [("CSSTransition", "tabbrowser-tab", prop, 100, "ease-out") for prop in ("max-width", "min-width")]
        try:
            self.reduced(False)
            got = self.tab_in("top")
            self.assertFalse(got["vertical"])
            self.assertEqual(sorted(tuple(a) for a in got["opening"]), width)
            self.assertEqual(sorted(tuple(a) for a in got["closing"]), width)
            self.assertFalse(got["goneAtOnce"], "with the tabs on top the tab closes by its width")
            self.assertTrue(got["gone"], "the closing tab never left")
            self.assertEqual(got["moved"], [])
            self.assertEqual(got["room"], "transform 180ms cubic-bezier(0.2, 0, 0, 1)")
            self.assertFalse(got["marked"] or got["markedAfter"], "a tab was marked with the tabs on top")
            self.reduced(True)
            got = self.tab_in("top")
            self.assertEqual((got["opening"], got["moved"], got["closing"]), ([], [], []))
            self.assertTrue(got["goneAtOnce"])
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")
            self.tab_in("lateral")  # the layout the other tests of this class start from

    def sidebar_step(self, step: str) -> list | None:
        """One change of the sidebar; the timing of the engine's view transition for it (None: no transition ran)."""
        self.m.set_context("chrome")
        try:
            return self.m.execute_async(
                "const done = arguments[arguments.length - 1];"
                "(async () => {"
                "  await SidebarController.waitUntilStable();"
                f"  const step = {step};"
                "  let seen = null;"
                "  for (let i = 0; i < 200 && !seen; i++) {"
                "    await new Promise(r => requestAnimationFrame(r));"
                "    const groups = document.getAnimations()"
                "      .filter(a => (a.effect.pseudoElement || '').startsWith('::view-transition-group('));"
                "    const timing = a => [a.effect.getComputedTiming().duration,"
                "      getComputedStyle(document.documentElement, a.effect.pseudoElement).animationTimingFunction];"
                "    if (groups.length) seen = groups.map(timing);"
                "  }"
                "  await step; await SidebarController.waitUntilStable();"
                "  done(seen);"
                "})().catch(e => done({error: String(e)}));"
            )
        finally:
            self.m.set_context("content")

    def test_08_a_sidebar_panel_moves_on_the_same_tokens_as_the_launcher(self):
        """The motion map: a sidebar panel opens in 220 ms, closes in 160 ms and gives way to another in 120 ms, on the
        standard curve (the engine's view transition, its variables given the tokens' values by Horizon). Under
        reduced motion the engine starts no transition."""
        curve = "cubic-bezier(0.2, 0, 0, 1)"
        steps = (
            ("SidebarController.toggle('viewHistorySidebar')", 220),  # opens
            ("SidebarController.toggle('viewBookmarksSidebar')", 120),  # gives way to another
            ("SidebarController.toggle('viewBookmarksSidebar')", 160),  # closes
        )  # toggle() is what the sidebar's buttons call; show() and hide() by themselves start no transition
        try:
            self.reduced(False)
            self.tab_in("lateral")
            for step, time in steps:
                with self.subTest(step=step):
                    seen = self.sidebar_step(step)
                    self.assertTrue(seen, "no transition ran")
                    self.assertEqual({tuple(a) for a in seen}, {(time, curve)})
            self.assertFalse(self.m.chrome("return SidebarController.isOpen;"), "the panel is still open")
            self.reduced(True)
            for step, _ in steps:
                with self.subTest(step=step, reduced=True):
                    self.assertIsNone(self.sidebar_step(step), "a transition ran under reduced motion")
        finally:
            self.m.chrome("SidebarController.hide();")
            self.m.chrome("Services.prefs.clearUserPref('ui.prefersReducedMotion');")


if __name__ == "__main__":
    unittest.main()
