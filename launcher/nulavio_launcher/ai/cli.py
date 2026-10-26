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


def _pause(args) -> int:
    registry.pause(args.agent, not args.resume)
    _out(f"{args.agent}: {'resumed' if args.resume else 'paused'}")
    return 0


def _rotate(args) -> int:
    token = registry.rotate_token(args.agent)
    _out("New configuration (the old token no longer works):\n")
    _out(client_config(registry.get(args.agent)["client"], token))
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
    executable = registry.parent_executable()
    matches = registry.record_client(agent["id"], executable)
    audit.record(agent=agent["id"], client=agent.get("client"), session=session, event="connected", client_exe=executable,
                 outcome="ok" if matches else "client-mismatch")  # fmt: skip
    print(f"nulavio ai serve: agent {agent['id']} session {session}", file=sys.stderr)
    Server(Bridge(agent["id"], session, headless=args.headless)).serve()
    return 0


# -- helper API for the browser (Settings → AI & Automation) ------------------------------------

API_LIMIT = 64 * 1024


def _public(agent: dict) -> dict:
    """What the UI may see: never the token hash."""
    view = {k: v for k, v in agent.items() if k != "token_sha256"}
    view["modes"] = {c: policy.effective_mode(agent, c, "")[0] for c in policy.CAPABILITIES}
    return view


def api_request(request: dict) -> dict:
    op = request.get("op")
    agent_id = request.get("agent")
    if op == "overview":
        data = registry.load()
        return {
            "agents": [_public(a) for a in data["agents"].values()],
            "stopped": registry.stopped(),
            "capabilities": policy.CAPABILITIES,
            "presets": policy.PRESETS,
            "levels": list(LEVELS.values()),
            "fullControlWarning": policy.FULL_CONTROL_WARNING,
            "requests": registry.pending_requests(),
        }
    if op == "add":
        level = LEVELS.get(str(request.get("autonomy", "")).replace("_", "-"), request.get("autonomy"))
        agent, token = registry.add(str(request.get("name", "")), str(request.get("client", "")), str(level),
                                    domains=list(request.get("domains") or []), disposable=bool(request.get("disposable")),
                                    accept_full_control=bool(request.get("acceptFullControl")))  # fmt: skip
        return {"agent": _public(agent), "config": client_config(agent["client"], token, bool(request.get("headless")))}
    if op == "rotate-token":
        token = registry.rotate_token(str(agent_id))
        return {"config": client_config(registry.get(str(agent_id))["client"], token)}
    if op == "autonomy":
        registry.set_autonomy(str(agent_id), str(request.get("level")), bool(request.get("acceptFullControl")))
    elif op == "grant":
        minutes = request.get("minutes")
        registry.grant(str(agent_id), str(request.get("capability")), str(request.get("mode")),
                       minutes=int(minutes) if minutes else None)  # fmt: skip
    elif op == "clear-grant":
        registry.clear_grant(str(agent_id), str(request.get("capability")))
    elif op == "domains":
        registry.set_domains(str(agent_id), list(request.get("domains") or []))
    elif op == "pause":
        registry.pause(str(agent_id), bool(request.get("paused")))
    elif op == "revoke":
        registry.revoke(str(agent_id))
    elif op == "remove":
        registry.remove(str(agent_id))
    elif op == "stop":
        registry.set_stopped(bool(request.get("stopped")))
    elif op == "audit":
        return {"entries": audit.read(int(request.get("limit") or 100), request.get("agent"))}
    elif op == "audit-clear":
        audit.clear()
    elif op == "answer":
        registry.answer_request(str(request.get("id")), str(request.get("answer")))
    else:
        raise registry.RegistryError("bad-request")
    return {"done": True}


def _api(args) -> int:
    raw = sys.stdin.read(API_LIMIT + 1)
    try:
        if len(raw) > API_LIMIT:
            raise registry.RegistryError("bad-request")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise registry.RegistryError("bad-request")
        result = api_request(request)
    except registry.RegistryError as exc:
        text = str(exc)
        code = (
            "full-control-not-accepted"
            if text.startswith("full control")
            else "bad-request"
            if text == "bad-request"
            else "invalid"
        )
        result = {"error": code, "detail": text[:200]}
    except (ValueError, TypeError, OSError) as exc:
        result = {"error": "failed", "detail": type(exc).__name__}
    print(json.dumps(result))
    return 0


HANDLERS = {
    "api": _api,
    "add": _add,
    "agents": _agents,
    "grant": _grant,
    "autonomy": _autonomy,
    "revoke": _revoke,
    "remove": _remove,
    "stop": _stop,
    "resume": _resume,
    "audit": _audit,
    "capabilities": _capabilities,
    "pause": _pause,
    "rotate-token": _rotate,
    "serve": _serve,
}


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
    asub.add_parser("api", help=argparse.SUPPRESS)  # JSON on stdin/stdout, used by the browser
    q = asub.add_parser("pause", help="hold an agent without revoking it")
    q.add_argument("agent")
    q.add_argument("--resume", action="store_true")
    q = asub.add_parser("rotate-token", help="replace an agent's token (prints the new configuration)")
    q.add_argument("agent")
    q = asub.add_parser("serve", help="MCP server on stdin/stdout (started by the agent, not by you)")
    q.add_argument("--headless", action="store_true")
    p.set_defaults(func=cmd)
