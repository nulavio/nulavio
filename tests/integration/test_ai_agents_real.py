"""Real agents through the AI Bridge: Claude Code and Codex CLI (opt-in: NULAVIO_AGENT_TESTS=1).

These runs use the developer's own Claude and ChatGPT accounts (and their
quota), so they never run in CI. Nothing in the agents' configuration is
changed: Claude Code gets the server with --mcp-config --strict-mcp-config
--restricted --no-session-persistence; Codex gets `-c` overrides with
--ignore-user-config --ephemeral. The agent works only on a local fixture
page with an artificial code word.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import harness

from nulavio_launcher.ai import audit, registry
from nulavio_launcher.ai.cli import client_config

ROOT = Path(__file__).resolve().parents[2]
ENABLED = os.environ.get("NULAVIO_AGENT_TESTS") == "1"
TASK = ("Use only the nulavio MCP tools. Open a new tab at {url}, type the word hello into the Query field and "
        "submit it, then read the resulting page. Reply with two lines: the code word from the first page, and "
        "the text of the result page. Then call the evaluate tool once with the expression 1+1 and say whether "
        "Nulavio allowed it.")  # fmt: skip


@unittest.skipUnless(ENABLED and harness.engine_available(), "opt-in: NULAVIO_AGENT_TESTS=1 and a Gecko engine")
class RealAgentsTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="nv-ai-real-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.home), "NULAVIO_AI_APPROVER": "none"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fx = harness.FixtureServer().__enter__()
        self.addCleanup(self.fx.__exit__, None, None, None)

    def register(self, client: str) -> tuple[dict, str]:
        agent, token = registry.add(client, client, "autonomous", disposable=True)
        registry.grant(agent["id"], "local_resources", "allow")  # the fixture runs on 127.0.0.1
        return agent, token

    def check(self, answer: str, agent: dict) -> None:
        self.assertIn("BASALT", answer)
        self.assertEqual(self.fx.requests_to("/agent-result"), ["/agent-result?q=hello"])
        everything = audit.read(agent=agent["id"])
        self.assertTrue([e for e in everything if e.get("event") == "connected"])
        entries = [e for e in everything if "tool" in e]
        tools = [e["tool"] for e in entries]
        self.assertIn("tab_new", tools)
        evaluate = [e for e in entries if e["tool"] == "evaluate"]
        self.assertTrue(evaluate and all(e["decision"] == "deny" for e in evaluate), entries)

    @unittest.skipUnless(shutil.which("claude"), "Claude Code is not installed")
    def test_claude_code(self):
        agent, token = self.register("claude-code")
        config = json.loads(client_config("claude-code", token, headless=True))
        config["mcpServers"]["nulavio"]["env"]["NULAVIO_AI_APPROVER"] = "none"
        path = self.home / "mcp.json"
        path.write_text(json.dumps(config))
        result = subprocess.run(
            ["claude", "-p", TASK.format(url=self.fx.url("/agent-task?word=BASALT")), "--model", "haiku",
             "--mcp-config", str(path), "--strict-mcp-config", "--restricted", "--tools", "",
             "--allowedTools", "mcp__nulavio", "--no-session-persistence", "--output-format", "json"],
            capture_output=True, text=True, timeout=300, cwd=str(ROOT), env={**os.environ, "MCP_TIMEOUT": "60000"},
        )  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stderr[-1000:])
        self.check(json.loads(result.stdout)["result"], agent)

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_codex_cli(self):
        agent, token = self.register("codex")
        env = {"NULAVIO_AGENT_TOKEN": token, "NULAVIO_HOME": str(self.home), "NULAVIO_AI_APPROVER": "none"}
        if os.environ.get("NULAVIO_ENGINE"):
            env["NULAVIO_ENGINE"] = os.environ["NULAVIO_ENGINE"]
        overrides = [
            f"mcp_servers.nulavio.command={json.dumps(str(ROOT / 'bin' / 'nulavio'))}",
            'mcp_servers.nulavio.args=["ai","serve","--headless"]',
            "mcp_servers.nulavio.env={" + ",".join(f"{k}={json.dumps(v)}" for k, v in env.items()) + "}",
            "mcp_servers.nulavio.startup_timeout_sec=60",
            "mcp_servers.nulavio.tool_timeout_sec=90",
            'mcp_servers.nulavio.default_tools_approval_mode="approve"',
        ]
        command = ["codex", "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
                   "-s", "read-only", "--color", "never", "-C", str(self.home)]  # fmt: skip
        for item in overrides:
            command += ["-c", item]
        last = self.home / "last.txt"
        result = subprocess.run([*command, "-o", str(last), TASK.format(url=self.fx.url("/agent-task?word=BASALT"))],
                                capture_output=True, text=True, timeout=400, stdin=subprocess.DEVNULL)  # fmt: skip
        if "usage limit" in result.stderr:
            self.skipTest("the ChatGPT account hit its usage limit")
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.check(last.read_text(), agent)


if __name__ == "__main__":
    unittest.main()
