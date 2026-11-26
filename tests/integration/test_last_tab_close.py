"""Close and Cancel on a Shell page that is its window's only tab (#700, #720). Nulavio build only.

Closing a window's only tab would close the window, so these pages open a new tab there instead. They
used to load ``about:newtab`` into their own tab with ``tabs.update``, which the engine refuses from an
extension page: the button did nothing and the page stayed. Each page here is opened alone in a
window of its own, in the state that shows its Close or Cancel button, and the button must leave
that window open on the new-tab page, without the Shell page.

The pages for a held link (``routing/ask.html``, ``routing/blocked.html``) do the same (#720): "Don't
open", and "Open in …" once the link went to the other profile, used to remove their tab whatever else
was in the window, which closed the window, and the browser with its last window. The routing module
holds a link for them as it does for a real one, and the call that would open another profile is
replaced by a recorder, so nothing is started.

The permission request (``ai/request.html``) and the unlock page (``vault/unlock.html``) close only
after a real answer or unlock; they use the same function (``tests/unit/test_shell.py``), and
``test_ai_ui`` and ``test_vault_ui`` close them in a window with other tabs.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

# Page, the state it shows when opened bare, and the button that closes it in that state.
PAGES = (
    ("guard/review.html", None, "#close"),
    ("vault/create.html", None, "#cancel"),
    ("warning/warning.html", "missing", "#delete"),  # no download: only "Close tab" is left
    ("passwords/lookalike.html", "invalid", "#go-real"),  # no site to compare: only "Close tab" is left
)

# A held-link page, what the routing module holds for it, and the button that closes it. No rule, or a rule
# whose profile is in this browser: "Don't open" is the quiet button, "Open in …" the primary one.
HELD = (
    ("routing/ask.html", {}, "#actions .button--quiet"),
    ("routing/blocked.html", {"why": "missing"}, "#actions .button--quiet"),
    ("routing/ask.html", {"rule": True}, "#actions .button--primary"),
)
ROUTING = 'const R = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs").NulavioRouting;'
PROFILES = 'const P = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs").NulavioProfiles;'

NEW_TAB_URL = """
const {AboutNewTab} = ChromeUtils.importESModule("resource:///modules/AboutNewTab.sys.mjs");
return AboutNewTab.newTabURL;
"""

# The browser window showing `url`, by its browsing context id, with the address of each of its tabs.
FIND_WINDOW = """
const [url] = arguments;
for (const w of Services.wm.getEnumerator("navigator:browser")) {
  const tabs = w.gBrowser.tabs.map(t => t.linkedBrowser.currentURI.spec);
  if (!w.closed && tabs.some(u => u.startsWith(url))) {
    return {id: w.browsingContext.id, tabs};
  }
}
return null;
"""

OPEN_WINDOW = """
const w = OpenBrowserWindow();
await new Promise(resolve => {
  const seen = subject => {
    if (subject === w) {
      Services.obs.removeObserver(seen, "browser-delayed-startup-finished");
      resolve();
    }
  };
  Services.obs.addObserver(seen, "browser-delayed-startup-finished");
});
return w.browsingContext.id;
"""

WINDOW_TABS = """
const [id] = arguments;
const w = [...Services.wm.getEnumerator("navigator:browser")].find(w => w.browsingContext.id === id);
return w && !w.closed ? w.gBrowser.tabs.map(t => t.linkedBrowser.currentURI.spec) : null;
"""

CLOSE_WINDOW = """
const [id] = arguments;
const w = [...Services.wm.getEnumerator("navigator:browser")].find(w => w.browsingContext.id === id);
if (w && !w.closed) { w.close(); }
"""

PAGE_STATE = """
const [selector] = arguments;
return document.readyState === "complete" && Boolean(document.querySelector(selector))
  ? (document.documentElement.dataset.state ?? document.body.dataset.state ?? "") : null;
"""


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: String(e)}));"
    )
    m.set_context("chrome")
    try:
        result = m.execute_async(script, list(args))
    finally:
        m.set_context("content")
    if "error" in result:
        raise AssertionError(result["error"])
    return result["ok"]


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class LastTabCloseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.main = cls.m.window_handles()[0]
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        cls.new_tab = cls.m.chrome(NEW_TAB_URL)

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()

    def open_alone(self, page: str) -> int:
        """`page` as the only tab of a new browser window; returns the window's browsing context id.
        Marionette's own NewWindow is not supported in Nulavio, so the window is opened as the menu does."""
        self.m.switch_to(self.main)
        before = set(self.m.window_handles())
        window = chrome_async(self.m, OPEN_WINDOW)
        self.addCleanup(self.m.chrome, CLOSE_WINDOW, [window])
        created = harness.wait_until(lambda: [h for h in self.m.window_handles() if h not in before], timeout=15)
        self.assertEqual(len(created or []), 1, f"no new window: {created}")
        self.m.switch_to(created[0])
        self.m.navigate(self.base + page)
        return window

    def close_alone(self, page: str, state: str | None, button: str, query: str = "") -> None:
        opened = self.open_alone(page + query)
        # Wait for the expected state itself (a page may show "loading" first), or, for a page with no state,
        # for the page and its button: an empty state is falsy, and would make the wait run out its timeout.
        if state:
            reached = harness.wait_until(lambda: self.m.execute(PAGE_STATE, [button]) == state, timeout=20)
            self.assertTrue(reached, f"{page} did not reach its {state} state: {self.m.execute(PAGE_STATE, [button])}")
        else:
            loaded = harness.wait_until(lambda: self.m.execute(PAGE_STATE, [button]) is not None, timeout=20)
            self.assertTrue(loaded, f"{page} did not load")
        window = self.m.chrome(FIND_WINDOW, [self.base + page])
        self.assertTrue(window, f"{page}: its window was not found")
        self.assertEqual(window["id"], opened, f"{page} did not load in the window opened for it")
        self.assertEqual(len(window["tabs"]), 1, f"{page} is not its window's only tab: {window['tabs']}")
        self.m.execute("document.querySelector(arguments[0]).click();", [button])
        self.m.switch_to(self.main)  # the page's tab goes away: drive from a tab that stays
        # The new-tab page, by the address the override gives it (or its about: name while it loads).
        new_tab = {self.new_tab, "about:newtab"}

        def settled():
            tabs = self.m.chrome(WINDOW_TABS, [window["id"]])
            return tabs if tabs and len(tabs) == 1 and tabs[0] in new_tab else None

        tabs = harness.wait_until(settled, timeout=20) or self.m.chrome(WINDOW_TABS, [window["id"]])
        self.assertIsNotNone(tabs, f"{page}: {button} closed the window")
        self.assertEqual(len(tabs), 1, f"{page}: {button} left {tabs}")
        self.assertIn(tabs[0], new_tab, f"{page}: {button} left {tabs}, not the new-tab page")

    def test_01_close_or_cancel_in_a_windows_only_tab_leaves_the_window_on_a_new_tab(self):
        self.assertTrue(
            self.new_tab.startswith("moz-extension://") and self.new_tab.endswith("/newtab/newtab.html"), self.new_tab
        )
        for page, state, button in PAGES:
            with self.subTest(page=page):
                self.close_alone(page, state, button)

    def test_02_a_held_link_page_in_a_windows_only_tab_leaves_the_window_on_a_new_tab(self):
        other = chrome_async(self.m, PROFILES + "return P.create({name: 'Bancos'});")
        # A recorder instead of what would start the other profile; put back when the test ends.
        chrome_async(
            self.m,
            ROUTING + "R.__calls = []; R.openIn = async (...a) => { R.__calls.push(a); return {action: 'delivered'}; };",
        )
        self.addCleanup(chrome_async, self.m, ROUTING + "delete R.openIn; delete R.__calls;")
        rule = chrome_async(
            self.m,
            ROUTING + "return R.addRule({site: 'held.example', match: 'host', action: 'ask', profileId: args[0]});",
            [other],
        )
        self.addCleanup(chrome_async, self.m, ROUTING + "await R.removeRule(args[0]);", [rule])
        for page, record, button in HELD:
            with self.subTest(page=page, button=button):
                held = chrome_async(
                    self.m,
                    ROUTING + "return R.hold(args[0], {u: 'https://held.example/page', r: args[1], why: args[2]});",
                    [page, rule if record.get("rule") else None, record.get("why")],
                )
                self.close_alone(page, None, button, f"?h={held}")
        # "Open in Bancos" went to the recorder, with the held link, and nothing else did.
        calls = chrome_async(self.m, ROUTING + "return R.__calls;")
        self.assertEqual(calls, [[other, "https://held.example/page"]])


if __name__ == "__main__":
    unittest.main()
