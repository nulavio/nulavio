"""AI Bridge without the engine: MCP protocol, policy decisions, addresses, audit, WebSocket framing, CLI.

Engine-backed tests are in tests/integration/test_ai_bridge.py; real Claude Code
and Codex runs in tests/integration/test_ai_agents_real.py (opt-in).
"""

from __future__ import annotations

import base64
import contextlib
import datetime as _dt
import hashlib
import io
import json
import os
import re
import shutil
import socket
import struct
import tempfile
import threading
import time
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from nulavio_launcher.ai import audit, mcp, policy, registry, tools
from nulavio_launcher.ai import cli as ai_cli
from nulavio_launcher.ai.websocket import GUID, WebSocket, WebSocketError
from nulavio_launcher.ai.workspace import RAW_MARKER, WORKSPACE_PREFS, ProfileTarget, Workspace


class Home(unittest.TestCase):
    """Every test gets its own NULAVIO_HOME: nothing touches the real state."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="nv-ai-unit-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = mock.patch.dict(os.environ, {"NULAVIO_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.closed = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def list_tools(self):
        return [tools.descriptor(tools.BY_NAME["session_state"])]

    def call(self, name, arguments, cancel):
        self.started.set()
        self.release.wait(5)
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}

    def close(self):
        self.closed = True


def run_server(lines: list, bridge=None) -> list[dict]:
    raw = b"".join((json.dumps(m).encode() if not isinstance(m, bytes) else m) + b"\n" for m in lines)
    out = io.BytesIO()
    server = mcp.Server(bridge or FakeBridge(), io.BytesIO(raw), out)
    server.serve()
    return [json.loads(line) for line in out.getvalue().splitlines()]


def req(i, method, params=None):
    message = {"jsonrpc": "2.0", "id": i, "method": method}
    if params is not None:
        message["params"] = params
    return message


MODERN = {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}}
INIT = req(0, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})


class ProtocolTest(unittest.TestCase):
    def test_legacy_handshake_and_tools(self):
        out = run_server([INIT, {"jsonrpc": "2.0", "method": "notifications/initialized"}, req(1, "tools/list"),
                          req(2, "tools/call", {"name": "session_state", "arguments": {}}), req(3, "ping")])  # fmt: skip
        by_id = {m["id"]: m for m in out}
        self.assertEqual(by_id[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(by_id[0]["result"]["capabilities"], {"tools": {"listChanged": False}})
        self.assertNotIn("resultType", by_id[1]["result"])
        self.assertEqual(by_id[1]["result"]["tools"][0]["name"], "session_state")
        self.assertFalse(by_id[2]["result"]["isError"])
        self.assertEqual(by_id[3]["result"], {})

    def test_unknown_legacy_version_gets_the_newest_legacy_one(self):
        out = run_server([req(0, "initialize", {"protocolVersion": "1999-01-01"})])
        self.assertEqual(out[0]["result"]["protocolVersion"], mcp.LEGACY[0])

    def test_requests_before_initialize_are_refused(self):
        out = run_server([req(1, "tools/list")])
        self.assertEqual(out[0]["error"]["code"], -32600)

    def test_modern_discover_and_result_type(self):
        out = run_server([req(1, "server/discover", MODERN), req(2, "tools/list", MODERN)])
        self.assertEqual(out[0]["result"]["resultType"], "complete")
        self.assertIn("2026-07-28", out[0]["result"]["supportedVersions"])
        self.assertEqual(out[0]["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "nulavio")
        self.assertEqual(out[1]["result"]["resultType"], "complete")

    def test_modern_unsupported_version(self):
        params = {
            "_meta": {"io.modelcontextprotocol/protocolVersion": "1900-01-01", "io.modelcontextprotocol/clientCapabilities": {}}
        }
        out = run_server([req(1, "tools/list", params)])
        self.assertEqual(out[0]["error"]["code"], -32022)
        self.assertEqual(out[0]["error"]["data"]["requested"], "1900-01-01")
        self.assertIn("2026-07-28", out[0]["error"]["data"]["supported"])

    def test_modern_request_without_capabilities_is_malformed(self):
        params = {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}
        self.assertEqual(run_server([req(1, "tools/list", params)])[0]["error"]["code"], -32602)

    def test_malformed_input(self):
        out = run_server([b"{not json", b"[1, 2]", {"jsonrpc": "1.0", "id": 1, "method": "ping"},
                          {"jsonrpc": "2.0", "id": None, "method": "ping"}, req(5, "tools/list", [])])  # fmt: skip
        self.assertEqual([m["error"]["code"] for m in out], [-32700, -32600, -32600, -32600, -32602])

    def test_unknown_method_and_tool(self):
        out = run_server([INIT, req(1, "resources/list"), req(2, "tools/call", {"name": "shell", "arguments": {}}),
                          req(3, "tools/call", {"name": "session_state", "arguments": "x"})])  # fmt: skip
        codes = {m["id"]: m.get("error", {}).get("code") for m in out}
        self.assertEqual((codes[1], codes[2], codes[3]), (-32601, -32602, -32602))

    def test_oversized_message_is_dropped_and_the_server_continues(self):
        huge = b'{"jsonrpc":"2.0","id":9,"method":"ping","params":{"x":"' + b"a" * (mcp.MAX_LINE + 10) + b'"}}'
        out = run_server([huge, INIT, req(1, "ping")])
        self.assertEqual(out[0]["error"]["code"], -32600)
        self.assertEqual(out[-1]["id"], 1)

    def test_stdout_carries_only_json_lines(self):
        raw = json.dumps(INIT).encode() + b"\n" + json.dumps(req(1, "tools/list")).encode() + b"\n"
        out = io.BytesIO()
        mcp.Server(FakeBridge(), io.BytesIO(raw), out).serve()
        for line in out.getvalue().splitlines():
            json.loads(line)
        self.assertTrue(out.getvalue().endswith(b"\n"))

    def test_cancelled_before_start_gets_no_response(self):
        bridge = FakeBridge()
        bridge.release.clear()
        server_in_r, server_in_w = os.pipe()
        out = io.BytesIO()
        server = mcp.Server(bridge, os.fdopen(server_in_r, "rb"), out)
        thread = threading.Thread(target=server.serve)
        thread.start()
        w = os.fdopen(server_in_w, "wb")
        for message in (INIT, req(1, "tools/call", {"name": "session_state", "arguments": {}}),
                        req(2, "tools/call", {"name": "session_state", "arguments": {}}),
                        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}}):  # fmt: skip
            w.write(json.dumps(message).encode() + b"\n")
            w.flush()
        bridge.started.wait(5)
        # Let request 1 finish only once the server has read the cancellation of request 2 (under load
        # the reader thread can lag behind the writes above).
        deadline = time.monotonic() + 5
        while not (server._cancels.get(2) and server._cancels[2].is_set()) and time.monotonic() < deadline:
            time.sleep(0.01)
        bridge.release.set()
        w.close()
        thread.join(10)
        ids = [json.loads(line).get("id") for line in out.getvalue().splitlines()]
        self.assertEqual(ids, [0, 1])
        self.assertEqual(len(bridge.calls), 1)
        self.assertTrue(bridge.closed)

    def test_no_tool_edits_policy(self):
        names = {t.name for t in tools.TOOLS}
        self.assertFalse({n for n in names if any(w in n for w in ("grant", "permission", "policy", "autonomy", "revoke"))})
        for tool in tools.TOOLS:
            self.assertFalse(tool.schema.get("additionalProperties", True), tool.name)


class SchemaTest(unittest.TestCase):
    def test_arguments_are_strict(self):
        schema = tools.BY_NAME["type"].schema
        good = {"tab": "abc-1", "element": "e3", "text": "hi"}
        tools.validate(schema, good)
        for bad in ({**good, "extra": 1}, {"tab": "abc"}, {**good, "tab": "../x"}, {**good, "element": "x1"},
                    {**good, "text": "a" * 5001}, {**good, "submit": "yes"}):  # fmt: skip
            with self.assertRaises(tools.ToolError):
                tools.validate(schema, bad)
        with self.assertRaises(tools.ToolError):
            tools.validate(tools.BY_NAME["page_read"].schema, {"tab": "a", "max_chars": True})
        with self.assertRaises(tools.ToolError):
            tools.validate(tools.BY_NAME["page_read"].schema, {"tab": "a", "max_chars": 10})


class AddressTest(unittest.TestCase):
    def test_public_sites_need_nothing_extra(self):
        self.assertEqual(policy.classify_url("https://example.org/a?b=c", resolve=False).needs, ())
        self.assertEqual(policy.classify_url("about:blank").needs, ())

    def test_local_network_needs_local_resources(self):
        for url in ("http://127.0.0.1:8080/", "http://localhost/", "http://10.0.0.5/", "http://192.168.1.1/",
                    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fd00::1]/", "http://printer.local/",
                    "http://router.lan/", "http://box.home.arpa/", "http://0.0.0.0/"):  # fmt: skip
            self.assertIn("local_resources", policy.classify_url(url, resolve=False).needs, url)

    def test_names_that_resolve_locally(self):
        with mock.patch.object(policy.socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("10.1.2.3", 0))]):
            self.assertIn("local_resources", policy.classify_url("https://intranet.example.com/").needs)

    def test_internal_pages(self):
        self.assertEqual(policy.classify_url("file:///etc/hostname").needs, ("local_resources",))
        self.assertEqual(policy.classify_url("about:config").needs, ("local_resources", "debugging"))
        self.assertEqual(policy.classify_url("chrome://browser/content/browser.xhtml").needs, ("local_resources", "debugging"))

    def test_refused(self):
        for url in ("javascript:alert(1)", "data:text/html,hi", "https://user:pw@example.org/", "http:///x",
                    "https://example.org/\nx", "ftp://example.org/", "x" * 9000):  # fmt: skip
            with self.assertRaises(policy.UrlRefused, msg=url):
                policy.classify_url(url, resolve=False)

    def test_forms_the_engine_reads_differently_are_refused_or_classified_alike(self):
        # Audit A1 (2026-11-10): Python's parser and the engine's disagreed on these hosts.
        for url in ("http://192.168.1.1\\.x.example/", "http://%31%32%37.0.0.1:8080/", "http://evil.example\\.intranet.example/",
                    "http://1.2.3.4.5/", "http://999.1/"):  # fmt: skip
            with self.assertRaises(policy.UrlRefused, msg=url):
                policy.classify_url(url, resolve=False)
        for url in ("http://127.1/", "http://0x7f.0.0.1/", "http://0177.0.0.1/", "http://2130706433/", "http://１２７.0.0.1/",
                    "http://localhost./", "http://10.0.0.1./", "http://[::ffff:127.0.0.1]/"):  # fmt: skip
            self.assertIn("local_resources", policy.classify_url(url, resolve=False).needs, url)
        self.assertEqual(policy.classify_url("http://[::ffff:8.8.8.8]/", resolve=False).needs, ())

    def test_a_name_that_does_not_resolve_here_counts_as_local(self):
        # The engine may resolve it where this process cannot (DoH, a proxy).
        with mock.patch.object(policy.socket, "getaddrinfo", side_effect=OSError("no answer")):
            self.assertIn("local_resources", policy.classify_url("https://nas.example/").needs)

    def test_the_shells_own_pages_need_raw_automation(self):
        # Audit A2: Settings, Vault and profile pages were reachable with local_resources alone.
        for url in ("moz-extension://0e3a/settings/settings.html#profiles", "moz-extension://0e3a/vault/unlock.html",
                    "view-source:https://example.org/"):  # fmt: skip
            self.assertEqual(policy.classify_url(url).needs, ("local_resources", "debugging"), url)

    def test_origin_drops_path_and_query(self):
        self.assertEqual(policy.origin("https://bank.example:8443/acct?id=123#x"), "https://bank.example:8443")
        self.assertEqual(policy.origin("file:///home/me/secret.txt"), "file:")


class Approve(registry.Approver):
    def __init__(self, answer, meanwhile=None):
        self.answer = answer
        self.asked = []
        self.places = []
        self.meanwhile = meanwhile  # what the user does while the prompt is open

    def ask(self, agent, capability, target, place="", cancel=None):
        self.asked.append((capability, target))
        self.places.append(place)
        if self.meanwhile:
            self.meanwhile()
        return self.answer


class PolicyTest(Home):
    def decide(self, agent_id, capability, approver=None, host=None, session="s-1"):
        return registry.decide(
            agent_id, capability, host=host, target=None, session_id=session, approver=approver or registry.Approver()
        )

    def test_presets(self):
        expect = {
            "restricted": {"read_pages": True, "interact": False, "execute_js": False, "submit_forms": False},
            "assisted": {"interact": True, "submit_forms": False, "execute_js": False},
            "autonomous": {"interact": True, "submit_forms": True, "files": True, "transactions": False, "execute_js": False},
            # Everything but raw automation, which is a separate opt-in (ADR 0007, 2026-10-28).
            "full_control": {c: c != policy.RAW_CAPABILITY for c in policy.CAPABILITIES},
        }
        for level, caps in expect.items():
            agent, _ = registry.add(level, "other", level, accept_full_control=True)
            for capability, allowed in caps.items():
                self.assertEqual(self.decide(agent["id"], capability).allowed, allowed, f"{level}/{capability}")

    def test_autonomous_does_not_ask_for_what_it_covers(self):
        agent, _ = registry.add("auto", "other", "autonomous")
        approver = Approve("deny")
        for capability in ("read_pages", "navigate", "interact", "submit_forms", "files", "screenshots"):
            self.assertTrue(self.decide(agent["id"], capability, approver).allowed)
        self.assertEqual(approver.asked, [])

    def test_ask_answers(self):
        agent, _ = registry.add("ask", "other", "restricted")
        self.assertEqual(self.decide(agent["id"], "interact").reason, "no-approver")
        self.assertEqual(self.decide(agent["id"], "interact", Approve("deny")).reason, "denied")
        self.assertTrue(self.decide(agent["id"], "interact", Approve("once")).allowed)
        self.assertEqual(self.decide(agent["id"], "interact").reason, "no-approver")  # once means once
        self.assertTrue(self.decide(agent["id"], "interact", Approve("session"), session="s-1").allowed)
        self.assertEqual(self.decide(agent["id"], "interact", session="s-1").reason, "session-grant")
        self.assertEqual(self.decide(agent["id"], "interact", session="s-2").reason, "no-approver")  # another session

    def test_session_answers_never_replace_the_users_grant(self):
        """UX5-0: an explicit "ask", then "allow until the agent disconnects", then a new session asks again."""
        agent, _ = registry.add("keep", "other", "autonomous")  # its level allows interact
        registry.grant(agent["id"], "interact", "ask")
        self.assertTrue(self.decide(agent["id"], "interact", Approve("session"), session="s-1").allowed)
        self.assertEqual(registry.get(agent["id"])["grants"]["interact"]["mode"], "ask")  # untouched
        self.assertEqual(self.decide(agent["id"], "interact", session="s-1").reason, "session-grant")
        later = Approve("deny")
        self.assertEqual(self.decide(agent["id"], "interact", later, session="s-2").reason, "denied")
        self.assertEqual(later.asked, [("interact", None)])  # asked again, not the level's "allow"
        # The bridge's end takes the session's answers with it; what the user sets replaces them.
        registry.end_session(agent["id"], "s-1")
        self.assertEqual(registry.get(agent["id"])["session_grants"], {})
        self.assertTrue(self.decide(agent["id"], "interact", Approve("session"), session="s-3").allowed)
        registry.grant(agent["id"], "interact", "block")
        self.assertEqual(self.decide(agent["id"], "interact", session="s-3").reason, "grant")
        registry.grant(agent["id"], "interact", "ask")
        self.assertTrue(self.decide(agent["id"], "interact", Approve("session"), session="s-3").allowed)
        registry.set_autonomy(agent["id"], "restricted")
        self.assertEqual(self.decide(agent["id"], "interact", session="s-3").reason, "no-approver")

    def test_answers_after_a_stop_pause_or_revoke_do_nothing(self):
        """UX5-0: the prompt was open when the user stopped, paused, revoked or blocked: "allow" does nothing."""
        cases = (
            ("stopped", lambda a: registry.set_stopped(True)),
            ("paused", lambda a: registry.pause(a, True)),
            ("revoked", lambda a: registry.revoke(a)),
            ("grant", lambda a: registry.grant(a, "interact", "block")),
            ("out-of-scope", lambda a: registry.set_domains(a, ["other.example"])),
        )
        for reason, act in cases:
            for answer in ("once", "session"):
                with self.subTest(reason=reason, answer=answer):
                    agent, _ = registry.add("late", "other", "restricted")
                    approver = Approve(answer, meanwhile=lambda a=agent["id"], act=act: act(a))
                    decision = self.decide(agent["id"], "interact", approver, host="example.org")
                    self.assertEqual((decision.allowed, decision.reason), (False, reason))
                    self.assertNotIn("interact", registry.get(agent["id"]).get("session_grants", {}))
                    registry.set_stopped(False)

    def test_grants_override_presets_and_persist(self):
        agent, _ = registry.add("g", "other", "assisted")
        registry.grant(agent["id"], "execute_js", "allow")
        registry.grant(agent["id"], "navigate", "block")
        self.assertTrue(self.decide(agent["id"], "execute_js").allowed)
        self.assertFalse(self.decide(agent["id"], "navigate").allowed)
        # A new process reads the same file: the grant survives a restart.
        self.assertEqual(
            json.loads((self.home / "state" / "ai" / "agents.json").read_text())["agents"][agent["id"]]["grants"]["execute_js"][
                "mode"
            ],
            "allow",
        )

    def test_temporary_grant_expires(self):
        agent, _ = registry.add("t", "other", "assisted")
        registry.grant(agent["id"], "execute_js", "allow", minutes=5)
        self.assertTrue(self.decide(agent["id"], "execute_js").allowed)
        later = policy.now() + _dt.timedelta(minutes=6)
        with mock.patch.object(policy, "now", return_value=later):
            self.assertFalse(self.decide(agent["id"], "execute_js").allowed)

    def test_agents_do_not_share_permissions(self):
        a, token_a = registry.add("a", "other", "assisted")
        b, token_b = registry.add("b", "other", "assisted")
        registry.grant(a["id"], "execute_js", "allow")
        self.assertTrue(self.decide(a["id"], "execute_js").allowed)
        self.assertFalse(self.decide(b["id"], "execute_js").allowed)
        self.assertEqual(registry.by_token(token_b)["id"], b["id"])
        self.assertIsNone(registry.by_token(token_a + "x"))
        self.assertIsNone(registry.by_token(None))
        self.assertNotIn(token_a, (self.home / "state" / "ai" / "agents.json").read_text())

    def test_revocation_and_emergency_stop(self):
        agent, _ = registry.add("r", "other", "full_control", accept_full_control=True)
        registry.set_stopped(True)
        self.assertEqual(self.decide(agent["id"], "read_pages").reason, "stopped")
        registry.set_stopped(False)
        self.assertTrue(self.decide(agent["id"], "read_pages").allowed)
        registry.revoke(agent["id"])
        self.assertEqual(self.decide(agent["id"], "read_pages").reason, "revoked")

    def test_site_scope(self):
        agent, _ = registry.add("s", "other", "autonomous", domains=["Example.org"])
        self.assertTrue(self.decide(agent["id"], "navigate", host="docs.example.org").allowed)
        self.assertEqual(self.decide(agent["id"], "navigate", host="example.org.evil.test").reason, "out-of-scope")
        self.assertEqual(self.decide(agent["id"], "navigate", host="notexample.org").reason, "out-of-scope")

    def test_full_control_needs_acceptance(self):
        with self.assertRaises(registry.RegistryError) as caught:
            registry.add("f", "other", "full_control")
        self.assertEqual(caught.exception.code, "full-control-not-accepted")
        agent, _ = registry.add("x", "other", "assisted")
        with self.assertRaises(registry.RegistryError):
            registry.set_autonomy(agent["id"], "full_control")

    def test_raw_automation_is_a_separate_opt_in(self):
        """D-UX4 / SB-03: no level includes raw automation; it needs its own confirmation, per agent."""
        raw = policy.RAW_CAPABILITY
        for level in policy.PRESETS:
            self.assertEqual(policy.PRESETS[level][raw], "block", level)
        agent, _ = registry.add("full", "other", "full_control", accept_full_control=True)
        self.assertEqual(self.decide(agent["id"], raw).reason, "raw-automation-off")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        self.assertNotIn("raw_automation", {t["name"] for t in bridge.list_tools()})
        for mode in ("allow", "ask"):  # without the warning, neither turns it on
            with self.assertRaises(registry.RegistryError) as caught:
                registry.grant(agent["id"], raw, mode)
            self.assertEqual(caught.exception.code, "raw-automation-not-accepted")
        self.assertFalse(self.decide(agent["id"], raw).allowed)
        registry.set_raw_automation(agent["id"], True, accept=True)
        self.assertTrue(registry.get(agent["id"])["raw_automation_accepted"])
        self.assertTrue(self.decide(agent["id"], raw).allowed)
        self.assertIn("raw_automation", {t["name"] for t in bridge.list_tools()})
        registry.set_raw_automation(agent["id"], False)
        self.assertIsNone(registry.get(agent["id"])["raw_automation_accepted"])
        self.assertEqual(self.decide(agent["id"], raw).reason, "raw-automation-off")
        with self.assertRaises(registry.RegistryError):  # turning it on again shows the warning again
            registry.set_raw_automation(agent["id"], True)
        registry.grant(agent["id"], raw, "ask", accept_raw_automation=True)
        registry.grant(agent["id"], raw, "block")
        self.assertIsNone(registry.get(agent["id"])["raw_automation_accepted"])

    def test_registries_from_before_the_opt_in_lose_raw_automation(self):
        """Tightening: a Full control agent, or a grant given without the new warning, no longer has it."""
        agent, _ = registry.add("old", "other", "full_control", accept_full_control=True)
        path = self.home / "state" / "ai" / "agents.json"
        data = json.loads(path.read_text())
        data["agents"][agent["id"]]["grants"][policy.RAW_CAPABILITY] = {"mode": "allow", "set": "2026-10-27T10:00:00+00:00",
                                                                        "until": None, "session": None}  # fmt: skip
        path.write_text(json.dumps(data))
        self.assertEqual(self.decide(agent["id"], policy.RAW_CAPABILITY).reason, "raw-automation-off")
        # Privileged pages are under the same option: Full control alone does not open about:config.
        self.assertIn(policy.RAW_CAPABILITY, policy.classify_url("about:config").needs)

    def test_every_capability_has_a_risk_tier(self):
        self.assertEqual(set(policy.RISK), set(policy.CAPABILITIES))
        self.assertTrue(set(policy.RISK.values()) <= {"critical", "warning", "info"})
        for capability in ("transactions", "execute_js", "local_resources", "private_tabs", "multiple_profiles",
                           policy.RAW_CAPABILITY):  # fmt: skip
            self.assertEqual(policy.RISK[capability], "critical", capability)
        for capability in ("interact", "submit_forms", "files"):
            self.assertEqual(policy.RISK[capability], "warning", capability)
        for capability in ("read_pages", "navigate", "screenshots"):
            self.assertEqual(policy.RISK[capability], "info", capability)

    def test_requests_say_where_the_agent_acts(self):
        agent, _ = registry.add("where", "other", "restricted")
        approver = Approve("deny")
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        bridge.owner = {"t1": "Trabalho", "t2": ""}
        for tab in ("t1", "t2"):
            bridge.elements[tab] = {"e1": "shared-1"}
        with mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"):
            self.assertTrue(bridge.call("click", {"tab": "t1", "element": "e1"})["isError"])
            self.assertTrue(bridge.call("click", {"tab": "t2", "element": "e1"})["isError"])
        self.assertEqual(approver.places, ["Trabalho", ""])  # one of the user's profiles, then the AI Workspace

    def test_bad_input(self):
        for kwargs in ({"name": "a/b"}, {"client": "mystery"}, {"autonomy": "god"}, {"domains": ["exa mple.org"]}):
            args = {"name": "ok", "client": "other", "autonomy": "assisted", **kwargs}
            with self.assertRaises(registry.RegistryError):
                registry.add(args.pop("name"), args.pop("client"), args.pop("autonomy"), **args)
        agent, _ = registry.add("ok", "other", "assisted")
        with self.assertRaises(registry.RegistryError):
            registry.grant(agent["id"], "root_access", "allow")

    def test_tool_list_hides_blocked_tools(self):
        agent, _ = registry.add("l", "other", "restricted")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        names = {t["name"] for t in bridge.list_tools()}
        self.assertNotIn("evaluate", names)
        self.assertIn("page_read", names)
        registry.revoke(agent["id"])
        self.assertEqual([t["name"] for t in bridge.list_tools()], ["session_state"])

    def test_kdialog_approver(self):
        fake = self.home / "kdialog"
        fake.write_text('#!/bin/sh\nexit "$NV_ANSWER"\n')
        fake.chmod(0o700)
        agent, _ = registry.add("k", "other", "restricted")
        approver = registry.KDialogApprover(str(fake))
        with mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
            for code, answer in (("0", "once"), ("1", "session"), ("2", "deny")):
                with mock.patch.dict(os.environ, {"NV_ANSWER": code}):
                    self.assertEqual(approver.ask(registry.get(agent["id"]), "interact", "https://example.org"), answer)
        with mock.patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
            self.assertIsNone(approver.ask(registry.get(agent["id"]), "interact", None))
        with mock.patch.dict(os.environ, {"NULAVIO_AI_APPROVER": "none", "DISPLAY": ":0"}):
            self.assertEqual(type(registry.default_approver()), registry.Approver)


class AuditTest(Home):
    def test_allow_list_and_rotation(self):
        with self.assertRaises(ValueError):
            audit.record(tool="type", text="secret")
        audit.record(tool="navigate", target=policy.origin("https://example.org/private?token=abc"))
        entry = audit.read()[-1]
        self.assertEqual(entry["target"], "https://example.org")
        self.assertNotIn("token=abc", audit.audit_path().read_text())
        self.assertEqual(os.stat(audit.audit_path()).st_mode & 0o777, 0o600)
        with mock.patch.object(audit, "MAX_BYTES", 10):
            audit.record(tool="a")
            audit.record(tool="b")
        self.assertTrue(audit.audit_path().with_suffix(".jsonl.1").exists())

    def test_tools_check_where_the_tab_is_now(self):
        # Audit A1/A2: a redirect or the page's own navigation put the tab where navigate would
        # have asked; reading it, or acting on it, now needs the same capabilities.
        def at(url, **more):
            stack = contextlib.ExitStack()
            stack.enter_context(mock.patch.object(tools.Bridge, "_url_of", return_value=url))
            for name in ("_eval", "_call_fn", "bidi"):
                patch = {"return_value": more[name]} if name in more else {"side_effect": AssertionError("ran")}
                stack.enter_context(mock.patch.object(tools.Bridge, name, **patch))
            stack.enter_context(mock.patch.object(tools.Bridge, "_open_dialog", return_value=None))
            return stack

        agent, _ = registry.add("here", "other", "full_control", accept_full_control=True)
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        bridge.elements["t1"] = {"e1": "shared-1"}
        calls = (
            ("page_read", {"tab": "t1"}),
            ("screenshot", {"tab": "t1"}),
            ("click", {"tab": "t1", "element": "e1"}),
            ("evaluate", {"tab": "t1", "expression": "1"}),
        )
        for url in ("moz-extension://0e3a/settings/settings.html#profiles", "about:config"):
            for name, args in calls:
                with self.subTest(url=url, tool=name), at(url):
                    result = bridge.call(name, args)
                    self.assertTrue(result["isError"], result)
                    entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                    self.assertEqual(entry["decision"], "deny")
                    self.assertIn("debugging", json.dumps(entry))
        restricted, _ = registry.add("near", "other", "restricted")
        bridge = tools.Bridge(restricted["id"], "s-1", approver=registry.Approver())
        with at("http://192.168.1.1/"):
            self.assertTrue(bridge.call("page_read", {"tab": "t1"})["isError"])
        page = {"text": "ok", "url": "https://example.org/", "title": "t"}
        with at("https://example.org/", _eval=page):
            self.assertFalse(bridge.call("page_read", {"tab": "t1"})["isError"])

    def test_typing_cannot_send_a_form_without_submit_forms(self):
        # Audit A3: U+E007 is Enter for WebDriver, and Enter in a single-line field sends the form.
        agent, _ = registry.add("typist", "other", "assisted")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        bridge.elements["t1"] = {"e1": "shared-1"}
        single = {"connected": True, "editable": True, "multiline": False}
        with (
            mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"),
            mock.patch.object(tools.Bridge, "_call_fn", return_value=single) as call_fn,
            mock.patch.object(tools.Bridge, "bidi", side_effect=AssertionError("typed")),
        ):
            result = bridge.call("type", {"tab": "t1", "element": "e1", "text": "x\ue007"})
            self.assertIn("special keys", result["content"][0]["text"])
            call_fn.assert_not_called()
            result = bridge.call("type", {"tab": "t1", "element": "e1", "text": "x\n"})
            self.assertTrue(result["isError"])
            entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
            self.assertIn("submit_forms", json.dumps(entry))

    def test_an_approval_does_not_follow_the_tab_to_another_site(self):
        # Audit A4: the page navigated while the request was open; the action ran on the new site.
        agent, _ = registry.add("js", "other", "full_control", accept_full_control=True)
        registry.grant(agent["id"], "execute_js", "allow")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        with (
            mock.patch.object(tools.Bridge, "_url_of", side_effect=["https://blog.example/", "https://bank.example/"]),
            mock.patch.object(tools.Bridge, "_eval", side_effect=AssertionError("ran")),
        ):
            result = bridge.call("evaluate", {"tab": "t1", "expression": "1"})
        self.assertIn("moved to https://bank.example", result["content"][0]["text"])

    def test_denied_call_is_audited_without_arguments(self):
        agent, _ = registry.add("d", "other", "assisted")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        with mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/inbox?msg=42"):
            result = bridge.call("evaluate", {"tab": "t1", "expression": "document.cookie + 'TOPSECRET'"})
        self.assertTrue(result["isError"])
        self.assertIn("Only the user can change this", result["content"][0]["text"])
        text = audit.audit_path().read_text()
        entry = json.loads(text.splitlines()[-1])
        self.assertEqual(
            (entry["decision"], entry["reason"], entry["target"]), ("deny", "preset:assisted", "https://example.org")
        )
        self.assertEqual(entry["input_chars"], len("document.cookie + 'TOPSECRET'"))
        self.assertNotIn("TOPSECRET", text)
        self.assertNotIn("msg=42", text)


class WorkspaceTest(Home):
    def test_engine_ends_with_the_bridge(self):
        from nulavio_launcher.ai import workspace

        with mock.patch.object(workspace.shutil, "which", return_value="/usr/bin/setpriv") as which:
            self.assertEqual(workspace.die_with_parent(), ["/usr/bin/setpriv", "--pdeathsig", "TERM", "--"])
        self.assertEqual(which.call_args.kwargs["path"], "/usr/bin:/bin")  # never a setpriv from the user's PATH
        with mock.patch.object(workspace.shutil, "which", return_value=None):
            self.assertEqual(workspace.die_with_parent(), [])

    def test_command_and_prefs(self):
        engine = mock.Mock(path=Path("/opt/engine/nulavio"))
        ws = Workspace("ag-1", engine=engine, headless=True)
        command = ws.command()
        self.assertIn("--remote-debugging-port=0", command)
        self.assertIn("--no-remote", command)
        for flag in ("--marionette", "--remote-allow-system-access", "--remote-allow-hosts", "--remote-allow-origins",
                     "--start-debugger-server", "-start-debugger-server"):  # fmt: skip
            self.assertNotIn(flag, command)
        ws._write_prefs()
        user_js = (ws.profile_dir / "user.js").read_text()
        self.assertIn('user_pref("remote.prefs.recommended", false);', user_js)
        self.assertIn('user_pref("dom.security.https_only_mode", true);', user_js)  # the baseline is included
        self.assertNotIn("safebrowsing", user_js)  # Safe Browsing keeps the engine defaults (on)
        self.assertNotIn("@", user_js)
        self.assertEqual(user_js.count("browser.aboutwelcome.enabled"), 1)
        self.assertFalse(set(WORKSPACE_PREFS) - set(re.findall(r'user_pref\("([^"]+)"', user_js)))
        self.assertTrue(str(ws.profile_dir).startswith(str(self.home)))
        self.assertIn('user_pref("nulavio.ai.target", "workspace");', user_js)

    def test_raw_marker_for_the_window(self):
        """WCS-01: the hand-over is written where the Shell in the AI Workspace can see it, and never outlives it."""
        agent, _ = registry.add("raw", "other", "autonomous")
        registry.set_raw_automation(agent["id"], True, accept=True)
        ws = Workspace(agent["id"], engine=mock.Mock(path=Path("/x")))
        (ws.profile_dir).mkdir(parents=True, exist_ok=True)
        (ws.profile_dir / RAW_MARKER).write_text("{}")  # left by a bridge that was killed
        ws._write_prefs()
        self.assertFalse((ws.profile_dir / RAW_MARKER).exists())
        fake = mock.Mock()
        ws.port = 4444

        def start():
            ws.bidi = fake
            return fake

        ws.start = start
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver(), workspace_factory=lambda a: ws)
        result = bridge.call("raw_automation", {})
        self.assertFalse(result["isError"], result)
        marker = json.loads((ws.profile_dir / RAW_MARKER).read_text())
        self.assertEqual((marker["agent"], marker["pid"]), (agent["id"], os.getpid()))
        self.assertEqual(os.stat(ws.profile_dir / RAW_MARKER).st_mode & 0o777, 0o600)
        bridge.close()
        self.assertFalse((ws.profile_dir / RAW_MARKER).exists())

    def test_profile_target_says_it_is_the_users_profile(self):
        """WCS-02 / AI-06: a profile opened for an agent is marked as the user's, by name, and only temporarily."""
        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        (folder / "user.js").write_text('user_pref("browser.startup.page", 3);\n')
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        user_js = (folder / "user.js").read_text()
        self.assertIn('user_pref("nulavio.ai.target", "profile");', user_js)
        self.assertIn('user_pref("nulavio.ai.target.label", "Trabalho");', user_js)
        target._remove_temporary()
        self.assertEqual((folder / "user.js").read_text(), 'user_pref("browser.startup.page", 3);\n')

    def test_disposable_workspace_is_deleted(self):
        ws = Workspace("ag-2", disposable=True, engine=mock.Mock(path=Path("/x")))
        self.assertTrue(ws.dir.exists())
        ws.stop()
        self.assertFalse(ws.dir.exists())


class WebSocketTest(unittest.TestCase):
    """Framing against a tiny local server: handshake, masking, fragments, ping, size limit."""

    def serve(self, frames: list[bytes]):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        received = []

        def run():
            conn, _ = listener.accept()
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            key = next(
                line.split(":", 1)[1].strip()
                for line in data.decode().split("\r\n")
                if line.lower().startswith("sec-websocket-key")
            )
            accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()  # noqa: S324
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode()
            )
            for frame in frames:
                conn.sendall(frame)
            conn.settimeout(2)
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    received.append(chunk)
            except OSError:
                pass
            conn.close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return listener.getsockname()[1], received, thread

    @staticmethod
    def frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
        head = bytes([(0x80 if fin else 0) | opcode])
        n = len(payload)
        head += (
            bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536 else bytes([127]) + struct.pack(">Q", n)
        )
        return head + payload

    def test_fragments_and_ping(self):
        frames = [self.frame(0x9, b"hi"), self.frame(0x1, b'{"a":', fin=False), self.frame(0x0, b"1}"),
                  self.frame(0x1, b"x" * 70000)]  # fmt: skip
        port, received, thread = self.serve(frames)
        ws = WebSocket("127.0.0.1", port)
        self.assertEqual(ws.recv_text(), '{"a":1}')
        self.assertEqual(len(ws.recv_text()), 70000)
        ws.send_text("hello")
        ws.close()
        thread.join(5)
        data = b"".join(received)
        self.assertEqual(data[0], 0x8A)  # pong first
        self.assertTrue(data[1] & 0x80)  # client frames are masked

    def test_size_limit_and_remote_hosts(self):
        port, _, thread = self.serve([self.frame(0x1, b"y" * 2000)])
        ws = WebSocket("127.0.0.1", port, max_message=1000)
        with self.assertRaises(WebSocketError):
            ws.recv_text()
        thread.join(5)
        with self.assertRaises(WebSocketError):
            WebSocket("192.0.2.1", 9)


class CliTest(Home):
    def test_printed_configs_are_valid_and_nothing_else_is_written(self):
        before = set(Path.home().glob(".codex/*")) | set(Path.home().glob(".claude.json"))
        codex = tomllib.loads(ai_cli.client_config("codex", "tok-123"))
        self.assertEqual(codex["mcp_servers"]["nulavio"]["args"], ["ai", "serve"])
        self.assertEqual(codex["mcp_servers"]["nulavio"]["env"]["NULAVIO_AGENT_TOKEN"], "tok-123")
        claude = json.loads(ai_cli.client_config("claude-code", "tok-123", headless=True))
        self.assertEqual(claude["mcpServers"]["nulavio"]["args"], ["ai", "serve", "--headless"])
        self.assertEqual(before, set(Path.home().glob(".codex/*")) | set(Path.home().glob(".claude.json")))

    def test_serve_refuses_unknown_tokens(self):
        from nulavio_launcher.cli import main

        with mock.patch.dict(os.environ, {"NULAVIO_AGENT_TOKEN": "nope"}), mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(main(["ai", "serve", "--headless"]), 2)

    def test_full_control_flag(self):
        from nulavio_launcher.cli import main

        with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(main(["ai", "add", "F", "--client", "other", "--autonomy", "full-control"]), 1)
            self.assertIn("irreversible", err.getvalue())
            self.assertIn("Raw automation is not included", err.getvalue())
            self.assertEqual(
                main(["ai", "add", "F", "--client", "other", "--autonomy", "full-control", "--accept-full-control"]), 0
            )

    def test_raw_automation_flag(self):
        from nulavio_launcher.cli import main

        agent, _ = registry.add("R", "other", "full_control", accept_full_control=True)
        with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(main(["ai", "grant", agent["id"], "debugging", "allow"]), 1)
            self.assertIn("does not check, ask about or record", err.getvalue())
            self.assertFalse(registry.get(agent["id"]).get("raw_automation_accepted"))
            self.assertEqual(main(["ai", "grant", agent["id"], "debugging", "allow", "--accept-raw-automation"]), 0)
        self.assertTrue(registry.get(agent["id"])["raw_automation_accepted"])


class AutonomyControlsTest(Home):
    """S7: pause, new key, client evidence, approvals in the browser, activity retention, the Settings API."""

    def decide(self, agent_id, capability, approver=None):
        return registry.decide(
            agent_id, capability, host=None, target=None, session_id="s-1", approver=approver or registry.Approver()
        )

    def test_pause_and_resume(self):
        agent, _ = registry.add("p", "other", "full_control", accept_full_control=True)
        registry.pause(agent["id"], True)
        self.assertEqual(self.decide(agent["id"], "read_pages").reason, "paused")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        self.assertEqual([t["name"] for t in bridge.list_tools()], ["session_state"])
        registry.pause(agent["id"], False)
        self.assertTrue(self.decide(agent["id"], "read_pages").allowed)

    def test_new_key_replaces_the_old_one(self):
        agent, old = registry.add("k", "codex", "assisted")
        new = registry.rotate_token(agent["id"])
        self.assertIsNone(registry.by_token(old))
        self.assertEqual(registry.by_token(new)["id"], agent["id"])

    def test_client_evidence(self):
        agent, _ = registry.add("c", "claude-code", "assisted")
        self.assertTrue(registry.record_client(agent["id"], "claude"))
        self.assertFalse(registry.record_client(agent["id"], "python3"))
        self.assertFalse(registry.get(agent["id"])["last_client"]["matches"])
        other, _ = registry.add("o", "other", "assisted")
        self.assertTrue(registry.record_client(other["id"], "anything"))

    def answer_when_seen(self, answer, delay=0.1):
        def run():
            folder = registry.requests_dir()
            for _ in range(100):
                pending = list(folder.glob("*.json"))
                if pending:
                    request = pending[0]
                    request.with_suffix(".seen").touch()
                    time.sleep(delay)
                    registry.answer_request(request.stem, answer)
                    return
                time.sleep(0.05)

        thread = threading.Thread(target=run)
        thread.start()
        return thread

    def test_browser_approver(self):
        agent, _ = registry.add("b", "other", "restricted")
        for answer in ("once", "session", "deny"):
            thread = self.answer_when_seen(answer)
            approver = registry.BrowserApprover(fallback=Approve("deny"), notice=3, timeout=5, poll=0.05)
            self.assertEqual(approver.ask(registry.get(agent["id"]), "interact", "https://example.org"), answer)
            thread.join()
        self.assertEqual(list(registry.requests_dir().iterdir()), [])  # nothing left behind

    def test_request_file_has_risk_place_and_expiry(self):
        """SB-01: the request page shows the risk tier, where the agent acts and when silence means no."""
        agent, _ = registry.add("b", "other", "restricted")
        seen = []

        def read_request():
            for _ in range(100):
                pending = list(registry.requests_dir().glob("*.json"))
                if pending:
                    seen.append(json.loads(pending[0].read_text()))
                    pending[0].with_suffix(".seen").touch()
                    registry.answer_request(pending[0].stem, "deny")
                    return
                time.sleep(0.05)

        cases = (
            ("transactions", "Trabalho", "critical", {"kind": "profile", "profile": "Trabalho"}),
            ("interact", "", "warning", {"kind": "workspace"}),
        )
        for capability, place, risk, where in cases:
            thread = threading.Thread(target=read_request)
            thread.start()
            approver = registry.BrowserApprover(fallback=Approve("deny"), notice=3, timeout=30, poll=0.05)
            self.assertEqual(approver.ask(registry.get(agent["id"]), capability, None, place), "deny")
            thread.join()
            request = seen.pop()
            self.assertEqual((request["risk"], request["place"]), (risk, where))
            expires = _dt.datetime.fromisoformat(request["expires"]) - _dt.datetime.fromisoformat(request["created"])
            self.assertEqual(expires, _dt.timedelta(seconds=30))

    def test_browser_approver_falls_back_when_no_browser_answers(self):
        agent, _ = registry.add("f", "other", "restricted")
        fallback = Approve("once")
        approver = registry.BrowserApprover(fallback=fallback, notice=0.3, timeout=5, poll=0.05)
        self.assertEqual(approver.ask(registry.get(agent["id"]), "interact", None, "Trabalho"), "once")
        self.assertEqual(fallback.asked, [("interact", None)])
        self.assertEqual(fallback.places, ["Trabalho"])  # the desktop dialog says where, too
        self.assertEqual(list(registry.requests_dir().iterdir()), [])

    def test_unanswered_request_is_denied(self):
        agent, _ = registry.add("u", "other", "restricted")

        def mark_seen():
            for _ in range(100):
                pending = list(registry.requests_dir().glob("*.json"))
                if pending:
                    pending[0].with_suffix(".seen").touch()
                    return
                time.sleep(0.05)

        thread = threading.Thread(target=mark_seen)
        thread.start()
        approver = registry.BrowserApprover(notice=3, timeout=0.5, poll=0.05)
        self.assertEqual(approver.ask(registry.get(agent["id"]), "interact", None), "deny")
        thread.join()

    def test_pending_request_is_denied_at_once_when_called_off(self):
        """UX5-0: a stop, pause, revoke or cancelled call ends a pending request now, not at its expiry."""

        def mark_seen():
            for _ in range(100):
                pending = list(registry.requests_dir().glob("*.json"))
                if pending:
                    pending[0].with_suffix(".seen").touch()
                    return
                time.sleep(0.05)

        cancel = threading.Event()
        cases = (
            ("stop", lambda a: registry.set_stopped(True)),
            ("pause", lambda a: registry.pause(a, True)),
            ("revoke", lambda a: registry.revoke(a)),
            ("cancel", lambda a: cancel.set()),
        )
        for name, act in cases:
            with self.subTest(name):
                agent, _ = registry.add("w", "other", "restricted")
                cancel.clear()
                seen = threading.Thread(target=mark_seen)
                seen.start()
                threading.Timer(0.4, act, [agent["id"]]).start()
                approver = registry.BrowserApprover(fallback=Approve("once"), notice=3, timeout=30, poll=0.05)
                started = time.monotonic()
                self.assertEqual(approver.ask(registry.get(agent["id"]), "interact", None, cancel=cancel), "deny")
                self.assertLess(time.monotonic() - started, 5)
                seen.join()
                self.assertEqual(list(registry.requests_dir().iterdir()), [])
                registry.set_stopped(False)

    def test_a_session_marker_says_who_is_connected_only_while_it_runs(self):
        """UX5-I2: the bridge writes <state>/ai/sessions/<id>.json (0600) with its pid, removed at the end."""
        agent, token = registry.add("Marcado", "claude-code", "restricted")
        seen = {}

        class Probe:
            def __init__(self, *_a, **_k):
                pass

            def serve(self):
                files = list(registry.sessions_dir().glob("*.json"))
                seen["files"] = [json.loads(f.read_text()) for f in files]
                seen["modes"] = [f.stat().st_mode & 0o777 for f in files]

        with mock.patch.dict(os.environ, {"NULAVIO_AGENT_TOKEN": token}), mock.patch("nulavio_launcher.ai.mcp.Server", Probe), \
                mock.patch("nulavio_launcher.ai.tools.Bridge", lambda *a, **k: None):  # fmt: skip
            self.assertEqual(ai_cli._serve(mock.Mock(headless=True)), 0)
        self.assertEqual([(f["agent"], f["name"], f["pid"]) for f in seen["files"]], [(agent["id"], "Marcado", os.getpid())])
        self.assertEqual(seen["modes"], [0o600])
        self.assertEqual(list(registry.sessions_dir().glob("*.json")), [])  # gone when the session ends

    def test_answers_are_validated(self):
        for request_id, answer in (("../../x", "once"), ("0123456789abcdef", "always"), ("0123456789abcdef", "once")):
            with self.assertRaises(registry.RegistryError):
                registry.answer_request(request_id, answer)

    def test_activity_retention(self):
        old = (policy.now() - _dt.timedelta(days=40)).isoformat(timespec="milliseconds")
        audit.audit_path().write_text(json.dumps({"ts": old, "tool": "x"}) + "\n")
        audit.record(tool="y")
        self.assertEqual([e["tool"] for e in audit.read()], ["y"])
        audit.clear()
        self.assertEqual(audit.read(), [])

    def test_settings_api(self):
        added = ai_cli.api_request({"op": "add", "name": "Claude", "client": "claude-code", "autonomy": "assisted"})
        agent_id = added["agent"]["id"]
        self.assertNotIn("token_sha256", added["agent"])
        self.assertIn("NULAVIO_AGENT_TOKEN", added["config"])
        ai_cli.api_request({"op": "grant", "agent": agent_id, "capability": "execute_js", "mode": "allow", "minutes": 30})
        overview = ai_cli.api_request({"op": "overview"})
        self.assertEqual(overview["agents"][0]["modes"]["execute_js"], "allow")
        self.assertNotIn("token_sha256", json.dumps(overview))
        # SPA-01 / SB-02: consent texts come from the browser's locales; the API sends no English warning.
        self.assertNotIn("fullControlWarning", overview)
        self.assertNotIn(policy.FULL_CONTROL_WARNING, json.dumps(overview))
        self.assertNotIn(policy.RAW_AUTOMATION_WARNING, json.dumps(overview))
        with self.assertRaises(registry.RegistryError):
            ai_cli.api_request({"op": "raw-automation", "agent": agent_id, "enabled": True})
        ai_cli.api_request({"op": "raw-automation", "agent": agent_id, "enabled": True, "acceptRawAutomation": True})
        self.assertEqual(ai_cli.api_request({"op": "overview"})["agents"][0]["modes"][policy.RAW_CAPABILITY], "allow")
        ai_cli.api_request({"op": "raw-automation", "agent": agent_id, "enabled": False})
        self.assertEqual(ai_cli.api_request({"op": "overview"})["agents"][0]["modes"][policy.RAW_CAPABILITY], "block")
        ai_cli.api_request({"op": "pause", "agent": agent_id, "paused": True})
        ai_cli.api_request({"op": "stop", "stopped": True})
        self.assertTrue(ai_cli.api_request({"op": "overview"})["stopped"])
        with self.assertRaises(registry.RegistryError):
            ai_cli.api_request({"op": "add", "name": "F", "client": "other", "autonomy": "full_control"})
        with self.assertRaises(registry.RegistryError):
            ai_cli.api_request({"op": "explode"})


class ProfilesAndKeysTest(Home):
    """S8: profiles an agent may use, its routes, and the key file its configuration points to."""

    def test_key_file(self):
        agent, token = registry.add("k", "claude-code", "assisted")
        path = registry.token_file(agent["id"])
        self.assertEqual(path.read_text(), token)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        config = json.loads(ai_cli.client_config("claude-code", agent_id=agent["id"]))
        self.assertEqual(config["mcpServers"]["nulavio"]["env"]["NULAVIO_AGENT_TOKEN_FILE"], str(path))
        self.assertNotIn(token, json.dumps(config))
        new = registry.rotate_token(agent["id"])
        self.assertEqual(path.read_text(), new)  # the configuration stays valid
        self.assertEqual(registry.read_token_file(str(path)), new)
        self.assertIsNone(registry.read_token_file(str(self.home / "missing")))
        registry.remove(agent["id"])
        self.assertFalse(path.exists())

    def test_profiles_and_routes(self):
        agent, _ = registry.add("r", "codex", "autonomous")
        registry.set_profiles(agent["id"], [{"label": "Trabalho", "path": "/home/u/.nulavio/p1"},
                                            {"label": "Dev", "path": "/home/u/.nulavio/p2"}])  # fmt: skip
        for bad in ([{"label": "AI Workspace", "path": "/x"}], [{"label": "a/b", "path": "/x"}], [{"label": "X", "path": "rel"}],
                    [{"label": "X", "path": "/a"}, {"label": "X", "path": "/b"}]):  # fmt: skip
            with self.assertRaises(registry.RegistryError):
                registry.set_profiles(agent["id"], bad)
        registry.set_routes(
            agent["id"], [{"site": "example.org", "profile": "Trabalho"}, {"site": "dev.example.org", "profile": "Dev"}]
        )
        with self.assertRaises(registry.RegistryError):
            registry.set_routes(agent["id"], [{"site": "x.org", "profile": "Banco"}])  # not one of its profiles
        stored = registry.get(agent["id"])
        self.assertEqual(registry.route_for(stored, "api.dev.example.org"), "Dev")  # the most specific site wins
        self.assertEqual(registry.route_for(stored, "www.example.org"), "Trabalho")
        self.assertIsNone(registry.route_for(stored, "example.org.evil.test"))
        self.assertIsNone(registry.route_for(stored, None))


if __name__ == "__main__":
    unittest.main()
