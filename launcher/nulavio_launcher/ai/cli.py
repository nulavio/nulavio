"""`nulavio ai …`: connect agents, set their permissions, stop them, read the audit.

The agent's own MCP configuration is printed, never written: Nulavio does not
edit Claude Code, Codex or any other program's settings (brief, phase 4).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import sys

from .. import paths
from . import audit, connect, policy, registry

LEVELS = {"restricted": "restricted", "assisted": "assisted", "autonomous": "autonomous", "full-control": "full_control"}


def _out(text: str = "") -> None:
    print(text)


def _launcher() -> str:
    return str(paths.repo_root() / "bin" / "nulavio")


def server_env(token: str | None = None, agent_id: str | None = None) -> dict[str, str]:
    """The bridge's environment in an agent's configuration: a pointer to the key file, never the key
    (configurations get copied, shared and committed). An explicit token is for one-off runs and tests."""
    env = {"NULAVIO_AGENT_TOKEN": token} if token else {"NULAVIO_AGENT_TOKEN_FILE": str(registry.token_file(agent_id))}
    for key in ("NULAVIO_ENGINE", "NULAVIO_HOME"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def client_config(client: str, token: str | None = None, headless: bool = False, agent_id: str | None = None) -> str:
    """Exact configuration for the user to add to their agent (or to pass for one run)."""
    args = ["ai", "serve"] + (["--headless"] if headless else [])
    env = server_env(token, agent_id)
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
    agent, _ = registry.add(args.name, args.client, level, domains=args.site, disposable=args.disposable,
                                accept_full_control=args.accept_full_control)  # fmt: skip
    _out(f"Agent {agent['id']} ({agent['name']}, {args.autonomy}) registered.")
    _out("Add this to the agent's MCP configuration (it points to the agent's key file; no secret in it):\n")
    _out(client_config(agent["client"], headless=args.headless, agent_id=agent["id"]))
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
        if a.get("raw_automation_accepted"):
            _out(f"      raw automation: on since {a['raw_automation_accepted']} (Nulavio does not check or log it)")
    if registry.stopped():
        _out("\nEMERGENCY STOP is on: every agent is blocked (`nulavio ai resume` to lift it).")
    return 0


def _grant(args) -> int:
    if args.capability == policy.RAW_CAPABILITY and args.mode != "block":
        print(policy.RAW_AUTOMATION_WARNING, file=sys.stderr)
    entry = registry.grant(args.agent, args.capability, args.mode, minutes=args.minutes,
                           accept_raw_automation=args.accept_raw_automation)  # fmt: skip
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
    registry.rotate_token(args.agent)
    _out(f"{args.agent}: new key in effect; the old one no longer works. The agent's configuration does not change.")
    return 0


def _connect(args) -> int:
    """Add Nulavio to the agent's own configuration, through the agent's CLI, after showing exactly what runs."""
    agent = registry.get(args.agent)
    try:
        plan = connect.plan(agent["client"], agent["id"])
    except connect.ConnectError as exc:
        print(f"nulavio: {exc.code}: {exc}", file=sys.stderr)
        return 1
    _out(f"{plan['label']} will be configured to use Nulavio. This changes: {plan['target']}.")
    _out("Command (no secret in it; it points to the agent's key file):\n")
    _out("    " + connect.describe(plan["command"]) + "\n")
    if plan["existing"]:
        _out(f"{plan['label']} already has a server named 'nulavio'; it will be replaced.")
    if not args.yes:
        if not sys.stdin.isatty():
            print("nulavio: not a terminal; re-run with --yes to run the command shown above", file=sys.stderr)
            return 1
        if input("Run it? [y/N] ").strip().lower() not in ("y", "yes", "s", "sim"):
            _out("Nothing was changed.")
            return 1
    try:
        result = connect.install(agent["client"], agent["id"], replace=plan["existing"])
    except connect.ConnectError as exc:
        print(f"nulavio: {exc.code}: {exc}", file=sys.stderr)
        return 1
    check = result["check"]
    state = "connected" if check["connected"] else "configured" if check["configured"] else "not visible"
    _out(f"{plan['label']}: Nulavio is {state}.")
    return 0 if check["configured"] else 1


def _capabilities(args) -> int:
    names = list(policy.PRESETS)
    _out(f"{'capability':<24}" + "".join(f"{n.replace('_', ' '):<14}" for n in names))
    for cap, label in policy.CAPABILITIES.items():
        _out(f"{cap:<24}" + "".join(f"{policy.PRESETS[n][cap]:<14}" for n in names) + f"  {label}")
    return 0


def _serve(args) -> int:
    from .mcp import Server
    from .tools import Bridge

    token = os.environ.get("NULAVIO_AGENT_TOKEN") or registry.read_token_file(os.environ.get("NULAVIO_AGENT_TOKEN_FILE"))
    agent = registry.by_token(token)
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
    try:
        Server(Bridge(agent["id"], session, headless=args.headless)).serve()
    finally:
        with contextlib.suppress(registry.RegistryError, OSError, ValueError):
            registry.end_session(agent["id"], session)
        audit.record(agent=agent["id"], client=agent.get("client"), session=session, event="disconnected")
    return 0


# -- helper API for the browser (Settings → AI & Automation) ------------------------------------

API_LIMIT = 64 * 1024


def _public(agent: dict, active: dict | None = None) -> dict:
    """What the UI may see: never the token hash."""
    view = {k: v for k, v in agent.items() if k != "token_sha256"}
    view["modes"] = {c: policy.effective_mode(agent, c, "")[0] for c in policy.CAPABILITIES}
    view["active_sessions"] = (active or {}).get(agent["id"], [])
    return view


def active_sessions() -> dict[str, list[dict]]:
    """Bridge sessions that connected and have not disconnected (from the activity log)."""
    sessions: dict[str, dict] = {}
    for entry in audit.read(1000):
        if entry.get("event") == "connected":
            sessions[entry.get("session")] = {"agent": entry.get("agent"), "since": entry["ts"], "session": entry.get("session")}
        elif entry.get("event") == "disconnected":
            sessions.pop(entry.get("session"), None)
    out: dict[str, list[dict]] = {}
    for item in sessions.values():
        out.setdefault(item["agent"], []).append(item)
    return out


def api_request(request: dict) -> dict:
    op = request.get("op")
    agent_id = request.get("agent")
    if op == "overview":
        data = registry.load()
        active = active_sessions()
        return {
            "agents": [_public(a, active) for a in data["agents"].values()],
            "stopped": registry.stopped(),
            "capabilities": policy.CAPABILITIES,
            "presets": policy.PRESETS,
            "levels": list(LEVELS.values()),
            # The consent texts are the browser's own (locale keys), never English from here.
            "rawCapability": policy.RAW_CAPABILITY,
            "requests": registry.pending_requests(),
        }
    if op == "add":
        level = LEVELS.get(str(request.get("autonomy", "")).replace("_", "-"), request.get("autonomy"))
        agent, _ = registry.add(str(request.get("name", "")), str(request.get("client", "")), str(level),
                                    domains=list(request.get("domains") or []), disposable=bool(request.get("disposable")),
                                    accept_full_control=bool(request.get("acceptFullControl")))  # fmt: skip
        config = client_config(agent["client"], headless=bool(request.get("headless")), agent_id=agent["id"])
        return {"agent": _public(agent), "config": config}
    if op == "rotate-token":
        registry.rotate_token(str(agent_id))  # the key file changes; the agent's configuration stays valid
        return {"done": True}
    if op == "autonomy":
        registry.set_autonomy(str(agent_id), str(request.get("level")), bool(request.get("acceptFullControl")))
    elif op == "grant":
        minutes = request.get("minutes")
        registry.grant(str(agent_id), str(request.get("capability")), str(request.get("mode")),
                       minutes=int(minutes) if minutes else None,
                       accept_raw_automation=bool(request.get("acceptRawAutomation")))  # fmt: skip
    elif op == "raw-automation":
        registry.set_raw_automation(str(agent_id), bool(request.get("enabled")), bool(request.get("acceptRawAutomation")))
    elif op == "clear-grant":
        registry.clear_grant(str(agent_id), str(request.get("capability")))
    elif op == "domains":
        registry.set_domains(str(agent_id), list(request.get("domains") or []))
    elif op == "profiles":
        registry.set_profiles(str(agent_id), list(request.get("profiles") or []))
    elif op == "routes":
        registry.set_routes(str(agent_id), list(request.get("routes") or []))
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
    elif op == "detect":
        return {"clients": connect.detect()}
    elif op == "plan":
        plan = connect.plan(str(request.get("client")), str(agent_id))
        return {**plan, "display": connect.describe(plan["command"])}
    elif op == "install":
        return connect.install(str(request.get("client")), str(agent_id), bool(request.get("replace")))
    elif op == "verify":
        return connect.verify(str(request.get("client")))
    elif op == "unconfigure":
        return {"removed": connect.remove(str(request.get("client")))}
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
    except connect.ConnectError as exc:
        result = {"error": exc.code, "detail": str(exc)[:300]}
    except registry.RegistryError as exc:
        text = str(exc)
        code = exc.code or ("bad-request" if text == "bad-request" else "invalid")
        result = {"error": code, "detail": text[:200]}
    except (ValueError, TypeError, OSError) as exc:
        result = {"error": "failed", "detail": type(exc).__name__}
    print(json.dumps(result))
    return 0


ASSISTANT_LIMIT = 512 * 1024  # a question plus the page's text


def _assistant_error(exc: BaseException) -> dict:
    """The error answer for the browser: a stable code (and, from the provider, whether it was reached)."""
    from . import assistant
    from ..vault.core import VaultError

    if isinstance(exc, assistant.AssistantError):
        result = {"error": exc.code, "detail": str(exc)[:200] if str(exc) != exc.code else None, "sent": exc.sent}
        if exc.retry_after is not None:
            result["retryAfter"] = exc.retry_after
        if exc.status is not None:
            result["status"] = exc.status
        return result
    if isinstance(exc, VaultError):  # the system keyring
        return {"error": exc.code}
    if isinstance(exc, registry.RegistryError):
        return {"error": "registry"}
    if isinstance(exc, OSError):
        return {"error": "failed", "detail": type(exc).__name__}
    raise exc


def _assistant(args) -> int:
    """`nulavio ai assistant`: one JSON request line on stdin for the browser's assistant panel (A12).

    Without "stream", one JSON answer on stdout. With "stream": true (UX5-C1), one JSON event per line:
    start, sending, delta (Ask), step and approval (Task), then exactly one terminal line, done or error.
    The browser keeps stdin open until then: its end, or SIGTERM, cancels; the answer then is
    done {cancelled: true, sent}, where sent says whether a request may have reached the provider."""
    import signal

    from . import assistant
    from ..vault.core import VaultError

    # A SIGTERM that comes before stream mode is set up waits (and is then a cancel), instead of
    # ending the process without its terminal line.
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    raw = sys.stdin.readline(ASSISTANT_LIMIT + 1)
    try:
        request = json.loads(raw) if len(raw) <= ASSISTANT_LIMIT else None
    except ValueError:
        request = None
    if isinstance(request, dict) and request.get("stream") is True and request.get("op") in ("ask", "task"):
        return _assistant_stream(request)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})  # one answer: SIGTERM ends it as before
    try:
        if not isinstance(request, dict):
            raise assistant.AssistantError("bad-request")
        result = assistant.api_request(request)
    except (assistant.AssistantError, VaultError, registry.RegistryError, OSError) as exc:
        result = _assistant_error(exc)
    print(json.dumps(result))
    return 0


def _assistant_stream(request: dict) -> int:
    import signal
    import threading

    from . import assistant
    from ..vault.core import VaultError

    def write(line: str) -> None:
        # SIGTERM waits while a line is written, so a cancel never leaves half a line for the browser to read.
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()  # bin/nulavio runs python3 -I, which ignores PYTHONUNBUFFERED
        finally:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})

    out = assistant.Stream(write)

    def cancel(_signum, _frame):
        if not out.cancellable:
            # The answer is in, or the AI Workspace is closing: that finishes, and the browser says the
            # answer arrived before the stop.
            out.cancel_requested = True
            return
        signal.signal(signal.SIGTERM, signal.SIG_IGN)  # once: the unwinding (closing the AI Workspace) is not cut
        raise assistant.Cancelled()

    signal.signal(signal.SIGTERM, cancel)
    main = threading.main_thread().ident

    def watch_stdin() -> None:
        # Anything after the request line is ignored; the end of stdin means the browser closed it or ended.
        with contextlib.suppress(OSError):
            while os.read(sys.stdin.fileno(), 4096):
                pass
        signal.pthread_kill(main, signal.SIGTERM)

    try:
        try:
            threading.Thread(target=watch_stdin, name="stdin-watch", daemon=True).start()
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGTERM})  # a cancel can come from here on
            result = assistant.api_request(request, out=out)
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)  # the terminal line is never cut in half
        terminal = {"type": "done", **result, "cancelled": False, "sent": out.sent}
    except assistant.Cancelled:
        terminal = {"type": "done", "cancelled": True, "sent": out.sent, "steps": out.steps}
    except (assistant.AssistantError, VaultError, registry.RegistryError, OSError) as exc:
        error = _assistant_error(exc)
        error["sent"] = bool(error.get("sent")) or out.answered > 0  # an earlier turn reached it
        terminal = {"type": "error", "code": error.pop("error"), **error, "steps": out.steps}
    except Exception as exc:  # never end without a terminal line: the browser would wait for its timeout
        terminal = {"type": "error", "code": "failed", "detail": type(exc).__name__, "sent": out.sent, "steps": out.steps}
    write(json.dumps(terminal, ensure_ascii=False))
    return 0


HANDLERS = {
    "api": _api,
    "assistant": _assistant,
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
    "connect": _connect,
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
    q.add_argument("--accept-raw-automation", action="store_true",
                   help=f"required to allow or ask for {policy.RAW_CAPABILITY} (raw automation)")  # fmt: skip
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
    asub.add_parser("assistant", help=argparse.SUPPRESS)  # the browser's assistant panel (A12)
    q = asub.add_parser("pause", help="hold an agent without revoking it")
    q.add_argument("agent")
    q.add_argument("--resume", action="store_true")
    q = asub.add_parser("rotate-token", help="replace an agent's key (its configuration stays valid)")
    q.add_argument("agent")
    q = asub.add_parser("connect", help="add Nulavio to the agent's own configuration, through its CLI, after approval")
    q.add_argument("agent")
    q.add_argument("--yes", action="store_true", help="run the command shown without asking")
    q = asub.add_parser("serve", help="MCP server on stdin/stdout (started by the agent, not by you)")
    q.add_argument("--headless", action="store_true")
    p.set_defaults(func=cmd)
