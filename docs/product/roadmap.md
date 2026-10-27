# Roadmap

Each milestone has a definition of done (DoD). "Done" requires the DoD to be verified, not just the UI to exist.

## Phase 0 — Discovery, feasibility, engine ADR · **complete (2026-10-24)**

- [x] Environment inventory (Fedora 44 KDE 6.7.5 Wayland, Firefox 158.0.1, Qt 6.11.2, 16 threads, 30 GiB, 325 GB free)
- [x] Gecko spike: vertical slice + password-manager extension smoke tests
- [x] Qt WebEngine spike: MV3 loading works, enabling crashes (not isolated), documented limits
- [x] [ADR 0001](../adr/0001-engine-selection.md) with evidence, risks, reversal criteria
- [x] Source-release verification with a pinned Mozilla key

**DoD:** ADR accepted with reproducible evidence ✔

## Phase 1 — Foundation and branding · **complete except trademark search**

- [x] Repo structure, docs, threat model, policies
- [x] Brand strategy, 3 directions, selection, tokens (AA-verified), logo family, icons 16–512, symbolic, favicon
- [x] CI workflow (lint, unit tests, token/asset freshness, headless integration)
- [x] CI integration job rehearsed locally in a Fedora 44 container (rootless podman, default seccomp): 14/14
- [x] CI on GitHub (private repository `caiolombello/nulavio`): green on 2026-10-25 for lint, unit tests and the Fedora/Ubuntu integration matrix, including the KeePassXC end-to-end test
- [x] **Track B build spike in a container**: ≈ 52 min, 23 GB, branded binary passes 14/15 (Safe Browsing key pending) — [build.md](../architecture/build.md)
- [x] Ubuntu userspace check (Mozilla APT Firefox): 15/15
- [x] Domain `nulavio.net` registered by the maintainer (2026-10-25)
- [x] Domain live and hardened: https://nulavio.net (static site, no scripts or cookies), DNSSEC, TLS ≥ 1.2, DMARC `p=reject`, `security@nulavio.net` and `/.well-known/security.txt` (2026-10-25)
- [ ] Trademark search (INPI, USPTO/EUIPO) and handles, by the maintainer or counsel

**DoD:** CI green on a fresh clone; measured Track B build numbers recorded in the ADR.

## Phase 2 — Browser vertical slice · **Track A done; Track B dev build done**

- [x] Nulavio Shell UI, M0–M2 first slice: audit, three directions, Horizon chosen, window theme for tab strip, toolbar and address bar (Track B). Next milestones: [design migration plan](../design/migration-plan.md)

- [x] Track A: launcher, isolated profile, start page, desktop identity, chrome theme
- [x] Track B inputs: `browser/branding/nulavio/` + generated assets, `browser/build/mozconfig`, patch stack (`browser/patches/`, 5 patches: vendor name, l10n mapping of the branding, Horizon stylesheet link, per-provider consent for search suggestions, address-bar routing hook), container build script
- [x] `distribution/` generated from `browser/config/` (`distribution.ini` defaults + `policies.json`), verified active in the build (`test_13`)
- [x] Google Safe Browsing API key from a secret: dedicated Google Cloud project, key restricted to the Safe Browsing API, build passes 17/17 incl. the end-to-end phishing test
- [x] Nulavio Shell built-in add-on (`browser/shell/`), built from the branding directory with no Mozilla file patched
- [x] New tab (FR-08): search with the default engine, live protection status read from the browser settings
- [x] Flow E executable-download warning (compensates R15): Show in folder / Delete, no Open
- [ ] Google's download-protection API for Track B (request access) (R15)
- [ ] Flow E inside the engine's downloads panel (needs engine UI work; today a Nulavio page opens next to it)
- [x] Track B in Portuguese: en-US + pt-BR packaged from signed-off firefox-l10n revisions, brand translated, follows the desktop language

**DoD:** a branded Nulavio binary built from verified source opens a window on Fedora KDE Wayland with the sandbox verified by `test_04`, with no Mozilla marks in the UI.

## Phase 2b — Search, profiles, routing and integrations ([ADR 0002](../adr/0002-nulavio-search.md), [0003](../adr/0003-nulavio-profiles-and-routing.md), [0004](../adr/0004-nulavio-connect.md))

- [x] Nulavio Search: DuckDuckGo default (normal and private, only where the default was still the app's), Brave and Mojeek added with aliases, Kagi and SearXNG on request (never a public instance), custom URL and OpenSearch, add/remove in Nulavio settings
- [x] No typed text leaves without consent: suggestions and trending off; per-provider consent enforced at the single fetch point (patch 0004); measured on the real engine (`test_search`)
- [x] Nulavio Profiles: engine profiles with templates (Personal, Work, Banking, Research), toolbar selector with the profile's colour and initial, Alt+Shift+P, one-click switch, rename/icon/colour, delete with confirmation; isolation and no duplicate instance measured (`test_profiles`)
- [x] Smart Profile Routing M4a: decision engine (precedence, IDN, Public Suffix List) + links from other apps routed before any request, with ask-first and conservative failure pages, rules editor and "Always open this site in this profile" (`test_routing`)
- [x] Smart Profile Routing M4b: typed addresses routed on Enter (patch 0005), "Open link in profile" in the link menu (`test_routing` 11–14)
- [ ] Smart Profile Routing M5: automatic routing of in-page navigation, only after a security review
- [x] Temporary profile (deleted on close): in memory where the system allows, deleted by the Nulavio tools when its instance exits; selector, Settings and `nulavio run --temporary` (`test_temporary`)
- [x] Nulavio Connect P0: `nulavio integrations` and Settings → Integrations (Plasma Browser Integration, portals, secret storage, default browser) with evidence; "Make Nulavio the default browser" on request, with restore (`test_connect`)
- [ ] Nulavio Connect P1/P2: KRunner, KDE Connect send link, screen-cast status, passkeys status, notifications; MPRIS, activities, per-profile proxy

**DoD:** each item verified on the Nulavio build by an integration test that uses the engine's real services.

## Phase 2c — Secure Profiles: Vault and unlock · **planned** ([brief](briefs/2026-10-26-profile-unlock.md), [execution plan](execution-plan.md) S2, S3, S5, S6, S10, S11)

Unlock encrypted profiles with, in order of convenience: the phone (biometrics/PIN), the operating system, the profile's own password, or a FIDO2 security key. A successful authentication only unlocks data if it takes part in releasing the key. Components: Nulavio Vault, Unlock Coordinator, Platform Key Provider, Phone Unlock, Hardware Key Provider. This is not a passkey manager for websites and does not change WebAuthn for pages.

- [x] U0 Repository audit (no Vault code existed; tooling inventory in the [execution plan](execution-plan.md))
- [x] U1 Study: WebAuthn hybrid + PRF vs Nulavio Companion vs approval-only ([compatibility report](../research/phone-unlock-compatibility.md))
- [x] U2 [ADR 0005](../adr/0005-phone-profile-unlock.md): Nulavio Companion, protocol `nv1`, cancellation criteria
- [x] U3 [Threat model for unlock](../security/threat-model-unlock.md) and [ADR 0006](../adr/0006-nulavio-vault.md) key management; [architecture](../architecture/vault-and-unlock.md)
- [x] U4 Cryptographic unlock prototype with artificial data (password, recovery code, OS keyring, password + phone) — `launcher/nulavio_launcher/vault/`, [ADR 0006](../adr/0006-nulavio-vault.md#implementation-s3-2026-10-26)
- [x] U5 Desktop–phone pairing proof with a simulated phone (`tests/lib/phone_reference.py`); the real device comes in U6
- [ ] U6 Android Companion POC (Keystore, BiometricPrompt) — **last slice**; free software for F-Droid first, Play Store later; test device Galaxy S24+ (Android 17)
- [ ] U7 Recovery, replay and lost-device tests — done with the simulated phone (`test_vault`); repeat on the real device in U6
- [x] U8 Integration with Gecko profiles (encrypted profile container; lock = instance ended and container closed) — S5: launcher profiles end to end (`nulavio vault`, supervised `nulavio run`); browser-group profiles recognised as locked by the selector and routing
- [x] U9 UX: onboarding in three decisions, locked profile, recovery (S6, `browser/shell/vault/`); phone devices come with U6
- [ ] U10 iOS and Windows evaluation
- [ ] U11 Hardening and independent audit

**DoD:** a profile does not unlock without a valid method; copying its files does not reveal the key; at least two recovery methods work before phone unlock ships; the protection-state matrix (`encrypted_at_rest`, `os_user_protected`, `password_protected`, `hardware_bound`, `phone_approved`, `phone_key_release_verified`) shows only what is really in place.

## Phase 2d — AI Bridge, agent autonomy and browser automation · **planned** ([brief](briefs/2026-10-26-ai-bridge.md), [execution plan](execution-plan.md) S4, S7, S8)

External agents (Codex CLI and Desktop, Claude Code and Desktop, other MCP clients) and, later, a built-in assistant use the browser through one policy decision point outside the model. Safe by default (isolated AI Workspace profile), with autonomy the user can grant up to full control; grants are honoured as given, visible and revocable.

- [x] A0 Audit (engine, Shell, profiles, IPC, automation tests) — in [ADR 0007](../adr/0007-ai-bridge.md)
- [x] A1 [Compatibility matrix](../ai/compatibility.md): Nulavio MCP, WebDriver BiDi, Marionette, firefox-devtools-mcp, Playwright, Puppeteer, Selenium, CDP (documented / implemented / tested)
- [x] A2 [ADR 0007](../adr/0007-ai-bridge.md) AI Bridge; [architecture](../architecture/ai-bridge.md)
- [x] A3 [Threat model for automation and autonomy](../security/threat-model-ai.md) (incl. deliberately accepted risk)
- [x] A4 MCP server (`nulavio ai serve`) with 11 browser tools on a per-agent AI Workspace; tested with real Claude Code
- [x] A5 Gecko automation adapter (S7: dialogs, downloads per permission, uploads from a dedicated folder)
- [x] A6 Agent registry and sessions (S4/S7: token per agent, pause, new key, client evidence; stdio sessions)
- [x] A7 Permission and autonomy manager (per agent, site and duration; per profile in S8)
- [x] A8 Restricted, Assisted, Autonomous, Full control (with the full-control warning)
- [x] A9 Codex CLI and Claude Code connection wizard (S8: the agent's own CLI, after approval; key file, no secret in configs)
- [x] A10 Secure Profiles and Smart Profile Routing integration (S8: given profiles, per-agent routes, locked and open profiles refused)
- [x] A11 UX (Horizon): agents, autonomy, activity, revoke, emergency stop, permission requests (S7); agent detection and sessions view in S8
- [ ] A12 Built-in assistant (provider-agnostic, same policies)
- [ ] A13 Advanced compatibility (Playwright/CDP adapters where feasible)
- [ ] A14 Hardening, multi-platform tests, documentation

**DoD:** real clients (not mocks) connect and act within their grants; denied capabilities are denied; "Autonomous" does not ask again for granted actions; revocation stops new operations; no access to a locked profile; nothing in the UI claims isolation that is not there.

## Phase 3 — Privacy and blocking

- [x] uBO pinned and verified; ETP Strict; HTTPS-Only; reversibility tested. Correction (2026-10-26): in the Nulavio build the Strict category came only as a `distribution.ini` default, which the engine recomputes to Standard; since S14 the Shell sets it once per profile as a user value, and `test_privacy` checks every baseline pref of the build and a real blocked tracker
- [x] Per-site privacy panel with honest state: the engine's own site panel (address bar: connection, what tracking protection blocked from the engine's log, per-site switch, clear site data) plus Settings → Site exceptions (every site where a protection is off, removable; uBlock Origin's own trusted-sites page) (`test_privacy`)
- [ ] Real-site regression suite (top sites list, screenshot diff, breakage triage)
- [x] DoH onboarding choice (new tab asks once; Settings → DNS: computer's resolver, encrypted with fallback, encrypted only; Cloudflare, Quad9, Mullvad or own https:// resolver) (`test_dns`, local DoH resolver); fingerprinting regression analysis, measured ([fingerprinting](../research/fingerprinting.md), `test_privacy`)

**DoD:** blocking test + 50-site regression run with recorded breakage and per-site fixes.

## Phase 4 — Password integrations

- [x] Proton Pass on the maintainer's real desktop: installed through the launcher, signed in, autofilled a real site, engine manager off (2026-10-25)
- [ ] Proton Pass: unlock after restart, autosave, passkeys (checklist in [password-providers](../architecture/password-providers.md))
- [x] KeePassXC association + autofill end to end (Fedora 44 container, KeePassXC 2.8.0)
- [ ] KeePassXC on Ubuntu KDE and Flatpak KeePassXC: community testers (the maintainer does not use KeePassXC; container E2E runs in CI)
- [x] Bitwarden desktop-app native messaging host verified in Bitwarden's source
- [ ] Bitwarden login/autofill: community testers (the maintainer does not use Bitwarden)
- [ ] Provider chooser UI (flow B), suspicious-login interstitial (flow D)

**DoD:** checklist passes for the P0 providers on both distributions, or a blocker is recorded with its technical cause.

## Phase 5 — Hardening and anti-infostealer measures (with proven limits)

- [x] Guard runtime: changes made outside the browser since the last run (extensions, protective settings, certificate authorities, security modules, native-messaging hosts, policies, `user.js`, search engines), reviewed and undone or kept by the user; bypass analysis in [hardening](../security/hardening.md#guard-at-run-time-what-it-catches-and-how-it-can-be-bypassed) (`test_guard`)
- [ ] Spikes: bubblewrap, Flatpak and native-messaging portal, SELinux module
- [ ] Sensitive-sites container with clear-on-close

**DoD:** each control has a test and a documented bypass analysis.

## Phase 6 — Tests, packaging, alpha

- [ ] RPM (Fedora) with signed repository; DEB later
- [ ] Update SLA automation; security changelog
- [ ] Alpha only after [release criteria](release-criteria.md) are met

## Next task (recommended)

Follow the [execution plan](execution-plan.md): S1 (Connect P0), S2 (unlock research and ADRs), S3 (Vault crypto prototype), S4 (AI Bridge foundation), S5 (encrypted profile storage), S6 (unlock UX in the browser), S7 (AI autonomy and its UI), S8 (AI with profiles, routing and the connect wizard), S12 (temporary profile), S13 (Guard at run time), S14 (per-site privacy, Strict fix) and S15 (DNS choice, fingerprinting measured) are done; next: S16 (real-site regression suite) through S24 (alpha gate), with S10 (security key, needs a key) and S11 (Android Companion, last) waiting on the maintainer. The plan lists the decisions each slice needs from the maintainer.
