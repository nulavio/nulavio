"""Policy Decision Point of the AI Bridge (ADR 0007).

Decisions come from the user's configuration only: the agent's autonomy
preset, its explicit grants, its site scope, revocation and the emergency
stop. Nothing an agent or a web page sends can change them; the MCP surface
has no tool that edits policy.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import re
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
    "local_resources": "Reach this computer and the local network",
    "transactions": "Make purchases and payments",
    "account_settings": "Change account settings",
    "background": "Keep working in the background",
    "debugging": "The browser's internal pages (not offered to agents)",
}
MODES = ("allow", "ask", "block")
# The browser's internal pages (about:, chrome:, the Shell's own pages, the source viewer, Reader View). Only raw
# automation's separate opt-in ever turned this on; raw automation was removed (#463, ADR 0007 amendment of
# 2026-11-17), so no preset, grant or stored opt-in does: an agent acts only through the tools and the policy.
INTERNAL_CAPABILITY = "debugging"

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
    # Everything without confirmations, except the internal pages, which no agent gets.
    "full_control": _preset(set(CAPABILITIES) - {INTERNAL_CAPABILITY}, set()),
}
# For the CLI only: the browser shows its own localised text (aiFullControlBody).
FULL_CONTROL_WARNING = (
    "Full control: this agent will do without asking everything the other levels ask about: any action on "
    "pages, purchases and payments, account changes, private tabs, the profiles in its list and running "
    "scripts in pages. The browser's internal pages are never included. "
    "If the agent is compromised or makes a mistake, your data and accounts can be affected. You can revoke "
    "access later, but actions already taken may be irreversible."
)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    mode: str  # allow / ask / block (the effective setting before any prompt)
    capability: str
    # preset:<name>, grant, session-grant, internal-pages-off, approved-once, approved-session, denied,
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


def effective_mode(agent: dict, capability: str, session_id: str, at: _dt.datetime | None = None, *,
                   scope: tuple[str | None, str] | None = None) -> tuple[str, str]:  # fmt: skip
    """(mode, source) for one capability: an "allow for this session" answer, then an active explicit
    grant, then the preset. A session answer is kept apart from the user's own grants (UX5-0), so when
    the session ends the capability goes back to what the user set, never to the preset.

    A session answer covers what its request showed and nothing more: `scope` is (target, place) of the call, the
    site (policy.origin) and where it acts ("" for the AI Workspace, or a profile's label), and the answer counts only
    for a scope it was given for. Without a scope (the capability as a whole: the tool list, what an engine is told
    to hold or let through) no session answer counts."""
    if capability not in CAPABILITIES:
        return "block", "unknown-capability"
    if capability == INTERNAL_CAPABILITY:
        # No agent gets the internal pages since raw automation was removed (#463): not a grant, a session answer
        # or the `raw_automation_accepted` an earlier version recorded.
        return "block", "internal-pages-off"
    held = agent.get("session_grants", {}).get(capability)
    given = held.get("scopes") or [] if held and session_id and held.get("session") == session_id else []
    if scope is not None and [scope[0], scope[1]] in given:
        return "allow", "session-grant"
    grant = agent.get("grants", {}).get(capability)
    if grant and grant_active(grant, session_id, at):
        return grant["mode"], "grant"
    return PRESETS[agent["autonomy"]][capability], f"preset:{agent['autonomy']}"


def in_scope(agent: dict, host: str | None) -> bool:
    """An agent with a site list may only act on those sites (and their subdomains). `host` is host_of(): None when
    there is no address (nothing to bound), "" for an address with no site (file:, an internal page), never on a list."""
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


# The only characters the engine sends to its resolver in a name (net_IsValidDNSHost, netwerk/base/nsURLHelper.cpp):
# RFC 1035 plus "$+_". A host with any other one is not a name the engine looks up or opens.
DNS_HOST = re.compile(r"[a-z0-9.\-$+_]{1,253}")

LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet")
INTERNAL_SCHEMES = {"about", "file", "chrome", "resource", "moz-extension", "view-source"}


def wrapped(url: str) -> str | None:
    """The address an internal page shows the content of: what follows `view-source:`, or the
    `url` of Reader View (`about:reader?url=…`). None for every other address.

    Such a tab is at an address with no host of its own, but what it shows is another site's
    page, so the site list, the routes and the local-network check go by the inner address."""
    # As the engine reads an address: without the control characters and spaces around it.
    scheme, _, rest = url.strip("".join(map(chr, range(0x21)))).partition(":")
    scheme = scheme.lower()
    if scheme == "view-source":
        return rest
    if scheme == "about":
        name, _, query = rest.partition("?")
        if name.lower() == "reader":
            # Reader View takes the first `url`, empty or not (URL.searchParams.get).
            pairs = urllib.parse.parse_qsl(query.partition("#")[0], keep_blank_values=True)
            return next((value for key, value in pairs if key == "url"), None)
    return None


def subject(url: str | None) -> str | None:
    """The address whose site a tab at `url` is about: `url` itself, or the one it wraps."""
    if not url:
        return url
    for _ in range(2):  # a wrapper around a wrapper is refused by classify_url; this only has to end
        inner = wrapped(url)
        if inner is None:
            return url
        url = inner
    return url


def host_of(url: str | None) -> str | None:
    """The host the site list and the routes are checked against, for any address a tab can be at: None when there is
    no address (nothing, about:blank), "" when the address has no host (file:///…, about:…), which no site list holds."""
    url = subject(url)
    if not url or url == "about:blank":
        return None
    try:
        return urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""


NAT64 = ipaddress.IPv6Network("64:ff9b::/96")  # carries an IPv4 address a NAT64 gateway reaches


def _local_address(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text.strip("[]"))
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return not address.ipv4_mapped.is_global
        if address in NAT64:
            return not ipaddress.IPv4Address(int(address) & 0xFFFFFFFF).is_global
    return not address.is_global


def _resolves_locally(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        # Fail closed: the engine may resolve it where this process cannot (its own
        # resolver, DNS over HTTPS, a proxy), and then it may well be local.
        return True
    return any(_local_address(info[4][0]) for info in infos)


_IPV4_PART = re.compile(r"0[xX][0-9a-fA-F]*|[0-9]+")


def _ipv4_number(part: str) -> int | None:
    if not _IPV4_PART.fullmatch(part):
        return None
    if part[:2] in ("0x", "0X"):
        return int(part[2:] or "0", 16)
    if len(part) > 1 and part[0] == "0":
        return int(part[1:], 8) if re.fullmatch(r"[0-7]+", part[1:]) else None
    return int(part)


def _ends_in_number(host: str) -> bool:
    last = host.split(".")[-1]
    return bool(last) and (last.isdigit() or bool(re.fullmatch(r"0[xX][0-9a-fA-F]*", last)))


def _whatwg_ipv4(host: str) -> str | None:
    """The address a browser reads from a host ending in a number (127.1, 0x7f.0.0.1, 2130706433), or None.

    Python's ipaddress accepts only the dotted-quad form; the engine follows the URL
    standard, which accepts these too, so the check must read them the same way.
    """
    parts = host.split(".")
    if len(parts) > 4:
        return None
    numbers = [_ipv4_number(p) for p in parts]
    if any(n is None for n in numbers) or any(n > 255 for n in numbers[:-1]) or numbers[-1] >= 256 ** (5 - len(numbers)):
        return None
    value = numbers[-1]
    for index, number in enumerate(numbers[:-1]):
        value += number << (8 * (3 - index))
    return str(ipaddress.IPv4Address(value))


def canonical_host(host: str) -> str:
    """A host as the engine writes it in the requests it sends: lower case, punycode, no final dot, an
    IPv4 address dotted (127.1 is 127.0.0.1), an IPv6 address compressed. Unchanged when it reads as none."""
    host = host.lower().rstrip(".")
    if ":" in host:
        try:
            return ipaddress.IPv6Address(host.strip("[]")).compressed
        except ValueError:
            return host
    if _ends_in_number(host):
        return _whatwg_ipv4(host) or host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError:
        return host


def is_address(host: str) -> bool:
    """An IP address, in any form the engine reads as one: what it is needs no lookup."""
    host = host.strip("[]")
    return ":" in host or _ends_in_number(host.rstrip("."))


def local_host(host: str, resolve: bool = True) -> bool:
    """Whether a host, as the engine sends a request to it, is this computer or the local network.

    The engine's hosts are already canonical (punycode, IPv4 dotted, IPv6 bracketed); one that
    still ends in a number it could not read is taken as local, like a name that does not resolve."""
    host = host.lower().rstrip(".")
    if host.startswith("["):
        return _local_address(host)
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES) or _local_address(host):
        return True
    if _ends_in_number(host):
        ipv4 = _whatwg_ipv4(host)
        return ipv4 is None or _local_address(ipv4)
    return resolve and _resolves_locally(host)


def classify_url(url: str, resolve: bool = True) -> Target:
    """Which capabilities a navigation needs. Refuses what no capability can allow."""
    if len(url) > 8192 or any(ch < " " or ch == "\x7f" for ch in url) or url != url.strip():
        # The engine drops some of these and trims others: what is checked must be what is opened.
        raise UrlRefused("the address is too long, or has control characters or spaces around it")
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:  # an unclosed "[" in the host, for one
        raise UrlRefused("the address is not one the browser would open as written") from None
    scheme = parsed.scheme.lower()
    if url == "about:blank":
        return Target(url, None, ())
    if scheme in ("http", "https"):
        # The engine reads "\\" as "/" and decodes "%" in the host: refuse what this
        # parser would read differently, so the host checked is the host opened.
        if "\\" in url:
            raise UrlRefused("addresses with a backslash are not opened")
        if parsed.username or parsed.password or "@" in parsed.netloc:
            raise UrlRefused("addresses with a user name or password are not opened")
        if "%" in parsed.netloc:
            raise UrlRefused("addresses with an encoded host are not opened")
        try:
            host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError:
            raise UrlRefused("the address has a host the browser would read differently") from None
        if not host:
            raise UrlRefused("the address has no host")
        if ":" in host:
            try:
                ipaddress.IPv6Address(host)
            except ValueError:
                raise UrlRefused("the address has a host that is not a valid IPv6 address") from None
        elif not DNS_HOST.fullmatch(host) or "" in host.split("."):
            # Before any lookup: such a host never reaches a request, and a permission request would show its text.
            raise UrlRefused("the address has a host the browser would not look up")
        if ":" not in host and _ends_in_number(host):  # an IPv6 literal has its own syntax
            ipv4 = _whatwg_ipv4(host)
            if ipv4 is None:
                raise UrlRefused("the address has a host that is not a valid IPv4 address")
            host = ipv4
        local = host == "localhost" or host.endswith(LOCAL_SUFFIXES) or _local_address(host)
        if not local and resolve:
            local = _resolves_locally(host)
        return Target(url, host, ("local_resources",) if local else ())
    if scheme in INTERNAL_SCHEMES:
        inner = wrapped(url)
        if inner is not None:
            # The source viewer and Reader View show another address's content: the page is an
            # internal one (never offered to agents, like about:config), and the address inside is
            # checked as if it were opened itself, so it has a host for the site list.
            if wrapped(inner) is not None:
                raise UrlRefused("an address wrapped more than once is not opened")
            target = classify_url(inner, resolve)
            needs = ("local_resources", "debugging", *(n for n in target.needs if n not in ("local_resources", "debugging")))
            return Target(url, target.host, needs)
        # moz-extension: is the Shell's own pages (Settings, Vault, profiles). Internal pages, like
        # about:config: never offered to agents.
        privileged = scheme in ("chrome", "resource", "moz-extension", "view-source") or (
            scheme == "about" and url not in ("about:blank",)
        )
        return Target(url, None, ("local_resources", "debugging") if privileged else ("local_resources",))
    if scheme == "javascript":
        raise UrlRefused("javascript: addresses are not opened; scripts need the evaluate tool")
    raise UrlRefused(f"'{scheme or '?'}:' addresses are not supported")


def origin(url: str | None) -> str | None:
    """scheme://host[:port] for logs and permission requests: never the path or query. The host as the engine writes
    it (canonical_host: punycode, IPv4 dotted, IPv6 in brackets), never as an agent typed it."""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(subject(url))
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme in ("http", "https") and parsed.hostname:
        host = canonical_host(parsed.hostname)
        return f"{scheme}://[{host}]{port}" if ":" in host else f"{scheme}://{host}{port}"
    return f"{scheme}:" if scheme else None
