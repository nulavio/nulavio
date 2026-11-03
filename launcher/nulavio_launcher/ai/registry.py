"""Agent Registry and approvals for the AI Bridge.

Each connected agent has an id, an autonomy preset, explicit grants, an
optional site list and a secret token. Only the token's SHA-256 is stored;
the token sits in the agent's MCP configuration, so it identifies *that
configuration*, not the program (any process of the same user that reads it
can present it). The bridge re-reads this file on every call, so revocation,
grant changes and the emergency stop apply to the next call.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .. import paths
from .policy import (
    CAPABILITIES,
    FULL_CONTROL_WARNING,
    MODES,
    PRESETS,
    RAW_AUTOMATION_WARNING,
    RAW_CAPABILITY,
    RISK,
    Decision,
    effective_mode,
    in_scope,
    now,
)

CLIENTS = ("claude-code", "codex", "other", "nulavio-assistant")
NAME_RE = re.compile(r"^[\w .+-]{1,48}$")


class RegistryError(RuntimeError):
    """`code` is what the browser shows (a locale key err_<code>); the message is for the CLI and logs."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def ai_state() -> Path:
    return paths.ensure_private_dir(paths.state_home() / "ai")


def _registry_path() -> Path:
    return ai_state() / "agents.json"


def stop_path() -> Path:
    return ai_state() / "STOP"


def token_file(agent_id: str) -> Path:
    """Where an agent's key lives (0600). Agent configurations point here instead of holding the key."""
    return paths.ensure_private_dir(ai_state() / "tokens") / f"{agent_id}.token"


def read_token_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read(256).strip() or None
    except OSError:
        return None


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@contextlib.contextmanager
def _locked():
    lock = ai_state() / "agents.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def load() -> dict:
    path = _registry_path()
    if not path.exists():
        return {"version": 1, "agents": {}}
    paths.check_private(path, paths.PRIVATE_FILE_MODE, fix=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("agents"), dict):
        raise RegistryError("unsupported agents.json")
    return data


def _save(data: dict) -> None:
    paths.write_private_file(_registry_path(), json.dumps(data, indent=1, sort_keys=True))


def _update(fn):
    with _locked():
        data = load()
        result = fn(data)
        _save(data)
        return result


def stopped() -> bool:
    return stop_path().exists()


def set_stopped(value: bool) -> None:
    if value:
        paths.write_private_file(stop_path(), now().isoformat(timespec="seconds"))
    else:
        stop_path().unlink(missing_ok=True)


# -- agents -------------------------------------------------------------------------


def add(name: str, client: str, autonomy: str, *, domains: list[str] | None = None, disposable: bool = False,
        accept_full_control: bool = False) -> tuple[dict, str]:  # fmt: skip
    """Register an agent; returns (record, token). The token is shown once."""
    if not NAME_RE.match(name):
        raise RegistryError("name: 1-48 letters, digits, spaces, '.', '+', '-'")
    if client not in CLIENTS:
        raise RegistryError(f"client must be one of {', '.join(CLIENTS)}")
    if autonomy not in PRESETS:
        raise RegistryError(f"autonomy must be one of {', '.join(PRESETS)}")
    if autonomy == "full_control" and not accept_full_control:
        raise RegistryError("full control needs an explicit acceptance: " + FULL_CONTROL_WARNING, "full-control-not-accepted")
    clean_domains = sorted({_domain(d) for d in domains or []})
    token = secrets.token_urlsafe(32)
    record = {
        "id": "ag-" + secrets.token_hex(6), "name": name, "client": client, "autonomy": autonomy,
        "grants": {}, "domains": clean_domains, "workspace": "disposable" if disposable else "persistent",
        "token_sha256": _hash(token), "created": now().isoformat(timespec="seconds"), "revoked": None,
        "full_control_accepted": now().isoformat(timespec="seconds") if autonomy == "full_control" else None,
    }  # fmt: skip

    def apply(data):
        data["agents"][record["id"]] = record

    _update(apply)
    paths.write_private_file(token_file(record["id"]), token)
    return record, token


def _domain(text: str) -> str:
    text = text.strip().lower().rstrip(".")
    if not re.fullmatch(r"(?=.{1,253}$)([a-z0-9-]{1,63}\.)*[a-z0-9-]{1,63}", text):
        raise RegistryError(f"not a domain: {text!r}")
    return text


def get(agent_id: str) -> dict:
    agent = load()["agents"].get(agent_id)
    if agent is None:
        raise RegistryError(f"no agent {agent_id}")
    return agent


def by_token(token: str | None) -> dict | None:
    if not token:
        return None
    digest = _hash(token)
    for agent in load()["agents"].values():
        if hmac.compare_digest(agent["token_sha256"], digest):
            return agent
    return None


def revoke(agent_id: str) -> None:
    def apply(data):
        if agent_id not in data["agents"]:
            raise RegistryError(f"no agent {agent_id}")
        data["agents"][agent_id]["revoked"] = now().isoformat(timespec="seconds")

    _update(apply)


def remove(agent_id: str) -> None:
    def apply(data):
        if data["agents"].pop(agent_id, None) is None:
            raise RegistryError(f"no agent {agent_id}")

    _update(apply)
    from .workspace import workspaces_root

    shutil.rmtree(workspaces_root() / agent_id, ignore_errors=True)
    token_file(agent_id).unlink(missing_ok=True)


def set_autonomy(agent_id: str, autonomy: str, accept_full_control: bool = False) -> None:
    if autonomy not in PRESETS:
        raise RegistryError(f"autonomy must be one of {', '.join(PRESETS)}")
    if autonomy == "full_control" and not accept_full_control:
        raise RegistryError("full control needs an explicit acceptance: " + FULL_CONTROL_WARNING, "full-control-not-accepted")

    def apply(data):
        agent = data["agents"].get(agent_id)
        if agent is None:
            raise RegistryError(f"no agent {agent_id}")
        agent["autonomy"] = autonomy
        agent.pop("session_grants", None)  # answers given under the old level do not outlive it
        if autonomy == "full_control":
            agent["full_control_accepted"] = now().isoformat(timespec="seconds")

    _update(apply)


def grant(agent_id: str, capability: str, mode: str, *, minutes: int | None = None,
          accept_raw_automation: bool = False) -> dict:  # fmt: skip
    """The user sets one capability to allow/ask/block, forever or for N minutes. It replaces an
    "allow for this session" answer for that capability (grant_session), so what the user sets wins.

    Raw automation (policy.RAW_CAPABILITY) is a separate opt-in: allowing or asking for it needs
    `accept_raw_automation` (the user saw its own warning) unless the agent already has it on;
    blocking it turns the opt-in off, so turning it on again shows the warning again.
    """
    if capability not in CAPABILITIES:
        raise RegistryError(f"unknown capability {capability}")
    if mode not in MODES:
        raise RegistryError(f"mode must be one of {', '.join(MODES)}")
    entry = {"mode": mode, "set": now().isoformat(timespec="seconds"), "until": None, "session": None}
    if minutes is not None:
        if not 1 <= minutes <= 60 * 24 * 365:
            raise RegistryError("minutes out of range")
        entry["until"] = (now() + _dt.timedelta(minutes=minutes)).isoformat(timespec="seconds")

    def apply(data):
        agent = data["agents"].get(agent_id)
        if agent is None:
            raise RegistryError(f"no agent {agent_id}")
        if capability == RAW_CAPABILITY:
            if mode == "block":
                agent["raw_automation_accepted"] = None
            elif accept_raw_automation:
                agent["raw_automation_accepted"] = now().isoformat(timespec="seconds")
            elif not agent.get("raw_automation_accepted"):
                raise RegistryError("raw automation needs an explicit acceptance: " + RAW_AUTOMATION_WARNING,
                                    "raw-automation-not-accepted")  # fmt: skip
        agent["grants"][capability] = entry
        agent.get("session_grants", {}).pop(capability, None)

    _update(apply)
    return entry


def grant_session(agent_id: str, capability: str, session_id: str) -> None:
    """The answer "allow until the agent disconnects": kept apart from the user's grants, never over them."""
    if capability not in CAPABILITIES or not session_id:
        raise RegistryError("bad session grant")

    def apply(data):
        agent = data["agents"].get(agent_id)
        if agent is None:
            raise RegistryError(f"no agent {agent_id}")
        held = agent.setdefault("session_grants", {})
        held[capability] = {"session": session_id, "set": now().isoformat(timespec="seconds")}

    _update(apply)


def end_session(agent_id: str, session_id: str) -> None:
    """The bridge session ended: its "allow until the agent disconnects" answers go with it."""

    def apply(data):
        held = (data["agents"].get(agent_id) or {}).get("session_grants") or {}
        for capability in [c for c, g in held.items() if g.get("session") == session_id]:
            del held[capability]

    _update(apply)


def set_raw_automation(agent_id: str, enabled: bool, accept: bool = False) -> None:
    """The per-agent "Raw automation" option: on (allowed until changed, after its warning) or off."""
    if enabled:
        grant(agent_id, RAW_CAPABILITY, "allow", accept_raw_automation=accept)
    else:
        clear_grant(agent_id, RAW_CAPABILITY)


def _change(agent_id: str, fn) -> None:
    def apply(data):
        agent = data["agents"].get(agent_id)
        if agent is None:
            raise RegistryError(f"no agent {agent_id}")
        fn(agent)

    _update(apply)


def pause(agent_id: str, paused: bool) -> None:
    """Hold an agent without revoking it: its calls are refused until resumed."""
    _change(agent_id, lambda a: a.__setitem__("paused", now().isoformat(timespec="seconds") if paused else None))


def set_domains(agent_id: str, domains: list[str]) -> None:
    clean = sorted({_domain(d) for d in domains})
    _change(agent_id, lambda a: a.__setitem__("domains", clean))


LABEL_RE = re.compile(r"^[\w .+-]{1,40}$")


def set_profiles(agent_id: str, profiles: list[dict]) -> None:
    """Real browser profiles this agent may use, besides its AI Workspace: [{"label", "path"}]."""
    clean = []
    for item in profiles:
        label, path = str(item.get("label", "")).strip(), str(item.get("path", ""))
        if not LABEL_RE.match(label) or not path.startswith("/") or "\x00" in path:
            raise RegistryError(f"bad profile entry {label!r}")
        if label.lower() in ("workspace", "ai workspace") or any(p["label"] == label for p in clean):
            raise RegistryError(f"profile label {label!r} is reserved or repeated")
        clean.append({"label": label, "path": str(Path(path))})
    _change(agent_id, lambda a: a.__setitem__("profiles", clean))


def set_routes(agent_id: str, routes: list[dict]) -> None:
    """Per-agent routing: sites that open in one of the agent's authorised profiles: [{"site", "profile"}]."""
    agent = get(agent_id)
    labels = {p["label"] for p in agent.get("profiles", [])}
    clean = []
    for item in routes:
        site, label = _domain(str(item.get("site", ""))), str(item.get("profile", ""))
        if label not in labels:
            raise RegistryError(f"route to {label!r}: not one of this agent's profiles")
        clean.append({"site": site, "profile": label})
    _change(agent_id, lambda a: a.__setitem__("routes", clean))


def route_for(agent: dict, host: str | None) -> str | None:
    """The profile label a site goes to for this agent (the most specific site wins), or None (its workspace)."""
    if not host:
        return None
    host = host.lower().rstrip(".")
    matches = [r for r in agent.get("routes", []) if host == r["site"] or host.endswith("." + r["site"])]
    return max(matches, key=lambda r: len(r["site"]))["profile"] if matches else None


def rotate_token(agent_id: str) -> str:
    """A new token for the agent's configuration; the old one stops working at once."""
    token = secrets.token_urlsafe(32)
    _change(agent_id, lambda a: a.__setitem__("token_sha256", _hash(token)))
    paths.write_private_file(token_file(agent_id), token)
    return token


# Program names that each client runs as (the bridge's parent process). Evidence only:
# a mismatch is shown to the user, never used to grant anything.
CLIENT_EXECUTABLES = {"claude-code": {"claude", "node", "bun"}, "codex": {"codex", "codex-exec", "node"}}


def parent_executable() -> str | None:
    try:
        return Path(os.readlink(f"/proc/{os.getppid()}/exe")).name
    except OSError:
        return None


def record_client(agent_id: str, executable: str | None) -> bool:
    """Remember which program started the bridge; returns False when it does not look like the registered client."""
    agent = load()["agents"].get(agent_id) or {}
    expected = CLIENT_EXECUTABLES.get(agent.get("client"))
    matches = expected is None or executable is None or executable in expected
    _change(agent_id, lambda a: a.__setitem__("last_client", {
        "executable": executable, "seen": now().isoformat(timespec="seconds"), "matches": matches}))  # fmt: skip
    return matches


def clear_grant(agent_id: str, capability: str) -> None:
    def apply(data):
        agent = data["agents"].get(agent_id, {})
        agent.get("grants", {}).pop(capability, None)
        agent.get("session_grants", {}).pop(capability, None)
        if capability == RAW_CAPABILITY and agent:
            agent["raw_automation_accepted"] = None  # back to the level's default: off

    _update(apply)


# -- approvals ------------------------------------------------------------------------


class Approver:
    """Asks the person at the computer. `None` means there is no way to ask (fail closed).

    `place`: where the call acts, "" for the agent's AI Workspace or the label of one of the
    user's own profiles the agent was given.
    """

    def ask(self, agent: dict, capability: str, target: str | None, place: str = "",
            cancel: threading.Event | None = None) -> str | None:  # fmt: skip
        return None


class KDialogApprover(Approver):
    """A KDE dialog, outside the browser the agent controls. Allow once / until the agent disconnects / deny."""

    def __init__(self, executable: str | None = None, timeout: float = 120):
        self.executable = executable or shutil.which("kdialog")
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.executable) and bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))

    def ask(self, agent: dict, capability: str, target: str | None, place: str = "",
            cancel: threading.Event | None = None) -> str | None:  # fmt: skip
        # The dialog cannot be taken back once shown; decide() checks stop, pause and revoke again after it.
        if not self.available():
            return None
        where = f"in your profile {place}" if place else "in its AI Workspace"
        text = (f"{agent['name']} ({agent['autonomy'].replace('_', ' ')}) wants to: {CAPABILITIES[capability]}"
                + (f"\non {target}" if target else "") + f"\n{where}"
                + "\n\nOnly allow this if you asked the agent to do it.")  # fmt: skip
        try:
            result = subprocess.run(
                [self.executable, "--title", "Nulavio AI Bridge", "--yes-label", "Allow once",
                 "--no-label", "Allow until the agent disconnects", "--cancel-label", "Deny", "--yesnocancel", text],
                capture_output=True, timeout=self.timeout, check=False,
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):
            return "deny"
        return {0: "once", 1: "session"}.get(result.returncode, "deny")


class BrowserApprover(Approver):
    """Ask in the user's Nulavio window (Shell page "Agent permission request").

    The bridge writes a request file; a running Nulavio (never the AI Workspace
    itself) marks it seen, shows it, and writes the answer. If no browser
    picks it up quickly, the next approver is asked (the KDE dialog, or no).
    """

    def __init__(self, fallback: Approver | None = None, notice: float = 4.0, timeout: float = 120.0, poll: float = 0.2,
                 on_request=None):  # fmt: skip
        self.fallback = fallback or Approver()
        self.notice, self.timeout, self.poll = notice, timeout, poll
        self.on_request = on_request  # told about each request written (the assistant's stream, UX5-C1)

    def ask(self, agent: dict, capability: str, target: str | None, place: str = "",
            cancel: threading.Event | None = None) -> str | None:  # fmt: skip
        """Denies as soon as the emergency stop is on, the agent is paused or revoked, or the call was
        cancelled: the request page then closes as expired, and nothing waits for an answer."""
        folder = requests_dir()
        request_id = secrets.token_hex(8)
        base = folder / request_id
        body = {"id": request_id, "agent_id": agent["id"], "agent": agent["name"], "client": agent.get("client"),
                "autonomy": agent["autonomy"], "capability": capability, "label": CAPABILITIES[capability],
                "risk": RISK.get(capability, "critical"), "target": target,
                "place": {"kind": "profile", "profile": place} if place else {"kind": "workspace"},
                "created": now().isoformat(timespec="seconds"),
                "expires": (now() + _dt.timedelta(seconds=self.timeout)).isoformat(timespec="seconds")}  # fmt: skip
        paths.write_private_file(base.with_suffix(".json"), json.dumps(body))
        try:
            if self.on_request:
                self.on_request(body)
            deadline = time.monotonic() + self.notice
            while not base.with_suffix(".seen").exists():
                if _called_off(agent["id"], cancel):
                    return "deny"
                if time.monotonic() > deadline:
                    base.with_suffix(".json").unlink(missing_ok=True)
                    return self.fallback.ask(agent, capability, target, place, cancel)
                time.sleep(self.poll)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                answer = base.with_suffix(".answer")
                if answer.exists():
                    value = answer.read_text().strip()
                    return value if value in ("once", "session", "deny") else "deny"
                if _called_off(agent["id"], cancel):
                    return "deny"
                time.sleep(self.poll)
            return "deny"
        finally:
            for suffix in (".json", ".seen", ".answer"):
                base.with_suffix(suffix).unlink(missing_ok=True)


def _called_off(agent_id: str, cancel: threading.Event | None) -> bool:
    """While a request waits: the call was cancelled, the stop is on, or the agent was paused or revoked."""
    if (cancel is not None and cancel.is_set()) or stopped():
        return True
    try:
        agent = load()["agents"].get(agent_id)
    except (OSError, ValueError, RegistryError):
        return True  # the registry cannot be read: fail closed
    return agent is None or bool(agent.get("revoked") or agent.get("paused"))


def requests_dir() -> Path:
    return paths.ensure_private_dir(ai_state() / "requests")


def sessions_dir() -> Path:
    return paths.ensure_private_dir(ai_state() / "sessions")


def mark_session(agent: dict, session_id: str) -> Path:
    """While a bridge session runs: who is connected and the process that serves it (UX5-I2). The band
    of the user's windows reads these files (never a process) and checks that the pid still lives; a
    file left by a process that was killed is then ignored."""
    marker = sessions_dir() / f"{session_id}.json"
    paths.write_private_file(marker, json.dumps({"agent": agent["id"], "name": agent["name"], "client": agent.get("client"),
                                                 "pid": os.getpid(), "since": now().isoformat(timespec="seconds")}))  # fmt: skip
    return marker


def pending_requests() -> list[dict]:
    out = []
    for item in sorted(requests_dir().glob("*.json")):
        try:
            out.append(json.loads(item.read_text()))
        except (OSError, ValueError):
            continue
    return out


def answer_request(request_id: str, answer: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{16}", request_id) or answer not in ("once", "session", "deny"):
        raise RegistryError("bad answer")
    base = requests_dir() / request_id
    if not base.with_suffix(".json").exists():
        raise RegistryError("no such request (expired?)")
    paths.write_private_file(base.with_suffix(".answer"), answer)


def default_approver() -> Approver:
    if os.environ.get("NULAVIO_AI_APPROVER") == "none":  # only ever makes the bridge stricter
        return Approver()
    kdialog = KDialogApprover()
    return BrowserApprover(fallback=kdialog if kdialog.available() else Approver())


def _held(agent: dict | None, host: str | None) -> str | None:
    """Why nothing this agent asks for may happen now, or None."""
    if stopped():
        return "stopped"
    if agent is None or agent.get("revoked"):
        return "revoked"
    if agent.get("paused"):
        return "paused"
    if not in_scope(agent, host):
        return "out-of-scope"
    return None


def decide(agent_id: str, capability: str, *, host: str | None, target: str | None, session_id: str,
           approver: Approver, place: str = "", cancel: threading.Event | None = None) -> Decision:  # fmt: skip
    """The single decision point: stop switch, revocation, site scope, grant/preset, then a prompt if needed.

    A prompt can stay open for minutes, so everything is checked again after the answer: a stop, a pause,
    a revocation, a smaller site list or a block set meanwhile wins over "allow" (UX5-0)."""
    agent = load()["agents"].get(agent_id)
    held = _held(agent, host)
    if held:
        return Decision(False, "block", capability, held)
    mode, source = effective_mode(agent, capability, session_id)
    if mode == "allow":
        return Decision(True, mode, capability, source)
    if mode == "block":
        return Decision(False, mode, capability, source)
    answer = approver.ask(agent, capability, target, place, cancel)
    if answer is None:
        return Decision(False, mode, capability, "no-approver")
    if answer in ("once", "session"):
        agent = load()["agents"].get(agent_id)
        held = _held(agent, host)
        if held:
            return Decision(False, "block", capability, held)
        now_mode, now_source = effective_mode(agent, capability, session_id)
        if now_mode == "block":
            return Decision(False, now_mode, capability, now_source)
    if answer == "session":
        grant_session(agent_id, capability, session_id)
        return Decision(True, mode, capability, "approved-session")
    if answer == "once":
        return Decision(True, mode, capability, "approved-once")
    return Decision(False, mode, capability, "denied")
