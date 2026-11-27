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
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

from nulavio_launcher.ai import audit, mcp, policy, registry, tools
from nulavio_launcher.ai import bidi as bidi_mod
from nulavio_launcher.ai import cli as ai_cli
from nulavio_launcher.ai.websocket import GUID, WebSocket, WebSocketError
from nulavio_launcher.engine import EngineError
from nulavio_launcher.ai.workspace import OLD_RAW_MARKER, WORKSPACE_PREFS, ProfileTarget, Workspace


def wait_for(predicate, timeout: float = 5.0) -> bool:
    """True once `predicate` is (work on another thread), False after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


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

    def end(self):
        self.closed = True


class ClientInput(io.BytesIO):
    """A client's lines on the server's stdin. Like a client that shuts down cleanly, it closes stdin only once every
    call it made has its response: the end of stdin cancels the calls still in progress (#646)."""

    server: mcp.Server | None = None

    def readline(self, *args):
        line = super().readline(*args)
        if not line and self.server is not None:
            wait_for(lambda: self.server._jobs.empty() and not self.server._cancels)
        return line


def run_server(lines: list, bridge=None) -> list[dict]:
    raw = b"".join((json.dumps(m).encode() if not isinstance(m, bytes) else m) + b"\n" for m in lines)
    out = io.BytesIO()
    stdin = ClientInput(raw)
    server = stdin.server = mcp.Server(bridge or FakeBridge(), stdin, out)
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
        # The client closes stdin once it has its response: the end of stdin cancels a call still running (#646).
        self.assertTrue(wait_for(lambda: len(out.getvalue().splitlines()) == 2 and not server._cancels))
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

    def test_the_shells_own_pages_are_internal_pages(self):
        # Audit A2: Settings, Vault and profile pages were reachable with local_resources alone.
        for url in ("moz-extension://0e3a/settings/settings.html#profiles", "moz-extension://0e3a/vault/unlock.html",
                    "view-source:https://example.org/"):  # fmt: skip
            self.assertEqual(policy.classify_url(url).needs, ("local_resources", "debugging"), url)

    def test_an_address_wrapped_by_an_internal_page_goes_by_what_it_shows(self):
        # LESIS afa509d1: view-source:https://… has no host of its own, so the site list let it through.
        with mock.patch.object(policy, "_resolves_locally", return_value=False):
            wrapped = (
                "view-source:https://bank.example/acct?id=4",
                "VIEW-SOURCE:https://bank.example/",
                "about:reader?url=https%3A%2F%2Fbank.example%2Fnews",
                "about:READER?url=https://bank.example/",
            )
            for url in wrapped:
                with self.subTest(url=url):
                    target = policy.classify_url(url)
                    self.assertEqual((target.host, target.needs), ("bank.example", ("local_resources", "debugging")))
                    self.assertEqual(policy.host_of(url), "bank.example")
                    self.assertEqual(policy.origin(url), "https://bank.example")
            self.assertEqual(policy.classify_url("view-source:http://192.168.1.1/").host, "192.168.1.1")
            # Reader View reads the first `url`, as the engine does (an empty one shows nothing).
            self.assertEqual(policy.host_of("about:reader?url=https://a.example/&url=https://b.example/"), "a.example")
            self.assertIsNone(policy.host_of("about:reader?url=&url=https://b.example/"))
            # The engine trims an address; a wrapper is one however it is padded, and is not opened padded.
            for padded in (
                " view-source:https://bank.example/",
                "\x01view-source:https://bank.example/",
                "view-source:https://bank.example/ ",
            ):
                self.assertEqual(policy.host_of(padded), "bank.example", padded)
                with self.assertRaises(policy.UrlRefused):
                    policy.classify_url(padded)
            self.assertEqual(policy.classify_url("view-source:file:///etc/hostname").host, None)
            for url in ("view-source:view-source:https://x.example/", "view-source:about:reader?url=https://x.example/",
                        "about:reader?url=view-source:https://x.example/", "view-source:javascript:alert(1)",
                        "view-source:https://user@x.example/", "view-source:", "view-source:http://[::1"):  # fmt: skip
                with self.subTest(url=url), self.assertRaises(policy.UrlRefused):
                    policy.classify_url(url)
        for url in ("about:blank", None, ""):  # no address: nothing for a site list to bound
            self.assertIsNone(policy.host_of(url), url)
        # An address with no site: not on any list. The engine opens a file: address's path whatever host it is
        # written with (nsNoAuthURLParser), so that host is no site either, nor is one of any scheme but http(s).
        for url in ("about:config", "about:reader", "file:///etc/hostname", "file://example.org/etc/passwd",
                    "FILE://example.org/etc/passwd", "view-source:file://example.org/etc/passwd",
                    "resource://example.org/", "moz-extension://example.org/x.html"):  # fmt: skip
            self.assertEqual(policy.host_of(url), "", url)
        self.assertEqual(policy.host_of("https://docs.example.org/a"), "docs.example.org")
        with self.assertRaises(policy.UrlRefused):
            policy.classify_url("http://[::1")  # the parser refuses it: an answer, not an exception

    def test_origin_drops_path_and_query(self):
        self.assertEqual(policy.origin("https://bank.example:8443/acct?id=123#x"), "https://bank.example:8443")
        self.assertEqual(policy.origin("file:///home/me/secret.txt"), "file:")

    def test_a_host_the_engine_would_not_look_up_is_refused_before_any_lookup(self):
        # The engine sends a name to its resolver only when it is made of letters, digits and ".-$+_" (net_IsValidDNSHost):
        # any other host is not one it opens, and a request shows the person nothing the agent wrote as a host.
        with mock.patch.object(policy.socket, "getaddrinfo", side_effect=AssertionError("looked up")):
            for url in ("http://local host text/", "http://a<b>c.example/", 'https://ex"ample.org/', "http://a{b}.example/",
                        "http://allow,this.example/", "http://x;y.example:8080/", "http://a..b.example/",
                        "https://straße.example/", "https://ς.example/", "https://a\u200db.example/"):  # fmt: skip
                with self.subTest(url=url), self.assertRaises(policy.UrlRefused):
                    policy.classify_url(url)
        for url in ("https://my_host.example/", "https://xn--80ak6aa92e.com/", "https://аррӏе.com/", "http://[::1]:8080/"):
            with self.subTest(url=url):
                policy.classify_url(url, resolve=False)
        self.assertEqual(policy.classify_url("https://аррӏе.com/", resolve=False).host, "xn--80ak6aa92e.com")

    def test_a_request_names_the_host_as_the_engine_reads_it(self):
        self.assertEqual(policy.origin("https://аррӏе.com/x"), "https://xn--80ak6aa92e.com")
        self.assertEqual(policy.origin("HTTPS://Docs.Example.ORG/a"), "https://docs.example.org")
        self.assertEqual(policy.origin("http://127.1:8080/"), "http://127.0.0.1:8080")
        self.assertEqual(policy.origin("http://[::1]:8080/a"), "http://[::1]:8080")
        self.assertEqual(policy.origin("http://[0:0::1]/"), "http://[::1]")
        self.assertEqual(policy.origin("view-source:https://аррӏе.com/"), "https://xn--80ak6aa92e.com")
        self.assertEqual(policy.origin("https://example.org:443/"), "https://example.org")  # the engine drops it too
        self.assertEqual(policy.origin("http://example.org:80/"), "http://example.org")
        self.assertEqual(policy.origin("http://example.org:443/"), "http://example.org:443")
        self.assertEqual(policy.origin("http://example.org:0/"), "http://example.org:0")  # not a default port


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
            "assisted": {"interact": True, "submit_forms": False, "authenticated_sessions": False, "execute_js": False},
            "autonomous": {
                "interact": True,
                "submit_forms": True,
                "files": True,
                "authenticated_sessions": True,
                "multiple_profiles": False,
                "local_resources": False,
                "execute_js": False,
                "cookies_storage": False,
            },
            # Everything but the internal pages, which no agent gets (#463).
            "full_control": {c: c != policy.INTERNAL_CAPABILITY for c in policy.CAPABILITIES},
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

    def test_an_answer_until_the_agent_disconnects_is_for_what_the_request_showed(self):
        # A request names a site and a place; "Allow until the agent disconnects" is for that site in that place, not
        # the capability on every site and in every profile.
        agent, _ = registry.add("bound", "other", "autonomous")
        registry.grant(agent["id"], "local_resources", "ask")

        def decide(capability, target, place="", approver=None, session="s-1"):
            return registry.decide(agent["id"], capability, host=None, target=target, session_id=session,
                                   approver=approver or registry.Approver(), place=place)  # fmt: skip

        self.assertTrue(decide("local_resources", "http://localhost:3000", approver=Approve("session")).allowed)
        self.assertEqual(decide("local_resources", "http://localhost:3000").reason, "session-grant")
        for target, place in (("http://192.168.1.1", ""), ("http://169.254.169.254", ""), ("file:", ""),
                              ("http://localhost:3000", "Trabalho"), ("http://localhost:8080", "")):  # fmt: skip
            with self.subTest(target=target, place=place):
                later = Approve("deny")
                self.assertEqual(decide("local_resources", target, place, later).reason, "denied")
                self.assertEqual(later.asked, [("local_resources", target)])
        registry.grant(agent["id"], "submit_forms", "ask")
        self.assertTrue(decide("submit_forms", "https://shop.example", approver=Approve("session")).allowed)
        self.assertEqual(decide("submit_forms", "https://shop.example").reason, "session-grant")
        self.assertEqual(decide("submit_forms", "https://bank.example").reason, "no-approver")
        registry.grant(agent["id"], "authenticated_sessions", "ask")
        self.assertTrue(decide("authenticated_sessions", "https://mail.example", "Trabalho", Approve("session")).allowed)
        self.assertEqual(decide("authenticated_sessions", "https://mail.example", "Trabalho").reason, "session-grant")
        self.assertEqual(decide("authenticated_sessions", "https://mail.example", "Pessoal").reason, "no-approver")
        self.assertEqual(decide("authenticated_sessions", "https://mail.example", "Trabalho", session="s-2").reason,
                         "no-approver")  # fmt: skip
        # The capability as a whole (the tool list, what an engine holds or lets through) is what the user set.
        self.assertEqual(policy.effective_mode(registry.get(agent["id"]), "local_resources", "s-1"), ("ask", "grant"))
        # An answer stored before it named what it was for counts for nothing.
        registry._change(agent["id"], lambda a: a["session_grants"].__setitem__("interact", {"session": "s-1", "set": "x"}))
        registry.grant(agent["id"], "interact", "ask")
        registry._change(agent["id"], lambda a: a["session_grants"].__setitem__("interact", {"session": "s-1", "set": "x"}))
        self.assertEqual(decide("interact", "https://shop.example").reason, "no-approver")

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

    def test_raw_automation_is_gone_and_no_agent_gets_the_internal_pages(self):
        """#463: no tool hands the endpoint over, and nothing turns the internal pages on: no level, grant, session
        answer, or the opt-in an earlier version recorded."""
        internal = policy.INTERNAL_CAPABILITY
        self.assertNotIn("raw_automation", tools.BY_NAME)
        self.assertNotIn("raw_automation", {t.name for t in tools.TOOLS})
        for level in policy.PRESETS:
            self.assertEqual(policy.PRESETS[level][internal], "block", level)
        agent, _ = registry.add("full", "other", "full_control", accept_full_control=True)
        self.assertEqual(self.decide(agent["id"], internal).reason, "internal-pages-off")
        for mode in ("allow", "ask"):
            with self.assertRaises(registry.RegistryError) as caught:
                registry.grant(agent["id"], internal, mode)
            self.assertEqual(caught.exception.code, "internal-pages-off")
        with self.assertRaises(registry.RegistryError):
            registry.grant_session(agent["id"], internal, "s-1")
        registry.grant(agent["id"], internal, "block")  # blocking it again is harmless
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        self.assertNotIn("raw_automation", {t["name"] for t in bridge.list_tools()})
        self.assertIn(internal, policy.classify_url("about:config").needs)

    def test_a_stored_raw_automation_opt_in_grants_nothing_and_is_said_once(self):
        """#463: a registry written by a version with raw automation is read without error; its opt-in, an
        allow grant and a session answer for the internal pages grant nothing, and the agents' page says so
        until the person acknowledges it."""
        agent, _ = registry.add("old", "other", "full_control", accept_full_control=True)
        path = self.home / "state" / "ai" / "agents.json"
        data = json.loads(path.read_text())
        stored = data["agents"][agent["id"]]
        stored["raw_automation_accepted"] = "2026-11-01T10:00:00+00:00"
        stored["grants"][policy.INTERNAL_CAPABILITY] = {"mode": "allow", "set": "2026-11-01T10:00:00+00:00",
                                                        "until": None, "session": None}  # fmt: skip
        stored.setdefault("session_grants", {})[policy.INTERNAL_CAPABILITY] = {
            "session": "s-1",
            "set": "2026-11-01T10:00:00+00:00",
        }
        path.write_text(json.dumps(data))
        self.assertEqual(self.decide(agent["id"], policy.INTERNAL_CAPABILITY).reason, "internal-pages-off")
        self.assertIn(policy.INTERNAL_CAPABILITY, policy.classify_url("about:config").needs)
        overview = ai_cli.api_request({"op": "overview"})
        listed = overview["agents"][0]
        self.assertTrue(listed["raw_automation_removed"])
        self.assertNotIn("raw_automation_accepted", listed)
        self.assertEqual(listed["modes"][policy.INTERNAL_CAPABILITY], "block")
        ai_cli.api_request({"op": "forget-raw-automation", "agent": agent["id"]})
        stored = registry.get(agent["id"])
        self.assertNotIn("raw_automation_accepted", stored)
        self.assertNotIn(policy.INTERNAL_CAPABILITY, stored["grants"])
        self.assertNotIn(policy.INTERNAL_CAPABILITY, stored.get("session_grants", {}))
        self.assertFalse(ai_cli.api_request({"op": "overview"})["agents"][0]["raw_automation_removed"])

    def test_every_capability_has_a_risk_tier(self):
        self.assertEqual(set(policy.RISK), set(policy.CAPABILITIES))
        self.assertTrue(set(policy.RISK.values()) <= {"critical", "warning", "info"})
        for capability in ("authenticated_sessions", "execute_js", "cookies_storage", "local_resources",
                           "multiple_profiles", policy.INTERNAL_CAPABILITY):  # fmt: skip
            self.assertEqual(policy.RISK[capability], "critical", capability)
        for capability in ("interact", "submit_forms", "files"):
            self.assertEqual(policy.RISK[capability], "warning", capability)
        for capability in ("read_pages", "navigate", "screenshots"):
            self.assertEqual(policy.RISK[capability], "info", capability)

    def test_only_checked_capabilities_are_offered(self):
        """#714: every capability Settings and the CLI offer is one a tool checks before it acts, so that no row or
        level hint promises a question nobody asks. The five offered until 2026-11-25 are checked by none."""
        import ast
        import inspect

        checked = set()
        for node in ast.walk(ast.parse(inspect.getsource(tools))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args
                    and node.func.attr in ("require", "require_here", "_refuse_if_held")
                    and isinstance(node.args[0], ast.Constant)):  # fmt: skip
                checked.add(node.args[0].value)
                for keyword in node.keywords:  # require_here(..., also=(...)): asked after the tool's own (#725)
                    if keyword.arg == "also" and isinstance(keyword.value, ast.Tuple):
                        checked |= {e.value for e in keyword.value.elts if isinstance(e, ast.Constant)}
        # The rest come from what an address needs (classify_url), which require_needs asks for.
        checked |= set(policy.classify_url("http://127.0.0.1/").needs) | set(policy.classify_url("about:config").needs)
        offered = set(policy.CAPABILITIES)
        self.assertEqual(offered - checked, set(), "offered, and checked by no tool")
        self.assertEqual(policy.RETIRED_CAPABILITIES & offered, set())
        self.assertEqual(policy.RETIRED_CAPABILITIES & checked, set(), "checked again: offer it again")
        self.assertEqual(policy.RETIRED_CAPABILITIES, {"transactions", "account_settings", "private_tabs", "network",
                                                       "background"})  # fmt: skip
        for level, modes in policy.PRESETS.items():
            self.assertEqual(set(modes), offered, level)
        self.assertEqual(set(ai_cli.api_request({"op": "overview"})["capabilities"]), offered)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ai_cli._capabilities(None)
        listed = {line.split()[0] for line in out.getvalue().splitlines()[1:]}
        self.assertEqual(listed, offered)
        for locale in ("en", "pt_BR"):
            path = Path(__file__).resolve().parents[2] / "browser" / "shell" / "_locales" / locale / "messages.json"
            keys = {k.removeprefix("aiCap_") for k in json.loads(path.read_text(encoding="utf-8")) if k.startswith("aiCap_")}
            self.assertEqual(keys, offered, locale)

    def test_a_saved_grant_for_a_capability_no_longer_offered_loads_and_counts_for_nothing(self):
        """#714: a registry written while the five were offered still loads; their grants and session answers stay in
        the file, grant nothing, are not shown, and every other change still works."""
        agent, _ = registry.add("old", "other", "assisted")
        path = self.home / "state" / "ai" / "agents.json"
        data = json.loads(path.read_text())
        stored = data["agents"][agent["id"]]
        for capability in sorted(policy.RETIRED_CAPABILITIES):
            stored["grants"][capability] = {"mode": "allow", "set": "2026-11-01T10:00:00+00:00", "until": None,
                                            "session": None}  # fmt: skip
            stored.setdefault("session_grants", {})[capability] = {
                "session": "s-1", "set": "2026-11-01T10:00:00+00:00", "scopes": [[None, ""]]}  # fmt: skip
        path.write_text(json.dumps(data))
        approver = Approve("once")
        for capability in sorted(policy.RETIRED_CAPABILITIES):
            decision = self.decide(agent["id"], capability, approver)
            self.assertEqual((decision.allowed, decision.reason), (False, "unknown-capability"), capability)
            self.assertEqual(policy.effective_mode(registry.get(agent["id"]), capability, "s-1", scope=(None, "")),
                             ("block", "unknown-capability"))  # fmt: skip
            with self.assertRaises(registry.RegistryError):
                registry.grant(agent["id"], capability, "allow")
            with self.assertRaises(registry.RegistryError):
                registry.grant_session(agent["id"], capability, "s-1")
        self.assertEqual(approver.asked, [])
        listed = ai_cli.api_request({"op": "overview"})["agents"][0]
        self.assertEqual(set(listed["modes"]), set(policy.CAPABILITIES))
        self.assertEqual(set(listed["grants"]) & policy.RETIRED_CAPABILITIES, set())
        self.assertEqual(set(listed["session_grants"]) & policy.RETIRED_CAPABILITIES, set())
        self.assertEqual(set(registry.get(agent["id"])["grants"]), policy.RETIRED_CAPABILITIES)  # the file keeps them
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            ai_cli._agents(mock.Mock(json=False))
        for capability in policy.RETIRED_CAPABILITIES:
            self.assertNotIn(capability, out.getvalue())
        # The rest of the record is untouched by them.
        registry.grant(agent["id"], "submit_forms", "allow")
        self.assertTrue(self.decide(agent["id"], "submit_forms").allowed)
        registry.set_autonomy(agent["id"], "autonomous")
        registry.end_session(agent["id"], "s-1")
        ai_cli.api_request({"op": "clear-grant", "agent": agent["id"], "capability": "transactions"})
        stored = registry.get(agent["id"])
        self.assertNotIn("transactions", stored["grants"])
        self.assertIn("account_settings", stored["grants"])  # kept in the file, as it was
        self.assertEqual(self.decide(agent["id"], "account_settings").reason, "unknown-capability")

    def test_requests_say_where_the_agent_acts(self):
        agent, _ = registry.add("where", "other", "restricted")
        approver = Approve("deny")
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        bridge.owner = {"t1": "Trabalho", "t2": ""}
        for tab in ("t1", "t2"):
            bridge.elements[tab] = {"e1": "shared-1"}
        with (
            mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"),
            mock.patch.object(tools.Bridge, "_call_fn", return_value={"connected": True}),  # the look before asking
        ):
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
    def setUp(self):
        super().setUp()
        # Unit tests use no network: public names count as public, not "did not resolve here".
        patcher = mock.patch.object(policy, "_resolves_locally", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

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
        # still_at reads the address twice, around its check of the session (OpenCodeReview on #812, round 3).
        moved = ["https://blog.example/", "https://bank.example/", "https://bank.example/"]
        with (
            mock.patch.object(tools.Bridge, "_url_of", side_effect=moved),
            mock.patch.object(tools.Bridge, "_eval", side_effect=AssertionError("ran")),
        ):
            result = bridge.call("evaluate", {"tab": "t1", "expression": "1"})
        self.assertIn("moved to https://bank.example", result["content"][0]["text"])

    def test_tabs_outside_the_agents_sites_are_not_described(self):
        # Audit A8: tabs_list gave every tab's full address and title, whatever the site list said.
        agent, _ = registry.add("sites", "other", "restricted", domains=["example.org"])
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        tabs = [
            {"context": "t1", "profile": "AI Workspace", "url": "https://docs.example.org/a"},
            {"context": "t2", "profile": "AI Workspace", "url": "https://bank.example/acct?id=42"},
        ]
        with (
            mock.patch.object(tools.Bridge, "_tabs", return_value=tabs),
            mock.patch.object(tools.Bridge, "_title", side_effect=lambda tab, _c: f"title of {tab}"),
        ):
            listed = bridge.call("tabs_list", {})["structuredContent"]["tabs"]
        self.assertEqual(listed[0]["url"], "https://docs.example.org/a")
        self.assertEqual((listed[1]["url"], listed[1]["title"], listed[1]["outside_sites"]), (None, None, True))
        self.assertNotIn("bank.example", json.dumps(listed))

    def test_a_script_needs_cookies_and_storage_too(self):
        # Audit A9: evaluate reads document.cookie; execute_js alone let it.
        agent, _ = registry.add("scripts", "other", "autonomous")
        registry.grant(agent["id"], "execute_js", "allow")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        with (
            mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"),
            mock.patch.object(tools.Bridge, "_eval", side_effect=AssertionError("ran")),
        ):
            result = bridge.call("evaluate", {"tab": "t1", "expression": "document.cookie"})
        self.assertTrue(result["isError"])
        self.assertIn("cookies_storage", audit.audit_path().read_text().splitlines()[-1])

    def test_a_script_is_not_asked_for_while_cookies_and_storage_are_blocked(self):
        # #725: Autonomous asked for execute_js (and, on the local network, local_resources), then refused the call
        # for cookies_storage whatever the answer, and a "for this session" answer stayed for nothing.
        for name, url, block_cookies in (("preset", "https://example.org/", False),
                                         ("local", "http://localhost:8080/", False),
                                         ("grant", "https://example.org/", True)):  # fmt: skip
            agent, _ = registry.add(f"js-{name}", "other", "autonomous")
            if block_cookies:
                registry.grant(agent["id"], "cookies_storage", "block")
            asks = Approve("session")
            with (
                self.subTest(name=name),
                mock.patch.object(tools.Bridge, "_url_of", return_value=url),
                mock.patch.object(tools.Bridge, "_eval", side_effect=AssertionError("ran")),
            ):
                result = tools.Bridge(agent["id"], "s-1", approver=asks).call("evaluate", {"tab": "t1", "expression": "1"})
                self.assertTrue(result["isError"])
                self.assertIn("Read or change cookies and site storage", result["content"][0]["text"])
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["capability"], entry["reason"]),
                                 ("cookies_storage", "grant" if block_cookies else "preset:autonomous"))  # fmt: skip
                self.assertEqual(asks.asked, [])
                self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})

    def test_a_script_is_asked_for_when_cookies_and_storage_can_be_allowed(self):
        # #725 refuses only what no answer could allow: cookies_storage allowed or asking still lets a script run.
        target = "https://example.org"
        for cookies, asked in (("allow", [("execute_js", target)]),
                               ("ask", [("execute_js", target), ("cookies_storage", target)])):  # fmt: skip
            agent, _ = registry.add(f"js-{cookies}", "other", "autonomous")
            registry.grant(agent["id"], "cookies_storage", cookies)
            asks = Approve("once")
            with (
                self.subTest(cookies=cookies),
                mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"),
                mock.patch.object(tools.Bridge, "_eval", return_value=42) as ran,
            ):
                result = tools.Bridge(agent["id"], "s-1", approver=asks).call("evaluate", {"tab": "t1", "expression": "6*7"})
                self.assertFalse(result["isError"])
                self.assertEqual(result["structuredContent"]["value"], 42)
                self.assertEqual(asks.asked, asked)
                ran.assert_called_once()

    def test_a_script_blocked_by_its_own_permission_is_refused_for_it(self):
        # #725 keeps the refusal on execute_js where that is blocked too (Restricted, Assisted).
        for level in ("restricted", "assisted"):
            agent, _ = registry.add(f"js-{level}", "other", level)
            asks = Approve("session")
            with self.subTest(level=level), mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"):
                result = tools.Bridge(agent["id"], "s-1", approver=asks).call("evaluate", {"tab": "t1", "expression": "1"})
                self.assertIn("Run JavaScript in pages", result["content"][0]["text"])
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["capability"], entry["reason"]), ("execute_js", f"preset:{level}"))
                self.assertEqual(asks.asked, [])

    # #730: a call that also needs a permission blocked for the agent there, besides what it asks first, is refused
    # before any question: asking could only end in a refusal, and an answer "until the agent disconnects" stayed.
    LOCAL = "http://localhost:8080/"
    ASKED_FIRST = (
        # Restricted: interact asks, and an address on this computer needs local_resources, which it blocks.
        ("click", "restricted", {}, LOCAL, {"tab": "t1", "element": "e1"}, "local_resources"),
        ("type", "restricted", {}, LOCAL, {"tab": "t1", "element": "e1", "text": "x"}, "local_resources"),
        # What the address needs, which #728's also= did not look at: execute_js asks, cookies_storage is allowed.
        ("evaluate", "autonomous", {"cookies_storage": "allow"}, LOCAL, {"tab": "t1", "expression": "1"}, "local_resources"),
        # Enter (submit=true) while submit_forms is blocked: interact asked first.
        ("type", "restricted", {}, "https://example.org/", {"tab": "t1", "element": "e1", "text": "x", "submit": True},
         "submit_forms"),
    )  # fmt: skip

    def asked_first(self, blocked: str):
        for tool, level, grants, url, args, capability in self.ASKED_FIRST:
            agent, _ = registry.add(f"first-{len(registry.load()['agents'])}", "other", level)
            for name, mode in grants.items():
                registry.grant(agent["id"], name, mode)
            reason = f"preset:{level}"  # what the level blocks is refused by the level, as #730 found it
            if policy.PRESETS[level][capability] != blocked:
                registry.grant(agent["id"], capability, blocked)
                reason = "grant"
            yield tool, agent, url, args, capability, reason

    def test_a_call_is_not_asked_about_while_another_permission_it_needs_is_blocked(self):
        for tool, agent, url, args, capability, reason in self.asked_first("block"):
            asks = Approve("session")
            bridge = tools.Bridge(agent["id"], "s-1", approver=asks)
            bridge.elements["t1"] = {"e1": "shared-1"}
            with (
                self.subTest(tool=tool, capability=capability),
                mock.patch.object(tools.Bridge, "_url_of", return_value=url),
                mock.patch.object(tools.Bridge, "_call_fn", side_effect=AssertionError("acted")),
                mock.patch.object(tools.Bridge, "_eval", side_effect=AssertionError("ran")),
            ):
                result = bridge.call(tool, args)
                self.assertTrue(result["isError"], result)
                self.assertIn(policy.CAPABILITIES[capability], result["content"][0]["text"])
                self.assertEqual(asks.asked, [])
                self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["capability"], entry["reason"], entry["target"]),
                                 (capability, reason, policy.origin(url)))  # fmt: skip

    def test_a_call_still_asks_in_the_same_order_when_an_answer_can_allow_it(self):
        # I7: the same calls with that permission on ask are asked what they were asked before, in the same order.
        for tool, agent, url, args, capability, _reason in self.asked_first("ask"):
            asks = Approve("once")
            bridge = tools.Bridge(agent["id"], "s-1", approver=asks)
            bridge.elements["t1"] = {"e1": "shared-1"}
            first = "execute_js" if tool == "evaluate" else "interact"
            with (
                self.subTest(tool=tool, capability=capability),
                mock.patch.object(tools.Bridge, "_url_of", return_value=url),
                mock.patch.object(tools.Bridge, "_earlier_forms", return_value=None),
                mock.patch.object(tools.Bridge, "_forms_prepare"),
                mock.patch.object(tools.Bridge, "_call_fn", return_value={"connected": False}),
                mock.patch.object(tools.Bridge, "_eval", return_value=42),
            ):
                result = bridge.call(tool, args)
                self.assertEqual(asks.asked, [(first, policy.origin(url)), (capability, policy.origin(url))])
                if tool == "evaluate":
                    self.assertFalse(result["isError"], result)
                else:  # asked and allowed: the call went on to the element
                    self.assertIn("the element is gone", result["content"][0]["text"])

    def test_a_burst_of_calls_does_not_hide_earlier_actions(self):
        # Audit A7: ~10 000 cheap calls rotated the log twice and Activity read only the current file.
        audit.record(agent="ag-x", tool="evaluate", decision="allow", target="https://bank.example")
        with mock.patch.object(audit, "MAX_BYTES", 10):  # every record rotates the log
            for _ in range(audit.KEEP):
                audit.record(agent="ag-x", tool="session_state", decision="allow")
        self.assertTrue(audit.audit_path().with_suffix(f".jsonl.{audit.KEEP}").exists())
        tools_seen = [e["tool"] for e in audit.read(limit=1000, agent="ag-x")]
        self.assertEqual(tools_seen, ["evaluate"] + ["session_state"] * audit.KEEP)
        audit.clear()
        self.assertEqual(audit.read(), [])

    def test_a_new_key_ends_a_session_opened_with_the_old_one(self):
        # Audit A11: "Nova chave" left a session that started with the old key working.
        agent, _ = registry.add("keyed", "other", "full_control", accept_full_control=True)
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver(), key_sha256=agent["token_sha256"])
        page = {"text": "ok", "url": "https://example.org/", "title": "t"}
        with (
            mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"),
            mock.patch.object(tools.Bridge, "_eval", return_value=page),
            mock.patch.object(tools.Bridge, "_open_dialog", return_value=None),
        ):
            self.assertFalse(bridge.call("page_read", {"tab": "t1"})["isError"])
            registry.rotate_token(agent["id"])
            result = bridge.call("page_read", {"tab": "t1"})
        self.assertTrue(result["isError"])
        self.assertIn("replaced this agent's key", result["content"][0]["text"])

    def test_a_held_session_gets_no_tool_but_its_state(self):
        # LESIS 987a7ec1: profiles_list has no capability, so nothing checked it. A session connected
        # before a revoke, a pause or the stop still read the agent's profiles and routes.
        def held_by(change, undo=None):
            agent, _ = registry.add("lists", "other", "autonomous")
            registry.set_profiles(agent["id"], [{"label": "Trabalho", "path": "/home/u/.nulavio/p1"}])
            registry.set_routes(agent["id"], [{"site": "intranet.example.org", "profile": "Trabalho"}])
            bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver(), key_sha256=agent["token_sha256"])
            self.assertIn("intranet.example.org", json.dumps(bridge.call("profiles_list", {})))
            change(agent["id"])
            result = bridge.call("profiles_list", {})
            names = {tool["name"] for tool in bridge.list_tools()}
            state = bridge.call("session_state", {})
            if undo:
                undo(agent["id"])
            return result, names, state

        cases = {
            "revoked": (registry.revoke, None),
            "paused": (lambda agent_id: registry.pause(agent_id, True), None),
            "stopped": (lambda _id: registry.set_stopped(True), lambda _id: registry.set_stopped(False)),
            "key-replaced": (registry.rotate_token, None),
        }
        for reason, (change, undo) in cases.items():
            with self.subTest(reason=reason):
                result, names, state = held_by(change, undo)
                self.assertTrue(result["isError"], result)
                self.assertNotIn("Trabalho", json.dumps(result))
                self.assertNotIn("intranet.example.org", json.dumps(result))
                entry = json.loads(audit.audit_path().read_text().splitlines()[-2])  # then session_state
                self.assertEqual((entry["tool"], entry["decision"], entry["reason"]), ("profiles_list", "deny", reason))
                self.assertEqual(entry["capability"], "profiles_list")  # what was refused, also when it needs no capability
                self.assertEqual(names, {"session_state"})
                self.assertFalse(state["isError"], state)  # the one tool left: it says why
                told = state["structuredContent"]
                self.assertEqual(told["key_replaced"], reason == "key-replaced")
                if reason in ("revoked", "key-replaced"):  # no longer this session's to read
                    self.assertFalse({"sites", "capabilities", "autonomy", "workspace"} & set(told), told)

    def test_a_key_replaced_while_a_request_is_open_denies_it(self):
        # A request can wait for minutes; "allow once" then went to a session whose key was gone.
        agent, _ = registry.add("waits", "other", "assisted")
        approver = Approve("once", meanwhile=lambda: registry.rotate_token(agent["id"]))
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver, key_sha256=agent["token_sha256"])
        with self.assertRaises(tools.Denied) as denied:
            bridge.require("submit_forms", "https://example.org/", checked=[])
        self.assertEqual(denied.exception.decision.reason, "key-replaced")
        self.assertEqual(approver.asked, [("submit_forms", "https://example.org")])

    def test_a_site_list_also_bounds_addresses_without_a_host(self):
        # "Only these sites": a file: address has no site, so it is not one of them; local_resources alone does not
        # open it for such an agent. Without a site list it stays what local_resources allows.
        agent, _ = registry.add("files", "other", "full_control", domains=["example.org"], accept_full_control=True)
        bridge = tools.Bridge(agent["id"], "s-1", approver=Approve("session"))
        for url in ("file:///etc/passwd", "file:///home/u/", "about:srcdoc", "file://example.org/etc/passwd",
                    "file://docs.example.org/etc/passwd"):  # fmt: skip
            with self.subTest(url=url):
                decision = registry.decide(agent["id"], "navigate", host=policy.host_of(url), target=policy.origin(url),
                                           session_id="s-1", approver=registry.Approver())  # fmt: skip
                self.assertEqual((decision.allowed, decision.reason), (False, "out-of-scope"))
        for url in ("file:///etc/passwd", "file://example.org/etc/passwd"):  # refused before the engine is asked
            with (
                self.subTest(url=url),
                mock.patch.object(tools.Bridge, "_url_of", return_value="about:blank"),
                mock.patch.object(tools.Bridge, "bidi", side_effect=AssertionError("navigated")),
            ):
                result = bridge.call("navigate", {"tab": "t1", "url": url})
                self.assertTrue(result["isError"], result)
                self.assertIn("outside the sites", result["content"][0]["text"])
        with self.assertRaises(tools.Denied) as denied:
            bridge.require_url("file:///etc/passwd", checked=[])
        self.assertEqual(denied.exception.decision.reason, "out-of-scope")
        page = {"text": "root:x:0:0", "url": "file:///etc/passwd", "title": ""}
        with (
            mock.patch.object(tools.Bridge, "_url_of", return_value="file:///etc/passwd"),
            mock.patch.object(tools.Bridge, "_eval", return_value=page),
            mock.patch.object(tools.Bridge, "_open_dialog", return_value=None),
        ):
            result = bridge.call("page_read", {"tab": "t1"})
        self.assertTrue(result["isError"], result)
        self.assertNotIn("root:x", json.dumps(result))
        self.assertEqual(json.loads(audit.audit_path().read_text().splitlines()[-1])["reason"], "out-of-scope")
        # No address at all, about:blank and the listed site stay in scope.
        bridge.require("navigate", checked=[])
        bridge.require_url("about:blank", checked=[])
        with mock.patch.object(policy, "_resolves_locally", return_value=False):
            bridge.require_url("https://docs.example.org/a", checked=[])
        anywhere, _ = registry.add("anywhere", "other", "full_control", accept_full_control=True)
        decision = registry.decide(anywhere["id"], "navigate", host=policy.host_of("file:///etc/passwd"), target="file:",
                                   session_id="s-1", approver=registry.Approver())  # fmt: skip
        self.assertTrue(decision.allowed)

    def test_the_source_viewer_is_refused_before_anything_is_asked(self):
        # LESIS afa509d1: with raw automation on, view-source: took an agent outside its sites. Raw automation is gone
        # (#463): an internal page is refused before any question, so the person is never asked for local_resources
        # for a page the agent could not open anyway (independent review of #504).
        agent, _ = registry.add("scoped", "other", "autonomous", domains=["example.org"])
        approver = Approve("session")
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        outside, inside = "view-source:https://bank.example/acct", "view-source:https://docs.example.org/a"
        for url in (outside, inside, "about:config"):
            with (
                self.subTest(url=url),
                mock.patch.object(tools.Bridge, "_url_of", return_value="about:blank"),
                mock.patch.object(tools.Bridge, "bidi", side_effect=AssertionError("navigated")),
            ):
                result = bridge.call("navigate", {"tab": "t1", "url": url})
                self.assertTrue(result["isError"])
                self.assertIn("not offered to agents", result["content"][0]["text"])
                self.assertNotIn("Only the user can change this", result["content"][0]["text"])
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual(entry["reason"], "internal-pages-off")
        self.assertEqual(approver.asked, [], "nothing is asked for an internal page")
        self.assertNotIn("local_resources", registry.get(agent["id"]).get("session_grants", {}))
        # A tab that is already there (a redirect, the page's own navigation): refused too, inside the sites or not.
        for url, reason in ((outside, "internal-pages-off"), (inside, "internal-pages-off")):
            page = {"text": "<html>", "url": url, "title": ""}
            with (
                self.subTest(url=url),
                mock.patch.object(tools.Bridge, "_url_of", return_value=url),
                mock.patch.object(tools.Bridge, "_eval", return_value=page),
                mock.patch.object(tools.Bridge, "_open_dialog", return_value=None),
            ):
                self.assertTrue(bridge.call("page_read", {"tab": "t1"})["isError"])
                self.assertEqual(json.loads(audit.audit_path().read_text().splitlines()[-1])["reason"], reason)
        self.assertEqual(approver.asked, [])
        # The tool's own question is not asked either for a tab already at an internal page: a Restricted agent's
        # dialog would ask for interact, an Autonomous one's evaluate for execute_js (independent review of #504).
        reader = "about:reader?url=https://docs.example.org/a"
        for level, tool, args in (("restricted", "dialog", {"tab": "t1", "accept": True}),
                                  ("autonomous", "evaluate", {"tab": "t1", "expression": "1"})):  # fmt: skip
            other, _ = registry.add(level, "other", level)
            asks = Approve("session")
            with self.subTest(tool=tool), mock.patch.object(tools.Bridge, "_url_of", return_value=reader):
                result = tools.Bridge(other["id"], "s-2", approver=asks).call(tool, args)
                self.assertTrue(result["isError"])
                self.assertEqual(json.loads(audit.audit_path().read_text().splitlines()[-1])["reason"], "internal-pages-off")
                self.assertEqual(asks.asked, [])
                self.assertEqual(registry.get(other["id"]).get("session_grants", {}), {})
        tabs = [{"context": "t1", "profile": "AI Workspace", "url": outside}]
        with mock.patch.object(tools.Bridge, "_tabs", return_value=tabs), mock.patch.object(tools.Bridge, "_title") as title:
            listed = bridge.call("tabs_list", {})["structuredContent"]["tabs"]
        self.assertEqual((listed[0]["url"], listed[0]["outside_sites"]), (None, True))
        title.assert_not_called()

    def test_an_address_agents_never_act_on_is_refused_before_the_tools_question(self):
        # #508: a tab already at data: or blob: was refused only after the tool's own question (interact, execute_js),
        # and a "for this session" answer stayed for a capability the agent could not use there.
        for level, tool, args in (("restricted", "dialog", {"tab": "t1", "accept": True}),
                                  ("autonomous", "evaluate", {"tab": "t1", "expression": "1"})):  # fmt: skip
            for url in ("data:text/html,<p>hi", "blob:https://example.org/3f6c"):
                agent, _ = registry.add(f"{level}-{url[:4]}", "other", level)
                asks = Approve("session")
                with (
                    self.subTest(tool=tool, url=url),
                    mock.patch.object(tools.Bridge, "_url_of", return_value=url),
                    mock.patch.object(tools.Bridge, "bidi", side_effect=AssertionError("acted")),
                ):
                    result = tools.Bridge(agent["id"], "s-1", approver=asks).call(tool, args)
                    self.assertTrue(result["isError"])
                    self.assertIn("an address agents do not act on", result["content"][0]["text"])
                    entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                    self.assertEqual((entry["tool"], entry["outcome"]), (tool, "error:tool"))
                    self.assertTrue(entry.get("target", "").startswith(url.split(":")[0] + ":"), entry)
                    self.assertEqual(asks.asked, [])
                    self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})

    def test_a_tab_that_needs_more_than_reading_is_not_described(self):
        # LESIS 83a648d8, c6bc7acd: a redirect leaves the tab on the local network; page_read then
        # asks for local_resources (audit A1), but tabs_list still gave its address and title.
        agent, _ = registry.add("near", "other", "restricted")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        tabs = [
            {"context": "t1", "profile": "AI Workspace", "url": "https://example.org/a"},
            {"context": "t2", "profile": "AI Workspace", "url": "http://192.168.1.1/admin/wifi"},
            {"context": "t3", "profile": "AI Workspace", "url": "about:config"},
            {"context": "t4", "profile": "AI Workspace", "url": "blob:https://example.org/3f6c"},
            {"context": "t5", "profile": "AI Workspace", "url": "about:blank"},
        ]
        with (
            mock.patch.object(tools.Bridge, "_tabs", return_value=tabs),
            mock.patch.object(tools.Bridge, "_title", side_effect=lambda tab, _c: f"title of {tab}") as title,
        ):
            listed = {entry["tab"]: entry for entry in bridge.call("tabs_list", {})["structuredContent"]["tabs"]}
            self.assertEqual({call.args[0] for call in title.call_args_list}, {"t1", "t5"})
            self.assertEqual(listed["t1"]["url"], "https://example.org/a")
            self.assertEqual(listed["t5"]["url"], "about:blank")
            self.assertEqual((listed["t2"]["url"], listed["t2"]["title"]), (None, None))
            self.assertEqual(listed["t2"]["needs_permission"], ["local_resources"])
            self.assertEqual(listed["t3"]["needs_permission"], ["local_resources", "debugging"])
            self.assertEqual(listed["t4"]["needs_permission"], ["local_resources"])
            self.assertNotIn("192.168.1.1", json.dumps(listed))
            registry.grant(agent["id"], "local_resources", "allow")
            listed = {entry["tab"]: entry for entry in bridge.call("tabs_list", {})["structuredContent"]["tabs"]}
            self.assertEqual(listed["t2"]["url"], "http://192.168.1.1/admin/wifi")

    def acting(self, level, approver, *, held, info=None):
        """A Bridge whose page is a stand-in. `held`: what the page's documents report as held forms,
        one answer for each time they are asked. Returns the bridge and what happened, in order."""
        agent, _ = registry.add(f"forms-{level}-{len(registry.load()['agents'])}", "other", level)
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        bridge.elements["t1"] = {"e1": "shared-1"}
        bridge._forms_ever = level != "autonomous"  # its documents got the guard when the engine started
        steps, answers = [], list(held)
        engine = mock.Mock()
        engine.mark.return_value = 0
        engine.command.side_effect = lambda method, *_a, **_k: steps.append(method) or {}
        names = {tools.FORMS_GUARD_FN: "guard", tools.FORMS_HELD_FN: "held?", tools.FORMS_DROP_FN: "drop",
                 tools.FORMS_SEND_FN: "send", tools.FORMS_OPEN_FN: "open"}  # fmt: skip

        def in_frames(_self, _tab, fn, _cancel, *, must):
            steps.append(names[fn])
            return [answers.pop(0)] if fn == tools.FORMS_HELD_FN else [1]

        ahead = []  # inside _act_here: the look before the question (#736)
        act_here = tools.Bridge._act_here

        def acts_here(_self, *args, **kwargs):
            ahead.append(True)
            try:
                return act_here(_self, *args, **kwargs)
            finally:
                ahead.pop()

        def forms_where(_self, _tab, _cancel, **_k):  # the documents that hold a form, by the realm of their sandbox
            if not _self._forms_ever:
                return []
            if ahead:  # nothing happens on the page between the look and the count that follows it
                steps.append("look")
                return ["realm-1"] if answers[:1] and answers[0] else []
            steps.append("held?")
            return ["realm-1"] if answers.pop(0) else []

        def in_realms(_self, _tab, realms, fn, _cancel, until=None):
            assert realms == ["realm-1"], realms
            steps.append(names[fn])
            return [1], ""

        def call_fn(_self, _tab, fn, _args, _cancel, *, sandbox=False, **_k):
            if sandbox:  # the look before the question reads the element where the page does not see it
                self.assertEqual(fn, tools.INSPECT_FN)
                steps.append("look")
            else:
                steps.append({tools.INSPECT_FN: "inspect", tools.SCROLL_FN: "scroll", tools.FOCUS_FN: "focus"}[fn])
            return info or {"connected": True, "editable": True, "multiline": True}

        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name, how in (
            ("_url_of", {"return_value": "https://example.org/cart"}),
            ("bidi", {"return_value": engine}),
            ("_settle", {"return_value": False}),
            ("_open_dialog", {"return_value": None}),
            ("_in_frames", {"new": in_frames}),
            ("_forms_where", {"new": forms_where}),
            ("_in_realms", {"new": in_realms}),
            ("_call_fn", {"new": call_fn}),
            ("_act_here", {"new": acts_here}),
        ):
            stack.enter_context(mock.patch.object(tools.Bridge, name, **how))
        return bridge, steps

    CLICK = ("click", {"tab": "t1", "element": "e1"})
    INPUT = "input.performActions"

    def test_a_form_sent_by_a_click_handler_needs_submit_forms(self):
        # LESIS 3dea86ea: a role=button whose handler calls requestSubmit() is not a submit button
        # to INSPECT_FN, so the click went ahead on `interact` alone and the form was sent.
        bridge, steps = self.acting("assisted", registry.Approver(), held=[0, 1])
        result = bridge.call(*self.CLICK)
        self.assertTrue(result["isError"], result)
        self.assertIn("'Submit forms'", result["content"][0]["text"])
        self.assertIn("The click was done; the form the page then tried to send was not sent.", result["content"][0]["text"])
        self.assertEqual((steps.count(self.INPUT), steps[-1], "send" in steps), (1, "drop", False))
        self.assertLess(steps.index("guard"), steps.index("scroll"))  # held before anything the page can observe
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["decision"], entry["capability"]), ("deny", "interact,submit_forms"))

        # The user says yes: the form that was held goes as it was. No second click.
        approver = Approve("once")
        bridge, steps = self.acting("assisted", approver, held=[0, 1])
        result = bridge.call(*self.CLICK)
        self.assertFalse(result["isError"], result)
        self.assertTrue(result["structuredContent"]["navigated"])
        self.assertEqual(approver.asked, [("submit_forms", "https://example.org")])
        self.assertEqual((steps.count(self.INPUT), steps.count("send"), "drop" in steps), (1, 1, False))

        # A click that sends nothing is only a click.
        approver = Approve("once")
        bridge, steps = self.acting("assisted", approver, held=[0, 0])
        self.assertFalse(bridge.call(*self.CLICK)["isError"])
        self.assertEqual((approver.asked, "send" in steps, "drop" in steps), ([], False, False))

        # Allowed to submit without asking: nothing is held and nothing is asked of the page.
        bridge, steps = self.acting("autonomous", registry.Approver(), held=[])
        self.assertFalse(bridge.call(*self.CLICK)["isError"])
        self.assertEqual([s for s in steps if s in ("guard", "held?", "send", "drop", "open")], [])

        # A real submit button asks before the click, as before; its form is held like any other
        # and then sent without a second question.
        approver = Approve("once")
        submit = {"connected": True, "submits": True}
        bridge, steps = self.acting("assisted", approver, held=[0, 1], info=submit)
        self.assertFalse(bridge.call(*self.CLICK)["isError"])
        self.assertEqual(approver.asked, [("submit_forms", "https://example.org")])
        self.assertLess(steps.index("inspect"), steps.index(self.INPUT))
        self.assertEqual(steps.count("send"), 1)

    def test_a_form_the_page_sent_later_is_settled_before_the_next_action(self):
        # A timer, or the answer to a dialog, sent it after the call returned: it is still held.
        bridge, steps = self.acting("assisted", registry.Approver(), held=[2])
        result = bridge.call(*self.CLICK)
        self.assertTrue(result["isError"], result)
        self.assertIn(
            "An earlier action was done; the form the page then tried to send was not sent.", result["content"][0]["text"]
        )
        self.assertEqual((self.INPUT in steps, "inspect" in steps, steps[-1]), (False, False, "drop"))
        bridge, steps = self.acting("assisted", Approve("once"), held=[2])
        result = bridge.call(*self.CLICK)
        self.assertFalse(result["isError"], result)
        self.assertTrue(result["structuredContent"]["form_sent"])
        self.assertIn("Nothing else was done", result["content"][0]["text"])
        self.assertEqual((self.INPUT in steps, steps.count("send")), (False, 1))

    def test_a_form_sent_while_typing_or_after_a_dialog_needs_submit_forms(self):
        typing = ("type", {"tab": "t1", "element": "e1", "text": "123456", "clear": True})
        bridge, steps = self.acting("assisted", registry.Approver(), held=[0, 1])
        result = bridge.call(*typing)
        self.assertTrue(result["isError"], result)
        self.assertIn("The typing was done; the form the page then tried to send was not sent.", result["content"][0]["text"])
        # The focus and the clearing run the page's handlers: the forms are held before them.
        self.assertLess(steps.index("guard"), min(steps.index("scroll"), steps.index("focus")))
        bridge, steps = self.acting("assisted", Approve("once"), held=[0, 1])
        result = bridge.call(*typing)
        self.assertFalse(result["isError"], result)
        self.assertEqual((result["structuredContent"]["navigated"], steps.count("send")), (True, 1))
        # submit=true was allowed for this call: what Enter sends is held and then let go, unasked.
        approver = Approve("once")
        bridge, steps = self.acting("assisted", approver, held=[0, 1])
        self.assertFalse(bridge.call("type", {"tab": "t1", "element": "e1", "text": "q", "submit": True})["isError"])
        self.assertEqual((len(approver.asked), steps.count("send")), (1, 1))

        # The page goes on after a dialog is answered, however the dialog came to be open.
        answer = ("dialog", {"tab": "t1", "accept": True})
        bridge, steps = self.acting("assisted", registry.Approver(), held=[1])
        with mock.patch.object(tools.Bridge, "_open_dialog", side_effect=[{"type": "confirm", "message": "Send?"}, None]):
            result = bridge.call(*answer)
        self.assertTrue(result["isError"], result)
        self.assertIn("The answer was done; the form the page then tried to send was not sent.", result["content"][0]["text"])
        self.assertEqual(steps[-1], "drop")

    def test_documents_hold_their_forms_from_the_moment_they_are_created(self):
        agent, _ = registry.add("frames", "other", "assisted")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())

        def engine():
            connection, commands = mock.Mock(), []

            def command(method, params=None, **_k):
                commands.append((method, params))
                if method == "network.addIntercept":
                    return {"intercept": f"intercept-{id(connection)}"}
                return {"script": f"preload-{id(connection)}"} if method == "script.addPreloadScript" else {}

            connection.command.side_effect = command
            return connection, commands

        first, commands = engine()
        bridge.workspace = mock.Mock(bidi=first)
        self.assertFalse(bridge._forms_ever)
        bridge._sync_forms()
        bridge._sync_forms()  # once for the engine, not once a call
        added = [params for method, params in commands if method == "script.addPreloadScript"]
        self.assertEqual(added, [{"functionDeclaration": tools.FORMS_GUARD_FN, "sandbox": tools.SANDBOX}])
        self.assertTrue(bridge._forms_ever)
        registry.grant(agent["id"], "submit_forms", "allow")  # the user allows it: new documents stop holding
        bridge._sync_forms()
        self.assertEqual(commands[-1], ("script.removePreloadScript", {"script": f"preload-{id(first)}"}))
        ran = []
        with mock.patch.object(tools.Bridge, "_in_frames", lambda _s, _t, fn, _c, *, must: ran.append((fn, must)) or [0]):
            bridge._forms_prepare("t1", None)  # and the ones already open are opened when next acted on
        self.assertEqual(ran, [(tools.FORMS_OPEN_FN, True)])
        registry.grant(agent["id"], "submit_forms", "ask")
        bridge._sync_forms()
        self.assertEqual(len([m for m, _ in commands if m == "script.addPreloadScript"]), 2)
        with (
            mock.patch.object(tools.Bridge, "_in_frames", return_value=[True, False]),  # a frame where submit() is out of reach
            self.assertRaises(tools.ToolError),
        ):
            bridge._forms_prepare("t1", None)
        # The engine ended behind the Bridge's back (raw automation ended by a pause) and a new one
        # started: it is another connection, and gets its own guard before its first navigation.
        second, commands = engine()
        bridge.workspace = mock.Mock(bidi=second)
        bridge.workspace.start.return_value = second
        self.assertIs(bridge.bidi(), second)
        self.assertEqual([m for m, _ in commands if m.startswith("script.")], ["script.addPreloadScript"])

    def test_an_answer_for_the_session_sends_the_form_it_was_given_for(self):
        # "Allow until the agent disconnects" in the middle of the call: the form is still held, and goes (it went
        # nowhere before, and later at an unrelated click). The answer is for that site in that place, so the page's
        # documents go on holding what they send, and a form of the same site goes later without a new question.
        approver = Approve("session")
        bridge, steps = self.acting("assisted", approver, held=[0, 1, 0, 1], info={"connected": True, "submits": True})
        result = bridge.call(*self.CLICK)
        self.assertFalse(result["isError"], result)
        self.assertEqual(approver.asked, [("submit_forms", "https://example.org")])
        self.assertEqual((result["structuredContent"]["navigated"], steps[-1]), (True, "send"))
        self.assertFalse(bridge.call(*self.CLICK)["isError"])
        self.assertEqual((len(approver.asked), steps[-1]), (1, "send"))
        # Asked after the click (a handler sent it): the same.
        approver = Approve("session")
        bridge, steps = self.acting("assisted", approver, held=[0, 1])
        self.assertTrue(bridge.call(*self.CLICK)["structuredContent"]["navigated"])
        self.assertEqual((len(approver.asked), steps[-1]), (1, "send"))

    def test_a_form_held_when_the_permission_came_is_sent_and_said_not_slipped_out(self):
        # The user allowed submitting (another tab's question, or in Settings) while this page held a
        # form: the next click sent it without a word, then failed on the page that had moved.
        bridge, steps = self.acting("assisted", registry.Approver(), held=[1])
        registry.grant(bridge.agent_id, "submit_forms", "allow")
        result = bridge.call(*self.CLICK)
        self.assertFalse(result["isError"], result)
        self.assertTrue(result["structuredContent"]["form_sent"])
        self.assertEqual((steps[:3], self.INPUT in steps), (["look", "held?", "open"], False))
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual(entry["capability"], "interact,submit_forms")

    def page(self, approver, *, domains=None, info=None):
        """A Bridge on a page that is real down to the engine's commands: one document, the sandbox
        it has (a new document has another), the forms it holds. Returns the bridge and the page.
        `page.click` is what the page does when it is clicked, `page.landed` what happens once a
        form of it was sent, `page.fails` the error the engine answers a call by realm with."""
        agent, _ = registry.add(f"page-{len(registry.load()['agents'])}", "other", "assisted", domains=domains)
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        bridge.elements["t1"] = {"e1": "shared-1"}
        bridge._forms_ever = True
        page = mock.Mock(url="https://example.org/cart", realm="realm-1", held=0, sent=[], dropped=[], fails=None)
        page.click = page.landed = lambda: None
        page.asks = page.dialog = None  # the dialog its submit handler opens; the one it has open

        def goes(url: str, held: int) -> None:
            page.url, page.realm, page.held = url, f"realm-{int(page.realm[6:]) + 1}", held

        page.goes = goes

        def command(method, params=None, **_k):
            if method == "browsingContext.getTree":
                return {"contexts": [{"context": "t1", "url": page.url, "children": []}]}
            if method == "input.performActions":
                page.click()
            if method == "browsingContext.navigate":
                page.goes(params["url"], held=1)  # a page that sends a form as it loads
            if method != "script.callFunction":
                return {}
            target, fn = params["target"], params["functionDeclaration"]
            if "realm" in target and page.fails:
                raise page.fails
            if page.asks and fn in (tools.FORMS_SEND_FN, tools.FORMS_OPEN_FN) and page.held and _k.get("until"):
                page.dialog, page.held = page.asks, 0  # the handler waits for the answer; the call does not return
                return None
            if target.get("realm", page.realm) != page.realm:
                raise tools.BidiError("no such frame", "the document is gone")
            self.assertEqual(target.get("sandbox", tools.SANDBOX), tools.SANDBOX)
            value, realm = (page.held if fn == tools.FORMS_HELD_FN else 1), page.realm
            if fn in (tools.FORMS_SEND_FN, tools.FORMS_OPEN_FN, tools.FORMS_DROP_FN):
                value, page.held = page.held, 0
                (page.dropped if fn == tools.FORMS_DROP_FN else page.sent).append((page.realm, page.url))
                if fn != tools.FORMS_DROP_FN:
                    page.landed()
            return {"type": "success", "realm": realm, "result": {"type": "number", "value": value}}

        engine = mock.Mock()
        engine.mark.return_value = 0
        engine.command.side_effect = command
        page.engine = engine
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name, how in (
            ("bidi", {"return_value": engine}),
            ("_settle", {"return_value": False}),
            ("_open_dialog", {"side_effect": lambda _tab: page.dialog}),
            ("_title", {"return_value": "t"}),
            ("_call_fn", {"return_value": info or {"connected": True, "editable": True, "multiline": True}}),
        ):
            stack.enter_context(mock.patch.object(tools.Bridge, name, **how))
        return bridge, page

    def moving(self, answer, to, **how):
        """A page that moves to `to`, where a form is sent as it loads, while the first question is
        open (and not at the later ones). Returns the bridge, the page and the approver."""
        pending = [lambda: page.goes(to, held=1)]
        approver = Approve(answer, meanwhile=lambda: pending.pop()() if pending else None)
        bridge, page = self.page(approver, **how)
        return bridge, page, approver

    def test_an_answer_does_not_send_the_form_of_the_page_the_tab_moved_to_meanwhile(self):
        # The question can stay open for minutes. The page moved on meanwhile, and the next one sent
        # a form by itself: the answer was given for the first page, and sent the second one's form.
        bridge, page, approver = self.moving("once", "https://other.example/x")
        page.click = lambda: setattr(page, "held", 1)  # a handler sends the form
        result = bridge.call(*self.CLICK)
        self.assertTrue(result["isError"], result)
        self.assertIn("while the question about its form was open the page moved on", result["content"][0]["text"])
        self.assertEqual(approver.asked, [("submit_forms", "https://example.org")])
        self.assertEqual((page.sent, page.dropped, page.held), ([], [], 1), "the new page's form is still held")
        # The form held there is judged at the next call, by that page's address, and asked about by name.
        page.click = lambda: self.fail("clicked: the earlier form comes first")
        result = bridge.call(*self.CLICK)
        self.assertTrue(result["structuredContent"]["form_sent"], result)
        self.assertEqual(approver.asked[1:], [("submit_forms", "https://other.example")])
        self.assertEqual(page.sent, [("realm-2", "https://other.example/x")])

        # Refused: what is dropped is the form that was asked about, not the next page's.
        bridge, page, approver = self.moving("deny", "https://example.org/other")
        page.click = lambda: setattr(page, "held", 1)
        self.assertTrue(bridge.call(*self.CLICK)["isError"])
        self.assertEqual((page.sent, page.dropped, page.held), ([], [], 1))

    def test_an_answer_for_the_session_does_not_open_the_page_the_tab_moved_to_meanwhile(self):
        # "Allow until the agent disconnects" turns the permission on. The call then went on to the
        # page the tab had moved to, outside the agent's sites, and let that page's forms go.
        for began_held in (0, 1):  # asked after the click, or about a form held since an earlier action
            with self.subTest(began_held=began_held):
                bridge, page, _approver = self.moving("session", "http://192.168.1.1/apply", domains=["example.org"])
                page.held = began_held
                page.click = lambda page=page: setattr(page, "held", 1)
                result = bridge.call(*self.CLICK)
                self.assertTrue(result["isError"], result)
                self.assertIn("nothing was sent", result["content"][0]["text"])
                self.assertEqual((page.sent, page.held, page.realm), ([], 1, "realm-2"))
                self.assertNotIn("192.168.1.1", json.dumps(result))
                # And the next call there is refused by the site list before anything is asked of the page.
                asked_of_the_page = page.engine.command.call_count
                self.assertTrue(bridge.call(*self.CLICK)["isError"])
                self.assertEqual((page.sent, page.held), ([], 1))
                self.assertEqual(page.engine.command.call_count, asked_of_the_page + 1)  # where the tab is

    def test_a_session_ended_while_a_form_was_asked_about_asks_nothing_more_of_the_engine(self):
        # A revocation or the stop closes the workspace. Dropping the held form then went looking
        # for the tab's engine, which started the workspace again.
        def ended_by(end):
            seen = []

            def meanwhile():
                end(bridge)
                seen.append(page.engine.command.call_count)

            bridge, page = self.page(Approve("once", meanwhile=meanwhile))
            page.click = lambda: setattr(page, "held", 1)
            with mock.patch.object(tools.Bridge, "close") as closed:
                result = bridge.call(*self.CLICK)
            self.assertTrue(result["isError"], result)
            self.assertEqual([page.engine.command.call_count], seen, "nothing after the session ended")
            self.assertEqual((page.sent, page.dropped), ([], []))
            return json.loads(audit.audit_path().read_text().splitlines()[-1])["reason"], closed.called

        self.assertEqual(ended_by(lambda bridge: registry.revoke(bridge.agent_id)), ("revoked", True))
        self.assertEqual(ended_by(lambda bridge: registry.pause(bridge.agent_id, True)), ("paused", False))
        self.addCleanup(registry.set_stopped, False)
        self.assertEqual(ended_by(lambda _bridge: registry.set_stopped(True)), ("stopped", True))

    def test_a_form_of_the_page_an_action_led_to_is_judged_by_that_page(self):
        # A submit button, allowed for its page, leads to another site whose page sends a form as it
        # loads: "submit_forms" had been checked for this call, and the second form went with it.
        submit = {"connected": True, "submits": True}
        approver = Approve("once")
        bridge, page = self.page(approver, info=submit)
        page.click = lambda: page.goes("https://pay.example/confirm", held=1)
        result = bridge.call(*self.CLICK)
        self.assertFalse(result["isError"], result)
        self.assertEqual(approver.asked, [("submit_forms", "https://example.org"), ("submit_forms", "https://pay.example")])
        self.assertEqual(page.sent, [("realm-2", "https://pay.example/confirm")])
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])  # the activity says where the form went out
        self.assertEqual((entry["capability"], entry["target"]), ("interact,submit_forms", "https://pay.example"))

        class FormsOnly(Approve):  # yes to submitting, no to the local network
            def ask(self, agent, capability, target, place="", cancel=None):
                super().ask(agent, capability, target, place, cancel)
                return "once" if capability == "submit_forms" else "deny"

        # Outside the agent's sites, or on the local network: not asked about, and not sent.
        for where, domains in (("https://pay.example/confirm", ["example.org"]), ("http://192.168.1.1/apply", None)):
            with self.subTest(where=where):
                approver = FormsOnly("once")
                bridge, page = self.page(approver, domains=domains, info=submit)
                page.click = lambda page=page, where=where: page.goes(where, held=1)
                result = bridge.call(*self.CLICK)
                self.assertTrue(result["isError"], result)
                self.assertIn("The click was done and took the tab elsewhere", result["content"][0]["text"])
                self.assertNotIn(("submit_forms", policy.origin(where)), approver.asked)
                self.assertEqual((page.sent, page.held), ([], 1))
        # The same site, in another document: the permission of this call stands.
        approver = Approve("once")
        bridge, page = self.page(approver, info=submit)
        page.click = lambda: page.goes("https://example.org/thanks", held=1)
        self.assertFalse(bridge.call(*self.CLICK)["isError"])
        self.assertEqual((len(approver.asked), page.sent), (1, [("realm-2", "https://example.org/thanks")]))

    def test_each_site_a_chain_of_forms_goes_through_is_asked_about(self):
        # A page that sends a form as it loads, to a page of another site that does the same: one
        # answer, given for the first site, sent them all.
        hops = ["https://bank.example/confirm", "https://bank.example/done"]
        hops_taken = list(hops)
        approver = Approve("once")
        bridge, page = self.page(approver)
        page.landed = lambda: page.goes(hops.pop(0), held=1) if hops else None
        result = bridge.call("navigate", {"tab": "t1", "url": "https://example.org/pay"})
        self.assertFalse(result["isError"], result)
        self.assertEqual(approver.asked, [("submit_forms", "https://example.org"), ("submit_forms", "https://bank.example")])
        # The third form is the second site's again: the answer given for that site in this call stands.
        self.assertEqual([url for _realm, url in page.sent], ["https://example.org/pay", *hops_taken])
        # Four forms are sent; where the fourth lands is checked like the others.
        agent_hops = [f"https://example.org/{n}" for n in (2, 3, 4)] + ["https://bank.example/acct?id=4"]
        bridge, page = self.page(registry.Approver(), domains=["example.org"])
        registry.grant(bridge.agent_id, "submit_forms", "allow")
        page.landed = lambda: page.goes(agent_hops.pop(0), held=1)
        result = bridge.call("navigate", {"tab": "t1", "url": "https://example.org/1"})
        self.assertEqual(len(page.sent), 4)
        self.assertTrue(result["isError"], result)
        self.assertIn("is not described. The tab is t1.", result["content"][0]["text"])
        self.assertNotIn("bank.example", json.dumps(result))
        # A fifth form stays held (for the next action there), on a page the agent may see.
        bridge, page = self.page(Approve("session"))
        page.landed = lambda: page.goes(f"https://example.org/{len(page.sent) + 1}", held=1)
        result = bridge.call("navigate", {"tab": "t1", "url": "https://example.org/1"})
        self.assertFalse(result["isError"], result)
        self.assertEqual((len(page.sent), page.held, result["structuredContent"]["url"]), (4, 1, "https://example.org/5"))
        # An error on the way names the tab too (tab_new made it; the agent has no other way to it).
        bridge, page, _approver = self.moving("once", "https://other.example/x")
        result = bridge.call("navigate", {"tab": "t1", "url": "https://example.org/pay"})
        self.assertIn("nothing was sent. Call page_snapshot again. The tab is t1.", result["content"][0]["text"])

    def test_a_form_the_engine_does_not_answer_for_is_not_said_to_be_sent_or_held(self):
        # "The document is gone" is one answer; a timeout is not that one, and is not asked twice:
        # what the page did by then is not known.
        bridge, page = self.page(Approve("once"))
        page.click = lambda: setattr(page, "held", 1)
        page.fails = tools.BidiError("timeout", "script.callFunction took longer than 5 s")
        result = bridge.call(*self.CLICK)
        self.assertTrue(result["isError"], result)
        self.assertIn("may or may not have been sent", result["content"][0]["text"])
        sends = [c for c in page.engine.command.call_args_list if c.args[1:] and "realm" in c.args[1].get("target", {})]
        self.assertEqual((len(sends), page.sent, page.held), (1, [], 1))
        calls = {
            "_in_realms": lambda: bridge._in_realms("t1", ["realm-1"], tools.FORMS_SEND_FN, None),
            "_in_frames": lambda: bridge._in_frames("t1", tools.FORMS_HELD_FN, None, must=False),
            "_forms_where": lambda: bridge._forms_where("t1", None),
        }
        for name, cancelled in calls.items():  # a cancel is not "the frame went away"
            with (
                self.subTest(cancelled=name),
                mock.patch.object(tools.Bridge, "_in_sandbox", side_effect=tools.Cancelled()),
                self.assertRaises(tools.Cancelled),
            ):
                cancelled()
        # A count with no realm cannot be tied to its document: nothing is sent on it.
        page.fails = None
        with mock.patch.object(tools.Bridge, "_in_sandbox", return_value=(1, "")), self.assertRaises(tools.ToolError):
            bridge._forms_where("t1", None)
        # An agent whose documents never held anything is not asked about forms at all.
        bridge._forms_ever = False
        before = page.engine.command.call_count
        self.assertEqual(bridge._forms_where("t1", None), [])
        self.assertEqual(page.engine.command.call_count, before)

    def test_a_dialog_the_forms_own_handler_opens_is_reported_not_an_error(self):
        # onsubmit="return confirm('Send?')": the handler runs when the held form is let go, and the
        # engine does not answer until the dialog is. That was a timeout, then "nothing was sent".
        asks = {"type": "confirm", "message": "Send?"}
        bridge, page = self.page(Approve("once"))
        page.asks = asks
        page.click = lambda: setattr(page, "held", 1)
        result = bridge.call(*self.CLICK)
        self.assertFalse(result["isError"], result)
        self.assertEqual((result["structuredContent"]["dialog"], result["structuredContent"]["navigated"]), (asks, False))
        # A form held since an earlier action: the same, and the call does not go on to click under the dialog.
        bridge, page = self.page(Approve("once"))
        page.asks, page.held = asks, 1
        page.click = lambda: self.fail("clicked under a dialog")
        result = bridge.call(*self.CLICK)
        self.assertEqual((result["isError"], result["structuredContent"]["dialog"]), (False, asks))
        self.assertIn("answer the dialog", result["content"][0]["text"])
        # After the dialog is answered, the page's next dialog is in the answer too.
        bridge, page = self.page(Approve("once"))
        page.dialog = {"type": "confirm", "message": "Proceed?"}
        real = page.engine.command.side_effect

        def answered(method, *args, **kwargs):
            if method == "browsingContext.handleUserPrompt":
                page.dialog, page.held, page.asks = None, 1, asks  # "if (confirm(…)) form.requestSubmit()"
            return real(method, *args, **kwargs)

        page.engine.command.side_effect = answered
        result = bridge.call("dialog", {"tab": "t1", "accept": True})
        self.assertEqual((result["isError"], result["structuredContent"].get("dialog")), (False, asks))

    def test_the_activity_names_the_site_that_was_refused(self):
        class Answers(Approve):  # one answer for each question, in order
            def ask(self, agent, capability, target, place="", cancel=None):
                super().ask(agent, capability, target, place, cancel)
                return self.answer.pop(0)

        bridge, page = self.page(Answers(["once", "deny"]))
        hops = ["https://bank.example/confirm"]
        page.landed = lambda: page.goes(hops.pop(0), held=1)
        result = bridge.call("navigate", {"tab": "t1", "url": "https://example.org/pay"})
        self.assertTrue(result["isError"], result)
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["decision"], entry["target"]), ("deny", "https://bank.example"))
        self.assertEqual(bridge.last_call["origin"], "https://bank.example")
        # An answer counts within its call: the same site is asked about again a call later, and the
        # site a form went out for is not the next call's target.
        bridge, page = self.page(Approve("once"), info={"connected": True, "submits": True})
        page.click = lambda: page.goes("https://pay.example/confirm", held=1)
        self.assertFalse(bridge.call(*self.CLICK)["isError"])
        asked = len(bridge.approver.asked)
        page.click = lambda: setattr(page, "held", 1)
        self.assertFalse(bridge.call(*self.CLICK)["isError"])
        self.assertEqual(bridge.approver.asked[asked:], [("submit_forms", "https://pay.example")])
        page.url = "https://example.org/back"
        with mock.patch.object(tools.Bridge, "_eval", return_value={"text": "ok", "url": page.url, "title": "t"}):
            self.assertFalse(bridge.call("page_read", {"tab": "t1"})["isError"])
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["tool"], entry["target"]), ("page_read", "https://example.org"))

    def test_where_an_action_left_the_tab_is_not_described_outside_the_agents_sites(self):
        # tabs_list does not say where such a tab is; the click that took it there did.
        typing = ("type", {"tab": "t1", "element": "e1", "text": "abc"})
        for where, domains, says in (
            ("https://bank.example/acct?id=4", ["example.org"], {"outside_sites": True}),
            ("http://192.168.1.1/admin/wifi", None, {"needs_permission": ["local_resources"]}),
        ):
            for action in (self.CLICK, typing):
                with self.subTest(where=where, action=action[0]):
                    bridge, page = self.page(registry.Approver(), domains=domains)

                    def leaves(page=page, where=where):
                        page.goes(where, held=0)
                        page.dialog = {"type": "alert", "message": "Balance: 1 234,00"}

                    page.click = leaves
                    result = bridge.call(*action)
                    self.assertFalse(result["isError"], result)
                    self.assertEqual({k: result["structuredContent"].get(k) for k in ("url", *says)}, {"url": None, **says})
                    self.assertEqual(result["structuredContent"]["dialog"], {"type": "alert", "message": None})
                    self.assertNotIn(policy.host_of(where), json.dumps(result))
                    self.assertNotIn("Balance", json.dumps(result))
        # An earlier form that was sent, and where it landed.
        bridge, page = self.page(registry.Approver(), domains=["example.org"])
        registry.grant(bridge.agent_id, "submit_forms", "allow")
        page.held, page.landed = 1, lambda: page.goes("https://bank.example/acct?id=4", held=0)
        result = bridge.call(*self.CLICK)
        self.assertEqual((result["structuredContent"]["form_sent"], result["structuredContent"]["url"]), (True, None))
        self.assertNotIn("bank.example", json.dumps(result))
        # Inside the sites, the address is given; and so is the one the call was allowed for by an answer.
        bridge, page = self.page(registry.Approver(), domains=["example.org"])
        page.click = lambda: page.goes("https://docs.example.org/a", held=0)
        self.assertEqual(bridge.call(*self.CLICK)["structuredContent"]["url"], "https://docs.example.org/a")
        bridge, page = self.page(Approve("once"))
        registry.grant(bridge.agent_id, "local_resources", "ask")
        page.url = "http://192.168.1.10:3000/app"
        result = bridge.call(*self.CLICK)
        self.assertEqual(bridge.approver.asked, [("local_resources", "http://192.168.1.10:3000")])
        self.assertEqual(result["structuredContent"]["url"], "http://192.168.1.10:3000/app")
        # A tab that moved while a question was open: the refusal does not say where to, either.
        bridge, page, approver = self.moving("once", "http://192.168.1.1/apply", info={"connected": True, "submits": True})
        result = bridge.call(*self.CLICK)
        self.assertEqual(approver.asked, [("submit_forms", "https://example.org")])
        self.assertIn("the tab moved to another site while waiting for approval", result["content"][0]["text"])
        self.assertNotIn("192.168.1.1", json.dumps(result))

    def test_a_page_that_sends_a_form_as_it_loads_is_settled_by_the_navigation(self):
        # Nothing reported a form held by a load, an upload or a timer; it stayed held for good.
        bridge, steps = self.acting("assisted", registry.Approver(), held=[1])
        result = bridge.call("navigate", {"tab": "t1", "url": "https://example.org/cart"})
        self.assertTrue(result["isError"], result)
        self.assertIn("The navigation was done; the form the page then tried to send was not sent.", result["content"][0]["text"])
        self.assertEqual(steps[-1], "drop")
        bridge, steps = self.acting("assisted", Approve("once"), held=[1, 0])
        with mock.patch.object(tools.Bridge, "_title", return_value="t"):
            self.assertFalse(bridge.call("navigate", {"tab": "t1", "url": "https://example.org/cart"})["isError"])
        self.assertEqual(steps[-2:], ["send", "held?"])  # and where the form landed is looked at again
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual(entry["capability"], "navigate,submit_forms")  # the activity shows that a form went out
        # Where the sent form lands is checked like any place a redirect ends: outside the agent's
        # sites, it is not described.
        agent, _ = registry.add("lands", "other", "autonomous", domains=["example.org"])
        registry.grant(agent["id"], "submit_forms", "ask")
        scoped = tools.Bridge(agent["id"], "s-1", approver=Approve("once"))
        scoped._forms_ever = True
        engine = mock.Mock()
        engine.command.return_value = {}
        engine.mark.return_value = 0
        places = ["about:blank", "https://example.org/pay", "https://example.org/pay", "https://bank.example/acct?id=4"]
        with (
            mock.patch.object(tools.Bridge, "bidi", return_value=engine),
            mock.patch.object(tools.Bridge, "_url_of", side_effect=places),
            mock.patch.object(tools.Bridge, "_forms_where", return_value=["realm-1"]),
            mock.patch.object(tools.Bridge, "_in_realms", return_value=([1], "")),
            mock.patch.object(tools.Bridge, "_settle", return_value=True),
            mock.patch.object(tools.Bridge, "_open_dialog", return_value=None),
            mock.patch.object(tools.Bridge, "_title", side_effect=AssertionError("described")),
        ):
            result = scoped.call("navigate", {"tab": "t1", "url": "https://example.org/pay"})
        self.assertIn("is not described. The tab is t1.", result["content"][0]["text"])
        self.assertNotIn("bank.example", json.dumps(result))
        # Reading says that the page holds a form; it asks nothing.
        approver = Approve("once")
        bridge, steps = self.acting("assisted", approver, held=[2])
        page = {"text": "ok", "url": "https://example.org/cart", "title": "t"}
        with mock.patch.object(tools.Bridge, "_eval", return_value=page):
            read = bridge.call("page_read", {"tab": "t1"})["structuredContent"]
        self.assertEqual((read["forms_held"], approver.asked, "send" in steps), (2, [], False))
        bridge, steps = self.acting("assisted", approver, held=[3])
        with (
            mock.patch.object(tools.Bridge, "_call_fn", return_value=[]),
            mock.patch.object(tools.Bridge, "_title", return_value="t"),
        ):
            listed = bridge.call("page_snapshot", {"tab": "t1"})["structuredContent"]
        self.assertEqual((listed["forms_held"], approver.asked), (3, []))

    def test_choosing_a_file_runs_the_pages_handlers_too(self):
        # onchange="this.form.submit()" on a file field: nothing looked at what the page then sent.
        def uploading(approver, held):
            bridge, steps = self.acting("assisted", approver, held=held)
            registry.grant(bridge.agent_id, "files", "allow")
            folder = self.home / "uploads"
            folder.mkdir(exist_ok=True)
            (folder / "report.txt").write_text("artificial")
            bridge.workspace = mock.Mock(uploads=True, bidi=None)  # no engine of its own: the page is the stand-in
            stack = contextlib.ExitStack()
            self.addCleanup(stack.close)
            stack.enter_context(mock.patch.object(tools, "_uploads", return_value=folder))
            stack.enter_context(mock.patch.object(tools.Bridge, "_owner", return_value=""))
            return bridge.call("upload", {"tab": "t1", "element": "e1", "file": "report.txt"}), steps

        result, steps = uploading(registry.Approver(), [0, 1])
        self.assertTrue(result["isError"], result)
        self.assertIn("The upload was done; the form the page then tried to send was not sent.", result["content"][0]["text"])
        self.assertLess(steps.index("guard"), steps.index("input.setFiles"))
        result, steps = uploading(Approve("once"), [0, 1])
        self.assertEqual((result["isError"], result["structuredContent"]["navigated"], steps.count("send")), (False, True, 1))
        result, steps = uploading(registry.Approver(), [2])  # one held from before: settled first, the file is not chosen
        self.assertIn("An earlier action was done", result["content"][0]["text"])
        self.assertNotIn("input.setFiles", steps)

    # #736: what a click or typing will need besides interact, and a form held from an earlier action, were known only
    # once the element was inspected (after interact was asked) or the form settled (after interact or files was
    # asked). A question could then only end in a refusal, and an answer "until the agent disconnects" stayed.
    CART = "https://example.org/cart"
    LINK_LOCAL: ClassVar[dict] = {"connected": True, "href": "http://localhost:8080/admin"}
    LINK: ClassVar[dict] = {"connected": True, "href": "https://other.example/next"}
    SUBMIT: ClassVar[dict] = {"connected": True, "submits": True}
    FIELD: ClassVar[dict] = {"connected": True, "editable": True, "multiline": False}

    def element_page(self, level, approver, info, *, held=0, grants=()):
        """A Bridge on CART whose element reads as `info`, and whose documents hold `held` forms from an earlier
        action. Returns the bridge, what was done, in order ("look": read in the sandbox before the question,
        "inspect": read in the page after it, "guard": the forms guard set, "drop", "send", engine commands) and the
        page's state."""
        agent, _ = registry.add(f"look-{len(registry.load()['agents'])}", "other", level)
        for name, mode in grants:
            registry.grant(agent["id"], name, mode)
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        bridge.elements["t1"] = {"e1": "shared-1"}
        bridge._forms_ever = level != "autonomous"
        done, page = [], {"held": held}
        engine = mock.Mock()
        engine.mark.return_value = 0
        engine.command.side_effect = lambda method, *_a, **_k: done.append(method) or {}

        def forms_where(_self, _tab, _cancel, **_k):
            done.append("held?")
            return ["realm-1"] if page["held"] else []

        def in_realms(_self, _tab, realms, fn, _cancel, until=None):
            self.assertEqual(realms, ["realm-1"])
            done.append({tools.FORMS_DROP_FN: "drop", tools.FORMS_SEND_FN: "send", tools.FORMS_OPEN_FN: "open"}[fn])
            sent, page["held"] = page["held"], 0
            return [sent], ""

        def call_fn(_self, _tab, fn, _args, _cancel, *, sandbox=False, **_k):
            done.append(("look" if sandbox else "inspect") if fn == tools.INSPECT_FN else "page")
            return info

        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        for name, how in (
            ("_url_of", {"return_value": self.CART}),
            ("bidi", {"return_value": engine}),
            ("_settle", {"return_value": False}),
            ("_open_dialog", {"return_value": None}),
            ("_forms_where", {"new": forms_where}),
            ("_in_realms", {"new": in_realms}),
            ("_call_fn", {"new": call_fn}),
            ("_forms_prepare", {"new": lambda _self, _tab, _cancel: done.append("guard")}),
        ):
            stack.enter_context(mock.patch.object(tools.Bridge, name, **how))
        stack.enter_context(mock.patch.object(policy, "_resolves_locally", return_value=False))
        return bridge, done, page

    def assert_refused_before_asking(self, result, approver, bridge, done, capability, reason, target):
        self.assertTrue(result["isError"], result)
        self.assertIn(f"'{policy.CAPABILITIES[capability]}'", result["content"][0]["text"])
        self.assertEqual(approver.asked, [])
        self.assertEqual(registry.get(bridge.agent_id).get("session_grants", {}), {})
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["decision"], entry["capability"], entry["reason"], entry["target"]),
                         ("deny", capability, reason, target))  # fmt: skip
        self.assertFalse({"inspect", "guard", "page", "send", "input.performActions"} & set(done), done)

    ELEMENT_DECIDES = (
        # The preset reaches it: in Restricted interact asks, and an address on this computer needs local_resources.
        ("click", {}, LINK_LOCAL, "restricted", (), "local_resources", "preset:restricted", "http://localhost:8080"),
        ("click", {}, LINK, "restricted", (("navigate", "block"),), "navigate", "grant", "https://other.example"),
        ("click", {}, SUBMIT, "restricted", (("submit_forms", "block"),), "submit_forms", "grant", "https://example.org"),
        # A submit button with a link: its form's question (Assisted asks) came before the link's refusal.
        ("click", {}, {**SUBMIT, **LINK_LOCAL}, "assisted", (), "local_resources", "preset:assisted",
         "http://localhost:8080"),
        ("type", {"text": "x\n"}, FIELD, "restricted", (("submit_forms", "block"),), "submit_forms", "grant",
         "https://example.org"),
        ("type", {"text": "x\r"}, FIELD, "restricted", (("submit_forms", "block"),), "submit_forms", "grant",
         "https://example.org"),
    )  # fmt: skip

    def test_what_the_element_decides_is_refused_before_interact_is_asked(self):
        for tool, extra, info, level, grants, capability, reason, target in self.ELEMENT_DECIDES:
            with self.subTest(tool=tool, info=info, capability=capability):
                approver = Approve("session")
                bridge, done, _page = self.element_page(level, approver, info, grants=grants)
                result = bridge.call(tool, {"tab": "t1", "element": "e1", **extra})
                self.assert_refused_before_asking(result, approver, bridge, done, capability, reason, target)
                self.assertIn("look", done)  # read where the page does not see it

    def test_what_the_element_needs_is_still_asked_in_the_same_order_when_an_answer_can_allow_it(self):
        # I7: the same calls with that permission on ask are asked what they were before, in the same order, and act.
        for tool, extra, info, level, grants, capability, _reason, target in self.ELEMENT_DECIDES:
            if capability == "local_resources":
                continue  # allowing this computer also sets up the engines' network (_sync_network); same order as navigate
            with self.subTest(tool=tool, info=info, capability=capability):
                approver = Approve("once")
                grants = tuple((name, "ask") for name, _mode in grants)
                bridge, done, _page = self.element_page(level, approver, info, grants=grants)
                result = bridge.call(tool, {"tab": "t1", "element": "e1", **extra})
                self.assertFalse(result["isError"], result)
                self.assertEqual(approver.asked, [("interact", "https://example.org"), (capability, target)])
                self.assertIn("input.performActions", done)

    def test_an_element_that_needs_nothing_blocked_is_asked_about_as_before(self):
        # A plain button, a multi-line field, a newline-free text: nothing more is refused, and the look reads only.
        for tool, extra, info in (
            ("click", {}, {"connected": True}),
            ("type", {"text": "x\ny"}, {**self.FIELD, "multiline": True}),
            ("type", {"text": "xy"}, self.FIELD),
        ):
            with self.subTest(tool=tool, info=info):
                approver = Approve("once")
                bridge, done, _page = self.element_page("restricted", approver, info, grants=(("submit_forms", "block"),))
                result = bridge.call(tool, {"tab": "t1", "element": "e1", **extra})
                self.assertFalse(result["isError"], result)
                self.assertEqual(approver.asked, [("interact", "https://example.org")])
                self.assertLess(done.index("look"), done.index("inspect"))  # and read again after the question
                if tool == "click":
                    self.assertLess(done.index("guard"), done.index("inspect"))  # once its forms are held

    def test_a_form_held_from_an_earlier_action_is_dropped_and_refused_before_asking(self):
        # The second exception #737 documented: settled after the call's own question (interact, files for upload).
        cases = (
            ("click", "restricted", {}),
            ("type", "restricted", {"text": "abc"}),
            ("upload", "assisted", {"file": "report.txt"}),  # Assisted asks before it uses files
        )
        folder = self.home / "uploads"
        folder.mkdir()
        (folder / "report.txt").write_text("artificial")
        for tool, level, extra in cases:
            with self.subTest(tool=tool):
                approver = Approve("session")
                bridge, done, page = self.element_page(level, approver, self.FIELD, held=1,
                                                       grants=(("submit_forms", "block"),))  # fmt: skip
                bridge.workspace = mock.Mock(uploads=True, bidi=None)
                with (
                    mock.patch.object(tools, "_uploads", return_value=folder),
                    mock.patch.object(tools.Bridge, "_owner", return_value=""),
                ):
                    arguments = {"tab": "t1", "element": "e1", **extra}
                    result = bridge.call(tool, arguments)
                    self.assert_refused_before_asking(result, approver, bridge, done, "submit_forms", "grant",
                                                      "https://example.org")  # fmt: skip
                    self.assertIn("An earlier action was done; the form the page then tried to send was not sent.",
                                  result["content"][0]["text"])  # fmt: skip
                    self.assertEqual((done.count("drop"), page["held"], "input.setFiles" in done), (1, 0, False))
                    # Dropped: the next call is not refused for it again, and asks what it asks.
                    bridge.approver = again = Approve("once")
                    self.assertFalse(bridge.call(tool, arguments)["isError"])
                    own = tools.BY_NAME[tool].capability
                    self.assertEqual(again.asked, [(own, "https://example.org")])

    def test_a_form_held_from_an_earlier_action_is_still_asked_about_when_an_answer_can_allow_it(self):
        # I7: with submit_forms on ask, the held form is asked about after interact, and sent; nothing else is done.
        approver = Approve("once")
        bridge, done, page = self.element_page("restricted", approver, self.LINK_LOCAL, held=1)
        result = bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assertFalse(result["isError"], result)
        self.assertTrue(result["structuredContent"]["form_sent"])
        self.assertEqual(approver.asked, [("interact", "https://example.org"), ("submit_forms", "https://example.org")])
        self.assertEqual((done.count("send"), page["held"], "drop" in done, "input.performActions" in done),
                         (1, 0, False, False))  # fmt: skip
        self.assertNotIn("look", done)  # a held form ends the call: its link is not read, nor refused (local_resources)

    def test_enter_refused_before_asking_leaves_a_held_form_to_the_next_call(self):
        # Enter (submit=true) is refused for submit_forms before anything is read of the page (#730); a form held
        # from an earlier action is settled by the next call that looks, before its question.
        approver = Approve("session")
        bridge, done, page = self.element_page("restricted", approver, self.FIELD, held=1,
                                               grants=(("submit_forms", "block"),))  # fmt: skip
        result = bridge.call("type", {"tab": "t1", "element": "e1", "text": "x", "submit": True})
        self.assert_refused_before_asking(result, approver, bridge, done, "submit_forms", "grant", "https://example.org")
        self.assertEqual((done, page["held"]), ([], 1))
        result = bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assert_refused_before_asking(result, approver, bridge, done, "submit_forms", "grant", "https://example.org")
        self.assertEqual((done.count("drop"), page["held"]), (1, 0))

    def test_a_link_agents_never_go_to_is_refused_before_asking(self):
        # The refusals a link decides that are no permission (#463, an address agents never open): before interact is
        # asked too, and after what is blocked before them, in the order the call meets them.
        for href, said, refused in (
            ("data:text/html,x", "'data:' addresses are not supported", None),
            ("about:config", "internal pages are not offered to agents", ("debugging", "internal-pages-off")),
        ):
            with self.subTest(href=href):
                approver = Approve("session")
                bridge, done, _page = self.element_page("restricted", approver, {"connected": True, "href": href})
                result = bridge.call("click", {"tab": "t1", "element": "e1"})
                self.assertTrue(result["isError"], result)
                self.assertIn(said, result["content"][0]["text"])
                self.assertEqual(approver.asked, [])
                self.assertFalse({"inspect", "guard", "input.performActions"} & set(done), done)
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual(entry["target"], policy.origin(href))
                if refused:
                    self.assertEqual((entry["capability"], entry["reason"]), refused)
                # A submit button with that link while submit_forms is blocked: the form's refusal comes first.
                bridge, _done, _page = self.element_page("restricted", approver, {**self.SUBMIT, "href": href},
                                                         grants=(("submit_forms", "block"),))  # fmt: skip
                result = bridge.call("click", {"tab": "t1", "element": "e1"})
                self.assertIn("'Submit forms'", result["content"][0]["text"])
                self.assertEqual(approver.asked, [])

    def test_a_field_that_takes_no_text_is_refused_before_asking(self):
        # Also known from the element before the question: a tool error, after what is blocked before it.
        approver = Approve("session")
        bridge, done, _page = self.element_page("restricted", approver, {"connected": True, "editable": False})
        result = bridge.call("type", {"tab": "t1", "element": "e1", "text": "x"})
        self.assertTrue(result["isError"], result)
        self.assertIn("that element does not take text", result["content"][0]["text"])
        self.assertEqual(approver.asked, [])
        self.assertFalse({"inspect", "guard", "input.performActions"} & set(done), done)
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual(entry["target"], "https://example.org")  # the site it was refused at, as after the question
        # Enter while submit_forms is blocked: that refusal comes first, before anything is read (#730).
        bridge, done, _page = self.element_page("restricted", approver, {"connected": True, "editable": False},
                                                grants=(("submit_forms", "block"),))  # fmt: skip
        result = bridge.call("type", {"tab": "t1", "element": "e1", "text": "x", "submit": True})
        self.assert_refused_before_asking(result, approver, bridge, done, "submit_forms", "grant", "https://example.org")
        self.assertNotIn("look", done)

    def test_a_look_that_fails_adds_nothing(self):
        # The element gone, or the engine not answering: said after the question, as before.
        for failure in ({"return_value": {"connected": False}}, {"side_effect": tools.BidiError("no such node", "gone")}):
            with self.subTest(failure=failure):
                approver = Approve("once")
                bridge, _done, _page = self.element_page("restricted", approver, self.SUBMIT,
                                                         grants=(("submit_forms", "block"),))  # fmt: skip
                with mock.patch.object(tools.Bridge, "_call_fn", **failure):
                    result = bridge.call("click", {"tab": "t1", "element": "e1"})
                self.assertTrue(result["isError"], result)
                self.assertEqual(approver.asked, [("interact", "https://example.org")])

    # OpenCodeReview on #748, round 1.
    def test_a_form_counted_in_a_page_the_tab_moved_to_is_left_held(self):
        # The tab went to another site between the call's first look and the count: that page's form is not judged
        # by the site the call began at, nor dropped; the move is said after the question, as before.
        approver = Approve("once")
        bridge, done, page = self.element_page("restricted", approver, self.FIELD, held=1,
                                               grants=(("submit_forms", "block"),))  # fmt: skip
        where = iter([self.CART])
        with mock.patch.object(tools.Bridge, "_url_of", side_effect=lambda *_a, **_k: next(where, "https://elsewhere.example/")):
            result = bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assertTrue(result["isError"], result)
        self.assertIn("the tab moved to", result["content"][0]["text"])
        self.assertEqual(approver.asked, [("interact", "https://example.org")])
        self.assertEqual((done.count("drop"), page["held"]), (0, 1))

    def test_a_call_its_own_checks_refuse_leaves_a_held_form_to_the_next_call(self):
        # What refused typing or an upload before a held form was settled (_t_type, _t_upload) still does, and the
        # form stays held: a field that takes no text, an element gone, a newline in a single-line field (its own
        # submit_forms), a file that is not there.
        folder = self.home / "uploads"
        folder.mkdir()
        cases = (
            ("type", "restricted", {"text": "x"}, {"connected": True, "editable": False}, [],
             "that element does not take text"),
            ("type", "restricted", {"text": "x"}, {"connected": False}, [("interact", "https://example.org")],
             "the element is gone"),
            ("type", "restricted", {"text": "x\n"}, self.FIELD, [], "'Submit forms'"),
            ("upload", "assisted", {"file": "missing.txt"}, self.FIELD, [("files", "https://example.org")],
             "no file named 'missing.txt'"),
        )  # fmt: skip
        for tool, level, extra, info, asked, said in cases:
            with self.subTest(tool=tool, extra=extra, info=info):
                approver = Approve("once")
                bridge, done, page = self.element_page(level, approver, info, held=1,
                                                       grants=(("submit_forms", "block"),))  # fmt: skip
                bridge.workspace = mock.Mock(uploads=True, bidi=None)
                with (
                    mock.patch.object(tools, "_uploads", return_value=folder),
                    mock.patch.object(tools.Bridge, "_owner", return_value=""),
                ):
                    result = bridge.call(tool, {"tab": "t1", "element": "e1", **extra})
                self.assertTrue(result["isError"], result)
                self.assertIn(said, result["content"][0]["text"])
                self.assertNotIn("An earlier action", result["content"][0]["text"])
                self.assertEqual(approver.asked, asked)
                self.assertEqual((done.count("drop"), page["held"]), (0, 1))

    def test_a_key_replaced_while_the_page_is_read_is_refused_for_it(self):
        # A new key while the sandbox read was open: the old session is refused for that (and closed), and is not
        # told what the page decides (a field that takes no text).
        approver = Approve("session")
        bridge, _done, _page = self.element_page("restricted", approver, {})
        bridge.key_sha256 = registry.get(bridge.agent_id)["token_sha256"]

        def read(*_a, **_k):
            registry.rotate_token(bridge.agent_id)
            return {"connected": True, "editable": False}

        with mock.patch.object(tools.Bridge, "_call_fn", side_effect=read):
            result = bridge.call("type", {"tab": "t1", "element": "e1", "text": "x"})
        self.assertTrue(result["isError"], result)
        self.assertNotIn("does not take text", result["content"][0]["text"])
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["decision"], entry["reason"]), ("deny", "key-replaced"))
        self.assertEqual(approver.asked, [])

    def test_a_cancelled_call_leaves_a_held_form_held(self):
        # Cancelled while the look was open: the refusal is not answered, and nothing is sent to the page for it.
        approver = Approve("session")
        bridge, done, page = self.element_page("restricted", approver, self.FIELD, held=1,
                                               grants=(("submit_forms", "block"),))  # fmt: skip
        cancel = threading.Event()

        def forms_where(_self, _tab, _cancel, **_k):
            cancel.set()  # the client cancels while the page is read
            return ["realm-1"]

        with mock.patch.object(tools.Bridge, "_forms_where", forms_where):
            bridge.call("click", {"tab": "t1", "element": "e1"}, cancel)
        self.assertEqual((done.count("drop"), page["held"]), (0, 1))
        self.assertEqual(approver.asked, [])

    def test_a_links_host_is_not_looked_up_when_a_block_before_it_refuses_the_call(self):
        # navigate blocked, or submit_forms for a submit button with that link: refused before its host is looked up.
        for grants, info, looked in (
            ((("navigate", "block"),), self.LINK, False),
            ((("submit_forms", "block"),), {**self.SUBMIT, **self.LINK}, False),
            ((), self.LINK, True),  # nothing blocked: looked up, as before, to know what it needs on this computer
        ):
            with self.subTest(grants=grants, info=info):
                hosts: list[str] = []
                approver = Approve("deny")
                bridge, _done, _page = self.element_page("restricted", approver, info, grants=grants)
                looks_up = mock.patch.object(policy, "_resolves_locally", side_effect=lambda h, seen=hosts: seen.append(h))
                with looks_up:
                    bridge.call("click", {"tab": "t1", "element": "e1"})
                self.assertEqual("other.example" in hosts, looked, hosts)

    def test_the_look_has_one_time_budget_for_all_the_documents(self):
        # Documents that do not answer: the look stops at its budget, not after each of them, and the call goes on
        # as before (asked, then settled after the question).
        approver = Approve("once")
        at_question: list[int] = []
        approver.meanwhile = lambda: at_question.append(len(given))
        given: list[float] = []

        def in_sandbox(_self, _tab, _target, _fn, _cancel, timeout=5.0, until=None):
            given.append(timeout)
            time.sleep(min(timeout, 0.01))
            raise tools.BidiError("timeout", "slow")

        real_where = tools.Bridge._forms_where
        bridge, _done, _page = self.element_page("restricted", approver, {"connected": True})
        with (
            mock.patch.object(tools.Bridge, "_forms_where", real_where),
            mock.patch.object(tools.Bridge, "_frames", return_value=[f"f{i}" for i in range(tools.FORMS_FRAMES)]),
            mock.patch.object(tools.Bridge, "_in_sandbox", in_sandbox),
            mock.patch.object(tools, "LOOK_SECONDS", 0.05),
        ):
            result = bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assertFalse(result["isError"], result)
        self.assertEqual(approver.asked, [("interact", "https://example.org")])
        looked = given[: at_question[0]]
        self.assertLess(len(looked), tools.FORMS_FRAMES)
        self.assertTrue(all(timeout <= 0.05 for timeout in looked), looked)

    # OpenCodeReview on #748, round 2.
    def test_a_page_is_not_read_before_what_its_address_needs_is_answered(self):
        # A page on this computer, local_resources on ask (an earlier answer "once" was for that call): nothing is
        # read of it, nor its held form dropped, before that question; the call asks as before #736.
        class Answers(Approve):
            def ask(self, agent, capability, target, place="", cancel=None):
                super().ask(agent, capability, target, place, cancel)
                return "deny" if capability == "local_resources" else "once"

        approver = Answers("once")
        bridge, done, page = self.element_page("restricted", approver, self.FIELD, held=1,
                                               grants=(("local_resources", "ask"), ("submit_forms", "block")))  # fmt: skip
        approver.meanwhile = lambda: done.append("asked")
        with mock.patch.object(tools.Bridge, "_url_of", return_value="http://localhost:8080/cart"):
            result = bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [("interact", "http://localhost:8080"), ("local_resources", "http://localhost:8080")])
        self.assertEqual((done[:2], page["held"]), (["asked", "asked"], 1))
        self.assertNotIn("look", done)

    def test_the_file_uploaded_is_the_one_the_name_points_to_after_the_question(self):
        # The name is resolved again once files is answered: an alias moved meanwhile uploads where it points then,
        # and one removed uploads nothing.
        folder = self.home / "uploads"
        folder.mkdir()
        (folder / "a.txt").write_text("artificial a")
        (folder / "b.txt").write_text("artificial b")
        for moved, sent in (("b.txt", "b.txt"), (None, None)):
            with self.subTest(moved=moved):
                alias = folder / "report.txt"
                alias.unlink(missing_ok=True)
                alias.symlink_to(folder / "a.txt")

                def meanwhile(alias=alias, moved=moved):
                    alias.unlink()
                    if moved:
                        alias.symlink_to(folder / moved)

                approver = Approve("once", meanwhile)
                bridge, _done, _page = self.element_page("assisted", approver, self.FIELD)
                bridge.workspace = mock.Mock(uploads=True, bidi=None)
                files = []

                def command(method, params=None, files=files, **_k):
                    if method == "input.setFiles":
                        files.extend(params["files"])
                    return {}

                bridge.bidi().command.side_effect = command
                with (
                    mock.patch.object(tools, "_uploads", return_value=folder),
                    mock.patch.object(tools.Bridge, "_owner", return_value=""),
                ):
                    result = bridge.call("upload", {"tab": "t1", "element": "e1", "file": "report.txt"})
                self.assertEqual(approver.asked, [("files", "https://example.org")])
                if sent:
                    self.assertFalse(result["isError"], result)
                    self.assertEqual(files, [str(folder.resolve() / sent)])
                else:
                    self.assertIn("no file named 'report.txt'", result["content"][0]["text"])
                    self.assertEqual(files, [])

    def test_the_looks_reads_of_the_tab_keep_to_its_budget(self):
        # The tab's documents and its address, read in the look, wait no longer than what is left of its budget.
        approver = Approve("once")
        asked: list[bool] = []
        approver.meanwhile = lambda: asked.append(True)
        frames, addresses = [], []
        real_where = tools.Bridge._forms_where
        bridge, _done, _page = self.element_page("restricted", approver, self.FIELD, held=1)

        def frames_of(_self, _tab, _cancel, timeout=30.0):
            if not asked:
                frames.append(timeout)
            return ["t1"]

        def url_of(_self, _tab, _cancel, *, enter=True, timeout=30.0):
            if not asked:
                addresses.append(timeout)
            return self.CART

        with (
            mock.patch.object(tools.Bridge, "_forms_where", real_where),
            mock.patch.object(tools.Bridge, "_frames", frames_of),
            mock.patch.object(tools.Bridge, "_url_of", url_of),
            mock.patch.object(tools.Bridge, "_in_sandbox", return_value=(1, "realm-1")),
        ):
            bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assertTrue(frames and all(timeout <= tools.LOOK_SECONDS for timeout in frames), frames)
        self.assertTrue(any(timeout <= tools.LOOK_SECONDS for timeout in addresses), addresses)

    def test_what_a_link_needs_known_only_after_the_budget_adds_nothing(self):
        # A link whose host takes longer than the look to look up: what it needs is checked after the question, as
        # before, not refused before it from an answer that came too late.
        approver = Approve("once")
        bridge, _done, _page = self.element_page("restricted", approver, self.LINK)

        def slow(host):
            if host != "other.example":
                return False
            time.sleep(0.1)
            return True  # on this computer: local_resources, which Restricted blocks

        with mock.patch.object(policy, "_resolves_locally", side_effect=slow), mock.patch.object(tools, "LOOK_SECONDS", 0.05):
            result = bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [("interact", "https://example.org")])

    def test_an_agent_removed_while_its_link_is_read_is_refused_for_it(self):
        # Removed while the sandbox read was open: refused as revoked (and closed), not an internal error.
        approver = Approve("session")
        bridge, _done, _page = self.element_page("restricted", approver, {})

        def read(*_a, **_k):
            registry.remove(bridge.agent_id)
            return self.LINK

        with mock.patch.object(tools.Bridge, "_call_fn", side_effect=read):
            result = bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assertTrue(result["isError"], result)
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["decision"], entry["reason"]), ("deny", "revoked"))
        self.assertEqual(approver.asked, [])

    # OpenCodeReview on #748, round 3.
    def test_enter_refused_while_the_page_is_read_leaves_a_held_form_held(self):
        # submit_forms blocked while the look counted a held form: Enter (submit=true) asks it first, at the same
        # address, so the refusal is Enter's own. The held form is not dropped for it: on main, Enter refused after
        # the question leaves it held for the next call too.
        approver = Approve("once")
        bridge, done, page = self.element_page("restricted", approver, self.FIELD, held=1)

        def forms_where(_self, _tab, _cancel, **kwargs):
            if "deadline" in kwargs:  # the look's count, before the question
                registry.grant(bridge.agent_id, "submit_forms", "block")
                done.append("look")
            return ["realm-1"] if page["held"] else []

        with mock.patch.object(tools.Bridge, "_forms_where", forms_where):
            result = bridge.call("type", {"tab": "t1", "element": "e1", "text": "x", "submit": True})
        self.assertIn("look", done)
        self.assert_refused_before_asking(result, approver, bridge, done, "submit_forms", "grant", "https://example.org")
        self.assertNotIn("An earlier action", result["content"][0]["text"])
        self.assertEqual((done.count("drop"), page["held"]), (0, 1))

    def test_a_file_name_that_cannot_be_resolved_before_the_question_adds_nothing(self):
        # A loop of links in the uploads folder makes Path.resolve raise RuntimeError before Python 3.13: before the
        # question that is not known to be a file, so the call asks files as on main, and a refusal is said as such.
        folder = self.home / "uploads"
        folder.mkdir()
        approver = Approve("deny")
        bridge, done, page = self.element_page("assisted", approver, self.FIELD, held=1)
        bridge.workspace = mock.Mock(uploads=True, bidi=None)
        real = Path.resolve

        def resolve(path, *args, **kwargs):
            if path.name == "loop.txt":
                raise RuntimeError(f"Symlink loop from {path}")
            return real(path, *args, **kwargs)

        with (
            mock.patch.object(tools, "_uploads", return_value=folder),
            mock.patch.object(tools.Bridge, "_owner", return_value=""),
            mock.patch.object(Path, "resolve", resolve),
        ):
            result = bridge.call("upload", {"tab": "t1", "element": "e1", "file": "loop.txt"})
        self.assertTrue(result["isError"], result)
        self.assertIn(f"'{policy.CAPABILITIES['files']}'", result["content"][0]["text"])
        self.assertEqual(approver.asked, [("files", "https://example.org")])
        self.assertEqual((done.count("drop"), page["held"], "input.setFiles" in done), (0, 1, False))

    # Issue #764: what can change while the page is read or a host is looked up is checked again before the result is
    # acted on: where the tab is, the cancel, the session.
    ELSEWHERE = "https://elsewhere.example/"

    def moving_tab(self):
        """Where the tab is (`where["url"]`, changed by the test) and the patch of _url_of that reads it."""
        where = {"url": self.CART}
        return where, mock.patch.object(tools.Bridge, "_url_of", side_effect=lambda *_a, **_k: where["url"])

    @staticmethod
    def looks_up(hosts: list[str], when=lambda: True):
        """A patch of this computer's lookup that lists the hosts looked up while `when()`."""
        return mock.patch.object(policy, "_resolves_locally", side_effect=lambda h: when() and hosts.append(h) and False)

    def test_a_page_the_tab_moved_to_while_its_forms_were_counted_is_not_read(self):
        # Case 1: the tab went to another site while the look counted its forms (none there): the element is not read
        # in that page. The move is said after the question, as before.
        approver = Approve("once")
        bridge, done, _page = self.element_page("restricted", approver, self.LINK)
        where, moving = self.moving_tab()

        def forms_where(_self, _tab, _cancel, **_k):
            where["url"] = self.ELSEWHERE
            done.append("moved")
            return []

        with moving, mock.patch.object(tools.Bridge, "_forms_where", forms_where):
            result = bridge.call("click", {"tab": "t1", "element": "e1"})
        self.assertTrue(result["isError"], result)
        self.assertIn("the tab moved to", result["content"][0]["text"])
        self.assertNotIn("look", done)
        self.assertEqual(approver.asked, [("interact", "https://example.org")])

    def test_a_link_read_in_a_page_the_tab_moved_to_is_not_looked_up_or_asked_about(self):
        # Case 1: the tab went to another site while the element was read, in the look before the question or in the
        # page after it: that page's link is not looked up on this computer, nor asked about.
        for in_sandbox in (True, False):
            with self.subTest(in_sandbox=in_sandbox):
                approver = Approve("once")
                bridge, done, _page = self.element_page("restricted", approver, self.LINK)
                where, moving = self.moving_tab()

                def call_fn(_self, _tab, fn, _args, _cancel, *, sandbox=False, in_sandbox=in_sandbox, where=where, done=done,
                            **_k):  # fmt: skip
                    done.append(("look" if sandbox else "inspect") if fn == tools.INSPECT_FN else "page")
                    if fn == tools.INSPECT_FN and sandbox == in_sandbox:
                        where["url"] = self.ELSEWHERE
                    return self.LINK

                hosts: list[str] = []
                with (
                    moving,
                    mock.patch.object(tools.Bridge, "_call_fn", call_fn),
                    self.looks_up(hosts, lambda where=where: where["url"] != self.CART),
                ):
                    result = bridge.call("click", {"tab": "t1", "element": "e1"})
                self.assertTrue(result["isError"], result)
                self.assertIn("the tab moved to", result["content"][0]["text"])
                self.assertNotIn("other.example", hosts)  # (the new site's is, to know whether the error may name it)
                self.assertEqual(approver.asked, [("interact", "https://example.org")])
                self.assertNotIn("input.performActions", done)

    def test_a_page_the_tab_moved_to_while_an_earlier_form_was_looked_for_is_not_read_or_watched(self):
        # Case 1: after the question, the tab went to another site while the call looked for a form held from an
        # earlier action (none there): the forms guard is not set in that page, and nothing more is read there.
        for tool, extra, info in (("click", {}, {"connected": True}), ("type", {"text": "x"}, self.FIELD)):
            with self.subTest(tool=tool):
                approver = Approve("once")
                bridge, done, _page = self.element_page("restricted", approver, info)
                where, moving = self.moving_tab()

                def forms_where(_self, _tab, _cancel, where=where, done=done, **kwargs):
                    if "deadline" not in kwargs:  # not the look's count: the one after the question
                        where["url"] = self.ELSEWHERE
                        done.append("moved")
                    return []

                with moving, mock.patch.object(tools.Bridge, "_forms_where", forms_where):
                    result = bridge.call(tool, {"tab": "t1", "element": "e1", **extra})
                self.assertTrue(result["isError"], result)
                self.assertIn("the tab moved to", result["content"][0]["text"])
                after = set(done[done.index("moved") :])
                self.assertFalse({"guard", "inspect", "page", "input.performActions"} & after, done)

    def test_a_call_cancelled_during_a_host_lookup_asks_nothing(self):
        # Case 2: cancelled while this computer looked up the tab's own host, or the host of the link the look read:
        # the lookup does not watch the cancel, and the call asks nothing after it.
        for host in ("example.org", "other.example"):
            with self.subTest(host=host):
                approver = Approve("once")
                bridge, done, _page = self.element_page("restricted", approver, self.LINK)
                cancel = threading.Event()

                def resolves(name, host=host, cancel=cancel):
                    if name == host:
                        cancel.set()
                    return False

                with mock.patch.object(policy, "_resolves_locally", side_effect=resolves):
                    result = bridge.call("click", {"tab": "t1", "element": "e1"}, cancel)
                self.assertTrue(result["isError"], result)
                self.assertEqual(approver.asked, [])
                self.assertNotIn("input.performActions", done)

    def called_off_in_registry_read(self, cancel: threading.Event, name: str, armed: list[bool]):
        """A patch of the call's read of its agent record (_held) that, while `armed`, cancels the call (`name`
        "cancel") or turns the emergency stop on ("stop") during that read, after the cancel and the stop were looked
        at, and disarms."""
        real_agent = tools.Bridge._agent

        def agent(bridge, cancel=cancel, name=name, armed=armed):
            record = real_agent(bridge)
            if armed:
                armed.clear()
                cancel.set() if name == "cancel" else registry.set_stopped(True)
            return record

        return mock.patch.object(tools.Bridge, "_agent", agent)

    def test_a_call_called_off_while_its_session_is_read_before_a_lookup_looks_nothing_up(self):
        # OpenCodeReview on #812 (round 2): a cancel, or the emergency stop, that comes while the call reads its agent
        # record before a host lookup (_go_on), after it looked at the cancel and the stop: nothing is looked up on this
        # computer, nothing is asked, nothing is done.
        self.addCleanup(registry.set_stopped, False)
        real_go_on = tools.Bridge._go_on
        for name in ("cancel", "stop"):
            with self.subTest(name):
                registry.set_stopped(False)
                approver = Approve("once")
                bridge, done, _page = self.element_page("restricted", approver, self.LINK)
                cancel = threading.Event()
                armed: list[bool] = []

                def go_on(bridge, *args, armed=armed, cancel=cancel, **kwargs):
                    if kwargs.get("at") and not cancel.is_set() and not registry.stopped():
                        armed.append(True)  # the check before (or after) a host lookup
                    return real_go_on(bridge, *args, **kwargs)

                hosts: list[str] = []
                with (
                    mock.patch.object(tools.Bridge, "_go_on", go_on),
                    self.called_off_in_registry_read(cancel, name, armed),
                    self.looks_up(hosts),
                ):
                    result = bridge.call("click", {"tab": "t1", "element": "e1"}, cancel)
                self.assertTrue(result["isError"], result)
                self.assertEqual(hosts, [])
                self.assertEqual(approver.asked, [])
                self.assertNotIn("input.performActions", done)

    def test_a_key_replaced_while_the_page_is_read_gets_no_lookup(self):
        # Case 3: a new key while the element was read (in the look before the question, or in the page after it), or
        # while the tab's address was read again after the question: nothing is looked up for the old session on
        # this computer, and it is refused for the new key.
        for when, asked in (("look", []), ("inspect", [("interact", "https://example.org")]),
                            ("recheck", [("interact", "https://example.org")])):  # fmt: skip
            with self.subTest(when=when):
                approver = Approve("once")
                bridge, done, _page = self.element_page("restricted", approver, self.LINK)
                bridge.key_sha256 = registry.get(bridge.agent_id)["token_sha256"]
                rotated: list[bool] = []

                def rotate(rotated=rotated, bridge=bridge):
                    if not rotated:
                        registry.rotate_token(bridge.agent_id)
                        rotated.append(True)

                def call_fn(_self, _tab, fn, _args, _cancel, *, sandbox=False, when=when, rotate=rotate, done=done, **_k):
                    done.append(("look" if sandbox else "inspect") if fn == tools.INSPECT_FN else "page")
                    if fn == tools.INSPECT_FN and when == ("look" if sandbox else "inspect"):
                        rotate()
                    return self.LINK

                def url_of(*_a, when=when, approver=approver, rotate=rotate, **_k):
                    if when == "recheck" and approver.asked:  # the first read after the question: still_at's
                        rotate()
                    return self.CART

                hosts: list[str] = []
                with (
                    mock.patch.object(tools.Bridge, "_call_fn", call_fn),
                    mock.patch.object(tools.Bridge, "_url_of", side_effect=url_of),
                    self.looks_up(hosts, lambda rotated=rotated: bool(rotated)),
                ):
                    result = bridge.call("click", {"tab": "t1", "element": "e1"})
                self.assertTrue(result["isError"], result)
                self.assertEqual(hosts, [])
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["decision"], entry["reason"]), ("deny", "key-replaced"))
                self.assertEqual(approver.asked, asked)
                self.assertNotIn("input.performActions", done)

    def test_a_session_held_while_the_tab_is_read_again_before_acting_does_nothing(self):
        # OpenCodeReview on #812: a pause or a new key while the tab's address was read again after the count of forms
        # held from an earlier action (none there), the last read before click, type and upload act: nothing is set up
        # or done in the page, and the call is refused for it.
        for tool, extra, level in (("click", {}, "restricted"), ("type", {"text": "x"}, "restricted"),
                                   ("upload", {"file": "report.txt"}, "assisted")):  # fmt: skip
            for held, change in (("paused", lambda a: registry.pause(a, True)), ("key-replaced", registry.rotate_token)):
                with self.subTest(tool=tool, held=held):
                    approver = Approve("once")
                    bridge, done, _page = self.element_page(level, approver, self.FIELD)
                    bridge.key_sha256 = registry.get(bridge.agent_id)["token_sha256"]
                    counted: list[bool] = []

                    def forms_where(_self, _tab, _cancel, counted=counted, done=done, **kwargs):
                        if "deadline" not in kwargs:  # not the look's count: the one after the question
                            counted.append(True)
                            done.append("counted")
                        return []

                    def url_of(*_a, counted=counted, change=change, bridge=bridge, **_k):
                        if counted == [True]:  # the read after that count
                            counted.append(True)
                            change(bridge.agent_id)
                        return self.CART

                    folder = self.home / "uploads"
                    folder.mkdir(exist_ok=True)
                    (folder / "report.txt").write_text("artificial")
                    bridge.workspace = mock.Mock(uploads=True, bidi=None)
                    with (
                        mock.patch.object(tools.Bridge, "_forms_where", forms_where),
                        mock.patch.object(tools.Bridge, "_url_of", side_effect=url_of),
                        mock.patch.object(tools, "_uploads", return_value=folder),
                        mock.patch.object(tools.Bridge, "_owner", return_value=""),
                    ):
                        result = bridge.call(tool, {"tab": "t1", "element": "e1", **extra})
                    self.assertTrue(result["isError"], result)
                    self.assertEqual(len(counted), 2, done)  # the read after the count came, and changed the session
                    entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                    self.assertEqual((entry["decision"], entry["reason"]), ("deny", held))
                    after = set(done[done.index("counted") :])
                    self.assertFalse({"guard", "inspect", "page", "input.performActions", "input.setFiles"} & after, done)

    def test_a_call_called_off_while_its_session_is_read_again_before_acting_does_nothing(self):
        # OpenCodeReview on #812 (round 2): a cancel, or the emergency stop, that comes while the call reads its agent
        # record after the tab's address was read again before acting (still_at's _go_on), after it looked at the cancel
        # and the stop: click, type and upload do nothing in the page.
        self.addCleanup(registry.set_stopped, False)
        for tool, extra, level in (("click", {}, "restricted"), ("type", {"text": "x"}, "restricted"),
                                   ("upload", {"file": "report.txt"}, "assisted")):  # fmt: skip
            for name in ("cancel", "stop"):
                with self.subTest(tool=tool, name=name):
                    registry.set_stopped(False)
                    approver = Approve("once")
                    bridge, done, _page = self.element_page(level, approver, self.FIELD)
                    cancel = threading.Event()
                    counted: list[bool] = []
                    armed: list[bool] = []

                    def forms_where(_self, _tab, _cancel, counted=counted, done=done, **kwargs):
                        if "deadline" not in kwargs:  # not the look's count: the one after the question
                            counted.append(True)
                            done.append("counted")
                        return []

                    def url_of(*_a, counted=counted, armed=armed, **_k):
                        if counted == [True]:  # the read after that count: still_at's, the last before acting
                            counted.append(True)
                            armed.append(True)
                        return self.CART

                    folder = self.home / "uploads"
                    folder.mkdir(exist_ok=True)
                    (folder / "report.txt").write_text("artificial")
                    bridge.workspace = mock.Mock(uploads=True, bidi=None)
                    with (
                        mock.patch.object(tools.Bridge, "_forms_where", forms_where),
                        mock.patch.object(tools.Bridge, "_url_of", side_effect=url_of),
                        mock.patch.object(tools, "_uploads", return_value=folder),
                        mock.patch.object(tools.Bridge, "_owner", return_value=""),
                        self.called_off_in_registry_read(cancel, name, armed),
                    ):
                        result = bridge.call(tool, {"tab": "t1", "element": "e1", **extra}, cancel)
                    self.assertTrue(result["isError"], result)
                    self.assertEqual((len(counted), armed), (2, []), done)  # that read came, and the record was read
                    after = set(done[done.index("counted") :])
                    self.assertFalse({"guard", "inspect", "page", "input.performActions", "input.setFiles"} & after, done)

    def test_a_form_held_from_an_earlier_action_in_a_page_the_tab_moved_to_is_not_settled(self):
        # OpenCodeReview on #812: after the question, the tab went to another site while the call counted the forms
        # held from an earlier action, and that page holds one. Nothing of this call took the tab there: that site's
        # form is not asked about, sent or dropped; it stays held, and the move is said.
        for grants in ((("submit_forms", "allow"),), ()):
            with self.subTest(grants=grants):
                approver = Approve("once")
                bridge, done, page = self.element_page("restricted", approver, self.FIELD, grants=grants)
                where, moving = self.moving_tab()

                def forms_where(_self, _tab, _cancel, where=where, done=done, page=page, **kwargs):
                    if "deadline" not in kwargs:  # not the look's count: the one after the question
                        where["url"] = self.ELSEWHERE
                        page["held"] = 1  # the page it moved to tried to send a form
                        done.append("moved")
                        return ["realm-1"]
                    return []

                with moving, mock.patch.object(tools.Bridge, "_forms_where", forms_where):
                    result = bridge.call("click", {"tab": "t1", "element": "e1"})
                self.assertTrue(result["isError"], result)
                self.assertIn("the tab moved to", result["content"][0]["text"])
                self.assertIn("while the page was read", result["content"][0]["text"])
                self.assertEqual(approver.asked, [("interact", "https://example.org")])
                self.assertEqual(page["held"], 1)
                after = set(done[done.index("moved") :])
                self.assertFalse({"send", "open", "drop", "guard", "inspect", "input.performActions"} & after, done)

    def test_the_last_read_before_acting_is_the_tabs_address(self):
        # OpenCodeReview on #812 (round 3): still_at read the agent record (_go_on) after it read the tab's address, so a
        # move during that read reached the action unseen. The tab moves at the last read of the agent record before
        # the action (found in a first run): the action is not done in the page it moved to.
        page_text = {"title": "t", "url": self.CART, "text": "x"}
        for tool, extra, info in (("click", {}, {"connected": True}), ("type", {"text": "x"}, self.FIELD),
                                  ("page_read", {}, {"connected": True})):  # fmt: skip

            def run(move_at, tool=tool, extra=extra, info=info):
                bridge, _done, _page = self.element_page("restricted", Approve("once"), info)
                where, events = {"url": self.CART}, []
                real_agent = tools.Bridge._agent

                def agent(bridge_, where=where, events=events, move_at=move_at):
                    if len(events) == move_at:
                        where["url"] = self.ELSEWHERE
                    events.append("agent")
                    return real_agent(bridge_)

                def url_of(*_a, where=where, events=events, **_k):
                    events.append("url")
                    return where["url"]

                def act(where=where, events=events):
                    events.append(("act", where["url"]))

                engine = bridge.bidi("t1")
                engine.command.side_effect = lambda method, *_a, act=act, **_k: (
                    method == "input.performActions" and act()) or {}  # fmt: skip
                with (
                    mock.patch.object(tools.Bridge, "_url_of", side_effect=url_of),
                    mock.patch.object(tools.Bridge, "_agent", agent),
                    mock.patch.object(tools.Bridge, "_eval", side_effect=lambda *_a, act=act, **_k: act() or page_text),
                ):
                    result = bridge.call(tool, {"tab": "t1", "element": "e1", **extra} if tool != "page_read" else
                                         {"tab": "t1"})  # fmt: skip
                return result, events

            with self.subTest(tool=tool):
                result, events = run(None)
                self.assertFalse(result["isError"], result)
                acted = next(i for i, event in enumerate(events) if isinstance(event, tuple))
                last = max(i for i in range(acted) if events[i] == "agent")
                result, events = run(last)
                self.assertNotIn(("act", self.ELSEWHERE), events, events)
                self.assertTrue(result["isError"], result)
                self.assertIn("the tab moved to", result["content"][0]["text"])

    def test_a_call_refused_at_a_host_lookup_names_the_address_looked_up(self):
        # OpenCodeReview on #812: a call paused or cancelled while a host was looked up is refused there, before the
        # question that would have named the address: the activity record still names it, as on main.
        for stop in ("pause", "cancel"):
            for tool, args, host, origin in (
                ("tab_new", {"url": "https://other.example/x"}, "other.example", "https://other.example"),
                ("click", {"tab": "t1", "element": "e1"}, "example.org", "https://example.org"),
            ):
                with self.subTest(stop=stop, tool=tool):
                    approver = Approve("once")
                    bridge, _done, _page = self.element_page("restricted", approver, {"connected": True})
                    cancel = threading.Event()

                    def resolves(name, host=host, stop=stop, cancel=cancel, bridge=bridge):
                        if name == host:
                            registry.pause(bridge.agent_id, True) if stop == "pause" else cancel.set()
                        return False

                    with mock.patch.object(policy, "_resolves_locally", side_effect=resolves):
                        result = bridge.call(tool, args, cancel)
                    self.assertTrue(result["isError"], result)
                    self.assertEqual(approver.asked, [])
                    entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                    outcome = ("denied", "paused") if stop == "pause" else ("error:cancelled", None)
                    self.assertEqual((entry["outcome"], entry.get("reason"), entry.get("target")), (*outcome, origin))

    def test_where_a_redirect_ends_is_one_of_the_agents_sites_or_is_not_described(self):
        agent, _ = registry.add("redirected", "other", "autonomous", domains=["example.org"])
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        engine = mock.Mock()
        engine.command.return_value = {}
        with (
            mock.patch.object(tools.Bridge, "bidi", return_value=engine),
            mock.patch.object(tools.Bridge, "_url_of", side_effect=["about:blank", "https://bank.example/acct?id=4"]),
            mock.patch.object(tools.Bridge, "_title", side_effect=AssertionError("described")),
        ):
            result = bridge.call("navigate", {"tab": "t1", "url": "https://example.org/go"})
        self.assertIn("outside the sites this agent may use", result["content"][0]["text"])
        self.assertNotIn("bank.example", json.dumps(result))

    def test_routes_go_by_the_address_a_wrapper_shows(self):
        agent, _ = registry.add("routed", "other", "autonomous")
        registry.set_profiles(agent["id"], [{"label": "Trabalho", "path": "/home/u/.nulavio/p1"}])
        registry.set_routes(agent["id"], [{"site": "example.org", "profile": "Trabalho"}])
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        cases = {
            "https://docs.example.org/a": "Trabalho",
            "view-source:https://docs.example.org/a": "Trabalho",
            "about:reader?url=https%3A%2F%2Fexample.org%2F": "Trabalho",
            "view-source:https://other.example/": "",
        }
        for url, place in cases.items():
            bridge._args = {"url": url}
            self.assertEqual(bridge._place(), place, url)

    def test_a_page_that_cannot_be_watched_is_not_acted_on(self):
        agent, _ = registry.add("watch", "other", "assisted")
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
        tree = {
            "contexts": [{"context": "t1", "children": [{"context": "f1", "children": [{"context": "f2"}]}, {"context": "f3"}]}]
        }
        engine = mock.Mock()
        engine.command.return_value = tree
        gone = {"f3"}

        def in_sandbox(_self, tab, target, fn, cancel, timeout=5.0):
            frame = target["context"]
            if frame in gone:
                raise tools.BidiError("no such frame")
            return (2 if frame == "f1" else 0), f"realm-{frame}"

        with (
            mock.patch.object(tools.Bridge, "bidi", return_value=engine),
            mock.patch.object(tools.Bridge, "_in_sandbox", in_sandbox),
        ):
            self.assertEqual(bridge._frames("t1", None), ["t1", "f1", "f3", "f2"])
            # f3 answers with an error and is still in the tree: not a frame that went away.
            with self.assertRaises(tools.ToolError):
                bridge._in_frames("t1", tools.FORMS_GUARD_FN, None, must=True)
            self.assertEqual(bridge._in_frames("t1", tools.FORMS_HELD_FN, None, must=False), [0, 2, 0])
            bridge._forms_ever = True
            self.assertEqual(bridge._forms_where("t1", None), ["realm-f1"])  # the documents that hold one, by their sandbox
            engine.command.return_value = {"contexts": [{"context": "t1", "children": [{"context": "f1"}]}]}
            gone.add("t1")
            with self.assertRaises(tools.ToolError):  # the document itself
                bridge._in_frames("t1", tools.FORMS_GUARD_FN, None, must=True)
            many = {"contexts": [{"context": "t1", "children": [{"context": f"f{i}"} for i in range(200)]}]}
            engine.command.return_value = many
            self.assertEqual(len(bridge._frames("t1", None)), tools.FORMS_FRAMES)

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


def _s(value: str) -> dict:
    return {"type": "string", "value": value}


def _obj(**fields) -> dict:
    return {"type": "object", "value": [[key, value] for key, value in fields.items()]}


def _arr(*items) -> dict:
    return {"type": "array", "value": list(items)}


def _node(shared: str) -> dict:
    return {"type": "node", "sharedId": shared, "value": {"nodeType": 1, "localName": "a"}}


NUMBER = {"type": "number", "value": 7}
# A BigInt arrives as its digits; past Python's limit for converting digits to an int (4300), int() raises.
BIGINT = {"type": "bigint", "value": "9" * 5000}


class PageResultsTest(Home):
    """#674: page_read and page_snapshot run their helper in the page's own realm, so a page that redefines
    document.title, document.body, querySelectorAll or getComputedStyle chooses what the helper returns. A result
    of another shape is a tool error, never an exception that ends the agent's call or the assistant's Task."""

    def setUp(self):
        super().setUp()
        # BIGINT is past Python's default limit (4300 digits), which -X int_max_str_digits or the environment can
        # change: pin it for these tests, so that the BigInt cases test the limit rather than the interpreter's start.
        self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
        sys.set_int_max_str_digits(4300)

    def reading(self, result: dict) -> tools.Bridge:
        """A Bridge whose engine answers every script call with the BiDi RemoteValue `result`."""
        agent, _ = registry.add(f"reader-{len(registry.load()['agents'])}", "other", "full_control", accept_full_control=True)
        bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())

        def command(method, params=None, **_k):
            if method in ("script.evaluate", "script.callFunction"):
                return {"type": "success", "realm": "realm-1", "result": result}
            return {}

        engine = mock.Mock()
        engine.mark.return_value = 0
        engine.command.side_effect = command
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(tools.Bridge, "bidi", return_value=engine))
        stack.enter_context(mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"))
        stack.enter_context(mock.patch.object(tools.Bridge, "_open_dialog", return_value=None))
        stack.enter_context(mock.patch.object(tools.Bridge, "_title", return_value="t"))
        return bridge

    def assert_tool_error(self, result: dict) -> None:
        self.assertTrue(result["isError"], result)
        self.assertIn("unexpected", result["content"][0]["text"])
        self.assertNotIn("SECRET", json.dumps(result))  # nothing of the page's own values is repeated
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual(entry["outcome"], "error:tool")

    def test_a_read_of_another_shape_is_a_tool_error(self):
        good = {"title": _s("Example"), "url": _s("https://example.org/"), "text": _s("Hello")}
        for name, result in (
            ("text is a number", _obj(**{**good, "text": NUMBER})),  # the issue's case: text[:limit] on a number
            ("text is an object", _obj(**{**good, "text": _obj(a=_s("SECRET"))})),
            ("title is an object", _obj(**{**good, "title": _obj(a=_s("SECRET"))})),
            ("title is a number", _obj(**{**good, "title": NUMBER})),
            ("title is a BigInt too long for an int", _obj(**{**good, "title": BIGINT})),
            ("url is missing", _obj(title=good["title"], text=good["text"])),
            ("not an object", _arr(_s("SECRET"))),
            ("a string", _s("SECRET")),
            ("null", {"type": "null"}),
        ):
            with self.subTest(name):
                self.assert_tool_error(self.reading(result).call("page_read", {"tab": "t1"}))
        read = self.reading(_obj(**good)).call("page_read", {"tab": "t1", "max_chars": 100})
        self.assertFalse(read["isError"], read)
        self.assertEqual((read["structuredContent"]["text"], read["structuredContent"]["title"]), ("Hello", "Example"))

    def test_a_snapshot_of_another_shape_is_a_tool_error(self):
        info = _obj(role=_s("link"), name=_s("Home"), tag=_s("a"))
        for name, result in (
            ("a node that is a plain object", _arr(_arr(_obj(x=_s("SECRET")), info))),  # the issue's KeyError
            ("a node without its id", _arr(_arr({"type": "node", "value": {"nodeType": 1, "localName": "a"}}, info))),
            # A page that redefines querySelectorAll can return nodes that are not elements: click and type need one.
            ("a text node", _arr(_arr({"type": "node", "sharedId": "n-1", "value": {"nodeType": 3}}, info))),
            ("a node of no type", _arr(_arr({"type": "node", "sharedId": "n-1", "value": {"localName": "a"}}, info))),
            ("a node that is null", _arr(_arr({"type": "null"}, info))),
            ("a node id that is not a string", _arr(_arr(_obj(sharedId=NUMBER), info))),
            ("an object that has a node's id", _arr(_arr(_obj(sharedId=_s("n-1"), localName=_s("a")), info))),
            ("info that is a string", _arr(_arr(_node("n-1"), _s("SECRET")))),
            ("a pair of three", _arr(_arr(_node("n-1"), info, info))),
            ("a pair that is an object", _arr(_obj(a=_node("n-1"), b=info))),
            ("a number", NUMBER),
            ("a string", _s("SECRET")),
            ("an object", _obj(a=_s("SECRET"))),
            ("null", {"type": "null"}),
            ("more than max_elements", _arr(*[_arr(_node(f"n-{i}"), info) for i in range(3)])),
        ):
            with self.subTest(name):
                bridge = self.reading(result)
                bridge.elements["t1"] = {"e1": "shared-earlier"}
                self.assert_tool_error(bridge.call("page_snapshot", {"tab": "t1", "max_elements": 2}))
                self.assertEqual(bridge.elements["t1"], {"e1": "shared-earlier"})  # the earlier map is kept whole

    def test_a_snapshot_keeps_its_own_element_ids(self):
        # A page can add properties to the helper's info objects (a setter on Object.prototype): an `element`
        # among them does not replace the id the click map uses.
        info = _obj(role=_s("link"), name=_s("Home"), tag=_s("a"), element=_s("e2"))
        bridge = self.reading(_arr(_arr(_node("n-1"), info), _arr(_node("n-2"), _obj(role=_s("button")))))
        listed = bridge.call("page_snapshot", {"tab": "t1"})
        self.assertFalse(listed["isError"], listed)
        elements = listed["structuredContent"]["elements"]
        self.assertEqual([e["element"] for e in elements], ["e1", "e2"])
        self.assertEqual(elements[0], {"element": "e1", "role": "link", "name": "Home", "tag": "a"})
        self.assertEqual(bridge.elements["t1"], {"e1": "n-1", "e2": "n-2"})
        # An empty page is a snapshot with no elements.
        empty = self.reading(_arr()).call("page_snapshot", {"tab": "t1"})
        self.assertEqual(empty["structuredContent"]["elements"], [])

    def test_a_bigint_too_long_for_an_int_is_no_value(self):
        # BiDi sends a BigInt as its digits, which Python turns into an int only up to 4300 of them. One the page
        # puts in what it lists is no value, not an exception that ends the call; nor in the title it reads.
        title = tools.Bridge._title  # the real one: reading() puts a fixed title in its place
        bridge = self.reading(_arr(_arr(_node("n-1"), _obj(role=BIGINT, name=_s("Home")))))
        listed = bridge.call("page_snapshot", {"tab": "t1"})
        self.assertFalse(listed["isError"], listed)
        self.assertEqual(listed["structuredContent"]["elements"], [{"element": "e1", "role": None, "name": "Home"}])
        self.assertEqual(title(self.reading(BIGINT), "t1", None), "")
        self.assertEqual(bidi_mod.deserialize(_arr(BIGINT, {"type": "bigint", "value": "-12"})), [None, -12])


class OpenProfileTest(Home):
    """A profile of the user's that a session has open follows the user's choices on every call: taken away from the
    agent, given at another path, its signed-in sessions blocked, an answer "once" that was for an earlier call, a
    timed grant that ended, or a second place no longer allowed. The tab is acted on only when they allow it now."""

    PATH = "/home/u/.nulavio/p1"
    ACTS = frozenset({"script.evaluate", "script.callFunction", "input.performActions", "input.setFiles",
                      "browsingContext.navigate", "browsingContext.close", "browsingContext.captureScreenshot",
                      "browsingContext.handleUserPrompt"})  # fmt: skip

    def opened(self, level="assisted", answer="once", url="https://mail.example/inbox"):
        agent, _ = registry.add(f"p-{len(registry.load()['agents'])}", "other", level)
        registry.set_profiles(agent["id"], [{"label": "Trabalho", "path": self.PATH}])
        approver = Approve(answer)
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        commands, tabs = [], {"w1": url}
        self.tabs = tabs  # where each tab is now (a test moves one while a question is open)
        self.redirects: dict[str, str] = {}  # where a navigation to an address ends
        self.click_goes: str | None = None  # where a click takes the tab

        def command(method, params=None, **_k):
            looks = method == "script.callFunction" and params["target"].get("sandbox") and params[
                "functionDeclaration"] == tools.INSPECT_FN  # fmt: skip
            commands.append("look" if looks else method)  # read where the page does not see it, before a question (#736)
            if method == "browsingContext.getTree":
                return {"contexts": [{"context": tab, "url": at} for tab, at in tabs.items()]}
            if method == "browsingContext.create":
                tabs["w2"] = "about:blank"
                return {"context": "w2"}
            if method == "browsingContext.navigate":
                tabs[params["context"]] = self.redirects.get(params["url"], params["url"])
            if method == "input.performActions" and self.click_goes:
                tabs[params["context"]] = self.click_goes
            return {"script": "p-1", "intercept": "i-1"}

        engine = mock.Mock(events=[])
        engine.command.side_effect = command
        target = mock.Mock(bidi=engine, profile_dir=Path(self.PATH))
        target.start.return_value = engine
        bridge.profiles["Trabalho"] = target
        bridge.owner["w1"] = "Trabalho"
        bridge.elements["w1"] = {"e1": "shared-1"}
        page = {"text": "Inbox: 3 new", "url": url, "title": "Mail"}
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.read = stack.enter_context(mock.patch.object(tools.Bridge, "_eval", return_value=page))
        stack.enter_context(mock.patch.object(policy, "_resolves_locally", return_value=False))
        stack.enter_context(mock.patch.object(tools.Bridge, "_forms_held", return_value=0))
        stack.enter_context(mock.patch.object(tools.Bridge, "_forms_where", return_value=[]))  # no form is held
        return agent, bridge, approver, target, commands

    @staticmethod
    def arguments(tool) -> dict:
        args = {}
        for name in tool.schema.get("required", []):
            kind = tool.schema["properties"][name].get("type")
            args[name] = {"tab": "w1", "url": "https://mail.example/other"}.get(name, True if kind == "boolean" else "e1")
        return args

    def tab_tools(self):
        return [tool for tool in tools.TOOLS if "tab" in tool.schema.get("properties", {})]

    def test_an_answer_once_is_for_the_call_that_asked(self):
        _agent, bridge, approver, _target, commands = self.opened(answer="once")
        first = bridge.call("page_read", {"tab": "w1"})
        self.assertFalse(first["isError"], first)
        self.assertEqual(approver.asked, [("authenticated_sessions", "https://mail.example")])
        self.assertEqual(approver.places, ["Trabalho"])
        for tool in self.tab_tools():
            with self.subTest(tool=tool.name):
                approver = Approve("deny")
                bridge.approver = approver
                commands.clear()
                self.read.reset_mock()
                if tool.capability == "execute_js":
                    # Assisted blocks scripts, which would be refused before the profile is asked about (#730): on ask,
                    # with cookies and storage allowed, the script shows the answer "once" is not reused either.
                    registry.grant(_agent["id"], "execute_js", "ask")
                    registry.grant(_agent["id"], "cookies_storage", "allow")
                result = bridge.call(tool.name, self.arguments(tool))
                self.assertTrue(result["isError"], result)
                self.assertFalse(self.ACTS & set(commands), commands)
                self.read.assert_not_called()
                if tool.name == "upload":
                    # Uploads work only in the AI Workspace: refused before the profile is asked about (#730).
                    self.assertEqual(approver.asked, [])
                    self.assertIn("uploads work only in the AI Workspace", result["content"][0]["text"])
                    continue
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual(approver.asked[:1], [("authenticated_sessions", "https://mail.example")])
                self.assertEqual((entry["reason"], entry["capability"].split(",")[0]), ("denied", "authenticated_sessions"))

    def test_a_profile_taken_away_moved_or_blocked_is_closed_before_the_call(self):
        changes = {
            "taken away": lambda a: registry.set_profiles(a, []),
            "another path": lambda a: registry.set_profiles(a, [{"label": "Trabalho", "path": "/home/u/.nulavio/p2"}]),
            "sessions blocked": lambda a: registry.grant(a, "authenticated_sessions", "block"),
        }
        for name, change in changes.items():
            for tool in self.tab_tools():
                with self.subTest(change=name, tool=tool.name):
                    agent, bridge, approver, target, commands = self.opened(level="autonomous")
                    change(agent["id"])
                    result = bridge.call(tool.name, self.arguments(tool))
                    self.assertTrue(result["isError"], result)
                    target.stop.assert_called_once()
                    self.assertNotIn("Trabalho", bridge.profiles)
                    self.assertNotIn("w1", bridge.owner)
                    self.assertFalse(self.ACTS & set(commands), commands)
                    self.read.assert_not_called()
                    self.assertEqual(approver.asked, [])
        # tabs_list no longer lists its tabs either (the AI Workspace is the one engine left).
        agent, bridge, _approver, target, commands = self.opened(level="autonomous")
        registry.set_profiles(agent["id"], [])
        workspace = mock.Mock(events=[])
        workspace.command.side_effect = lambda method, *_a, **_k: {"script": "p-2", "intercept": "i-2", "contexts": []}
        bridge.workspace = mock.Mock(bidi=workspace)
        bridge.workspace.start.return_value = workspace
        listed = bridge.call("tabs_list", {})
        self.assertFalse(listed["isError"], listed)
        self.assertNotIn("mail.example", json.dumps(listed))
        self.assertNotIn("Trabalho", json.dumps(listed))
        target.stop.assert_called_once()

    def test_a_profiles_downloads_are_listed_only_where_acting_there_would_not_ask(self):
        agent, bridge, approver, target, _commands = self.opened(answer="deny")
        registry.grant(agent["id"], "files", "allow")
        target.bidi.events = [
            (1, {"method": "browsingContext.downloadWillBegin",
                 "params": {"navigation": "n1", "url": "https://mail.example/a.pdf", "suggestedFilename": "salary.pdf"}}),
        ]  # fmt: skip
        self.assertNotIn("salary.pdf", json.dumps(bridge.call("downloads_list", {})))
        self.assertEqual(approver.asked, [])  # a list does not ask
        registry.grant(agent["id"], "authenticated_sessions", "allow")
        self.assertIn("salary.pdf", json.dumps(bridge.call("downloads_list", {})))

    def test_a_new_tab_in_an_open_profile_asks_once_in_that_call_and_again_in_the_next(self):
        _agent, bridge, approver, _target, _commands = self.opened(answer="once")
        with mock.patch.object(tools.Bridge, "_arrived"):
            made = bridge.call("tab_new", {"profile": "Trabalho", "url": "https://mail.example/new"})
        self.assertFalse(made["isError"], made)
        self.assertEqual(approver.asked, [("authenticated_sessions", "https://mail.example")])  # asked once, not per step
        later = Approve("deny")
        bridge.approver = later
        self.read.reset_mock()
        self.assertTrue(bridge.call("page_read", {"tab": "w2"})["isError"])
        self.assertEqual(later.asked, [("authenticated_sessions", "https://mail.example")])
        self.read.assert_not_called()

    def test_a_timed_grant_that_ended_or_a_second_place_now_refused_stops_acting_there(self):
        agent, bridge, approver, _target, _commands = self.opened(answer="deny")
        registry.grant(agent["id"], "authenticated_sessions", "allow", minutes=30)
        self.assertFalse(bridge.call("page_read", {"tab": "w1"})["isError"])
        later = policy.now() + _dt.timedelta(minutes=31)
        with mock.patch.object(policy, "now", return_value=later):
            result = bridge.call("page_read", {"tab": "w1"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [("authenticated_sessions", "https://mail.example")])
        # Autonomous: multiple_profiles asks; set to block while the AI Workspace is open too.
        agent, bridge, approver, _target, _commands = self.opened(level="autonomous", answer="session")
        workspace = mock.Mock(events=[])
        workspace.command.side_effect = lambda method, *_a, **_k: {"script": "p-2", "intercept": "i-2", "contexts": []}
        bridge.workspace = mock.Mock(bidi=workspace)
        bridge.workspace.start.return_value = workspace
        self.assertFalse(bridge.call("page_read", {"tab": "w1"})["isError"])
        self.assertEqual(approver.asked, [("multiple_profiles", None)])
        self.assertFalse(bridge.call("page_read", {"tab": "w1"})["isError"])  # the answer stands for this session
        self.assertEqual(len(approver.asked), 1)
        registry.grant(agent["id"], "multiple_profiles", "block")
        self.read.reset_mock()
        result = bridge.call("page_read", {"tab": "w1"})
        self.assertTrue(result["isError"], result)
        self.read.assert_not_called()
        self.assertNotIn("Trabalho", bridge.profiles)  # let go before the call (the next test)

    def test_autonomous_acts_in_a_given_profile_alone_without_asking(self):
        """The Autonomous level hint says what this does (#714 review): with signed-in sessions allowed, a profile on
        the agent's list is worked in without a question while it is the only place open; only a second place at once
        asks (multiple_profiles, the test above)."""
        _agent, bridge, approver, _target, _commands = self.opened(level="autonomous", answer="deny")
        self.assertFalse(bridge.call("page_read", {"tab": "w1"})["isError"])
        with mock.patch.object(tools.Bridge, "_arrived"):
            made = bridge.call("tab_new", {"profile": "Trabalho", "url": "https://mail.example/new"})
        self.assertFalse(made["isError"], made)
        self.assertEqual(approver.asked, [])
        self.assertEqual([name for name, _ in bridge._engines()], ["Trabalho"])  # one place only: no AI Workspace

    def test_a_tab_list_describes_a_profiles_tab_only_where_acting_would_not_ask(self):
        agent, bridge, approver, _target, _commands = self.opened(answer="deny")
        listed = [{"context": "w1", "url": "https://mail.example/inbox", "profile": "Trabalho"}]
        with mock.patch.object(tools.Bridge, "_tabs", return_value=listed):
            entry = bridge.call("tabs_list", {})["structuredContent"]["tabs"][0]
            self.assertEqual((entry["url"], entry["title"], entry["needs_permission"]), (None, None, ["authenticated_sessions"]))
            self.assertEqual(approver.asked, [])  # a list does not ask
            registry.grant(agent["id"], "authenticated_sessions", "allow")
            entry = bridge.call("tabs_list", {})["structuredContent"]["tabs"][0]
            self.assertEqual(entry["url"], "https://mail.example/inbox")

    def test_navigating_a_profiles_tab_asks_for_the_site_it_goes_to(self):
        _agent, bridge, approver, _target, commands = self.opened(answer="session")
        with mock.patch.object(tools.Bridge, "_arrived"):
            self.assertFalse(bridge.call("navigate", {"tab": "w1", "url": "https://mail.example/sent"})["isError"])
            self.assertEqual(approver.asked, [("authenticated_sessions", "https://mail.example")])
            later = Approve("deny")
            bridge.approver = later
            result = bridge.call("navigate", {"tab": "w1", "url": "https://bank.example/"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(later.asked, [("authenticated_sessions", "https://bank.example")])  # mail.example's answer stands
        self.assertEqual(commands.count("browsingContext.navigate"), 1)

    def test_where_a_call_ends_in_a_profile_is_asked_about_or_not_described(self):
        # A redirect, or a page after a click, can take a profile's tab to another of the agent's sites: the user's
        # signed-in session there is asked about for that site too (a navigation), or its address is not described.
        class PerSite(Approve):
            def ask(self, agent, capability, target, place="", cancel=None):
                super().ask(agent, capability, target, place, cancel)
                return "deny" if target == "https://bank.example" else "once"

        for tool, args in (
            ("navigate", {"tab": "w1", "url": "https://mail.example/x"}),
            ("tab_new", {"profile": "Trabalho", "url": "https://mail.example/x"}),
        ):
            with self.subTest(tool=tool):
                _agent, bridge, _approver, _target, _commands = self.opened()
                bridge.approver = approver = PerSite("once")
                self.redirects["https://mail.example/x"] = "https://bank.example/account"
                with (
                    mock.patch.object(tools.Bridge, "_open_dialog", return_value=None),
                    mock.patch.object(tools.Bridge, "_forms_settle", return_value=False),
                ):
                    result = bridge.call(tool, args)
                self.assertTrue(result["isError"], result)
                self.assertEqual(approver.asked[-1], ("authenticated_sessions", "https://bank.example"))
                self.assertEqual(approver.places[-1], "Trabalho")
                self.assertNotIn("bank.example/account", json.dumps(result))
                self.assertNotIn("Inbox", json.dumps(result))
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["reason"], entry["target"]), ("denied", "https://bank.example"))
        # A click: the result does not say where the page took the tab, and asks nothing more.
        _agent, bridge, approver, _target, _commands = self.opened()
        self.click_goes = "https://bank.example/account"
        with (
            mock.patch.object(tools.Bridge, "_call_fn", return_value={"connected": True}),
            mock.patch.object(tools.Bridge, "_settle", return_value=True),
            mock.patch.object(tools.Bridge, "_forms_prepare"),
            mock.patch.object(tools.Bridge, "_forms_settle", return_value=False),
            mock.patch.object(tools.Bridge, "_open_dialog", return_value=None),
        ):
            result = bridge.call("click", {"tab": "w1", "element": "e1"})
        self.assertFalse(result["isError"], result)
        where = result["structuredContent"]
        self.assertEqual((where["url"], where.get("needs_permission")), (None, ["authenticated_sessions"]))
        self.assertNotIn("bank.example", json.dumps(result))
        self.assertEqual(approver.asked, [("authenticated_sessions", "https://mail.example")])
        # The page moves on while the question about where the navigation ended is open (a question can stay open
        # for minutes): the call describes where the tab is now only if that needs no other answer, title included.
        test = self
        goes_on = {"https://other.example": "https://third.example/next",
                   "https://third.example": "https://bank.example/account"}  # fmt: skip

        class GoesOn(Approve):
            def ask(self, agent, capability, target, place="", cancel=None):
                for tab, at in list(test.tabs.items()):
                    if target in goes_on and policy.origin(at) == target:
                        test.tabs[tab] = goes_on[target]
                return super().ask(agent, capability, target, place, cancel)

        for tool, args in (
            ("navigate", {"tab": "w1", "url": "https://mail.example/x"}),
            ("tab_new", {"profile": "Trabalho", "url": "https://mail.example/x"}),
        ):
            with self.subTest(tool=tool, moves="while asked"):
                _agent, bridge, _approver, _target, _commands = self.opened()
                bridge.approver = approver = GoesOn("once")
                self.redirects["https://mail.example/x"] = "https://other.example/land"
                with (
                    mock.patch.object(tools.Bridge, "_open_dialog", return_value=None),
                    mock.patch.object(tools.Bridge, "_forms_settle", return_value=False),
                ):
                    result = bridge.call(tool, args)
                self.assertFalse(result["isError"], result)
                where = result["structuredContent"]
                self.assertEqual((where["url"], where["title"]), (None, None))
                self.assertEqual(where.get("needs_permission"), ["authenticated_sessions"])
                for unasked in ("third.example", "bank.example"):
                    if ("authenticated_sessions", f"https://{unasked}") not in approver.asked:
                        self.assertNotIn(unasked, json.dumps(result))
                self.assertIn(("authenticated_sessions", "https://other.example"), approver.asked)  # it moved meanwhile
                self.assertNotIn(("authenticated_sessions", "https://bank.example"), approver.asked)
                self.assertNotIn("Inbox", json.dumps(result))

    def test_a_new_tab_in_a_profile_not_given_to_the_agent_asks_nothing(self):
        # The question would name a place that is not one of the agent's (any label the agent writes).
        agent, bridge, approver, _target, commands = self.opened()
        registry.grant(agent["id"], "navigate", "ask")
        result = bridge.call("tab_new", {"profile": "Nowhere", "url": "https://mail.example/"})
        self.assertTrue(result["isError"], result)
        self.assertEqual((approver.asked, approver.places), ([], []))
        self.assertFalse(self.ACTS & set(commands), commands)
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual(entry["reason"], "profile-not-authorized")

    def test_a_second_place_refused_closes_the_users_profiles(self):
        # Two places open, then multiple_profiles blocked: the user's profiles are closed before the call (as for
        # their signed-in sessions blocked), not left running with tabs no call may use or close.
        agent, bridge, approver, target, _commands = self.opened(level="autonomous", answer="session")
        workspace = mock.Mock(events=[])
        workspace.command.side_effect = lambda method, *_a, **_k: {"script": "p-2", "intercept": "i-2", "contexts": []}
        bridge.workspace = mock.Mock(bidi=workspace)
        bridge.workspace.start.return_value = workspace
        self.assertFalse(bridge.call("page_read", {"tab": "w1"})["isError"])
        registry.grant(agent["id"], "multiple_profiles", "block")
        result = bridge.call("page_read", {"tab": "w1"})
        self.assertTrue(result["isError"], result)
        target.stop.assert_called_once()
        self.assertNotIn("Trabalho", bridge.profiles)
        self.assertNotIn("w1", bridge.owner)
        self.assertEqual(approver.asked, [("multiple_profiles", None)])

    # The tools that act on the page where the tab is (require_here): what that address needs is theirs to check.
    # upload works only in the AI Workspace: refused in a profile's tab before anything else (test_an_upload_...).
    HERE = ("page_read", "page_snapshot", "screenshot", "click", "type", "evaluate", "dialog")

    @staticmethod
    def with_workspace(bridge) -> None:
        """The AI Workspace open beside the profile: a second place, which Autonomous asks about (multiple_profiles)."""
        workspace = mock.Mock(events=[])
        workspace.command.side_effect = lambda method, *_a, **_k: {"script": "p-2", "intercept": "i-2", "contexts": []}
        bridge.workspace = mock.Mock(bidi=workspace)
        bridge.workspace.start.return_value = workspace

    def test_a_profiles_tab_asks_nothing_before_a_refusal_no_answer_changes(self):
        # #730: reading where a profile's tab is entered the profile, which asked about the signed-in session there and
        # (another place open) multiple_profiles, before the refusals that no answer changes.
        cases = (
            # An address agents never act on (#508): refused as a tool error, whatever the tool.
            ("data", "data:text/html,hi", {}, None),
            # A permission the address needs, blocked for the agent (cookies_storage allowed: the script's own check).
            ("local", "http://localhost:8080/", {"local_resources": "block", "cookies_storage": "allow"}, "local_resources"),
            # #725's case there: a script while cookies_storage is blocked (Autonomous blocks it).
            ("cookies", "https://mail.example/inbox", {}, "cookies_storage"),
        )  # fmt: skip
        for name, url, grants, capability in cases:
            for tool in self.HERE if name != "cookies" else ("evaluate",):
                with self.subTest(case=name, tool=tool):
                    agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="session", url=url)
                    for grant, mode in grants.items():
                        registry.grant(agent["id"], grant, mode)
                    self.with_workspace(bridge)
                    result = bridge.call(tool, self.arguments(tools.BY_NAME[tool]))
                    self.assertTrue(result["isError"], result)
                    self.assertEqual(approver.asked, [])
                    self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
                    self.assertFalse(self.ACTS & set(commands), commands)
                    self.read.assert_not_called()
                    entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                    if capability is None:
                        self.assertIn("agents do not act on", result["content"][0]["text"])
                    else:
                        reason = "grant" if grants else "preset:autonomous"
                        self.assertEqual((entry["capability"], entry["reason"], entry["target"]),
                                         (capability, reason, policy.origin(url)))  # fmt: skip
        # A profile's tab now outside the agent's sites (a redirect or the page took it there): refused whatever the
        # answer, as out of scope, so nothing is asked first either.
        for tool in self.HERE:
            with self.subTest(case="outside its sites", tool=tool):
                agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="session",
                                                                         url="https://elsewhere.example/")  # fmt: skip
                registry.set_domains(agent["id"], ["mail.example"])
                self.with_workspace(bridge)
                result = bridge.call(tool, self.arguments(tools.BY_NAME[tool]))
                self.assertTrue(result["isError"], result)
                self.assertEqual(approver.asked, [])
                self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
                self.assertFalse(self.ACTS & set(commands), commands)
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["reason"], entry["target"]), ("out-of-scope", "https://elsewhere.example"))
        # Navigating from a profile's tab to an address whose permission is blocked: Assisted asked about the
        # signed-in session for the site the tab was at, then refused local_resources.
        agent, bridge, approver, _target, commands = self.opened(level="assisted", answer="session")
        result = bridge.call("navigate", {"tab": "w1", "url": "http://localhost:8080/"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [])
        self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
        self.assertNotIn("browsingContext.navigate", commands)
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["capability"], entry["reason"], entry["target"]),
                         ("local_resources", "preset:assisted", "http://localhost:8080"))  # fmt: skip

    def test_an_upload_in_a_profiles_tab_asks_nothing(self):
        # Independent review of #737: an upload in a tab of one of the user's profiles asked about the signed-in
        # session there, with another place open about working in two places, and about files, and then always failed
        # because uploads work only in the AI Workspace. The session answers stayed.
        for level, workspace in (("assisted", False), ("autonomous", True)):
            with self.subTest(level=level, workspace=workspace):
                agent, bridge, approver, _target, commands = self.opened(level=level, answer="session")
                registry.grant(agent["id"], "files", "ask")
                if workspace:  # a second place open: Autonomous asks about it (multiple_profiles)
                    self.with_workspace(bridge)
                result = bridge.call("upload", {"tab": "w1", "element": "e1", "file": "a.txt"})
                self.assertTrue(result["isError"], result)
                self.assertIn("uploads work only in the AI Workspace", result["content"][0]["text"])
                self.assertEqual(approver.asked, [])
                self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
                self.assertFalse(self.ACTS & set(commands), commands)
                self.read.assert_not_called()
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["outcome"], entry["target"]), ("error:tool", "https://mail.example"))

    def test_an_upload_the_workspace_was_started_without_asks_nothing(self):
        # The AI Workspace started while files was blocked has no uploads folder: an upload, once files asks, asked and
        # then always failed. It fails first now, as the profile's tab does.
        agent, _ = registry.add("u-1", "other", "assisted")
        approver = Approve("session")
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        bridge.elements["t1"] = {"e1": "shared-1"}
        bridge.owner["t1"] = ""
        self.with_workspace(bridge)
        bridge.workspace.uploads = False
        bridge.workspace.uploads_dir = Path(self.PATH) / "uploads"
        with mock.patch.object(tools.Bridge, "_url_of", return_value="https://example.org/"):
            result = bridge.call("upload", {"tab": "t1", "element": "e1", "file": "a.txt"})
        self.assertTrue(result["isError"], result)
        self.assertIn("uploads were not allowed when this workspace started", result["content"][0]["text"])
        self.assertEqual(approver.asked, [])
        self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["outcome"], entry["target"]), ("error:tool", "https://example.org"))

    def test_a_profiles_tab_is_asked_about_in_the_same_order_when_an_answer_can_allow_it(self):
        # I7: with those permissions on ask or allowed, the same questions as before, in the same order.
        agent, bridge, approver, _target, _commands = self.opened(level="autonomous", answer="once")
        registry.grant(agent["id"], "cookies_storage", "allow")
        self.with_workspace(bridge)
        result = bridge.call("evaluate", {"tab": "w1", "expression": "1"})
        self.assertFalse(result["isError"], result)
        self.assertEqual(approver.asked, [("multiple_profiles", None), ("execute_js", "https://mail.example")])
        agent, bridge, approver, _target, _commands = self.opened(level="autonomous", answer="once",
                                                                  url="http://localhost:8080/")  # fmt: skip
        self.with_workspace(bridge)
        result = bridge.call("page_read", {"tab": "w1"})
        self.assertFalse(result["isError"], result)
        self.assertEqual(approver.asked, [("multiple_profiles", None), ("local_resources", "http://localhost:8080")])
        agent, bridge, approver, _target, _commands = self.opened(level="assisted", answer="once")
        registry.grant(agent["id"], "local_resources", "ask")
        with mock.patch.object(tools.Bridge, "_arrived", return_value="http://localhost:8080/"):
            result = bridge.call("navigate", {"tab": "w1", "url": "http://localhost:8080/"})
        self.assertFalse(result["isError"], result)
        self.assertEqual(approver.asked, [("authenticated_sessions", "https://mail.example"),
                                          ("local_resources", "http://localhost:8080"),
                                          ("authenticated_sessions", "http://localhost:8080")])  # fmt: skip

    def assisted_beside_the_workspace(self):
        """Assisted, with a profile given and only the AI Workspace open (it blocks multiple_profiles)."""
        agent, _ = registry.add(f"p-{len(registry.load()['agents'])}", "other", "assisted")
        registry.set_profiles(agent["id"], [{"label": "Trabalho", "path": self.PATH}])
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(policy, "_resolves_locally", return_value=False))
        started = stack.enter_context(mock.patch.object(tools, "ProfileTarget", side_effect=AssertionError("opened")))
        return agent, started

    def test_a_new_tab_in_a_profile_is_not_asked_about_while_a_second_place_is_blocked(self):
        # #730: Assisted asked about the signed-in session in the profile (_open_profile), then refused the call for
        # multiple_profiles, and a "for this session" answer stayed.
        agent, started = self.assisted_beside_the_workspace()
        approver = Approve("session")
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        self.with_workspace(bridge)
        result = bridge.call("tab_new", {"profile": "Trabalho", "url": "https://mail.example/"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [])
        self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
        started.assert_not_called()
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["capability"], entry["reason"], entry["target"]),
                         ("multiple_profiles", "preset:assisted", "https://mail.example"))  # fmt: skip
        # On ask, the same two questions as before, in the same order (the second one answered no here).
        registry.grant(agent["id"], "multiple_profiles", "ask")

        class SecondNo(Approve):
            def ask(self, agent, capability, target, place="", cancel=None):
                super().ask(agent, capability, target, place, cancel)
                return "deny" if capability == "multiple_profiles" else "once"

        bridge.approver = approver = SecondNo("once")
        result = bridge.call("tab_new", {"profile": "Trabalho", "url": "https://mail.example/"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [("authenticated_sessions", "https://mail.example"), ("multiple_profiles", None)])
        self.assertEqual(approver.places, ["Trabalho", "Trabalho"])
        started.assert_not_called()
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["capability"].split(",")[-1], entry["reason"]), ("multiple_profiles", "denied"))

    # OpenCodeReview of #737 at d8c808ee: what a question waits on the person for, the tab can change meanwhile.
    READER = "about:reader?url=https%3A%2F%2Fmail.example%2Finbox"

    def move_on(self, approver: Approve, capability: str, to: str) -> None:
        """While the question about `capability` is open, the tab goes to `to` (the person, or the page)."""

        def meanwhile():
            if approver.asked[-1][0] == capability:
                self.tabs["w1"] = to

        approver.meanwhile = meanwhile

    def here_arguments(self, tool: str) -> dict:
        return self.arguments(tools.BY_NAME[tool])

    def test_reader_view_opened_while_a_question_is_open_is_not_acted_in(self):
        # Finding 1: the tab went into Reader View, an internal page, while the profile's question (Assisted asks about
        # the signed-in session) or the tool's own question was open. Reader View shows the same site, so the check
        # after the answer let the call act in a page agents never act on.
        for question, level in (("authenticated_sessions", "assisted"), ("own", "autonomous")):
            for tool in self.HERE:
                with self.subTest(question=question, tool=tool):
                    agent, bridge, approver, _target, commands = self.opened(level=level, answer="once")
                    own = tools.BY_NAME[tool].capability
                    if own == "execute_js":
                        registry.grant(agent["id"], "cookies_storage", "allow")
                    if question == "own":
                        registry.grant(agent["id"], own, "ask")
                    elif own == "execute_js":
                        registry.grant(agent["id"], "execute_js", "allow")
                    self.move_on(approver, own if question == "own" else question, self.READER)
                    result = bridge.call(tool, self.here_arguments(tool))
                    self.assertTrue(result["isError"], result)
                    self.assertFalse(self.ACTS & set(commands), commands)
                    self.read.assert_not_called()

    def test_a_move_while_the_profiles_question_is_open_goes_on_where_the_tab_is(self):
        # I7: the address was read after entering the profile before #730, so a tab that moved to another of the
        # agent's sites while that question was open was acted in there, and named there in the activity.
        _agent, bridge, approver, _target, _commands = self.opened(level="assisted", answer="once")
        self.move_on(approver, "authenticated_sessions", "https://news.example/today")
        result = bridge.call("page_read", {"tab": "w1"})
        self.assertFalse(result["isError"], result)
        self.read.assert_called()
        self.assertEqual(json.loads(audit.audit_path().read_text().splitlines()[-1])["target"], "https://news.example")

    def test_a_tab_closed_after_a_question_is_checked_where_it_is_now(self):
        # Finding 2: the tab went outside the agent's sites while the profile's question was open, and was closed there,
        # checked (and recorded) for the site it had been at.
        agent, bridge, approver, _target, commands = self.opened(level="assisted", answer="once")
        registry.set_domains(agent["id"], ["mail.example"])
        self.move_on(approver, "authenticated_sessions", "https://elsewhere.example/")
        result = bridge.call("tab_close", {"tab": "w1"})
        self.assertTrue(result["isError"], result)
        self.assertNotIn("browsingContext.close", commands)
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["reason"], entry["target"]), ("out-of-scope", "https://elsewhere.example"))

    def test_a_tab_that_moved_while_closing_it_was_asked_is_not_closed(self):
        # The tab moved while its own question (navigate) was open: not closed at an address nobody was asked about.
        agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="once")
        registry.grant(agent["id"], "navigate", "ask")
        self.move_on(approver, "navigate", "https://elsewhere.example/")
        result = bridge.call("tab_close", {"tab": "w1"})
        self.assertTrue(result["isError"], result)
        self.assertIn("moved", result["content"][0]["text"])
        self.assertNotIn("browsingContext.close", commands)

    def test_a_tab_that_moved_while_the_profile_was_entered_quietly_is_checked_where_it_is(self):
        # OpenCodeReview of #737 at 4a01fde3: with the profile and navigate both allowed, nothing is asked, and the tab
        # went outside the agent's sites while the profile's checks ran. The address read before them was checked, and
        # the tab was closed at its new site; before #730 the address was read after entering the profile.
        agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="once")
        registry.set_domains(agent["id"], ["mail.example"])
        registry.grant(agent["id"], "authenticated_sessions", "allow")
        registry.grant(agent["id"], "navigate", "allow")
        decide = registry.decide

        def checked_meanwhile(agent_id, capability, **kwargs):
            decision = decide(agent_id, capability, **kwargs)
            if capability == "authenticated_sessions" and kwargs.get("place") == "Trabalho":
                self.tabs["w1"] = "https://elsewhere.example/"
            return decision

        with mock.patch.object(registry, "decide", side_effect=checked_meanwhile):
            result = bridge.call("tab_close", {"tab": "w1"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [])
        self.assertNotIn("browsingContext.close", commands)
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["reason"], entry["target"]), ("out-of-scope", "https://elsewhere.example"))

    def test_a_profiles_tab_outside_the_agents_sites_is_not_looked_up(self):
        # Finding 3: the host of a tab outside the agent's sites went to this computer's resolver (the local network
        # check) before the site list refused the call: a profile with encrypted DNS would not have asked it.
        for tool in self.HERE:
            with self.subTest(tool=tool):
                agent, bridge, approver, _target, _commands = self.opened(level="autonomous", url="https://elsewhere.example/")
                registry.set_domains(agent["id"], ["mail.example"])
                with mock.patch.object(policy, "_resolves_locally", return_value=False) as resolved:
                    result = bridge.call(tool, self.here_arguments(tool))
                self.assertTrue(result["isError"], result)
                resolved.assert_not_called()
                self.assertEqual(approver.asked, [])
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["reason"], entry["target"]), ("out-of-scope", "https://elsewhere.example"))

    def test_enter_is_not_asked_about_after_the_tab_moved(self):
        # Finding 4: typing with Enter asked about sending forms for the site the tab had been at, after it moved
        # while interact was asked; an answer "until the agent disconnects" stayed, for a form never sent.
        agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="session")
        registry.grant(agent["id"], "interact", "ask")
        registry.grant(agent["id"], "submit_forms", "ask")
        self.move_on(approver, "interact", "https://news.example/")
        result = bridge.call("type", {"tab": "w1", "element": "e1", "text": "x", "submit": True})
        self.assertTrue(result["isError"], result)
        self.assertIn("moved", result["content"][0]["text"])
        self.assertEqual(approver.asked, [("interact", "https://mail.example")])
        self.assertNotIn("submit_forms", registry.get(agent["id"]).get("session_grants", {}))
        self.assertFalse(self.ACTS & set(commands), commands)

    def test_a_scripts_second_question_is_not_asked_after_the_tab_moved(self):
        # A script's two questions come one after the other: the second is not asked for a page the tab left.
        agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="session")
        registry.grant(agent["id"], "cookies_storage", "ask")
        self.move_on(approver, "execute_js", "https://news.example/")
        result = bridge.call("evaluate", {"tab": "w1", "expression": "1"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [("execute_js", "https://mail.example")])
        self.assertNotIn("cookies_storage", registry.get(agent["id"]).get("session_grants", {}))
        self.assertFalse(self.ACTS & set(commands), commands)

    def test_a_profiles_page_is_read_only_after_its_question_is_answered(self):
        # #736: the look before interact reads the page (its held forms, the element) in a profile's tab only once
        # the profile was entered: nothing is read there for a call the person did not let in.
        for answer in ("deny", "once"):
            with self.subTest(answer=answer):
                _agent, bridge, approver, _target, commands = self.opened(level="assisted", answer=answer)
                at_question: list[int] = []
                approver.meanwhile = lambda seen=commands, at=at_question: at.append(len(seen))
                with mock.patch.object(tools.Bridge, "_forms_where", return_value=[]) as where:
                    where.side_effect = lambda *_a, seen=commands, **_k: seen.append("held?") or []
                    bridge.call("click", {"tab": "w1", "element": "e1"})
                self.assertEqual(approver.asked[0], ("authenticated_sessions", "https://mail.example"))
                self.assertFalse({"look", "held?"} & set(commands[: at_question[0]]), commands)
                if answer == "deny":
                    self.assertFalse({"look", "held?"} & set(commands), commands)
                else:
                    self.assertLess(commands.index("held?"), commands.index("look"))

    def test_a_page_the_tab_moved_to_is_not_read_before_its_own_question(self):
        # OpenCodeReview on #748, round 2: the tab went to another of the agent's sites while the profile's question
        # was open. That site's page is read only once its own signed-in-session question is answered.
        _agent, bridge, approver, _target, commands = self.opened(level="assisted", answer="once")
        at_question: list[int] = []

        def meanwhile():
            at_question.append(len(commands))
            if len(approver.asked) == 1:
                self.tabs["w1"] = "https://news.example/"

        approver.meanwhile = meanwhile
        with mock.patch.object(tools.Bridge, "_forms_where", side_effect=lambda *_a, **_k: commands.append("held?") or []):
            bridge.call("click", {"tab": "w1", "element": "e1"})
        self.assertEqual(approver.asked[:2], [("authenticated_sessions", "https://mail.example"),
                                              ("authenticated_sessions", "https://news.example")])  # fmt: skip
        self.assertFalse({"look", "held?"} & set(commands[: at_question[1]]), commands)

    def test_a_links_question_is_not_asked_after_the_tab_moved(self):
        # A submit button with a link: the link's question (navigate) is not asked for a page the tab left while the
        # form's was open.
        agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="session")
        registry.grant(agent["id"], "submit_forms", "ask")
        registry.grant(agent["id"], "navigate", "ask")
        self.move_on(approver, "submit_forms", "https://news.example/")
        info = {"connected": True, "submits": True, "href": "https://mail.example/sent"}
        with (
            mock.patch.object(tools.Bridge, "_earlier_forms", return_value=None),
            mock.patch.object(tools.Bridge, "_forms_prepare"),
            mock.patch.object(tools.Bridge, "_call_fn", return_value=info),
        ):
            result = bridge.call("click", {"tab": "w1", "element": "e1"})
        self.assertTrue(result["isError"], result)
        self.assertIn("moved", result["content"][0]["text"])
        self.assertEqual(approver.asked, [("submit_forms", "https://mail.example")])
        self.assertNotIn("navigate", registry.get(agent["id"]).get("session_grants", {}))
        self.assertNotIn("input.performActions", commands)

    def test_the_look_before_asking_never_asks(self):
        # Finding 5: a block that ended (a grant until a time) between the look before asking and the decision made
        # the look ask about it, before the call's first question and out of order, and an answer stayed.
        agent, bridge, _approver, _target, commands = self.opened(level="autonomous")
        registry.grant(agent["id"], "interact", "ask")
        registry.grant(agent["id"], "submit_forms", "ask")

        class NoToInteract(Approve):
            def ask(self, agent, capability, target, place="", cancel=None):
                super().ask(agent, capability, target, place, cancel)
                return "deny" if capability == "interact" else "session"

        bridge.approver = approver = NoToInteract("session")
        looked = policy.effective_mode

        def ended_since(agent, capability, *args, **kwargs):  # the Bridge read it blocked; the decision reads it on ask
            return ("block", "grant") if capability == "submit_forms" else looked(agent, capability, *args, **kwargs)

        with mock.patch.object(policy, "effective_mode", side_effect=ended_since):
            result = bridge.call("type", {"tab": "w1", "element": "e1", "text": "x", "submit": True})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [("interact", "https://mail.example")])
        self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
        self.assertFalse(self.ACTS & set(commands), commands)

    def test_a_route_to_a_profile_taken_away_is_refused_before_asking(self):
        # Finding 6: a site's route still named a profile no longer given to the agent. A new tab there asked to open
        # the address, and an answer "until the agent disconnects" stayed, before the profile was refused.
        agent, _ = registry.add("r-1", "other", "restricted")
        registry.set_profiles(agent["id"], [{"label": "Trabalho", "path": self.PATH}])
        registry.set_routes(agent["id"], [{"site": "mail.example", "profile": "Trabalho"}])
        registry.set_profiles(agent["id"], [])  # the route stays
        registry.grant(agent["id"], "navigate", "ask")
        approver = Approve("session")
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)
        with mock.patch.object(policy, "_resolves_locally", return_value=False):
            result = bridge.call("tab_new", {"url": "https://mail.example/"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [])
        self.assertEqual(registry.get(agent["id"]).get("session_grants", {}), {})
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["capability"], entry["reason"]), ("authenticated_sessions", "profile-not-authorized"))
        # I7: a refusal that comes first, with nothing asked before it, is still that one (navigate blocked here).
        registry.grant(agent["id"], "navigate", "block")
        with mock.patch.object(policy, "_resolves_locally", return_value=False):
            result = bridge.call("tab_new", {"url": "https://mail.example/"})
        self.assertTrue(result["isError"], result)
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["capability"], entry["reason"]), ("navigate", "grant"))

    # OpenCodeReview of #737 at c6b99ea8: after any question, the tab's address is looked at and classified again.
    def resolving(self, approver: Approve, capability: str) -> dict:
        """The tab's host starts to resolve to the local network while the question about `capability` is open (a
        rebinding name). Returns the lookups made, with how many questions had been asked by then."""
        state = {"local": False, "lookups": []}

        def lookup(host):
            state["lookups"].append((host, len(approver.asked)))
            return state["local"] and host == "mail.example"  # the tab's site, not where its link goes

        def meanwhile():
            if approver.asked[-1][0] == capability:
                state["local"] = True

        approver.meanwhile = meanwhile
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(policy, "_resolves_locally", side_effect=lookup))
        return state

    def test_a_host_that_turns_local_while_a_question_is_open_is_checked_again(self):
        # Finding 1: the tab's address was classified before the tool's own question and that reading was kept, so a
        # host that resolved to the local network once the person answered was acted on without local_resources
        # (the base classified it again after that question). Each question a call can ask about the tab, the last
        # one of each chain included: the check after it is the one before acting.
        info = {"connected": True, "submits": True, "href": "https://news.example/sent", "editable": True}
        cases = [(tool, "own") for tool in self.HERE] + [
            ("page_read", "authenticated_sessions"),  # the profile's question (Assisted)
            ("evaluate", "cookies_storage"),  # a script's second question
            ("type", "submit_forms"),  # Enter (submit=true)
            ("type", "enter"),  # Enter in a single-line field, inspected after interact
            ("click", "submit_forms"),  # a submit button, before its link
            ("click", "navigate"),  # its link: the last question before the click
        ]
        for tool, question in cases:
            with self.subTest(tool=tool, question=question):
                level = "assisted" if question == "authenticated_sessions" else "autonomous"
                agent, bridge, approver, _target, commands = self.opened(level=level, answer="once")
                registry.grant(agent["id"], "local_resources", "block")
                own = tools.BY_NAME[tool].capability
                registry.grant(agent["id"], own, "ask" if question == "own" else "allow")
                registry.grant(agent["id"], "cookies_storage", "ask" if question == "cookies_storage" else "allow")
                asked = {"own": own, "enter": "submit_forms"}.get(question, question)
                for other in ("submit_forms", "navigate"):
                    registry.grant(agent["id"], other, "ask" if asked == other else "allow")
                state = self.resolving(approver, asked)
                arguments = self.here_arguments(tool)
                if tool == "type" and question == "submit_forms":
                    arguments["submit"] = True
                if question == "enter":
                    arguments["text"] = "x\n"
                with (
                    mock.patch.object(tools.Bridge, "_earlier_forms", return_value=None),
                    mock.patch.object(tools.Bridge, "_forms_prepare"),
                    mock.patch.object(tools.Bridge, "_call_fn", return_value=info) as called,
                ):
                    result = bridge.call(tool, arguments)
                self.assertTrue(result["isError"], result)
                self.assertTrue(state["local"], approver.asked)  # the question was asked
                self.assertEqual(approver.asked[-1][0], asked)  # and nothing after it
                self.assertFalse(self.ACTS & set(commands), commands)
                self.read.assert_not_called()
                self.assertFalse([c for c in called.call_args_list if c.args[1] != tools.INSPECT_FN], called.call_args_list)
                entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
                self.assertEqual((entry["capability"].split(",")[-1], entry["reason"]), ("local_resources", "grant"))

    def test_a_call_that_asks_nothing_looks_its_tab_up_once(self):
        # I7: without a question, the tab's host is looked up once, as before.
        _agent, bridge, approver, _target, _commands = self.opened(level="autonomous")
        state = self.resolving(approver, "read_pages")
        self.assertFalse(bridge.call("page_read", {"tab": "w1"})["isError"])
        self.assertEqual((approver.asked, state["lookups"]), ([], [("mail.example", 0)]))

    def test_a_profiles_tab_is_not_looked_up_before_its_question_is_answered(self):
        # Finding 2: the host of a profile's tab, and of where navigate takes it, went to this computer's resolver
        # before the person answered the profile's question (Assisted asks about the signed-in session), even when
        # they said no; the profile may use encrypted DNS. The base entered the profile first.
        for tool in (*self.HERE, "navigate"):
            for answer in ("deny", "once"):
                with self.subTest(tool=tool, answer=answer):
                    agent, bridge, approver, _target, _commands = self.opened(level="assisted", answer=answer)
                    for capability in ("interact", "execute_js", "cookies_storage", "screenshots"):
                        registry.grant(agent["id"], capability, "allow")
                    state = self.resolving(approver, "authenticated_sessions")
                    arguments = self.here_arguments(tool)
                    with mock.patch.object(tools.Bridge, "_call_fn", return_value={"connected": True, "editable": True}):
                        bridge.call(tool, arguments)
                    self.assertEqual(approver.asked[0], ("authenticated_sessions", "https://mail.example"))
                    if answer == "deny":
                        self.assertEqual(state["lookups"], [])
                    else:
                        self.assertTrue(state["lookups"])
                        self.assertNotIn(0, [asked for _host, asked in state["lookups"]], state["lookups"])

    def test_a_tab_already_in_reader_view_is_closed_after_its_question(self):
        # Finding 3: tab_close on a tab at Reader View, or at an address agents do not act on, asked navigate and,
        # after a yes, said the tab had moved, though it had not; the base closed it, as it does with navigate allowed.
        for url in (self.READER, "data:text/html,hi"):
            with self.subTest(url=url):
                agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="once", url=url)
                registry.grant(agent["id"], "navigate", "ask")
                result = bridge.call("tab_close", {"tab": "w1"})
                self.assertFalse(result["isError"], result)
                self.assertEqual([c for c, _ in approver.asked], ["navigate"])
                self.assertIn("browsingContext.close", commands)
        # Moved into Reader View while the question was open: not closed, as before.
        agent, bridge, approver, _target, commands = self.opened(level="autonomous", answer="once")
        registry.grant(agent["id"], "navigate", "ask")
        self.move_on(approver, "navigate", self.READER)
        result = bridge.call("tab_close", {"tab": "w1"})
        self.assertTrue(result["isError"], result)
        self.assertNotIn("browsingContext.close", commands)

    def test_a_profile_given_back_during_the_lookup_is_not_refused(self):
        # Finding 4: a new tab for a site routed to a profile taken from the agent, given back while the address was
        # looked up, was refused as not given, from the agent's record read before the lookup.
        agent, _ = registry.add("r-2", "other", "assisted")
        profiles = [{"label": "Trabalho", "path": self.PATH}]
        registry.set_profiles(agent["id"], profiles)
        registry.set_routes(agent["id"], [{"site": "mail.example", "profile": "Trabalho"}])
        registry.set_profiles(agent["id"], [])  # the route stays
        registry.grant(agent["id"], "navigate", "ask")
        approver = Approve("deny")
        bridge = tools.Bridge(agent["id"], "s-1", approver=approver)

        def given_back(_host):
            registry.set_profiles(agent["id"], profiles)
            return False

        with mock.patch.object(policy, "_resolves_locally", side_effect=given_back):
            result = bridge.call("tab_new", {"url": "https://mail.example/"})
        self.assertTrue(result["isError"], result)
        self.assertEqual(approver.asked, [("navigate", "https://mail.example")])
        entry = json.loads(audit.audit_path().read_text().splitlines()[-1])
        self.assertEqual((entry["capability"], entry["reason"]), ("navigate", "denied"))


class LocalRequestsTest(Home):
    """R29 (LESIS 83a648d8): an agent without local_resources has every request of its engines held, and one
    to this computer or the local network failed before it is sent, a redirect hop included."""

    def engine(self):
        connection, commands, handlers = mock.Mock(), [], {}

        def command(method, params=None, **_k):
            commands.append((method, params))
            return {"intercept": f"intercept-{len(commands)}"} if method == "network.addIntercept" else {}

        connection.command.side_effect = command
        connection.on.side_effect = handlers.__setitem__
        return connection, commands, handlers

    def bridge(self, mode: str = "ask"):
        agent, _ = registry.add("net", "other", "autonomous")
        registry.grant(agent["id"], "local_resources", mode)
        return agent, tools.Bridge(agent["id"], "s-1", approver=registry.Approver())

    def test_policy_reads_the_hosts_the_engine_sends_requests_to(self):
        for host in ("127.0.0.1", "localhost", "app.localhost", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1",
                     "[::1]", "fd00::1", "printer.local", "0.0.0.0", "127.1", "0x7f000001"):  # fmt: skip  # noqa: S104 (a host the test reads, not one it binds)
            self.assertTrue(policy.local_host(host, resolve=False), host)
        self.assertFalse(policy.local_host("93.184.215.14", resolve=False))
        self.assertFalse(policy.local_host("2a00:1450:4001::200e", resolve=False))
        with mock.patch.object(policy.socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("10.1.2.3", 0))]):
            self.assertTrue(policy.local_host("intranet.example.com"))
        with mock.patch.object(policy.socket, "getaddrinfo", side_effect=OSError("no answer")):
            self.assertTrue(policy.local_host("unknown.example"))  # closed when this process cannot tell
        with mock.patch.object(policy.socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("93.184.215.14", 0))]):
            self.assertFalse(policy.local_host("example.org"))

    def test_the_intercept_follows_the_permission(self):
        agent, bridge = self.bridge("ask")
        connection, commands, handlers = self.engine()
        bridge.workspace = mock.Mock(bidi=connection)
        bridge._sync_network()
        bridge._sync_network()  # once for the engine, not once a call
        self.assertEqual(
            [m for m, _ in commands], ["session.subscribe", "network.addIntercept"]
        )  # fmt: skip
        self.assertEqual(commands[1][1], {"phases": ["beforeRequestSent"]})
        self.assertIn("network.beforeRequestSent", handlers)
        self.addCleanup(bridge.close)
        handlers["network.beforeRequestSent"]({"isBlocked": True, "request": {"request": "r9", "url": "http://10.0.0.1/"}})
        self.assertTrue(wait_for(lambda: ("network.failRequest", {"request": "r9"}) in commands))  # what the engine sends
        commands.remove(("network.failRequest", {"request": "r9"}))
        registry.grant(agent["id"], "local_resources", "allow")  # the user allows it: nothing is held
        bridge._sync_network()
        self.assertEqual(commands[-1], ("network.removeIntercept", {"intercept": "intercept-2"}))
        registry.grant(agent["id"], "local_resources", "block")
        bridge._sync_network()  # held again, with the handler already set
        self.assertEqual([m for m, _ in commands].count("session.subscribe"), 1)
        self.assertEqual([m for m, _ in commands].count("network.addIntercept"), 2)
        # A new connection (the engine ended and another started) gets its own, before its first navigation.
        second, commands, _ = self.engine()
        bridge.workspace = mock.Mock(bidi=second)
        bridge.workspace.start.return_value = second
        self.assertIs(bridge.bidi(), second)
        self.assertEqual([m for m, _ in commands if m.startswith(("network.", "session."))],
                         ["session.subscribe", "network.addIntercept"])  # fmt: skip

    def test_a_local_request_fails_before_it_leaves_and_a_public_one_goes_on(self):
        _agent, bridge = self.bridge("ask")
        connection, commands, _ = self.engine()
        public = [(0, 0, 0, "", ("93.184.215.14", 0))]

        def held(url: str, request: str = "r1") -> tuple:
            commands.clear()
            bridge._decide(connection, {"request": request, "url": url})
            return commands[-1] if commands else None

        with mock.patch.object(policy.socket, "getaddrinfo", return_value=public) as resolve:
            self.assertEqual(held("https://example.org/a"), ("network.continueRequest", {"request": "r1"}))
            held("https://example.org/b")
            self.assertEqual(resolve.call_count, 1)  # a name's answer is kept for the requests that follow
            for url in ("http://127.0.0.1:8080/hit", "http://192.168.1.1/reboot", "http://[::1]/", "ws://localhost:9/",
                        "http://printer.local/", "file:///etc/passwd", "http://user@/", "http://[64:ff9b::c0a8:101]/",
                        "http://[::ffff:192.168.1.1]/"):  # fmt: skip
                self.assertEqual(held(url, "r2"), ("network.failRequest", {"request": "r2"}), url)
            for url in ("data:text/plain,a", "blob:https://example.org/1", "about:blank", "http://[64:ff9b::5db8:d70e]/"):
                self.assertEqual(held(url)[0], "network.continueRequest", url)
            for url in ("jar:http://192.168.1.1/a.zip!/x", "view-source:http://10.0.0.1/", "gopher://10.0.0.1/", "x-new:1"):
                self.assertEqual(held(url)[0], "network.failRequest", url)  # a scheme not known to be hostless is closed
            # The place the current call was allowed (asked, and the user said yes) is sent on, only it: its
            # WebSocket and the engine's upgrade of it to https are the same place; another port is not.
            bridge._local_ok = {("127.0.0.1", 8080), ("192.168.1.1", 80)}
            self.assertEqual(held("http://127.0.0.1:8080/next")[0], "network.continueRequest")
            self.assertEqual(held("ws://127.0.0.1:8080/socket")[0], "network.continueRequest")
            self.assertEqual(held("https://192.168.1.1/upgraded")[0], "network.continueRequest")
            self.assertEqual(held("http://127.0.0.1:2375/containers")[0], "network.failRequest")
            self.assertEqual(held("http://10.0.0.9/other")[0], "network.failRequest")
            self.assertIsNone(tools.Bridge._request_place("http://127.0.0.1:99999/"))  # no place: refused, no error
            # Codex review: an approval is matched as the engine writes the host it sends the request to.
            same = (("http://127.1/", "http://127.0.0.1/"), ("http://0x7f000001:8080/", "http://127.0.0.1:8080/x"),
                    ("http://[0:0:0:0:0:0:0:1]/", "http://[::1]/"), ("http://LOCALHOST./", "http://localhost/"))  # fmt: skip
            for asked, sent in same:
                bridge._local_ok = {tools.Bridge._request_place(asked)}
                self.assertEqual(held(sent)[0], "network.continueRequest", (asked, sent))
            # Anything unexpected fails the request: closed, not open.
            with mock.patch.object(tools.Bridge, "_request_allowed", side_effect=RuntimeError("bug")):
                self.assertEqual(held("https://example.org/a")[0], "network.failRequest")
        refused = [json.loads(line) for line in audit.audit_path().read_text().splitlines()]
        refused = [e["target"] for e in refused if e.get("reason") == "local-request"]
        self.assertEqual(refused.count("http://192.168.1.1"), 1)  # once per place, not once per request
        self.assertNotIn("/reboot", audit.audit_path().read_text())  # the place, never the path

    def test_held_requests_are_decided_off_the_connections_thread(self):
        # Events reach the handler in order on one thread: a request is decided on a pool, so a name that is
        # slow to resolve holds only its own requests, and one the intercept does not hold is left alone.
        _agent, bridge = self.bridge("ask")
        self.addCleanup(bridge.close)
        connection, commands, _ = self.engine()
        slow, released = threading.Event(), threading.Event()

        def resolve(host, *_a, **_k):
            if host == "slow.example":
                slow.set()
                released.wait(10)
            return [(0, 0, 0, "", ("93.184.215.14", 0))]

        with mock.patch.object(policy.socket, "getaddrinfo", side_effect=resolve):
            bridge._on_request(connection, {"isBlocked": True, "request": {"request": "r1", "url": "https://slow.example/"}})
            self.assertTrue(slow.wait(5))
            bridge._on_request(connection, {"isBlocked": True, "request": {"request": "r2", "url": "http://10.0.0.1/"}})
            bridge._on_request(connection, {"isBlocked": False, "request": {"request": "r3", "url": "http://10.0.0.2/"}})
            self.assertTrue(wait_for(lambda: ("network.failRequest", {"request": "r2"}) in commands))
            released.set()
            self.assertTrue(wait_for(lambda: ("network.continueRequest", {"request": "r1"}) in commands))
        self.assertNotIn("r3", json.dumps(commands))

    def test_a_name_that_does_not_answer_in_time_fails_its_request_and_its_late_answer_is_kept(self):
        _agent, bridge = self.bridge("ask")
        connection, commands, _ = self.engine()
        asked = []

        def resolve(host, *_a, **_k):
            asked.append(host)
            time.sleep(0.4)
            return [(0, 0, 0, "", ("93.184.215.14", 0))]

        with (
            mock.patch.object(tools, "LOCAL_LOOKUP_TIMEOUT", 0.1),
            mock.patch.object(policy.socket, "getaddrinfo", side_effect=resolve),
        ):
            bridge._decide(connection, {"request": "r1", "url": "https://late.example/"})
            bridge._decide(connection, {"request": "r2", "url": "https://late.example/b"})  # the same lookup, not another
            self.assertEqual(commands, [("network.failRequest", {"request": "r1"}), ("network.failRequest", {"request": "r2"})])
            self.assertTrue(wait_for(lambda: "late.example" in bridge._local_hosts))
            bridge._decide(connection, {"request": "r3", "url": "https://late.example/c"})
        self.assertEqual(commands[-1], ("network.continueRequest", {"request": "r3"}))
        self.assertEqual(asked, ["late.example"])

    def test_while_many_names_are_out_a_new_one_counts_as_local(self):
        # Review: a page that asks for many names that never answer must not make the Bridge wait for each;
        # past the limit a new name fails at once (closed), and an address or a known name is not held up.
        _agent, bridge = self.bridge("ask")
        connection, commands, _ = self.engine()
        released = threading.Event()
        self.addCleanup(released.set)

        def resolve(host, *_a, **_k):
            if host.startswith("hang"):
                released.wait(10)
            return [(0, 0, 0, "", ("93.184.215.14", 0))]

        with (
            mock.patch.object(tools, "LOOKUPS_AT_ONCE", 2),
            mock.patch.object(tools, "LOCAL_LOOKUP_TIMEOUT", 0.05),
            mock.patch.object(policy.socket, "getaddrinfo", side_effect=resolve),
        ):
            bridge._local_hosts["known.example"] = (time.monotonic(), False)
            for name in ("hang1", "hang2"):
                bridge._decide(connection, {"request": name, "url": f"https://{name}.example/"})
            started = time.monotonic()
            bridge._decide(connection, {"request": "new", "url": "https://new.example/"})
            bridge._decide(connection, {"request": "known", "url": "https://known.example/"})
            bridge._decide(connection, {"request": "ip", "url": "https://93.184.215.14/"})
            self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(commands[-3:], [("network.failRequest", {"request": "new"}),
                                         ("network.continueRequest", {"request": "known"}),
                                         ("network.continueRequest", {"request": "ip"})])  # fmt: skip
        entries = [json.loads(line) for line in audit.audit_path().read_text().splitlines()]
        reasons = [e["reason"] for e in entries if e.get("tool") == "network"]
        self.assertEqual(reasons, ["local-requests-busy"])  # one line, not a public site taken for a local one

    def test_the_activity_lists_a_few_refused_places_then_says_there_were_more(self):
        # Review: a page that tries a whole network (or a port scan of this computer) wrote a line per
        # place, and pushed the agent's own actions out of the activity (audit A7 again).
        _agent, bridge = self.bridge("ask")
        self.addCleanup(bridge.close)
        connection, _, _ = self.engine()
        for port in range(1, 200):
            bridge._decide(connection, {"request": f"r{port}", "url": f"http://127.0.0.1:{port}/"})
        entries = [json.loads(line) for line in audit.audit_path().read_text().splitlines()]
        reasons = [e["reason"] for e in entries if e.get("tool") == "network"]
        self.assertEqual(reasons, ["local-request"] * tools.LOCAL_REFUSED_NOTED + ["local-requests-more"])

    def test_an_answer_for_the_session_lets_that_place_through_and_no_other(self):
        # "Allow until the agent disconnects", asked for http://127.0.0.1:8080 in the AI Workspace, is for that host
        # and port there, from the moment it is given (requests already held follow it), until the session ends. Not
        # the rest of this computer and the local network, not file:, not another profile: those are asked about.
        agent, _ = registry.add("session-net", "other", "autonomous")
        registry.grant(agent["id"], "local_resources", "ask")
        bridge = tools.Bridge(agent["id"], "s-1", approver=Approve("session"))
        self.addCleanup(bridge.close)
        connection, commands, _ = self.engine()
        bridge.workspace = mock.Mock(bidi=connection)
        shell = bridge._local_path()
        bridge._sync_network()
        self.assertFalse(bridge._request_allowed("http://127.0.0.1:8080/other", label=""))
        bridge.require("local_resources", "http://127.0.0.1:8080/app", checked=[], place="")
        self.assertNotIn("network.removeIntercept", [m for m, _ in commands])  # the rest stays held
        bridge._local_ok = set()  # the call ended
        self.assertTrue(bridge._request_allowed("http://127.0.0.1:8080/other", label=""))
        self.assertTrue(bridge._request_allowed("https://127.0.0.1:8080/other", label=""))
        for url in ("http://127.0.0.1:9090/", "http://192.168.1.1/admin", "http://169.254.169.254/latest/meta-data/",
                    "file:///home/u/.ssh/id_ed25519"):  # fmt: skip
            self.assertFalse(bridge._request_allowed(url, label=""), url)
        self.assertFalse(bridge._request_allowed("http://127.0.0.1:8080/other", label="Trabalho"))  # not where it was given
        self.assertEqual(json.loads(shell.read_text()), {"v": 1, "all": False, "places": [["127.0.0.1", 8080]]})
        later = Approve("deny")
        bridge.approver = later
        bridge.require("local_resources", "http://127.0.0.1:8080/", checked=[], place="")  # not asked again
        for url in ("http://192.168.1.1/", "file:///home/u/.ssh/id_ed25519"):
            with self.assertRaises(tools.Denied):
                bridge.require("local_resources", url, checked=[], place="")
        self.assertEqual(later.asked, [("local_resources", "http://192.168.1.1"), ("local_resources", "file:")])

    def test_what_the_user_allowed_for_a_call_ends_with_it(self):
        # "Ask": the user is asked for the address the agent opens; its requests go on during that call only.
        agent, _ = registry.add("ask-net", "other", "autonomous")
        registry.grant(agent["id"], "local_resources", "ask")
        bridge = tools.Bridge(agent["id"], "s-1", approver=Approve("once"))
        self.addCleanup(bridge.close)
        bridge.require("local_resources", "http://127.0.0.1:8080/app", checked=[])
        self.assertEqual(bridge._local_ok, {("127.0.0.1", 8080)})
        during = []

        def tabs_list(_self, args, cancel, checked):
            _self.require("local_resources", "http://127.0.0.1:8080/app", checked=checked)
            during.append(set(_self._local_ok))
            return _self._ok({"tabs": []}), None

        with mock.patch.object(tools.Bridge, "_t_tabs_list", tabs_list):
            self.assertFalse(bridge.call("tabs_list", {})["isError"])
        self.assertEqual(during, [{("127.0.0.1", 8080)}])
        self.assertEqual(bridge._local_ok, set())  # a page left open afterwards reaches it no more

    def test_the_shell_reads_which_local_places_are_allowed_now(self):
        # #243: the engine connects to its own DNS answer, which the Bridge does not see. The Shell in each engine
        # checks that address against this file before it shows the page; it must say what the Bridge allows, and
        # no more: nothing before a call, the place a call was allowed by asking only during that call, and every
        # place while local_resources is allowed without asking.
        from nulavio_launcher import paths

        agent, _ = registry.add("shell-net", "other", "autonomous")
        registry.grant(agent["id"], "local_resources", "ask")
        bridge = tools.Bridge(agent["id"], "s-1", approver=Approve("once"))
        self.addCleanup(bridge.close)
        folder = paths.state_home() / "ai" / "local"
        folder.mkdir(parents=True)
        left = folder / "999999999-0123456789abcdef.json"  # by a Bridge that ended without closing
        left.write_text('{"v": 1, "all": true, "places": []}')
        path = bridge._local_path()
        self.assertFalse(left.exists())
        self.assertEqual(path.parent, folder)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)

        def read() -> dict:
            return json.loads(path.read_text())

        self.assertEqual(read(), {"v": 1, "all": False, "places": []})  # closed before any engine starts
        self.assertEqual(bridge._workspace().local_file, path)  # the engine is told where it is
        during = []

        def tabs_list(_self, args, cancel, checked):
            _self.require("local_resources", "http://127.0.0.1:8080/app", checked=checked)
            during.append(read())
            return _self._ok({"tabs": []}), None

        with mock.patch.object(tools.Bridge, "_t_tabs_list", tabs_list):
            self.assertFalse(bridge.call("tabs_list", {})["isError"])
        self.assertEqual(during, [{"v": 1, "all": False, "places": [["127.0.0.1", 8080]]}])
        self.assertEqual(read()["places"], [])  # the call ended
        registry.grant(agent["id"], "local_resources", "allow")
        bridge._sync_network()
        self.assertEqual(read(), {"v": 1, "all": True, "places": []})
        registry.grant(agent["id"], "local_resources", "block")
        bridge._sync_network()
        self.assertEqual(read(), {"v": 1, "all": False, "places": []})
        # A file that cannot be written is removed, and the Shell then shows no local page at all.
        registry.grant(agent["id"], "local_resources", "allow")
        with mock.patch.object(tools.paths, "write_private_file", side_effect=OSError("disk full")):
            bridge._sync_network()
        self.assertFalse(path.exists())
        bridge._sync_network()
        self.assertTrue(read()["all"])
        # One that can be neither written nor removed still says "all": the engines that read it are closed, and the
        # next engine is given a new file that says what is allowed now.
        workspace = mock.Mock(bidi=mock.Mock())
        bridge.workspace = workspace
        registry.grant(agent["id"], "local_resources", "block")
        real_unlink = Path.unlink

        def unlink(self, *args, **kwargs):
            if self == path:
                raise OSError("read-only")
            return real_unlink(self, *args, **kwargs)

        with (
            mock.patch.object(tools.paths, "write_private_file", side_effect=OSError("disk full")),
            mock.patch.object(Path, "unlink", unlink),
        ):
            bridge._sync_network()
        workspace.stop.assert_called_once()
        self.assertIsNone(bridge.workspace)
        self.assertTrue(read()["all"])  # still there, and no engine reads it
        fresh = bridge._local_path()
        self.assertNotEqual(fresh, path)
        self.assertEqual(json.loads(fresh.read_text()), {"v": 1, "all": False, "places": []})
        bridge.close()
        self.assertFalse(fresh.exists())
        path.unlink()


class WorkspaceTest(Home):
    def test_engine_ends_with_the_bridge(self):
        from nulavio_launcher.ai import workspace

        with mock.patch.object(workspace.shutil, "which", return_value="/usr/bin/setpriv") as which:
            self.assertEqual(workspace.die_with_parent(), ["/usr/bin/setpriv", "--pdeathsig", "TERM", "--"])
        self.assertEqual(which.call_args.kwargs["path"], "/usr/bin:/bin")  # never a setpriv from the user's PATH
        with mock.patch.object(workspace.shutil, "which", return_value=None):
            self.assertEqual(workspace.die_with_parent(), [])

    def test_the_window_lock_is_in_the_engine_environment(self):
        # Audit A6: the lock rested on a pref an agent with raw automation could reset in about:config.
        from nulavio_launcher.ai import workspace

        class Started(Exception):
            pass

        seen = {}

        def popen(_command, env, **_kwargs):
            seen.update(env)
            raise Started

        engine = mock.Mock(path=Path("/opt/engine/nulavio"), vendor="Nulavio")  # the Bridge drives only Nulavio's
        targets = (
            (Workspace("ag-1", engine=engine, headless=True), "ag-1"),
            (
                workspace.ProfileTarget("ag-2", "Trabalho", self.home / "p", downloads_dir=self.home, engine=engine),
                f"ag-2:{os.getpid()}",
            ),
        )
        (self.home / "p").mkdir(parents=True)
        for target, marker in targets:
            seen.clear()
            with mock.patch.object(workspace.subprocess, "Popen", side_effect=popen), self.assertRaises(Started):
                target.start()
            self.assertEqual(seen[workspace.WORKSPACE_ENV], marker)
            user_js = (target.profile_dir / "user.js").read_text()
            self.assertIn(f'user_pref("nulavio.ai.workspace", "{marker}");', user_js)
        root = Path(__file__).resolve().parents[2]
        shell = (root / "browser" / "shell" / "modules" / "NulavioAI.sys.mjs").read_text(encoding="utf-8")
        self.assertIn(f'const WORKSPACE_ENV = "{workspace.WORKSPACE_ENV}";', shell)
        self.assertIn("const value = fromEnv || Services.prefs.getStringPref(WORKSPACE_PREF", shell)

    def test_the_bar_takes_only_its_own_words_and_a_live_bridge(self):
        # Audit A12: markWorkspace kept any texts it was given. A13: a reused PID kept a window "driven".
        root = Path(__file__).resolve().parents[2]
        shell = (root / "browser" / "shell" / "modules" / "NulavioAI.sys.mjs").read_text(encoding="utf-8")
        built = (root / "browser" / "shell" / "lib" / "agent-texts.js").read_text(encoding="utf-8")
        keys = re.search(r"const BAR_TEXT_KEYS = \[([^\]]*)\]", shell)[1]
        self.assertEqual(sorted(re.findall(r'"(\w+)"', keys)), sorted(re.findall(r"^\s+(\w+):", built, re.M)))
        self.assertIn("texts: clean", shell)
        self.assertIn("if (pid && !(fromEnv && ", shell)  # a mark left in prefs.js by an ended session

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
        # #243: the engine refuses a public page's requests to this computer and the local network itself, a
        # pop-up's included, with no prompt (LESIS 929cb094: what the Bridge's own DNS lookup cannot see).
        lna = (
            ("network.lna.blocking", "true"),
            ("network.lna.allow_top_level_navigation", "false"),
            ("permissions.default.local-network", "2"),
            ("permissions.default.loopback-network", "2"),
        )
        for name, value in lna:
            self.assertIn(f'user_pref("{name}", {value});', user_js)

    def test_the_engine_is_used_only_once_its_shell_checks_local_addresses(self):
        # #243: what the agent opens is checked by the Shell (workspace.GUARD_READY), not by the engine's Local Network
        # Access. The Bridge gets the engine only once the Shell says its check is on; a file left from an earlier run
        # counts for nothing. The path of the Bridge's file of allowed places is in the engine's environment.
        from nulavio_launcher.ai import workspace

        seen: dict = {}
        ready = {"write": False}

        def popen(_command, env, **_kwargs):
            seen.update(env)
            (ws.profile_dir / "WebDriverBiDiServer.json").write_text('{"ws_port": 1234}')
            if ready["write"]:
                (ws.profile_dir / workspace.GUARD_READY).write_text("1")
            return mock.Mock(**{"poll.return_value": None})

        ws = Workspace("ag-1", engine=mock.Mock(path=Path("/opt/engine/nulavio"), vendor="Nulavio"), headless=True)
        ws.local_file = self.home / "local.json"
        ws.profile_dir.mkdir(parents=True)
        (ws.profile_dir / workspace.GUARD_READY).write_text("1")  # from an earlier run
        with mock.patch.object(workspace.subprocess, "Popen", side_effect=popen), mock.patch.object(workspace, "Bidi") as bidi:
            with self.assertRaises(workspace.WorkspaceError):
                ws.start(timeout=1)
            bidi.assert_not_called()
            self.assertEqual(seen[workspace.LOCAL_ENV], str(ws.local_file))
            ready["write"] = True
            self.assertIs(ws.start(timeout=5), bidi.return_value)
            ws.bidi = None
            # Any other browser is refused before it starts (#563, engine.require_nulavio)...
            ready["write"] = False
            ws.engine = mock.Mock(path=Path("/usr/lib64/firefox/firefox"), vendor="Mozilla", label="Mozilla Firefox 160.0")
            seen.clear()
            with mock.patch.dict(os.environ, {"NULAVIO_TEST_DISTRIBUTION_FIREFOX": ""}), self.assertRaises(EngineError):
                ws.start(timeout=5)
            self.assertEqual(seen, {})  # never started
            # ...except the test harness's distribution Firefox in a source checkout, which has no Shell to wait for.
            with mock.patch.dict(os.environ, {"NULAVIO_TEST_DISTRIBUTION_FIREFOX": "1"}):
                self.assertIs(ws.start(timeout=5), bidi.return_value)

    def test_the_engine_refuses_a_local_page_its_driver_opens_before_sending_it(self):
        # #561: patch 0015 keys on the variable the Bridge sets and reads the file the Shell reads, with the Shell's
        # limits. It checks only the top-level loads of the engine's driver (the system principal), and ends a refusal
        # as the Shell's own does. Of the engine's code it changes two lines, and loosens no check. What it does is
        # tests/integration/test_ai_bridge.py test_33, against a build of this tree.
        from nulavio_launcher.ai import workspace

        root = Path(__file__).resolve().parents[2]
        name = "0015-lna-an-agents-engine-refuses-a-local-page-before-sending.patch"
        self.assertIn(name, (root / "browser" / "patches" / "series").read_text(encoding="utf-8").split())
        patch = (root / "browser" / "patches" / name).read_text(encoding="utf-8")
        http = "netwerk/protocol/http/"
        self.assertEqual(
            set(re.findall(r"(?m)^\+\+\+ b/(\S+)", patch)),
            {http + "NulavioAgentLocalAccess.cpp", http + "NulavioAgentLocalAccess.h", http + "moz.build",
             http + "nsHttpChannel.cpp"},
        )  # fmt: skip
        self.assertIn(f'kWorkspaceEnv[] = "{workspace.WORKSPACE_ENV}";', patch)
        self.assertIn(f'kLocalEnv[] = "{workspace.LOCAL_ENV}";', patch)
        shell = (root / "browser" / "shell" / "modules" / "NulavioAgentNetwork.sys.mjs").read_text(encoding="utf-8")
        for ours, theirs in (("kMaxFileBytes", "MAX_FILE_BYTES"), ("kMaxPlaces", "MAX_PLACES")):
            value = re.search(rf"(?m)^const {theirs} = (\d+);", shell)[1]
            self.assertIn(f"+constexpr uint32_t {ours} = {value};", patch)
        self.assertIn("ExtContentPolicy::TYPE_DOCUMENT", patch)
        self.assertIn("triggering->IsSystemPrincipal() && InAgentEngine()", patch)
        removed = [line[1:] for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(
            removed,
            ["  if (mLoadInfo && StaticPrefs::network_lna_allow_top_level_navigation()) {",
             "      UpdateLocalNetworkAccessPermissions(permissionKey);"],
        )  # fmt: skip
        # The driver's load is checked as a public page's request, and never granted by the top-level pref.
        self.assertIn("+    parentAddressSpace = nsILoadInfo::IPAddressSpace::Public;", patch)
        self.assertIn("StaticPrefs::network_lna_allow_top_level_navigation() &&\n+      !nulavioAgentDriverLoad) {", patch)
        # The refusal comes first in ProcessLNAActions, right after its transaction check, and ends as a blocked page;
        # the load goes on only when the Bridge's file allows its place.
        process = patch.split("return NS_ERROR_LOCAL_NETWORK_ACCESS_DENIED;\n   }\n", 1)[1].split("// Suspend to block", 1)[0]
        self.assertIn("+  if (nulavioAgentDriverLoad && !nulavio::AgentMayReach(mURI)) {", process)
        self.assertEqual(process.count("ContinueOnStartRequest1(NS_ERROR_BLOCKED_BY_POLICY)"), 2)

    def test_the_shell_reads_what_the_bridge_writes(self):
        # #243: the Shell's check (NulavioAgentNetwork.sys.mjs) and the Bridge name the same environment variables and
        # file, and the Shell pins the same Local Network Access values in an agent's engine as the AI Workspace has.
        from nulavio_launcher.ai import workspace

        module = Path(__file__).resolve().parents[2] / "browser" / "shell" / "modules" / "NulavioAgentNetwork.sys.mjs"
        text = module.read_text(encoding="utf-8")
        for name, value in (("WORKSPACE_ENV", workspace.WORKSPACE_ENV), ("LOCAL_ENV", workspace.LOCAL_ENV),
                            ("READY_FILE", workspace.GUARD_READY)):  # fmt: skip
            self.assertIn(f'const {name} = "{value}";', text)
        listed = text.split("LOCAL_NETWORK_PREFS", 1)[1].split("]);", 1)[0]
        pinned = dict(re.findall(r'\["([\w.\-]+)", (true|false|\d+)\]', listed))
        lna = {k: json.dumps(v) for k, v in WORKSPACE_PREFS.items() if k.startswith(("network.lna.", "permissions.default."))}
        self.assertEqual(pinned, lna)

    def test_the_engine_ignores_a_sites_saved_local_network_permission_where_the_bridge_started_it(self):
        # #570: patch 0014 keys on the variable the Bridge sets and the Shell reads, and in such an engine it skips the
        # site's saved allow (its saved deny still applies) and refuses before anything the prompt code would grant.
        # What it does is tests/integration/test_ai_bridge.py test_32, against a build of this tree.
        from nulavio_launcher.ai import workspace

        root = Path(__file__).resolve().parents[2]
        name = "0014-lna-an-agents-engine-ignores-a-sites-saved-local-network-permission.patch"
        series = (root / "browser" / "patches" / "series").read_text(encoding="utf-8").split()
        self.assertIn(name, series)
        patch = (root / "browser" / "patches" / name).read_text(encoding="utf-8")
        self.assertEqual(
            set(re.findall(r"(?m)^\+\+\+ b/(\S+)", patch)),
            {"netwerk/base/LNAPermissionRequest.h", "netwerk/base/LNAPermissionRequest.cpp",
             "netwerk/protocol/http/nsHttpChannel.cpp"},
        )  # fmt: skip
        self.assertIn(f'PR_GetEnv("{workspace.WORKSPACE_ENV}")', patch)
        removed = [line[1:] for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(removed, ["  if (nsContentUtils::IsExactSitePermAllow(mLoadInfo->TriggeringPrincipal(),"])
        # The driver's own loads carry the system principal, which the permission manager allows everything: they
        # are granted at this step as before (test_27 shows they are still sent, and the Shell checks their pages).
        self.assertIn(
            "+  if ((!InNulavioAgentEngine() ||\n+       mLoadInfo->TriggeringPrincipal()->IsSystemPrincipal()) &&\n"
            "+      nsContentUtils::IsExactSitePermAllow(mLoadInfo->TriggeringPrincipal(),",
            patch,
        )
        self.assertNotIn("IsExactSitePermDeny", "".join(removed))  # a saved deny keeps refusing
        request = patch.split("LNAPermissionRequest::RequestPermission() {", 1)[1].split("// Enforce Permissions Policy", 1)[0]
        self.assertIn("+  if (InNulavioAgentEngine()) {\n+    return Cancel();\n+  }", request)

    def test_a_raw_marker_left_by_an_earlier_version_is_deleted(self):
        """#463: the marker the window read while raw automation was on is not written any more; one left in a
        workspace's profile by an earlier version goes when the workspace starts."""
        agent, _ = registry.add("raw", "other", "autonomous")
        ws = Workspace(agent["id"], engine=mock.Mock(path=Path("/x")))
        (ws.profile_dir).mkdir(parents=True, exist_ok=True)
        (ws.profile_dir / OLD_RAW_MARKER).write_text("{}")
        ws._write_prefs()
        self.assertFalse((ws.profile_dir / OLD_RAW_MARKER).exists())
        self.assertFalse(hasattr(ws, "mark_raw"))

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

    # What the engine leaves in prefs.js after a session: it loads user.js as user values and saves them (#639).
    ENGINE_PREFS = (
        "// Mozilla User Preferences\n"
        "\n"
        'user_pref("browser.startup.page", 3);\n'
        'user_pref("nulavio.ai.target", "profile");\n'
        'user_pref("nulavio.ai.target.label", "Trabalho \\"casa\\" \\u00e7");\n'
        'user_pref("nulavio.ai.workspace", "ag-1:4242");\n'
        'user_pref("privacy.sanitize.pending", "[]");\n'
        'user_pref("remote.prefs.recommended", false);\n'
    )
    KEPT_PREFS = (
        '// Mozilla User Preferences\n\nuser_pref("browser.startup.page", 3);\nuser_pref("privacy.sanitize.pending", "[]");\n'
    )

    def test_a_session_leaves_none_of_its_prefs_in_prefs_js(self):
        """#639: the four values the engine saved from the temporary lines go from prefs.js when the session ends, so
        the Guard no longer finds remote.prefs.recommended and `nulavio run` starts the profile again."""
        from nulavio_launcher import guard

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")  # the engine, on its way out
        self.assertIn("remote.prefs.recommended", [f.pref for f in guard.audit(folder) if f.severity == "critical"])
        target._remove_temporary()
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.KEPT_PREFS)
        self.assertEqual((folder / "prefs.js").stat().st_mode & 0o777, 0o600)
        self.assertFalse((folder / "user.js").exists())
        self.assertEqual([f.pref for f in guard.audit(folder) if f.severity == "critical"], [])

    def test_the_next_session_clears_what_a_killed_one_left(self):
        """A bridge killed mid-session leaves the lines; the next session in that profile removes them, from user.js
        and prefs.js, before it writes its own."""
        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")._write_prefs()  # killed after this
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        target = ProfileTarget("ag-2", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.KEPT_PREFS)
        self.assertEqual((folder / "user.js").read_text().count("nulavio-ai-temporary"), 4)
        self.assertIn(f'"ag-2:{os.getpid()}"', (folder / "user.js").read_text())

    def test_prefs_js_is_left_alone_when_there_is_nothing_to_remove(self):
        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._remove_temporary()
        self.assertFalse((folder / "prefs.js").exists())  # none is made
        (folder / "prefs.js").write_text(self.KEPT_PREFS, encoding="utf-8")
        os.utime(folder / "prefs.js", (1, 1))
        target._remove_temporary()
        self.assertEqual((folder / "prefs.js").stat().st_mtime, 1)  # not rewritten

    def test_a_prefs_js_link_is_not_followed(self):
        """A prefs.js that is a link is neither read nor replaced, and the session still ends."""
        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        elsewhere = self.home / "elsewhere.js"
        elsewhere.write_text(self.ENGINE_PREFS, encoding="utf-8")
        (folder / "prefs.js").symlink_to(elsewhere)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        target.stop()
        self.assertTrue((folder / "prefs.js").is_symlink())
        self.assertEqual(elsewhere.read_text(encoding="utf-8"), self.ENGINE_PREFS)
        self.assertFalse((folder / "user.js").exists())

    def test_a_prefs_js_that_cannot_be_read_does_not_stop_the_session(self):
        """Another user's prefs.js with mode 0600 cannot be opened at all (PermissionError, before the owner check):
        it is left as it is, as one that is not the user's, and the agent's session still starts (review of #826)."""
        from nulavio_launcher import paths

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        real_read = paths.read_private_file

        def read(path):
            if Path(path).name == "prefs.js":
                raise PermissionError(13, "Permission denied", str(path))
            return real_read(path)

        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        with mock.patch.object(paths, "read_private_file", read):
            target._write_prefs()
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.ENGINE_PREFS)
        self.assertEqual((folder / "user.js").read_text().count("nulavio-ai-temporary"), 4)

    def test_a_launch_meanwhile_keeps_the_prefs_it_wrote_in_prefs_js(self):
        """`nulavio run` appends seed and pending prefs to prefs.js; the Bridge's clean-up reads and replaces that file.
        One waits for the other, so the launch's prefs are not lost to a copy read before them (review of #826)."""
        from nulavio_launcher import paths, profile
        from nulavio_launcher.ai import workspace

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        prof = profile.Profile(name="Trabalho", path=folder)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        me = threading.get_ident()
        real_read = paths.read_private_file
        launch: list[threading.Thread] = []

        def read(path):
            data = real_read(path)
            if threading.get_ident() == me and Path(path).name == "prefs.js" and not launch:
                # Between the Bridge's read and its replace, the launcher prepares the profile.
                launch.append(threading.Thread(target=profile._append_prefs_js, args=(prof, [("nulavio.test.pending", 7)])))
                launch[0].start()
                launch[0].join(0.5)
            return data

        with mock.patch.object(paths, "read_private_file", read):
            target._remove_temporary()
        launch[0].join(10)
        self.assertFalse(launch[0].is_alive())
        text = (folder / "prefs.js").read_text(encoding="utf-8")
        self.assertIn('user_pref("nulavio.test.pending", 7);', text)
        for name in workspace.TEMPORARY_PREFS:
            self.assertNotIn(f'"{name}"', text)

    def protected(self, folder: Path):
        """A profile with a Vault next to it (`<name>.vault/vault.json`): ProfileTarget then works under its state lock."""
        from nulavio_launcher.vault.storage import Container

        folder.with_name(folder.name + ".vault").mkdir()
        box = Container(folder)
        box.vault_path.write_text("{}", encoding="utf-8")
        return box

    def test_a_protected_profile_is_not_locked_before_its_prefs_are_gone(self):
        """The auto-lock watcher sees the agent's engine exit and unmounts the volume under the profile's state lock.
        stop() holds that lock from before the engine exits until the temporary prefs are out of prefs.js, so the
        watcher locks the profile only after that (review of #826)."""
        from nulavio_launcher.vault.storage import StorageError

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        box = self.protected(folder)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        watcher: list[str] = []

        def engine_exits():
            try:
                with box._state_lock(wait=0):
                    watcher.append("could lock")
            except StorageError as exc:
                watcher.append(exc.code)

        with mock.patch.object(Workspace, "stop", side_effect=engine_exits):
            target.stop()
        self.assertEqual(watcher, ["busy"])
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.KEPT_PREFS)
        with box._state_lock(wait=0):
            pass  # released once the session has ended

    def test_a_failed_start_stops_under_the_lock_it_already_holds(self):
        """Workspace.start() calls stop() when the engine's endpoint never came, while start() holds the state lock:
        stop() does not wait for that lock again. One that cannot be had never keeps the engine running."""
        from nulavio_launcher.vault.storage import StorageError

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        box = self.protected(folder)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        began = time.monotonic()
        with target._held():
            target.stop()
        self.assertLess(time.monotonic() - began, 5)
        self.assertFalse((folder / "user.js").exists())
        target._write_prefs()
        stopped = []
        held_elsewhere = mock.patch.object(type(box), "_state_lock", side_effect=StorageError("busy", "held"))
        with mock.patch.object(Workspace, "stop", side_effect=lambda: stopped.append(1)), held_elsewhere:
            target.stop()  # the lock is held elsewhere: the engine is stopped all the same
        self.assertEqual(stopped, [1])

    def test_a_vault_that_cannot_be_looked_at_still_stops_the_engine(self):
        """A profile's Vault folder that became unreadable (Path.exists raises PermissionError on Python 3.11): stop()
        stops the engine and clears the profile all the same (review 2 of #826)."""
        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        real_exists = Path.exists

        def exists(path, *args, **kwargs):
            if path.name == "vault.json":
                raise PermissionError(13, "Permission denied", str(path))
            return real_exists(path, *args, **kwargs)

        stopped = []
        with (
            mock.patch.object(Workspace, "stop", side_effect=lambda: stopped.append(1)),
            mock.patch.object(Path, "exists", exists),
        ):
            target.stop()
        self.assertEqual(stopped, [1])
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.KEPT_PREFS)

    def test_a_user_js_that_cannot_be_cleaned_still_lets_prefs_js_be(self):
        """A user.js saved in another encoding during the session: stop() leaves it, still takes the saved values out of
        prefs.js, and does not raise into the Bridge's shutdown of its other engines (review 2 of #826)."""
        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        (folder / "user.js").write_bytes((folder / "user.js").read_bytes() + b'user_pref("a.b", "\xe7");\n')
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        with mock.patch.object(Workspace, "stop"):
            target.stop()
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.KEPT_PREFS)
        self.assertIn(b"\xe7", (folder / "user.js").read_bytes())  # left as it is

    def test_a_prefs_js_that_cannot_be_replaced_does_not_stop_the_session(self):
        """Before the engine starts, a prefs.js that cannot be replaced (an immutable file) is left as it is, and the
        session starts with its user.js lines, as before #826 (review 2 of #826)."""
        from nulavio_launcher import paths

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        real_write = paths.write_private_file

        def write(path, data):
            if Path(path).name == "prefs.js":
                raise PermissionError(1, "Operation not permitted", str(path))
            return real_write(path, data)

        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        with mock.patch.object(paths, "write_private_file", write):
            target._write_prefs()
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.ENGINE_PREFS)
        self.assertEqual((folder / "user.js").read_text().count("nulavio-ai-temporary"), 4)

    def test_a_launch_stuck_on_prefs_js_does_not_hold_up_the_end_of_the_session(self):
        """`nulavio run` holding prefs_js_lock and never letting go: stop() waits a bounded time, leaves prefs.js for
        the next agent session (R36) and lets the Bridge go on (review 2 of #826)."""
        import fcntl

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        target = ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")
        target._write_prefs()
        (folder / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(fd, fcntl.LOCK_EX)  # the stuck launcher
        try:
            with mock.patch.object(Workspace, "stop"), mock.patch.object(ProfileTarget, "PREFS_WAIT", 0.2):
                stopping = threading.Thread(target=target.stop, daemon=True)
                stopping.start()
                stopping.join(5)
                self.assertFalse(stopping.is_alive())
        finally:
            os.close(fd)
        stopping.join(10)
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.ENGINE_PREFS)
        self.assertFalse((folder / "user.js").exists())

    def test_a_line_with_another_statement_is_left_in_prefs_js(self):
        """Only a line that is one temporary pref and nothing else goes: one that also sets another pref stays whole
        (review 2 of #826)."""
        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        mixed = 'user_pref("remote.prefs.recommended", false); user_pref("browser.startup.page", 3);\n'
        (folder / "prefs.js").write_text(self.ENGINE_PREFS + mixed, encoding="utf-8")
        ProfileTarget("ag-1", "Trabalho", folder, downloads_dir=self.home / "dl")._remove_temporary()
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.KEPT_PREFS + mixed)

    def test_a_launch_finds_the_profile_opened_while_it_waited_for_prefs_js(self):
        """`nulavio run` waits for prefs_js_lock behind the Bridge's clean-up; a profile an engine opened meanwhile is
        refused as in use, and its prefs.js is not replaced (review 2 of #826)."""
        from nulavio_launcher import profile

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        (folder / "prefs.js").write_text(self.KEPT_PREFS, encoding="utf-8")
        prof = profile.Profile(name="work", path=folder)
        with mock.patch.object(profile.Profile, "running_pid", return_value=4242), self.assertRaises(profile.ProfileInUse):
            profile._append_prefs_js(prof, [("nulavio.test.pending", 7)])
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.KEPT_PREFS)

    def test_a_launch_behind_a_stuck_prefs_js_change_is_refused_as_busy(self):
        """`nulavio run` waits a bounded time for prefs_js_lock, then stops with a retryable message and leaves
        prefs.js (and the pending prefs, saved only after it) as they were (review 3 of #826)."""
        import fcntl

        from nulavio_launcher import profile

        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        (folder / "prefs.js").write_text(self.KEPT_PREFS, encoding="utf-8")
        prof = profile.Profile(name="work", path=folder)
        outcome = []

        def launch():
            try:
                profile._append_prefs_js(prof, [("nulavio.test.pending", 7)])
                outcome.append("appended")
            except profile.ProfileError as exc:
                outcome.append(str(exc))

        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(fd, fcntl.LOCK_EX)  # a suspended launcher or Bridge
        try:
            with mock.patch.object(profile, "PREFS_JS_WAIT", 0.2):
                launching = threading.Thread(target=launch, daemon=True)
                launching.start()
                launching.join(5)
                self.assertFalse(launching.is_alive(), "nulavio run waited without end")
        finally:
            os.close(fd)
        launching.join(10)
        self.assertEqual(len(outcome), 1)
        self.assertIn("try again", outcome[0])
        self.assertEqual((folder / "prefs.js").read_text(encoding="utf-8"), self.KEPT_PREFS)

    def test_a_linked_profile_folder_shares_the_prefs_js_lock(self):
        """A profile given by a link to its folder takes the same lock as `nulavio run` on the folder itself, so the
        clean-up never puts back a copy from before that launch's change (review 3 of #826)."""
        import fcntl

        real = self.home / "profiles" / "work"
        real.mkdir(parents=True)
        link = self.home / "work-link"
        link.symlink_to(real)
        (real / "prefs.js").write_text(self.ENGINE_PREFS, encoding="utf-8")
        target = ProfileTarget("ag-1", "Trabalho", link, downloads_dir=self.home / "dl")
        target.wrote_prefs = True
        fd = os.open(real, os.O_RDONLY | os.O_DIRECTORY)
        fcntl.flock(fd, fcntl.LOCK_EX)  # `nulavio run` appending through the folder's own path
        try:
            with mock.patch.object(Workspace, "stop"), mock.patch.object(ProfileTarget, "PREFS_WAIT", 0.2):
                target.stop()
        finally:
            os.close(fd)
        self.assertEqual((real / "prefs.js").read_text(encoding="utf-8"), self.ENGINE_PREFS, "replaced without the lock")

    def test_a_target_whose_folder_has_no_name_still_stops(self):
        """stop() looks for a Vault next to the profile's folder; a grant with no folder name ("/") makes that lookup
        fail, and the engine is stopped and the Bridge goes on all the same (review 3 of #826)."""
        target = ProfileTarget("ag-1", "Root", Path("/"), downloads_dir=self.home / "dl")
        with mock.patch.object(Workspace, "stop") as stopped:
            target.stop()
        stopped.assert_called_once()

    def test_the_bridge_drives_only_the_nulavio_build(self):
        # The band and lock of an agent's window, the forms guard and Nulavio's pages refusing permission requests
        # live in the Nulavio build: another browser (the distribution's Firefox) is refused before the profile is
        # touched or anything starts, for the AI Workspace and for the user's own profile alike.
        from nulavio_launcher import engine as engine_mod
        from nulavio_launcher.ai import workspace

        firefox = engine_mod.Engine(path=Path("/usr/lib64/firefox/firefox"), version="160.0", vendor="Mozilla Firefox")
        folder = self.home / "profiles" / "work"
        folder.mkdir(parents=True)
        (folder / "user.js").write_text('user_pref("browser.startup.page", 3);\n')
        clean = {k: v for k, v in os.environ.items() if k != engine_mod.HARNESS_FIREFOX_ENV}

        def targets(engine):
            return (
                Workspace("ag-1", engine=engine, headless=True),
                ProfileTarget("ag-2", "Trabalho", folder, downloads_dir=self.home / "dl", engine=engine),
                Workspace("ag-3", headless=True),  # the engine found by the lookup
            )

        with (
            mock.patch.dict(os.environ, clean, clear=True),
            mock.patch.object(engine_mod, "find_engine", return_value=firefox),
            mock.patch.object(workspace.subprocess, "Popen") as popen,
        ):
            for target in targets(firefox):
                with (
                    self.subTest(target=type(target).__name__),
                    self.assertRaisesRegex(engine_mod.EngineError, "AI Bridge drives only Nulavio's own engine"),
                ):
                    target.start()
            popen.assert_not_called()
            self.assertEqual((folder / "user.js").read_text(), 'user_pref("browser.startup.page", 3);\n')
            self.assertEqual([p for p in self.home.rglob("user.js") if p != folder / "user.js"], [])

            # The agent is told why, as a tool error, not an internal one.
            agent, _ = registry.add("probe", "other", "autonomous")
            bridge = tools.Bridge(agent["id"], "s-1", approver=registry.Approver())
            answer = bridge.call("tabs_list", {})
            self.assertTrue(answer["isError"])
            self.assertIn("is not the Nulavio build", answer["content"][0]["text"])
            popen.assert_not_called()

        # A profile of the user's that could not start is not left as open.
        with (
            mock.patch.dict(os.environ, clean, clear=True),
            mock.patch.object(engine_mod, "find_engine", return_value=firefox),
            mock.patch.object(workspace.subprocess, "Popen") as popen,
        ):
            given, _ = registry.add("profiles", "other", "autonomous")
            registry.set_profiles(given["id"], [{"label": "Trabalho", "path": str(folder)}])
            bridge = tools.Bridge(given["id"], "s-2", approver=registry.Approver())
            answer = bridge.call("tab_new", {"profile": "Trabalho"})
            self.assertTrue(answer["isError"], answer)
            self.assertIn("is not the Nulavio build", answer["content"][0]["text"])
            self.assertNotIn("Trabalho", bridge.profiles)
            listed = bridge.call("profiles_list", {})["structuredContent"]["profiles"]
            self.assertIn({"profile": "Trabalho", "open": False}, listed)
            popen.assert_not_called()
            self.assertEqual((folder / "user.js").read_text(), 'user_pref("browser.startup.page", 3);\n')

        class Started(Exception):
            pass

        # The test harness, which says so, still runs the distribution's Firefox (pull-request CI).
        with (
            mock.patch.dict(os.environ, {**clean, engine_mod.HARNESS_FIREFOX_ENV: "1"}, clear=True),
            mock.patch.object(workspace.subprocess, "Popen", side_effect=Started),
            self.assertRaises(Started),
        ):
            Workspace("ag-4", engine=firefox, headless=True).start()

    def test_disposable_workspace_is_deleted(self):
        ws = Workspace("ag-2", disposable=True, engine=mock.Mock(path=Path("/x")))
        self.assertTrue(ws.dir.exists())
        ws.stop()
        self.assertFalse(ws.dir.exists())


class BidiEventsTest(unittest.TestCase):
    def test_events_with_a_handler_go_to_it_in_order_and_not_to_the_list(self):
        # The network intercept's events are many: kept in `events`, they would push out the dialog
        # events a call waits for. A handler that fails does not stop the ones after it.
        seen, done = [], threading.Event()

        class Socket:
            def __init__(self, *_a, **_k):
                self.queue: list[str] = []

            def send_text(self, text):
                if json.loads(text)["method"] == "session.new":
                    self.queue.append(json.dumps({"type": "success", "id": json.loads(text)["id"], "result": {}}))

            def recv_text(self):
                while not self.queue:
                    time.sleep(0.01)
                return self.queue.pop(0)

            def close(self):
                pass

        def handler(params):
            seen.append(params["n"])
            if params["n"] == 0:
                raise RuntimeError("a handler's own bug")
            if params["n"] == 2:
                done.set()

        with mock.patch.object(bidi_mod, "WebSocket", Socket):
            connection = bidi_mod.Bidi(9)
        connection.on("network.beforeRequestSent", handler)
        frames = [{"type": "event", "method": "network.beforeRequestSent", "params": {"n": n}} for n in range(3)]
        frames.insert(1, {"type": "event", "method": "browsingContext.userPromptOpened", "params": {"context": "t1"}})
        connection.ws.queue.extend(json.dumps(f) for f in frames)
        self.assertTrue(done.wait(5))
        self.assertEqual(seen, [0, 1, 2])
        self.assertEqual([e["method"] for _, e in connection.events], ["browsingContext.userPromptOpened"])


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
            self.assertIn("internal pages are never included", err.getvalue())
            self.assertEqual(
                main(["ai", "add", "F", "--client", "other", "--autonomy", "full-control", "--accept-full-control"]), 0
            )

    def test_the_internal_pages_cannot_be_granted_from_the_command_line(self):
        from nulavio_launcher.cli import main

        agent, _ = registry.add("R", "other", "full_control", accept_full_control=True)
        with mock.patch("sys.stdout", new=io.StringIO()), mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(main(["ai", "grant", agent["id"], "debugging", "allow"]), 1)
            self.assertIn("not offered to agents", err.getvalue())
            with self.assertRaises(SystemExit):  # the flag is gone
                main(["ai", "grant", agent["id"], "debugging", "allow", "--accept-raw-automation"])
        self.assertNotIn("debugging", registry.get(agent["id"])["grants"])


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
            ("multiple_profiles", "Trabalho", "critical", {"kind": "profile", "profile": "Trabalho"}),
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

    def test_a_request_called_off_before_it_is_written_is_never_shown(self):
        """#764: a call cancelled (or a session stopped, paused or revoked) before its question writes no request
        file for the person to see; it is denied at once."""
        cancel = threading.Event()
        cases = (
            ("cancel", lambda a: cancel.set()),
            ("stop", lambda a: registry.set_stopped(True)),
            ("pause", lambda a: registry.pause(a, True)),
        )
        real_write = registry.paths.write_private_file
        for name, act in cases:
            with self.subTest(name):
                agent, _ = registry.add("o", "other", "restricted")
                cancel.clear()
                act(agent["id"])
                written: list[str] = []
                shown: list[dict] = []

                def write(path, *args, written=written, **kwargs):
                    written.append(str(path))
                    return real_write(path, *args, **kwargs)

                approver = registry.BrowserApprover(fallback=Approve("once"), notice=3, timeout=30, poll=0.05,
                                                    on_request=shown.append)  # fmt: skip
                with mock.patch.object(registry.paths, "write_private_file", write):
                    self.assertEqual(approver.ask(registry.get(agent["id"]), "interact", None, cancel=cancel), "deny")
                self.assertEqual((written, shown), ([], []))
                registry.set_stopped(False)

    def test_a_request_cancelled_while_the_registry_is_read_is_never_shown(self):
        """OpenCodeReview on #812: a cancel that comes while the approver reads the registry, after it looked at the
        cancel, still writes no request file for the person to see (not even one removed right after: CodeRabbit on
        #812)."""
        agent, _ = registry.add("o", "other", "restricted")
        cancel = threading.Event()
        real_load, real_write = registry.load, registry.paths.write_private_file
        written: list[str] = []

        def load(*args, **kwargs):
            cancel.set()
            return real_load(*args, **kwargs)

        def write(path, *args, **kwargs):
            if Path(path).parent == registry.requests_dir():
                written.append(str(path))
            return real_write(path, *args, **kwargs)

        shown: list[dict] = []
        approver = registry.BrowserApprover(fallback=Approve("once"), notice=3, timeout=30, poll=0.05,
                                            on_request=shown.append)  # fmt: skip
        calling = registry.get(agent["id"])
        with mock.patch.object(registry, "load", load), mock.patch.object(registry.paths, "write_private_file", write):
            self.assertEqual(approver.ask(calling, "interact", None, cancel=cancel), "deny")
        self.assertEqual((written, shown), ([], []))
        self.assertEqual(list(registry.requests_dir().iterdir()), [])

    def test_a_request_called_off_while_it_is_written_or_the_registry_is_read_is_never_shown(self):
        """OpenCodeReview on #812 (round 2): the emergency stop turned on while the approver reads the registry, after it
        looked at the stop, or a cancel or the stop while it writes the request: no approval event is sent, the
        request file is removed (or, for the stop during the read, never written: CodeRabbit on #812), and the request
        is denied."""
        self.addCleanup(registry.set_stopped, False)
        cancel = threading.Event()
        real_load, real_write = registry.load, registry.paths.write_private_file
        for number, (when, name) in enumerate((("read", "stop"), ("write", "cancel"), ("write", "stop"))):
            with self.subTest(when=when, name=name):
                registry.set_stopped(False)
                cancel.clear()
                agent, _ = registry.add(f"off {number}", "other", "restricted")
                calling = registry.get(agent["id"])

                def act(name=name):
                    cancel.set() if name == "cancel" else registry.set_stopped(True)

                def load(*args, when=when, act=act, **kwargs):
                    if when == "read":
                        act()
                    return real_load(*args, **kwargs)

                written: list[str] = []

                def write(path, *args, when=when, act=act, written=written, **kwargs):
                    real_write(path, *args, **kwargs)
                    if Path(path).parent == registry.requests_dir():
                        written.append(str(path))
                        if when == "write":
                            act()  # while the request was written: it is there now

                shown: list[dict] = []
                approver = registry.BrowserApprover(fallback=Approve("once"), notice=3, timeout=30, poll=0.05,
                                                    on_request=shown.append)  # fmt: skip
                with mock.patch.object(registry, "load", load), mock.patch.object(registry.paths, "write_private_file", write):
                    self.assertEqual(approver.ask(calling, "interact", None, cancel=cancel), "deny")
                self.assertEqual(shown, [])
                self.assertEqual(len(written), 0 if when == "read" else 1)  # a stop during the read writes nothing
                self.assertEqual(list(registry.requests_dir().iterdir()), [])

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
        with self.assertRaises(registry.RegistryError):  # #463: the operation is gone
            ai_cli.api_request({"op": "raw-automation", "agent": agent_id, "enabled": True, "acceptRawAutomation": True})
        self.assertEqual(ai_cli.api_request({"op": "overview"})["agents"][0]["modes"][policy.INTERNAL_CAPABILITY], "block")
        ai_cli.api_request({"op": "pause", "agent": agent_id, "paused": True})
        ai_cli.api_request({"op": "stop", "stopped": True})
        self.assertTrue(ai_cli.api_request({"op": "overview"})["stopped"])
        with self.assertRaises(registry.RegistryError):
            ai_cli.api_request({"op": "add", "name": "F", "client": "other", "autonomy": "full_control"})
        with self.assertRaises(registry.RegistryError):
            ai_cli.api_request({"op": "explode"})


class DisconnectTest(Home):
    """#646: the agent's client exits or closes stdin while a call waits for the person's answer."""

    @staticmethod
    def take(then=None) -> threading.Thread:
        """What a Nulavio window does with a new request: it marks it seen (the bridge then waits for the answer),
        then `then(base)`."""

        def run():
            for _ in range(200):
                pending = list(registry.requests_dir().glob("*.json"))
                if pending:
                    base = pending[0].with_suffix("")
                    base.with_suffix(".seen").touch()
                    if then:
                        then(base)
                    return
                time.sleep(0.02)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def test_stdin_eof_during_a_pending_approval_denies_it_at_once_and_removes_its_files(self):
        agent, _ = registry.add("d", "other", "restricted")
        approver = registry.BrowserApprover(fallback=Approve("once"), notice=5, timeout=60, poll=0.05)
        decisions: list[policy.Decision] = []

        class Asking(FakeBridge):
            def call(self, name, arguments, cancel):
                self.started.set()
                decisions.append(registry.decide(agent["id"], "interact", host=None, target=None, session_id="s-1",
                                                 approver=approver, cancel=cancel))  # fmt: skip
                return {"content": [{"type": "text", "text": "done"}], "isError": False}

        bridge = Asking()
        server_in_r, server_in_w = os.pipe()
        out = io.BytesIO()
        server = mcp.Server(bridge, os.fdopen(server_in_r, "rb"), out)
        thread = threading.Thread(target=server.serve, daemon=True)
        thread.start()
        writer = os.fdopen(server_in_w, "wb")
        for message in (INIT, req(1, "tools/call", {"name": "session_state", "arguments": {}})):
            writer.write(json.dumps(message).encode() + b"\n")
        writer.flush()
        taken: list[Path] = []
        self.take(taken.append).join(5)
        self.assertEqual(len(taken), 1, "no request was written")
        self.assertTrue(wait_for(lambda: bridge.started.is_set()))
        time.sleep(0.2)  # the approver now waits for the answer
        started = time.monotonic()
        writer.close()  # the agent's client exits
        thread.join(10)
        self.assertFalse(thread.is_alive(), "the server still waits for the call")
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual([(d.allowed, d.reason) for d in decisions], [(False, "denied")])
        self.assertEqual(list(registry.requests_dir().iterdir()), [])  # the request page closes as expired
        self.assertEqual([json.loads(line).get("id") for line in out.getvalue().splitlines()], [0])  # no answer to a gone client
        self.assertTrue(bridge.closed)
        # The person clicks "Allow" afterwards: there is nothing to answer any more, and nothing is left behind.
        with self.assertRaises(registry.RegistryError):
            registry.answer_request(taken[0].name, "once")
        self.assertEqual(list(registry.requests_dir().iterdir()), [])

    def test_an_allow_that_comes_with_the_cancel_does_nothing(self):
        """The person's answer and the cancel arrive together: the cancel wins, and an answer for the session is not
        kept either."""
        agent, _ = registry.add("l", "other", "restricted")
        cancel = threading.Event()
        for answer in ("once", "session"):
            with self.subTest(answer):
                cancel.clear()
                decision = registry.decide(agent["id"], "interact", host=None, target=None, session_id="s-1",
                                           approver=Approve(answer, meanwhile=cancel.set), cancel=cancel)  # fmt: skip
                self.assertEqual((decision.allowed, decision.reason), (False, "cancelled"))
        self.assertEqual(registry.decide(agent["id"], "interact", host=None, target=None, session_id="s-1",
                                         approver=registry.Approver()).reason, "no-approver")  # fmt: skip

    def test_a_browser_answer_read_after_the_cancel_is_a_denial(self):
        agent, _ = registry.add("b", "other", "restricted")
        cancel = threading.Event()

        def answer(base: Path):
            time.sleep(0.2)
            cancel.set()  # the client went away, and the answer is on disk before the approver looks again
            (base.with_suffix(".answer")).write_text("once")

        thread = self.take(answer)
        approver = registry.BrowserApprover(fallback=Approve("once"), notice=5, timeout=30, poll=0.5)
        self.assertEqual(approver.ask(registry.get(agent["id"]), "interact", None, cancel=cancel), "deny")
        thread.join(5)
        self.assertEqual(list(registry.requests_dir().iterdir()), [])

    def test_an_answer_written_as_its_request_ends_is_not_left_behind(self):
        base = registry.requests_dir() / "0123456789abcdef"
        base.with_suffix(".json").write_text("{}")
        real_write = registry.paths.write_private_file

        def write(path, *args, **kwargs):
            for suffix in (".json", ".seen", ".answer"):  # the call ended meanwhile (BrowserApprover.ask's finally)
                base.with_suffix(suffix).unlink(missing_ok=True)
            return real_write(path, *args, **kwargs)

        with mock.patch.object(registry.paths, "write_private_file", write), self.assertRaises(registry.RegistryError):
            registry.answer_request(base.name, "once")
        self.assertEqual(list(registry.requests_dir().iterdir()), [])

    def test_the_desktop_dialog_closes_when_the_call_is_cancelled(self):
        fake = self.home / "kdialog"
        pid_file = self.home / "kdialog.pid"
        fake.write_text(f'#!/bin/sh\necho $$ > "{pid_file}"\nexec sleep 30\n')
        fake.chmod(0o700)
        agent, _ = registry.add("k", "other", "restricted")
        cancel = threading.Event()
        threading.Timer(0.5, cancel.set).start()
        started = time.monotonic()
        with mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
            answer = registry.KDialogApprover(str(fake)).ask(registry.get(agent["id"]), "interact", None, cancel=cancel)
        self.assertEqual(answer, "deny")
        self.assertLess(time.monotonic() - started, 5)
        pid = int(pid_file.read_text())
        self.assertFalse(Path(f"/proc/{pid}").exists() and "zombie" not in Path(f"/proc/{pid}/status").read_text().lower())

    def ended_bridge(self, agent_id: str, made: list, *, end_while_made: bool = False) -> tools.Bridge:
        bridge: tools.Bridge

        def factory(_agent):
            workspace = mock.Mock(bidi=None, downloads_dir=self.home / "downloads")
            workspace.start.side_effect = lambda *a, **k: setattr(workspace, "bidi", mock.Mock()) or workspace.bidi
            made.append(workspace)
            if end_while_made:
                bridge.end()  # the client went away while the call was making its engine
            return workspace

        bridge = tools.Bridge(agent_id, "s-1", approver=registry.Approver(), workspace_factory=factory)
        return bridge

    def test_a_call_still_running_after_the_bridge_ended_starts_no_engine(self):
        agent, _ = registry.add("e", "other", "autonomous")
        made: list = []
        bridge = self.ended_bridge(agent["id"], made)
        bridge.end()
        result = bridge.call("tabs_list", {})
        self.assertTrue(result["isError"], result)
        self.assertEqual(made, [])
        self.assertIsNone(bridge.workspace)

    def test_an_engine_made_as_the_bridge_ends_is_stopped(self):
        agent, _ = registry.add("e", "other", "autonomous")
        made: list = []
        bridge = self.ended_bridge(agent["id"], made, end_while_made=True)
        result = bridge.call("tabs_list", {})
        self.assertTrue(result["isError"], result)
        self.assertEqual(len(made), 1)
        made[0].start.assert_not_called()
        made[0].stop.assert_called()  # a disposable workspace's folder goes with it
        self.assertIsNone(bridge.workspace)


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
