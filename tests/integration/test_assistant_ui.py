"""Nulavio Assistant in the browser (A12), Nulavio build.

A stand-in provider on 127.0.0.1 (tests/lib/fake_llm.py) plays the model and a
stand-in secret-tool plays the system keyring, so no real key, account or
model is involved. Checked: the key goes to the keyring and nowhere in the
profile; a profile must be allowed; the page's text goes only when the user
includes it, extracted by the engine; tasks are tool calls under the
assistant's agent policy (restricted: a local address is refused).
"""

from __future__ import annotations

import base64
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from fake_llm import FakeProvider
from fake_keyring import FAKE_SECRET_TOOL

AI = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs").NulavioAI'
KEY = "sk-artificial-ui-key-456"


def chrome_async(m, body: str, args=()):
    script = (
        "const done = arguments[arguments.length - 1]; const args = Array.from(arguments).slice(0, -1);"
        "(async () => {" + body + "})().then(v => done({ok: v ?? null}), e => done({error: e?.code ?? String(e)}));"
    )
    m.set_context("chrome")
    try:
        return m.execute_async(script, list(args))
    finally:
        m.set_context("content")


@unittest.skipUnless(harness.nulavio_engine(), "the Nulavio build's Shell (NULAVIO_ENGINE)")
class AssistantUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = FakeProvider()
        cls.server = harness.FixtureServer().__enter__()
        cls.session = harness.GeckoProfileSession(name="Pessoal")
        tool = cls.session.tmp / "secret-tool"
        tool.write_text(FAKE_SECRET_TOOL.format(python=sys.executable))
        tool.chmod(0o700)
        cls.keyring = cls.session.tmp / "keyring.json"
        cls.session.env["NULAVIO_SECRET_TOOL"] = str(tool)
        cls.session.env["NV_FAKE_KEYRING"] = str(cls.keyring)
        cls.m = cls.session.start()
        cls.base = cls.m.chrome("return WebExtensionPolicy.getByID('shell@nulavio.net').getURL('');")
        cls.shots = harness.artifacts_dir() / "assistant"
        cls.shots.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.session.cleanup()
            cls.provider.close()
        finally:
            cls.server.__exit__(None, None, None)

    def open(self, page: str) -> None:
        self.m.navigate(self.base + page)
        self.assertTrue(
            harness.wait_until(lambda: self.m.execute("return document.documentElement.dataset.ready === 'true';"), 20)
        )

    def shoot(self, name: str, keep: str | None = None) -> None:
        for scheme in ("light", "dark"):
            self.m.execute(
                "document.documentElement.dataset.theme = arguments[0]; document.body.style.display = 'none';"
                "document.body.offsetHeight; document.body.style.display = '';"
                "for (const s of arguments[1] ? document.querySelectorAll('section.section') : []) {"
                " s.hidden = s.id !== arguments[1]; }",
                [scheme, keep],
            )
            time.sleep(0.3)
            (self.shots / f"{name}-{scheme}.png").write_bytes(self.m.screenshot_png(full=True))
        self.m.execute("delete document.documentElement.dataset.theme;")

    def test_01_settings_store_the_key_in_the_keyring_only(self):
        self.open("settings/settings.html#ai")
        self.m.execute(
            "const f = document.getElementById('ai-assistant'); f.elements.kind.value = 'openai';"
            "f.elements.baseUrl.value = arguments[0]; f.elements.model.value = 'test-model'; f.elements.key.value = arguments[1];"
            "f.elements.allowed.checked = true; f.requestSubmit();",
            [self.provider.base, KEY],
        )
        configured = "return document.getElementById('ai-assistant').dataset.configured === 'true';"
        self.assertTrue(harness.wait_until(lambda: self.m.execute(configured), 20))
        status = self.m.execute("return document.getElementById('ai-assistant-state').textContent;")
        self.assertIn("test-model", status)
        self.assertIn("127.0.0.1", status)
        self.assertIn("chaveiro", status)
        self.assertEqual(self.m.execute("return document.querySelector('#ai-assistant [name=key]').value;"), "")
        stored = json.loads(self.keyring.read_text())
        self.assertEqual([base64.b64decode(i["secret"]).decode() for i in stored], [KEY])  # in the (stand-in) keyring
        for path in self.session.profile_dir.rglob("*"):
            if path.is_file() and path.stat().st_size < 20_000_000:
                self.assertNotIn(KEY.encode(), path.read_bytes(), f"key found in {path}")
        self.shoot("settings", keep="ai")

    def test_02_page_text_goes_only_when_included(self):
        self.m.navigate(self.server.url("/agent-task?word=OBSIDIAN"))
        before = len(self.provider.requests)
        result = chrome_async(self.m, f"return await {AI}.assistantAsk('Qual é a palavra?', false, window);")
        self.assertEqual(result["ok"]["pageChars"], 0)
        self.assertNotIn("OBSIDIAN", json.dumps(self.provider.requests[before:]))
        result = chrome_async(self.m, f"return await {AI}.assistantAsk('Qual é a palavra?', true, window);")
        self.assertGreater(result["ok"]["pageChars"], 0)
        sent = json.dumps(self.provider.requests[-1][2])
        self.assertIn("OBSIDIAN", sent)  # the visible text, extracted by the engine
        self.assertIn("untrusted", sent)
        self.assertEqual(self.provider.requests[-1][1]["authorization"], f"Bearer {KEY}")

    def test_03_panel_asks_and_shows_the_answer_as_text(self):
        self.provider.replies.append({"choices": [{"message": {"content": "<b>Resposta</b> em texto"}}]})
        self.open("assistant/panel.html")
        self.assertEqual(self.m.execute("return document.body.dataset.state;"), "ready")
        self.m.execute("document.getElementById('prompt').value = 'Olá?'; document.getElementById('ask').requestSubmit();")
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.body.dataset.answered === 'true';"), 20))
        answer = self.m.execute(
            "return [document.getElementById('answer').textContent, document.getElementById('answer').children.length];"
        )
        self.assertEqual(answer, ["<b>Resposta</b> em texto", 0])  # never rendered as markup
        self.shoot("panel")

    def test_04_tasks_obey_the_assistant_agent_policy(self):
        call = {
            "id": "c1",
            "type": "function",
            "function": {"name": "tab_new", "arguments": json.dumps({"url": self.server.url("/page/local")})},
        }
        self.provider.replies += [
            {"choices": [{"message": {"content": None, "tool_calls": [call]}}]},
            {"choices": [{"message": {"content": "Não pude abrir."}}]},
        ]
        result = chrome_async(self.m, f"return await {AI}.assistantTask('Abra a página local');")["ok"]
        self.assertEqual(result["steps"], [{"tool": "tab_new", "error": True}])  # restricted: no local addresses
        self.assertEqual(result["answer"], "Não pude abrir.")
        denied = [m for m in self.provider.requests[-1][2]["messages"] if m.get("role") == "tool"]
        self.assertIn("Denied by Nulavio", denied[-1]["content"])

    def test_05_the_side_panel_is_registered(self):
        self.assertTrue(self.m.chrome("return SidebarController.sidebars.has('shell_nulavio_net-sidebar-action');"))


if __name__ == "__main__":
    unittest.main()
