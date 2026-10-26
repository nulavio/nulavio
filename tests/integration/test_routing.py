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


if __name__ == "__main__":
    unittest.main()
