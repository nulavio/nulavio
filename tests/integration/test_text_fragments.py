"""Copy Link to Highlight in the Nulavio build (#157).

The engine's own feature, untouched by Nulavio's prefs and patches: a selection
gives "Copy Link to Highlight" and "Copy Clean Link to Highlight" in the page
menu, the link carries a text directive (`#:~:text=`), the clean one drops the
tracking parameters of the engine's strip-on-share list, and opening the link
scrolls to the text and highlights it until "Remove highlight". The highlight
(`::target-text`) is checked for AA contrast in a light and a dark page, from
screenshots: getComputedStyle does not resolve that pseudo-element in Gecko.
"""

from __future__ import annotations

import sys
import time
import unittest
import urllib.parse
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
import pngdiff

MENU = """
const menu = document.getElementById("contentAreaContextMenu");
const state = id => { const i = document.getElementById(id); return i ? {shown: !i.hidden, disabled: i.disabled} : null; };
return { open: menu.state === "open", copy: state("context-copy-link-to-highlight"),
         clean: state("context-copy-clean-link-to-highlight"), remove: state("context-remove-highlight") };
"""

CLIPBOARD = """
const trans = Cc["@mozilla.org/widget/transferable;1"].createInstance(Ci.nsITransferable);
trans.init(null);
trans.addDataFlavor("text/plain");
Services.clipboard.getData(trans, Ci.nsIClipboard.kGlobalClipboard, null);
const data = {};
try { trans.getTransferData("text/plain", data); } catch (e) { return null; }
return data.value.QueryInterface(Ci.nsISupportsString).data;
"""

# The system colours the engine's highlight uses (Mark, MarkText), resolved in the page, for the report.
SYSTEM = """
const probe = document.createElement("span");
probe.style.cssText = "background-color: Mark; color: MarkText";
document.body.append(probe);
const style = getComputedStyle(probe);
const out = { mark: style.backgroundColor, markText: style.color };
probe.remove();
return out;
"""


def luminance(r: float, g: float, b: float) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(fg: tuple, bg: tuple) -> float:
    hi, lo = sorted((luminance(*fg[:3]), luminance(*bg[:3])), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def colours(png: bytes) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """The commonest colour of a screenshot (the background) and its ink: the colour seen at least
    five times that contrasts most with it (the core of the glyphs, past their anti-aliasing)."""
    width, _height, bpp, rows = pngdiff.decode(png)
    counts = Counter(tuple(row[i : i + 3]) for row in rows for i in range(0, width * bpp, bpp))
    background = counts.most_common(1)[0][0]
    ink = max((c for c, n in counts.items() if n >= 5), key=lambda c: contrast(c, background))
    return background, ink


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's defaults (NULAVIO_ENGINE)")
class TextFragmentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.page = cls.server.url("/highlight?id=7&utm_source=newsletter&utm_medium=email")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    def tearDown(self):
        self.m.chrome("document.getElementById('contentAreaContextMenu').hidePopup();")

    def close_menu(self) -> None:
        """Hidden and closed: a right click while the menu is still hiding opens nothing."""
        self.m.chrome("document.getElementById('contentAreaContextMenu').hidePopup();")
        closed = "return document.getElementById('contentAreaContextMenu').state === 'closed';"
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(closed), 10), "the page menu did not close")

    def open_menu_on_target(self, select: bool) -> dict:
        self.close_menu()  # a choice made in it a moment ago may still be closing it
        if select:
            self.m.execute(
                "const r = document.createRange(); r.selectNodeContents(document.getElementById('target'));"
                "getSelection().removeAllRanges(); getSelection().addRange(r);"
            )
        self.m.execute("document.getElementById('target').scrollIntoView({block: 'center'});")
        self.m.context_click("#target")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(MENU)["open"], 10), "the page menu did not open")
        return self.m.chrome(MENU)

    def copy_from_menu(self, item: str) -> str:
        self.m.chrome("Services.clipboard.emptyClipboard(Ci.nsIClipboard.kGlobalClipboard);")
        menu = self.open_menu_on_target(select=True)
        self.assertTrue(menu["copy"] and menu["copy"]["shown"], menu)
        # Both items start disabled while the engine builds the text directive.
        ready = harness.wait_until(lambda: not self.m.chrome(MENU)[item]["disabled"], 10)
        self.assertTrue(ready, f"{item} stayed disabled: {self.m.chrome(MENU)}")
        ids = {"copy": "context-copy-link-to-highlight", "clean": "context-copy-clean-link-to-highlight"}
        self.m.chrome(
            "const menu = document.getElementById('contentAreaContextMenu');"
            "menu.activateItem(document.getElementById(arguments[0]));",
            [ids[item]],
        )
        copied = harness.wait_until(lambda: self.m.chrome(CLIPBOARD) or None, 10)
        self.assertTrue(copied, "nothing reached the clipboard")
        return copied

    def test_01_both_items_copy_a_link_with_a_text_directive(self):
        self.m.navigate(self.page)
        link = self.copy_from_menu("copy")
        print(f"copied: {link}", file=sys.stderr)
        base, _, fragment = link.partition("#")
        self.assertEqual(base, self.page)
        self.assertTrue(fragment.startswith(":~:text="), link)
        self.assertIn("frase", urllib.parse.unquote(fragment))
        clean = self.copy_from_menu("clean")
        print(f"clean: {clean}", file=sys.stderr)
        clean_base, _, clean_fragment = clean.partition("#")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(clean_base).query)
        self.assertEqual(query, {"id": ["7"]}, "the clean link kept a tracking parameter or lost the page's own")
        self.assertEqual(clean_fragment, fragment)
        type(self).link = link

    def test_02_the_link_scrolls_to_the_text_highlights_it_and_remove_highlight_clears_it(self):
        link = getattr(type(self), "link", None)
        if link is None:
            self.skipTest("test_01 did not copy a link")
        self.m.navigate("about:blank")
        self.m.navigate(link)
        shown = harness.wait_until(
            lambda: self.m.execute(
                "const r = document.getElementById('target')?.getBoundingClientRect();"
                "return !!r && scrollY > 0 && r.top >= 0 && r.bottom <= innerHeight;"
            ),
            10,
        )
        self.assertTrue(shown, "the page did not scroll to the highlighted text")
        self.assertEqual(self.highlights(), 1, "the page shows no highlight")
        menu = self.open_menu_on_target(select=False)
        self.assertTrue(menu["remove"] and menu["remove"]["shown"], f"no 'Remove highlight' on a page with one: {menu}")
        self.m.chrome(
            "const menu = document.getElementById('contentAreaContextMenu');"
            "menu.activateItem(document.getElementById('context-remove-highlight'));"
        )
        # Read from the document itself: the menu reopened right after the choice did not always open (#300).
        self.assertTrue(harness.wait_until(lambda: self.highlights() == 0, 10), "the highlight stayed")

    def highlights(self) -> int:
        """The text directives the page shows, as the engine's own menu reads them (a chrome-only API)."""
        return self.m.execute("return document.fragmentDirective.getTextDirectiveRanges().length;", sandbox="system")

    def press_ctrl_shift_l(self) -> None:
        """Ctrl+Shift+L through the widget (nsITextInputProcessor), as typing does (test_shortcuts' way)."""
        self.m.chrome(
            "const tip = Cc['@mozilla.org/text-input-processor;1'].createInstance(Ci.nsITextInputProcessor);"
            "if (!tip.beginInputTransactionForTests(window)) throw new Error('no input transaction');"
            "const ctrl = new KeyboardEvent('', {key: 'Control', code: 'ControlLeft', keyCode: 17});"
            "const shift = new KeyboardEvent('', {key: 'Shift', code: 'ShiftLeft', keyCode: 16});"
            "const letter = new KeyboardEvent('', {key: 'L', code: 'KeyL', keyCode: 76});"
            "tip.keydown(ctrl); tip.keydown(shift); tip.keydown(letter); tip.keyup(letter); tip.keyup(shift); tip.keyup(ctrl);"
        )

    def test_02b_ctrl_shift_l_copies_the_link_to_the_selected_text(self):
        """#157: the shortcut the maintainer accepted gives the link the page menu gives; nothing selected, nothing copied."""
        self.m.navigate(self.page)
        self.m.chrome("Services.clipboard.emptyClipboard(Ci.nsIClipboard.kGlobalClipboard);")
        self.m.execute("getSelection().removeAllRanges(); document.body.focus();")
        self.press_ctrl_shift_l()
        time.sleep(1)  # nothing is expected to arrive: give a copy the time it would take
        self.assertIsNone(self.m.chrome(CLIPBOARD), "a link was copied with nothing selected")
        self.m.execute(
            "const r = document.createRange(); r.selectNodeContents(document.getElementById('target'));"
            "getSelection().removeAllRanges(); getSelection().addRange(r);"
        )
        self.press_ctrl_shift_l()
        copied = harness.wait_until(lambda: self.m.chrome(CLIPBOARD) or None, 10)
        self.assertTrue(copied, "Ctrl+Shift+L copied nothing")
        base, _, fragment = copied.partition("#")
        # The page's own address: its path and id=7 (the engine may already have dropped utm_ from this second visit).
        self.assertTrue(base.startswith(self.server.url("/highlight?id=7")), copied)
        self.assertTrue(fragment.startswith(":~:text="), copied)
        self.assertIn("frase", urllib.parse.unquote(fragment))

    def test_03_the_highlight_is_readable_in_a_light_and_a_dark_page(self):
        link = getattr(type(self), "link", None)
        if link is None:
            self.skipTest("test_01 did not copy a link")
        try:
            for dark in (0, 1):
                with self.subTest(dark=bool(dark)):
                    self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                    self.m.navigate(self.page)
                    page, _ = colours(self.m.screenshot_png(element=self.m.find_element("#target")))
                    self.m.navigate("about:blank")
                    self.m.navigate(link)
                    harness.wait_until(lambda: self.m.execute("return scrollY > 0;"), 10)
                    shot = self.m.screenshot_png(element=self.m.find_element("#target"))
                    background, ink = colours(shot)
                    ratio = contrast(ink, background)
                    report = {"page": page, "highlight": background, "ink": ink, "ratio": round(ratio, 2),
                              **self.m.execute(SYSTEM)}  # fmt: skip
                    print(f"highlight dark={dark}: {report}", file=sys.stderr)
                    (harness.artifacts_dir() / f"text-fragment-{'dark' if dark else 'light'}.png").write_bytes(shot)
                    self.assertNotEqual(background, page, f"the highlight is not told apart from the page: {report}")
                    self.assertGreaterEqual(ratio, 4.5, f"the highlighted text is below AA contrast: {report}")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")


if __name__ == "__main__":
    unittest.main()
