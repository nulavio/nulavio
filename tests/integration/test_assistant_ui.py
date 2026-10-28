"""Nulavio Assistant in the browser (A12, UX1), Nulavio build.

A stand-in provider on 127.0.0.1 (tests/lib/fake_llm.py) plays the model and a
stand-in secret-tool plays the system keyring, so no real key, account or
model is involved. Checked: the key goes to the keyring and nowhere in the
profile; a profile must be allowed; a page's text goes only for the tab the
user included, extracted by the engine, and never after that tab changed;
tasks are tool calls under the assistant's agent policy (restricted: a local
address is refused).

UX1 (audit 2026-10-27): the real side panel (not the page opened as a tab)
finds the page next to it (AI-01); consent is per message and bound to one tab,
and the panel says when it lapses (AI-02); nothing in private windows (AI-15,
D-UX6); the emergency stop and pausing the assistant block questions and page
text too (AI-10, D-UX5); task endings are told honestly and permission
requests open in front (AI-04); progress carries no check mark, Ctrl+Enter
sends, the answer sits under a heading (AI-12).

The side panel runs in the extension process, out of Marionette's reach, so the
tests read and drive it through a message-manager frame script in its browser.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import signal
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from fake_llm import FakeProvider
from fake_keyring import FAKE_SECRET_TOOL

AI = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs").NulavioAI'
TABS = 'ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs").ExtensionParent.apiManager.global.tabTracker'
KEY = "sk-artificial-ui-key-456"
SIDEBAR = "shell_nulavio_net-sidebar-action"
# The browser window a helper acts on: the private one when its argument says "private".
WINDOW = (
    "(args[args.length - 1] === 'private' ? [...Services.wm.getEnumerator('navigator:browser')].find(w =>"
    " ChromeUtils.importESModule('resource://gre/modules/PrivateBrowsingUtils.sys.mjs')"
    ".PrivateBrowsingUtils.isWindowPrivate(w)) : window)"
)

# Run `code` (an async function body) in the side panel's page and resolve to its JSON result.
PANEL = (
    "const [code, which] = arguments; const done = arguments[arguments.length - 1]; const args = [which];"
    f"const win = {WINDOW};"
    "const browser = win?.SidebarController.browser.contentDocument?.getElementById('webext-panels-browser');"
    "if (!browser?.messageManager) { done({ error: 'no-panel' }); return; }"
    "const mm = browser.messageManager; const id = String(Math.random()).slice(2);"
    "const listener = msg => { if (msg.data.id === id) { mm.removeMessageListener('nv-test:result', listener);"
    " done(msg.data); } };"
    "mm.addMessageListener('nv-test:result', listener);"
    "const script = '(async () => { const document = content.document; let reply;'"
    " + ' try { const value = await (async () => {' + code + '})();'"
    " + ' reply = { ok: value === undefined ? null : JSON.parse(JSON.stringify(value)) }; }'"
    " + ' catch (e) { reply = { error: String(e) }; }'"
    " + ' sendAsyncMessage(\"nv-test:result\", Object.assign(reply, { id: \"' + id + '\" })); })();';"
    "mm.loadFrameScript('data:,' + encodeURIComponent(script), false);"
)
VIEW = (
    "const $ = id => document.getElementById(id);"
    "return { state: document.body.dataset.state, answered: document.body.dataset.answered === 'true',"
    " offer: $('include-page').hidden ? null : $('include-page').textContent,"
    " attached: $('attached').hidden ? null : $('attached-binding').textContent,"
    " heading: $('attached-heading').textContent, remove: $('remove-page').getAttribute('aria-label'),"
    " drift: $('drift').hidden ? null : $('drift-text').textContent, noPage: !$('no-page').hidden,"
    " summarize: !$('summarize').hidden, status: $('status').textContent, level: $('status').dataset.level ?? null,"
    " receipt: $('receipt').textContent, activity: !$('activity-actions').hidden,"
    " blocked: $('blocked').hidden ? null : [$('blocked-title').textContent, $('blocked-text').textContent],"
    " private: !$('private').hidden, composer: !$('ask').hidden };"
)


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

    def setUp(self):
        self.provider.delay = 0.0
        self.provider.replies.clear()

    # -- helpers ---------------------------------------------------------------------------

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

    def shoot_window(self, name: str) -> None:
        """The browser window with the side panel, in both themes of the panel."""
        for scheme in ("light", "dark"):
            self.panel(f"document.documentElement.dataset.theme = '{scheme}';")
            time.sleep(0.3)
            self.m.set_context("chrome")
            try:
                (self.shots / f"{name}-{scheme}.png").write_bytes(self.m.screenshot_png())
            finally:
                self.m.set_context("content")
        self.panel("delete document.documentElement.dataset.theme;")

    def panel(self, code: str, which: str | None = None):
        self.m.set_context("chrome")
        try:
            result = self.m.execute_async(PANEL, [code, which])
        finally:
            self.m.set_context("content")
        if "error" in result:
            raise AssertionError(f"in the side panel: {result['error']}")
        return result["ok"]

    def view(self, which: str | None = None) -> dict:
        return self.panel(VIEW, which)

    def wait_view(self, predicate, which: str | None = None, timeout: float = 20) -> dict:
        found = harness.wait_until(lambda: (lambda v: v if predicate(v) else None)(self.view(which)), timeout)
        self.assertTrue(found, self.view(which))
        return found

    def show_sidebar(self, which: str | None = None, reload: bool = False) -> dict:
        show = f"const w = {WINDOW}; await w.SidebarController.show(args[0]); return w.SidebarController.currentID;"
        self.assertEqual(chrome_async(self.m, show, [SIDEBAR, which]), {"ok": SIDEBAR})
        if reload:
            self.panel("delete document.documentElement.dataset.ready; content.location.reload();", which)

        def ready():
            try:
                return self.panel("return document.documentElement.dataset.ready === 'true';", which)
            except AssertionError:
                return False  # the panel's browser is still being created

        self.assertTrue(harness.wait_until(ready, 20))
        return self.view(which)

    def select_new_tab(self, url: str) -> None:
        self.m.chrome("gBrowser.selectedTab = gBrowser.addTrustedTab(arguments[0]);", [url])
        self.wait_loaded(url)

    def select_tab(self, url: str) -> None:
        self.m.chrome(
            "gBrowser.selectedTab = [...gBrowser.tabs].find(t => t.linkedBrowser.currentURI.spec === arguments[0]);", [url]
        )

    def go(self, url: str) -> None:
        """Navigate the selected tab, as following a link would."""
        self.m.chrome("openTrustedLinkIn(arguments[0], 'current');", [url])
        self.wait_loaded(url)

    def wait_loaded(self, url: str) -> None:
        loaded = (
            "const b = gBrowser.selectedBrowser; return b.currentURI.spec === arguments[0] && !b.webProgress.isLoadingDocument;"
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(loaded, [url]), 20), url)

    def close_other_tabs(self) -> None:
        self.m.chrome(
            "for (const t of [...gBrowser.tabs].slice(1)) gBrowser.removeTab(t); gBrowser.selectedTab = gBrowser.tabs[0];"
        )

    def submit(self, text: str, which: str | None = None) -> None:
        self.panel(
            "const p = document.getElementById('prompt'); p.value = " + json.dumps(text) + ";"
            " document.getElementById('ask').requestSubmit();",
            which,
        )

    def mode(self, value: str) -> None:
        self.panel(f"document.querySelector('input[name=mode][value={value}]').click();")

    def sent_since(self, before: int) -> str:
        return json.dumps([body for _path, _headers, body in self.provider.requests[before:]], ensure_ascii=False)

    def assistant_agent(self) -> str:
        return chrome_async(self.m, f"return (await {AI}.assistantState(window)).agent.id;")["ok"]

    # -- settings and the module ------------------------------------------------------------

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

    def test_02_page_text_goes_only_for_the_included_tab(self):
        url = self.server.url("/agent-task?word=OBSIDIAN")
        self.m.navigate(url)
        page = chrome_async(self.m, f"return {AI}.assistantPage(window);")["ok"]
        self.assertEqual((page["url"], page["title"]), (url, "agent-task"))
        self.assertIsInstance(page["tabId"], int)
        binding = {"tabId": page["tabId"], "url": page["url"]}
        ask = f"return await {AI}.assistantAsk('Qual é a palavra?', args[0], window);"
        before = len(self.provider.requests)
        self.assertEqual(chrome_async(self.m, ask, [None])["ok"]["pageChars"], 0)
        self.assertNotIn("OBSIDIAN", self.sent_since(before))
        result = chrome_async(self.m, ask, [binding])
        self.assertGreater(result["ok"]["pageChars"], 0)
        sent = self.sent_since(before)
        self.assertIn("OBSIDIAN", sent)  # the visible text, extracted by the engine
        self.assertIn("untrusted", sent)
        self.assertEqual(self.provider.requests[-1][1]["authorization"], f"Bearer {KEY}")
        # Bound to that tab: another selected tab is never read in its place.
        other = self.server.url("/agent-task?word=QUARTZ")
        self.select_new_tab(other)
        before = len(self.provider.requests)
        self.assertGreater(chrome_async(self.m, ask, [binding])["ok"]["pageChars"], 0)
        self.assertIn("OBSIDIAN", self.sent_since(before))
        self.assertNotIn("QUARTZ", self.sent_since(before))
        self.close_other_tabs()
        # That tab went to another address: refused, nothing sent (the consent was for the page before).
        moved = self.server.url("/agent-task?word=JASPER")
        self.m.navigate(moved)
        before = len(self.provider.requests)
        self.assertEqual(chrome_async(self.m, ask, [binding]), {"error": "page-changed"})
        self.assertEqual(chrome_async(self.m, ask, [{"tabId": page["tabId"], "url": url + "#more"}]), {"error": "page-changed"})
        self.assertEqual(chrome_async(self.m, ask, [{"tabId": 999999, "url": moved}]), {"error": "page-changed"})
        self.assertEqual(len(self.provider.requests), before)
        # Without a window around the caller, the assistant does nothing.
        self.assertEqual(chrome_async(self.m, f"return await {AI}.assistantAsk('Oi', null, null);"), {"error": "no-window"})
        self.assertEqual(chrome_async(self.m, f"return await {AI}.assistantTask('Oi', null);"), {"error": "no-window"})
        self.assertEqual(len(self.provider.requests), before)

    def test_03_panel_answers_as_text_and_announces_only_start_and_end(self):
        self.provider.replies.append({"choices": [{"message": {"content": "<b>Resposta</b> em texto"}}]})
        self.provider.delay = 2.0
        self.open("assistant/panel.html")
        self.assertEqual(self.m.execute("return document.body.dataset.state;"), "ready")
        # Opened as a tab, the selected tab is the panel itself: nothing to include, and the panel says why.
        nothing = (
            "return [!document.getElementById('no-page').hidden, document.getElementById('include-page').hidden,"
            " document.getElementById('summarize').hidden];"
        )
        self.assertEqual(self.m.execute(nothing), [True, True, True])
        # Ctrl+Enter sends (AI-12).
        self.m.execute(
            "const p = document.getElementById('prompt'); p.value = 'Olá?';"
            "p.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, bubbles: true, cancelable: true}));"
        )
        status = (
            "const s = document.getElementById('status');"
            "return [s.dataset.level, s.textContent, getComputedStyle(s, '::before').content];"
        )
        busy = harness.wait_until(lambda: (lambda v: v if v[0] == "busy" else None)(self.m.execute(status)), 10)
        self.assertTrue(busy, self.m.execute(status))
        self.assertEqual(busy[1], "Enviado para 127.0.0.1. Aguardando a resposta…")
        self.assertEqual(busy[2], "none")  # no check mark while waiting
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.body.dataset.answered === 'true';"), 20))
        level, text, mark = self.m.execute(status)
        self.assertEqual((level, text), ("ok", "Resposta pronta."))
        self.assertIn("✓", mark)  # done
        answer = self.m.execute(
            "const a = document.getElementById('answer'), s = document.getElementById('answer-section');"
            "const h = document.getElementById(s.getAttribute('aria-labelledby'));"
            "return [a.textContent, a.children.length, a.hasAttribute('aria-live'), h.tagName, h.textContent,"
            " document.getElementById('receipt').textContent];"
        )
        self.assertEqual(
            answer, ["<b>Resposta</b> em texto", 0, False, "H2", "Resposta", "Só a pergunta foi enviada para 127.0.0.1."]
        )
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
        result = chrome_async(self.m, f"return await {AI}.assistantTask('Abra a página local', window);")["ok"]
        self.assertEqual(result["steps"], [{"tool": "tab_new", "error": True}])  # restricted: no local addresses
        self.assertEqual(result["answer"], "Não pude abrir.")
        denied = [m for m in self.provider.requests[-1][2]["messages"] if m.get("role") == "tool"]
        self.assertIn("Denied by Nulavio", denied[-1]["content"])

    def test_05_the_side_panel_is_registered(self):
        self.assertTrue(self.m.chrome(f"return SidebarController.sidebars.has('{SIDEBAR}');"))

    # -- the real side panel ------------------------------------------------------------------

    def test_06_the_side_panel_includes_the_page_next_to_it_for_one_message(self):
        url = self.server.url("/page/Artigo")
        host = url.split("/")[2]
        self.select_new_tab(url)
        view = self.show_sidebar()
        self.assertEqual(view["state"], "ready")
        # AI-01: the panel in the sidebar finds the page in its window (Gecko 158+ renamed ownerGlobal).
        view = self.wait_view(lambda v: v["offer"])
        self.assertEqual(view["offer"], "+ Incluir esta página: Artigo")
        self.assertTrue(view["summarize"])
        self.assertFalse(view["noPage"])
        self.assertIsNone(view["attached"])  # nothing is included until the user says so
        # Including binds this tab, and the item says so.
        self.panel("document.getElementById('include-page').click();")
        view = self.wait_view(lambda v: v["attached"])
        self.assertEqual(view["attached"], f"só da aba “Artigo” · {host}")
        self.assertEqual(view["heading"], "Vai junto com a próxima mensagem, para 127.0.0.1")
        self.assertEqual(view["remove"], "Remover a página “Artigo” da mensagem")
        self.assertIsNone(view["offer"])
        self.shoot_window("sidebar-attached")
        before = len(self.provider.requests)
        self.submit("Do que trata a página?")
        view = self.wait_view(lambda v: v["answered"])
        self.assertIn("<<<PAGE", self.sent_since(before))
        self.assertIn("Artigo", self.sent_since(before))
        self.assertRegex(view["receipt"], r"^\d+ caracteres desta página foram enviados para 127\.0\.0\.1\.$")
        # Consent is per message: the item left with the message, and the next one goes without it.
        self.assertIsNone(view["attached"])
        self.assertEqual(view["offer"], "+ Incluir esta página: Artigo")
        before = len(self.provider.requests)
        self.submit("E depois?")
        view = self.wait_view(lambda v: v["answered"] and v["receipt"].startswith("Só a pergunta"))
        self.assertNotIn("<<<PAGE", self.sent_since(before))
        # The remove control takes it out before Send.
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        self.panel("document.getElementById('remove-page').click();")
        view = self.wait_view(lambda v: not v["attached"] and v["offer"])
        self.assertTrue(self.panel("return document.activeElement.id === 'include-page';"))
        before = len(self.provider.requests)
        self.submit("Sem a página?")
        self.wait_view(lambda v: v["answered"] and v["receipt"].startswith("Só a pergunta"))
        self.assertNotIn("<<<PAGE", self.sent_since(before))
        # Summarise sends this page, by that explicit action, and nothing stays included after it.
        before = len(self.provider.requests)
        self.panel("document.getElementById('summarize').click();")
        view = self.wait_view(lambda v: v["answered"] and "desta página" in v["receipt"])
        self.assertIn("<<<PAGE", self.sent_since(before))
        self.assertIsNone(view["attached"])
        before = len(self.provider.requests)
        self.submit("E mais?")
        self.wait_view(lambda v: v["answered"] and v["receipt"].startswith("Só a pergunta"))
        self.assertNotIn("<<<PAGE", self.sent_since(before))

    def test_07_switching_tabs_or_leaving_the_page_takes_it_out_and_says_so(self):
        first, second, third = (self.server.url(f"/page/{name}") for name in ("Artigo", "Quadro", "Painel"))
        self.close_other_tabs()
        self.select_new_tab(first)
        self.select_new_tab(second)
        self.select_tab(first)
        self.show_sidebar()
        self.wait_view(lambda v: v["offer"] == "+ Incluir esta página: Artigo")
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        # Another tab: the item does not follow (the drift message), and the new page is only offered.
        self.select_tab(second)
        view = self.wait_view(lambda v: v["drift"])
        self.assertEqual(view["drift"], "“Artigo” era de outra aba e saiu da mensagem.")
        self.assertIsNone(view["attached"])
        self.assertEqual(view["offer"], "+ Incluir esta página: Quadro")
        self.shoot_window("sidebar-drift")
        before = len(self.provider.requests)
        self.submit("E esta?")
        self.wait_view(lambda v: v["answered"] and v["receipt"].startswith("Só a pergunta"))
        self.assertNotIn("<<<PAGE", self.sent_since(before))
        # The included tab goes to another address: out as well.
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"] and "Quadro" in v["attached"])
        self.go(third)
        view = self.wait_view(lambda v: v["drift"] and "Quadro" in v["drift"])
        self.assertEqual(view["drift"], "“Quadro” não está mais nesta aba e saiu da mensagem.")
        self.assertIsNone(view["attached"])
        self.wait_view(lambda v: v["offer"] == "+ Incluir esta página: Painel")
        # A tab with no web page offers nothing and says why; once it loads one, that page is offered.
        self.select_new_tab("about:blank")
        view = self.wait_view(lambda v: v["noPage"])
        self.assertIsNone(view["offer"])
        self.assertFalse(view["summarize"])
        self.go(self.server.url("/page/Fim"))
        self.wait_view(lambda v: v["offer"] == "+ Incluir esta página: Fim")
        self.close_other_tabs()

    def test_08_nothing_in_private_windows(self):
        url = self.server.url("/agent-task?word=PRIVATE")
        opened = chrome_async(
            self.m,
            "const w = OpenBrowserWindow({private: true}); await new Promise(r => w.addEventListener('load', r, {once: true}));"
            "await w.delayedStartupPromise; w.gBrowser.selectedTab = w.gBrowser.addTrustedTab(args[0]); return true;",
            [url],
        )
        self.assertEqual(opened, {"ok": True})
        self.addCleanup(lambda: chrome_async(self.m, f"{WINDOW}?.close(); return true;", ["private"]))
        loaded = (
            f"const args = ['private']; const b = {WINDOW}.gBrowser.selectedBrowser;"
            " return b.currentURI.spec === arguments[0] && !b.webProgress.isLoadingDocument;"
        )
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(loaded, [url]), 20))
        before = len(self.provider.requests)
        private_tab = f"{{tabId: {TABS}.getId(w.gBrowser.selectedTab), url: args[0]}}"
        for call in (
            f"return {AI}.assistantPage(w);",
            f"return await {AI}.assistantAsk('Oi', null, w);",
            f"return await {AI}.assistantAsk('Qual é a palavra?', {private_tab}, w);",
            f"return await {AI}.assistantTask('Abra algo', w);",
        ):
            with self.subTest(call=call):
                result = chrome_async(self.m, f"const w = {WINDOW};" + call, [url, "private"])
                self.assertEqual(result, {"error": "private-window"})
        # A private tab named from a normal window is not "this window's page" either.
        result = chrome_async(
            self.m, f"const w = {WINDOW}; return await {AI}.assistantAsk('Oi', {private_tab}, window);", [url, "private"]
        )
        self.assertEqual(result, {"error": "page-changed"})
        self.assertEqual(len(self.provider.requests), before)
        self.assertNotIn("PRIVATE", self.sent_since(0))
        # The side panel there explains instead of offering a composer (D-UX6).
        view = self.show_sidebar("private")
        view = self.wait_view(lambda v: v["state"] == "private", "private")
        self.assertTrue(view["private"])
        self.assertFalse(view["composer"])
        text = self.panel("return document.getElementById('private').textContent;", "private")
        self.assertIn("Desligado nesta janela privativa", text)
        self.assertIn("nada do que você digita ou abre aqui vai para um modelo", text)

    def test_09_the_emergency_stop_and_a_pause_silence_the_assistant(self):
        url = self.server.url("/page/Notas")
        self.close_other_tabs()
        self.select_new_tab(url)
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready" and v["offer"])
        self.assertEqual(chrome_async(self.m, f"return await {AI}.setStopped(true);").get("error"), None)
        self.addCleanup(chrome_async, self.m, f"return await {AI}.setStopped(false);")
        before = len(self.provider.requests)
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        self.submit("Qual é a palavra?")
        view = self.wait_view(lambda v: v["state"] == "blocked")
        self.assertEqual(view["blocked"][0], "Parada de emergência ativa")
        self.assertIn("nenhuma pergunta ou página sai daqui", view["blocked"][1])
        self.assertFalse(view["composer"])
        self.assertEqual(view["status"], "A parada de emergência está ativa: o assistente não envia nada.")
        self.assertTrue(self.panel("return !document.getElementById('resume-settings').hidden;"))
        self.assertEqual(len(self.provider.requests), before)  # neither the question nor the page left
        self.assertEqual(
            chrome_async(self.m, f"return await {AI}.assistantAsk('Oi', null, window);"), {"error": "emergency-stop"}
        )
        self.shoot_window("sidebar-stopped")
        # Turned off in Settings: the panel offers the composer again when the user comes back to it.
        chrome_async(self.m, f"return await {AI}.setStopped(false);")
        self.select_tab(self.m.chrome("return gBrowser.tabs[0].linkedBrowser.currentURI.spec;"))
        self.select_tab(url)
        self.wait_view(lambda v: v["state"] == "ready")
        # The assistant's agent paused: the same.
        agent = self.assistant_agent()
        chrome_async(self.m, f"return await {AI}.change(args[0], 'pause', {{paused: true}});", [agent])
        self.addCleanup(chrome_async, self.m, f"return await {AI}.change(args[0], 'pause', {{paused: false}});", [agent])
        self.assertEqual(
            chrome_async(self.m, f"return await {AI}.assistantAsk('Oi', null, window);"), {"error": "assistant-paused"}
        )
        view = self.show_sidebar(reload=True)
        view = self.wait_view(lambda v: v["state"] == "blocked")
        self.assertEqual(view["blocked"][0], "Assistente pausado")
        self.assertEqual(len(self.provider.requests), before)
        self.assertNotIn("Notas", self.sent_since(0))
        chrome_async(self.m, f"return await {AI}.change(args[0], 'pause', {{paused: false}});", [agent])
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")

    def test_10_a_task_never_claims_more_than_it_knows(self):
        self.show_sidebar()
        self.wait_view(lambda v: v["state"] == "ready")
        self.mode("task")
        self.addCleanup(self.mode, "ask")
        local = {
            "id": "c1",
            "type": "function",
            "function": {"name": "tab_new", "arguments": json.dumps({"url": self.server.url("/page/local")})},
        }
        self.provider.replies += [{"choices": [{"message": {"content": None, "tool_calls": [local]}}]}] * 8
        self.submit("Continue tentando")
        view = self.wait_view(lambda v: v["answered"], timeout=120)
        self.assertEqual(
            view["status"],
            "Parou após 8 passos sem concluir. Ações podem ter acontecido na Área de IA antes disso: veja em Atividade.",
        )
        self.assertEqual(view["level"], "error")
        self.assertTrue(view["activity"])
        self.assertNotIn("Nada foi alterado", view["status"])
        # The tools end before an answer (as when the time limit stops them): never "nothing was changed".
        self.provider.delay = 5.0
        self.provider.replies.append({"choices": [{"message": {"content": "Feito."}}]})
        self.submit("Faça devagar")
        self.wait_view(lambda v: v["level"] == "busy")
        busy = self.view()
        self.assertEqual(busy["status"], "Tarefa enviada para 127.0.0.1. O assistente está trabalhando na Área de IA dele…")
        self.assertNotIn("✓", busy["status"])

        def tools():
            for pid in harness.descendants(self.session.process.pid):
                try:
                    if "ai assistant" in harness.proc_info(pid)["cmd"]:
                        return pid
                except OSError:
                    continue
            return None

        pid = harness.wait_until(tools, 10)
        self.assertTrue(pid, "the Nulavio tools for this task")
        os.kill(pid, signal.SIGKILL)
        view = self.wait_view(lambda v: v["level"] == "error")
        self.assertEqual(
            view["status"], "A tarefa parou sem resposta. Ações podem ter acontecido na Área de IA: veja em Atividade."
        )
        self.assertTrue(view["activity"])

    def test_11_a_permission_request_opens_in_front(self):
        # A request nobody sees expires as "no". With background loading on (the engine default for new
        # tabs), the request page still opens in front. Gecko 158+ already does this for trusted links;
        # this pins it.
        self.close_other_tabs()
        request = secrets.token_hex(8)
        body = {
            "id": request, "agent_id": "ag-000000000000", "agent": "Teste", "client": "codex", "autonomy": "restricted",
            "capability": "interact", "label": "Interact with pages", "target": "https://docs.example.org",
            "created": "2026-10-28T10:00:00+00:00", "expires": "2099-01-01T00:00:00+00:00",
        }  # fmt: skip
        written = chrome_async(
            self.m,
            "Services.prefs.setBoolPref('browser.tabs.loadInBackground', true);"
            "const { stateDir } = ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioTools.sys.mjs');"
            "const dir = PathUtils.join(stateDir(), 'ai', 'requests'); await IOUtils.makeDirectory(dir, {createAncestors: true});"
            "await IOUtils.writeJSON(PathUtils.join(dir, args[0] + '.json'), args[1]); return dir;",
            [request, body],
        )
        self.assertIn("ok", written)
        cleanup = (
            "for (const s of ['.json', '.seen']) {"
            " await IOUtils.remove(PathUtils.join(args[1], args[0] + s), {ignoreAbsent: true}); }"
            "Services.prefs.clearUserPref('browser.tabs.loadInBackground'); return true;"
        )
        self.addCleanup(chrome_async, self.m, cleanup, [request, written["ok"]])
        selected = f"return gBrowser.selectedBrowser.currentURI.spec.includes('ai/request.html?id={request}');"
        self.assertTrue(
            harness.wait_until(lambda: self.m.chrome(selected), 20),
            self.m.chrome("return gBrowser.selectedBrowser.currentURI.spec;"),
        )
        self.close_other_tabs()


if __name__ == "__main__":
    unittest.main()
