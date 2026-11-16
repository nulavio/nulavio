"""#170: "Manter acima das outras janelas". On KDE Plasma, the View menu item and Ctrl+Alt+K ask KWin to keep the
window above the others and back, and show what KWin reports; elsewhere the item is shown unavailable, with the
reason. Nothing is asked of KWin but that one window's keepAbove.

The Plasma test runs only by hand, on a Plasma session: NULAVIO_TEST_HEADFUL=1 NULAVIO_TEST_PLASMA=1 (the engine's
window on the desktop, and the desktop's own session bus, where KWin is). Everywhere else the engine gets the
harness's private bus, where there is no KWin, and the item must say so."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest

import harness

KEEP = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioKeepAbove.sys.mjs").NulavioKeepAbove'
ITEM = """
const done = arguments[arguments.length - 1];
const popup = document.getElementById("menu_viewPopup");
const item = document.getElementById("nulavio-menu-keep-above");
popup.dispatchEvent(new Event("popupshowing"));
popup.dispatchEvent(new Event("popuphidden"));
const read = () => ({ parent: item.parentNode.id, label: item.getAttribute("label"), type: item.getAttribute("type"),
                      checked: item.getAttribute("checked"), disabled: item.hasAttribute("disabled") });
// The state is KWin's answer, which comes a moment later.
setTimeout(() => done(read()), 3000);
"""
PLASMA = os.environ.get("NULAVIO_TEST_PLASMA") == "1" and os.environ.get("NULAVIO_TEST_HEADFUL") == "1"


def chrome_async(m, script: str, args: list | None = None):
    m.set_context("chrome")
    try:
        return m.execute_async(script, args or [])
    finally:
        m.set_context("content")


def kwin_keep_above(uuid: str) -> bool:
    """KWin's own record of the window, read here and not through the module."""
    out = subprocess.run(
        ["busctl", "--user", "--json=short", "call", "org.kde.KWin", "/KWin", "org.kde.KWin", "getWindowInfo", "s", uuid],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(out.stdout)["data"][0]["keepAbove"]["data"]


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class KeepAboveElsewhereTest(unittest.TestCase):
    """The harness's private bus has no KWin: the item is there, disabled, and says why; the key changes nothing."""

    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def test_01_the_item_is_shown_unavailable_with_the_reason(self):
        item = chrome_async(self.m, ITEM)
        self.assertEqual((item["parent"], item["type"], item["disabled"]), ("menu_viewPopup", "checkbox", True), item)
        self.assertRegex(
            item["label"],
            r"\((só no KDE Plasma|KDE Plasma only|o barramento da sessão não respondeu|the session bus did not answer)\)",
        )

    def test_02_asked_anyway_it_refuses_and_says_why(self):
        refused = chrome_async(
            self.m,
            "const done = arguments[arguments.length - 1]; const said = [];"
            f"{KEEP}.set(window, true, k => said.push(k)).then(() => done('changed'), e => done([e.code, said]));",
        )
        self.assertEqual(refused[0], "keep-above-unavailable")
        self.assertIn(refused[1][0], ("keepAboveNotPlasma", "keepAboveNoBus"))

    def test_03_the_script_takes_only_a_window_id_and_a_boolean(self):
        tries = ["{0018f697-ff6d-438c-a85d-a1297e32a29c}", '"); workspace.windowList().forEach(w => w.minimized = true); ("']
        made = self.m.chrome(
            "const M = ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioKeepAbove.sys.mjs');"
            "return arguments[0].map(id => { try { return M.script(id, true); } catch (e) { return e.code; } });",
            [tries],
        )
        self.assertIn('w.internalId.toString() === "{0018f697-ff6d-438c-a85d-a1297e32a29c}"', made[0])
        self.assertIn("w.keepAbove = true;", made[0])
        self.assertEqual(made[1], "keep-above-invalid")


@unittest.skipUnless(harness.nulavio_engine() and PLASMA and shutil.which("busctl"), "a Plasma session, by hand (see the module)")
class KeepAbovePlasmaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal", desktop_bus=True)
        cls.m = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def test_01_on_and_off_as_kwin_reports_it(self):
        uuid = chrome_async(
            self.m, f"const done = arguments[arguments.length - 1]; {KEEP}.windowId(window).then(done, e => done(String(e)));"
        )
        self.assertRegex(uuid, r"^\{[0-9a-f-]{36}\}$")
        self.assertFalse(kwin_keep_above(uuid))
        item = chrome_async(self.m, ITEM)
        self.assertEqual((item["checked"], item["disabled"]), ("false", False), item)
        # The key, as a person presses it.
        self.m.chrome(
            "[...document.querySelectorAll('#ext-keyset-id-shell_nulavio_net key')]"
            ".find(k => (k.getAttribute('key') || '').toUpperCase() === 'K').doCommand();"
        )
        self.assertTrue(harness.wait_until(lambda: kwin_keep_above(uuid), 10), "KWin never kept the window above")
        item = chrome_async(self.m, ITEM)
        self.assertEqual(item["checked"], "true", item)
        # The menu item, back off.
        self.m.chrome("document.getElementById('nulavio-menu-keep-above').doCommand();")
        self.assertTrue(harness.wait_until(lambda: not kwin_keep_above(uuid), 10), "KWin kept the window above")
        # The title the window had is back once the window was found.
        self.assertNotIn("nulavio-keep-above-", self.m.chrome("return document.title;"))


if __name__ == "__main__":
    unittest.main()
