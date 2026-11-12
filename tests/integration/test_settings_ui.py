"""Nulavio settings in two panes (UX4, audit SPA-04/05/06). Nulavio build only.

One section per address, a rail grouped by how far a change reaches, a filter over every
section, the profile being configured in the header, and results shown next to the control
that made them (spoken once, with the control's name). Captures of every section in light
and dark go to the test artifacts.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

# ADR 0011: what the settings page draws itself is gone from this page; its old address opens that page at this pane.
MOVED = {
    "#dns": "privacy",
    "#exceptions": "privacy",
    "#passwords": "passwordsAutofill",
    "#search": "search",
    "#profiles": "nulavioProfiles",
    "#profiles-new": "nulavioProfiles",
    "#routing": "nulavioProfiles",
    "#routing-fallback-field": "nulavioProfiles",
}
SCOPES = {
    "layout": "scopeProfile",
    "appearance": "scopeProfile",
    "shortcuts": "scopeProfile",
    "ai": "scopeAllProfiles",
    "integrations": "scopeComputer",
}

VIEW = """
const main = document.getElementById('settings-main');
const shown = [...main.querySelectorAll(':scope > .section')].filter(s => getComputedStyle(s).display !== 'none');
return {
  view: main.dataset.view,
  shown: shown.map(s => s.id),
  current: [...document.querySelectorAll('.settings-nav a[aria-current="page"]')].map(a => a.dataset.section),
  focused: document.activeElement?.id || document.activeElement?.localName,
  results: document.getElementById('settings-results').hidden ? null : document.getElementById('settings-results').textContent,
};
"""


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class SettingsPanesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        cls.shots = harness.artifacts_dir() / "settings-ux4"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")
        cls.session.cleanup()

    def open(self, address: str = "") -> None:
        self.m.navigate(self.base + "settings/settings.html" + address)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 20)
        )

    def view(self) -> dict:
        return self.m.execute(VIEW)

    def message(self, key: str, *args: str) -> str:
        return self.m.execute("return browser.i18n.getMessage(arguments[0], arguments[1]);", [key, list(args)])

    def type_search(self, text: str) -> None:
        self.m.execute(
            "const s = document.getElementById('settings-search'); s.value = arguments[0];"
            "s.dispatchEvent(new Event('input', {bubbles: true}));",
            [text],
        )

    def test_01_one_section_per_address(self):
        self.open()
        state = self.view()
        self.assertEqual(state["view"], "section")
        self.assertEqual(len(state["shown"]), 1, state)
        self.assertEqual(state["current"], state["shown"])  # the rail marks the section on screen
        for address, section in (("#ai-assistant", "ai"), ("#integrations", "integrations"), ("#layout", "layout")):
            self.open(address)
            self.assertTrue(
                harness.wait_until(lambda section=section: self.view()["shown"] == [section], 10), (address, self.view())
            )
            # Layout is drawn by the settings page too (ADR 0008): it still opens by its address, with no entry in the rail.
            self.assertEqual(self.view()["current"], [] if section == "layout" else [section])
        # A card's own address (the assistant panel links there) scrolls it into view.
        self.open("#ai-assistant")
        harness.wait_until(lambda: self.view()["shown"] == ["ai"], 10)
        top = self.m.execute("return document.getElementById('ai-assistant').getBoundingClientRect().top;")
        self.assertLess(top, self.m.execute("return innerHeight;"))

    def test_01b_an_address_of_a_moved_section_opens_the_settings_page(self):
        where = lambda: self.m.chrome("return gBrowser.selectedBrowser.currentURI.spec;")  # noqa: E731
        for address, pane in MOVED.items():
            with self.subTest(address=address):
                self.m.navigate("about:blank")
                self.m.navigate(self.base + "settings/settings.html" + address)
                self.assertTrue(harness.wait_until(lambda pane=pane: where() == f"about:preferences#{pane}", 15), where())
                self.assertEqual(self.m.chrome("return gBrowser.tabs.length;"), 1, "it opened a second tab")
        # Going back does not bounce: it lands on what this page still holds, and stays there.
        self.m.chrome("gBrowser.selectedBrowser.goBack();")
        self.assertTrue(harness.wait_until(lambda: where().startswith(self.base + "settings/settings.html"), 10), where())
        time.sleep(1)
        self.assertEqual(where(), self.base + "settings/settings.html")

    def test_01c_the_band_opens_the_settings_page_at_its_pane(self):
        """The band's protection state and its route mark led to the old sections; they open the settings page now."""
        where = lambda: self.m.chrome("return gBrowser.selectedBrowser.currentURI.spec;")  # noqa: E731
        for button in (".nv-band-protection", ".nv-band-route"):
            with self.subTest(button=button):
                self.m.navigate("about:blank")
                press = "const b = document.querySelector(arguments[0]); b?.click(); return !!b;"
                self.assertTrue(self.m.chrome(press, [button]))
                self.assertTrue(harness.wait_until(lambda: where() == "about:preferences#nulavioProfiles", 15), where())
                self.m.chrome("gBrowser.removeTab(gBrowser.selectedTab);")

    def test_02_rail_link_moves_the_keyboard_to_the_section(self):
        self.open("#ai")
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element('.settings-nav a[data-section="integrations"]')})
        self.assertTrue(harness.wait_until(lambda: self.view()["shown"] == ["integrations"], 10))
        self.assertEqual(self.view()["focused"], "integrations-heading")
        self.assertEqual(self.m.execute("return location.hash;"), "#integrations")

    def test_03_every_section_says_how_far_it_reaches(self):
        self.open()
        found = self.m.execute(
            "return Object.fromEntries([...document.querySelectorAll('.settings-main > .section')]"
            ".map(s => [s.id, s.querySelector('.section__head .scope')?.textContent]));"
        )
        for section, key in SCOPES.items():
            self.assertEqual(found.get(section), self.message(key), section)
        groups = self.m.execute("return [...document.querySelectorAll('.settings-nav__group')].map(g => g.textContent);")
        # ("This profile" has no entry left: all of it is drawn by the settings page itself.)
        self.assertEqual(groups, [self.message(k) for k in ("scopeAllProfiles", "scopeComputer")])
        # Every entry of the rail points to a section that exists, in the order of its group.
        entries = self.m.execute("return [...document.querySelectorAll('.settings-nav a')].map(a => a.dataset.section);")
        # ADR 0008: Layout, Aparência and Atalhos are drawn by the settings page itself; this page keeps no entry for them.
        native = ("layout", "appearance", "shortcuts")
        self.assertEqual(entries, [section for section in SCOPES if section not in native])
        # ...and its own search does not offer them either: one option, one place.
        self.type_search(self.message("layoutHeading").lower())
        self.assertTrue(harness.wait_until(lambda: self.view()["view"] == "search", 5))
        self.assertNotIn("layout", self.view()["shown"])
        self.type_search("")
        self.assertNotIn(self.message("settingsIntro"), ["", "settingsIntro"])

    def test_04_search_filters_the_cards_of_every_section(self):
        self.open("#layout")
        # A word of the integrations' introduction ("verificação"), typed without accents, in lower case.
        words = [w.strip(".,;:") for w in self.message("connectIntro").split()]
        word = max(words, key=len)
        query = self.m.execute("return arguments[0].normalize('NFD').replace(/\\p{M}/gu, '').toLowerCase();", [word])
        self.type_search(query)
        self.assertTrue(harness.wait_until(lambda: self.view()["view"] == "search", 5))
        state = self.view()
        self.assertIn("integrations", state["shown"])
        self.assertNotIn("layout", state["shown"])
        self.assertEqual(state["current"], [])  # results span sections: the rail marks none
        self.assertTrue(state["results"])
        self.shoot("search-results")
        # Several words: each must be found, in any order.
        two = self.m.execute(
            "return browser.i18n.getMessage('connectIntro').normalize('NFD').replace(/\\p{M}/gu, '').toLowerCase()"
            ".replace(/[.,;:]/g, '').split(' ').filter(w => w.length > 5).slice(0, 2).reverse().join(' ');"
        )
        self.type_search(two)
        self.assertTrue(harness.wait_until(lambda: "integrations" in self.view()["shown"], 5), two)
        self.type_search(f"{two} zzzz")
        self.assertTrue(harness.wait_until(lambda: self.view()["shown"] == [], 5))
        self.type_search("zzzz-nada")
        none = self.message("settingsSearchNone", "zzzz-nada")
        self.assertTrue(harness.wait_until(lambda: self.view()["results"] == none, 5), self.view())
        self.assertEqual(self.view()["shown"], [])
        # Escape leaves the search and returns to the section of the address.
        self.m.send("WebDriver:ElementSendKeys", {"id": self.m.find_element("#settings-search"), "text": ""})
        self.assertTrue(harness.wait_until(lambda: self.view()["shown"] == ["layout"], 5))
        self.assertIsNone(self.view()["results"])

    def test_05_header_names_the_profile_being_configured(self):
        self.open()
        self.assertTrue(
            harness.wait_until(lambda: not self.m.execute("return document.getElementById('settings-where').hidden;"), 10)
        )
        where = self.m.execute(
            "const w = document.getElementById('settings-where');"
            "return {label: w.querySelector('.settings-where__label').textContent,"
            " name: w.querySelector('.settings-where__name').textContent, chip: Boolean(w.querySelector('.chip'))};"
        )
        self.assertEqual(where, {"label": self.message("whereLabel"), "name": "Pessoal", "chip": True})

    def test_06_a_result_is_shown_next_to_its_control(self):
        self.open("#ai")
        self.assertTrue(harness.wait_until(lambda: self.view()["shown"] == ["ai"], 10))
        switch = self.m.find_element("#ai-stop")
        before = self.m.execute("return document.getElementById('ai-stop').checked;")
        self.m.send("WebDriver:ElementClick", {"id": switch})
        try:
            mark = harness.wait_until(
                lambda: self.m.execute(
                    "const m = document.querySelector('#ai-stop').closest('.check').querySelector('.inline-status');"
                    "return m && {text: m.textContent, level: m.dataset.level, hidden: m.getAttribute('aria-hidden')};"
                ),
                10,
            )
            said = self.message("aiResumedNow" if before else "aiStoppedNow")
            self.assertEqual(mark, {"text": said, "level": "ok", "hidden": "true"})
            status = self.m.execute(
                "const s = document.getElementById('status');"
                "return {text: s.textContent, inline: s.hasAttribute('data-inline'), clip: getComputedStyle(s).clipPath};"
            )
            name = self.message("aiStopLabel")
            self.assertEqual(status["text"], self.message("statusNamed", name, said))
            self.assertTrue(status["inline"])  # spoken, not shown twice
            self.assertNotEqual(status["clip"], "none")
            # The switch keeps its own name: the mark is not part of it.
            label = self.m.execute(
                "return document.getElementById('ai-stop').labels[0].querySelector('span > span').textContent;"
            )
            self.assertEqual(label, name)
            self.shoot("inline-saved", full=False)
        finally:
            if self.m.execute("return document.getElementById('ai-stop').checked;") != before:
                self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#ai-stop")})
                time.sleep(0.5)

    def test_07_captures_every_section_in_both_themes(self):
        self.open()
        sections = self.m.execute(
            "return [...document.querySelectorAll('.settings-nav li:not([hidden]) a')].map(a => a.dataset.section);"
        )
        self.assertGreaterEqual(len(sections), 2)  # what is left in this page's rail (ADR 0008, ADR 0011)
        for section in sections:
            self.open(f"#{section}")
            self.assertTrue(harness.wait_until(lambda section=section: self.view()["shown"] == [section], 10))
            self.shoot(section)
        # A narrow window: the rail becomes a row above the page, and still marks the section.
        rect = self.m.send("WebDriver:GetWindowRect")
        self.m.send("WebDriver:SetWindowRect", {"width": 760, "height": 900})
        try:
            self.open("#ai")
            self.assertTrue(harness.wait_until(lambda: self.view()["shown"] == ["ai"], 10))
            self.assertEqual(
                self.m.execute(
                    "return getComputedStyle(document.querySelector('.settings')).gridTemplateColumns.split(' ').length;"
                ),
                1,
            )
            self.assertEqual(self.view()["current"], ["ai"])
            self.shoot("narrow-ai")
            # QA R2-1: a section near the end keeps its entry in the visible part of the row.
            self.open("#integrations")
            self.assertTrue(harness.wait_until(lambda: self.view()["shown"] == ["integrations"], 10))
            seen = self.m.execute(
                "const nav = document.querySelector('.settings-nav').getBoundingClientRect();"
                "const a = document.querySelector('.settings-nav a[aria-current]').getBoundingClientRect();"
                "const n = document.querySelector('.settings-nav');"
                "return {inside: a.left >= nav.left - 1 && a.right <= nav.right + 1,"
                " scrollable: n.scrollWidth > n.clientWidth, marked: n.hasAttribute('data-more-start')};"
            )
            self.assertTrue(seen["inside"], seen)
            if seen["scrollable"]:
                self.assertTrue(seen["marked"], seen)  # entries before it are hidden: the row says so
            self.shoot("narrow-integrations")
        finally:
            self.m.send("WebDriver:SetWindowRect", {"width": rect["width"], "height": rect["height"]})

    def test_09_slow_lists_show_placeholder_rows_and_never_stay_busy(self):
        """Audit SPA-26: a list still being read shows still placeholder rows after 400 ms, not before;
        once every section has answered, no list is left busy."""
        self.open("#integrations")
        self.assertTrue(
            harness.wait_until(lambda: not self.m.execute("return document.querySelector('.list[aria-busy=\"true\"]');"), 30),
            self.m.execute("return [...document.querySelectorAll('.list[aria-busy=\"true\"]')].map(l => l.id);"),
        )
        probe = (
            "const ul = document.createElement('ul'); ul.className = 'list'; ul.id = 'probe';"
            "ul.setAttribute('aria-busy', 'true'); document.querySelector('#integrations .card').append(ul);"
            "return getComputedStyle(ul).visibility;"
        )
        self.assertEqual(self.m.execute(probe), "hidden")  # a fast list never flashes them
        time.sleep(0.6)
        late = self.m.execute(
            "const s = getComputedStyle(document.getElementById('probe'));"
            "return {visibility: s.visibility, rows: s.backgroundImage.split('linear-gradient').length - 1};"
        )
        self.assertEqual((late["visibility"], late["rows"]), ("visible", 3), late)
        self.shoot("busy-list", full=False)

    def shoot(self, name: str, full: bool = True) -> None:
        for dark in (0, 1):
            self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            time.sleep(0.4)
            scheme = "dark" if dark else "light"
            (self.shots / f"{name}-{scheme}.png").write_bytes(self.m.screenshot_png(full=full))
        self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")


if __name__ == "__main__":
    unittest.main()
