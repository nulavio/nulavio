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
| FR-09 | Ad and tracker blocking on first run, reversible per site | **Done** (uBO + ETP Strict; per-site toggles are upstream UI) | `test_03`, `test_08` |
| FR-10 | Proton Pass official extension works | **Preview**: install, signature, background, popup Done; **login and autofill on a real site done on the maintainer's desktop** (2026-10-25) | `test_password_extensions` |
| FR-11 | KeePassXC-Browser works with native messaging | **Done (container)**: association + autofill end to end with KeePassXC 2.8.0, in CI. No manual desktop certification planned by the maintainer | `keepassxc_native_messaging_spike.py` |
| FR-12 | Bitwarden official extension works | **Preview**: install, signature, background, popup Done; desktop-app host name verified in Bitwarden's source. No manual certification planned by the maintainer | `test_password_extensions` |
| FR-13 | Choose the credential provider; only one autofills | **Preview** (CLI `provider set`) | provider unit tests |
| FR-14 | User can install their own extensions | **Done** (engine/AMO) | E4 normal installs |
| FR-15 | Settings essentials explained | **Preview** (`nulavio prefs explain`; engine settings UI) | — |
| FR-16 | Private window | **Done** (engine; `nulavio run --private`) | engine unit test |
| FR-17 | Onboarding | **Prototype** (CLI plan + flows in [ux-flows](../brand/ux-flows.md)) | — |
| FR-18 | Privacy dashboard / per-site panel | **Prototype** (mockups) | — |
| FR-19 | Environment and profile diagnostics | **Done** (`nulavio doctor`) | manual |
| FR-20 | Desktop integration without root | **Done** (`nulavio desktop install/uninstall`) | desktop unit tests |
| FR-21 | Search engine choice: privacy-focused providers, SearXNG instance, custom URL or OpenSearch, aliases, separate private default, add/remove in the UI | **Done (Track B)** ([ADR 0002](../adr/0002-nulavio-search.md)). Track A: upstream Settings | `test_search` 04, 06–10, 12 |
| FR-22 | Smart Profile Routing (explicit rules, host > domain > policy > stay) | **Done (Track B) for links from other apps** (M4a): decided before any request, conservative failure, ask first, rules editor, "Always open this site in this profile". **Typed addresses** routed on Enter (M4b); in-page links move only by an explicit "Open link in profile"; automatic in-page routing: Planned (M5, after a security review) | `test_routing` |
| FR-23 | Integration Manager (KDE, portals, Secret Service, default browser) with real discovery | **Planned** ([ADR 0004](../adr/0004-nulavio-connect.md)) | — |

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

## Non-functional

| ID | Requirement | Status |
|---|---|---|
| NFR-01 | Accessibility: keyboard, screen readers, scaling, contrast WCAG AA | Tokens AA-verified (78 pairs); engine a11y upstream; Nulavio pages semantic HTML |
| NFR-02 | Performance comparable to the engine (no extra processes at runtime) | Launcher exits via `exec`; zero runtime overhead |
| NFR-03 | Zero third-party runtime dependencies in the launcher | Done (Python stdlib) |
| NFR-04 | Reproducible brand assets | Done (generators + determinism tests) |
| NFR-05 | Works offline after setup | Done (start page local; uBO ships lists) |
