"""Activity & Audit for the AI Bridge: what each agent did, never what it saw or typed.

One JSON line per tool call in $XDG_STATE_HOME/nulavio/ai/audit.jsonl (0600):
time, agent, bridge session, tool, capability, decision and reason, the
target's origin (scheme://host:port, never the path or query), outcome,
duration and sizes. Typed text, page text, scripts and screenshots are not
stored. The file rotates at a fixed size and keeps one previous file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .registry import ai_state
from .policy import now

MAX_BYTES = 2_000_000
FIELDS = {"agent", "session", "tool", "capability", "decision", "reason", "target", "outcome", "ms",
          "input_chars", "output_bytes", "client"}  # fmt: skip


def audit_path() -> Path:
    return ai_state() / "audit.jsonl"


def record(**fields) -> None:
    unknown = set(fields) - FIELDS
    if unknown:
        raise ValueError(f"audit fields not allowed: {sorted(unknown)}")  # an allow-list, so nothing leaks by accident
    entry = {"ts": now().isoformat(timespec="milliseconds"), **{k: v for k, v in fields.items() if v is not None}}
    path = audit_path()
    if path.exists() and path.stat().st_size > MAX_BYTES:
        os.replace(path, path.with_suffix(".jsonl.1"))
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def read(limit: int = 50, agent: str | None = None) -> list[dict]:
    path = audit_path()
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if agent:
        entries = [e for e in entries if e.get("agent") == agent]
    return entries[-limit:]
