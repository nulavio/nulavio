# ADR 0004 — Nulavio Connect and the Integration Manager

- **Status:** Accepted (2026-10-25). **P0 discovery implemented (2026-10-26)**: `nulavio integrations` and Settings → Integrations. **P1/P2 implemented (2026-10-27)**, except activities ↔ workspaces and per-profile proxy (below).
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

## P0 implementation (2026-10-26)

- **One definition file**, `browser/config/integrations.json`, read by the launcher (`launcher/nulavio_launcher/connect.py`, `nulavio integrations [--json]`) and packaged into the Shell (`modules/NulavioConnect.sys.mjs`, Settings → Integrations).
- **Probes**, each an argument list with a timeout (Python `subprocess`, the engine's `Subprocess` module), never a shell: `busctl --user status|get-property` for D-Bus name owners and portal interface versions; `xdg-settings get` and `xdg-mime query default` for the default browser; the host manifest and program for Plasma Browser Integration, in the directories **this build reads** (`XREUserNativeManifests`, `XRESysNativeManifests`). A version or owner that is not reported is shown as "not reported", never guessed.
- **States** `enabled`, `available`, `unavailable`, `error`, `unknown`, each with a reason and the evidence lines shown under "How this was checked".
- **The only change** is "Make Nulavio the default browser": a confirmation, a user-level desktop entry (`net.nulavio.Nulavio.desktop`, `Exec` unquoted because `xdg-settings` does not unquote it), `xdg-settings set`, a check that it took effect, and the previous browser kept for "Restore".
- **Finding:** the engine reads system native-messaging hosts from a directory fixed at build time (`/usr/lib64/mozilla` only when `libdir` contains `lib64`). Without `--libdir=/usr/lib64` the Nulavio build did not see Fedora's Plasma Browser Integration host; the mozconfig now sets it, and the Integrations page says so plainly when a host is installed where the build does not read ("not-read"). A Debian/Ubuntu package must build with `/usr/lib`.
- **Verification:** `tests/unit/test_connect.py` (real CLI, private D-Bus bus, fake services, read-only proof) and `tests/integration/test_connect.py` (inside the browser: discovery, make default and restore in a throwaway home, settings page, the real desktop's `mimeapps.list` and `kdeglobals` hashed before and after).

## P1/P2 implementation (2026-10-27)

- **One implementation** for P1/P2 probes, in the Nulavio tools (`launcher/nulavio_launcher/connect_p1.py`): `nulavio integrations` prints them and the browser asks for them (`nulavio integrations api`), with a stable reason code per state so Settings → Integrations translates them. P0 probes keep running inside the browser.
- **KDE Connect**: the daemon's D-Bus name and the devices `kdeconnect-cli --list-available` reports. **Send link to device** in the link menu lists the devices reachable when the menu opens and shares that one address with that one device (`kdeconnect-cli --device … --share …`, an argument list); only http(s) links; never in private windows; nothing is sent otherwise.
- **Screen sharing**: the portal's ScreenCast version and a running PipeWire; the desktop asks the user which screen or window every time.
- **Security keys and passkeys**: hidraw devices whose HID report descriptor carries the FIDO usage page (0xF1D0), and whether this user may open them (udev rules); status only. It is also the first check of the planned security-key unlock (S10).
- **Notifications**: the desktop's notification service and portal.
- **KRunner**: an optional plugin, "Add to KRunner" in Settings: two user-level files (a D-Bus runner entry in `~/.local/share/krunner/dbusplugins/` and a session-bus activation file) and a small service (`nulavio integrations krunner-serve`, Python GLib bindings, started on demand, gone after five idle minutes). Typing an address offers "Open … in Nulavio"; "nulavio <words>" offers a search. Running a match opens it like a link from any app, so Smart Profile Routing chooses the profile. "Remove from KRunner" deletes both files.
- **Plasma activities**: detected and reported as not used. Mapping profiles to activities waits until it can be done as an explicit choice (the brief forbids inferring profiles from the desktop's state without consent).
- **MPRIS** is the engine's own (media keys and the desktop's media controls); **per-profile proxy** is already per profile in the engine's connection settings, and Guard reports proxy changes made outside the browser. Nulavio adds no separate adapter for either.
- **Verification**: `tests/unit/test_connect_p1.py` (FIDO descriptors in a fake sysfs, refusals, one link to one device, plugin files, the runner answering KRunner's `Match`/`Run` on a private session bus) and `tests/integration/test_connect.py` 05–06 (the states in the browser, sending a link through a stand-in `kdeconnect-cli`, adding and removing the plugin).

## Risks

| Risk | Mitigation |
|---|---|
| Plasma Browser Integration registers for "Firefox" by name | Verified: manifests are read from the Firefox path in rebranded builds; the extension's AMO ID works with Nulavio's Firefox app ID |
| Portals differ between KDE and GNOME | Discovery reads interface versions; features degrade to the engine's default dialogs |
| D-Bus probing reveals too much | Only the owner of a few named services (its program name) and the `version` property of portal interfaces; no monitoring, no calls into services (a past experiment that captured other apps' traffic is not repeated) |
| Default-browser change is intrusive | Offered, never automatic; `xdg-settings` is called with an argument list, no shell |
