# ADR 0004 — Nulavio Connect and the Integration Manager

- **Status:** Accepted (2026-10-25). Interfaces and discovery defined; adapters staged (M6–M7).
- **Related:** [trust boundaries](../architecture/trust-boundaries.md), [password providers](../architecture/password-providers.md).

## Context

Nulavio targets Fedora KDE Wayland first, then Ubuntu KDE and GNOME. Several integrations already work through the engine without Nulavio code:
- **XDG portals:** file chooser, screen cast via PipeWire, notifications;
- **native messaging:** KDE Plasma Browser Integration, KeePassXC, Bitwarden, read from `~/.mozilla/native-messaging-hosts` even in a rebranded build (ADR 0001 E16a);
- **Secret Service / KWallet** detection already in `nulavio doctor`.

What is missing is one place that shows what is **really** available, lets the user switch it on or off, and explains failures.

## Decision

1. **One adapter per integration, behind a narrow interface.** Discovery is read-only and uses only official protocols:
   - D-Bus `org.freedesktop.DBus.NameHasOwner` and portal interface versions;
   - freedesktop MIME defaults (`xdg-settings get default-web-browser`, `xdg-mime query default x-scheme-handler/https`);
   - files the integration itself owns (native-messaging manifests).

   No health check is invented: an adapter reports `unknown` when it cannot know.
2. **Least privilege:**
   - no blanket session-bus access, no filesystem scanning, no continuous clipboard reads;
   - nothing is sent to synced devices (KDE Connect) without an explicit action per link;
   - no SSID, location, active window or process list is used for profile decisions unless the user consents to that specific signal.
3. **Where adapters run:**
   - Track A: in the launcher (`nulavio_launcher/connect/`);
   - Track B: discovery through the launcher CLI (`nulavio integrations`); in-browser status through the Shell later (M7).
4. **Priorities:**
   - **P0:** Plasma Browser Integration, XDG portals, Secret Service/KWallet (status only; Nulavio stores no web secrets there), default browser and URL handlers;
   - **P1:** KRunner profile commands, KDE Connect (explicit "send link"), PipeWire screen-cast status, passkeys/FIDO2 (status), notifications;
   - **P2:** MPRIS, Plasma activities ↔ workspaces, per-profile proxy.

## Interface

```python
class Integration(Protocol):
    id: str                       # "kde-browser-integration", "xdg-portal", ...
    title: str
    priority: Literal["P0", "P1", "P2"]
    permissions: tuple[str, ...]  # human-readable, shown before enabling
    def discover(self) -> Status  # read-only; no side effects
    def enable(self, profile: str | None) -> Status   # may require a user step; never silent
    def disable(self, profile: str | None) -> Status  # always possible; revokes what enable did

@dataclass
class Status:
    state: Literal["available", "unavailable", "enabled", "error", "unknown"]
    detail: str                   # user-facing, no secrets, no URLs
    evidence: str                 # what was checked (e.g. "D-Bus name org.kde.plasma.browser_integration owned")
```

## Risks

| Risk | Mitigation |
|---|---|
| Plasma Browser Integration registers for "Firefox" by name | Verified: manifests are read from the Firefox path in rebranded builds; the extension's AMO ID works with Nulavio's Firefox app ID |
| Portals differ between KDE and GNOME | Discovery reads interface versions; features degrade to the engine's default dialogs |
| D-Bus probing reveals too much | Only `NameHasOwner` for named services; no monitoring (a past experiment that captured other apps' traffic is not repeated) |
| Default-browser change is intrusive | Offered, never automatic; `xdg-settings` is called with an argument list, no shell |
