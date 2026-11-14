"""ADR 0011: the arrangement picker of the settings page says why it cannot be used and what went wrong.

The old Layout card of the Shell's page said both (an administrator's lock, no sidebar in this window, a change
that could not be applied). The picker in Aparência says them now, read from NulavioLayout like the choice itself.
"""

from __future__ import annotations

import unittest

import harness
import settings_page

LAYOUT = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs").NulavioLayout'
PRESET = f"return {LAYOUT}.state(window).then(state => state.preset);"
# The arrangement the picker shows as chosen (the engine's own widget, one item per arrangement).
CHOSEN = (
    "const items = [...d.getElementById('nulavio-layout').querySelectorAll('moz-visual-picker-item')];"
    "const chosen = items.find(i => i.checked);"
)


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsLayoutTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def open(self) -> dict:
        settings_page.open_pane(self.m, "appearance")
        return settings_page.wait_control(self.m, "nulavio-layout", lambda now: now["shown"] and now["value"])

    def note(self, element_id: str) -> str | None:
        now = settings_page.control(self.m, element_id)
        return now["message"] if now and now["shown"] else None

    def test_01_a_picker_that_cannot_be_used_says_why(self):
        self.assertFalse(self.open()["disabled"])
        self.assertIsNone(self.note("nulavio-layout-why"))
        # An administrator set the arrangement: the picker shows it, takes no change, and the group says so.
        self.m.chrome("Services.prefs.lockPref('sidebar.verticalTabs');")
        self.addCleanup(self.m.chrome, "Services.prefs.unlockPref('sidebar.verticalTabs');")
        locked = settings_page.wait_control(self.m, "nulavio-layout", lambda now: now["disabled"])
        self.assertEqual(locked["value"], self.m.chrome(PRESET))  # what the lock set, not what was there before
        self.assertEqual(
            settings_page.wait_control(self.m, "nulavio-layout-why")["message"], "O layout é gerenciado pelo administrador."
        )
        self.m.chrome("Services.prefs.unlockPref('sidebar.verticalTabs');")
        settings_page.wait_control(self.m, "nulavio-layout", lambda now: not now["disabled"])
        self.assertIsNone(self.note("nulavio-layout-why"))
        # The engine's sidebar turned off: there is nothing to arrange in this window.
        self.m.chrome("Services.prefs.setBoolPref('sidebar.revamp', false);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('sidebar.revamp');")
        settings_page.wait_control(self.m, "nulavio-layout", lambda now: now["disabled"])
        self.assertEqual(
            settings_page.wait_control(self.m, "nulavio-layout-why")["message"], "O layout não está disponível nesta janela."
        )

    def test_02_a_change_that_could_not_be_applied_is_said_and_nothing_is_claimed(self):
        self.open()
        self.assertEqual(self.m.chrome(PRESET), "lateral")
        self.m.chrome(f"window.nvApply = {LAYOUT}.apply; {LAYOUT}.apply = () => {{ throw new Error('fixture'); }};")
        self.addCleanup(self.m.chrome, f"if (window.nvApply) {{ {LAYOUT}.apply = window.nvApply; delete window.nvApply; }}")
        settings_page.choose(self.m, "nulavio-layout", "top")
        failed = settings_page.wait_control(self.m, "nulavio-layout-error")
        self.assertEqual(
            failed["message"], "Não foi possível concluir a mudança de layout. Confira a janela atual e tente novamente."
        )
        # The window kept its arrangement, and the picker shows that one again, not the one that was asked for.
        self.assertEqual(self.m.chrome(PRESET), "lateral")
        self.assertEqual(
            settings_page.wait_control(self.m, "nulavio-layout", lambda now: now["value"] == "lateral")["value"], "lateral"
        )
        # Choosing again is the retry: once it applies, the error is gone.
        self.m.chrome(f"{LAYOUT}.apply = window.nvApply; delete window.nvApply;")
        settings_page.choose(self.m, "nulavio-layout", "top")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PRESET) == "top", 10), self.m.chrome(PRESET))
        settings_page.wait_control(self.m, "nulavio-layout", lambda now: now["value"] == "top")
        self.assertIsNone(self.note("nulavio-layout-error"))

    def test_03_the_keyboard_walks_the_arrangements_and_shows_where_it_is(self):
        """#142: the old Layout card's picker was walked with the arrow keys, with a focus ring. The picker in
        Aparência is the engine's own widget: the arrows choose the next arrangement, the window takes it, and
        the keyboard's place is drawn."""
        start = self.open()["value"]
        items = (
            settings_page.DOC
            + "return [...d.getElementById('nulavio-layout').querySelectorAll('moz-visual-picker-item')].map(i => i.value);"
        )
        values = self.m.chrome(items)
        self.assertEqual(self.m.chrome(PRESET), start)
        self.assertGreater(len(values), 1, values)
        focus = settings_page.DOC + CHOSEN + "chosen.focus(); return chosen.value;"
        self.assertEqual(self.m.chrome(focus), start)

        def press(key: str) -> None:
            keys = [{"type": "keyDown", "value": key}, {"type": "keyUp", "value": key}]
            self.m.send("WebDriver:PerformActions", {"actions": [{"type": "key", "id": "keys", "actions": keys}]})
            self.m.send("WebDriver:ReleaseActions")

        ring = (
            settings_page.DOC
            + CHOSEN
            + "const el = chosen.shadowRoot.activeElement ?? chosen.itemEl; const style = w.getComputedStyle(el);"
            + "const visible = Boolean(el?.matches(':focus-visible'));"
            + "return {value: chosen.value, within: chosen.matches(':focus-within'), visible,"
            + " outline: style.outlineStyle, width: parseFloat(style.outlineWidth)};"
        )
        following = values[(values.index(start) + 1) % len(values)]
        press("\ue014")  # ArrowRight
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PRESET) == following, 10), self.m.chrome(PRESET))
        settings_page.wait_control(self.m, "nulavio-layout", lambda now: now["value"] == following)
        drawn = self.m.chrome(ring)
        self.assertEqual((drawn["value"], drawn["within"], drawn["visible"]), (following, True, True), drawn)
        self.assertNotEqual(drawn["outline"], "none", drawn)
        self.assertGreater(drawn["width"], 0, drawn)
        press("\ue012")  # ArrowLeft: back where it was
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(PRESET) == start, 10), self.m.chrome(PRESET))


if __name__ == "__main__":
    unittest.main()
