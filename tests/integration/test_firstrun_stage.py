"""ADR 0010: the first run is a stage. The window shows the band and one card of a fixed size; nothing else."""

from __future__ import annotations

import unittest

import harness

SHELL_ID = "shell@nulavio.net"
# The window around the page: staged or not, what the band calls the page, and whether the toolbar is in view.
WINDOW = """
const root = document.documentElement;
const style = getComputedStyle(document.getElementById("nav-bar"));
const band = document.getElementById("nulavio-band").getBoundingClientRect();
return {
  stage: root.hasAttribute("nulavio-stage"),
  name: document.querySelector("#nulavio-band .nv-band-header")?.textContent,
  toolbarShown: style.opacity === "1" && style.pointerEvents !== "none",
  band: band.width > 0 && band.height > 0,
};
"""
# The page: the one card that is its question, where it is, and the facts the welcome lists.
PAGE = """
const shown = [...document.querySelectorAll("main > *")].filter(node => node.checkVisibility({ visibilityProperty: true }));
const card = shown.find(node => node.matches("section"));
const rect = card?.getBoundingClientRect();
return {
  stage: document.documentElement.hasAttribute("data-stage"),
  shown: shown.map(node => node.id),
  card: card?.id,
  rect: rect && [rect.x, rect.y, rect.width, rect.height].map(Math.round),
  levels: [...document.querySelectorAll("#firstrun-facts li")].map(li => li.dataset.level),
  primary: card ? card.querySelectorAll(".button--primary").length : 0,
};
"""
# The control that answers each step, and the card it leads to.
STEPS = [
    ("firstrun-start", "layout-choice"),
    ("layout-choice-done", "dns-choice"),
    ("dns-keep-system", "firstrun-passwords"),
    ("firstrun-passwords-later", "firstrun-default"),
    ("firstrun-default-later", "firstrun-done"),
]


@unittest.skipUnless(harness.nulavio_engine(), "the first run needs the built-in Shell on the engine")
class FirstRunStageTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Stage")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()
        self.newtab = self.m.chrome(f"return WebExtensionPolicy.getByID('{SHELL_ID}').getURL('newtab/newtab.html');")
        harness.wait_until(lambda: self.m.chrome("return gBrowser.currentURI.spec;") == self.newtab, 15)
        # A genuinely new profile's first run (the harness turns it off for every other suite).
        self.m.chrome(
            "Services.prefs.setStringPref('nulavio.firstrun.done', '');"
            "Services.prefs.setBoolPref('nulavio.startpage.shellFirstTab', true);"
            "Services.prefs.setBoolPref('nulavio.layout.choicePending', true);"
            "Services.prefs.setBoolPref('nulavio.dns.chosen', false);"
        )
        self.addCleanup(self.m.chrome, "Services.prefs.setStringPref('nulavio.firstrun.done', 'finished');")
        self.m.navigate(self.newtab)
        self.assertTrue(harness.wait_until(lambda: self.page()["card"] == "firstrun-welcome", 15), self.page())

    def page(self):
        return self.m.execute(PAGE)

    def window(self):
        return self.m.chrome(WINDOW)

    def click(self, control):
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f"#{control}")})

    def test_01_the_welcome_owns_the_window_and_states_only_what_is_true(self):
        harness.wait_until(lambda: self.window()["stage"], 10)
        window, page = self.window(), self.page()
        self.assertTrue(window["band"], window)
        self.assertIn("·", window["name"], window)  # "Nulavio · Boas-vindas": the band names the stage
        self.assertFalse(window["toolbarShown"], window)
        self.assertTrue(page["stage"], page)
        self.assertEqual(page["card"], "firstrun-welcome", page)
        # Nothing else on the page: no search, no status card, no second card.
        self.assertEqual([node for node in page["shown"] if node != "firstrun-progress"], ["firstrun-welcome"], page)
        self.assertTrue(page["levels"], page)
        self.assertEqual(set(page["levels"]), {"ok"}, "the welcome lists only facts that are true now")
        self.assertEqual(page["primary"], 1, page)

    def test_02_the_card_keeps_its_place_and_size_on_every_step(self):
        welcome = self.page()
        seen = [welcome["card"]]
        for control, _ in STEPS:
            if not self.m.execute("return Boolean(document.getElementById(arguments[0])?.checkVisibility());", [control]):
                continue  # a step that does not apply here (no default-browser support in this session)
            self.click(control)
            harness.wait_until(lambda before=seen[-1]: self.page()["card"] not in (None, before), 10)
            page = self.page()
            seen.append(page["card"])
            with self.subTest(card=page["card"]):
                self.assertTrue(page["stage"], page)
                self.assertEqual(page["rect"], welcome["rect"], "the card moved or changed size between steps")
                self.assertLessEqual(page["primary"], 1, page)
        self.assertGreaterEqual(len(seen), 4, seen)
        self.assertEqual(self.page()["card"], "firstrun-done")
        self.assertTrue(self.window()["stage"])
        self.click("firstrun-finish")
        harness.wait_until(lambda: not self.window()["stage"], 10)
        window = self.window()
        self.assertTrue(window["toolbarShown"], "the ordinary window comes back when the first run ends")
        self.assertFalse(self.page()["stage"])

    def test_03_use_the_defaults_ends_it_at_once(self):
        harness.wait_until(lambda: self.window()["stage"], 10)
        self.click("firstrun-skip")
        harness.wait_until(lambda: not self.window()["stage"], 10)
        self.assertTrue(self.window()["toolbarShown"])
        self.assertIn("finished", self.m.chrome('return Services.prefs.getStringPref("nulavio.firstrun.done", "");'))

    def test_04_another_tab_is_never_staged(self):
        harness.wait_until(lambda: self.window()["stage"], 10)
        self.m.chrome('gBrowser.selectedTab = gBrowser.addTrustedTab("about:license");')
        harness.wait_until(lambda: not self.window()["stage"], 10)
        self.assertTrue(self.window()["toolbarShown"])
        self.m.chrome("gBrowser.selectedTab = gBrowser.tabs[0];")
        harness.wait_until(lambda: self.window()["stage"], 10)


if __name__ == "__main__":
    unittest.main()
