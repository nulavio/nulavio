"""The lists a new profile starts with in uBlock Origin (Nulavio build): cookie notices hidden by default.

`distribution/policies.json` hands uBlock Origin its own list registry with the lists of
`browser/distribution/content-filter.json` switched on (scripts/build/make_distribution.py). The test starts a
new profile as a person does, with the real signed uBlock Origin the policy installs, and checks what the
person gets: the lists are on beside uBlock Origin's own defaults, a cookie notice is hidden, an update of the
registry from uBlock Origin's servers keeps them, and a list the person switches off stays off.

It needs the network, as a first start does: the policy downloads uBlock Origin and uBlock Origin downloads
the lists. Without it the module is skipped and says so.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

ROOT = Path(__file__).resolve().parents[2]
UBLOCK = "uBlock0@raymondhill.net"
CONFIG = json.loads((ROOT / "browser" / "distribution" / "content-filter.json").read_text(encoding="utf-8"))
STOCK = json.loads((ROOT / "browser" / "distribution" / "ublock-origin" / "assets.json").read_text(encoding="utf-8"))
DEFAULT_ON = set(CONFIG["default_on"])
# EasyList switches hiding by id and class off on 127.0.0.1 and localhost (`@@://127.0.0.1$generichide`), so the
# fixture is reached by a name the engine resolves to this machine.
HOST = "nulavio-notice.test"

# uBlock Origin's own state, read (never written) from its extension storage by the test.
STATE = """
const {AddonManager} = ChromeUtils.importESModule("resource://gre/modules/AddonManager.sys.mjs");
const addon = await AddonManager.getAddonByID(args[0]);
if (!addon?.isActive) return null;
const {ExtensionStorageIDB} = ChromeUtils.importESModule("resource://gre/modules/ExtensionStorageIDB.sys.mjs");
const policy = WebExtensionPolicy.getByID(args[0]);
const store = await ExtensionStorageIDB.open(ExtensionStorageIDB.getStoragePrincipal(policy.extension));
const data = await store.get(["selectedFilterLists", "cachedManagedStorage"]);
return {
  version: addon.version,
  lists: policy.getURL("3p-filters.html"),
  selected: data.selectedFilterLists ?? null,
  managed: Object.keys(data.cachedManagedStorage ?? {}),
};
"""

# In uBlock Origin's own "Filter lists" page: the registry it keeps, and the page's controls.
REGISTRY = """
const done = arguments[arguments.length - 1];
(async () => {
  const db = await new Promise((resolve, reject) => {
    const request = indexedDB.open("uBlock0CacheStorage");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const read = key => new Promise(resolve => {
    const request = db.transaction("uBlock0CacheStorage").objectStore("uBlock0CacheStorage").get(key);
    request.onsuccess = () => resolve(request.result?.value);
    request.onerror = () => resolve(undefined);
  });
  let registry = await read("assetSourceRegistry");
  if (typeof registry === "string") registry = JSON.parse(registry);
  db.close();
  return Object.fromEntries(arguments[0].map(key => [key, registry?.[key] ? registry[key].off ?? "absent" : null]));
})().then(done, error => done({error: String(error)}));
"""

BANNERS = """
const shown = id => { const el = document.getElementById(id); return !!el && getComputedStyle(el).display !== "none"; };
return {title: document.title, content: shown("content"), onetrust: shown("onetrust-banner-sdk"), banner: shown("cookie-banner")};
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


@unittest.skipUnless(harness.nulavio_engine(), "the default lists come with the Nulavio build's policies (NULAVIO_ENGINE)")
class ContentFilterDefaultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.server = harness.FixtureServer().__enter__()
        cls.m = cls.session.start()
        cls.artifacts = Path(os.environ.get("NULAVIO_TEST_ARTIFACTS") or cls.session.tmp / "artifacts")
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.counter = 0
        # Test profile only: the name reaches the fixture server, with an HTTPS-Only exception for it.
        chrome_async(
            cls.m,
            "Services.prefs.setStringPref('network.dns.localDomains', args[0]);"
            "const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin(args[1]);"
            "Services.perms.addFromPrincipal(p, 'https-only-load-insecure', Ci.nsIPermissionManager.ALLOW_ACTION);",
            [HOST, f"http://{HOST}:{cls.server.port}"],
        )
        if not harness.wait_until(lambda: (cls.state() or {}).get("selected"), timeout=120, interval=1.0):
            cls.tearDownClass()
            raise unittest.SkipTest("uBlock Origin was not installed by the policy in two minutes (no network?)")

    @classmethod
    def tearDownClass(cls):
        cls.session.stop()
        cls.server.__exit__(None, None, None)

    @classmethod
    def state(cls):
        return chrome_async(cls.m, STATE, [UBLOCK])

    def notice(self, settle: float = 4.0) -> dict:
        """Load the fixture again (a new address each time) and say which of its elements show.

        uBlock Origin hides by id and class a moment after the page is parsed, so a notice counts as shown
        only when it still shows after `settle` seconds.
        """
        type(self).counter += 1
        self.m.navigate(f"http://{HOST}:{self.server.port}/cookie-notice?n={self.counter}")
        harness.wait_until(lambda: self.m.execute(BANNERS)["onetrust"] is False, timeout=settle)
        return self.m.execute(BANNERS)

    def lists_page(self) -> None:
        self.m.navigate(self.state()["lists"])
        drawn = "return !!document.querySelector('.listEntry[data-key=\"easylist\"]');"
        ready = harness.wait_until(lambda: self.m.execute(drawn), timeout=30)
        self.assertTrue(ready, "uBlock Origin's list page did not draw its lists")

    def test_01_a_new_profile_has_the_cookie_notice_lists_beside_the_stock_ones(self):
        state = self.state()
        self.assertEqual(state["version"], CONFIG["registry"]["version"], "the policy installs the pinned version first")
        selected = set(state["selected"])
        stock_on = {key for key, entry in STOCK.items() if entry.get("content") == "filters" and "off" not in entry}
        self.assertGreater(len(stock_on), 5)
        self.assertTrue(selected >= DEFAULT_ON, f"not switched on: {DEFAULT_ON - selected}")
        self.assertTrue(stock_on <= selected, f"a stock default was lost: {stock_on - selected}")
        self.assertIn("user-filters", selected)
        # What uBlock Origin adds by itself for the person's language still comes (AdGuard Spanish/Portuguese here).
        extra = selected - stock_on - DEFAULT_ON - {"user-filters"}
        self.assertEqual({key for key in extra if STOCK.get(key, {}).get("group") != "regions"}, set())
        if os.environ.get("NULAVIO_TEST_LANG", "pt_BR.UTF-8").startswith("pt"):
            self.assertTrue(extra, "the list for the person's language was not selected")
        self.assertEqual(state["managed"], ["adminSettings"])

    def test_02_a_cookie_notice_is_hidden_and_the_page_is_not(self):
        # uBlock Origin downloads and compiles the lists after the first start.
        hidden = harness.wait_until(lambda: self.notice()["onetrust"] is False, timeout=180, interval=1.0)
        seen = self.m.execute(BANNERS)
        self.assertTrue(hidden, f"the cookie notice still shows: {seen}")
        self.assertEqual(seen["title"], "cookie-notice")
        self.assertTrue(seen["content"], "the page's own content was hidden")
        (self.artifacts / "cookie-notice-hidden.png").write_bytes(self.m.screenshot_png())

    def test_03_a_registry_update_from_upstream_keeps_the_lists(self):
        self.lists_page()
        # Ask for uBlock Origin's registry again, as its own updater does every few days.
        self.m.execute_async(
            "const done = arguments[arguments.length - 1];"
            "vAPI.messaging.send('dashboard', {what: 'supportUpdateNow', assetKeys: ['assets.json']}).then(() => done(true));"
        )
        keys = sorted(DEFAULT_ON)

        def upstream() -> bool:
            flags = self.m.execute_async(REGISTRY, [keys])
            self.assertNotIn("error", flags)
            return all(flags[key] is True for key in keys)

        # The registry in the package says `false` for these lists; upstream's says `true` (off by default).
        self.assertTrue(harness.wait_until(upstream, timeout=120, interval=2.0), "upstream's registry did not arrive")
        self.assertTrue(set(self.state()["selected"]) >= DEFAULT_ON, "the registry update switched the lists off")

    def test_04_a_list_the_person_switches_off_stays_off(self):
        self.lists_page()
        # What the person sees in uBlock Origin's own page on a new profile: the cookie notices ticked.
        self.m.execute(
            "const entry = document.querySelector(arguments[0]);"
            "for (let node = entry; node; node = node.parentElement) node.classList?.add('expanded');"
            "entry.scrollIntoView({block: 'center'});",
            [f'.listEntry[data-key="{sorted(DEFAULT_ON)[0]}"]'],
        )
        (self.artifacts / "ublock-lists-new-profile.png").write_bytes(self.m.screenshot_png())
        for key in sorted(DEFAULT_ON):
            box = f'.listEntry[data-key="{key}"] > .detailbar input[type="checkbox"]'
            self.assertTrue(self.m.execute("return document.querySelector(arguments[0]).checked;", [box]), key)
            self.m.execute("document.querySelector(arguments[0]).click();", [box])
        self.m.execute("document.getElementById('buttonApply').click();")
        gone = harness.wait_until(lambda: not (DEFAULT_ON & set(self.state()["selected"])), timeout=30)
        self.assertTrue(gone, "uBlock Origin did not take the person's choice")
        shown = harness.wait_until(lambda: self.notice()["onetrust"] is True, timeout=120, interval=1.0)
        self.assertTrue(shown, "the notice is still hidden with the lists off: something else hides it")
        (self.artifacts / "cookie-notice-shown.png").write_bytes(self.m.screenshot_png())

        type(self).m = self.session.restart()
        back = harness.wait_until(lambda: (self.state() or {}).get("selected"), timeout=60, interval=1.0)
        self.assertTrue(back, "uBlock Origin did not start again")
        self.assertEqual(DEFAULT_ON & set(self.state()["selected"]), set(), "the policy switched the lists on again")
        self.assertEqual(self.state()["managed"], ["adminSettings"])
        self.assertTrue(self.notice()["onetrust"])


if __name__ == "__main__":
    unittest.main()
