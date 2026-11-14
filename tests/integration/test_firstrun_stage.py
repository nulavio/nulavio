"""ADR 0010: the first run is a stage. The window shows the band and one card of a fixed size; nothing else.

The card has two panes (what is asked and the actions; the choice itself), and every choice is made in it:
the DNS options, the password managers, a protected profile."""

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
  // The three parts of the card: where each is, and how much of its content does not fit.
  panes: Object.fromEntries(["say", "show", "do"].map(name => {
    const pane = card?.querySelector(`.firstrun__${name}`);
    const box = pane?.getBoundingClientRect();
    const rect = pane && [box.x, box.y, box.right, box.bottom].map(Math.round);
    return [name, pane && { rect, cut: pane.scrollHeight - pane.clientHeight }];
  })),
  sideways: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  height: innerHeight,
};
"""
PRIVACY = "resource://builtin-addons/nulavio-shell/modules/NulavioPrivacy.sys.mjs"
DNS = f"return ChromeUtils.importESModule('{PRIVACY}').NulavioPrivacy.dns();"
# The control that answers each step, and the card it leads to.
STEPS = [
    ("firstrun-start", "layout-choice"),
    ("layout-choice-done", "dns-choice"),
    ("dns-apply", "firstrun-passwords"),
    ("firstrun-passwords-next", "firstrun-default"),
    ("firstrun-default-later", "firstrun-profile"),
    ("firstrun-profile-later", "firstrun-done"),
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
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(control if control[0] in "#.[" else f"#{control}")})

    def go_to(self, card):
        """Answer each step with its main "go on" control until `card` is the question."""
        for control, _ in STEPS:
            if self.page()["card"] == card:
                return
            if not self.m.execute("return Boolean(document.getElementById(arguments[0])?.checkVisibility());", [control]):
                continue
            before = self.page()["card"]
            self.click(control)
            harness.wait_until(lambda before=before: self.page()["card"] not in (None, before), 10)
        self.assertEqual(self.page()["card"], card)

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

    def test_01b_the_welcome_says_so_when_a_protection_is_off(self):
        """A profile whose HTTPS-Only was switched off (a managed setting, a `user.js`): the welcome lists it with
        its warning, not only what is fine."""
        self.m.chrome("Services.prefs.setBoolPref('dom.security.https_only_mode', false);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('dom.security.https_only_mode');")
        self.m.navigate(self.newtab)
        self.assertTrue(harness.wait_until(lambda: self.page()["card"] == "firstrun-welcome", 15), self.page())
        self.assertTrue(harness.wait_until(lambda: "warn" in self.page()["levels"], 10), self.page()["levels"])
        facts = self.m.execute(
            "return [...document.querySelectorAll('#firstrun-facts li')].map(li => [li.dataset.level, li.textContent]);"
        )
        status = self.m.execute(
            "const dd = document.querySelector('#status [data-status=https]');"
            " return [dd.dataset.level, `${dd.previousElementSibling.textContent}: ${dd.textContent}`];"
        )
        self.assertEqual(status[0], "warn", status)
        self.assertIn(status, facts, "the welcome leaves out what the status card says about HTTPS-Only")

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
                cut = [page["panes"][name]["cut"] for name in ("say", "show", "do")]
                self.assertEqual(cut, [0, 0, 0], "a pane cuts its content")
        self.assertGreaterEqual(len(seen), 5, seen)
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
        self.assertTrue(harness.wait_until(lambda: self.window()["stage"], 10), "back on the first run's tab, not staged")

    def test_04b_a_tab_opened_later_keeps_the_keyboard_in_the_address_field(self):
        """New-user QA (2026-11-11): Ctrl+T and typing at once went nowhere, because the stage took the keyboard."""
        harness.wait_until(lambda: self.window()["stage"], 10)
        self.m.chrome('gBrowser.selectedTab = gBrowser.addTrustedTab("about:license");')
        harness.wait_until(lambda: not self.window()["stage"], 10)
        self.m.chrome("BrowserCommands.openTab();")
        self.addCleanup(self.m.chrome, "while (gBrowser.tabs.length > 1) gBrowser.removeTab(gBrowser.tabs.at(-1));")
        # The first run is not finished: the new tab shows it, staged.
        self.assertTrue(harness.wait_until(lambda: self.window()["stage"], 10), "the new tab is not the first run's stage")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return gURLBar.focused;"), 5), "the stage took the keyboard")
        self.assertTrue(self.window()["toolbarShown"], "the address field has the keyboard and is not in view")

    def test_05_two_panes_and_the_band_drawn_small_says_what_the_band_says(self):
        harness.wait_until(lambda: self.window()["stage"], 10)
        panes = self.page()["panes"]
        say, show, do = (panes[name]["rect"] for name in ("say", "show", "do"))
        self.assertGreaterEqual(show[0], say[2], "the choice is the right pane")
        self.assertGreaterEqual(do[1], say[3], "the actions sit under what is asked")
        self.assertEqual(do[0], say[0])
        small = self.m.execute(
            "return [...document.querySelectorAll('#firstrun-band > :not(.chip)')].map(node => node.textContent);"
        )
        real = self.m.chrome(
            "const band = document.getElementById('nulavio-band');"
            "return [band.querySelector('.nv-band-name')?.textContent, band.querySelector('.nv-band-protection')?.textContent];"
        )
        self.assertEqual(small, real, "the picture of the band and the band disagree")

    def test_06_dns_changes_nothing_before_the_main_action_and_then_does_what_was_picked(self):
        self.go_to("dns-choice")
        options = self.m.execute(
            "return [...document.querySelectorAll('#dns-options .option')].map(o => [o.dataset.value,"
            " o.querySelector('input').checked, Boolean(o.querySelector('.badge'))]);"
        )
        self.assertEqual(options, [["system", True, True], ["fallback", False, False]], "the one in use is checked and says so")
        self.click('[data-value="fallback"] .option__pick')
        self.assertTrue(self.m.execute("return document.getElementById('dns-service').checkVisibility();"))
        self.m.execute("document.getElementById('dns-service').value = 'quad9';")
        before = self.m.chrome(DNS)
        self.assertEqual((before["choice"], before["chosen"]), ("default", False), "picking an option changed the resolver")
        self.click("dns-apply")
        harness.wait_until(lambda: self.page()["card"] != "dns-choice", 10)
        after = self.m.chrome(DNS)
        self.assertEqual((after["choice"], after["provider"], after["chosen"]), ("fallback", "quad9", True))
        self.addCleanup(
            self.m.chrome, "Services.prefs.clearUserPref('network.trr.mode'); Services.prefs.clearUserPref('network.trr.uri');"
        )
        # #142: back on the question, the option in use says what is in use: not "the browser's default" once a
        # service was chosen, and not "your network answers" once nothing falls back to it (strict).
        self.back("dns-choice")
        keep = (
            "const o = document.querySelector('#dns-options [data-value=keep]');"
            "return o && [o.querySelector('.option__title span').textContent, o.querySelector('.hint').textContent];"
        )
        msg = lambda key, *subs: self.m.execute("return browser.i18n.getMessage(arguments[0], arguments[1]);", [key, list(subs)])  # noqa: E731
        name = self.m.execute("return browser.i18n.getMessage('dnsQuad9');") or "Quad9"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(keep) is not None, 10))
        title, note = self.m.execute(keep)
        self.assertEqual(title, msg("dnsOptionKeepChosen"))
        self.assertEqual(note, msg("dnsOptionKeepNote", name))
        self.m.chrome("Services.prefs.setIntPref('network.trr.mode', 3);")
        self.m.navigate(self.newtab)  # the question is drawn from the resolver as it is when the page shows it
        if self.page()["card"] != "dns-choice":
            self.back("dns-choice")
        strict = msg("dnsOptionKeepNoteStrict", name)
        self.assertTrue(harness.wait_until(lambda: (self.m.execute(keep) or [None, None])[1] == strict, 10), self.m.execute(keep))

    def test_07_a_password_manager_is_chosen_in_the_card(self):
        # Start from a profile where nothing saves passwords, so the choice is visible.
        self.m.chrome("Services.prefs.setBoolPref('signon.rememberSignons', false);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('signon.rememberSignons');")
        self.m.navigate(self.newtab)
        self.assertTrue(harness.wait_until(lambda: self.page()["card"] == "firstrun-welcome", 15), self.page())
        self.go_to("firstrun-passwords")
        rows = (
            "return [...document.querySelectorAll('#firstrun-providers li')].map(li =>"
            " [li.dataset.provider, li.dataset.inUse, Boolean(li.querySelector('.button'))]);"
        )
        harness.wait_until(lambda: len(self.m.execute(rows)) == 4, 10)
        self.assertEqual([row[0] for row in self.m.execute(rows)], ["builtin", "proton-pass", "keepassxc", "bitwarden"])
        self.assertEqual({row[1] for row in self.m.execute(rows)}, {"false"}, self.m.execute(rows))
        self.click('[data-provider="builtin"] .button')
        self.assertTrue(harness.wait_until(lambda: self.m.execute(rows)[0][1:] == ["true", False], 10), self.m.execute(rows))
        self.assertTrue(self.m.chrome("return Services.prefs.getBoolPref('signon.rememberSignons');"))
        self.assertEqual(self.page()["primary"], 1, "one main action: going on")
        self.click("firstrun-passwords-next")
        harness.wait_until(lambda: self.page()["card"] != "firstrun-passwords", 10)
        self.assertNotEqual(self.page()["card"], "firstrun-passwords")

    def test_08_a_protected_profile_is_offered_last_and_made_in_the_vault_steps(self):
        self.go_to("firstrun-profile")
        name = self.m.chrome("return document.querySelector('#nulavio-band .nv-band-name')?.textContent;")
        self.assertIn(name, self.m.execute("return document.getElementById('firstrun-profile-lead').textContent;"))
        self.click("firstrun-profile-create")
        tabs = "return gBrowser.tabs.map(tab => [tab.linkedBrowser.currentURI.filePath, tab.selected]);"
        self.assertTrue(harness.wait_until(lambda: ["/vault/create.html", True] in self.m.chrome(tabs), 10), self.m.chrome(tabs))
        self.addCleanup(self.m.chrome, "gBrowser.removeTab(gBrowser.tabs.at(-1));")
        self.assertFalse(self.window()["stage"], "the Vault's steps are an ordinary tab, with the address bar")
        self.assertTrue(self.window()["toolbarShown"])
        # The first run went on in its own tab and waits there.
        self.assertEqual(self.page()["card"], "firstrun-done")

    def back(self, card):
        self.click("firstrun-back")
        self.assertTrue(harness.wait_until(lambda: self.page()["card"] == card, 10), self.page())

    def test_08b_back_shows_an_answered_step_again_and_going_on_walks_the_steps_in_order(self):
        back_shown = "return document.getElementById('firstrun-back').checkVisibility({ visibilityProperty: true });"
        self.assertFalse(self.m.execute(back_shown), "there is nothing before the welcome")
        self.go_to("firstrun-passwords")
        self.addCleanup(
            self.m.chrome, "Services.prefs.clearUserPref('network.trr.mode'); Services.prefs.clearUserPref('network.trr.uri');"
        )
        answered = self.m.chrome(DNS)
        self.assertTrue(answered["chosen"])
        self.assertTrue(self.m.execute(back_shown))
        # It is under the card on screen and after it in the page's order, so the keyboard meets it after the card's actions.
        after_card = self.m.execute(
            "const back = document.getElementById('firstrun-back'), card = document.getElementById('firstrun-passwords');"
            "return [Boolean(card.compareDocumentPosition(back) & Node.DOCUMENT_POSITION_FOLLOWING),"
            " back.getBoundingClientRect().top >= card.getBoundingClientRect().bottom];"
        )
        self.assertEqual(after_card, [True, True])
        # Back to DNS: the card is the question again, with the resolver in use checked; nothing changed by looking.
        self.back("dns-choice")
        checked = "return document.querySelector('#dns-options input:checked')?.value ?? null;"
        self.assertIn(self.m.execute(checked), ("system", "keep"))
        self.assertEqual(self.m.execute("return document.getElementById('firstrun-progress').textContent;"), "Etapa 2 de 5")
        self.assertEqual(self.m.chrome(DNS), answered)
        # Back again, to the arrangement: another one is chosen there, and it applies as it did the first time.
        self.back("layout-choice")
        self.click('#layout-choice input[value="top"]')
        layout = (
            "return ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioLayout.sys.mjs')"
            ".NulavioLayout.state(window).then(state => state.preset);"
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(layout) == "top", 10), self.m.chrome(layout))
        # Going on from there does not jump to the first unanswered step: DNS comes next, as in the order asked.
        harness.wait_until(
            lambda: self.m.execute(
                "return document.getElementById('layout-choice-done').getAttribute('aria-disabled') !== 'true';"
            ),
            10,
        )
        self.click("layout-choice-done")
        self.assertTrue(harness.wait_until(lambda: self.page()["card"] == "dns-choice", 10), self.page())
        self.click("dns-apply")
        self.assertTrue(harness.wait_until(lambda: self.page()["card"] == "firstrun-passwords", 10), self.page())
        self.assertEqual(self.m.chrome(DNS)["choice"], answered["choice"], "keeping the answer changed the resolver")
        # From the last card, back reaches the question before it; the cards answered again stay answered.
        self.go_to("firstrun-done")
        self.back("firstrun-profile")
        self.click("firstrun-profile-later")
        self.assertTrue(harness.wait_until(lambda: self.page()["card"] == "firstrun-done", 10), self.page())
        self.click("firstrun-finish")
        self.assertTrue(harness.wait_until(lambda: not self.page()["stage"], 10), self.page())
        after = self.m.execute(
            "return ['layout-choice', 'dns-choice', 'firstrun-back'].map(id => document.getElementById(id).checkVisibility());"
        )
        self.assertEqual(after, [False, False, False], "a card shown again was left on the new tab")

    def test_09_in_a_short_window_the_panes_stack_and_the_actions_stay_on_screen(self):
        size = self.m.chrome("return [window.outerWidth, window.outerHeight];")
        self.addCleanup(self.m.chrome, "window.resizeTo(arguments[0], arguments[1]);", size)
        self.m.chrome("window.resizeTo(911, 512);")
        harness.wait_until(lambda: self.m.execute("return innerWidth;") <= 911, 10)
        for control, _ in [(None, None), *STEPS]:
            if control:
                if not self.m.execute("return Boolean(document.getElementById(arguments[0])?.checkVisibility());", [control]):
                    continue
                before = self.page()["card"]
                self.m.execute("document.getElementById(arguments[0]).click();", [control])
                harness.wait_until(lambda before=before: self.page()["card"] not in (None, before), 10)
            page = self.page()
            with self.subTest(card=page["card"]):
                say, show, do = (page["panes"][name] for name in ("say", "show", "do"))
                self.assertGreaterEqual(show["rect"][1], say["rect"][3], "stacked: the choice comes under what is asked")
                # The actions stay on screen while the choice scrolls under them: never below the fold.
                self.assertLessEqual(do["rect"][3], page["height"], "the actions are below the fold")
                self.assertEqual([say["cut"], show["cut"], do["cut"]], [0, 0, 0])
                self.assertLessEqual(page["sideways"], 0, "the page scrolls sideways")


if __name__ == "__main__":
    unittest.main()
