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
import re
import secrets
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
import settings_page
from fake_llm import FakeProvider, Reply
from fake_keyring import FAKE_SECRET_TOOL

# Type into the address bar with trusted key events, as tests/integration/test_search.py does.
TYPE_JS = """
const [text] = arguments;
const tip = Cc["@mozilla.org/text-input-processor;1"].createInstance(Ci.nsITextInputProcessor);
if (!tip.beginInputTransactionForTests(window)) {
  throw new Error("could not start an input transaction");
}
for (const ch of text) {
  const enter = {key: "Enter", code: "Enter", keyCode: 13};
  const event = ch === "\\n" ? new KeyboardEvent("", enter) : new KeyboardEvent("", {key: ch});
  tip.keydown(event);
  tip.keyup(event);
}
"""
AI = 'ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs").NulavioAI'
TABS = 'ChromeUtils.importESModule("resource://gre/modules/ExtensionParent.sys.mjs").ExtensionParent.apiManager.global.tabTracker'
KEY = "sk-artificial-ui-key-456"
# The Shell's pt-BR texts (the session runs in pt-BR), for messages the panel shows.
MESSAGES = json.loads(
    (Path(__file__).resolve().parents[2] / "browser" / "shell" / "_locales" / "pt_BR" / "messages.json").read_text(
        encoding="utf-8"
    )
)
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
    "const $ = id => document.getElementById(id); const chip = $('chips').querySelector('.assistant__chip');"
    "return { state: document.body.dataset.state, answered: document.body.dataset.answered === 'true',"
    " offer: $('include-page').hidden ? null : $('include-page').textContent,"
    " attached: $('attached').hidden || !chip ? null : chip.querySelector('[data-part=binding]').textContent,"
    " size: chip ? chip.querySelector('[data-part=size]').textContent : null,"
    " heading: $('attached-heading').textContent, remove: chip?.querySelector('button').getAttribute('aria-label') ?? null,"
    " sendLine: $('send-line').textContent,"
    " drift: $('drift').hidden ? null : $('drift-text').textContent, noPage: !$('no-page').hidden,"
    " summarize: !$('summarize').hidden, status: $('status').textContent, level: $('status').dataset.level ?? null,"
    " receipt: $('receipt').textContent, activity: !$('activity-actions').hidden,"
    " blocked: $('blocked').hidden ? null : [$('blocked-title').textContent, $('blocked-text').textContent],"
    " private: !$('private').hidden, composer: !$('ask').hidden };"
)

# Include a tab ({tabId, url}) in this window's next message, as "Incluir esta página" does.
INCLUDE = f"const w = {WINDOW}; return await {AI}.assistantInclude({{kind: 'page', ...args[0]}}, w);"
# Ask as the panel does: the items by id, and what the panel would show (recipient, model, whole size).
ASK = (
    f"const ai = {AI}; const w = {WINDOW}; const [question, ids] = args; const st = await ai.assistantState(w);"
    "let chips = []; try { chips = ai.assistantChips(w).filter(c => ids.includes(c.chipId)); } catch {}"
    "const chars = st.systemChars + chips.reduce((n, c) => n + c.blockChars, 0) + (chips.length ? 10 : 0)"
    " + [...question].length;"
    "return await ai.assistantAsk(question, {chips: ids, expected: {recipient: st.recipient, model: st.provider?.model ?? '',"
    " chars}}, w);"
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
        # Each test starts a new conversation (UX5-D keeps one per window, in memory).
        try:
            self.panel("document.getElementById('new-thread').click();")
        except AssertionError:
            chrome_async(self.m, f"return {AI}.assistantThreadClear(window);")

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
        """The browser window and its side panel follow the same real colour scheme."""
        previous = self.m.chrome(
            "return [Services.prefs.prefHasUserValue('ui.systemUsesDarkTheme'),"
            " Services.prefs.getIntPref('ui.systemUsesDarkTheme', 0)];"
        )
        try:
            for scheme in ("light", "dark"):
                dark = scheme == "dark"
                self.m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [int(dark)])
                self.assertTrue(
                    harness.wait_until(
                        lambda want=dark: (
                            self.panel("return content.matchMedia('(prefers-color-scheme: dark)').matches;") == want
                        ),
                        10,
                    )
                )
                time.sleep(0.3)
                self.m.set_context("chrome")
                try:
                    (self.shots / f"{name}-{scheme}.png").write_bytes(self.m.screenshot_png())
                finally:
                    self.m.set_context("content")
        finally:
            self.m.chrome(
                "if (arguments[0]) Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[1]);"
                " else Services.prefs.clearUserPref('ui.systemUsesDarkTheme');",
                previous,
            )

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

        def ready():
            try:
                return self.panel("return document.documentElement.dataset.ready === 'true';", which)
            except AssertionError:
                return False  # the panel's browser is still being created

        self.assertTrue(harness.wait_until(ready, 20))
        if reload:
            self.panel("delete document.documentElement.dataset.ready; content.location.reload();", which)
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

    def type(self, text: str) -> None:
        """Write in the question field as a person would (the send line follows the input events)."""
        self.panel(
            "const p = document.getElementById('prompt'); p.value = " + json.dumps(text) + ";"
            " p.dispatchEvent(new Event('input', {bubbles: true}));"
        )

    @staticmethod
    def shown_chars(line: str) -> int:
        """The number of characters a send line shows (pt-BR digits, '.' between thousands)."""
        found = re.search(r"· ([\d.]+) caracteres", line)
        assert found, line
        return int(found.group(1).replace(".", ""))

    def recipient(self) -> str:
        """Where the assistant sends, as the panel names it: host and port."""
        return self.provider.base.split("/")[2]

    def assistant_agent(self) -> str:
        return chrome_async(self.m, f"return (await {AI}.assistantState(window)).agent.id;")["ok"]

    # -- settings and the module ------------------------------------------------------------

    def test_01_settings_store_the_key_in_the_keyring_only(self):
        # ADR 0011, step 10: the assistant's service is set in the settings page.
        settings_page.open_pane(self.m, settings_page.assistant_pane(self.m))
        settings_page.wait_control(self.m, "nulavio-assistant-kind")
        settings_page.change(self.m, "nulavio-assistant-kind", "openai")
        settings_page.change(self.m, "nulavio-assistant-url", self.provider.base)
        settings_page.change(self.m, "nulavio-assistant-model", "test-model")
        settings_page.change(self.m, "nulavio-assistant-key", KEY)
        settings_page.click(self.m, "#nulavio-assistant-save")
        saved = lambda now: "test-model" in (now["description"] or "")  # noqa: E731
        status = settings_page.wait_control(self.m, "nulavio-assistant-now", saved, timeout=20)["description"]
        self.assertIn("127.0.0.1", status)
        self.assertIn("chaveiro", status)
        self.assertEqual(settings_page.control(self.m, "nulavio-assistant-key")["value"], "")
        # Whether this profile may send anything to it is its own switch, saved when it changes.
        settings_page.wait_control(self.m, "nulavio-assistant-allowed", lambda now: now["shown"] and not now["disabled"])
        settings_page.click(self.m, "#nulavio-assistant-allowed")
        allowed = lambda: chrome_async(self.m, f"return (await {AI}.assistantState(window)).profileAllowed;")["ok"]  # noqa: E731
        self.assertTrue(harness.wait_until(allowed, 10), "the profile was not allowed to use the assistant")
        stored = json.loads(self.keyring.read_text())
        self.assertEqual([base64.b64decode(i["secret"]).decode() for i in stored], [KEY])  # in the (stand-in) keyring
        for path in self.session.profile_dir.rglob("*"):
            if path.is_file() and path.stat().st_size < 20_000_000:
                self.assertNotIn(KEY.encode(), path.read_bytes(), f"key found in {path}")
        settings_page.shoot(self.m, self.shots, "settings")

    def test_02_page_text_goes_only_for_the_included_tab(self):
        url = self.server.url("/agent-task?word=OBSIDIAN")
        self.m.navigate(url)
        page = chrome_async(self.m, f"return {AI}.assistantPage(window);")["ok"]
        self.assertEqual((page["url"], page["title"]), (url, "agent-task"))
        self.assertIsInstance(page["tabId"], int)
        binding = {"tabId": page["tabId"], "url": page["url"]}
        before = self.provider.count
        self.assertEqual(chrome_async(self.m, ASK, ["Qual é a palavra?", []])["ok"]["pageChars"], 0)
        self.assertNotIn("OBSIDIAN", self.sent_since(before))
        # Including reads the page now and keeps it in the browser (UX5-B): the panel gets its size, not its text.
        before = self.provider.count
        chip = chrome_async(self.m, INCLUDE, [binding])["ok"]
        self.assertEqual(
            (chip["kind"], chip["title"], chip["host"], chip["truncated"]), ("page", "agent-task", url.split("/")[2], False)
        )
        self.assertNotIn("text", chip)
        self.assertGreater(chip["chars"], 0)
        self.assertEqual(self.provider.count, before)  # including sends nothing
        result = chrome_async(self.m, ASK, ["Qual é a palavra?", [chip["chipId"]]])
        self.assertEqual(result["ok"]["pageChars"], chip["chars"])
        self.assertEqual(result["ok"]["chars"], self.provider.chars[-1])  # the size the panel computed is what went
        sent = self.sent_since(before)
        self.assertIn("OBSIDIAN", sent)  # the visible text, extracted by the engine
        self.assertIn("untrusted", sent)
        self.assertEqual(self.provider.requests[-1][1]["authorization"], f"Bearer {KEY}")
        # Consent is per message: the item went with that one and is gone from the browser.
        self.assertEqual(chrome_async(self.m, f"return {AI}.assistantChips(window);")["ok"], [])
        self.assertEqual(chrome_async(self.m, ASK, ["De novo", [chip["chipId"]]]), {"error": "page-changed"})
        # Bound to that tab: another selected tab is never read in its place.
        chip = chrome_async(self.m, INCLUDE, [binding])["ok"]
        other = self.server.url("/agent-task?word=QUARTZ")
        self.select_new_tab(other)
        before = self.provider.count
        self.assertGreater(chrome_async(self.m, ASK, ["Qual é a palavra?", [chip["chipId"]]])["ok"]["pageChars"], 0)
        self.assertIn("OBSIDIAN", self.sent_since(before))
        self.assertNotIn("QUARTZ", self.sent_since(before))
        self.close_other_tabs()
        # That tab went to another address: refused, nothing sent (the consent was for the page before).
        chip = chrome_async(self.m, INCLUDE, [binding])["ok"]
        moved = self.server.url("/agent-task?word=JASPER")
        self.m.navigate(moved)
        before = self.provider.count
        self.assertEqual(chrome_async(self.m, ASK, ["Qual é a palavra?", [chip["chipId"]]]), {"error": "page-changed"})
        for stale in ({"tabId": page["tabId"], "url": url}, {"tabId": page["tabId"], "url": moved + "#more"},
                      {"tabId": 999999, "url": moved}):  # fmt: skip
            self.assertEqual(chrome_async(self.m, INCLUDE, [stale]), {"error": "page-changed"})
        self.assertEqual(self.provider.count, before)
        # Without a window around the caller, the assistant does nothing.
        self.assertEqual(chrome_async(self.m, f"return await {AI}.assistantAsk('Oi', null, null);"), {"error": "no-window"})
        self.assertEqual(chrome_async(self.m, f"return await {AI}.assistantTask('Oi', null, null);"), {"error": "no-window"})
        self.assertEqual(
            chrome_async(self.m, f"return await {AI}.assistantInclude({{kind: 'page'}}, null);"), {"error": "no-window"}
        )
        # The panel's line must match: an Ask whose size differs is refused before anything goes.
        st = chrome_async(self.m, f"return await {AI}.assistantState(window);")["ok"]
        wrong = {"recipient": st["recipient"], "model": st["provider"]["model"], "chars": 1}
        refused = chrome_async(
            self.m, f"return await {AI}.assistantAsk('Oi', {{chips: [], expected: args[0]}}, window);", [wrong]
        )
        self.assertEqual(refused, {"error": "size-changed"})
        self.assertEqual(
            chrome_async(self.m, f"return await {AI}.assistantAsk('Oi', {{chips: []}}, window);"), {"error": "bad-request"}
        )
        self.assertEqual(self.provider.count, before)

    def test_02b_a_long_page_is_cut_before_send_and_the_cut_is_what_goes(self):
        """UX5-B: 70 000 characters show "Página longa…" on the item before Send; exactly 60 000 go. A page
        far above the 512 KiB request limit is cut the same way, not refused."""
        for n in (70_000, 700_000):
            with self.subTest(n=n):
                url = self.server.url(f"/long-page?n={n}")
                self.m.navigate(url)
                page = chrome_async(self.m, f"return {AI}.assistantPage(window);")["ok"]
                chip = chrome_async(self.m, INCLUDE, [{"tabId": page["tabId"], "url": url}])["ok"]
                self.assertEqual((chip["chars"], chip["truncated"]), (60_000, True))
                before = self.provider.count
                result = chrome_async(self.m, ASK, ["Resuma", [chip["chipId"]]])["ok"]
                self.assertEqual(result["pageChars"], 60_000)
                body = self.provider.requests[-1][2]
                text = body["messages"][-1]["content"]
                inside = text.split("<<<PAGE\n", 1)[1].rsplit("\nPAGE>>>", 1)[0]
                self.assertEqual(len(inside), 60_000)  # code points, as counted
                self.assertEqual(self.provider.count, before + 1)
                self.assertEqual(result["chars"], self.provider.chars[-1])

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
            "return [s.dataset.level, s.textContent, getComputedStyle(s, '::before').maskImage];"
        )
        busy = harness.wait_until(lambda: (lambda v: v if v[0] == "progress" else None)(self.m.execute(status)), 10)
        self.assertTrue(busy, self.m.execute(status))
        self.assertEqual(busy[1], f"Enviado para {self.recipient()}. Aguardando a resposta…")
        self.assertNotIn("icon-check.svg", busy[2])  # a progress mark, never a check mark while waiting
        self.assertTrue(harness.wait_until(lambda: self.m.execute("return document.body.dataset.answered === 'true';"), 20))
        level, text, mark = self.m.execute(status)
        self.assertEqual((level, text), ("ok", "Resposta pronta."))
        self.assertIn("icon-check.svg", mark)  # done: the check, drawn as an SVG mask
        answer = self.m.execute(
            "const a = document.getElementById('answer'), s = document.getElementById('answer-section');"
            "const h = document.getElementById(s.getAttribute('aria-labelledby'));"
            "return [a.textContent, [...a.querySelectorAll('*')].map(e => e.localName).join(','), a.hasAttribute('aria-live'),"
            " h.tagName, h.textContent, document.getElementById('receipt').textContent];"
        )
        total = self.provider.chars[-1]
        receipt = f"Só a pergunta foi enviada para {self.recipient()}: {total} caracteres no total, com as instruções do Nulavio."
        # HTML in an answer is text (UX5-E): one paragraph, the <b> shown as written.
        self.assertEqual(answer, ["<b>Resposta</b> em texto", "p", False, "H2", "Resposta", receipt])
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
        result = chrome_async(self.m, f"return await {AI}.assistantTask('Abra a página local', null, window);")["ok"]
        self.assertEqual(
            result["steps"], [{"tool": "tab_new", "error": True, "state": "denied"}]
        )  # restricted: no local addresses
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
        # The side panel's header names it already; the page title stays for screen readers (R4 visual note).
        self.assertTrue(
            harness.wait_until(
                lambda: self.panel("return document.getElementById('title').classList.contains('visually-hidden');"), 10
            )
        )
        # AI-01: the panel in the sidebar finds the page in its window (Gecko 158+ renamed ownerGlobal).
        view = self.wait_view(lambda v: v["offer"])
        self.assertEqual(view["offer"], "+ Incluir esta página: Artigo")
        self.assertTrue(view["summarize"])
        self.assertFalse(view["noPage"])
        self.assertIsNone(view["attached"])  # nothing is included until the user says so
        # Including binds this tab and reads it now; the item says which tab and how much (UX5-B).
        before = self.provider.count
        self.panel("document.getElementById('include-page').click();")
        view = self.wait_view(lambda v: v["attached"])
        self.assertEqual(self.provider.count, before)  # nothing leaves before Send
        self.assertEqual(view["attached"], f"só da aba “Artigo” · {host}")
        self.assertRegex(view["size"], r"^\d+ caracteres$")
        self.assertEqual(view["heading"], f"Vai junto com a próxima mensagem, para {self.recipient()}")
        self.assertEqual(view["remove"], "Remover a página “Artigo” da mensagem")
        self.assertIsNone(view["offer"])
        # The line above Send: where it goes and the whole size, which is what the provider then gets.
        self.type("Do que trata a página?")
        line = self.view()["sendLine"]
        self.assertTrue(line.startswith(f"Vai para {self.recipient()} · test-model · "), line)
        self.shoot_window("sidebar-attached")
        self.submit("Do que trata a página?")
        view = self.wait_view(lambda v: v["answered"])
        self.assertEqual(self.shown_chars(line), self.provider.chars[-1])
        self.assertIn("<<<PAGE", self.sent_since(before))
        self.assertIn("Artigo", self.sent_since(before))
        self.assertRegex(
            view["receipt"],
            rf"^\d+ caracteres desta página foram enviados para {re.escape(self.recipient())}, [\d.]+ no total\.$",
        )
        # Consent is per message: the item left with the message. The conversation keeps the copy that went,
        # for the same recipient, and says so (Q1); a new conversation goes without it.
        self.assertIsNone(view["attached"])
        self.assertEqual(view["offer"], "+ Incluir esta página: Artigo")
        self.assertIn("com a página “Artigo”", self.panel("return document.getElementById('thread-line').textContent;"))
        self.panel("document.getElementById('new-thread').click();")
        before = self.provider.count
        self.type("E depois?")
        line = self.view()["sendLine"]
        self.submit("E depois?")
        view = self.wait_view(lambda v: v["answered"] and v["receipt"].startswith("Só a pergunta"))
        self.assertEqual(self.shown_chars(line), self.provider.chars[-1])  # the question alone, too
        self.assertNotIn("<<<PAGE", self.sent_since(before))
        # The remove control takes it out before Send.
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        self.panel("document.querySelector('#chips button').click();")
        view = self.wait_view(lambda v: not v["attached"] and v["offer"])
        self.assertTrue(self.panel("return document.activeElement.id === 'include-page';"))
        self.assertEqual(chrome_async(self.m, f"return {AI}.assistantChips(window);")["ok"], [])  # gone from the browser too
        before = self.provider.count
        self.submit("Sem a página?")
        # The receipt names the conversation that went with it, and no page (review UX5-D/G F2).
        self.wait_view(lambda v: v["answered"] and self.provider.count > before and "página" not in v["receipt"])
        self.assertNotIn("<<<PAGE", self.sent_since(before))
        # Summarise includes this page and writes the request; Send stays with the person (Q5).
        before = self.provider.count
        self.panel("document.getElementById('summarize').click();")
        view = self.wait_view(lambda v: v["attached"])
        self.assertEqual(self.panel("return [document.getElementById('prompt').value, document.activeElement.id];"),
                         ["Resuma esta página em poucos pontos curtos.", "send"])  # fmt: skip
        time.sleep(0.5)
        self.assertEqual(self.provider.count, before)
        self.panel("document.getElementById('ask').requestSubmit();")
        view = self.wait_view(lambda v: v["answered"] and "desta página" in v["receipt"])
        self.assertIn("<<<PAGE", self.sent_since(before))
        self.assertIsNone(view["attached"])
        self.panel("document.getElementById('new-thread').click();")
        before = self.provider.count
        self.submit("E mais?")
        self.wait_view(lambda v: v["answered"] and v["receipt"].startswith("Só a pergunta"))
        self.assertNotIn("<<<PAGE", self.sent_since(before))

    def test_06b_a_provider_changed_in_settings_is_refused_at_send(self):
        """UX5-B: the panel shows one recipient; Settings change it meanwhile: Send sends nothing and says so."""
        url = self.server.url("/page/Destino")
        self.select_new_tab(url)
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["offer"])
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        other = FakeProvider()
        restore = {"kind": "openai", "baseUrl": self.provider.base, "model": "test-model"}
        try:
            changed = chrome_async(
                self.m, f"return await {AI}.assistantConfigure(args[0]);", [{**restore, "baseUrl": other.base}]
            )
            self.assertNotIn("error", changed)
            before = (self.provider.count, other.count)
            self.submit("Para onde vai?")
            view = self.wait_view(lambda v: v["level"] == "error")
            self.assertEqual(view["status"], MESSAGES["err_recipient_changed"]["message"])
            self.assertEqual((self.provider.count, other.count), before)  # nothing went anywhere
            self.assertIsNone(view["attached"])  # the page has to be included again, for the new recipient
            self.wait_view(lambda v: other.base.split("/")[2] in v["sendLine"])  # the line names the new one now
        finally:
            chrome_async(self.m, f"return await {AI}.assistantConfigure(args[0]);", [restore])
            other.close()
            self.show_sidebar(reload=True)  # the panel shows the restored provider again
            self.close_other_tabs()

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
        self.assertEqual(view["status"], view["drift"])  # said once to a screen reader as well (UX5-B)
        self.assertIsNone(view["attached"])
        self.assertTrue(harness.wait_until(lambda: chrome_async(self.m, f"return {AI}.assistantChips(window);")["ok"] == [], 10))
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

    def test_07b_a_pending_include_cannot_attach_to_the_next_message(self):
        self.select_new_tab(self.server.url("/page/Consentimento"))
        for control in ("include-page", "summarize"):
            with self.subTest(control=control):
                self.show_sidebar(reload=True)
                self.wait_view(lambda v: v["offer"] and "Consentimento" in v["offer"])
                # Hold the reply at the experiment boundary, after it captured the requested tab.
                self.m.chrome(
                    f"const ai = {AI}; const original = ai.assistantPage;"
                    "ai.assistantPage = function(win) { this.assistantPage = original;"
                    " const page = original.call(this, win);"
                    " return new Promise(resolve => { this.testReleasePage = () => {"
                    " resolve(page); delete this.testReleasePage; }; }); };"
                )
                self.addCleanup(self.m.chrome, f"{AI}.testReleasePage?.();")
                self.panel(f"document.getElementById('{control}').click();")
                self.assertTrue(harness.wait_until(lambda: self.m.chrome(f"return !!{AI}.testReleasePage;"), 10))
                self.provider.delay = 1.0
                before = len(self.provider.requests)
                self.submit("Envie só esta pergunta")
                self.wait_view(lambda v: v["level"] == "progress")
                self.m.chrome(f"{AI}.testReleasePage();")
                view = self.wait_view(lambda v: v["answered"])
                self.assertIsNone(view["attached"])
                self.assertEqual(len(self.provider.requests) - before, 1)
                self.assertNotIn("<<<PAGE", self.sent_since(before))
                again = len(self.provider.requests)
                self.submit("E a próxima também")
                self.wait_view(
                    lambda v, n=again: v["answered"] and len(self.provider.requests) > n and "página" not in v["receipt"]
                )
                self.assertNotIn("<<<PAGE", self.sent_since(before))

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
        private_tab = f"{{kind: 'page', tabId: {TABS}.getId(w.gBrowser.selectedTab), url: args[0]}}"
        for call in (
            f"return {AI}.assistantPage(w);",
            f"return await {AI}.assistantInclude({private_tab}, w);",
            f"return {AI}.assistantChips(w);",
            f"return await {AI}.assistantAsk('Oi', {{chips: []}}, w);",
            f"return await {AI}.assistantTask('Abra algo', null, w);",
            f"return await {AI}.assistantStart('task', {{task: 'Abra algo'}}, w);",
        ):
            with self.subTest(call=call):
                result = chrome_async(self.m, f"const w = {WINDOW};" + call, [url, "private"])
                self.assertEqual(result, {"error": "private-window"})
        # A private tab named from a normal window is not "this window's page" either.
        result = chrome_async(
            self.m, f"const w = {WINDOW}; return await {AI}.assistantInclude({private_tab}, window);", [url, "private"]
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
        self.assertEqual(chrome_async(self.m, ASK, ["Oi", []]), {"error": "emergency-stop"})
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
        self.assertEqual(chrome_async(self.m, ASK, ["Oi", []]), {"error": "assistant-paused"})
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
        self.wait_view(lambda v: v["level"] == "progress")
        busy = self.view()
        self.assertEqual(
            busy["status"], f"Tarefa enviada para {self.recipient()}. O assistente está trabalhando na Área de IA dele…"
        )
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

    def test_12_errors_by_cause_and_a_cut_answer(self):
        """AI-08 / AI-09 (UX5-A): a 429 and a 401 read differently, the 429 never sends the person to the
        key, each Send makes one request, and an answer the provider's limit cut says so."""
        self.open("assistant/panel.html")
        msg = lambda key: self.m.execute("return browser.i18n.getMessage(arguments[0]);", [key])  # noqa: E731
        status = "const s = document.getElementById('status'); return [s.dataset.level, s.textContent];"

        def ask_and_wait(reply) -> list:
            before = self.provider.count
            self.provider.replies.append(reply)
            self.m.execute("document.getElementById('status').textContent = '';")
            self.m.execute(
                "const p = document.getElementById('prompt'); p.value = 'Olá?'; document.getElementById('ask').requestSubmit();"
            )
            done = harness.wait_until(
                lambda: (lambda v: v if v[0] in ("ok", "error") and v[1] else None)(self.m.execute(status)), 20
            )
            self.assertTrue(done, self.m.execute(status))
            self.assertEqual(self.provider.count, before + 1)  # one click, one request: no retry behind the person
            return done

        limited = ask_and_wait(Reply(status=429, headers={"Retry-After": "30"}))
        self.assertEqual(limited, ["error", msg("err_provider_rate_limited")])
        refused = ask_and_wait(Reply(status=401))
        self.assertEqual(refused, ["error", msg("err_provider_auth")])
        self.assertNotEqual(limited[1], refused[1])
        self.assertNotIn("chave", limited[1])
        self.assertIn("chave", refused[1])
        for reply in (
            {"choices": [{"message": {"content": "Metade da"}, "finish_reason": "length"}]},
            Reply(chunks=["Metade da"], stop="length"),
        ):
            self.assertEqual(ask_and_wait(reply)[0], "ok")
            cut = self.m.execute(
                "const c = document.getElementById('truncated');"
                "return [c.hidden, c.querySelector('p').textContent, !!c.querySelector('svg[data-icon=warning]')];"
            )
            self.assertEqual(cut, [False, msg("assistantTruncated"), True])
        self.shoot("answer-cut")
        # "Continuar" writes the next turn and leaves Send to the person (Q14).
        before = self.provider.count
        self.m.execute("document.getElementById('continue').click();")
        self.assertEqual(self.m.execute("return [document.getElementById('prompt').value, document.activeElement.id];"),
                         [msg("assistantContinuePrompt"), "send"])  # fmt: skip
        self.assertEqual(self.provider.count, before)
        self.assertEqual(ask_and_wait({"choices": [{"message": {"content": "Inteira."}}]})[0], "ok")
        self.assertTrue(self.m.execute("return document.getElementById('truncated').hidden;"))

    # -- stream and stop (UX5-C2) ----------------------------------------------------------------

    def tools_process(self):
        for pid in harness.descendants(self.session.process.pid):
            try:
                if "ai assistant" in harness.proc_info(pid)["cmd"]:
                    return pid
            except OSError:
                continue
        return None

    def answer_text(self) -> str:
        return self.panel("return document.getElementById('answer').textContent;")

    def test_13_the_answer_arrives_in_pieces(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.provider.replies.append({"choices": [{"message": {"content": "Antes."}}]})
        self.ask_panel("Uma antes?")
        self.assertTrue(self.view()["receipt"])
        pieces = ["Primeiro ", "segundo ", "terceiro ", "quarto ", "quinto ", "fim."]
        self.provider.replies.append(Reply(chunks=pieces, chunk_delay=0.5))
        self.submit("Conte devagar")
        self.assertTrue(harness.wait_until(lambda: self.answer_text(), 20))
        self.assertEqual(self.view()["receipt"], "")  # the receipt before never stands under this answer
        lengths = []
        seen_cursor = False
        while not self.view()["answered"]:
            text = self.answer_text()
            if text and (not lengths or lengths[-1] != len(text)):
                lengths.append(len(text))
                seen_cursor = seen_cursor or self.panel("return !!document.querySelector('#answer .assistant__cursor');")
            time.sleep(0.1)
        final = "".join(pieces)
        self.assertGreaterEqual(len([n for n in lengths if n < len(final)]), 2, lengths)  # pieces shown on the way
        self.assertEqual(self.answer_text(), final)
        self.assertTrue(seen_cursor)
        self.assertFalse(self.panel("return !!document.querySelector('#answer .assistant__cursor');"))
        self.assertFalse(self.panel("return document.getElementById('answer').hasAttribute('aria-live');"))
        self.assertEqual(self.view()["status"], "Resposta pronta.")
        self.assertTrue(self.provider.requests[-1][2]["stream"])

    def test_14_stop_and_esc_end_an_answer_and_say_what_may_have_left(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        for how in ("button", "escape"):
            with self.subTest(how=how):
                self.provider.replies.append(Reply(chunks=[f"parte {i} " for i in range(20)], chunk_delay=0.4))
                before = self.provider.count
                self.submit("Fale bastante")
                self.assertTrue(harness.wait_until(lambda: self.answer_text(), 20))
                self.assertEqual(self.panel("return document.getElementById('send').textContent;"), "Parar")
                if how == "button":
                    self.panel("document.getElementById('send').click();")
                else:
                    # An event of the page's own realm, as a key press would be (one made in the frame script is not
                    # seen by the page's listeners).
                    self.panel(
                        "const target = document.activeElement ?? document;"
                        "target.dispatchEvent(new content.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));"
                    )
                stopped = time.monotonic()
                view = self.wait_view(lambda v: v["answered"])
                self.assertEqual(
                    view["status"], f"Resposta interrompida por você. A pergunta pode já ter chegado a {self.recipient()}."
                )
                self.assertEqual(self.panel("return document.getElementById('interrupted').hidden;"), False)
                self.assertTrue(self.answer_text().startswith("parte 0"))  # what came stays
                self.assertNotIn("parte 19", self.answer_text())
                self.assertTrue(harness.wait_until(lambda: self.tools_process() is None, 5))
                self.assertLess(time.monotonic() - stopped, 5)
                self.assertEqual(self.provider.count, before + 1)  # no request after "Parar"
                self.assertEqual(self.panel("return document.getElementById('send').textContent;"), "Enviar")

    def test_15_the_emergency_stop_cuts_an_answer_at_once(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.provider.replies.append(Reply(chunks=[f"parte {i} " for i in range(20)], chunk_delay=0.4))
        self.submit("Fale bastante")
        self.assertTrue(harness.wait_until(lambda: self.answer_text(), 20))
        self.addCleanup(chrome_async, self.m, f"return await {AI}.setStopped(false);")
        chrome_async(self.m, f"return await {AI}.setStopped(true);")
        view = self.wait_view(lambda v: v["state"] == "blocked", timeout=10)
        self.assertIn(MESSAGES["err_emergency_stop"]["message"], view["status"])
        self.assertTrue(harness.wait_until(lambda: self.tools_process() is None, 5))
        chrome_async(self.m, f"return await {AI}.setStopped(false);")
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")

    def test_16_a_stopped_task_waiting_for_permission_ends_and_its_request_goes(self):
        self.close_other_tabs()
        agent = self.assistant_agent()
        chrome_async(self.m, f"return await {AI}.change(args[0], 'grant', {{capability: 'navigate', mode: 'ask'}});", [agent])
        self.addCleanup(
            chrome_async, self.m, f"return await {AI}.change(args[0], 'clear-grant', {{capability: 'navigate'}});", [agent]
        )
        call = {"id": "c1", "type": "function",
                "function": {"name": "tab_new", "arguments": json.dumps({"url": "https://example.invalid/"})}}  # fmt: skip
        self.provider.replies.append({"choices": [{"message": {"content": None, "tool_calls": [call]}}]})
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.mode("task")
        self.addCleanup(self.mode, "ask")
        before = self.provider.count
        self.submit("Abra um site")
        requests = Path(self.session.env["HOME"]) / ".local" / "state" / "nulavio" / "ai" / "requests"
        self.assertTrue(harness.wait_until(lambda: list(requests.glob("*.json")), 30))
        self.panel("document.getElementById('send').click();")
        view = self.wait_view(lambda v: v["answered"], timeout=40)
        self.assertEqual(
            view["status"], "Tarefa parada por você. Ações podem ter acontecido na Área de IA antes disso: veja em Atividade."
        )
        self.assertTrue(view["activity"])
        self.assertEqual(list(requests.glob("*.json")), [])  # the request page can no longer answer for it
        self.assertEqual(self.provider.count, before + 1)  # no next model turn
        self.assertTrue(harness.wait_until(lambda: self.tools_process() is None, 25))
        self.close_other_tabs()

    def test_17_no_line_for_too_long_ends_the_run(self):
        self.close_other_tabs()
        self.m.chrome("Services.prefs.setIntPref('nulavio.assistant.idle_ms', 2000);")
        self.addCleanup(self.m.chrome, "Services.prefs.clearUserPref('nulavio.assistant.idle_ms');")
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.provider.replies.append(Reply(hang=True))
        self.submit("Oi?")
        view = self.wait_view(lambda v: v["level"] == "error", timeout=15)
        self.assertEqual(view["status"], MESSAGES["err_timeout"]["message"])
        self.assertTrue(harness.wait_until(lambda: self.tools_process() is None, 5))

    # -- the conversation (UX5-D) -----------------------------------------------------------------

    def thread_view(self) -> dict:
        return self.panel(
            "const $ = id => document.getElementById(id);"
            "return { line: $('thread-line').textContent, turns: $('thread').children.length, shown: !$('thread-section').hidden,"
            " leave: !$('leave-page').hidden, moved: $('thread-moved').hidden ? null : $('thread-moved-text').textContent,"
            " large: $('too-large').hidden ? null : $('too-large-text').textContent, send: $('send').disabled,"
            " retry: $('retry-actions').hidden ? null : $('retry-hint').textContent, empty: !$('thread-empty').hidden };"
        )

    def user_turns(self) -> list[dict]:
        return [m for m in self.provider.requests[-1][2]["messages"] if m["role"] != "system"]

    def ask_panel(self, text: str) -> dict:
        self.type(text)
        line = self.view()["sendLine"]
        before = self.provider.count
        self.submit(text)
        view = self.wait_view(lambda v: v["answered"] and self.provider.count > before)
        self.assertEqual(self.shown_chars(line), self.provider.chars[-1])  # the line counted the conversation too
        return view

    def test_18_a_conversation_carries_its_turns_and_the_page_copy(self):
        url = self.server.url("/page/Conversa")
        self.close_other_tabs()
        self.select_new_tab(url)
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["offer"])
        self.panel("document.getElementById('new-thread').click();")
        self.assertTrue(harness.wait_until(lambda: self.thread_view()["empty"], 10))
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        self.provider.replies += [{"choices": [{"message": {"content": f"Resposta {i}."}}]} for i in (1, 2, 3, 4, 5)]
        self.ask_panel("PERGUNTA-UM sobre a página?")
        self.ask_panel("PERGUNTA-DOIS?")
        thread = self.thread_view()
        self.assertEqual(thread["line"], "Conversa: 2 respostas vão junto com a próxima pergunta, com a página “Conversa”")
        self.assertEqual(thread["turns"], 1)  # the latest is the answer below
        self.ask_panel("PERGUNTA-TRES?")
        turns = self.user_turns()
        self.assertEqual([m["role"] for m in turns], ["user", "assistant", "user", "assistant", "user"])
        self.assertIn("<<<PAGE", turns[0]["content"])  # the copy that went, to the same recipient (Q1)
        self.assertEqual((turns[1]["content"], turns[3]["content"]), ("Resposta 1.", "Resposta 2."))
        self.shoot_window("sidebar-thread")
        # The panel closes and opens again: the conversation is still there (Q16).
        self.show_sidebar(reload=True)
        self.assertTrue(harness.wait_until(lambda: self.thread_view()["turns"] == 3, 10))
        # "Deixar a página de fora": from now on the page copy stays here.
        self.panel("document.getElementById('leave-page').click();")
        self.assertTrue(harness.wait_until(lambda: not self.thread_view()["leave"], 10))
        self.ask_panel("PERGUNTA-QUATRO?")
        self.assertNotIn("<<<PAGE", json.dumps(self.provider.requests[-1][2]))
        self.assertEqual(len(self.user_turns()), 7)
        # Nothing of it is written to the profile or the state directory.
        for root in (self.session.profile_dir, Path(self.session.env["HOME"]) / ".local" / "state"):
            for path in root.rglob("*"):
                if path.is_file() and path.stat().st_size < 20_000_000:
                    self.assertNotIn(b"PERGUNTA-DOIS", path.read_bytes(), f"the conversation is in {path}")
        # "Começar conversa nova": nothing from before goes.
        self.panel("document.getElementById('new-thread').click();")
        self.assertTrue(harness.wait_until(lambda: not self.thread_view()["shown"], 10))
        self.ask_panel("PERGUNTA-CINCO?")
        self.assertEqual(len(self.user_turns()), 1)
        self.close_other_tabs()

    def test_19_try_again_sends_what_it_says_and_the_limit_stops_send(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.panel("document.getElementById('new-thread').click();")
        self.provider.replies += [{"choices": [{"message": {"content": "Primeira."}}]}, Reply(status=503)]
        self.ask_panel("Uma pergunta?")
        self.submit("Outra pergunta?")
        self.wait_view(lambda v: v["level"] == "error")
        self.assertTrue(harness.wait_until(lambda: self.thread_view()["retry"], 10))  # after the error is shown
        hint = self.thread_view()["retry"]
        announced = int(re.search(r"Reenvia ([\d.]+) caracteres", hint).group(1).replace(".", ""))
        self.provider.replies.append({"choices": [{"message": {"content": "Agora sim."}}]})
        before = self.provider.count
        self.panel("document.getElementById('retry').click();")
        self.wait_view(lambda v: v["answered"] and self.provider.count == before + 1)
        self.assertEqual(self.provider.chars[-1], announced)  # exactly what it said (Q17)
        self.assertEqual(self.user_turns()[-1]["content"], "Outra pergunta?")
        self.assertEqual(self.answer_text(), "Agora sim.")
        # A conversation above 200 000 characters: Send waits for a choice, and nothing goes.
        self.provider.replies.append({"choices": [{"message": {"content": "x" * 199_900}}]})
        self.ask_panel("Longa?")
        self.type("E agora?")
        thread = self.thread_view()
        self.assertTrue(thread["large"] and thread["send"], thread)
        before = self.provider.count
        self.panel("document.getElementById('ask').requestSubmit();")
        time.sleep(0.5)
        self.assertEqual(self.provider.count, before)
        self.panel("document.getElementById('large-new').click();")
        self.assertTrue(harness.wait_until(lambda: not self.thread_view()["large"] and not self.thread_view()["send"], 10))

    def test_20_another_recipient_does_not_get_the_conversation_unless_chosen(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.panel("document.getElementById('new-thread').click();")
        self.provider.replies.append({"choices": [{"message": {"content": "Com o primeiro."}}]})
        self.ask_panel("SEGREDO-DA-CONVERSA?")
        other = FakeProvider()
        restore = {"kind": "openai", "baseUrl": self.provider.base, "model": "test-model"}
        try:
            chrome_async(self.m, f"return await {AI}.assistantConfigure(args[0]);", [{**restore, "baseUrl": other.base}])
            self.show_sidebar(reload=True)
            moved = harness.wait_until(lambda: self.thread_view()["moved"], 10)
            self.assertIn(other.base.split("/")[2], moved)
            self.assertTrue(self.thread_view()["send"])  # Send waits for the choice
            self.panel("document.getElementById('moved-carry').click();")
            self.assertTrue(harness.wait_until(lambda: not self.thread_view()["moved"], 10))
            other.replies.append({"choices": [{"message": {"content": "Com o segundo."}}]})
            self.type("Continua?")
            self.submit("Continua?")
            self.wait_view(lambda v: v["answered"] and other.count == 1)
            sent = [m for m in other.requests[-1][2]["messages"] if m["role"] != "system"]
            self.assertEqual([m["content"] for m in sent], ["SEGREDO-DA-CONVERSA?", "Com o primeiro.", "Continua?"])
        finally:
            chrome_async(self.m, f"return await {AI}.assistantConfigure(args[0]);", [restore])
            other.close()
            self.show_sidebar(reload=True)

    def test_21_an_error_mid_answer_keeps_it_marked_incomplete(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.provider.replies.append(Reply(chunks=["Metade ", "do ", "texto"], chunk_delay=0.3, error="overloaded_error"))
        self.submit("Fale")
        view = self.wait_view(lambda v: v["level"] == "error")
        self.assertEqual(view["status"], MESSAGES["err_provider_unavailable"]["message"])
        self.assertEqual(self.answer_text(), "Metade do texto")  # everything that came
        self.assertFalse(self.panel("return !!document.querySelector('#answer .assistant__cursor');"))
        self.assertEqual(
            self.panel(
                "return [document.getElementById('interrupted').hidden, document.getElementById('interrupted-text').textContent];"
            ),
            [False, "Resposta incompleta: parou antes do fim"],
        )

    def test_22_a_stop_at_once_says_nothing_left(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        before = self.provider.count
        self.panel(
            "const p = document.getElementById('prompt'); p.value = 'Ops'; document.getElementById('ask').requestSubmit();"
            "document.getElementById('send').click();"
        )
        view = self.wait_view(lambda v: v["answered"] or v["level"] == "error")
        self.assertEqual(view["status"], "Cancelado antes de enviar: nada saiu deste computador.")
        time.sleep(0.5)
        self.assertEqual(self.provider.count, before)

    def test_23_removing_the_assistant_cuts_an_answer(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.provider.replies.append(Reply(chunks=[f"parte {i} " for i in range(20)], chunk_delay=0.4))
        self.submit("Fale bastante")
        self.assertTrue(harness.wait_until(lambda: self.answer_text(), 20))
        restore = {"kind": "openai", "baseUrl": self.provider.base, "model": "test-model", "key": KEY}
        try:
            chrome_async(self.m, f"return await {AI}.assistantForget();")
            self.assertTrue(harness.wait_until(lambda: self.tools_process() is None, 5))
            self.assertNotIn("parte 19", self.answer_text())
        finally:
            chrome_async(self.m, f"return await {AI}.assistantConfigure(args[0]);", [restore])
            chrome_async(self.m, f"return await {AI}.assistantAllow(true);")
            self.show_sidebar(reload=True)
            self.wait_view(lambda v: v["state"] == "ready")

    def test_24_answers_in_safe_markdown_load_nothing(self):
        """UX5-E: only p, br, strong, em, code, pre, ul, ol, li, blockquote; links are text with their host;
        images, raw HTML and javascript: links never become elements, and nothing is requested."""
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        leak = self.server.url("/leak")
        answer = (
            "# Título do modelo\n\n**forte** e *ênfase*, `código <b>`\n\n- um\n- dois\n\n1. a\n2. b\n\n> citação\n\n"
            "```\nx<y && z\n```\n\n"
            f'[leia](https://ex.example/p) ![img]({leak}?img) <img src="{leak}?tag" onerror="alert(1)"> [js](javascript:alert(1))'
        )
        hits = len(self.server.hits)
        self.provider.replies.append({"choices": [{"message": {"content": answer}}]})
        self.ask_panel("Formate?")
        shape = self.panel(
            "const a = document.getElementById('answer');"
            "return { tags: [...new Set([...a.querySelectorAll('*')].map(e => e.localName))].sort(),"
            " attrs: [...a.querySelectorAll('*')].flatMap(e => [...e.attributes].map(x => x.name)),"
            " text: a.textContent, headings: a.querySelectorAll('h1,h2,h3,h4,h5,h6').length };"
        )
        self.assertTrue(set(shape["tags"]) <= {"p", "br", "strong", "em", "code", "pre", "ul", "ol", "li", "blockquote"}, shape)
        self.assertEqual(shape["attrs"], [])  # no href, src, style or on* anywhere
        self.assertEqual(shape["headings"], 0)  # the model's heading is a bold paragraph
        self.assertIn("leia (ex.example)", shape["text"])
        self.assertIn("<img src=", shape["text"])  # raw HTML shows as text
        self.assertIn("![img](", shape["text"])
        self.assertNotIn("javascript", shape["text"])
        time.sleep(1)
        self.assertFalse([h for h in self.server.hits[hits:] if h.startswith("/leak")])  # nothing was requested
        self.shoot_window("sidebar-markdown")

    def test_25_a_word_for_word_quote_is_a_source_that_shows_its_tab(self):
        """UX5-E / Q13: the source names the page; "Mostrar a aba" selects it only while it shows that address."""
        url = self.server.url("/long-page?n=1000")
        self.close_other_tabs()
        self.select_new_tab(url)
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["offer"])
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        quote = "Ção é um parágrafo longo de teste. Ção é um parágrafo longo"
        self.provider.replies.append(
            {"choices": [{"message": {"content": f"A página repete “{quote}”, e também diz outras coisas."}}]}
        )
        self.ask_panel("O que a página diz?")
        sources = self.panel(
            "return [...document.querySelectorAll('#sources li')].map(li => ({label: li.querySelector('p').textContent,"
            " quote: li.querySelector('blockquote').textContent}));"
        )
        self.assertEqual(sources, [{"label": f"Trecho citado da página “long-page” · {url.split('/')[2]}", "quote": quote}])
        self.select_new_tab(self.server.url("/page/Outra"))
        self.panel("document.querySelector('#sources li button').click();")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return gBrowser.selectedBrowser.currentURI.spec;") == url, 10))
        self.go(self.server.url("/page/Mudou"))
        self.panel("document.querySelector('#sources li button').click();")
        view = self.wait_view(lambda v: v["level"] == "error")
        self.assertEqual(view["status"], "“long-page” não está mais aberta nesse endereço nesta janela.")
        # An answer that only paraphrases has no sources, and the section is gone.
        self.provider.replies.append({"choices": [{"message": {"content": "Fala de um parágrafo de teste."}}]})
        self.ask_panel("E resumindo?")
        self.assertTrue(self.panel("return document.getElementById('sources-section').hidden;"))
        self.close_other_tabs()

    # -- the run timeline and the permission card (UX5-F) -----------------------------------------

    def card(self) -> dict:
        return self.panel(
            "const $ = id => document.getElementById(id);"
            "return { shown: !$('approval').hidden, focused: document.activeElement?.id ?? null,"
            " headline: $('approval-headline').textContent, once: $('approval-once').disabled,"
            " steps: [...$('steps').children].map(li => li.dataset.state),"
            " elsewhere: $('approval-elsewhere').hidden ? null : $('approval-elsewhere').textContent };"
        )

    def audit(self) -> list[dict]:
        log = Path(self.session.env["HOME"]) / ".local" / "state" / "nulavio" / "ai" / "audit.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines() if line.strip()] if log.exists() else []

    def ask_first(self, agent: str) -> None:
        chrome_async(self.m, f"return await {AI}.change(args[0], 'grant', {{capability: 'navigate', mode: 'ask'}});", [agent])
        self.addCleanup(
            chrome_async, self.m, f"return await {AI}.change(args[0], 'clear-grant', {{capability: 'navigate'}});", [agent]
        )

    def test_26_a_permission_request_is_a_card_in_the_panel_with_deny_first(self):
        self.close_other_tabs()
        self.ask_first(self.assistant_agent())
        call = {"id": "c1", "type": "function", "function": {"name": "tab_new", "arguments": json.dumps({"url": "about:blank"})}}
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.mode("task")
        self.addCleanup(self.mode, "ask")
        for answer in ("deny", "once"):
            with self.subTest(answer=answer):
                self.provider.replies += [{"choices": [{"message": {"content": None, "tool_calls": [call]}}]},
                                          {"choices": [{"message": {"content": "Feito."}}]}]  # fmt: skip
                self.submit("Abra uma aba")
                self.assertTrue(harness.wait_until(lambda: self.card()["shown"], 30))
                card = self.card()
                self.assertEqual(card["focused"], "approval-deny")  # the safe answer is the keyboard's default
                self.assertIn(MESSAGES["aiCap_navigate"]["message"], card["headline"])
                self.assertTrue(card["once"])  # "Permitir" waits a moment before it works
                if answer == "deny":
                    self.assertTrue(harness.wait_until(lambda: not self.card()["once"], 5))
                    self.shoot_window("sidebar-approval")
                self.assertEqual(card["steps"], ["started"])
                self.assertFalse(
                    any("ai/request.html" in u for u in self.m.chrome("return gBrowser.browsers.map(b => b.currentURI.spec);"))
                )
                if answer == "once":
                    self.assertTrue(harness.wait_until(lambda: not self.card()["once"], 5))
                self.panel(f"document.getElementById('approval-{answer}').click();")
                # Allowed, the call goes on and starts the AI Workspace. This harness has no display for it
                # (the tools never pass MOZ_HEADLESS on), so that ends as workspace-failed here.
                view = self.wait_view(lambda v: v["answered"] or v["level"] == "error", timeout=90)
                self.assertFalse(self.card()["shown"])
                steps = self.card()["steps"]
                calls = [e for e in self.audit() if e.get("tool") == "tab_new"]
                if answer == "deny":
                    self.assertEqual(steps, ["denied"])
                    self.assertEqual(view["status"], "Resposta pronta.")
                    self.assertEqual(calls[-1]["outcome"], "denied")
                else:
                    self.assertNotIn("denied", steps)  # it went on past the permission
                    self.assertNotEqual(calls[-1]["outcome"], "denied")

    def test_27_with_the_panel_closed_the_request_opens_in_front_in_its_window(self):
        self.close_other_tabs()
        self.ask_first(self.assistant_agent())
        call = {"id": "c1", "type": "function", "function": {"name": "tab_new", "arguments": json.dumps({"url": "about:blank"})}}
        self.provider.replies += [{"choices": [{"message": {"content": None, "tool_calls": [call]}}]},
                                  {"choices": [{"message": {"content": "Feito."}}]}]  # fmt: skip
        self.provider.delay = 2.0  # time to close the panel while the model thinks
        self.m.chrome(
            "window.nvPlaces = [];"
            f"window.nvOff = {AI}.subscribeAssistant((w, e) => e.type === 'approval' && window.nvPlaces.push(e.place));"
        )
        self.addCleanup(self.m.chrome, "window.nvOff?.();")
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.mode("task")
        self.submit("Abra uma aba")
        self.assertTrue(harness.wait_until(self.tools_process, 10))  # the run started; the panel closes now
        chrome_async(self.m, f"const w = {WINDOW}; w.SidebarController.hide(); return true;", [None])
        shown = "const spec = gBrowser.selectedBrowser.currentURI.spec; return spec.includes('ai/request.html') ? spec : null;"
        try:
            found = harness.wait_until(lambda: self.m.chrome(shown), 30)
            self.assertTrue(found, self.m.chrome("return window.nvPlaces;"))  # in front, in the window the task belongs to
            self.assertEqual(self.m.chrome("return window.nvPlaces;"), ["tab"])  # never also a card
            chrome_async(self.m, f"return await {AI}.answer(args[0], 'deny');", [found.split("id=")[1]])
        finally:
            self.provider.delay = 0.0
            requests = Path(self.session.env["HOME"]) / ".local" / "state" / "nulavio" / "ai" / "requests"
            for pending in requests.glob("*.json"):
                chrome_async(self.m, f"return await {AI}.answer(args[0], 'deny');", [pending.stem])
            self.assertTrue(harness.wait_until(lambda: self.tools_process() is None, 60))
            self.show_sidebar(reload=True)
            self.mode("ask")
            self.close_other_tabs()

    def test_28_stop_with_the_card_open_removes_it_and_denies(self):
        self.close_other_tabs()
        self.ask_first(self.assistant_agent())
        call = {"id": "c1", "type": "function", "function": {"name": "tab_new", "arguments": json.dumps({"url": "about:blank"})}}
        self.provider.replies.append({"choices": [{"message": {"content": None, "tool_calls": [call]}}]})
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.mode("task")
        self.addCleanup(self.mode, "ask")
        before = self.provider.count
        self.submit("Abra uma aba")
        self.assertTrue(harness.wait_until(lambda: self.card()["shown"], 30))
        self.panel("document.getElementById('send').click();")
        view = self.wait_view(lambda v: v["answered"], timeout=40)
        self.assertFalse(self.card()["shown"])
        self.assertIn(self.card()["steps"], (["cancelled"], ["denied"]))
        requests = Path(self.session.env["HOME"]) / ".local" / "state" / "nulavio" / "ai" / "requests"
        self.assertEqual(list(requests.glob("*.json")), [])
        self.assertEqual(self.provider.count, before + 1)
        self.assertTrue(view["activity"])

    # -- entry points (UX5-G) ------------------------------------------------------------------------

    def select_first_paragraph(self) -> str:
        return self.m.execute(
            "const p = document.querySelector('p'); const r = document.createRange(); r.selectNodeContents(p);"
            "getSelection().removeAllRanges(); getSelection().addRange(r); return getSelection().toString();"
        )

    def ask_menu_item(self) -> bool | None:
        """The "Perguntar ao assistente" item of the page menu that is open, in whichever window it is
        (#138: reading this window's document could read another window's menu): True drawn, False
        hidden (by its attribute or its window's sheet), None absent."""
        return self.m.chrome(
            "const open = [...Services.wm.getEnumerator('navigator:browser')].map(w => w.document)"
            ".find(d => d.getElementById('contentAreaContextMenu').state === 'open');"
            "const item = open?.querySelector(\"#contentAreaContextMenu [id$='-menuitem-_nulavio-ask-selection']\");"
            "return item ? !item.hidden && item.ownerDocument.defaultView.getComputedStyle(item).display !== 'none' : null;"
        )

    def focused_in_panel(self) -> str | None:
        try:
            return self.panel("return document.documentElement.dataset.ready === 'true' ? document.activeElement.id : null;")
        except AssertionError:
            return None  # the panel's page is still loading

    def sidebar_shows_assistant(self, which: str | None = None) -> bool:
        return chrome_async(self.m, f"const w = {WINDOW}; return w.SidebarController.isOpen && w.SidebarController.currentID;",
                            [which])["ok"] == SIDEBAR  # fmt: skip

    def test_29_the_selection_menu_opens_the_panel_with_the_selection_and_sends_nothing(self):
        url = self.server.url("/long-page?n=200")
        self.close_other_tabs()
        self.m.switch_to(self.m.window_handles()[0])
        self.m.navigate(url)  # in the tab Marionette drives, so the right click lands on it
        self.wait_loaded(url)
        chrome_async(self.m, f"const w = {WINDOW}; w.SidebarController.hide(); return true;", [None])
        selected = self.select_first_paragraph()
        before = self.provider.count
        self.m.context_click("p")
        self.assertTrue(harness.wait_until(self.m.menu_open))
        self.assertTrue(harness.wait_until(lambda: self.ask_menu_item() is True, 10))
        label = self.m.chrome("return document.querySelector(\"[id$='nulavio-ask-selection']\").getAttribute('label');")
        self.assertEqual(label, "Perguntar ao assistente sobre a seleção")  # never the selected text in the label
        self.m.chrome(
            "const m = document.getElementById('contentAreaContextMenu');"
            "m.activateItem(document.querySelector(\"[id$='nulavio-ask-selection']\"));"
        )
        self.assertTrue(harness.wait_until(self.sidebar_shows_assistant, 10))  # opened in this window
        view = self.wait_view(lambda v: v["attached"])
        self.assertTrue(self.panel("return document.querySelector('#chips li[data-kind=selection]') !== null;"))
        self.assertEqual(view["attached"], f"só da aba “long-page” · {url.split('/')[2]}")
        self.assertTrue(harness.wait_until(lambda: self.focused_in_panel() == "prompt", 10))
        self.assertEqual(self.provider.count, before)  # nothing went
        self.type("O que diz a seleção?")
        line = self.view()["sendLine"]
        self.submit("O que diz a seleção?")
        self.wait_view(lambda v: v["answered"] and self.provider.count == before + 1)
        content = self.provider.requests[-1][2]["messages"][-1]["content"]
        self.assertIn("<<<SELECTION", content)
        self.assertIn(" ".join(selected.split())[:40], " ".join(content.split()))
        self.assertEqual(self.shown_chars(line), self.provider.chars[-1])
        # A selection whose tab goes elsewhere leaves the message, like a page.
        self.panel("document.getElementById('new-thread').click();")
        self.select_first_paragraph()
        tab = chrome_async(self.m, f"return {TABS}.getId(gBrowser.selectedTab);")["ok"]
        text = self.m.execute("return getSelection().toString();")
        chrome_async(
            self.m,
            f"return await {AI}.assistantOffer({{kind: 'selection', pageUrl: args[0], text: args[1]}}, args[2]);",
            [url, text, tab],
        )
        self.wait_view(lambda v: v["attached"])
        self.go(self.server.url("/page/Outra"))
        view = self.wait_view(lambda v: v["drift"])
        self.assertIsNone(view["attached"])
        self.close_other_tabs()

    def test_30_no_selection_menu_or_delivery_in_a_private_window(self):
        url = self.server.url("/long-page?n=200")
        handles = set(self.m.window_handles())
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, timeout=20))
        private = (set(self.m.window_handles()) - handles).pop()
        self.m.switch_to(private)
        try:
            harness.wait_until(lambda: self.m.current_url() == "about:privatebrowsing", timeout=20)
            self.m.navigate(url)
            self.select_first_paragraph()
            self.m.context_click("p")
            self.assertTrue(harness.wait_until(self.m.menu_open))
            # #138: there and hidden from the moment the menu is open (its visibility is no longer switched for every
            # window, so "absent" would mean the check found nothing), not once the Shell's event page has woken.
            self.assertIs(self.ask_menu_item(), False)
            time.sleep(1)  # and still after the Shell's own listeners have run
            self.assertIs(self.ask_menu_item(), False)
            self.m.close_menu()
            tab = self.m.chrome(f"return {TABS}.getId(gBrowser.selectedTab);")
            refused = chrome_async(self.m, f"return await {AI}.assistantOffer({{kind: 'composer'}}, args[0]);", [tab])
            self.assertEqual(refused, {"error": "private-window"})
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)
        # After a private window, an ordinary window's menu offers the item at once (its visibility is
        # no longer switched for every window from the private one).
        self.close_other_tabs()
        self.m.switch_to(self.m.window_handles()[0])
        self.m.navigate(url)
        self.wait_loaded(url)
        self.select_first_paragraph()
        self.m.context_click("p")
        self.assertTrue(harness.wait_until(self.m.menu_open))
        self.assertIs(self.ask_menu_item(), True)
        self.m.close_menu()

    def test_31_the_shortcut_opens_the_panel_on_the_question_and_keeps_it_open(self):
        """Alt+Shift+A (Q8): the extension's key in the window; it opens and never toggles the panel."""
        self.close_other_tabs()
        self.select_new_tab(self.server.url("/page/Atalho"))
        chrome_async(self.m, f"const w = {WINDOW}; w.SidebarController.hide(); return true;", [None])
        # The engine adds one <key> per command to the extension's keyset (no id): the assistant's is Alt+Shift+A.
        key = "[...document.querySelectorAll('#ext-keyset-id-shell_nulavio_net key')].find(k => k.getAttribute('key') === 'A')"
        self.assertEqual(self.m.chrome(f"const k = {key}; return k && [k.getAttribute('modifiers'), k.getAttribute('key')];"),
                         ["alt,shift", "A"])  # fmt: skip
        for _ in range(2):  # pressed again, the panel stays open
            self.m.chrome(f"{key}.doCommand();")
            self.assertTrue(harness.wait_until(self.sidebar_shows_assistant, 10))
            self.assertTrue(harness.wait_until(lambda: self.focused_in_panel() == "prompt", 10))
        self.close_other_tabs()

    def test_32_ia_in_the_address_bar_only_writes_the_question(self):
        """UX5-H, Q7: "@ia …" then Enter opens this window's panel with the text in the question; nothing is sent."""
        self.close_other_tabs()
        chrome_async(self.m, f"const w = {WINDOW}; w.SidebarController.hide(); return true;", [None])
        before = self.provider.count
        self.m.chrome("if (window.gDialogBox?.isOpen) { window.gDialogBox.dialog?.close(); } gURLBar.focus(); gURLBar.select();")
        self.m.chrome(TYPE_JS, ["@ia Qual é a capital do Peru?\n"])
        self.assertTrue(harness.wait_until(self.sidebar_shows_assistant, 10))
        self.assertTrue(harness.wait_until(lambda: self.focused_in_panel() == "prompt", 10))
        self.assertEqual(self.panel("return document.getElementById('prompt').value;"), "Qual é a capital do Peru?")
        self.assertEqual(self.provider.count, before)  # written, not sent
        self.close_other_tabs()

    def test_33_the_quick_action_includes_this_page_and_is_not_in_private_windows(self):
        """UX5-H, Q6: the address bar action (moz-src ActionsProviderQuickActions, pinned here)."""
        url = self.server.url("/page/Acao")
        self.close_other_tabs()
        self.select_new_tab(url)
        chrome_async(self.m, f"const w = {WINDOW}; w.SidebarController.hide(); return true;", [None])
        actions = (
            "const {ActionsProviderQuickActions: Q} = ChromeUtils.importESModule("
            "'moz-src:///browser/components/urlbar/ActionsProviderQuickActions.sys.mjs');"
        )
        # As typed: a prefix of one of its words (the whole word is matched in the phrase).
        found = chrome_async(self.m, actions + "return [...await Q.getActions({input: 'assis'})];")["ok"]
        self.assertIn("nulavio-assistant", found)
        label = chrome_async(self.m, "return await document.l10n.formatValue('nulavio-quickaction-assistant');")["ok"]
        self.assertEqual(label, "Perguntar ao assistente sobre esta página")  # the branding's Fluent text, in this window
        self.assertFalse(self.m.chrome(actions + "return Q.getAction('nulavio-assistant').isUnsupported();"))
        before = self.provider.count
        self.m.chrome(actions + "Q.getAction('nulavio-assistant').onPick(null, {browserWindow: window});")
        self.assertTrue(harness.wait_until(self.sidebar_shows_assistant, 10))
        view = self.wait_view(lambda v: v["attached"])
        self.assertEqual(view["attached"], f"só da aba “Acao” · {url.split('/')[2]}")
        self.assertEqual(self.provider.count, before)
        # With a private window in front, the action is not offered.
        handles = set(self.m.window_handles())
        main = self.m.send("WebDriver:GetWindowHandle")["value"]
        self.m.chrome("OpenBrowserWindow({private: true});")
        self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, timeout=20))
        private = (set(self.m.window_handles()) - handles).pop()
        self.m.switch_to(private)
        try:
            self.assertTrue(
                harness.wait_until(
                    lambda: self.m.chrome(actions + "return Q.getAction('nulavio-assistant').isUnsupported();"), 10
                )
            )
        finally:
            self.m.send("WebDriver:CloseWindow")
            self.m.switch_to(main)
        self.close_other_tabs()

    # -- the activity seal in the band (UX5-I) ---------------------------------------------------

    def band_seal(self, kind: str) -> dict | None:
        """The band's seal in this window: its text, and whether it is really on screen and on top."""
        return self.m.chrome(
            "const row = document.querySelector('#nulavio-band .nv-band-row');"
            "const node = row?.querySelector(`.nv-band-${arguments[0]}`);"
            "if (!node || node.hidden) { return null; }"
            "const r = node.getBoundingClientRect();"
            "const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
            "return {text: node.getAttribute('aria-label') || node.textContent, width: r.width,"
            " opacity: getComputedStyle(node).opacity, onTop: node === top || node.contains(top)};",
            [kind],
        )

    def test_34_the_band_counts_a_tasks_steps_and_says_when_it_waits(self):
        self.close_other_tabs()
        # A refused call is not an action; a call that ran and failed (bad arguments) is.
        local = {
            "id": "c1",
            "type": "function",
            "function": {"name": "tab_new", "arguments": json.dumps({"url": "http://127.0.0.1:9/"})},
        }
        failing = {"id": "c3", "type": "function", "function": {"name": "tab_new", "arguments": json.dumps({"url": 5})}}
        self.provider.replies.append({"choices": [{"message": {"content": None, "tool_calls": [local]}}]})
        self.provider.replies += [{"choices": [{"message": {"content": None, "tool_calls": [failing]}}]}] * 2
        self.provider.replies.append({"choices": [{"message": {"content": "Fim."}}]})
        self.provider.delay = 1.5  # each model turn takes a moment: the seal shows each count
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.mode("task")
        self.addCleanup(self.mode, "ask")
        self.submit("Tente duas vezes")
        seen = set()
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and not self.view()["answered"]:
            seal = self.band_seal("activity")
            if seal:
                seen.add(seal["text"])
                self.assertEqual((seal["opacity"], seal["onTop"]), ("1", True), seal)  # on screen, not covered
                self.assertGreater(seal["width"], 0)
            time.sleep(0.1)
        self.assertIn("Assistente agindo na Área de IA", seen)  # the refused call: no count
        self.assertIn("Assistente agindo na Área de IA · 1 ação", seen)
        self.assertIn("Assistente agindo na Área de IA · 2 ações", seen)
        self.assertNotIn("Assistente agindo na Área de IA · 0 ações", seen)
        self.assertTrue(harness.wait_until(lambda: self.band_seal("activity") is None, 10))  # gone when done
        self.provider.delay = 0.0
        # Waiting for an answer, and "Parar tarefa" from the band.
        self.ask_first(self.assistant_agent())
        call = {"id": "c2", "type": "function", "function": {"name": "tab_new", "arguments": json.dumps({"url": "about:blank"})}}
        self.provider.replies.append({"choices": [{"message": {"content": None, "tool_calls": [call]}}]})
        self.submit("Abra uma aba")
        waiting = harness.wait_until(
            lambda: (lambda s: s if s and "aguardando" in s["text"] else None)(self.band_seal("activity")), 30
        )
        self.assertEqual(waiting["text"], "Assistente aguardando você: um pedido de permissão")
        self.m.chrome("document.querySelector('#nulavio-band .nv-band-task-stop').click();")
        self.assertTrue(harness.wait_until(lambda: self.band_seal("activity") is None, 40))
        self.wait_view(lambda v: v["answered"], timeout=20)
        # A hard end of the tools (SIGKILL) takes the seal away too.
        self.provider.replies.append({"choices": [{"message": {"content": None, "tool_calls": [call]}}]})
        self.submit("Abra outra")
        self.assertTrue(harness.wait_until(lambda: self.band_seal("activity"), 30))
        os.kill(harness.wait_until(self.tools_process, 10), signal.SIGKILL)
        self.assertTrue(harness.wait_until(lambda: self.band_seal("activity") is None, 15))

    def test_35_the_band_names_an_agent_connected_through_the_bridge(self):
        """UX5-I2: a session marker whose pid is a live bridge shows; a dead pid, a pid that is some other
        program (reused after a kill), or no marker shows nothing."""
        sessions = Path(self.session.env["HOME"]) / ".local" / "state" / "nulavio" / "ai" / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        marker = sessions / "s-test.json"
        # A stand-in for `nulavio ai serve`: what the band checks is a live pid whose command has "serve".
        bridge = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)", "serve"])
        self.addCleanup(bridge.wait)
        self.addCleanup(bridge.kill)
        marker.write_text(json.dumps({"agent": "ag-0123456789ab", "name": "Claude Code", "pid": bridge.pid}))
        try:
            seal = harness.wait_until(lambda: self.band_seal("connected"), 15)
            self.assertEqual(seal["text"], "Agente conectado: Claude Code")

            # Several band ticks (1.5 s each) read the markers: no process is started for it.
            def tools():
                found = []
                for pid in harness.descendants(self.session.process.pid):
                    try:
                        cmd = harness.proc_info(pid)["cmd"]
                        if "-contentproc" not in cmd and ("nulavio-tools" in cmd or "python" in cmd):
                            found.append(pid)  # the Nulavio tools (bin/nulavio runs python3), not the engine's processes
                    except OSError:
                        continue
                return found

            started = set()
            for _ in range(25):
                started |= set(tools())
                time.sleep(0.2)
            self.assertEqual(started, set())
            # Not in a private window.
            handles = set(self.m.window_handles())
            main = self.m.send("WebDriver:GetWindowHandle")["value"]
            self.m.chrome("OpenBrowserWindow({private: true});")
            self.assertTrue(harness.wait_until(lambda: set(self.m.window_handles()) - handles, timeout=20))
            self.m.switch_to((set(self.m.window_handles()) - handles).pop())
            try:
                time.sleep(2)  # past a band tick
                self.assertIsNone(self.band_seal("connected"))
            finally:
                self.m.send("WebDriver:CloseWindow")
                self.m.switch_to(main)
            marker.write_text(json.dumps({"agent": "ag-0123456789ab", "name": "Claude Code", "pid": os.getpid()}))
            self.assertTrue(harness.wait_until(lambda: self.band_seal("connected") is None, 15))  # alive, not a bridge
            marker.write_text(json.dumps({"agent": "ag-0123456789ab", "name": "Claude Code", "pid": bridge.pid}))
            self.assertTrue(harness.wait_until(lambda: self.band_seal("connected"), 15))
            marker.write_text(json.dumps({"agent": "ag-0123456789ab", "name": "Claude Code", "pid": 2**22 + 12345}))
            self.assertTrue(harness.wait_until(lambda: self.band_seal("connected") is None, 15))  # that process is gone
        finally:
            marker.unlink(missing_ok=True)

    # -- fixes from the UX5 D-I review -------------------------------------------------------------

    def test_36_a_retry_after_leaving_the_page_out_sends_no_page_and_the_receipt_says_all(self):
        url = self.server.url("/page/Reenvio")
        self.close_other_tabs()
        self.select_new_tab(url)
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["offer"])
        self.panel("document.getElementById('new-thread').click();")
        self.assertTrue(harness.wait_until(lambda: self.thread_view()["empty"], 10))
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        self.provider.replies.append({"choices": [{"message": {"content": "Primeira."}}]})
        view = self.ask_panel("PERGUNTA-A?")
        self.assertIn("desta página foram enviados", view["receipt"])  # only the page went with it
        # The page again with the next question, which fails; then "Deixar a página de fora".
        self.wait_view(lambda v: v["offer"])
        self.panel("document.getElementById('include-page').click();")
        self.wait_view(lambda v: v["attached"])
        self.provider.replies.append(Reply(status=503))
        self.submit("PERGUNTA-B?")
        self.wait_view(lambda v: v["level"] == "error")
        self.assertTrue(harness.wait_until(lambda: self.thread_view()["retry"], 10))
        self.panel("document.getElementById('leave-page').click();")
        self.assertTrue(harness.wait_until(lambda: not self.thread_view()["leave"], 10))
        hint = harness.wait_until(lambda: self.thread_view()["retry"], 10)
        announced = int(re.search(r"Reenvia ([\d.]+) caracteres", hint).group(1).replace(".", ""))
        self.provider.replies.append({"choices": [{"message": {"content": "Sem a página."}}]})
        before = self.provider.count
        self.panel("document.getElementById('retry').click();")
        view = self.wait_view(lambda v: v["answered"] and self.provider.count == before + 1)
        sent = json.dumps(self.provider.requests[-1][2], ensure_ascii=False)
        self.assertNotIn("<<<PAGE", sent)  # neither the failed turn's copy nor the earlier one
        self.assertIn("PERGUNTA-B?", sent)
        self.assertEqual(self.provider.chars[-1], announced)
        self.assertIn(" da conversa)", view["receipt"])  # the conversation went with it, and the receipt says so
        # A turn that failed for one recipient is not sent again to another, after carrying the conversation.
        self.provider.replies.append(Reply(status=503))
        self.submit("PERGUNTA-C?")
        self.wait_view(lambda v: v["level"] == "error")
        self.assertTrue(harness.wait_until(lambda: self.thread_view()["retry"], 10))
        other = FakeProvider()
        restore = {"kind": "openai", "baseUrl": self.provider.base, "model": "test-model"}
        try:
            chrome_async(self.m, f"return await {AI}.assistantConfigure(args[0]);", [{**restore, "baseUrl": other.base}])
            self.show_sidebar(reload=True)
            self.assertTrue(harness.wait_until(lambda: self.thread_view()["moved"], 10))
            self.panel("document.getElementById('moved-carry').click();")
            self.assertTrue(harness.wait_until(lambda: not self.thread_view()["moved"], 10))
            self.assertIsNone(self.thread_view()["retry"])
            st = chrome_async(self.m, f"const w = {WINDOW}; return await {AI}.assistantState(w);", [None])["ok"]
            expected = {"recipient": st["recipient"], "model": "test-model", "chars": 1}
            start = f"const w = {WINDOW}; return await {AI}.assistantStart('ask', {{retry: true, expected: args[0]}}, w);"
            refused = chrome_async(self.m, start, [expected, None])
            self.assertEqual(refused, {"error": "thread-recipient"})
            self.assertEqual(other.count, 0)
        finally:
            chrome_async(self.m, f"return await {AI}.assistantConfigure(args[0]);", [restore])
            other.close()
            self.show_sidebar(reload=True)
            self.close_other_tabs()

    def test_37_a_new_conversation_during_an_answer_does_not_get_that_turn(self):
        self.close_other_tabs()
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.panel("document.getElementById('new-thread').click();")
        self.provider.replies += [{"choices": [{"message": {"content": "Da conversa velha."}}]},
                                  {"choices": [{"message": {"content": "Da nova."}}]}]  # fmt: skip
        self.provider.delay = 2.0
        try:
            self.submit("PERGUNTA-VELHA?")
            self.assertTrue(harness.wait_until(self.tools_process, 10))
            self.panel("document.getElementById('new-thread').click();")
            self.wait_view(lambda v: v["answered"], timeout=30)
        finally:
            self.provider.delay = 0.0
        self.assertTrue(harness.wait_until(lambda: not self.thread_view()["shown"], 10))
        self.ask_panel("PERGUNTA-NOVA?")
        self.assertEqual([m["content"] for m in self.user_turns()], ["PERGUNTA-NOVA?"])

    def test_38_a_card_waiting_in_the_panel_comes_back_with_it_and_goes_to_a_tab_without_it(self):
        self.close_other_tabs()
        self.ask_first(self.assistant_agent())
        call = {"id": "c1", "type": "function", "function": {"name": "tab_new", "arguments": json.dumps({"url": "about:blank"})}}
        self.provider.replies.append({"choices": [{"message": {"content": None, "tool_calls": [call]}}]})
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")
        self.mode("task")
        self.addCleanup(self.mode, "ask")
        self.submit("Abra uma aba")
        self.assertTrue(harness.wait_until(lambda: self.card()["shown"], 30))
        tabs = "return gBrowser.browsers.filter(b => b.currentURI.spec.includes('ai/request.html')).length;"
        requests = Path(self.session.env["HOME"]) / ".local" / "state" / "nulavio" / "ai" / "requests"
        try:
            # The panel reloads: the card is there again, and no request tab opens as well.
            self.show_sidebar(reload=True)
            self.assertTrue(harness.wait_until(lambda: self.card()["shown"], 10))
            time.sleep(2)  # past the moment a closed panel's card goes to a tab
            self.assertTrue(self.card()["shown"])
            self.assertEqual(self.m.chrome(tabs), 0)
            # The panel closes: the request opens in front in the task's window, so it is never left unseen.
            chrome_async(self.m, f"const w = {WINDOW}; w.SidebarController.hide(); return true;", [None])
            front = "const s = gBrowser.selectedBrowser.currentURI.spec; return s.includes('ai/request.html') ? s : null;"
            found = harness.wait_until(lambda: self.m.chrome(front), 15)
            self.assertTrue(found)
            self.assertEqual(self.m.chrome(tabs), 1)
            chrome_async(self.m, f"return await {AI}.answer(args[0], 'deny');", [found.split("id=")[1]])
        finally:
            for pending in requests.glob("*.json"):
                chrome_async(self.m, f"return await {AI}.answer(args[0], 'deny');", [pending.stem])
            self.assertTrue(harness.wait_until(lambda: self.tools_process() is None, 60))
            self.show_sidebar(reload=True)
            self.close_other_tabs()

    def test_39_the_panels_doors_open_the_settings_page_and_the_agents_page(self):
        """The panel holds no settings: where this profile is not allowed, "Abrir configurações" opens the
        browser's settings page on the assistant; while the agents are stopped, the door opens the agents' page."""
        self.close_other_tabs()
        urls = "return gBrowser.browsers.map(b => b.currentURI.spec);"

        def opened(prefix: str) -> list[str]:
            return harness.wait_until(lambda: [u for u in self.m.chrome(urls) if u.startswith(prefix)], 15) or []

        self.addCleanup(self.close_other_tabs)
        self.addCleanup(chrome_async, self.m, f"return await {AI}.assistantAllow(true);")
        chrome_async(self.m, f"return await {AI}.assistantAllow(false);")
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "not-allowed")
        door = "const b = document.getElementById('%s'); return { shown: !b.closest('[hidden]'), text: b.textContent };"
        self.assertEqual(
            self.panel(door % "open-settings"), {"shown": True, "text": MESSAGES["assistantOpenSettings"]["message"]}
        )
        self.panel("document.getElementById('open-settings').click();")
        self.assertEqual(opened("about:preferences"), [f"about:preferences#{settings_page.assistant_pane(self.m)}"])
        chrome_async(self.m, f"return await {AI}.assistantAllow(true);")

        self.close_other_tabs()
        self.addCleanup(chrome_async, self.m, f"return await {AI}.setStopped(false);")
        chrome_async(self.m, f"return await {AI}.setStopped(true);")
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "blocked")
        self.assertTrue(self.panel(door % "resume-settings")["shown"])
        self.panel("document.getElementById('resume-settings').click();")
        agents = opened("moz-extension://")
        self.assertEqual(len(agents), 1, agents)
        self.assertTrue(agents[0].endswith("/settings/settings.html#ai-agents-card"), agents)
        chrome_async(self.m, f"return await {AI}.setStopped(false);")
        self.show_sidebar(reload=True)
        self.wait_view(lambda v: v["state"] == "ready")


if __name__ == "__main__":
    unittest.main()
