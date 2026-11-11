"""Activity & Audit for the AI Bridge: what each agent did, never what it saw or typed.

One JSON line per tool call in $XDG_STATE_HOME/nulavio/ai/audit.jsonl (0600):
time, agent, bridge session, tool, capability, decision and reason, the
target's origin (scheme://host:port, never the path or query), outcome,
duration and sizes. Typed text, page text, scripts and screenshots are not
stored. The file rotates at a fixed size and keeps KEEP previous files; the
Activity view reads them all, so a burst of cheap calls cannot push an
agent's earlier actions out of sight (audit A7).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

from .. import paths
from .policy import now
from .registry import ai_state

MAX_BYTES = 2_000_000
KEEP = 5  # audit.jsonl.1 (newest) to audit.jsonl.5
RETENTION_DAYS = 30  # older entries are dropped when the log rotates or is read
FIELDS = {"agent", "session", "tool", "capability", "decision", "reason", "target", "outcome", "ms",
          "input_chars", "output_bytes", "client", "event", "client_exe"}  # fmt: skip


def audit_path() -> Path:
    return ai_state() / "audit.jsonl"


def record(**fields) -> None:
    unknown = set(fields) - FIELDS
    if unknown:
        raise ValueError(f"audit fields not allowed: {sorted(unknown)}")  # an allow-list, so nothing leaks by accident
    entry = {"ts": now().isoformat(timespec="milliseconds"), **{k: v for k, v in fields.items() if v is not None}}
    path = audit_path()
    if path.exists() and path.stat().st_size > MAX_BYTES:
        for index in range(KEEP - 1, 0, -1):
            older = path.with_suffix(f".jsonl.{index}")
            if older.exists():
                os.replace(older, path.with_suffix(f".jsonl.{index + 1}"))
        os.replace(path, path.with_suffix(".jsonl.1"))
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _files() -> list[Path]:
    """Oldest first: the rotated files, then the current one."""
    path = audit_path()
    return [*(path.with_suffix(f".jsonl.{i}") for i in range(KEEP, 0, -1)), path]


def read(limit: int = 50, agent: str | None = None) -> list[dict]:
    prune()
    entries = []
    for path in _files():
        if path.exists():
            entries += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if agent:
        entries = [e for e in entries if e.get("agent") == agent]
    return entries[-limit:]


def prune(days: int = RETENTION_DAYS) -> int:
    """Drop entries older than `days`; returns how many were dropped."""
    cutoff = now() - _dt.timedelta(days=days)
    dropped = 0
    for path in _files():
        if not path.exists():
            continue
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        keep = [line for line in lines if _dt.datetime.fromisoformat(json.loads(line)["ts"]) >= cutoff]
        if not keep and path != audit_path():
            path.unlink()
        elif len(keep) != len(lines):
            paths.write_private_file(path, "".join(line + "\n" for line in keep))
        dropped += len(lines) - len(keep)
    return dropped


def clear() -> None:
    """Forget the whole activity history."""
    for path in _files():
        path.unlink(missing_ok=True)
