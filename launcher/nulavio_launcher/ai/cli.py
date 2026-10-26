"""`nulavio ai …`: connect agents, set their permissions, stop them, read the audit.

The agent's own MCP configuration is printed, never written: Nulavio does not
edit Claude Code, Codex or any other program's settings (brief, phase 4).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys

from .. import paths
from . import audit, policy, registry

LEVELS = {"restricted": "restricted", "assisted": "assisted", "autonomous": "autonomous", "full-control": "full_control"}


def _out(text: str = "") -> None:
    print(text)


def _launcher() -> str:
    return str(paths.repo_root() / "bin" / "nulavio")


def server_env(token: str) -> dict[str, str]:
    env = {"NULAVIO_AGENT_TOKEN": token}
    for key in ("NULAVIO_ENGINE", "NULAVIO_HOME"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def client_config(client: str, token: str, headless: bool = False) -> str:
    """Exact configuration for the user to add to their agent (or to pass for one run)."""
    args = ["ai", "serve"] + (["--headless"] if headless else [])
    env = server_env(token)
    if client == "codex":
        lines = ["[mcp_servers.nulavio]", f"command = {json.dumps(_launcher())}", f"args = {json.dumps(args)}",
                 "startup_timeout_sec = 30", "tool_timeout_sec = 90", "", "[mcp_servers.nulavio.env]"]  # fmt: skip
        lines += [f"{k} = {json.dumps(v)}" for k, v in env.items()]
        return "\n".join(lines)
    return json.dumps({"mcpServers": {"nulavio": {"type": "stdio", "command": _launcher(), "args": args, "env": env}}}, indent=2)


def cmd(args: argparse.Namespace) -> int:
    try:
        return HANDLERS[args.ai_cmd](args)
    except registry.RegistryError as exc:
        print(f"nulavio: {exc}", file=sys.stderr)
        return 1


def _add(args) -> int:
    level = LEVELS[args.autonomy]
    if level == "full_control":
        print(policy.FULL_CONTROL_WARNING, file=sys.stderr)
    agent, token = registry.add(args.name, args.client, level, domains=args.site, disposable=args.disposable,
                                accept_full_control=args.accept_full_control)  # fmt: skip
    _out(f"Agent {agent['id']} ({agent['name']}, {args.autonomy}) registered.")
    _out("Add this to the agent's MCP configuration yourself; the token is shown only once:\n")
    _out(client_config(agent["client"], token, args.headless))
    if agent["client"] == "claude-code":
        _out("\nClaude Code: save it as a file and run `claude --mcp-config <file>`, or add it to .mcp.json.")
    elif agent["client"] == "codex":
        _out("\nCodex: add it to ~/.codex/config.toml (or pass the same keys with `codex -c`).")
    return 0


def _agents(args) -> int:
    agents = registry.load()["agents"].values()
    if args.json:
        _out(json.dumps([{k: v for k, v in a.items() if k != "token_sha256"} for a in agents], indent=2))
        return 0
    if not agents:
        _out("No agents. Add one with `nulavio ai add`.")
    for a in agents:
        state = "revoked" if a.get("revoked") else a["autonomy"].replace("_", " ")
        sites = ", ".join(a.get("domains") or []) or "any site"
        _out(f"{a['id']}  {a['name']:<20} {a['client']:<12} {state:<13} {sites}  workspace: {a['workspace']}")
        for cap, g in sorted(a.get("grants", {}).items()):
            scope = f" until {g['until']}" if g.get("until") else " this session" if g.get("session") else ""
            _out(f"      {cap}: {g['mode']}{scope}")
    if registry.stopped():
        _out("\nEMERGENCY STOP is on: every agent is blocked (`nulavio ai resume` to lift it).")
    return 0


def _grant(args) -> int:
    entry = registry.grant(args.agent, args.capability, args.mode, minutes=args.minutes)
    until = f" until {entry['until']}" if entry["until"] else ""
    _out(f"{args.agent}: {args.capability} = {args.mode}{until}")
    return 0


def _autonomy(args) -> int:
    level = LEVELS[args.level]
    if level == "full_control":
        print(policy.FULL_CONTROL_WARNING, file=sys.stderr)
    registry.set_autonomy(args.agent, level, args.accept_full_control)
    _out(f"{args.agent}: autonomy {args.level}")
    return 0


def _revoke(args) -> int:
    registry.revoke(args.agent)
    _out(f"{args.agent}: access revoked; its next call is refused and its workspace closes")
    return 0


def _remove(args) -> int:
    registry.remove(args.agent)
    _out(f"{args.agent}: removed with its AI Workspace")
    return 0


def _stop(args) -> int:
    registry.set_stopped(True)
    _out("Emergency stop: every agent's next call is refused and its workspace closes.")
    return 0


def _resume(args) -> int:
    registry.set_stopped(False)
    _out("Emergency stop lifted.")
    return 0


def _audit(args) -> int:
    entries = audit.read(args.limit, args.agent)
    if args.json:
        _out(json.dumps(entries, indent=2))
        return 0
    for e in entries:
        _out(f"{e['ts']}  {e.get('agent')}  {e.get('tool'):<14} {e.get('decision'):<5} {e.get('outcome'):<12} "
             f"{e.get('target') or ''} {('(' + e['reason'] + ')') if e.get('reason') else ''}")  # fmt: skip
    return 0


def _capabilities(args) -> int:
    names = list(policy.PRESETS)
    _out(f"{'capability':<24}" + "".join(f"{n.replace('_', ' '):<14}" for n in names))
    for cap, label in policy.CAPABILITIES.items():
        _out(f"{cap:<24}" + "".join(f"{policy.PRESETS[n][cap]:<14}" for n in names) + f"  {label}")
    return 0


def _serve(args) -> int:
    from .mcp import Server
    from .tools import Bridge

    agent = registry.by_token(os.environ.get("NULAVIO_AGENT_TOKEN"))
    if agent is None:
        print("nulavio ai serve: unknown or missing NULAVIO_AGENT_TOKEN; register the agent with `nulavio ai add`",
              file=sys.stderr)  # fmt: skip
        return 2
    if agent.get("revoked"):
        print(f"nulavio ai serve: access for {agent['id']} was revoked", file=sys.stderr)
        return 2
    session = "s-" + secrets.token_hex(6)
    print(f"nulavio ai serve: agent {agent['id']} session {session}", file=sys.stderr)
    Server(Bridge(agent["id"], session, headless=args.headless)).serve()
    return 0


HANDLERS = {"add": _add, "agents": _agents, "grant": _grant, "autonomy": _autonomy, "revoke": _revoke,
            "remove": _remove, "stop": _stop, "resume": _resume, "audit": _audit, "capabilities": _capabilities,
            "serve": _serve}  # fmt: skip


def add_parser(sub) -> None:
    p = sub.add_parser("ai", help="AI Bridge: connect agents (MCP) to an isolated AI Workspace, with your permissions")
    asub = p.add_subparsers(dest="ai_cmd", required=True)
    q = asub.add_parser("add", help="register an agent and print its MCP configuration")
    q.add_argument("name")
    q.add_argument("--client", choices=registry.CLIENTS, required=True)
    q.add_argument("--autonomy", choices=list(LEVELS), default="restricted")
    q.add_argument("--site", action="append", default=[], help="limit the agent to this site (repeatable)")
    q.add_argument("--disposable", action="store_true", help="delete the AI Workspace when the agent disconnects")
    q.add_argument("--headless", action="store_true", help="no window (for scripts and tests)")
    q.add_argument("--accept-full-control", action="store_true", help="required for --autonomy full-control")
    q = asub.add_parser("agents", help="list agents and their permissions")
    q.add_argument("--json", action="store_true")
    q = asub.add_parser("grant", help="allow, ask or block one capability for an agent")
    q.add_argument("agent")
    q.add_argument("capability", choices=list(policy.CAPABILITIES))
    q.add_argument("mode", choices=policy.MODES)
    q.add_argument("--minutes", type=int, help="only for this many minutes")
    q = asub.add_parser("autonomy", help="change an agent's autonomy level")
    q.add_argument("agent")
    q.add_argument("level", choices=list(LEVELS))
    q.add_argument("--accept-full-control", action="store_true")
    for name, text in (("revoke", "revoke an agent's access"), ("remove", "forget an agent and delete its workspace")):
        q = asub.add_parser(name, help=text)
        q.add_argument("agent")
    asub.add_parser("stop", help="emergency stop: block every agent now")
    asub.add_parser("resume", help="lift the emergency stop")
    q = asub.add_parser("audit", help="what agents did (no page content, no typed text)")
    q.add_argument("--agent")
    q.add_argument("--limit", type=int, default=50)
    q.add_argument("--json", action="store_true")
    asub.add_parser("capabilities", help="capabilities and what each autonomy level does with them")
    q = asub.add_parser("serve", help="MCP server on stdin/stdout (started by the agent, not by you)")
    q.add_argument("--headless", action="store_true")
    p.set_defaults(func=cmd)
