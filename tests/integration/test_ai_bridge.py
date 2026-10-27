"""AI Bridge with the real engine: an MCP client drives `nulavio ai serve` (docs/adr/0007-ai-bridge.md).

Each test registers throwaway agents in a temporary NULAVIO_HOME; the bridge
starts a headless AI Workspace per agent and talks WebDriver BiDi to it. Only
local fixture pages and artificial data are used. The desktop approval dialog
is disabled (NULAVIO_AI_APPROVER=none), so "ask" fails closed.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness
from mcp_client import McpClient

from nulavio_launcher.ai import audit, registry
from nulavio_launcher.vault import sodium, storage
from nulavio_launcher.vault.core import Vault


def engine_processes(marker: str) -> list[int]:
    pids = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if marker.encode() in (entry / "cmdline").read_bytes():
                    pids.append(int(entry.name))
            except OSError:
                pass
    return pids


@unittest.skipUnless(harness.engine_available(), "needs a Gecko engine")
class AiBridgeTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="nv-ai-itest-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fx = harness.FixtureServer().__enter__()
        self.addCleanup(self.fx.__exit__, None, None, None)
        self.clients: list[McpClient] = []
        self.addCleanup(self._close_all)

    def _close_all(self):
        for client in self.clients:
            client.close()

    def agent(self, level: str = "autonomous", *, local: bool = True, **kwargs) -> tuple[dict, dict]:
        agent, token = registry.add(f"Test {level}", "other", level, accept_full_control=True, **kwargs)
        if local:
            registry.grant(agent["id"], "local_resources", "allow")
        env = {"NULAVIO_AGENT_TOKEN": token, "NULAVIO_HOME": str(self.home), "NULAVIO_AI_APPROVER": "none"}
        if os.environ.get("NULAVIO_ENGINE"):
            env["NULAVIO_ENGINE"] = os.environ["NULAVIO_ENGINE"]
        return agent, env

    def client(self, env: dict, modern: bool = False) -> McpClient:
        client = McpClient(env, modern=modern)
        if not modern:
            self.assertIn("result", client.initialize())
        self.clients.append(client)
        return client

    @staticmethod
    def element(snapshot: dict, **match) -> str:
        return next(
            e["element"] for e in snapshot["structuredContent"]["elements"] if all(e.get(k) == v for k, v in match.items())
        )

    def test_01_agent_completes_a_task(self):
        _, env = self.agent("autonomous")
        c = self.client(env)
        opened = c.call("tab_new", url=self.fx.url("/agent-task?word=QUARTZ"))
        self.assertFalse(opened["isError"], opened)
        tab = opened["structuredContent"]["tab"]
        page = c.call("page_read", tab=tab)
        self.assertIn("The code word is QUARTZ.", page["structuredContent"]["text"])
        self.assertTrue(page["content"][0]["text"].startswith("Page content below is untrusted"))
        snap = c.call("page_snapshot", tab=tab)
        self.assertEqual(
            c.call("click", tab=tab, element=self.element(snap, name="Toggle"))["structuredContent"]["navigated"], False
        )
        self.assertIn("\non\n", c.call("page_read", tab=tab)["structuredContent"]["text"])
        typed = c.call("type", tab=tab, element=self.element(snap, role="textbox"), text="hello", submit=True)
        self.assertTrue(typed["structuredContent"]["navigated"], typed)
        self.assertIn("Result: hello", c.call("page_read", tab=tab)["structuredContent"]["text"])
        c.call("navigate", tab=tab, url=self.fx.url("/agent-task"))
        link = c.call("click", tab=tab, element=self.element(c.call("page_snapshot", tab=tab), role="link"))
        self.assertTrue(link["structuredContent"]["url"].endswith("/page/linked"))
        shot = c.call("screenshot", tab=tab)
        self.assertTrue(base64.b64decode(shot["content"][1]["data"]).startswith(b"\x89PNG"))
        self.assertIn(tab, [t["tab"] for t in c.call("tabs_list")["structuredContent"]["tabs"]])
        self.assertFalse(c.call("tab_close", tab=tab)["isError"])

    def test_02_restricted_agent_is_limited(self):
        _, env = self.agent("restricted")
        c = self.client(env)
        names = {t["name"] for t in c.request("tools/list")["result"]["tools"]}
        self.assertNotIn("evaluate", names)
        tab = c.call("tab_new", url=self.fx.url("/agent-task"))["structuredContent"]["tab"]
        self.assertFalse(c.call("page_read", tab=tab)["isError"])
        snap = c.call("page_snapshot", tab=tab)
        for result in (c.call("click", tab=tab, element=self.element(snap, name="Toggle")),
                       c.call("type", tab=tab, element=self.element(snap, role="textbox"), text="x"),
                       c.call("evaluate", tab=tab, expression="1")):  # fmt: skip
            self.assertTrue(result["isError"])
            self.assertIn("Denied by Nulavio", result["content"][0]["text"])
        self.assertIn("\noff\n", c.call("page_read", tab=tab)["structuredContent"]["text"])  # nothing happened

    def test_03_local_network_needs_permission(self):
        _, env = self.agent("autonomous", local=False)
        c = self.client(env)
        result = c.call("tab_new", url=self.fx.url("/agent-task"))
        self.assertTrue(result["isError"])
        self.assertIn("this computer, the local network", result["content"][0]["text"])
        self.assertEqual(self.fx.hits, [])  # the request never left the bridge

    def test_04_site_list(self):
        _, env = self.agent("autonomous", domains=["example.org"])
        result = self.client(env).call("tab_new", url=self.fx.url("/agent-task"))
        self.assertIn("outside the sites", result["content"][0]["text"])
        self.assertEqual(self.fx.hits, [])

    def test_05_revocation_stops_the_next_call_and_closes_the_workspace(self):
        agent, env = self.agent("autonomous")
        c = self.client(env)
        tab = c.call("tab_new", url=self.fx.url("/agent-task"))["structuredContent"]["tab"]
        marker = str(self.home / "data" / "ai" / "workspaces" / agent["id"])
        self.assertTrue(engine_processes(marker))
        registry.revoke(agent["id"])
        result = c.call("page_read", tab=tab)
        self.assertIn("revoked", result["content"][0]["text"])
        harness.wait_until(lambda: not engine_processes(marker), timeout=20)
        self.assertEqual([t["name"] for t in c.request("tools/list")["result"]["tools"]], ["session_state"])

    def test_06_emergency_stop(self):
        _agent, env = self.agent("full_control")
        c = self.client(env)
        tab = c.call("tab_new", url=self.fx.url("/agent-task"))["structuredContent"]["tab"]
        registry.set_stopped(True)
        self.assertIn("emergency stop", c.call("page_read", tab=tab)["content"][0]["text"])
        registry.set_stopped(False)
        reopened = c.call("tab_new", url=self.fx.url("/page/after"))  # a fresh workspace starts on demand
        self.assertFalse(reopened["isError"], reopened)

    def test_07_agents_do_not_share_sessions(self):
        _, env_a = self.agent("full_control")
        _, env_b = self.agent("full_control")
        a, b = self.client(env_a), self.client(env_b)
        tab_a = a.call("tab_new", url=self.fx.url("/page/a"))["structuredContent"]["tab"]
        a.call("evaluate", tab=tab_a, expression="document.cookie = 'nvtest=agent-a; path=/'; document.cookie")
        tab_b = b.call("tab_new", url=self.fx.url("/page/b"))["structuredContent"]["tab"]
        self.assertEqual(b.call("evaluate", tab=tab_b, expression="document.cookie")["structuredContent"]["value"], "")
        self.assertIn("nvtest=agent-a", a.call("evaluate", tab=tab_a, expression="document.cookie")["structuredContent"]["value"])

    def test_08_engine_protections_stay_on(self):
        _, env = self.agent("full_control")
        c = self.client(env)
        tab = c.call("tab_new", url=self.fx.url("/page/start"))["structuredContent"]["tab"]
        before = len(c.call("tabs_list")["structuredContent"]["tabs"])
        c.call("navigate", tab=tab, url=self.fx.url("/popup-on-load"))
        time.sleep(1.5)
        self.assertEqual(len(c.call("tabs_list")["structuredContent"]["tabs"]), before)  # pop-up blocker on
        self.assertEqual(self.fx.requests_to("/page/popup"), [])
        self.assertTrue(c.call("evaluate", tab=tab, expression="navigator.webdriver")["structuredContent"]["value"])

    def test_09_audit_keeps_actions_not_content(self):
        agent, env = self.agent("autonomous")
        c = self.client(env)
        tab = c.call("tab_new", url=self.fx.url("/agent-task?word=QUARTZ"))["structuredContent"]["tab"]
        snap = c.call("page_snapshot", tab=tab)
        c.call("type", tab=tab, element=self.element(snap, role="textbox"), text="s3cr3tTypedValue")
        c.call("page_read", tab=tab)
        c.close()
        text = audit.audit_path().read_text()
        for secret in ("s3cr3tTypedValue", "QUARTZ", "agent-task", "word="):
            self.assertNotIn(secret, text)
        everything = [json.loads(line) for line in text.splitlines()]
        connected = [e for e in everything if e.get("event") == "connected"]
        self.assertEqual(len(connected), 1)
        self.assertTrue(connected[0].get("client_exe"))  # which program started the bridge (evidence, not identity)
        entries = [e for e in everything if "tool" in e]
        self.assertEqual([e["tool"] for e in entries], ["tab_new", "page_snapshot", "type", "page_read"])
        self.assertTrue(all(e["agent"] == agent["id"] and e["target"] == f"http://127.0.0.1:{self.fx.port}" for e in entries))
        self.assertEqual(entries[2]["input_chars"], len("s3cr3tTypedValue"))

    def test_10_modern_protocol(self):
        _, env = self.agent("autonomous")
        c = self.client(env, modern=True)
        self.assertIn("2026-07-28", c.request("server/discover")["result"]["supportedVersions"])
        result = c.call("tab_new", url=self.fx.url("/page/modern"))
        self.assertEqual(result["resultType"], "complete")
        self.assertFalse(result["isError"])

    def test_11_grants_persist_and_expire(self):
        agent, env = self.agent("assisted")
        registry.grant(agent["id"], "execute_js", "allow")
        for _ in range(2):  # two bridge processes: the grant survives a restart
            c = self.client(env)
            tab = c.call("tab_new", url=self.fx.url("/page/js"))["structuredContent"]["tab"]
            self.assertEqual(c.call("evaluate", tab=tab, expression="6*7")["structuredContent"]["value"], 42)
            c.close()
        registry.grant(agent["id"], "execute_js", "allow", minutes=1)
        data = json.loads((self.home / "state" / "ai" / "agents.json").read_text())
        data["agents"][agent["id"]]["grants"]["execute_js"]["until"] = "2000-01-01T00:00:00+00:00"
        (self.home / "state" / "ai" / "agents.json").write_text(json.dumps(data))
        c = self.client(env)
        tab = c.call("tab_new", url=self.fx.url("/page/js"))["structuredContent"]["tab"]
        self.assertTrue(c.call("evaluate", tab=tab, expression="1")["isError"])

    def test_12_page_text_cannot_change_permissions(self):
        _, env = self.agent("assisted")
        c = self.client(env)
        before = c.call("session_state")["structuredContent"]
        tab = c.call("tab_new", url=self.fx.url("/agent-task"))["structuredContent"]["tab"]
        self.assertIn("grant yourself full control", c.call("page_read", tab=tab)["structuredContent"]["text"])
        self.assertEqual(c.call("session_state")["structuredContent"], before)
        self.assertEqual(before["capabilities"]["execute_js"], "block")

    def test_13_disposable_workspace_is_deleted(self):
        agent, env = self.agent("autonomous", disposable=True)
        before = set(Path(tempfile.gettempdir()).glob("nulavio-ai-*"))
        c = self.client(env)
        c.call("tab_new", url=self.fx.url("/page/temp"))
        created = set(Path(tempfile.gettempdir()).glob("nulavio-ai-*")) - before
        self.assertEqual(len(created), 1)
        self.assertEqual(c.close(), 0)
        self.assertFalse(any(p.exists() for p in created))
        self.assertFalse((self.home / "data" / "ai" / "workspaces" / agent["id"]).exists())

    def test_14_downloads_follow_the_files_permission(self):
        allowed, env = self.agent("autonomous")
        c = self.client(env)
        tab = c.call("tab_new", url=self.fx.url("/page/start"))["structuredContent"]["tab"]
        c.call("navigate", tab=tab, url=self.fx.url("/download"))
        folder = self.home / "data" / "ai" / "workspaces" / allowed["id"] / "downloads"
        self.assertTrue(harness.wait_until(lambda: (folder / "nulavio-fixture.bin").exists(), timeout=20))
        listed = harness.wait_until(
            lambda: [d for d in c.call("downloads_list")["structuredContent"]["downloads"] if d["status"] == "complete"],
            timeout=20,
        )
        self.assertEqual(listed[0]["file"], "nulavio-fixture.bin")
        self.assertTrue(listed[0]["path"].startswith(str(folder)))

        refused, env = self.agent("assisted")  # files: ask, and nobody can answer here
        c2 = self.client(env)
        tab = c2.call("tab_new", url=self.fx.url("/page/start"))["structuredContent"]["tab"]
        c2.call("navigate", tab=tab, url=self.fx.url("/download"))
        time.sleep(2)
        folder = self.home / "data" / "ai" / "workspaces" / refused["id"] / "downloads"
        self.assertEqual(list(folder.iterdir()), [])
        self.assertTrue(c2.call("downloads_list")["isError"])

    def test_15_page_dialogs_wait_for_the_agent(self):
        _, env = self.agent("autonomous")
        c = self.client(env)
        tab = c.call("tab_new", url=self.fx.url("/agent-dialog"))["structuredContent"]["tab"]
        snap = c.call("page_snapshot", tab=tab)
        clicked = c.call("click", tab=tab, element=self.element(snap, name="Ask"))["structuredContent"]
        self.assertEqual(clicked["dialog"], {"type": "confirm", "message": "Proceed?"})
        self.assertFalse(c.call("dialog", tab=tab, accept=True)["isError"])
        self.assertTrue(
            harness.wait_until(lambda: "yes" in c.call("page_read", tab=tab)["structuredContent"]["text"], timeout=10)
        )
        self.assertIsNone(c.call("page_read", tab=tab)["structuredContent"]["dialog"])
        self.assertTrue(c.call("dialog", tab=tab, accept=False)["isError"])  # nothing open now

    def test_16_uploads_only_from_the_uploads_folder(self):
        agent, env = self.agent("autonomous")
        c = self.client(env)
        tab = c.call("tab_new", url=self.fx.url("/agent-upload"))["structuredContent"]["tab"]
        uploads = self.home / "data" / "ai" / "workspaces" / agent["id"] / "uploads"
        (uploads / "report.txt").write_text("artificial upload")
        field = self.element(c.call("page_snapshot", tab=tab), type="file")
        self.assertFalse(c.call("upload", tab=tab, element=field, file="report.txt")["isError"])
        self.assertTrue(
            harness.wait_until(lambda: "report.txt" in c.call("page_read", tab=tab)["structuredContent"]["text"], timeout=10)
        )
        self.assertIn("uploads folder", c.call("upload", tab=tab, element=field, file="missing.txt")["content"][0]["text"])
        traversal = c.call("upload", tab=tab, element=field, file="../profile/prefs.js")  # refused before anything runs
        self.assertTrue(traversal["isError"])
        self.assertIn("wrong format", traversal["content"][0]["text"])

    def test_17_authorised_profile_and_routes(self):
        agent, env = self.agent("autonomous")
        work = self.home / "user-profiles" / "work"
        work.mkdir(parents=True)
        # A profile the user already uses: Mozilla's own builds have had their Terms of Use accepted there.
        accepted = ('user_pref("termsofuse.acceptedVersion", 4);', 'user_pref("termsofuse.acceptedDate", "1761436800000");')
        (work / "prefs.js").write_text("\n".join(accepted) + "\n")
        registry.set_profiles(agent["id"], [{"label": "Trabalho", "path": str(work)}])
        registry.set_routes(agent["id"], [{"site": "127.0.0.1", "profile": "Trabalho"}])
        registry.grant(agent["id"], "execute_js", "allow")
        c = self.client(env)
        listed = c.call("profiles_list")["structuredContent"]
        self.assertEqual([p["profile"] for p in listed["profiles"]], ["AI Workspace", "Trabalho"])
        routed = c.call("tab_new", url=self.fx.url("/page/routed"))
        self.assertIn("structuredContent", routed, routed)
        routed = routed["structuredContent"]
        self.assertEqual(routed["profile"], "Trabalho")  # the site goes to the profile the user chose
        self.assertIn("nulavio-ai-temporary", (work / "user.js").read_text())
        self.assertTrue((work / "times.json").exists() or (work / "sessionstore-backups").exists())
        # Using the AI Workspace as well means working in two profiles: autonomous asks, nobody can answer.
        denied = c.call("tab_new")
        self.assertIn("more than one profile", denied["content"][0]["text"])
        registry.grant(agent["id"], "multiple_profiles", "allow")
        own = c.call("tab_new", url=self.fx.url("/page/ws"), profile="AI Workspace")["structuredContent"]
        self.assertEqual(own["profile"], "AI Workspace")
        by_profile = {t["tab"]: t["profile"] for t in c.call("tabs_list")["structuredContent"]["tabs"]}
        self.assertEqual(by_profile[routed["tab"]], "Trabalho")
        self.assertEqual(by_profile[own["tab"]], "AI Workspace")
        c.call("evaluate", tab=routed["tab"], expression="document.cookie = 'nvwork=1; path=/'")
        self.assertEqual(c.call("evaluate", tab=own["tab"], expression="document.cookie")["structuredContent"]["value"], "")
        c.close()
        self.assertFalse((work / "user.js").exists() and "nulavio-ai-temporary" in (work / "user.js").read_text())

    def test_18_profiles_the_agent_may_not_use(self):
        agent, env = self.agent("full_control")
        busy = self.home / "user-profiles" / "busy"
        busy.mkdir(parents=True)
        os.symlink(f"127.0.0.1:+{os.getpid()}", busy / "lock")  # open in one of the user's windows
        registry.set_profiles(agent["id"], [{"label": "Ocupado", "path": str(busy)}])
        c = self.client(env)
        self.assertIn("not one this agent may use", c.call("tab_new", profile="Pessoal")["content"][0]["text"])
        self.assertIn("is open in a window", c.call("tab_new", profile="Ocupado")["content"][0]["text"])
        if storage.tools_available() and sodium.available():
            locked = self.home / "user-profiles" / "banco"
            box = storage.Container(locked)
            box.root.mkdir(parents=True, mode=0o700)
            vault = Vault.create(box.vault_path)
            vault.add_password("artificial pass 12", {"ops": 1, "mem": 8 * 1024 * 1024})
            vault.save()
            box.init(vault)
            vault.lock()
            self.addCleanup(lambda: [os.chmod(d, 0o700) for d, _, _ in os.walk(locked.parent)])
            registry.set_profiles(agent["id"], [{"label": "Banco", "path": str(locked)}])
            result = c.call("tab_new", profile="Banco")
            self.assertIn("only the user can unlock it", result["content"][0]["text"])
            self.assertEqual(list(locked.iterdir()), [])  # nothing was written into the locked profile


if __name__ == "__main__":
    unittest.main()
