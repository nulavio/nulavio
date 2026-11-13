"""ADR 0011: the emergency stop and the assistant's service, inside the engine's settings page.

What is a setting of the assistant and the agents is in the "Assistente e IA" pane; granting an agent its
permissions, connecting one and the activity record stay the Shell's own page. Every change goes through
NulavioAI, which refuses changes asked from a window an agent drives. The tests use the real Nulavio tools for
the stop and for a provider without a key; a key is only ever handed to the module's entry replaced by the test
(no keyring is involved here: tests/integration/test_assistant_ui.py covers the key with a stand-in keyring).
"""

from __future__ import annotations

import unittest

import harness
from marionette import MarionetteError

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
A = 'const A = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs").NulavioAI;'
STATE = (
    A
    + """return Promise.all([A.overview(), A.assistantState(window)]).then(([overview, assistant]) => ({
  stopped: Boolean(overview.stopped), configured: assistant.configured, provider: assistant.provider ?? null,
  allowed: assistant.profileAllowed, hasKey: Boolean(assistant.hasKey),
}));"""
)
PAGE = (
    DOC
    + """
const shown = el => !!el && !el.closest("setting-control")?.hidden && el.getBoundingClientRect().height > 0;
const el = id => d.getElementById(id);
const bar = id => (shown(el(id)) ? el(id).message : null);
const value = id => (shown(el(id)) ? el(id).value : null);
return {
  stop: shown(el("nulavio-ai-stop")) ? Boolean(el("nulavio-ai-stop").pressed) : null,
  stopped: bar("nulavio-ai-stopped"), workspace: bar("nulavio-ai-workspace"),
  assistant: shown(el("nulavio-assistant-now")) ? el("nulavio-assistant-now").description : null,
  kind: value("nulavio-assistant-kind"), model: value("nulavio-assistant-model"), url: value("nulavio-assistant-url"),
  key: value("nulavio-assistant-key"), keyType: el("nulavio-assistant-key")?.localName ?? null,
  allowed: shown(el("nulavio-assistant-allowed")) ? Boolean(el("nulavio-assistant-allowed").pressed) : null,
  forget: shown(el("nulavio-assistant-forget")), agents: shown(el("nulavio-open-assistant")),
  said: bar("nulavio-ai-said"), error: bar("nulavio-ai-error"),
};
"""
)
CLICK = DOC + "const el = d.querySelector(arguments[0]); if (!el) return false; el.click(); return true;"
CHANGE = (
    DOC
    + """
const el = d.getElementById(arguments[0]);
if (!el) return false;
el.value = arguments[1];
el.dispatchEvent(new Event("change", { bubbles: true }));
return true;
"""
)
LOCAL = "http://127.0.0.1:9/v1"  # a model "on this computer": nothing is asked of it here


@unittest.skipUnless(harness.nulavio_engine(), "the settings page needs the built-in Shell on the engine")
class SettingsAssistantTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="Pessoal")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()
        self.pane = self.m.chrome(
            'return Services.prefs.getBoolPref("browser.preferences.aiControls", false) ? "ai" : "nulavioAssistant";'
        )

    def open(self) -> dict:
        self.m.navigate(f"about:preferences#{self.pane}")
        self.assertTrue(harness.wait_until(lambda: self.m.chrome(READY), 20))
        return self.seen(lambda now: now["stop"] is not None or now["workspace"])

    def seen(self, wanted, timeout: float = 20) -> dict:
        harness.wait_until(lambda: wanted(self.m.chrome(PAGE)), timeout)
        now = self.m.chrome(PAGE)
        self.assertTrue(wanted(now), now)
        return now

    def state(self) -> dict:
        return self.m.chrome(STATE)

    def alert_text(self):
        try:
            return self.m.send("WebDriver:GetAlertText")["value"]
        except MarionetteError:
            return None

    def test_01_the_emergency_stop_is_one_switch_and_says_when_it_is_on(self):
        now = self.open()
        self.assertFalse(now["stop"])
        self.assertIsNone(now["stopped"])
        self.assertFalse(self.state()["stopped"])
        self.m.chrome(CLICK, ["#nulavio-ai-stop"])
        on = self.seen(lambda n: n["stop"] and n["stopped"])
        self.assertTrue(self.state()["stopped"])
        self.assertIn("Parada de emergência ligada", on["stopped"])
        self.assertEqual(on["said"], "Todos os agentes estão parados.")
        self.m.chrome(CLICK, ["#nulavio-ai-stop"])
        off = self.seen(lambda n: n["stop"] is False and not n["stopped"])
        self.assertFalse(self.state()["stopped"])
        self.assertEqual(off["said"], "Os agentes podem trabalhar de novo, dentro das permissões.")

    def test_02_the_assistants_service_is_saved_through_the_module_and_the_key_is_never_kept(self):
        now = self.open()
        self.assertIn("Nenhum provedor ainda.", now["assistant"])
        self.assertEqual((now["kind"], now["model"], now["url"], now["key"]), ("openai", "", "", ""))
        self.assertEqual(now["keyType"], "moz-input-password")
        self.assertFalse(now["forget"])
        self.assertFalse(now["allowed"])
        # An address that is neither https nor this computer: refused in words, nothing saved, and a key typed
        # with it is dropped from the page at once (the other fields keep what was typed).
        self.m.chrome(CHANGE, ["nulavio-assistant-model", "modelo-de-teste"])
        self.m.chrome(CHANGE, ["nulavio-assistant-url", "http://example.org/v1"])
        self.m.chrome(CHANGE, ["nulavio-assistant-key", "sk-artificial-settings-key"])
        self.m.chrome(CLICK, ["#nulavio-assistant-save"])
        refused = self.seen(lambda n: n["error"])
        self.assertEqual(refused["error"], "Use https://, ou http:// só para um modelo neste computador.")
        self.assertEqual((refused["model"], refused["url"], refused["key"]), ("modelo-de-teste", "http://example.org/v1", ""))
        self.assertFalse(self.state()["configured"])
        # A model on this computer, with no key: saved for real through the Nulavio tools.
        self.m.chrome(CHANGE, ["nulavio-assistant-url", LOCAL])
        self.m.chrome(CLICK, ["#nulavio-assistant-save"])
        saved = self.seen(lambda n: n["said"] and "modelo-de-teste" in (n["assistant"] or ""))
        self.assertEqual(saved["said"], "Configurações do assistente salvas.")
        state = self.state()
        self.assertTrue(state["configured"])
        self.assertEqual(
            (state["provider"]["model"], state["provider"]["base_url"], state["hasKey"]), ("modelo-de-teste", LOCAL, False)
        )
        self.assertIn("Nenhuma chave de API guardada.", saved["assistant"])
        self.assertTrue(saved["forget"])
        # Whether this profile may send anything is a switch of its own, saved when it changes.
        self.m.chrome(CLICK, ["#nulavio-assistant-allowed"])
        self.seen(lambda n: n["allowed"] is True)
        self.assertTrue(self.state()["allowed"])
        # A key goes to the module once, with the save, and is not in the page afterwards.
        self.m.chrome(A + "window.__asked = []; A.assistantConfigure = async details => { window.__asked.push(details); };")
        self.addCleanup(self.m.chrome, A + "delete A.assistantConfigure;")
        self.m.chrome(CHANGE, ["nulavio-assistant-key", "sk-artificial-settings-key"])
        self.m.chrome(CLICK, ["#nulavio-assistant-save"])
        self.assertTrue(harness.wait_until(lambda: self.m.chrome("return window.__asked.length;") == 1, 10))
        asked = self.m.chrome("return window.__asked[0];")
        self.assertEqual(
            asked, {"kind": "openai", "baseUrl": LOCAL, "model": "modelo-de-teste", "key": "sk-artificial-settings-key"}
        )
        self.assertEqual(self.seen(lambda n: n["key"] == "")["key"], "")
        in_page = DOC + 'return d.documentElement.innerHTML.includes("sk-artificial-settings-key");'
        self.assertFalse(self.m.chrome(in_page), "the key is still somewhere in the page")
        self.m.chrome(A + "delete A.assistantConfigure;")
        # Removing the assistant asks first; closing the prompt removes nothing.
        self.m.chrome(CLICK, ["#nulavio-assistant-forget"])
        body = harness.wait_until(self.alert_text, 10)
        self.assertIn("a chave de API são apagadas", body or "no confirmation was shown")
        self.m.send("WebDriver:DismissAlert")
        self.assertTrue(self.state()["configured"])
        self.m.chrome(CLICK, ["#nulavio-assistant-forget"])
        self.assertTrue(harness.wait_until(self.alert_text, 10))
        self.m.send("WebDriver:AcceptAlert")
        gone = self.seen(lambda n: "Nenhum provedor ainda." in (n["assistant"] or "") and not n["forget"])
        self.assertFalse(self.state()["configured"])
        self.assertEqual((gone["model"], gone["url"]), ("", ""))

    def test_03_a_window_an_agent_drives_shows_no_control(self):
        # As the module answers in an agent's own window (the bridge sets that; a test cannot start one here).
        self.m.chrome(
            A + 'A.workspaceAgent = async () => "agente-x";'
            'A.overview = async () => ({ stopped: false, agents: [{ id: "agente-x", name: "Agente de teste" }] });'
        )
        self.addCleanup(self.m.chrome, A + "delete A.workspaceAgent; delete A.overview;")
        now = self.open()
        self.assertEqual(
            now["workspace"],
            "Esta janela é a Área de IA de Agente de teste. Gerencie os agentes, e a parada de emergência, numa janela sua.",
        )
        for control in ("stop", "assistant", "kind", "model", "url", "key", "allowed"):
            self.assertIsNone(now[control], control)
        self.assertFalse(now["forget"])
        self.assertFalse(now["agents"], "the way to the agents' page is offered in an agent's window")


if __name__ == "__main__":
    unittest.main()
