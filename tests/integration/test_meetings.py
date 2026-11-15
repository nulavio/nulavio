"""Meeting links, per profile (#221): open in the service's app (the default) or join in the browser.

An app is registered for zoommtg: (it would run /bin/true; the engine only asks). By default, a meeting page that
asks for its app (a link, a script, a hidden frame) gets the engine's prompt. With "join in the browser" the
engine asks nothing and the page stays, so the service's own "join from your browser" is what the person sees.
"""

from __future__ import annotations

import http.server
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

PERSONALISE = (
    'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioPersonalise.sys.mjs").NulavioPersonalise'
)
DARK_NOW = "return matchMedia('(prefers-color-scheme: dark)').matches;"
SCHEMES = ("zoommtg", "zoomus", "msteams")
APP_LINK = "zoommtg://zoom.us/join?confno=1234567890"
# A meeting page, as the services' launch pages are: it asks for the app by itself, or on a click.
PAGE = f"""<!doctype html><meta charset=utf-8><title>meeting</title>
<a id=launch href="{APP_LINK}">Launch meeting</a><p id=join>Join from your browser</p>
<script>
const how = location.hash.slice(1);
if (how === "script") setTimeout(() => {{ location.href = "{APP_LINK}"; }}, 200);
if (how === "frame") setTimeout(() => {{ const f = document.createElement("iframe"); f.hidden = true;
  f.src = "{APP_LINK}"; document.body.append(f); }}, 200);
</script>""".encode()
REGISTER_APP = """
const handlers = Cc["@mozilla.org/uriloader/handler-service;1"].getService(Ci.nsIHandlerService);
const protocols = Cc["@mozilla.org/uriloader/external-protocol-service;1"].getService(Ci.nsIExternalProtocolService);
const info = protocols.getProtocolHandlerInfo("zoommtg");
const app = Cc["@mozilla.org/uriloader/local-handler-app;1"].createInstance(Ci.nsILocalHandlerApp);
const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
file.initWithPath("/bin/true");
app.executable = file;
app.name = "Meeting app";
info.possibleApplicationHandlers.appendElement(app);
info.preferredApplicationHandler = app;
info.preferredAction = Ci.nsIHandlerInfo.useHelperApp;
info.alwaysAskBeforeHandling = true;
handlers.store(info);
return protocols.externalProtocolHandlerExists("zoommtg");
"""
DIALOGS = """
const box = gBrowser.getTabDialogBox(gBrowser.selectedBrowser);
return box.getTabDialogManager()._dialogs.length + box.getContentDialogManager()._dialogs.length;
"""
CLOSE_DIALOGS = "gBrowser.getTabDialogBox(gBrowser.selectedBrowser).abortAllDialogs();"


class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


@unittest.skipUnless(harness.nulavio_engine(), "the meeting-link choice is the Nulavio build's Shell (NULAVIO_ENGINE)")
class MeetingLinksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.page = f"http://127.0.0.1:{cls.server.server_address[1]}/j/1234567890"
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.m = cls.session.start()
        assert cls.m.chrome(REGISTER_APP), "the stand-in app is registered for zoommtg:"

    @classmethod
    def tearDownClass(cls):
        cls.session.cleanup()
        cls.server.shutdown()

    def choose(self, value: str) -> None:
        self.m.set_context("chrome")
        try:
            self.m.execute_async(
                f"const done = arguments[arguments.length - 1]; {PERSONALISE}"
                ".set('meetingLinks', arguments[0]).then(() => done(true));",
                [value],
            )
        finally:
            self.m.set_context("content")

    def switches(self) -> dict:
        return self.m.chrome(
            "return Object.fromEntries(arguments[0].map(s => [s, 'network.protocol-handler.external.' + s])"
            ".map(([s, p]) => [s, Services.prefs.prefHasUserValue(p) ? Services.prefs.getBoolPref(p) : null]));",
            [list(SCHEMES)],
        )

    def open_meeting(self, how: str) -> int:
        """Open the meeting page, let it ask for the app, and return how many dialogs the tab shows."""
        self.m.chrome(CLOSE_DIALOGS)
        self.m.navigate("about:blank")
        self.m.navigate(f"{self.page}?{how}#{how}")
        if how == "click":
            self.m.execute("document.getElementById('launch').click();")
        harness.wait_until(lambda: self.m.chrome(DIALOGS) > 0, 3)  # the prompt, when there is one
        shown = self.m.chrome(DIALOGS)
        self.m.chrome(CLOSE_DIALOGS)
        # Whatever the engine did, the page is still the service's, with its own way to join.
        self.assertEqual(self.m.chrome("return gBrowser.selectedBrowser.currentURI.spec;"), f"{self.page}?{how}#{how}")
        self.assertEqual(self.m.execute("return document.getElementById('join')?.textContent;"), "Join from your browser")
        return shown

    def test_01_by_default_the_engine_asks_before_opening_the_app(self):
        self.assertEqual(self.m.chrome("return Services.prefs.getStringPref('nulavio.meetings.join', '');"), "")
        self.assertEqual(self.switches(), dict.fromkeys(SCHEMES))
        for how in ("click", "script", "frame"):
            with self.subTest(how=how):
                self.assertEqual(self.open_meeting(how), 1)

    def test_02_join_in_the_browser_asks_nothing_and_leaves_the_page(self):
        self.choose("browser")
        self.addCleanup(self.choose, "app")
        self.assertEqual(self.m.chrome("return Services.prefs.getStringPref('nulavio.meetings.join', '');"), "browser")
        self.assertTrue(harness.wait_until(lambda: self.switches() == dict.fromkeys(SCHEMES, False), 5), self.switches())
        for how in ("click", "script", "frame"):
            with self.subTest(how=how):
                self.assertEqual(self.open_meeting(how), 0)
        self.choose("app")
        self.assertTrue(harness.wait_until(lambda: self.switches() == dict.fromkeys(SCHEMES), 5), self.switches())
        self.assertEqual(self.open_meeting("click"), 1)

    def test_04_a_switch_the_person_set_survives_a_start_with_the_default(self):
        # Review of #343: a start with "app" leaves the person's own false alone; only a change of choice clears.
        meetings = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioMeetings.sys.mjs").NulavioMeetings'
        pref = "network.protocol-handler.external.zoommtg"
        self.addCleanup(self.m.chrome, f"Services.prefs.clearUserPref('{pref}');")
        self.m.chrome(f"Services.prefs.setBoolPref('{pref}', false); {meetings}.unwatch(); {meetings}.watch();")
        self.assertEqual(self.switches()["zoommtg"], False)

    def test_03_settings_offers_the_choice_in_integrations(self):
        self.m.navigate("about:preferences#nulavioIntegrations")
        group = (
            "const radio = document.querySelector('[data-option=\"meetingLinks\"]');"
            "return radio ? { shown: radio.checkVisibility(), label: radio.label, value: radio.value,"
            "  options: [...radio.querySelectorAll('moz-radio')].map(o => [o.value, o.label]) } : null;"
        )
        self.assertTrue(harness.wait_until(lambda: (self.m.execute(group) or {}).get("shown"), 15), self.m.execute(group))
        state = self.m.execute(group)
        print(f"settings: {state}", file=sys.stderr)
        self.assertEqual([value for value, _ in state["options"]], ["app", "browser"])
        self.assertTrue(all(label.strip() for _, label in state["options"]), state)
        self.assertEqual(state["value"], "app")
        # For the review: the group in the light and the dark theme (NULAVIO_TEST_ARTIFACTS).
        folder = harness.artifacts_dir() / "meetings"
        folder.mkdir(parents=True, exist_ok=True)
        self.m.execute("document.querySelector('[data-option=\"meetingLinks\"]').scrollIntoView({block: 'center'});")
        try:
            for dark in (0, 1):
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
                harness.wait_until(lambda want=bool(dark): self.m.execute(DARK_NOW) == want, 10)
                (folder / f"settings-{'dark' if dark else 'light'}.png").write_bytes(self.m.screenshot_png())
        finally:
            self.m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")


if __name__ == "__main__":
    unittest.main()
