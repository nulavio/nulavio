# Architecture overview

Nulavio is a Gecko-based browser ([ADR 0001](../adr/0001-engine-selection.md)) built as a set of modules with explicit trust boundaries. Two delivery tracks share the same configuration: **Track A** (preview: launcher + profile layer over the distribution's unmodified Firefox) and **Track B** (Nulavio source build).

```
                    ┌──────────────────────────── user session (same UID) ───────────────────────────┐
                    │                                                                                 │
  desktop entry ──▶ │  Nulavio Shell launcher (Track A)          Nulavio Guard (pre-launch audit)     │
  (nulavio-preview) │   bin/nulavio → launcher/nulavio_launcher   browser/config/guard-rules.json     │
                    │        │ prepares profile, validates URL, strips risky env, execs engine        │
                    │        ▼                                                                         │
                    │  ┌─────────────── Nulavio Core = Gecko engine (root-owned package) ───────────┐ │
                    │  │ parent process (UI, network, profile I/O)                                  │ │
                    │  │   ├── content processes (one site each, seccomp + userns)  ◀── web (TB1)   │ │
                    │  │   ├── extension process  ◀── uBlock Origin (Nulavio Filter), password mgrs │ │
                    │  │   └── RDD / utility / socket / GPU processes (sandboxed)                   │ │
                    │  └─────────────┬────────────────────────────────────────────────────────────────┘ │
                    │                │ native messaging (stdio)  ──▶ keepassxc-proxy (Nulavio Bridge)  │
                    │                ▼                                                                  │
                    │  profile: $XDG_DATA_HOME/nulavio/profiles/<name>  (0700)  + nulavio/settings.json │
                    └─────────────────────────────────────────────────────────────────────────────────┘
```

## Modules

| Module | Responsibility | Track A (now) | Track B (planned) | Interface | Tests |
|---|---|---|---|---|---|
| **Nulavio Core** | Web engine, sandbox, site isolation, network, WebExtensions | Distribution Firefox, unmodified | Firefox release source + minimal patch stack, own branding | Engine command line (allow-listed), prefs, policies | `tests/integration/test_engine_slice.py` |
| **Nulavio Shell** | Identity, launcher, start page, onboarding, settings UI, chrome theme | `launcher/` CLI, `browser/startpage/`, `browser/theme/userChrome.css` | **Horizon window theme** (tab strip, toolbar, address bar; `content/theme/`, loaded by patch 0003) and **built-in add-on `shell@nulavio.net`** (`browser/shell/`): new tab, download warning, search settings (patch 0004 enforces per-provider consent for suggestions) and the profile selector (done; [ADR 0002](../adr/0002-nulavio-search.md), [ADR 0003](../adr/0003-nulavio-profiles-and-routing.md)); Privacy Center, profile routing, integrations and onboarding next ([design](../design/architecture.md)) | CLI; generated local pages; Shell pages (`moz-extension://`) | unit + `test_01`, `test_shell`, `test_search`, `test_profiles` |
| **Nulavio Filter** | Ad/tracker blocking | Pinned uBlock Origin + ETP Strict | Same, installed via `ExtensionSettings` policy; own UI surfaces for per-site state | `extensions.lock.json` | `test_08` |
| **Nulavio Guard** | Secure defaults, detection of weakening, permission and download policies | Pre-launch pref audit; `doctor` | Runtime component (built-in add-on): download warnings (flow E, **done** in the Shell); changes made outside the browser since the last run (**done**, S13); permission review next | `guard-rules.json`; findings | guard unit tests, `test_10` |
| **Nulavio Bridge** | Contracts with password managers and the Linux desktop | Provider selection; native messaging manifest checks | Provider certification, onboarding chooser, Secret Service status | `providers.json` | provider unit tests, extension smoke tests |
| **Nulavio Settings** | Readable, auditable per-profile configuration | `nulavio/settings.json` (0600) + annotated prefs | Same, surfaced in the settings UI | JSON schema v1 | profile unit tests |
| **Nulavio Build/Release** | Builds, SBOM, verification, packaging | `sbom.py`, `verify_firefox_release.py`, CI | Container builds, RPM/DEB, signing, update SLA | CI workflows | CI |

## Configuration flow (single source of truth)

```
browser/config/prefs/baseline.js ──┬─▶ Track A: seed → prefs.js (once), enforce → user.js (each launch)
browser/config/providers.json    ──┤
browser/config/guard-rules.json  ──┤─▶ Track B: generated distribution/policies.json + defaults/pref/nulavio.js
browser/distribution/extensions.lock.json ─┘
docs/brand/tokens.json ──▶ scripts/brand/build_tokens.py ──▶ browser/startpage/tokens.css (and Track B themes)
```

## Data the project stores, and where

| Data | Location | Mode | Leaves the machine? |
|---|---|---|---|
| Engine profile | `$XDG_DATA_HOME/nulavio/profiles/<name>/` | 0700/0600 | Only through normal browsing and opt-in sync |
| Nulavio settings | `<profile>/nulavio/settings.json` | 0600 | Never |
| Launcher log | `$XDG_STATE_HOME/nulavio/launcher.log` (JSONL, redacted) | 0600 | Never |
| Verified XPI cache | `$XDG_CACHE_HOME/nulavio/xpi/<sha256>.xpi` | 0600 | Never |
| Desktop entry and icons | `$XDG_DATA_HOME/applications`, `$XDG_DATA_HOME/icons` | 0644 | Never |

There is no Nulavio server. Nothing is sent to the project.

## Process model notes (verified on Firefox 158, Fedora 44)

- Web content, RDD, utility and socket processes each run with seccomp-bpf on every thread and their own user namespace. The fork server (spawner) is not sandboxed by design.
- The window's Wayland app_id is `nulavio-preview` (via `MOZ_APP_REMOTINGNAME`, `--name` and `--class`), so KDE associates it with `nulavio-preview.desktop`.
- A second `nulavio run` for a running profile is forwarded to the running instance through the engine's remoting.
