"""AI & Automation in the browser (S7, ADR 0007). Nulavio build only.

Settings → AI & Automation drives the AI Bridge registry through the Nulavio tools;
permission requests from a bridge appear as a page in the user's window and the
answer reaches the bridge. The registry lives in a throwaway NULAVIO_HOME shared by
the browser and this test. Captures (light and dark) go to tests/artifacts/ai-ui/.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from nulavio_launcher.ai import audit, registry


class Approve(registry.Approver):
    def __init__(self, answer=None):
        self.answer = answer
        self.asked = 0

    def ask(self, agent, capability, target):
        self.asked += 1
        return self.answer


@unittest.skipUnless(harness.nulavio_engine(), "needs the Nulavio build")
class AiUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.home = cls.session.tmp / "nulavio-home"
        cls.session.env["NULAVIO_HOME"] = str(cls.home)
        cls.patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(cls.home)})
        cls.patcher.start()
        cls.m = cls.session.start()
        cls.base = cls.m.chrome('return WebExtensionPolicy.getByID("shell@nulavio.net").getURL("");')
        cls.shots = harness.artifacts_dir() / "ai-ui"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
        finally:
            cls.patcher.stop()

    # -- helpers -------------------------------------------------------------------

    def open_page(self, page: str) -> None:
        self.m.switch_to(self.m.window_handles()[0])
        handle = self.m.send("WebDriver:NewWindow", {"type": "tab"})["handle"]
        self.m.switch_to(handle)
        self.m.navigate(self.base + page)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), timeout=30)
        )

    def click(self, selector: str) -> None:
        self.m.send("WebDriver:ElementClick", {"id": self.m.find_element(selector)})

    def js(self, script: str, *args):
        return self.m.execute(script, list(args))

    def shoot(self, name: str, section: str | None = None) -> None:
        for scheme in ("light", "dark"):
            self.js(
                "document.documentElement.dataset.theme = arguments[0];"
                "if (arguments[1]) { const keep = document.getElementById(arguments[1]);"
                "  for (const s of document.querySelectorAll('section.section')) { s.hidden = s !== keep; } }"
                "document.body.style.display = 'none'; document.body.offsetHeight; document.body.style.display = '';",
                scheme,
                section,
            )
            time.sleep(0.3)
            (self.shots / f"{name}-{scheme}.png").write_bytes(self.m.screenshot_png(full=True))
        self.js("delete document.documentElement.dataset.theme;")

    def agents(self) -> dict:
        return registry.load()["agents"]

    def tabs(self) -> list[str]:
        return self.m.chrome("return gBrowser.browsers.map(b => b.currentURI.spec);")

    def switch_to_tab(self, needle: str) -> None:
        for handle in self.m.window_handles():
            self.m.switch_to(handle)
            if needle in self.m.current_url():
                return
        raise AssertionError(f"no tab with {needle}")

    # -- tests ---------------------------------------------------------------------

    def test_01_connect_an_agent_from_settings(self):
        self.open_page("settings/settings.html#ai")
        self.assertTrue(harness.wait_until(lambda: not self.js("return document.getElementById('ai').hidden;"), timeout=20))
        self.js("document.querySelector('#ai-connect-form [name=name]').value = 'Claude UI';")
        self.click("#ai-levels input[value=assisted]")
        self.shoot("connect-form", "ai")
        self.click("#ai-connect-form button[type=submit]")
        self.assertTrue(
            harness.wait_until(lambda: not self.js("return document.getElementById('ai-connect-result').hidden;"), timeout=30)
        )
        config = json.loads(self.js("return document.getElementById('ai-config').textContent;"))
        server = config["mcpServers"]["nulavio"]
        self.assertEqual(server["args"], ["ai", "serve"])
        token = server["env"]["NULAVIO_AGENT_TOKEN"]
        agent = registry.by_token(token)
        self.assertEqual((agent["name"], agent["client"], agent["autonomy"]), ("Claude UI", "claude-code", "assisted"))
        self.assertNotIn(token, json.dumps(self.agents()))  # only the hash is stored
        self.shoot("connect-result", "ai")
        self.click("#ai-connect-again")
        self.assertEqual(self.js("return document.getElementById('ai-config').textContent;"), "")

    def test_02_full_control_needs_the_warning(self):
        self.open_page("settings/settings.html#ai")
        before = len(self.agents())
        self.js("document.querySelector('#ai-connect-form [name=name]').value = 'Total';")
        self.click("#ai-levels input[value=full_control]")
        self.click("#ai-connect-form button[type=submit]")
        self.assertTrue(harness.wait_until(lambda: self.js("return !!document.querySelector('dialog[open]');"), timeout=10))
        self.assertIn("irreversible", self.js("return document.querySelector('dialog[open]').textContent;"))
        self.shoot("full-control-warning", "ai")
        self.click("dialog[open] button[value=cancel]")
        time.sleep(1)
        self.assertEqual(len(self.agents()), before)
        self.click("#ai-connect-form button[type=submit]")
        self.assertTrue(harness.wait_until(lambda: self.js("return !!document.querySelector('dialog[open]');"), timeout=10))
        self.click("dialog[open] button[value=confirm]")
        self.assertTrue(harness.wait_until(lambda: len(self.agents()) == before + 1, timeout=20))
        total = next(a for a in self.agents().values() if a["name"] == "Total")
        self.assertEqual(total["autonomy"], "full_control")
        self.assertTrue(total["full_control_accepted"])

    def ask_in_thread(self, agent_id: str, capability: str, target: str) -> tuple[threading.Thread, dict]:
        result: dict = {}
        approver = registry.BrowserApprover(fallback=Approve(None), notice=10, timeout=60)
        thread = threading.Thread(target=lambda: result.update(answer=approver.ask(registry.get(agent_id), capability, target)))
        thread.start()
        return thread, result

    def test_03_permission_request_appears_in_the_window_and_answers_the_bridge(self):
        agent, _ = registry.add("Pesquisa", "codex", "restricted")
        for button, expected in (("#once", "once"), ("#deny", "deny")):
            thread, result = self.ask_in_thread(agent["id"], "interact", "https://docs.example.org")
            self.assertTrue(harness.wait_until(lambda: any("ai/request.html" in u for u in self.tabs()), timeout=20), self.tabs())
            self.switch_to_tab("ai/request.html")
            self.assertTrue(harness.wait_until(lambda: self.js("return document.body.dataset.state;") == "asking", timeout=20))
            self.assertIn("Pesquisa", self.js("return document.getElementById('headline').textContent;"))
            self.assertEqual(self.js("return document.getElementById('target').textContent;"), "https://docs.example.org")
            self.assertEqual(self.js("return document.activeElement.id;"), "deny")  # the safe answer is the keyboard default
            if expected == "once":
                self.shoot("permission-request")
            self.click(button)
            thread.join(30)
            self.assertEqual(result.get("answer"), expected)
            self.assertTrue(harness.wait_until(lambda: not any("ai/request.html" in u for u in self.tabs()), timeout=20))

    def test_04_pause_revoke_stop_and_permissions_from_settings(self):
        agent, _ = registry.add("Controle", "claude-code", "assisted")
        self.open_page("settings/settings.html#ai")
        row = f"[data-agent-id='{agent['id']}']"
        self.assertTrue(harness.wait_until(lambda: self.js(f'return !!document.querySelector("{row}");'), timeout=20))
        self.click(f"{row} [data-focus-key='pause-{agent['id']}']")
        self.assertTrue(harness.wait_until(lambda: registry.get(agent["id"]).get("paused"), timeout=20))
        self.js(f'document.querySelector("{row} details").open = true;')
        select = f"[data-focus-key='mode-{agent['id']}-execute_js']"
        self.js(f"const s = document.querySelector(\"{select}\"); s.value = 'allow'; s.dispatchEvent(new Event('change'));")
        self.assertTrue(
            harness.wait_until(
                lambda: registry.get(agent["id"])["grants"].get("execute_js", {}).get("mode") == "allow", timeout=20
            )
        )
        self.shoot("agent-permissions", "ai")
        self.click("#ai-stop")
        self.assertTrue(harness.wait_until(registry.stopped, timeout=20))
        self.click("#ai-stop")
        self.assertTrue(harness.wait_until(lambda: not registry.stopped(), timeout=20))
        self.js(f"[...document.querySelectorAll(\"{row} .row__end button\")].find(b => b.textContent === arguments[0]).click();",
                self.js("return browser.i18n.getMessage('aiRevoke');"))  # fmt: skip
        self.assertTrue(harness.wait_until(lambda: self.js("return !!document.querySelector('dialog[open]');"), timeout=10))
        self.click("dialog[open] button[value=confirm]")
        self.assertTrue(harness.wait_until(lambda: registry.get(agent["id"]).get("revoked"), timeout=20))

    def test_05_activity_shows_actions_not_content(self):
        agent, _ = registry.add("Historico", "other", "assisted")
        audit.record(agent=agent["id"], tool="navigate", decision="allow", outcome="ok", target="https://example.org")
        audit.record(agent=agent["id"], tool="evaluate", decision="deny", reason="preset:assisted", outcome="denied")
        self.open_page("settings/settings.html#ai")
        self.assertTrue(
            harness.wait_until(
                lambda: "evaluate" in self.js("return document.getElementById('ai-activity').textContent;"), timeout=20
            )
        )
        text = self.js("return document.getElementById('ai-activity').textContent;")
        self.assertIn("Historico · navigate", text)
        self.assertIn("https://example.org", text)

    def test_06_an_ai_workspace_never_shows_or_answers_requests(self):
        agent, _ = registry.add("Workspace", "other", "restricted")
        self.m.chrome("Services.prefs.setStringPref('nulavio.ai.workspace', arguments[0]);", [agent["id"]])
        try:
            fallback = Approve(None)
            approver = registry.BrowserApprover(fallback=fallback, notice=4, timeout=10)
            self.assertIsNone(approver.ask(registry.get(agent["id"]), "interact", None))
            self.assertEqual(fallback.asked, 1)  # nobody picked it up: the fallback was asked
            self.assertFalse(any("ai/request.html" in u for u in self.tabs()))
            # The window says who drives it.
            self.m.set_context("chrome")
            try:
                self.m.execute_async(
                    "const done = arguments[arguments.length - 1];"
                    "ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs')"
                    ".NulavioAI.markWorkspace('AI Workspace of Workspace').then(done, done);"
                )
                label = self.m.execute(
                    "const n = gNotificationBox.getNotificationWithValue('nulavio-ai-workspace');"
                    "return n ? n.messageText.textContent : null;"
                )
            finally:
                self.m.set_context("content")
            self.assertIn("AI Workspace of Workspace", label or "")
        finally:
            self.m.chrome("Services.prefs.clearUserPref('nulavio.ai.workspace');")


if __name__ == "__main__":
    unittest.main()
