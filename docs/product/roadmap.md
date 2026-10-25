# Roadmap

Each milestone has a definition of done (DoD). "Done" requires the DoD to be verified, not just the UI to exist.

## Phase 0 — Discovery, feasibility, engine ADR · **complete (2026-10-24)**

- [x] Environment inventory (Fedora 44 KDE 6.7.5 Wayland, Firefox 158.0.1, Qt 6.11.2, 16 threads, 30 GiB, 325 GB free)
- [x] Gecko spike: vertical slice + password-manager extension smoke tests
- [x] Qt WebEngine spike: MV3 loading works, enabling crashes (not isolated), documented limits
- [x] [ADR 0001](../adr/0001-engine-selection.md) with evidence, risks, reversal criteria
- [x] Source-release verification with a pinned Mozilla key

**DoD:** ADR accepted with reproducible evidence ✔

## Phase 1 — Foundation and branding · **complete except GitHub CI and trademark search**

- [x] Repo structure, docs, threat model, policies
- [x] Brand strategy, 3 directions, selection, tokens (AA-verified), logo family, icons 16–512, symbolic, favicon
- [x] CI workflow (lint, unit tests, token/asset freshness, headless integration)
- [x] CI integration job rehearsed locally in a Fedora 44 container (rootless podman, default seccomp): 14/14
- [ ] First CI run on GitHub (needs a remote repository)
- [x] **Track B build spike in a container**: ≈ 52 min, 23 GB, branded binary passes 14/15 (Safe Browsing key pending) — [build.md](../architecture/build.md)
- [x] Ubuntu userspace check (Mozilla APT Firefox): 15/15
- [ ] Trademark/domain search (INPI, domains, handles), done by the maintainer or counsel

**DoD:** CI green on a fresh clone; measured Track B build numbers recorded in the ADR.

## Phase 2 — Browser vertical slice · **Track A done; Track B dev build done**

- [x] Track A: launcher, isolated profile, start page, desktop identity, chrome theme
- [x] Track B inputs: `browser/branding/nulavio/` + generated assets, `browser/build/mozconfig`, patch stack (`browser/patches/`, 1 patch), container build script
- [x] `distribution/` generated from `browser/config/` (`distribution.ini` defaults + `policies.json`), verified active in the build (`test_13`)
- [x] Google Safe Browsing API key from a secret: dedicated Google Cloud project, key restricted to the Safe Browsing API, build passes 17/17 incl. the end-to-end phishing test
- [ ] Download protection for Track B: request Google's download-protection API, or ship flow E (R15)
- [ ] Built-in new tab add-on using the tokens

**DoD:** a branded Nulavio binary built from verified source opens a window on Fedora KDE Wayland with the sandbox verified by `test_04`, with no Mozilla marks in the UI.

## Phase 3 — Privacy and blocking

- [x] uBO pinned and verified; ETP Strict; HTTPS-Only; reversibility tested
- [ ] Per-site privacy panel (Shell) with honest state (no invented counters)
- [ ] Real-site regression suite (top sites list, screenshot diff, breakage triage)
- [ ] DoH onboarding choice; fingerprinting regression analysis

**DoD:** blocking test + 50-site regression run with recorded breakage and per-site fixes.

## Phase 4 — Password integrations

- [ ] Proton Pass manual certification (checklist in [password-providers](../architecture/password-providers.md))
- [x] KeePassXC association + autofill end to end (Fedora 44 container, KeePassXC 2.8.0)
- [ ] KeePassXC on the maintainer's desktop and Ubuntu KDE; Flatpak KeePassXC evaluation
- [ ] Bitwarden certification, biometrics via the desktop app
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

**Track B build spike** in a disposable Fedora container. Prerequisite: the maintainer approves about 45 GB of disk and 1–2 h of CPU. Output: measured build time, branding dir and first `mozconfig`. In parallel, the maintainer can run the manual Proton Pass certification with a test account.
