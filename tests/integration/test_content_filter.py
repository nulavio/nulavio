"""The lists a new profile starts with in uBlock Origin (Nulavio build): cookie notices hidden by default.

`distribution/policies.json` hands uBlock Origin its own list registry with the lists of
`browser/distribution/content-filter.json` switched on (scripts/build/make_distribution.py). The test starts a
new profile as a person does, with the real signed uBlock Origin the policy installs, and checks what the
person gets: the lists are on beside uBlock Origin's own defaults, a cookie notice is hidden, an update of the
registry from uBlock Origin's servers keeps them, and a list the person switches off stays off.

It needs the network, as a first start does: the policy downloads uBlock Origin and uBlock Origin downloads
the lists. When uBlock Origin could not be installed the module is skipped and says so, or fails where the run
requires the network (NULAVIO_REQUIRE_NETWORK=1); a uBlock Origin that is installed and selected no list fails.
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
# #220 item 3: Google on another site, each as (host, path) the fixture page asks for. Analytics (GA4) loads its
# tag from Tag Manager's name; *.google-analytics.com cannot be reached over plain http (HSTS preload).
GOOGLE = {
    "Analytics": ("www.googletagmanager.com", "/gtag/js"),
    "Tag Manager": ("www.googletagmanager.com", "/gtm.js"),
    "DoubleClick": ("securepubads.g.doubleclick.net", "/tag/js/gpt.js"),
    "AdSense": ("pagead2.googlesyndication.com", "/pagead/js/adsbygoogle.js"),
}
SITE_CDN = "cdn.nulavio-site.test"

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

# In uBlock Origin's own page: keep what uBlock Origin tells its pages, on the channel its pages listen to
# (js/broadcast.js). "staticFilteringDataChanged" is its word that every list is loaded again, with the lists
# it loaded; "assetsUpdated" is the end of an update, after which it loads every list again by itself.
LISTEN = """
if (!window.nulavioHeard) {
  window.nulavioHeard = [];
  window.nulavioChannel = new BroadcastChannel("uBO");
  window.nulavioChannel.onmessage = event => window.nulavioHeard.push(
    {what: String(event.data?.what), lists: event.data?.listKeys ?? null});
}
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
        # Two things can keep the lists from being there, and only one of them is the network. uBlock Origin not
        # installed: the policy could not download it. That is a skip, unless the run says it needs the network
        # (NULAVIO_REQUIRE_NETWORK=1, which the release's integration run sets): then it fails. uBlock Origin
        # installed and running with no selection, or an empty one: the mechanism this module tests is broken,
        # and that always fails.
        if not harness.wait_until(lambda: cls.state() is not None, timeout=120, interval=1.0):
            cls.tearDownClass()
            message = "uBlock Origin was not installed by the policy in two minutes (no network?)"
            if os.environ.get("NULAVIO_REQUIRE_NETWORK") == "1":
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        if not harness.wait_until(lambda: cls.state().get("selected"), timeout=120, interval=1.0):
            state = cls.state()
            cls.tearDownClass()
            raise AssertionError(f"uBlock Origin {state['version']} is running and selected no list: {state['selected']!r}")

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()  # stops the engine and removes the temporary home (about 180 MB in /tmp, a tmpfs)
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
        self.m.execute(LISTEN)

    def heard(self) -> list[dict]:
        """What uBlock Origin told its pages since the list page was opened (the page must still be open)."""
        return self.m.execute("return window.nulavioHeard;")

    def loaded_again(self, after: str | None = None, without: frozenset[str] = frozenset()) -> bool:
        """uBlock Origin said it loaded every list again: after the message `after`, and with none of `without`."""
        heard = self.heard()
        if after is not None:
            names = [message["what"] for message in heard]
            if after not in names:
                return False
            heard = heard[names.index(after) + 1 :]
        return any(m["what"] == "staticFilteringDataChanged" and not (without & set(m["lists"] or [])) for m in heard)

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
        # uBlock Origin ends an update by loading every list again, which takes as long as the lists are large.
        # Wait for it as a person waits for the page to stop updating. It is also what makes the next test's
        # change take effect: a reload asked for while one is running joins that one (µb.loadFilterLists returns
        # the promise in flight), and the one in flight read the selection before the person changed it.
        loaded = harness.wait_until(lambda: self.loaded_again(after="assetsUpdated"), timeout=300, interval=1.0)
        self.assertTrue(loaded, f"uBlock Origin did not load its lists again after the update: {self.heard()}")
        self.assertTrue(set(self.state()["selected"]) >= DEFAULT_ON, "the registry update switched the lists off")
        self.assertFalse(self.notice()["onetrust"], "the cookie notice shows after the registry update")

    def test_02b_googles_analytics_tag_manager_and_ad_tags_on_another_site_are_blocked(self):
        """#220 item 3: on a site that is not Google's, Analytics, Tag Manager, DoubleClick and AdSense load nothing
        with a new profile's defaults (uBlock Origin's default lists and the engine's tracking protection), while the
        site's own script does. Google's names reach this machine for the test, over plain http with the HTTPS-Only
        exception a person gives, so nothing leaves it. The control: with both protections off for the site, each of
        them does reach the server, so what stops them is the blocking and nothing else. Measured on 160.0-0.4 with
        one protection at a time: uBlock Origin's lists stop Analytics and Tag Manager, the engine's tracking
        protection stops DoubleClick and AdSense."""
        # A new profile's defaults: before 04 switches lists off (tests run in name order, on one profile).
        self.assertTrue(set(self.state()["selected"]) >= DEFAULT_ON, self.state()["selected"])
        hosts = sorted({HOST, SITE_CDN, *(host for host, _ in GOOGLE.values())})
        origins = [f"http://{host}:{self.server.port}" for host in hosts if host != HOST]
        grant = (
            "Services.prefs.setStringPref('network.dns.localDomains', args[0].join(','));"
            "for (const o of args[1]) {"
            "  const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin(o);"
            "  Services.perms.addFromPrincipal(p, 'https-only-load-insecure', Ci.nsIPermissionManager.ALLOW_ACTION);"
            "}"
        )
        chrome_async(self.m, grant, [hosts, origins])
        self.addCleanup(chrome_async, self.m, "Services.prefs.setStringPref('network.dns.localDomains', args[0]);", [HOST])
        site = f"http://{HOST}:{self.server.port}"

        def load() -> dict[str, bool]:
            type(self).counter += 1
            n = self.counter
            self.m.navigate(f"{site}/google-third-party?n={n}")
            asked = lambda path: any(hit.startswith(path) and hit.endswith(f"n={n}") for hit in self.server.hits)  # noqa: E731
            harness.wait_until(lambda: asked("/assets/site.js"), timeout=10)
            return {"site": asked("/assets/site.js"), **{name: asked(path) for name, (_, path) in GOOGLE.items()}}

        # uBlock Origin compiles its lists after the first start: the first loads may come before them.
        blocked = harness.wait_until(lambda: not any(v for k, v in load().items() if k != "site"), timeout=180, interval=2.0)
        seen = load()
        self.assertTrue(blocked, f"reached the server: {[name for name in GOOGLE if seen[name]]}")
        self.assertEqual(seen, {"site": True, **dict.fromkeys(GOOGLE, False)})

        # The control: the site trusted in uBlock Origin and given the engine's tracking-protection exception.
        self.lists_page()
        trusted = self.m.execute_async(
            "const done = arguments[arguments.length - 1];"
            "vAPI.messaging.send('dashboard', {what: 'getWhitelist'}).then(r => {"
            "  const before = Array.isArray(r.whitelist) ? r.whitelist.join('\\n') : String(r.whitelist ?? '');"
            "  return vAPI.messaging.send('dashboard', {what: 'setWhitelist', whitelist: before + '\\n' + arguments[0]})"
            "    .then(() => done({before}));"
            "}).catch(e => done({error: String(e)}));",
            [HOST],
        )
        self.assertNotIn("error", trusted, trusted)
        # The engine's own exception, as the shield in the address bar gives it (kept by site, whatever the scheme).
        allow = (
            "const { ContentBlockingAllowList } = ChromeUtils.importESModule("
            "'resource://gre/modules/ContentBlockingAllowList.sys.mjs');"
            "ContentBlockingAllowList[arguments[0]](gBrowser.selectedBrowser);"
        )
        self.m.navigate(f"{site}/page/control")
        self.m.chrome(allow, ["add"])
        try:
            opened = load()
            self.assertEqual(opened, {"site": True, **dict.fromkeys(GOOGLE, True)}, "with the protections off for the site")
        finally:
            self.m.navigate(f"{site}/page/control")
            self.m.chrome(allow, ["remove"])
            self.lists_page()
            self.m.execute_async(
                "const done = arguments[arguments.length - 1];"
                "vAPI.messaging.send('dashboard', {what: 'setWhitelist', whitelist: arguments[0]})"
                ".then(() => done(true), e => done(String(e)));",
                [trusted["before"]],
            )

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
        # "Apply changes" loads every list again, and the page is busy until then. The test leaves the page only
        # after uBlock Origin said it loaded them without the ones switched off: the notice cannot show before.
        loaded = harness.wait_until(lambda: self.loaded_again(without=frozenset(DEFAULT_ON)), timeout=300, interval=1.0)
        self.assertTrue(loaded, f"uBlock Origin did not load its lists again without the ones switched off: {self.heard()}")
        shown = harness.wait_until(lambda: self.notice()["onetrust"] is True, timeout=60, interval=1.0)
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
