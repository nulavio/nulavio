"""Local, append-only launcher log with redaction.

The launcher log answers "what did Nulavio do to my profile and when?" for
the person who owns the machine. It never leaves the machine and must never
contain secrets, cookies, tokens or browsing history:

* URLs are reduced to their scheme (``<url:https>``);
* ``key=value`` pairs whose key looks secret are masked;
* the home directory is shown as ``~``.

Format: JSON Lines in ``$XDG_STATE_HOME/nulavio/launcher.log`` (mode 0600).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Any

from . import paths

_URL_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.-]{1,15}):(//)?[^\s\"'<>]+")
_SECRET_KV_RE = re.compile(
    r"(?i)\b(pass(word|wd)?|secret|token|api[_-]?key|session(id)?|cookie|auth(orization)?|bearer|otp|pin)"
    r"(\s*[=:]\s*)([^\s,;&\"']+)"
)
_KEEP_SCHEMES = {"nulavio"}  # internal pseudo-URLs that carry no user data
_MAX_LOG_BYTES = 1_000_000


def redact(text: str) -> str:
    """Remove URLs, secret-looking values and the home path from ``text``."""

    def _url(match: re.Match[str]) -> str:
        scheme = match.group(1).lower()
        if scheme in _KEEP_SCHEMES:
            return match.group(0)
        if scheme in {"file"}:
            return "<url:file>"
        # Things like "C:" or "ratio:3" are not URLs worth hiding, but every
        # scheme with "//" or a known web scheme is.
        if match.group(2) or scheme in {"http", "https", "about", "moz-extension", "data", "blob", "javascript", "mailto"}:
            return f"<url:{scheme}>"
        return match.group(0)

    text = _URL_RE.sub(_url, text)
    text = _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}{m.group(5)}<redacted>", text)
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    return text


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


def log_path() -> Path:
    return paths.state_home() / "launcher.log"


def event(action: str, **fields: Any) -> None:
    """Append one redacted JSON line. Logging failures never break the launch."""
    try:
        paths.ensure_private_dir(paths.state_home())
        target = log_path()
        if target.exists() and target.stat().st_size > _MAX_LOG_BYTES:
            os.replace(target, target.with_suffix(".log.1"))
        record = {
            "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
            "action": action,
            **_sanitize(fields),
        }
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags, paths.PRIVATE_FILE_MODE)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass
