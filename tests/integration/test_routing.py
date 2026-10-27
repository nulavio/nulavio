"""Smart Profile Routing, M4a (docs/adr/0003-nulavio-profiles-and-routing.md). Nulavio build only.

Decisions are checked on the engine (Public Suffix List, IDN, URL parsing are
the engine's). Links "from another app" are delivered the way the desktop
delivers them: a command line sent through the engine's remote service to the
instance that receives links (here the "Trabalho" profile), over the private
D-Bus bus of harness.GeckoProfileSession. The fixture server counts requests,
and each instance is asked which tabs it has, so the tests show where a link
was loaded and that the wrong profile never requested it.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from marionette import MarionetteError

SHELL = "resource://builtin-addons/nulavio-shell/modules"
# Trusted key events into the address bar, as Firefox's own tests type (see test_search.py).
TYPE_JS = """
const [text] = arguments;
gURLBar.focus();
gURLBar.select();
const tip = Cc["@mozilla.org/text-input-processor;1"].createInstance(Ci.nsITextInputProcessor);
if (!tip.beginInputTransactionForTests(window)) {
  throw new Error("could not start an input transaction");
}
for (const ch of text) {
  const event = ch === "\\n"
    ? new KeyboardEvent("", {key: "Enter", code: "Enter", keyCode: 13})
    : new KeyboardEvent("", {key: ch});
  tip.keydown(event);
  tip.keyup(event);
}
"""
PRELUDE = (
    f'const R = ChromeUtils.importESModule("{SHELL}/NulavioRouting.sys.mjs").NulavioRouting;'
    f'const D = ChromeUtils.importESModule("{SHELL}/NulavioRouter.sys.mjs");'
    f'const P = ChromeUtils.importESModule("{SHELL}/NulavioProfiles.sys.mjs").NulavioProfiles;'
    'const SPS = ChromeUtils.importESModule("resource:///modules/profiles/SelectableProfileService.sys.mjs")'
    ".SelectableProfileService;"
)


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        f"(async () => {{ {PRELUDE} {body} }})().then(v => done({{ok: v ?? null}}), e => done({{error: e?.code ?? String(e)}}));"
    )
    m.set_context("chrome")
    try:
        return m.execute_async(script, list(args))
    finally:
        m.set_context("content")


@unittest.skipUnless(harness.nulavio_engine(), "Smart Profile Routing needs the Nulavio build (NULAVIO_ENGINE)")
class RoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        cls.others: dict[str, harness.Marionette] = {}
        ids = {}
        for template, name in (("work", "Trabalho"), ("banking", "Bancos")):
            ids[name] = cls.call(f"return P.create({{templateId: '{template}', name: '{name}'}});")
        cls.ids = ids
        cls.ids["Pessoal"] = cls.call("return (await P.current()).id;")
        cls.paths = {name: Path(cls.call("return (await SPS.getProfile(args[0])).path;", pid)) for name, pid in ids.items()}
        for name in ("Trabalho", "Bancos"):
            harness.GeckoProfileSession.enable_marionette(cls.paths[name])

    @classmethod
    def tearDownClass(cls):
        try:
            for client in cls.others.values():
                try:
                    client.quit()
                except (OSError, ConnectionError, MarionetteError):
                    pass
            cls.session.cleanup()
        finally:
            cls.server.__exit__(None, None, None)

    # -- helpers -----------------------------------------------------------

    @classmethod
    def call(cls, body: str, *args):
        result = chrome_async(cls.m, body, args)
        if "error" in result:
            raise AssertionError(f"routing call failed: {result['error']}")
        return result["ok"]

    def error_of(self, body: str, *args):
        return chrome_async(self.m, body, args).get("error")

    def local(self, path: str) -> str:
        return f"http://localhost:{self.server.port}{path}"

    def instance(self, name: str) -> harness.Marionette:
        """Connect to a profile's instance (started by the browser), once it runs."""
        path = self.paths[name]
        self.assertTrue(harness.wait_until(lambda: self.session.processes_for(path), timeout=60), f"{name} did not start")
        if name not in self.others:
            self.others[name] = harness.GeckoProfileSession.connect(path, timeout=90)
        return self.others[name]

    def start(self, name: str) -> harness.Marionette:
        self.call("return P.switchTo(args[0]);", self.ids[name])
        client = self.instance(name)
        time.sleep(1.5)  # let its profile service load the group's rules
        return client

    def stop(self, name: str) -> None:
        client = self.others.pop(name)
        client.quit()
        path = self.paths[name]
        self.assertTrue(harness.wait_until(lambda: not self.session.processes_for(path), timeout=30))
        (path / "MarionetteActivePort").unlink(missing_ok=True)

    def deliver(self, receiver: str, args: list[str]) -> None:
        """What an external app's link does: a command line for the running instance."""
        self.call(
            "Cc['@mozilla.org/remote;1'].getService(Ci.nsIRemoteService).sendCommandLine(args[0], args[1], false);",
            str(self.paths[receiver]),
            args,
        )

    def tabs(self, client) -> list[str]:
        urls = []
        for handle in client.window_handles():
            client.switch_to(handle)
            try:
                urls.append(client.current_url())
            except MarionetteError:
                urls.append("")
        return urls

    def own_tabs(self) -> list[str]:
        return self.m.chrome("return gBrowser.browsers.map(b => b.currentURI.spec);")

    def hits(self, path: str) -> int:
        return len(self.server.requests_to(path))

    # -- the decision engine (pure, on the engine's PSL and IDN) -------------

    def test_01_decisions(self):
        cases = self.call(
            """
            const rules = D.parseRules(JSON.stringify([
              {id: "h1", match: "host", value: "mail.example.com", action: "open-in", profileId: 2},
              {id: "d1", match: "domain", value: "example.com", action: "open-in", profileId: 3},
              {id: "s1", match: "host", value: "public.example.com", action: "stay"},
              {id: "i1", match: "domain", value: "xn--bcher-kva.example", action: "ask", profileId: 2},
              {id: "u1", match: "domain", value: "bbc.co.uk", action: "open-in", profileId: 2},
              {id: "ip", match: "host", value: "127.0.0.1", action: "open-in", profileId: 3},
              {id: "bad", match: "host", value: "UPPER.example.com", action: "open-in", profileId: 2},
              {id: "bad2", match: "domain", value: "x.org", action: "open-in"},
            ]));
            const d = (url, extra = {}) => {
              const r = D.decide({url, rules, ...extra});
              return [r.action, r.profileId, r.reason];
            };
            return {
              count: rules.length,
              host: d("https://mail.example.com/inbox"),
              domain: d("https://www.example.com/a?b"),
              caseAndDot: d("HTTPS://WWW.EXAMPLE.COM./x"),
              stayRule: d("https://public.example.com/"),
              idn: d("http://bücher.example/"),
              psl: d("https://news.bbc.co.uk/"),
              suffixOnly: d("https://co.uk/"),
              ip: d("http://127.0.0.1:8080/x"),
              otherIp: d("http://127.0.0.2/"),
              lookalike: d("https://example.com.evil.net/"),
              lookalike2: d("https://evilexample.com/"),
              userinfo: d("https://www.example.com@evil.net/"),
              javascript: d("javascript:alert(1)"),
              data: d("data:text/html,hi"),
              file: d("file:///etc/passwd"),
              about: d("about:config"),
              privateWin: d("https://www.example.com/", {isPrivate: true}),
              disabled: d("https://www.example.com/", {enabled: false}),
              explicit: d("https://mail.example.com/", {explicitProfileId: 3, currentProfileId: 1}),
              explicitHere: d("https://mail.example.com/", {explicitProfileId: 1, currentProfileId: 1}),
              alreadyHere: d("https://www.example.com/", {currentProfileId: 3}),
              garbage: d("not a url"),
            };
            """
        )
        self.assertEqual(cases.pop("count"), 6, "malformed stored rules must be dropped")
        expected = {
            "host": ["open-in", 2, "host"],
            "domain": ["open-in", 3, "domain"],
            "caseAndDot": ["open-in", 3, "domain"],
            "stayRule": ["stay", None, "rule"],
            "idn": ["ask", 2, "domain"],
            "psl": ["open-in", 2, "domain"],
            "suffixOnly": ["stay", None, "no-rule"],
            "ip": ["open-in", 3, "host"],
            "otherIp": ["stay", None, "no-rule"],
            "lookalike": ["stay", None, "no-rule"],
            "lookalike2": ["stay", None, "no-rule"],
            "userinfo": ["stay", None, "no-rule"],
            "javascript": ["stay", None, "scheme"],
            "data": ["stay", None, "scheme"],
            "file": ["stay", None, "scheme"],
            "about": ["stay", None, "scheme"],
            "privateWin": ["stay", None, "private"],
            "disabled": ["stay", None, "disabled"],
            "explicit": ["open-in", 3, "explicit"],
            "explicitHere": ["stay", None, "explicit"],
            "alreadyHere": ["stay", None, "already-here"],
            "garbage": ["stay", None, "invalid-url"],
        }
        for name, want in expected.items():
            with self.subTest(case=name):
                self.assertEqual(cases[name], want)

    def test_02_rule_validation_and_command_lines(self):
        result = self.call(
            """
            const v = input => { try { return D.validateRule(input); } catch (e) { return e.code; } };
            const p = a => { const r = D.parseCommandLine(a); return r.supported ? r.items.map(i => i.value) : null; };
            return {
              host: v({site: "https://Mail.Example.com/path?q", match: "host", action: "open-in", profileId: 2}),
              domainFromSub: v({site: "a.b.Bücher.example", match: "domain", action: "ask", profileId: 2}),
              suffix: v({site: "co.uk", match: "domain", action: "open-in", profileId: 2}),
              localhost: v({site: "localhost", match: "domain", action: "open-in", profileId: 2}),
              ipDomain: v({site: "127.0.0.1", match: "domain", action: "open-in", profileId: 2}),
              noProfile: v({site: "example.com", match: "domain", action: "open-in"}),
              badMatch: v({site: "example.com", match: "regex", action: "stay"}),
              script: v({site: "javascript:alert(1)", match: "host", action: "stay"}),
              spaces: v({site: "exa mple.com", match: "host", action: "stay"}),
              stay: v({site: "public.example.com", match: "host", action: "stay", profileId: 5}),
              bare: p(["https://a.example/"]),
              flags: p(["-new-tab", "https://a.example/", "--url", "https://b.example/", "-new-window", "c.example"]),
              privateWin: p(["-private-window", "https://a.example/"]),
              search: p(["-search", "words"]),
              missing: p(["-new-tab"]),
              flagAsValue: p(["-url", "-private-window"]),
            };
            """
        )
        self.assertEqual(result["host"], {"match": "host", "value": "mail.example.com", "action": "open-in", "profileId": 2})
        self.assertEqual(result["domainFromSub"]["value"], "xn--bcher-kva.example")
        for key in ("suffix", "localhost", "ipDomain"):
            self.assertEqual(result[key], "no-domain", key)
        self.assertEqual(result["noProfile"], "invalid-profile")
        self.assertEqual(result["badMatch"], "invalid-match")
        self.assertEqual(result["script"], "invalid-site")
        self.assertEqual(result["spaces"], "invalid-site")
        self.assertIsNone(result["stay"]["profileId"])
        self.assertEqual(result["bare"], ["https://a.example/"])
        self.assertEqual(result["flags"], ["https://a.example/", "https://b.example/", "c.example"])
        for key in ("privateWin", "search", "missing", "flagAsValue"):
            self.assertIsNone(result[key], f"{key} must leave the command line alone")

    # -- rules ---------------------------------------------------------------

    def test_03_rules_are_validated_shared_and_replaceable(self):
        bank = self.ids["Bancos"]
        first = self.call("return R.addRule({site: 'localhost', match: 'host', action: 'open-in', profileId: args[0]});", bank)
        again = self.call("return R.addRule({site: 'LOCALHOST.', match: 'host', action: 'open-in', profileId: args[0]});", bank)
        state = self.call("return R.state();")
        self.assertEqual([r["id"] for r in state["rules"]], [again], "a second rule for the same site replaces the first")
        self.assertNotEqual(first, again)
        self.assertEqual(state["rules"][0]["profileName"], "Bancos")
        self.assertEqual(
            self.error_of("return R.addRule({site: 'x.org', match: 'domain', action: 'open-in', profileId: 999});"),
            "invalid-profile",
        )
        shared = json.loads(self.call("return SPS.getDBPref('nulavio.routing.rules');"))
        self.assertEqual([r["id"] for r in shared], [again], "rules are not in the group store")
        rule_for = self.call("return R.ruleFor(args[0]);", self.local("/page/x"))
        self.assertEqual(rule_for["rule"]["id"], again)
        type(self).bank_rule = again

    # -- links from other apps ---------------------------------------------------

    def test_04_link_opens_in_the_rule_profile_and_nowhere_else(self):
        work = self.start("Trabalho")  # the instance that receives links from other apps
        self.deliver("Trabalho", [self.local("/page/routed-1")])
        bank = self.instance("Bancos")
        self.assertTrue(harness.wait_until(lambda: self.hits("/page/routed-1"), timeout=30))
        time.sleep(1)
        self.assertEqual(self.hits("/page/routed-1"), 1, "the link was requested more than once")
        self.assertTrue(any(u.endswith("/page/routed-1") for u in self.tabs(bank)), "not open in Bancos")
        self.assertFalse(any("/page/routed-1" in u for u in self.tabs(work)), "it was opened in Trabalho too")

        # The target already runs: the next link reaches it, no second instance.
        before = self.session.processes_for(self.paths["Bancos"])
        self.deliver("Trabalho", [self.local("/page/routed-2")])
        self.assertTrue(harness.wait_until(lambda: self.hits("/page/routed-2"), timeout=30))
        self.assertEqual(self.session.processes_for(self.paths["Bancos"]), before)
        self.assertTrue(harness.wait_until(lambda: any(u.endswith("/page/routed-2") for u in self.tabs(bank)), timeout=10))

    def test_05_ask_first_loads_nothing_until_the_user_chooses(self):
        self.call("await R.setRuleAction(args[0], 'ask');", self.bank_rule)
        time.sleep(1.5)
        work = self.others["Trabalho"]
        self.deliver("Trabalho", [self.local("/page/asked")])
        ask = harness.wait_until(lambda: [u for u in self.tabs(work) if "/routing/ask.html" in u], timeout=20)
        self.assertTrue(ask, "no question was shown")
        time.sleep(1)
        self.assertEqual(self.hits("/page/asked"), 0, "the site was loaded before the user chose")
        # The user chooses Bancos on the question page.
        for handle in work.window_handles():
            work.switch_to(handle)
            if "/routing/ask.html" in work.current_url():
                break
        harness.wait_until(lambda: work.execute("return document.documentElement.dataset.ready === 'true';"), timeout=10)
        self.assertIn("/page/asked", work.execute("return document.getElementById('url').textContent;"))
        work.send("WebDriver:ElementClick", {"id": work.find_element("#actions .button--primary")})
        self.assertTrue(harness.wait_until(lambda: self.hits("/page/asked"), timeout=30))
        self.assertTrue(
            harness.wait_until(lambda: any(u.endswith("/page/asked") for u in self.tabs(self.others["Bancos"])), timeout=10)
        )
        self.assertFalse(any("/page/asked" in u and "routing" not in u for u in self.tabs(work)))
        self.call("await R.setRuleAction(args[0], 'open-in');", self.bank_rule)

    def test_06_explicit_and_unsupported_command_lines_are_not_routed(self):
        time.sleep(1.5)
        work = self.others["Trabalho"]
        # Sent by routing or by an explicit choice: never routed again (no loops).
        self.deliver("Trabalho", ["--nulavio-routed", "-new-tab", self.local("/page/explicit")])
        self.assertTrue(harness.wait_until(lambda: any(u.endswith("/page/explicit") for u in self.tabs(work)), timeout=20))
        # Private windows are never moved to another profile.
        self.deliver("Trabalho", ["-private-window", self.local("/page/private")])
        self.assertTrue(harness.wait_until(lambda: self.hits("/page/private"), timeout=20))
        self.assertFalse(any(u.endswith("/page/private") for u in self.tabs(self.others["Bancos"])))

    def test_07_routing_off_opens_links_where_they_arrive(self):
        self.call("await R.setEnabled(false);")
        try:
            time.sleep(1.5)
            work = self.others["Trabalho"]
            self.deliver("Trabalho", [self.local("/page/disabled")])
            self.assertTrue(harness.wait_until(lambda: any(u.endswith("/page/disabled") for u in self.tabs(work)), timeout=20))
            self.assertFalse(any(u.endswith("/page/disabled") for u in self.tabs(self.others["Bancos"])))
        finally:
            self.call("await R.setEnabled(true);")

    def test_08_a_missing_profile_never_falls_back_silently(self):
        self.stop("Bancos")
        self.call("await P.remove(args[0]);", self.ids["Bancos"])
        state = self.call("return R.state();")
        self.assertTrue(state["rules"][0]["missing"])
        time.sleep(1.5)
        work = self.others["Trabalho"]
        self.deliver("Trabalho", [self.local("/page/orphan")])
        blocked = harness.wait_until(lambda: [u for u in self.tabs(work) if "/routing/blocked.html" in u], timeout=20)
        self.assertTrue(blocked, "no explanation was shown")
        time.sleep(1)
        self.assertEqual(self.hits("/page/orphan"), 0, "the link opened in the wrong profile")
        for handle in work.window_handles():
            work.switch_to(handle)
            if "/routing/blocked.html" in work.current_url():
                break
        harness.wait_until(lambda: work.execute("return document.documentElement.dataset.ready === 'true';"), timeout=10)
        # Opening it here is the user's explicit choice.
        work.send("WebDriver:ElementClick", {"id": work.find_element("#actions .button--secondary")})
        self.assertTrue(harness.wait_until(lambda: self.hits("/page/orphan"), timeout=20))
        self.assertTrue(harness.wait_until(lambda: any(u.endswith("/page/orphan") for u in self.tabs(work)), timeout=10))

    def test_09_a_link_that_starts_the_browser_waits_for_the_rules(self):
        """Cold start: the receiving profile is not running; the link arrives with it."""
        self.stop("Trabalho")
        self.call(
            "return R.addRule({site: '127.0.0.1', match: 'host', action: 'open-in', profileId: args[0]});",
            self.ids["Pessoal"],
        )
        url = self.server.url("/page/cold-start")
        self.call("SPS.execProcess(['--profile', args[0], args[1]]);", str(self.paths["Trabalho"]), url)
        work = self.instance("Trabalho")
        self.assertTrue(harness.wait_until(lambda: self.hits("/page/cold-start"), timeout=40))
        time.sleep(1)
        self.assertEqual(self.hits("/page/cold-start"), 1)
        self.assertTrue(harness.wait_until(lambda: any(u.endswith("/page/cold-start") for u in self.own_tabs()), timeout=10))
        self.assertFalse(any("/page/cold-start" in u for u in self.tabs(work)), "the cold-started profile loaded it")

    def test_10_rules_editor(self):
        url = self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('settings/settings.html#routing');")
        self.m.navigate(url)
        harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), timeout=15)

        def rows():
            return self.m.execute("return [...document.querySelectorAll('#rules > li[data-rule-id]')].map(li => li.textContent);")

        self.assertTrue(harness.wait_until(lambda: len(rows()) == 2, timeout=10), rows())
        self.assertTrue(any("⚠" in r for r in rows()), "a rule whose profile is gone must say so")
        self.m.execute(
            "const f = document.getElementById('add-rule'); f.elements.site.value = 'https://Wiki.Example.org/x';"
            "f.elements.match.value = 'domain'; f.elements.action.value = 'ask';"
        )
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#add-rule button[type=submit]")})
        self.assertTrue(harness.wait_until(lambda: any("example.org" in r for r in rows()), timeout=10), rows())
        rule = next(r for r in self.call("return (await R.state()).rules;") if r["value"] == "example.org")
        self.assertEqual((rule["match"], rule["action"]), ("domain", "ask"))
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(f'[data-focus-key="rule-remove-{rule["id"]}"]')})
        self.assertTrue(harness.wait_until(lambda: not any("example.org" in r for r in rows()), timeout=10))

    # -- M4b: addresses typed in the address bar, and the link menu -----------

    def type_address(self, url: str) -> None:
        self.m.chrome("if (window.gDialogBox?.isOpen) { window.gDialogBox.dialog?.close(); }")
        self.m.chrome(TYPE_JS, [url])
        time.sleep(0.3)
        self.m.chrome(TYPE_JS.replace("gURLBar.select();", ""), ["\n"])

    def selected_url(self) -> str:
        return self.m.chrome("return gBrowser.selectedBrowser.currentURI.spec;")

    def test_11_typed_address_opens_in_the_rule_profile(self):
        rule = self.call(
            "return R.addRule({site: '127.0.0.1', match: 'host', action: 'open-in', profileId: args[0]});",
            self.ids["Trabalho"],
        )
        type(self).typed_rule = rule
        work = self.others["Trabalho"]
        self.m.navigate("about:blank")
        before = self.selected_url()
        url = self.server.url("/page/typed")
        self.type_address(url)
        self.assertTrue(harness.wait_until(lambda: self.hits("/page/typed"), timeout=30), "nothing was opened")
        self.assertTrue(harness.wait_until(lambda: any(u.endswith("/page/typed") for u in self.tabs(work)), timeout=10))
        time.sleep(1)
        self.assertEqual(self.hits("/page/typed"), 1)
        self.assertEqual(self.selected_url(), before, "this tab navigated away")
        self.assertFalse(any("/page/typed" in u for u in self.own_tabs()), "it was loaded here too")
        self.assertNotIn("/page/typed", self.m.chrome("return gURLBar.value;"), "the address bar kept the routed address")

    def test_12_typed_address_can_ask_first(self):
        self.call("await R.setRuleAction(args[0], 'ask');", self.typed_rule)
        try:
            self.m.navigate("about:blank")
            self.type_address(self.server.url("/page/typed-ask"))
            ask = harness.wait_until(lambda: [u for u in self.own_tabs() if "/routing/ask.html" in u], timeout=20)
            self.assertTrue(ask, "no question was shown")
            time.sleep(1)
            self.assertEqual(self.hits("/page/typed-ask"), 0, "the site was loaded before the user chose")
            for handle in self.m.window_handles():
                self.m.switch_to(handle)
                if "/routing/ask.html" in self.m.current_url():
                    break
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), timeout=10)
            self.assertIn("127.0.0.1", self.m.execute("return document.getElementById('explain').textContent;"))
            # "Open in this profile" is the user's explicit choice: it loads here.
            self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#actions .button--secondary")})
            self.assertTrue(harness.wait_until(lambda: self.hits("/page/typed-ask"), timeout=20))
            self.assertTrue(harness.wait_until(lambda: any(u.endswith("/page/typed-ask") for u in self.own_tabs()), timeout=10))
        finally:
            self.call("await R.setRuleAction(args[0], 'open-in');", self.typed_rule)

    def test_13_never_routed_typed_navigations(self):
        url = self.server.url("/page/never")
        cases = self.call(
            """
            const url = args[0];
            return {
              privateWindow: R.routeNavigation({url, isPrivate: true}),
              post: R.routeNavigation({url, postData: "q=1"}),
              download: R.routeNavigation({url, where: "save"}),
              internal: R.routeNavigation({url: "about:preferences"}),
              script: R.routeNavigation({url: "javascript:void(0)"}),
            };
            """,
            url,
        )
        self.assertEqual(cases, dict.fromkeys(cases, False))
        time.sleep(1)
        self.assertEqual(self.hits("/page/never"), 0)

    def test_14_link_menu_opens_the_link_in_the_chosen_profile(self):
        work = self.others["Trabalho"]
        self.m.navigate(self.server.url("/links"))
        link = self.m.find_element("#go")
        menu_item = 'document.querySelector("[id$=\\"nulavio-open-link-in\\"]")'
        self.m.send(
            "WebDriver:PerformActions",
            {
                "actions": [
                    {
                        "type": "pointer",
                        "id": "mouse",
                        "parameters": {"pointerType": "mouse"},
                        "actions": [
                            {
                                "type": "pointerMove",
                                "origin": {"element-6066-11e4-a52e-4f735466cecf": link},
                                "x": 0,
                                "y": 0,
                            },
                            {"type": "pointerDown", "button": 2},
                            {"type": "pointerUp", "button": 2},
                        ],
                    }
                ]
            },
        )
        self.m.send("WebDriver:ReleaseActions")
        shown = harness.wait_until(
            lambda: self.m.chrome(
                "const m = document.getElementById('contentAreaContextMenu');"
                f"const item = {menu_item};"
                "return m.state === 'open' && item && !item.hidden ? item.getAttribute('label') : null;"
            ),
            timeout=10,
        )
        self.assertTrue(shown, "the link menu has no 'Open link in profile' item")
        target = self.m.chrome(
            f"const item = {menu_item};"
            "const choice = [...item.querySelectorAll('menuitem')].find(i => i.getAttribute('label') === arguments[0]);"
            "if (!choice) { return [...item.querySelectorAll('menuitem')].map(i => i.getAttribute('label')); }"
            "choice.click(); document.getElementById('contentAreaContextMenu').hidePopup(); return 'clicked';",
            ["Trabalho"],
        )
        self.assertEqual(target, "clicked")
        self.assertTrue(harness.wait_until(lambda: self.hits("/page/from-menu"), timeout=30), "nothing was opened")
        self.assertTrue(harness.wait_until(lambda: any(u.endswith("/page/from-menu") for u in self.tabs(work)), timeout=10))
        time.sleep(1)
        self.assertEqual(self.hits("/page/from-menu"), 1)
        self.assertFalse(any("/page/from-menu" in u for u in self.own_tabs()))

    # -- M5: links clicked in pages (docs/security/routing-m5-review.md) -------

    def m5_setup(self) -> None:
        """Rule: 127.0.0.1 opens in Trabalho. The fixture page is served from localhost, another site."""
        if "Trabalho" not in self.others:
            self.start("Trabalho")
        type(self).m5_rule = self.call(
            "return R.addRule({site: '127.0.0.1', match: 'host', action: 'open-in', profileId: args[0]});",
            self.ids["Trabalho"],
        )

    def open_m5(self, origin: str = "localhost") -> None:
        self.m.navigate(f"http://{origin}:{self.server.port}/m5")

    def click(self, selector: str, frame: str | None = None) -> None:
        """A real click (trusted input, so the page gets a user gesture)."""
        if frame:
            self.m.send("WebDriver:SwitchToFrame", {"element": self.m.find_element(frame)})
        try:
            self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(selector)})
        finally:
            if frame:
                self.m.send("WebDriver:SwitchToParentFrame")

    def routed_only(self, name: str) -> None:
        """Requested once, by Trabalho; never loaded here."""
        path, work = f"/page/{name}", self.others["Trabalho"]
        self.assertTrue(harness.wait_until(lambda: self.hits(path), timeout=30), f"{name}: nothing was opened")
        self.assertTrue(
            harness.wait_until(lambda: any(u.endswith(path) for u in self.tabs(work)), timeout=10), f"{name}: not in Trabalho"
        )
        time.sleep(1)
        self.assertEqual(self.hits(path), 1, f"{name}: requested more than once")
        self.assertFalse(any(path in u for u in self.own_tabs()), f"{name}: also loaded here")

    def stayed_here(self, name: str) -> None:
        """Requested here, as in any browser; Trabalho never got it."""
        path = f"/page/{name}"
        self.assertTrue(harness.wait_until(lambda: self.hits(path), timeout=20), f"{name}: never loaded")
        time.sleep(1)
        self.assertFalse(any(path in u for u in self.tabs(self.others["Trabalho"])), f"{name}: routed")

    def test_15_in_page_routing_is_off_by_default(self):
        self.m5_setup()
        self.assertFalse(self.call("return (await R.state()).inPage;"))
        self.open_m5()
        self.m.execute("document.getElementById('link').href += '-default';")
        self.click("#link")
        self.stayed_here("m5-link-default")

    def test_16_a_clicked_link_opens_in_the_rule_profile_and_the_page_stays(self):
        self.m5_setup()
        self.call("await R.setInPage(true);")
        self.open_m5()
        self.click("#link")
        self.routed_only("m5-link")
        self.assertTrue(self.selected_url().endswith("/m5"), "the page the user was on did not stay")

    def test_17_a_new_tab_link_is_routed_and_its_empty_tab_closes(self):
        self.open_m5()
        tabs_before = len(self.own_tabs())
        self.click("#blank")
        self.routed_only("m5-blank")
        self.assertTrue(harness.wait_until(lambda: len(self.own_tabs()) == tabs_before, timeout=10), self.own_tabs())

    def test_18_navigations_that_are_never_routed_load_here(self):
        port = self.server.port
        hop = f"http://nulavio-hop.test:{port}"
        chrome_async(
            self.m,
            "Services.prefs.setStringPref('network.dns.localDomains', 'nulavio-hop.test');"
            "const p = Services.scriptSecurityManager.createContentPrincipalFromOrigin(args[0]);"
            "Services.perms.addFromPrincipal(p, 'https-only-load-insecure', Ci.nsIPermissionManager.ALLOW_ACTION);",
            [hop],
        )
        cases = [
            ("no gesture", None, None, "m5-script"),
            ("GET form", "#fgetb", None, "m5-form-get"),
            ("POST form", "#fpostb", None, "m5-form-post"),
            ("pop-up with an opener", "#popup", None, "m5-popup"),
            ("redirect onto a routed site", "#redirect", None, "m5-redirect"),
            ("link inside a frame", "#in", "#frame", "m5-frame-in"),
            ("frame navigating the page", "#top", "#frame", "m5-frame-top"),
        ]
        for label, selector, frame, name in cases:
            with self.subTest(label):
                self.open_m5()
                if selector is None:
                    self.m.execute("location.href = arguments[0];", [self.server.url(f"/page/{name}")])
                else:
                    self.click(selector, frame)
                self.stayed_here(name)
        with self.subTest("same site"):
            self.open_m5("127.0.0.1")
            self.click("#same")
            self.stayed_here("m5-same")

    def test_19_one_click_moves_one_navigation(self):
        self.open_m5()
        self.click("#twice")  # navigates, then navigates again 0.3 s later within the same gesture
        self.routed_only("m5-twice-1")
        self.stayed_here("m5-twice-2")

    def test_20_private_windows_never_route(self):
        handles = set(self.m.window_handles())
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, timeout=20))
        private = (set(self.m.window_handles()) - handles).pop()
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.m.switch_to(private)
        # Let the new window finish its own first page before navigating it.
        harness.wait_until(lambda: self.m.current_url() == "about:privatebrowsing", timeout=20)
        time.sleep(1)
        try:
            self.open_m5()
            self.m.execute("document.getElementById('link').href += '-private';")
            self.click("#link")
            self.stayed_here("m5-link-private")
        finally:
            self.m.switch_to(private)
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)

    def test_21_an_ask_rule_asks_and_loads_nothing(self):
        self.call("await R.setRuleAction(args[0], 'ask');", self.m5_rule)
        try:
            self.open_m5()
            before = self.hits("/page/m5-link")
            self.click("#link")
            ask = harness.wait_until(lambda: [u for u in self.own_tabs() if "/routing/ask.html" in u], timeout=20)
            self.assertTrue(ask, "no question was shown")
            self.assertIn("src=page", ask[0])
            time.sleep(1)
            self.assertEqual(self.hits("/page/m5-link"), before, "the site was loaded before the user chose")
            self.assertTrue(self.selected_url().endswith("/m5") or "/routing/ask.html" in self.selected_url())
        finally:
            self.call("await R.setRuleAction(args[0], 'open-in');", self.m5_rule)

    def test_22_settings_switch(self):
        url = self.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('settings/settings.html#routing');")
        self.m.navigate(url)
        harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), timeout=15)
        checked = "return document.getElementById('routing-in-page').checked;"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(checked), timeout=10))
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element("#routing-in-page")})
        self.assertTrue(harness.wait_until(lambda: not self.call("return (await R.state()).inPage;"), timeout=10))
        hint = self.m.execute("return document.getElementById('routing-in-page-hint').textContent;")
        self.assertIn("pop-up", hint.lower())
        # With it off, the request observer is gone: a clicked link loads here again.
        self.open_m5()
        self.m.execute("document.getElementById('link').href += '-off';")
        self.click("#link")
        self.stayed_here("m5-link-off")


if __name__ == "__main__":
    unittest.main()
