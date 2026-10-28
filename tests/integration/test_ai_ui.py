"""AI & Automation in the browser (S7, ADR 0007). Nulavio build only.

Settings → AI & Automation drives the AI Bridge registry through the Nulavio tools;
permission requests from a bridge appear as a page in the user's window and the
answer reaches the bridge. The registry lives in a throwaway NULAVIO_HOME shared by
the browser and this test. Captures (light and dark) go to tests/artifacts/ai-ui/.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from nulavio_launcher.ai import audit, policy, registry


class Approve(registry.Approver):
    def __init__(self, answer=None):
        self.answer = answer
        self.asked = 0

    def ask(self, agent, capability, target, place=""):
        self.asked += 1
        return self.answer


@unittest.skipUnless(harness.nulavio_engine(), "needs the Nulavio build")
class AiUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        cls.home = cls.session.tmp / "nulavio-home"
        cls.session.env["NULAVIO_HOME"] = str(cls.home)
        # The agents' own CLIs (if installed) run with this throwaway HOME: they write only there.
        local_bin = Path(os.environ.get("HOME", "/")) / ".local" / "bin"
        cls.session.env["PATH"] = f"{local_bin}:/usr/bin:/bin"
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

    def msg(self, key: str, *subs: str) -> str:
        """The Shell's own text, in the page's language (pt-BR in these tests)."""
        text = self.js("return browser.i18n.getMessage(arguments[0], arguments[1]);", key, list(subs))
        self.assertTrue(text, key)
        return text

    def open_dialog(self) -> dict:
        self.assertTrue(harness.wait_until(lambda: self.js("return !!document.querySelector('dialog[open]');"), timeout=10))
        return self.js(
            "const d = document.querySelector('dialog[open]');"
            "return {title: d.querySelector('.dialog__title').textContent, body: d.querySelector('.dialog__body').textContent,"
            " className: d.className, role: d.getAttribute('role'), describedBy: d.getAttribute('aria-describedby'),"
            " icon: !!d.querySelector('.dialog__title svg[data-icon=critical]'), focused: document.activeElement.value,"
            " primary: d.querySelector('button.button--primary')?.value ?? null,"
            " buttons: [...d.querySelectorAll('button')].map(b => b.value)};"
        )

    def assert_critical_consent(self, dialog: dict, title: str, body: str) -> None:
        """SPA-01 / SB-02: the consent is the page's own locale text, in the critical variant, Cancel first."""
        self.assertEqual(dialog["title"], title)
        self.assertEqual(dialog["body"], body)
        self.assertIn("dialog--critical", dialog["className"])
        self.assertEqual((dialog["role"], dialog["describedBy"], dialog["icon"]), ("alertdialog", "dialog-body", True))
        self.assertEqual((dialog["focused"], dialog["buttons"]), ("cancel", ["cancel", "confirm"]))
        self.assertEqual(dialog["primary"], "cancel", "the safe choice must be visually primary in a critical consent")

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
        shown = lambda i: not self.js(f"return document.getElementById('{i}').hidden;")  # noqa: E731
        self.assertTrue(harness.wait_until(lambda: shown("ai-wizard") or shown("ai-connect-result"), timeout=60))
        if shown("ai-wizard"):  # Claude Code is installed: choose to copy the configuration instead
            self.click("#ai-wizard-manual")
        self.assertTrue(harness.wait_until(lambda: shown("ai-connect-result"), timeout=30))
        config = json.loads(self.js("return document.getElementById('ai-config').textContent;"))
        server = config["mcpServers"]["nulavio"]
        self.assertEqual(server["args"], ["ai", "serve"])
        self.assertNotIn("NULAVIO_AGENT_TOKEN", server["env"])  # a pointer to the key file, never the key
        token_file = Path(server["env"]["NULAVIO_AGENT_TOKEN_FILE"])
        self.assertEqual(os.stat(token_file).st_mode & 0o777, 0o600)
        token = token_file.read_text()
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
        dialog = self.open_dialog()
        self.assert_critical_consent(dialog, self.msg("aiFullControlTitle", "Total"), self.msg("aiFullControlBody", "Total"))
        self.assertNotIn(policy.FULL_CONTROL_WARNING, dialog["body"])  # never the tools' English text
        self.assertIn("automação bruta", dialog["body"])  # says what is not included (pt-BR UI)
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
        self.assertFalse(total.get("raw_automation_accepted"))  # raw automation stays a separate option

    def ask_in_thread(self, agent_id: str, capability: str, target: str, place: str = "") -> tuple[threading.Thread, dict]:
        result: dict = {}
        approver = registry.BrowserApprover(fallback=Approve(None), notice=10, timeout=60)
        thread = threading.Thread(
            target=lambda: result.update(answer=approver.ask(registry.get(agent_id), capability, target, place))
        )
        thread.start()
        return thread, result

    def test_03_permission_request_appears_in_the_window_and_answers_the_bridge(self):
        agent, _ = registry.add("Pesquisa", "codex", "restricted")
        cases = (
            ("interact", "", "warning", "#once", "once", "permission-request"),
            ("transactions", "Trabalho", "critical", "#deny", "deny", "permission-request-critical"),
        )
        for capability, place, risk, button, expected, shot in cases:
            thread, result = self.ask_in_thread(agent["id"], capability, "https://docs.example.org", place)
            self.assertTrue(harness.wait_until(lambda: any("ai/request.html" in u for u in self.tabs()), timeout=20), self.tabs())
            self.switch_to_tab("ai/request.html")
            self.assertTrue(harness.wait_until(lambda: self.js("return document.body.dataset.state;") == "asking", timeout=20))
            self.assertIn("Pesquisa", self.js("return document.getElementById('headline').textContent;"))
            self.assertEqual(self.js("return document.getElementById('target').textContent;"), "https://docs.example.org")
            self.assertEqual(self.js("return document.activeElement.id;"), "deny")  # the safe answer is the keyboard default
            page = self.js(
                "const buttons = [...document.querySelectorAll('#actions button')];"
                "const risk = document.getElementById('risk');"
                "return {order: buttons.map(b => b.id), classes: Object.fromEntries(buttons.map(b => [b.id, b.className])),"
                " session: document.getElementById('session').textContent, risk: risk.dataset.risk, riskClass: risk.className,"
                " riskHidden: risk.hidden, riskIcon: risk.querySelector('svg.callout__icon')?.dataset.icon,"
                " riskText: document.getElementById('risk-text').textContent, who: document.getElementById('who').textContent,"
                " where: document.getElementById('where').textContent, expires: document.getElementById('expires').textContent,"
                " manage: document.querySelector('a[href*=\"settings.html\"]').target};"
            )
            # SB-01: Deny is the filled primary, first; Allow once secondary; until it disconnects, quiet.
            self.assertEqual(page["order"], ["deny", "once", "session"])
            self.assertIn("button--primary", page["classes"]["deny"].split())
            self.assertIn("button--secondary", page["classes"]["once"].split())
            self.assertIn("button--quiet", page["classes"]["session"].split())
            self.assertEqual(page["session"], self.msg("aiAllowSession"))
            # The risk in an icon, words and the level's colour.
            self.assertEqual((page["risk"], page["riskIcon"], page["riskHidden"]), (risk, risk, False))
            self.assertIn(f"callout--{risk}", page["riskClass"].split())
            self.assertEqual(page["riskText"], self.msg(f"aiRisk_{risk}"))
            self.assertEqual(page["who"], self.msg("aiRequestFrom", "Pesquisa", self.msg("aiLevel_restricted")))
            where = self.msg("aiRequestWhereProfile", place) if place else self.msg("aiRequestWhereWorkspace", "Pesquisa")
            self.assertEqual(page["where"], where)
            self.assertRegex(page["expires"], r"\d{1,2}:\d{2}")  # silence means no, at a clock time
            self.assertEqual(page["manage"], "_blank")  # "Gerenciar agentes" opens in a new tab
            self.shoot(shot)
            self.click(button)
            thread.join(30)
            self.assertEqual(result.get("answer"), expected)
            self.assertTrue(harness.wait_until(lambda: not any("ai/request.html" in u for u in self.tabs()), timeout=20))

    def badge(self, agent_id: str, selector: str) -> dict | None:
        return self.js(
            f"const b = document.querySelector(\"[data-agent-id='{agent_id}'] .row__title {selector}\");"
            "return b ? {text: b.textContent, className: b.className, icon: b.querySelector('svg')?.dataset.icon ?? null} : null;"
        )

    def test_04_pause_revoke_stop_and_permissions_from_settings(self):
        agent, _ = registry.add("Controle", "claude-code", "assisted")
        full, _ = registry.add("Tudo", "other", "full_control", accept_full_control=True)
        auto, _ = registry.add("Sozinho", "other", "autonomous")
        self.open_page("settings/settings.html#ai")
        row = f"[data-agent-id='{agent['id']}']"
        self.assertTrue(harness.wait_until(lambda: self.js(f'return !!document.querySelector("{row}");'), timeout=20))
        # SPA-11 / D-UX21: "Nível: …"; Controle total warning-tinted with an icon, Autônomo a warning outline.
        level = self.badge(agent["id"], "[data-level]")
        self.assertEqual(level["text"], self.msg("aiLevelBadge", self.msg("aiLevel_assisted")))
        self.assertEqual((level["className"], level["icon"]), ("badge", None))
        level = self.badge(full["id"], "[data-level]")
        self.assertEqual(level["text"], self.msg("aiLevelBadge", self.msg("aiLevel_full_control")))
        self.assertEqual((level["className"], level["icon"]), ("badge badge--warning", "warning"))
        self.assertEqual(self.badge(auto["id"], "[data-level]")["className"], "badge badge--outline")
        self.click(f"{row} [data-focus-key='pause-{agent['id']}']")
        self.assertTrue(harness.wait_until(lambda: registry.get(agent["id"]).get("paused"), timeout=20))
        self.assertTrue(harness.wait_until(lambda: self.badge(agent["id"], "[data-state=paused]"), timeout=20))
        paused = self.badge(agent["id"], "[data-state=paused]")
        self.assertEqual((paused["text"], paused["icon"]), (self.msg("aiPaused"), "pause"))
        self.js(f'document.querySelector("{row} details").open = true;')
        select = f"[data-focus-key='mode-{agent['id']}-execute_js']"
        self.js(f"const s = document.querySelector(\"{select}\"); s.value = 'allow'; s.dispatchEvent(new Event('change'));")
        self.assertTrue(
            harness.wait_until(
                lambda: registry.get(agent["id"])["grants"].get("execute_js", {}).get("mode") == "allow", timeout=20
            )
        )
        self.shoot("agent-permissions", "ai")
        stopped = "return !document.getElementById('ai-stopped').hidden;"
        switch = "return document.getElementById('ai-stop').checked;"
        self.assertFalse(self.js(stopped))
        # Each toggle waits until the page shows the new state (the list is re-read after every change).
        # While stopped, a persistent warning at the top of the section, with "Retomar".
        self.click("#ai-stop")
        self.assertTrue(harness.wait_until(registry.stopped, timeout=20))
        self.assertTrue(harness.wait_until(lambda: self.js(stopped) and self.js(switch), timeout=20))
        self.click("#ai-stop")
        self.assertTrue(harness.wait_until(lambda: not registry.stopped(), timeout=20))
        self.assertTrue(harness.wait_until(lambda: not self.js(stopped) and not self.js(switch), timeout=20))
        self.click("#ai-stop")
        self.assertTrue(harness.wait_until(registry.stopped, timeout=20))
        self.assertTrue(harness.wait_until(lambda: self.js(stopped), timeout=20))
        self.assertTrue(self.js("return !!document.querySelector('#ai-stopped svg[data-icon=warning]');"))
        self.assertIn(self.msg("aiStoppedBanner"), self.js("return document.getElementById('ai-stopped').textContent;"))
        self.shoot("emergency-stop-on", "ai")
        self.click("#ai-resume")
        self.assertTrue(harness.wait_until(lambda: not registry.stopped(), timeout=20))
        self.assertTrue(harness.wait_until(lambda: not self.js(stopped), timeout=20))
        self.assertFalse(self.js("return document.getElementById('ai-stop').checked;"))
        self.js(f"[...document.querySelectorAll(\"{row} .row__end button\")].find(b => b.textContent === arguments[0]).click();",
                self.js("return browser.i18n.getMessage('aiRevoke');"))  # fmt: skip
        self.assertTrue(harness.wait_until(lambda: self.js("return !!document.querySelector('dialog[open]');"), timeout=10))
        self.click("dialog[open] button[value=confirm]")
        self.assertTrue(harness.wait_until(lambda: registry.get(agent["id"]).get("revoked"), timeout=20))

    def test_05_activity_shows_actions_not_content(self):
        agent, _ = registry.add("Historico", "other", "assisted")
        audit.record(agent=agent["id"], tool="navigate", decision="allow", outcome="ok", target="https://example.org")
        audit.record(agent=agent["id"], tool="evaluate", decision="deny", reason="preset:assisted", outcome="denied")
        audit.record(agent=agent["id"], tool="raw_automation", event="raw-ended", reason="stopped")
        audit.record(agent=agent["id"], tool="assistant.ask", decision="allow", outcome="ok")
        self.open_page("settings/settings.html#ai")
        evaluate = self.msg("aiTool_evaluate")
        self.assertTrue(
            harness.wait_until(
                lambda: evaluate in self.js("return document.getElementById('ai-activity').textContent;"), timeout=20
            )
        )
        text = self.js("return document.getElementById('ai-activity').textContent;")
        # AI-11: tools and events by their localised titles, never raw ids.
        self.assertIn(f"Historico · {self.msg('aiTool_navigate')}", text)
        self.assertIn(f"Historico · {self.msg('aiEvent_raw_ended')}", text)
        self.assertIn(f"Historico · {self.msg('aiTool_assistant_ask')}", text)
        for raw_id in ("· navigate", "· evaluate", "raw_automation", "raw-ended", "assistant.ask"):
            self.assertNotIn(raw_id, text)
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
            # The window says who drives it, in a bar that cannot be closed (the real AI Workspace: test_ai_bridge 21-22).
            texts = {"text": "Área de IA de Workspace", "rawText": "raw", "pausedText": "paused", "failedText": "failed",
                     "stopLabel": "Parar agente"}  # fmt: skip
            self.m.set_context("chrome")
            try:
                self.m.execute_async(
                    "const done = arguments[arguments.length - 1];"
                    "ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs')"
                    ".NulavioAI.markWorkspace(arguments[0]).then(done, done);",
                    [texts],
                )
                self.assertTrue(
                    harness.wait_until(
                        lambda: self.m.execute("return !!gNotificationBox.getNotificationWithValue('nulavio-ai-workspace');"),
                        timeout=10,
                    )
                )
                bar = self.m.execute(
                    "const n = gNotificationBox.getNotificationWithValue('nulavio-ai-workspace');"
                    "return {label: n.messageText.textContent.trim(), dismissable: n.dismissable,"
                    " buttons: [...n.querySelectorAll('.notification-button')].map(b => b.label),"
                    " state: document.documentElement.getAttribute('nulavio-state')};"
                )
            finally:
                self.m.set_context("content")
            self.assertEqual(bar, {"label": "Área de IA de Workspace", "dismissable": False, "buttons": ["Parar agente"],
                                   "state": "ai"})  # fmt: skip
        finally:
            self.m.chrome(
                "Services.prefs.clearUserPref('nulavio.ai.workspace');"
                "gNotificationBox.getNotificationWithValue('nulavio-ai-workspace')?.remove();"
                "document.documentElement.removeAttribute('nulavio-state');"
            )

    def real_config_fingerprint(self) -> dict:
        """The user's real MCP server settings. Claude Code rewrites the rest of ~/.claude.json while it runs
        (other state), so only the MCP sections are compared; Codex's config.toml is compared whole."""
        home = Path(os.environ["HOME"])
        out = {}
        claude = home / ".claude.json"
        if claude.exists():
            data = json.loads(claude.read_text(encoding="utf-8"))
            servers = {
                "user": data.get("mcpServers"),
                "projects": {k: v.get("mcpServers") for k, v in data.get("projects", {}).items()},
            }
            out[str(claude)] = hashlib.sha256(json.dumps(servers, sort_keys=True).encode()).hexdigest()
        codex = home / ".codex" / "config.toml"
        out[str(codex)] = hashlib.sha256(codex.read_bytes()).hexdigest() if codex.exists() else None
        return out

    def test_07_connect_wizard_runs_the_agents_own_cli(self):
        clients = [c for c in ("claude", "codex") if shutil.which(c, path=self.session.env["PATH"])]
        if not clients:
            self.skipTest("neither Claude Code nor Codex is installed")
        before = self.real_config_fingerprint()
        fake_home = Path(self.session.env["HOME"])
        for binary, client, label in (("claude", "claude-code", "Claude Code"), ("codex", "codex", "Codex")):
            if binary not in clients:
                continue
            self.open_page("settings/settings.html#ai")
            self.js("document.querySelector('#ai-connect-form [name=name]').value = arguments[0];", f"{label} via wizard")
            self.click(f"#ai-clients input[value={client}]")
            self.click("#ai-connect-form button[type=submit]")
            self.assertTrue(
                harness.wait_until(lambda: not self.js("return document.getElementById('ai-wizard').hidden;"), timeout=60)
            )
            command = self.js("return document.getElementById('ai-wizard-command').textContent;")
            self.assertIn("NULAVIO_AGENT_TOKEN_FILE", command)
            agent = next(a for a in self.agents().values() if a["name"] == f"{label} via wizard")
            token = registry.token_file(agent["id"]).read_text()
            self.assertNotIn(token, command)  # no secret on the command line or in the agent's settings
            if client == "claude-code":
                self.assertIn("mcp add-json --scope user nulavio", command)
                self.shoot("wizard")
            else:
                self.assertIn("mcp add nulavio", command)
            self.click("#ai-wizard-install")
            self.assertTrue(
                harness.wait_until(
                    lambda: not self.js("return document.getElementById('ai-connect-result').hidden;"), timeout=120
                )
            )
            intro = self.js("return document.getElementById('ai-config-intro').textContent;")
            expected = "aiInstalled_connected" if client == "claude-code" else "aiInstalled_configured"
            self.assertTrue(
                intro.startswith(self.js("return browser.i18n.getMessage(arguments[0], [arguments[1]]);", expected, label)), intro
            )
            written = (fake_home / ".claude.json") if client == "claude-code" else (fake_home / ".codex" / "config.toml")
            text = written.read_text()
            self.assertIn(str(registry.token_file(agent["id"])), text)
            self.assertNotIn(token, text)
        self.assertEqual(self.real_config_fingerprint(), before)  # the user's real agent settings were not touched

    def test_08_profiles_and_routes_for_an_agent(self):
        agent, _ = registry.add("Rotas", "codex", "autonomous")
        self.m.set_context("chrome")
        try:
            created = self.m.execute_async(
                "const done = arguments[arguments.length - 1];"
                "const P = ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs').NulavioProfiles;"
                "P.create({templateId: 'work', name: 'Trabalho'})"
                ".then(async id => done((await P.list()).profiles.find(p => p.id === id).path));"
            )
        finally:
            self.m.set_context("content")
        self.open_page("settings/settings.html#ai")
        row = f"[data-agent-id='{agent['id']}']"
        self.assertTrue(harness.wait_until(lambda: self.js(f'return !!document.querySelector("{row}");'), timeout=20))
        self.js(f'document.querySelector("{row} details").open = true;')
        self.js(f'document.querySelector("{row} input[type=checkbox][value=\'" + arguments[0] + "\']").checked = true;', created)
        self.click(f"[data-focus-key='profiles-save-{agent['id']}']")
        self.assertTrue(
            harness.wait_until(
                lambda: registry.get(agent["id"]).get("profiles") == [{"label": "Trabalho", "path": created}], timeout=20
            )
        )
        self.assertTrue(
            harness.wait_until(
                lambda: self.js(f"return !!document.querySelector(\"[data-focus-key='route-site-{agent['id']}']\");"), timeout=20
            )
        )
        self.js(f"document.querySelector(\"{row} details\").open = true;"
                f"document.querySelector(\"[data-focus-key='route-site-{agent['id']}']\").value = 'localhost';")  # fmt: skip
        self.click(f"[data-focus-key='route-add-{agent['id']}']")
        self.assertTrue(
            harness.wait_until(
                lambda: registry.get(agent["id"]).get("routes") == [{"site": "localhost", "profile": "Trabalho"}], timeout=20
            )
        )

    def test_09_raw_automation_is_a_separate_switch_with_its_own_warning(self):
        agent, _ = registry.add("Bruto", "other", "full_control", accept_full_control=True)
        self.open_page("settings/settings.html#ai")
        row = f"[data-agent-id='{agent['id']}']"
        self.assertTrue(harness.wait_until(lambda: self.js(f'return !!document.querySelector("{row}");'), timeout=20))
        self.js(f'document.querySelector("{row} details").open = true;')
        # D-UX4 / SB-03: not in the per-capability list, and off under Full control.
        self.assertFalse(self.js(f"return !!document.querySelector(\"[data-focus-key='mode-{agent['id']}-debugging']\");"))
        switch = f"[data-focus-key='raw-{agent['id']}']"
        self.assertFalse(self.js(f'return document.querySelector("{switch}").checked;'))
        self.click(switch)
        dialog = self.open_dialog()
        self.assert_critical_consent(dialog, self.msg("aiRawTitle", "Bruto"), self.msg("aiRawBody", "Bruto"))
        self.shoot("raw-automation-warning", "ai")
        self.click("dialog[open] button[value=cancel]")
        time.sleep(1)
        self.assertFalse(registry.get(agent["id"]).get("raw_automation_accepted"))
        self.assertFalse(self.js(f'return document.querySelector("{switch}").checked;'))
        self.click(switch)
        self.open_dialog()
        self.click("dialog[open] button[value=confirm]")
        self.assertTrue(harness.wait_until(lambda: registry.get(agent["id"]).get("raw_automation_accepted"), timeout=20))
        self.assertTrue(harness.wait_until(lambda: self.js(f'return document.querySelector("{switch}")?.checked;'), timeout=20))
        self.click(switch)  # off again needs no confirmation
        self.assertTrue(harness.wait_until(lambda: not registry.get(agent["id"]).get("raw_automation_accepted"), timeout=20))
        self.assertFalse(self.js("return !!document.querySelector('dialog[open]');"))

    def test_10_the_assistant_appears_as_an_agent_at_once(self):
        """AI-11: its client has a name, and the list refreshes after it is configured."""
        self.open_page("settings/settings.html#ai")
        self.assertTrue(harness.wait_until(lambda: self.js("return !!document.querySelector('#ai-agents li');"), timeout=20))
        form = "#ai-assistant"
        self.js(
            f"const f = document.querySelector('{form}'); f.elements.kind.value = 'openai';"
            "f.elements.model.value = 'modelo-local'; f.elements.baseUrl.value = 'http://127.0.0.1:9/v1';"
        )
        self.click(f"{form} button[type=submit]")
        name = self.msg("aiClient_nulavio_assistant")
        self.assertTrue(
            harness.wait_until(lambda: name in self.js("return document.getElementById('ai-agents').textContent;"), timeout=30),
            self.js("return document.getElementById('ai-agents').textContent;"),
        )
        listed = self.js("return document.getElementById('ai-agents').textContent;")
        self.assertNotIn("aiClient_", listed)
        assistant = next(a for a in self.agents().values() if a["client"] == "nulavio-assistant")
        self.assertFalse(self.js(f"return !!document.querySelector(\"[data-focus-key='raw-{assistant['id']}']\");"))
        self.assertTrue(re.search(re.escape(self.msg("aiLevelBadge", self.msg("aiLevel_restricted"))), listed))


if __name__ == "__main__":
    unittest.main()
