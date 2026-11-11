"""UX6 shortcuts (D-UX23) on the real build: Ctrl+Alt+F toggles Foco, Ctrl+Alt+B opens the profile menu,
Settings > Atalhos lists Nulavio's keys and changes them in the engine's own view, and every place that
names a key shows the key the engine has now. Headless, throwaway profile.
"""

from __future__ import annotations

import unittest

import harness
from test_profiles import chrome_async

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
KEYSET = "[...document.querySelectorAll('#ext-keyset-id-shell_nulavio_net key')]"
NAMES = {"accel": "control", "control": "control", "shift": "shift", "alt": "alt", "meta": "meta"}


# Modifiers as the engine writes them ("accel" is Ctrl on Linux), sorted, so "Ctrl+Alt+F" reads "alt,control+F".
NORM = (
    "const norm = m => (m || '').split(/[ ,]+/).filter(Boolean).map(x => x === 'accel' ? 'control' : x).sort().join(',');"
    "const combo = k => norm(k.getAttribute('modifiers')) + '+' + (k.getAttribute('key') || '').toUpperCase();"
)


def key_of(combo: str) -> str:
    return f"(() => {{ {NORM} return {KEYSET}.find(k => combo(k) === '{combo}'); }})()"


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class ShortcutsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def preset(self) -> str:
        return chrome_async(self.m, f"return (await {LAYOUT}.state(window)).preset;")["ok"]

    def apply(self, preset: str) -> None:
        chrome_async(self.m, f"await {LAYOUT}.apply(window, args[0]); return true;", [preset])

    def open_settings(self, address: str = "#shortcuts") -> None:
        self.m.navigate(self.base + "settings/settings.html" + address)
        ready = "return document.documentElement.dataset.ready === 'true';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(ready), 20))

    def test_01_the_keys_are_in_the_shell_keyset_without_clashing_with_the_browser(self):
        ours = self.m.chrome(f"{NORM} return {KEYSET}.map(combo);")
        self.assertEqual(sorted(ours), ["alt,control+B", "alt,control+F", "alt,control+I", "alt,shift+A", "alt,shift+P"])
        clashes = self.m.chrome(
            f"{NORM} const ours = {KEYSET}.map(combo);"
            "return [...document.querySelectorAll('key')].filter(k => !k.closest('#ext-keyset-id-shell_nulavio_net'))"
            "  .filter(k => k.getAttribute('key')).map(k => [k.id, combo(k)]).filter(([, c]) => ours.includes(c));"
        )
        self.assertEqual(clashes, [])

    def announced(self) -> str | None:
        return self.m.chrome("return document.querySelector('#a11y-announcement > label')?.getAttribute('aria-label') ?? null;")

    def test_02_the_focus_key_toggles_foco_and_returns_to_the_preset_it_came_from(self):
        focus_key = key_of("alt,control+F")
        for start in ("lateral", "top"):
            with self.subTest(start=start):
                self.apply(start)
                self.assertEqual(self.preset(), start)
                self.m.chrome(f"{focus_key}.doCommand();")
                self.assertTrue(harness.wait_until(lambda: self.preset() == "focus", 15), self.preset())
                self.assertTrue(harness.wait_until(lambda: self.announced() == "Layout Foco ligado.", 5), self.announced())
                self.m.chrome(f"{focus_key}.doCommand();")
                self.assertTrue(harness.wait_until(lambda want=start: self.preset() == want, 15), self.preset())
                self.assertTrue(harness.wait_until(lambda: self.announced() == "Layout Foco desligado.", 5), self.announced())
        self.apply("lateral")

    def test_02b_the_immersive_key_turns_the_mode_on_and_off_and_says_so(self):
        """ADR 0009: one key, one layout pref; where the mode applies is the window's decision (test_immersive)."""
        key = key_of("alt,control+I")
        pref = "return Services.prefs.getBoolPref('nulavio.layout.immersive', false);"
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('nulavio.layout.immersive');")
        self.assertFalse(self.m.chrome(pref))
        self.m.chrome(f"{key}.doCommand();")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(pref), 10))
        said = "Imersivo ligado. A barra de endereço volta com Ctrl+L."
        self.assertTrue(harness.wait_until(lambda: self.announced() == said, 5), self.announced())
        self.m.chrome(f"{key}.doCommand();")
        self.assertTrue(harness.wait_until(lambda: not self.m.chrome(pref), 10))
        self.assertTrue(harness.wait_until(lambda: self.announced() == "Imersivo desligado.", 5), self.announced())

    def test_02b_foco_chosen_elsewhere_still_returns_to_the_preset_it_came_from(self):
        """Review: Foco chosen in Settings (or the first run) from Lateral; the key goes back to Lateral.
        The remembered preset starts as the other one, so only the choice itself can set it."""
        self.m.chrome("Services.prefs.setStringPref('nulavio.layout.beforeFocus', 'top');")
        self.apply("top")
        self.apply("focus")  # remembered: top
        self.apply("lateral")
        self.apply("focus")  # as Settings does it: remembered now as lateral
        self.m.chrome(f"{key_of('alt,control+F')}.doCommand();")
        self.assertTrue(harness.wait_until(lambda: self.preset() == "lateral", 15), self.preset())

    def press(self, key: str, code: str, key_code: int) -> None:
        """Ctrl+Alt+<key> as keyboard events through the widget (nsITextInputProcessor), as typing does."""
        self.m.chrome(
            "const [key, code, keyCode] = arguments;"
            "const tip = Cc['@mozilla.org/text-input-processor;1'].createInstance(Ci.nsITextInputProcessor);"
            "if (!tip.beginInputTransactionForTests(window)) throw new Error('no input transaction');"
            "const ctrl = new KeyboardEvent('', {key: 'Control', code: 'ControlLeft', keyCode: 17});"
            "const alt = new KeyboardEvent('', {key: 'Alt', code: 'AltLeft', keyCode: 18});"
            "const letter = new KeyboardEvent('', {key, code, keyCode});"
            "tip.keydown(ctrl); tip.keydown(alt); tip.keydown(letter); tip.keyup(letter); tip.keyup(alt); tip.keyup(ctrl);",
            [key, code, key_code],
        )

    def test_02c_the_keys_work_when_pressed(self):
        """Terra R7 asked for real key presses: the keys reach the Shell through the window's key handling."""
        self.apply("lateral")
        self.m.chrome("gURLBar.blur(); gBrowser.selectedBrowser.focus();")
        self.press("f", "KeyF", 70)
        self.assertTrue(harness.wait_until(lambda: self.preset() == "focus", 15), self.preset())
        self.press("f", "KeyF", 70)
        self.assertTrue(harness.wait_until(lambda: self.preset() == "lateral", 15), self.preset())
        popup = (
            "return [...document.querySelectorAll('browser')]"
            "  .some(b => (b.currentURI?.spec || '').endsWith('/profiles/popup.html'));"
        )
        self.press("b", "KeyB", 66)
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(popup), 10))
        self.m.chrome("for (const p of document.querySelectorAll('panel[panelopen], panel[open]')) p.hidePopup?.();")

    def test_03_the_focus_key_explains_a_locked_layout_and_changes_nothing(self):
        self.apply("lateral")
        self.m.chrome("Services.prefs.lockPref('sidebar.visibility');")
        try:
            self.m.chrome(f"{key_of('alt,control+F')}.doCommand();")
            said = "O layout é gerenciado pelo administrador."
            self.assertTrue(harness.wait_until(lambda: self.announced() == said, 10), self.announced())
            self.assertEqual(self.preset(), "lateral")
        finally:
            self.m.chrome("Services.prefs.unlockPref('sidebar.visibility');")

    def test_04_the_lock_key_opens_the_profile_menu(self):
        """K2: action.openPopup from the command opens the menu; the menu runs the same confirmation as its button."""
        self.m.chrome(f"{key_of('alt,control+B')}.doCommand();")
        popup = (
            "return [...document.querySelectorAll('browser')]"
            "  .some(b => (b.currentURI?.spec || '').endsWith('/profiles/popup.html'));"
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(popup), 10))
        self.m.chrome("for (const p of document.querySelectorAll('panel[panelopen], panel[open]')) p.hidePopup?.();")

    def test_05_settings_lists_the_commands_and_restore_brings_the_default_back(self):
        self.open_settings()
        rows = lambda: self.m.execute(  # noqa: E731
            "return [...document.querySelectorAll('#shortcut-list > li')].map(li => [li.dataset.command,"
            " [...li.querySelectorAll('kbd')].map(k => k.textContent).join('+'), Boolean(li.querySelector('.button--quiet'))]);"
        )
        self.assertEqual(
            sorted(map(tuple, rows())),
            sorted([("_execute_action", "Alt+Shift+P", False), ("open-assistant", "Alt+Shift+A", False),
                    ("toggle-focus", "Ctrl+Alt+F", False), ("toggle-immersive", "Ctrl+Alt+I", False),
                    ("lock-profile", "Ctrl+Alt+B", False)]),
        )  # fmt: skip
        self.m.execute("return browser.commands.update({name: 'toggle-focus', shortcut: 'Ctrl+Alt+G'});")
        self.m.execute("window.dispatchEvent(new Event('focus'));")
        self.assertTrue(harness.wait_until(lambda: ["toggle-focus", "Ctrl+Alt+G", True] in rows(), 10), rows())
        self.m.send(
            "WebDriver:ElementClick", {"id": self.m.find_element('#shortcut-list li[data-command="toggle-focus"] .button--quiet')}
        )
        self.assertTrue(harness.wait_until(lambda: ["toggle-focus", "Ctrl+Alt+F", False] in rows(), 10), rows())

    def test_06_hints_follow_a_changed_key(self):
        self.open_settings()
        self.m.execute("return browser.commands.update({name: '_execute_action', shortcut: 'Alt+Shift+O'});")
        try:
            self.m.navigate(self.base + "profiles/popup.html")
            hint = "return document.querySelector('.popup__keys').textContent;"
            self.assertTrue(harness.wait_until(lambda: "Alt+Shift+O" in self.m.execute(hint), 10), self.m.execute(hint))
            self.m.navigate(self.base + "newtab/newtab.html")
            row = (
                "return [...document.querySelectorAll('#nulavio-keys li[data-command=\"_execute_action\"] kbd')]"
                "  .map(k => k.textContent).join('+');"
            )
            self.assertTrue(harness.wait_until(lambda: self.m.execute(row) == "Alt+Shift+O", 10), self.m.execute(row))
        finally:
            self.open_settings()
            self.m.execute("return browser.commands.reset('_execute_action');")

    def test_06b_restore_also_renames_the_profile_button(self):
        """Review: Firefox 159's commands.reset() fires no commands.onChanged, so Settings tells the
        background; the toolbar button's name (its title) names the key that works again."""
        self.open_settings()
        title = lambda: self.m.execute("return browser.action.getTitle({});")  # noqa: E731
        self.m.execute("return browser.commands.update({name: '_execute_action', shortcut: 'Alt+Shift+O'});")
        try:
            self.assertTrue(harness.wait_until(lambda: "Alt+Shift+O" in title(), 10), title())
            self.m.execute("window.dispatchEvent(new Event('focus'));")
            restore = '#shortcut-list li[data-command="_execute_action"] .button--quiet'
            self.assertTrue(
                harness.wait_until(lambda: self.m.execute("return Boolean(document.querySelector(arguments[0]));", [restore]), 10)
            )
            self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(restore)})
            self.assertTrue(harness.wait_until(lambda: "Alt+Shift+P" in title(), 10), title())
        finally:
            self.m.execute("return browser.commands.reset('_execute_action');")

    def test_07_change_opens_the_engine_shortcuts_view_with_the_shell_card(self):
        """K1: the hidden built-in Shell has its card in about:addons > Manage Extension Shortcuts."""
        self.open_settings()
        handles = set(self.m.window_handles())
        self.m.send(
            "WebDriver:ElementClick",
            {"id": self.m.find_element('#shortcut-list li[data-command="toggle-focus"] .button--secondary')},
        )
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, 10))
        self.m.switch_to((set(self.m.window_handles()) - handles).pop())
        try:
            self.assertTrue(harness.wait_until(lambda: self.m.current_url().startswith("about:addons"), 10))
            card = (
                "const card = document.querySelector('addon-shortcuts moz-card.shortcut[addon-id=\"shell@nulavio.net\"]');"
                "return card && {name: card.querySelector('.addon-name').textContent,"
                " keys: [...card.querySelectorAll('.shortcut-input')].map(i => [i.name, i.getAttribute('shortcut')])};"
            )
            self.assertTrue(harness.wait_until(lambda: self.m.execute(card), 10), self.m.execute(card))
            shown = self.m.execute(card)
            self.assertIn("Nulavio", shown["name"])
            self.assertIn(["toggle-focus", "Ctrl+Alt+F"], shown["keys"])
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(next(iter(handles)))

    def test_08_the_browser_shortcuts_link_opens_about_keyboard(self):
        self.open_settings()
        handles = set(self.m.window_handles())
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#shortcuts-browser")})
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, 10))
        self.m.switch_to((set(self.m.window_handles()) - handles).pop())
        try:
            self.assertTrue(harness.wait_until(lambda: self.m.current_url() == "about:keyboard", 10), self.m.current_url())
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(next(iter(handles)))

    def test_09_quick_actions_open_settings_and_toggle_focus(self):
        """UX6 (D8): after ">", Nulavio's settings and the Foco toggle; matched by their words."""
        actions = (
            "const {ActionsProviderQuickActions: Q} = ChromeUtils.importESModule("
            "'moz-src:///browser/components/urlbar/ActionsProviderQuickActions.sys.mjs');"
        )
        # As typed: a prefix of a word, or the whole word (the engine's exact-match path).
        found = lambda text, exact=False: chrome_async(  # noqa: E731
            self.m, actions + "return [...await Q.getActions({input: args[0], includesExactMatch: args[1]})];", [text, exact]
        )["ok"]
        self.assertIn("nulavio-focus", found("foc"))
        self.assertIn("nulavio-focus", found("foco", True))
        self.assertIn("nulavio-focus", found("focus", True))
        self.assertIn("nulavio-settings", found("nulav"))
        self.assertIn("nulavio-settings", found("nulavio", True))
        labels = chrome_async(
            self.m,
            "return await document.l10n.formatValues([{id: 'nulavio-quickaction-settings'}, {id: 'nulavio-quickaction-focus'}]);",
        )["ok"]
        self.assertEqual(labels, ["Abrir as configurações do Nulavio", "Ligar ou desligar o layout Foco"])
        self.apply("lateral")
        self.m.chrome(actions + "Q.getAction('nulavio-focus').onPick(null, {browserWindow: window});")
        self.assertTrue(harness.wait_until(lambda: self.preset() == "focus", 15), self.preset())
        self.m.chrome(actions + "Q.getAction('nulavio-focus').onPick(null, {browserWindow: window});")
        self.assertTrue(harness.wait_until(lambda: self.preset() == "lateral", 15), self.preset())
        before = self.m.chrome("return gBrowser.tabs.length;")
        self.m.chrome(actions + "Q.getAction('nulavio-settings').onPick(null, {browserWindow: window});")
        opened = (
            "return gBrowser.tabs.map(t => t.linkedBrowser.currentURI.spec).some(u => u.endsWith('/settings/settings.html'));"
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(opened), 10))
        self.m.chrome("while (gBrowser.tabs.length > arguments[0]) gBrowser.removeTab(gBrowser.tabs.at(-1));", [before])

    def test_10_quick_actions_are_not_offered_in_an_ai_workspace(self):
        actions = (
            "const {ActionsProviderQuickActions: Q} = ChromeUtils.importESModule("
            "'moz-src:///browser/components/urlbar/ActionsProviderQuickActions.sys.mjs');"
        )
        unsupported = actions + "return ['nulavio-settings', 'nulavio-focus'].map(a => Q.getAction(a).isUnsupported());"
        self.assertEqual(self.m.chrome(unsupported), [False, False])
        self.m.chrome("Services.prefs.setStringPref('nulavio.ai.workspace', 'test-agent');")
        try:
            self.assertEqual(self.m.chrome(unsupported), [True, True])
        finally:
            self.m.chrome("Services.prefs.clearUserPref('nulavio.ai.workspace');")


if __name__ == "__main__":
    unittest.main()
