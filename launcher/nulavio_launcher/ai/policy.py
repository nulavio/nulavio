"""Policy Decision Point of the AI Bridge (ADR 0007).

Decisions come from the user's configuration only: the agent's autonomy
preset, its explicit grants, its site scope, revocation and the emergency
stop. Nothing an agent or a web page sends can change them; the MCP surface
has no tool that edits policy.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import socket
import urllib.parse
from dataclasses import dataclass

# Capability id -> what the user sees. Mirrors the brief's list; "files" covers
# upload and download, "local_resources" covers this computer, the local
# network and internal pages (about:, file:).
CAPABILITIES: dict[str, str] = {
    "read_pages": "Read pages",
    "navigate": "Open tabs and go to addresses",
    "interact": "Click and type",
    "submit_forms": "Submit forms",
    "screenshots": "See screenshots",
    "files": "Upload and download files",
    "authenticated_sessions": "Use signed-in sessions",
    "execute_js": "Run JavaScript in pages",
    "network": "Inspect network activity",
    "cookies_storage": "Read or change cookies and site storage",
    "multiple_profiles": "Work in more than one profile",
    "private_tabs": "Use private tabs",
    "local_resources": "Reach this computer, the local network and internal pages",
    "transactions": "Make purchases and payments",
    "account_settings": "Change account settings",
    "background": "Keep working in the background",
    "debugging": "Raw automation and the browser's internal pages",
}
MODES = ("allow", "ask", "block")
# Raw automation (the raw_automation tool) and privileged pages (about:, chrome:). No preset
# includes it, Full control neither (ADR 0007, amendment of 2026-10-28): it is a separate
# opt-in per agent, with its own confirmation, recorded as `raw_automation_accepted`.
RAW_CAPABILITY = "debugging"

# How a permission request presents each capability (Shell page ai/request.html): critical for
# money, code, the user's own data and places outside the AI Workspace; warning for what changes
# pages or sends data; info for reading. Unknown capabilities are shown as critical.
RISK: dict[str, str] = {
    "read_pages": "info",
    "navigate": "info",
    "screenshots": "info",
    "interact": "warning",
    "submit_forms": "warning",
    "files": "warning",
    "background": "warning",
    "authenticated_sessions": "critical",
    "execute_js": "critical",
    "network": "critical",
    "cookies_storage": "critical",
    "multiple_profiles": "critical",
    "private_tabs": "critical",
    "local_resources": "critical",
    "transactions": "critical",
    "account_settings": "critical",
    "debugging": "critical",
}


def _preset(allow: set[str], ask: set[str]) -> dict[str, str]:
    return {c: "allow" if c in allow else "ask" if c in ask else "block" for c in CAPABILITIES}


PRESETS: dict[str, dict[str, str]] = {
    # Unknown agents: read and move around; everything that acts asks first.
    "restricted": _preset({"read_pages", "navigate", "screenshots"}, {"interact", "submit_forms"}),
    # Supervised automation: acts on pages, asks for consequential steps.
    "assisted": _preset(
        {"read_pages", "navigate", "screenshots", "interact"},
        {"submit_forms", "files", "authenticated_sessions", "transactions", "account_settings", "background"},
    ),
    # Trusted agent: no prompts for ordinary work; money, account changes and
    # stronger tools still ask until the user allows them explicitly.
    "autonomous": _preset(
        {"read_pages", "navigate", "screenshots", "interact", "submit_forms", "files", "authenticated_sessions", "background"},
        {"transactions", "account_settings", "local_resources", "execute_js", "network", "multiple_profiles", "private_tabs"},
    ),
    # Everything without confirmations, except raw automation (a separate opt-in).
    "full_control": _preset(set(CAPABILITIES) - {RAW_CAPABILITY}, set()),
}
# For the CLI only: the browser shows its own localised text (aiFullControlBody, aiRawBody).
FULL_CONTROL_WARNING = (
    "Full control: this agent will do without asking everything the other levels ask about: any action on "
    "pages, purchases and payments, account changes, private tabs, the profiles in its list and running "
    "scripts in pages. Raw automation is not included: it is a separate option with its own confirmation. "
    "If the agent is compromised or makes a mistake, your data and accounts can be affected. You can revoke "
    "access later, but actions already taken may be irreversible."
)
RAW_AUTOMATION_WARNING = (
    "Raw automation: this agent gets a direct WebDriver BiDi connection to its AI Workspace's browser and may "
    "open the browser's internal pages. Nulavio does not check, ask about or record anything done through that "
    "connection: your permissions, site list and activity log no longer apply to it. The emergency stop, pause "
    "and revoke still close the AI Workspace. Never available in your own profiles."
)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    mode: str  # allow / ask / block (the effective setting before any prompt)
    capability: str
    # preset:<name>, grant, session-grant, raw-automation-off, approved-once, approved-session, denied,
    # no-approver, revoked, paused, stopped, out-of-scope
    reason: str


def now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def grant_active(grant: dict, session_id: str, at: _dt.datetime | None = None) -> bool:
    at = at or now()
    until = grant.get("until")
    if until and _dt.datetime.fromisoformat(until) <= at:
        return False
    bound = grant.get("session")
    return not bound or bound == session_id


def effective_mode(agent: dict, capability: str, session_id: str, at: _dt.datetime | None = None) -> tuple[str, str]:
    """(mode, source) for one capability: an "allow for this session" answer, then an active explicit
    grant, then the preset. A session answer is kept apart from the user's own grants (UX5-0), so when
    the session ends the capability goes back to what the user set, never to the preset."""
    if capability not in CAPABILITIES:
        return "block", "unknown-capability"
    if capability == RAW_CAPABILITY and not agent.get("raw_automation_accepted"):
        # Only the separate opt-in turns it on; a grant given without that confirmation does not count.
        return "block", "raw-automation-off"
    held = agent.get("session_grants", {}).get(capability)
    if held and session_id and held.get("session") == session_id:
        return "allow", "session-grant"
    grant = agent.get("grants", {}).get(capability)
    if grant and grant_active(grant, session_id, at):
        return grant["mode"], "grant"
    return PRESETS[agent["autonomy"]][capability], f"preset:{agent['autonomy']}"


def in_scope(agent: dict, host: str | None) -> bool:
    """An agent with a site list may only act on those sites (and their subdomains)."""
    domains = agent.get("domains") or []
    if not domains or host is None:
        return True
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


# -- addresses --------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    url: str
    host: str | None
    needs: tuple[str, ...]  # extra capabilities beyond the tool's own


class UrlRefused(ValueError):
    pass


LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")
INTERNAL_SCHEMES = {"about", "file", "chrome", "resource", "moz-extension", "view-source"}


def _local_address(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        return False
    return not address.is_global


def _resolves_locally(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False  # the browser will fail to load it too
    return any(_local_address(info[4][0]) for info in infos)


def classify_url(url: str, resolve: bool = True) -> Target:
    """Which capabilities a navigation needs. Refuses what no capability can allow."""
    if len(url) > 8192 or any(ch in url for ch in "\r\n\t\x00"):
        raise UrlRefused("the address is too long or contains control characters")
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    if url == "about:blank":
        return Target(url, None, ())
    if scheme in ("http", "https"):
        if parsed.username or parsed.password:
            raise UrlRefused("addresses with a user name or password are not opened")
        host = (parsed.hostname or "").lower()
        if not host:
            raise UrlRefused("the address has no host")
        local = host == "localhost" or host.endswith(LOCAL_SUFFIXES) or _local_address(host)
        if not local and resolve:
            local = _resolves_locally(host)
        return Target(url, host, ("local_resources",) if local else ())
    if scheme in INTERNAL_SCHEMES:
        privileged = scheme in ("chrome", "resource") or (scheme == "about" and url not in ("about:blank",))
        return Target(url, None, ("local_resources", "debugging") if privileged else ("local_resources",))
    if scheme == "javascript":
        raise UrlRefused("javascript: addresses are not opened; scripts need the evaluate tool")
    raise UrlRefused(f"'{scheme or '?'}:' addresses are not supported")


def origin(url: str | None) -> str | None:
    """scheme://host[:port] for logs: never the path or query."""
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme in ("http", "https") and parsed.hostname:
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    return f"{parsed.scheme}:" if parsed.scheme else None
