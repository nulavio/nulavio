"""What a new profile may contact by itself (docs/security/new-profile-connections.json), and the engine's own record of
what it asked for (its network log: ``nsHttp:1`` writes the address of every HTTP channel, ``nsHostResolver:4`` every
name it resolves)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
LIST = ROOT / "docs" / "security" / "new-profile-connections.json"
PAGE = LIST.with_suffix(".md")
ENGINE_LOG = "timestamp,sync,nsHttp:1,nsHostResolver:4"

_LINE = re.compile(r"^\S+ \S+ UTC - \[[^\]]*\]: \S+ (.*)$")


def entries() -> list[dict]:
    return json.loads(LIST.read_text(encoding="utf-8"))["connections"]


def allowed(language: str) -> tuple[set[tuple[str, str]], set[str]]:
    """(scheme, host) pairs a new profile may ask for in that language, and the names it may only resolve."""
    addresses, names = set(), set()
    for entry in entries():
        hosts = [*entry["hosts"], *entry.get("mirrors_not_recorded", []), *entry.get("hosts_by_language", {}).get(language, [])]
        addresses.update((entry.get("scheme", "https"), host) for host in hosts)
        names.update(entry.get("names_only", []))
    return addresses, names


def read_log(folder: Path, name: str = "engine") -> tuple[list[str], list[str]]:
    """Every address a channel was made for and every name resolved, from all processes' logs, in the order written."""
    addresses, names = [], []
    for log in sorted(Path(folder).glob(f"{name}*")):
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _LINE.match(line)
            if not match:
                continue
            text = match.group(1)
            if text.startswith("uri="):
                addresses.append(text[4:])
            elif text.startswith("Resolving host ["):
                names.append(text.split("[", 1)[1].split("]", 1)[0])
    return addresses, names


def without_query(address: str) -> str:
    """The address as a failure may print it: a query can carry a key."""
    parts = urlsplit(address)
    return f"{parts.scheme}://{parts.hostname}{parts.path}"
