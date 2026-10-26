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
- [x] Track B inputs: `browser/branding/nulavio/` + generated assets, `browser/build/mozconfig`, patch stack (`browser/patches/`, 4 patches: vendor name, l10n mapping of the branding, Horizon stylesheet link, per-provider consent for search suggestions), container build script
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
- [ ] Smart Profile Routing M4a: decision engine (precedence, IDN, Public Suffix List) + external links routed before any request
- [ ] Smart Profile Routing M4b/M5: typed URLs, "Always open this site in this profile", rules editor, conflict dialog
- [ ] Temporary profile (deleted on close)
- [ ] Nulavio Connect: discovery CLI (`nulavio integrations`), then the Integration Manager page

**DoD:** each item verified on the Nulavio build by an integration test that uses the engine's real services.

## Phase 3 — Privacy and blocking

- [x] uBO pinned and verified; ETP Strict; HTTPS-Only; reversibility tested
- [ ] Per-site privacy panel (Shell) with honest state (no invented counters)
- [ ] Real-site regression suite (top sites list, screenshot diff, breakage triage)
- [ ] DoH onboarding choice; fingerprinting regression analysis

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

- [ ] Guard runtime: extension-set change alert, profile integrity manifest
- [ ] Spikes: bubblewrap, Flatpak and native-messaging portal, SELinux module
- [ ] Sensitive-sites container with clear-on-close

**DoD:** each control has a test and a documented bypass analysis.

## Phase 6 — Tests, packaging, alpha

- [ ] RPM (Fedora) with signed repository; DEB later
- [ ] Update SLA automation; security changelog
- [ ] Alpha only after [release criteria](release-criteria.md) are met

## Next task (recommended)

**Smart Profile Routing, slice M4a**: a pure decision module (`NulavioRouter.sys.mjs`: host and registrable-domain rules, IDN to punycode, Public Suffix List, precedence explicit > host > domain > policy > stay) with exhaustive tests, then external links (desktop handler) routed to the target profile before any network request, with conservative failure. Rules stay local and are created only by the user.
