"""Nulavio Guard (preview): detective checks on a profile before launch.

Guard reports; it does not silently revert. Rules live in
browser/config/guard-rules.json so they are reviewable as data.

Limitations (also in docs/security/residual-risks.md): any process running
as the same user can edit prefs.js/user.js after Guard ran or edit Guard's
own rules in a writable checkout. Guard catches accidental, legacy or
tool-induced weakening; it is not a malware defence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths, prefs

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
_OPS = {"lt", "gt", "eq", "ne", "present"}


@dataclass(frozen=True)
class Finding:
    pref: str
    severity: str
    message: str
    actual: Any


def load_rules(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or paths.config_dir() / "guard-rules.json"
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = data["rules"]
    for rule in rules:
        if rule["op"] not in _OPS or rule["severity"] not in SEVERITY_ORDER:
            raise ValueError(f"invalid guard rule: {rule}")
    return rules


def _matches(op: str, actual: Any, expected: Any) -> bool:
    if op == "present":
        return True
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if not isinstance(actual, int) or isinstance(actual, bool):
        return False
    return actual < expected if op == "lt" else actual > expected


def audit(profile_dir: Path, rules: list[dict[str, Any]] | None = None) -> list[Finding]:
    rules = rules if rules is not None else load_rules()
    effective = prefs.effective_user_prefs(profile_dir)
    findings = []
    for rule in rules:
        name = rule["pref"]
        if name not in effective:
            continue  # engine default applies; defaults are upstream-safe
        if _matches(rule["op"], effective[name], rule.get("value")):
            findings.append(Finding(name, rule["severity"], rule["message"], effective[name]))
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.pref))
    return findings
