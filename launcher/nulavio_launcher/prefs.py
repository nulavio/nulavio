"""Parse, render and inspect Firefox preference files.

Nulavio's pref files (browser/config/prefs/*.js) use plain ``user_pref()``
lines plus ``// @key value`` annotations (see baseline.js). Values are
JSON-compatible literals: ``true``, ``false``, integers or double-quoted
strings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PrefValue = bool | int | str

_PREF_LINE = re.compile(r'^\s*(?:user_)?pref\(\s*"((?:[^"\\]|\\.)+)"\s*,\s*(.+?)\s*\)\s*;\s*$')
_ANNOTATION = re.compile(r"^\s*//\s*@(\w+)\s+(.*?)\s*$")
_VALID_NAME = re.compile(r"^[A-Za-z0-9_.\-@{}]+$")
VALID_MODES = {"seed", "enforce"}


class PrefFileError(ValueError):
    pass


@dataclass(frozen=True)
class Pref:
    name: str
    value: PrefValue
    mode: str = "seed"
    category: str = ""
    why: str = ""
    tradeoff: str = ""
    source: str = ""
    meta: dict[str, str] = field(default_factory=dict, compare=False)


def parse_value(raw: str) -> PrefValue:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PrefFileError(f"unsupported pref value: {raw!r}") from exc
    if isinstance(value, (bool, int, str)):
        return value
    raise PrefFileError(f"unsupported pref value type: {raw!r}")


def format_value(value: PrefValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"unsupported pref value: {value!r}")


def format_pref(name: str, value: PrefValue) -> str:
    if not _VALID_NAME.match(name):
        raise PrefFileError(f"invalid pref name: {name!r}")
    return f'user_pref("{name}", {format_value(value)});'


def parse_annotated(path: Path) -> list[Pref]:
    """Parse a Nulavio pref file with annotations; strict about structure."""
    prefs: list[Pref] = []
    meta: dict[str, str] = {}
    seen: set[str] = set()
    for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            meta = {}
            continue
        annotation = _ANNOTATION.match(line)
        if annotation:
            meta[annotation.group(1)] = annotation.group(2)
            continue
        if line.lstrip().startswith("//"):
            continue
        match = _PREF_LINE.match(line)
        if not match:
            raise PrefFileError(f"{path}:{lineno}: not a user_pref() line")
        name = match.group(1)
        if name in seen:
            raise PrefFileError(f"{path}:{lineno}: duplicate pref {name}")
        seen.add(name)
        mode = meta.get("mode", "seed")
        if mode not in VALID_MODES:
            raise PrefFileError(f"{path}:{lineno}: invalid @mode {mode!r}")
        prefs.append(
            Pref(
                name=name,
                value=parse_value(match.group(2)),
                mode=mode,
                category=meta.get("category", ""),
                why=meta.get("why", ""),
                tradeoff=meta.get("tradeoff", ""),
                source=f"{Path(path).name}:{lineno}",
                meta=dict(meta),
            )
        )
        meta = {}
    return prefs


def read_user_prefs(path: Path) -> dict[str, PrefValue]:
    """Read ``user_pref`` values from prefs.js/user.js (last one wins).

    Lines that cannot be parsed (e.g. exotic escapes) are skipped: this is
    used for auditing, and the engine remains the source of truth.
    """
    values: dict[str, PrefValue] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return values
    for line in text.splitlines():
        match = _PREF_LINE.match(line)
        if not match:
            continue
        try:
            values[match.group(1)] = parse_value(match.group(2))
        except PrefFileError:
            continue
    return values


def substitute(value: PrefValue, variables: dict[str, str]) -> PrefValue:
    if isinstance(value, str):
        for key, replacement in variables.items():
            value = value.replace(f"@{key}@", replacement)
    return value


def render(prefs: list[tuple[str, PrefValue]], header: str) -> str:
    lines = [f"// {line}" if line else "//" for line in header.splitlines()]
    lines += [format_pref(name, value) for name, value in prefs]
    return "\n".join(lines) + "\n"


def effective_user_prefs(profile_dir: Path) -> dict[str, Any]:
    """prefs.js overlaid with user.js, mirroring the engine's load order."""
    values = read_user_prefs(Path(profile_dir) / "prefs.js")
    values.update(read_user_prefs(Path(profile_dir) / "user.js"))
    return values
