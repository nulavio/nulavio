# Requirements

Status legend: **Done** (implemented and verified by a test or recorded evidence) · **Preview** (works in Track A with limits) · **Prototype** (design or mock only) · **Planned** · **Blocked** (named cause).

## Functional

| ID | Requirement | Status | Verification |
|---|---|---|---|
| FR-01 | Starts on Fedora KDE Wayland with upstream sandbox active | **Done** (Track A) | `test_04`; real-window check (ADR E3) |
| FR-02 | Navigation, URL bar, search, back/forward/reload | **Done** (engine UI) | `test_05` |
| FR-03 | Tabs | **Done** | `test_05` |
| FR-04 | Downloads, saved privately, no auto-open | **Done**. Track B adds the executable-download warning (flow E) | `test_07`, `test_shell` 03–05 |
| FR-05 | Isolated Nulavio profile, separate from Firefox profiles | **Done** | `test_09`, registry hashes, path unit tests |
| FR-06 | Multiple profiles (work/personal) | **Done (Track B)**: engine profiles with Nulavio templates, toolbar selector (Alt+Shift+P), one-click switch, edit, delete with confirmation ([ADR 0003](../adr/0003-nulavio-profiles-and-routing.md)). Track A: CLI `--profile` | `test_profiles`, profile unit tests |
| FR-07 | Nulavio identity: icon, app name in the desktop, start page | **Done in Track B** (engine UI says Nulavio in English and Portuguese, About dialog, new tab, Horizon window theme). Track A preview: desktop entry, app_id, start page, chrome theme; engine UI says Firefox | `test_01`, `test_13`, `test_15`, ADR E3 |
| FR-08 | New tab with Nulavio identity | **Done (Track B)**: built-in Nulavio Shell new tab with search and live protection status. Track A: start page on launch and Home | `test_shell` 01–02 |
| FR-09 | Ad and tracker blocking on first run, reversible per site | **Done** (uBO + ETP Strict; per-site toggles are upstream UI). Track B: Strict set once per profile by the Shell (the build's default alone was recomputed to Standard until 2026-10-26) | `test_03`, `test_08`, `test_privacy` |
| FR-10 | Proton Pass official extension works | **Preview**: install, signature, background, popup Done; **login and autofill on a real site done on the maintainer's desktop** (2026-10-25) | `test_password_extensions` |
| FR-11 | KeePassXC-Browser works with native messaging | **Done (container)**: association + autofill end to end with KeePassXC 2.8.0, in CI. No manual desktop certification planned by the maintainer | `keepassxc_native_messaging_spike.py` |
| FR-12 | Bitwarden official extension works | **Preview**: install, signature, background, popup Done; desktop-app host name verified in Bitwarden's source. No manual certification planned by the maintainer | `test_password_extensions` |
| FR-13 | Choose the credential provider; only one autofills | **Done (Track B)**: Settings → Passwords (real state, pinned official extension installed after one confirmation, browser prompts off; disable integration keeps the extension). Track A: CLI `provider set` | provider unit tests, `test_passwords` |
| FR-14 | User can install their own extensions | **Done** (engine/AMO) | E4 normal installs |
| FR-15 | Settings essentials explained | **Preview** (`nulavio prefs explain`; engine settings UI) | — |
| FR-16 | Private window | **Done** (engine; `nulavio run --private`) | engine unit test |
| FR-17 | Onboarding | **Prototype** (CLI plan + flows in [ux-flows](../brand/ux-flows.md)) | — |
| FR-18 | Privacy dashboard / per-site panel | **Done (Track B)**: the engine's site panel (real blocked-tracker log, per-site switch, clear site data) and Settings → Site exceptions (all exceptions, removable; uBlock Origin's own list opened, never edited) | `test_privacy` |
| FR-19 | Environment and profile diagnostics | **Done** (`nulavio doctor`) | manual |
| FR-20 | Desktop integration without root | **Done** (`nulavio desktop install/uninstall`) | desktop unit tests |
| FR-21 | Search engine choice: privacy-focused providers, SearXNG instance, custom URL or OpenSearch, aliases, separate private default, add/remove in the UI | **Done (Track B)** ([ADR 0002](../adr/0002-nulavio-search.md)). Track A: upstream Settings | `test_search` 04, 06–10, 12 |
| FR-22 | Smart Profile Routing (explicit rules, host > domain > policy > stay) | **Done (Track B) for links from other apps** (M4a): decided before any request, conservative failure, ask first, rules editor, "Always open this site in this profile". **Typed addresses** routed on Enter (M4b); in-page links move only by an explicit "Open link in profile"; automatic in-page routing: Planned (M5, after a security review) | `test_routing` |
| FR-23 | Integration Manager (KDE, portals, Secret Service, default browser) with real discovery | **Done** ([ADR 0004](../adr/0004-nulavio-connect.md)): P0 `nulavio integrations`, Settings → Integrations, default browser on request with restore; P1/P2: KDE Connect send link, KRunner plugin, screen sharing, security keys, notifications, activities (status) | `test_connect`, `test_connect_p1` |
| FR-24 | Encrypted profiles at rest with real lock/unlock (Nulavio Vault) | **Done for launcher profiles (S5)**: `nulavio vault create/encrypt/unlock/lock/status`, `nulavio run` unlocks, runs and locks; browser-group profiles are recognised as locked (selector, switching, routing). Unlocking and creating protected profiles from the browser UI: done (S6) | `test_vault`, `test_vault_storage`, `test_vault_profiles`, `test_vault_ui` |
| FR-25 | Unlock with the phone (biometrics/PIN), OS authentication, profile password or FIDO2 key; recovery code and second device | **Prototype (S3, artificial data):** password, recovery code, OS keyring and password + phone work; phone protocol `nv1` runs end to end against a simulated phone (second phone, revocation). Not shipped: UI (S6), phone app (S11), security key (S10) | `test_vault` |
| FR-26 | AI Bridge: MCP for external agents with per-agent autonomy (Restricted, Assisted, Autonomous, Full control), revocable and audited | **Foundation done (S4)** ([ADR 0007](../adr/0007-ai-bridge.md)): `nulavio ai`, MCP server (2025 and 2026-07-28 protocols), per-agent AI Workspace, four levels with per-capability grants, revoke, emergency stop, audit; real Claude Code tested. Settings → AI & Automation, permission requests in the browser, pause, dialogs/downloads/uploads: done (S7). Given profiles, per-agent routes and the connect wizard: done (S8) | `test_ai_bridge` (unit, engine), `test_ai_ui`, `test_ai_agents_real` |
| FR-27 | Built-in AI assistant, provider-agnostic, under the same policies as external agents | **Done (Track B, S20)**: side panel and settings; OpenAI-compatible (including local models) or Anthropic; key in the system keyring; per-profile consent; page text only when included; tasks as an agent under the same policy | `test_assistant`, `test_assistant_ui` |
| FR-28 | Temporary profile, deleted when it closes | **Done**: "New temporary window" in the selector and Settings (Track B), `nulavio run --temporary` (both tracks); in memory where the system allows, deleted by the Nulavio tools after its instance exits ([ADR 0003](../adr/0003-nulavio-profiles-and-routing.md#temporary-profile-implementation)) | `test_temporary` (unit, engine) |
| FR-29 | Explicit DNS choice: the computer's resolver or encrypted DNS through a resolver the user picks; nothing to a Nulavio server | **Done (Track B)**: new-tab question (asked once) and Settings → DNS; the text follows the engine's effective mode | `test_dns` (local DoH resolver: lookups reach it; encrypted-only fails closed; system mode sends nothing to it) |

## Security and privacy

| ID | Requirement | Status | Verification |
|---|---|---|---|
| SEC-01 | Never disable sandbox, site isolation, TLS checks, Safe Browsing, updates | **Done** | forbidden-pref tests, Guard rules |
| SEC-02 | No telemetry to Nulavio (there is no server); upstream telemetry off by default | **Done** | `test_02` |
| SEC-03 | HTTPS-Only with clear, revocable exceptions | **Done** | `test_06` |
| SEC-04 | Profile dirs 0700 / files 0600 | **Done** | `test_09` |
| SEC-05 | Logs without secrets, tokens, cookies or URLs | **Done** | redaction tests |
| SEC-06 | No silent installation of arbitrary extensions | **Done** (only the disclosed default; explicit commands) | lock tests |
| SEC-07 | Pinned, verified inputs (extensions, source releases) | **Done** | integrity tests, `verify_firefox_release.py` |
| SEC-08 | Crashes never auto-submitted | **Done** | `test_02` |
| SEC-09 | Conservative failure: refuse to launch weakened profiles | **Done** (Guard critical) | `test_10` |
| SEC-10 | Never fill credentials without origin validation and user action | **Planned** (provider certification + flow D) | — |
| SEC-11 | Contextual, revocable device permissions | **Done** upstream; dashboard Planned | — |
| SEC-12 | SBOM | **Done** (CycloneDX for the preview) | `scripts/release/sbom.py` |
| SEC-13 | Signed artefacts and secure updates | **Planned** (Track B) | — |
| SEC-14 | What you type in the address bar is not sent anywhere without consent; consent is per search provider | **Done (Track B)**; Track A: remote suggestions and trending off (one global switch upstream) | `test_search` 02, 03, 05 |
| SEC-15 | Profiles never share cookies or site storage; a running profile is not deleted; switching never starts a duplicate instance | **Done (Track B)** | `test_profiles` 05 |
| SEC-16 | An unlock opens a profile only when a method releases its key: no method, a phone approval without the key, or a copy of the files does not reveal it; requests expire, are one-shot and signed; nothing secret in logs or files | **Done in the prototype (S3, simulated phone)**; applies to real profiles from S5 | `test_vault` |
| SEC-17 | An agent gets only what the user granted: decisions come from the user's configuration on every call, never from the agent or page content; the local network needs a grant; revocation and the emergency stop apply to the next call; the agent's workspace keeps Safe Browsing and the pop-up blocker on | **Done (S4)** | `test_ai_bridge` |
| SEC-18 | Report changes made to a profile outside the browser (extensions, protective settings, certificate authorities, security modules, native-messaging hosts, policies, `user.js`, search) and let the user undo or keep each | **Done (Track B)**: Guard at run time, with a bypass analysis; detection, not prevention ([R38](../security/residual-risks.md)) | `test_guard`, `test_shell.GuardModuleTest` |

## Non-functional

| ID | Requirement | Status |
|---|---|---|
| NFR-01 | Accessibility: keyboard, screen readers, scaling, contrast WCAG AA | Tokens AA-verified (78 pairs); engine a11y upstream; Nulavio pages semantic HTML |
| NFR-02 | Performance comparable to the engine (no extra processes at runtime) | Launcher exits via `exec`; zero runtime overhead |
| NFR-03 | Zero third-party runtime dependencies in the launcher | Done (Python stdlib; no pip packages). The Vault loads the system libsodium through `ctypes` (decision D1), listed in the SBOM |
| NFR-04 | Reproducible brand assets | Done (generators + determinism tests) |
| NFR-05 | Works offline after setup | Done (start page local; uBO ships lists) |
