"""Connect an agent with one approval (ADR 0007, S8): the agent's own CLI writes its configuration.

Nulavio never edits another program's files itself. It finds the agent's
command-line tool, shows the exact command and what it changes, and only
after the user approves runs that tool's documented `mcp add` command (a
fixed argument list, no shell). The configuration holds no secret: it points
to the agent's key file in Nulavio's state directory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .. import paths
from . import registry

SERVER_NAME = "nulavio"
CLIENTS = {
    "claude-code": {"binary": "claude", "label": "Claude Code",
                    "target": "Claude Code user settings (~/.claude.json): available in all your projects"},
    "codex": {"binary": "codex", "label": "Codex",
              "target": "Codex configuration ($CODEX_HOME/config.toml, usually ~/.codex/config.toml)"},
}  # fmt: skip
TIMEOUT = 60


class ConnectError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _launcher() -> str:
    return str(paths.repo_root() / "bin" / "nulavio")


def _run(command: list[str], timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConnectError("client-failed", type(exc).__name__) from None


def detect() -> list[dict]:
    """Which supported agents are installed, with their version."""
    found = []
    for client, spec in CLIENTS.items():
        path = shutil.which(spec["binary"])
        version = None
        if path:
            result = _run([path, "--version"], timeout=15)
            version = (result.stdout or result.stderr).strip().splitlines()[0][:80] if result.returncode == 0 else None
        found.append({"client": client, "label": spec["label"], "path": path, "version": version, "target": spec["target"]})
    return found


def _server(agent_id: str) -> tuple[list[str], dict[str, str]]:
    from .cli import server_env

    return ["ai", "serve"], server_env(agent_id=agent_id)


def install_command(client: str, agent_id: str) -> list[str]:
    """The exact command the approval runs."""
    if client not in CLIENTS:
        raise ConnectError("unsupported-client")
    registry.get(agent_id)
    binary = shutil.which(CLIENTS[client]["binary"])
    if not binary:
        raise ConnectError("client-missing")
    args, env = _server(agent_id)
    if client == "claude-code":
        spec = {"type": "stdio", "command": _launcher(), "args": args, "env": env}
        return [binary, "mcp", "add-json", "--scope", "user", SERVER_NAME, json.dumps(spec, separators=(",", ":"))]
    command = [binary, "mcp", "add", SERVER_NAME]
    for key, value in env.items():
        command += ["--env", f"{key}={value}"]
    return [*command, "--", _launcher(), *args]


def plan(client: str, agent_id: str) -> dict:
    """What the user approves: the program, the exact command, and what it changes."""
    command = install_command(client, agent_id)
    return {"client": client, "label": CLIENTS[client]["label"], "command": command, "target": CLIENTS[client]["target"],
            "existing": configured(client), "secret_in_command": False}  # fmt: skip


def configured(client: str) -> bool:
    binary = shutil.which(CLIENTS[client]["binary"])
    if not binary:
        return False
    return _run([binary, "mcp", "get", SERVER_NAME], timeout=30).returncode == 0


def remove(client: str) -> bool:
    binary = shutil.which(CLIENTS.get(client, {}).get("binary", ""))
    if not binary:
        raise ConnectError("client-missing")
    command = [binary, "mcp", "remove", SERVER_NAME] + (["--scope", "user"] if client == "claude-code" else [])
    return _run(command).returncode == 0


def install(client: str, agent_id: str, replace: bool = False) -> dict:
    """Run the approved command; then ask the agent's own tool whether it sees the server."""
    command = install_command(client, agent_id)
    if configured(client):
        if not replace:
            raise ConnectError("already-configured")
        remove(client)
    result = _run(command)
    if result.returncode != 0:
        raise ConnectError("client-failed", (result.stderr or result.stdout).strip()[-300:])
    return {"installed": True, "check": verify(client)}


def verify(client: str) -> dict:
    """The agent's own view of the server (`mcp get`); Claude Code also starts it to check the connection."""
    binary = shutil.which(CLIENTS[client]["binary"])
    if not binary:
        raise ConnectError("client-missing")
    result = _run([binary, "mcp", "get", SERVER_NAME], timeout=60)
    text = (result.stdout + result.stderr).strip()
    return {
        "configured": result.returncode == 0,
        "points_to_nulavio": _launcher() in text,
        "connected": result.returncode == 0 and ("✓ Connected" in text or "Connected" in text.split("Status:")[-1][:40]),
        "output": text[-600:],
    }


def describe(command: list[str]) -> str:
    """A readable one-line form of the command, for the approval screen."""
    return " ".join(part if part and all(c.isalnum() or c in "-_./=:~" for c in part) else json.dumps(part) for part in command)


__all__ = ["CLIENTS", "ConnectError", "Path", "describe", "detect", "install", "install_command", "plan", "remove", "verify"]
