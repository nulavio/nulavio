# Feature review, 2026-11

Status: **recommendations ready, decisions pending** (#453). Written by a coding agent (Claude Opus 5.5) on 2026-11-17 for the maintainer, who fills in the **Decision** column. Nothing here removes or changes a feature: each decision other than "Keep" becomes its own issue and pull request.

## What was reviewed

- **Shipped:** `main` at **`68ec0575faad9116a3aa0ce2f9abef314a3473e1`** (2026-11-16 22:27 −03, #438). Anything merged after that commit is not covered.
- **Under construction in another session**, reviewed as it stood, without touching it:
  - #151 from pull request #442 at `92dde400`;
  - #154 and #156 from pull request #443 at `fe60b580`;
  - #152 and #81 from their issue text only: neither has a pull request or code on `main`.
- **Planned and not built:** every open issue of waves 4b and 4c on the [board](https://github.com/orgs/nulavio/projects/1), read on 2026-11-17 (the list is also in #453).
- **Out of scope:** bugs and vulnerabilities (#454, from the feature freeze) and the DNS diagnostics plan (#446 to #452), which is not built.

## How to read it

| Outcome | Meaning |
|---|---|
| **Keep** | Worth its cost as it is. For a planned item: build it as its issue says |
| **Keep, change** | Worth it, with the change named |
| **Off by default** | Stays built in; the person turns it on |
| **Optional component** | Leaves the default install. The form is named: a built-in add-on shipped disabled, a separate package, or an extension from addons.mozilla.org (AMO). Under [ADR 0011](../adr/0011-nulavio-ui-native-not-an-extension.md) Nulavio's interface is native, so what leaves loses privileged access or needs a narrow API |
| **After 1.0** | Not in 1.0 (hidden, or the issue moves to the After 1.0 milestone); back later |
| **Remove** | Deleted, with what replaces it |
| **Do not build** | For a planned item: close the issue without building it, with the reason |

Each item's evidence separates:

- **Verified**: read in the code at the commit above, or the output of a command, with the path or the command.
- **Inferred**: a judgement or a fact not checked here; said as such.

**Use.** Nulavio has no telemetry, so nobody knows how many people use any of these features. Use is the maintainer's judgment and public feedback, for every item; no recommendation below rests on a guess about it, and the items do not repeat this.

**Sizes.** Lines of whole files (`wc -l`, comments and blank lines included), counted at the commit above with a feature-to-files map that leaves no Shell file, launcher module, patch or integration test module unclaimed. Two files are shared by many features and are split by their section comments: `browser/shell/settings/native/panes.mjs` (2,677 lines) and `browser/shell/modules/NulavioWindow.sys.mjs` (1,610 lines). Their shares are marked `~` and are approximate. Locale strings are not counted.

## Summary

The recommendations that are not "Keep" come first in each group of the [evidence](#evidence-shipped). An ID is stable: the issues opened after the decisions will name it.

### Shipped

| ID | Feature | Recommendation | Reason, in one line | Decision | Issue |
|---|---|---|---|---|---|
| U9 | Page-loading line (#318) | **Off by default** | Always indeterminate (the engine's progress was unreliable), repeats the tab's own loading indicator, has no switch, and its tests fail on a build of `main` (#436) | | |
| U10 | Edit the page's text (#161) | **Optional component** (AMO extension) | `document.designMode` needs no privilege; a built-in window actor and a key for an occasional tool | | |
| U12 | Keep above other windows, on KDE (#170) | **Remove** | KWin already offers it for every window (window menu "Keep Above Others", and a shortcut); Nulavio's version adds a D-Bus trust (R77) | | |
| I1 | Integrations status page (Connect P0) | **Keep, change** | Keep "make Nulavio the default browser"; move the status of portals, Secret Service and Plasma into `nulavio doctor` and drop the Settings pane | | |
| I2 | KRunner plugin | **Remove** | KDE's own runners open addresses and searches in the default browser; the plugin is a service any program can call (R44) | | |
| I3 | KDE Connect "send link to device" | **Remove** | Plasma Browser Integration, which Nulavio already detects, has its own KDE Connect plugin | | |
| A2 | Raw automation (WebDriver BiDi endpoint) | **Remove** | The one agent path outside Nulavio's per-call policy and its activity record (R42); agents keep the MCP tools. **Amends** ADR 0007 (decision 1, A13) | | |
| R8 | Phone unlock and the Android Companion | **After 1.0** (offering pairing) | Pairing is already hidden behind a pref; verified on one phone (R48); 1.0 took it back "with the Companion on F-Droid", which now waits until 2027 (#207). **Reverses** the 2026-11-10 scope decision | | |
| L6 | Flatpak bundle attached to releases | **After 1.0** | The bundle never updates itself (R75): a browser that does not update; ship it with Flathub (#88 to #91). **Reverses** #274 (D3) | | |
| L1 | Track A preview (distribution Firefox with Nulavio's profile, chrome theme and start page) | **Remove** (the user-facing preview) | Signed packages replaced it; it alone carries R1, R4, R5, R13, R17, R19. The launcher stays as the packaged tools and the test harness | | |
| L3 | Confined mode (`--confined`) | **After 1.0** | Reachable only from the preview launcher (#283), refuses on Ubuntu (R46), partial; out of the 1.0 promise until a package can start it | | |
| L4 | `nulavio desktop install` | **Remove** (with L1) | Packages install the menu entry; only the preview needed it | | |
| P8 | Fingerprinting additions | **Keep, change** | Keep; once a release carries patch 0012, remove the Shell's per-tab screen fallback where the engine decides, so there is one mechanism | | |
| P14 | Copy Link to Highlight shortcut (#157) | **Keep, change** | Keep the engine's menu item; choose another key: Ctrl+Shift+L is the autofill key of password-manager extensions Nulavio supports (Bitwarden; inferred, not checked) | | |
| P1 | Hardened baseline: prefs, policies, ETP Strict, HTTPS-Only, GPC, telemetry off | Keep | The product's first promise | | |
| P2 | Mozilla's AI features, account, Pocket and promotions off | Keep | "Nothing phones home"; costs a list of prefs and one test module | | |
| P3 | Guard at run time | Keep | The vision's "hope none of it silently regresses"; detection only, and said so (R38) | | |
| P4 | Content filter: uBlock Origin pinned, extra lists | Keep | Blocks ads from the first launch; no engine seam | | |
| P5 | Site exceptions in one place | Keep | "Undo any breakage per site in two clicks" | | |
| P6 | DNS choice | Keep | Small; the engine's own screen stays behind a button | | |
| P7 | Search: providers and per-engine suggestion consent (patch 0004) | Keep | Nothing typed leaves without consent (SEC-14); the engine has one switch for all engines | | |
| P9 | Firefox's name in the User-Agent (0009), font lists on every Fedora (0010) | Keep | Two small patches for compatibility and fingerprinting | | |
| P10 | Look-alike login warning (flow D) | Keep | Small; its limit is written (R41) | | |
| P11 | Programs never opened from the downloads UI (patch 0007) | Keep | Compensates the missing download protection (R15, accepted D9) | | |
| P12 | Routing offered on a sign-in (#220) | Keep | Small, decided in #220 | | |
| P13 | Copy Clean Link with extra parameters (#158) | Keep | One pref | | |
| P15 | DRM off in a new profile, WebRTC address limit, codecs (#221, #222, #377) | Keep | Prefs and tests | | |
| R1 | Profiles: templates, selector, colours and glyphs | Keep | The product's second promise; the engine's profile service is the base | | |
| R2 | The engine's profile chooser unlocks protected profiles (patch 0011) | Keep | Without it a protected profile cannot be chosen at start | | |
| R3 | Smart Profile Routing: links from other apps and typed addresses (patch 0005) | Keep | The differentiator of profiles | | |
| R4 | Routing of links clicked in pages (M5) | Keep (off by default, as today) | Opt-in after a security review; R24, R45 | | |
| R5 | Temporary profile | Keep | Small; a private window keeps the profile's extensions and logins | | |
| R6 | Sensitive-sites profile template | Keep | A template, not a mechanism; R47 | | |
| R7 | Vault: protected profiles (password, recovery code, keyring) | Keep | The third promise; reviewed independently (#224) | | |
| U1 | One settings page inside the engine's | Keep | Accepted ADRs 0008 and 0011; the riskiest seam on an engine update, with a fallback | | |
| U2 | The identity band and the Shell's pages named "Nulavio" | Keep | Carries profile identity and the site; the identity-handler wrap fails safe | | |
| U3 | Layouts: Lateral, Abas no topo, Foco | Keep | Presets over the engine's own options | | |
| U4 | Imersivo | Keep (off by default, as today) | Asked for by the maintainer; its style family is After 1.0 already | | |
| U5 | Appearance: density, accent, contrast, ambience, transparency | Keep | Small module, accessibility options among them | | |
| U6 | New tab and first run | Keep | FR-08, FR-17 | | |
| U7 | Horizon window theme and the Shell's styles | Keep | Required: no Mozilla marks; the brand | | |
| U8 | What's new in this version (#198) | Keep | Small, local, off by a switch | | |
| U11 | Allow copy and paste on a site (#160) | Keep | Per-site choice; lets a password manager paste where a site forbids it | | |
| U13 | Hide the page title from the window title (#322) | Keep | One switch over an engine pref | | |
| U14 | Split view (the engine's) | Keep | The engine's; Nulavio adds words and tests | | |
| U15 | Tab groups (the engine's) | Keep | The engine's; Nulavio adds tests | | |
| U16 | Nulavio's keys and address-bar quick actions | Keep | Engine commands; changed in the engine's own view | | |
| I4 | Meeting links per profile (#221) | Keep | 56 lines, decided in #221 | | |
| I5 | Password provider choice (flows B, H) | Keep | Principle 4, "your tools, not ours" | | |
| A1 | AI Bridge: MCP, autonomy levels, AI Workspaces, audit | Keep | Off until an agent is added; the policy outside the model is the design | | |
| A3 | Built-in assistant | Keep | Same policy as outside agents; per-profile consent | | |
| L2 | `nulavio doctor` | Keep | Diagnostics, and the target of I1's status | | |
| L5 | RPM and APT packages and repositories | Keep | How 1.0 ships | | |
| L7 | The site and the waitlist | Keep | The waitlist is the project's only server, outside the browser (TB17) | | |

### Planned, not built

| ID | Issue | Recommendation | Reason, in one line | Decision | Issue |
|---|---|---|---|---|---|
| N171 | #171 Privacy report | **Do not build** | The engine's `about:protections` already reports what Enhanced Tracking Protection blocked this week; option A builds the same layer again. **Reverses** the 2026-11-16 decision | | |
| N166 | #166 Toolbar buttons you define | **Do not build** | Bookmarks with keywords (`%s`) and bookmarklets on the toolbar already open an address built from the page | | |
| N162 | #162 Per-site CSS | **Do not build** | Unprivileged extensions (AMO) do it; the Guard would need an exception for it | | |
| N163 | #163 Notes per site | **Do not build** | No fit with the vision's problem; AMO extensions exist | | |
| N317 | #317 Pinned sites per profile | **Do not build** | Pinned tabs are already per profile: each profile is its own instance and session | | |
| N316 | #316 Acrylic window | **Do not build** | Taste, against "calm" and the opaque security grammar; `browser.tabs.allow_transparent_browser` is off in the engine | | |
| N347 | #347 Imersivo "Painel" | **Do not build** | Moves the engine's navigation toolbar and its indicators into a side panel: the most invasive style, and #348 is the maintainer's preferred default | | |
| N155 | #155 Sidebar chatbot providers | **Do not build** | A second chat surface next to the assistant (A3); the chatbot is a provider's web page in the sidebar. **Reverses** the 2026-11-14 decision | | |
| N151 | #151 Search provider in one step (PR #442) | **Keep, change** | Keep the chooser and "Entrar"; drop "carry this search to other profiles", which writes into other profiles' folders (a new boundary and R81 in the PR) | | |
| N152 | #152 Account search in private windows and temporary profiles | **Keep, change** | Keep the generic part (the warning, refusing session tokens in templates); Kagi's extension and Privacy Pass wait for #153, After 1.0 | | |
| N154 | #154 Page summaries (PR #443) | **After 1.0** | Built and tested, but one preset service (Kagi) and the assistant already summarises; a new privileged module shared with N156 | | |
| N156 | #156 Translation with a web service (PR #443) | Keep | On-device stays the default; web services on a named click, none preselected | | |
| N81 | #81 1Password | Keep | Decided P1 on 2026-11-16; principle 4 | | |
| N95 | #95 Spike: native content filter | **After 1.0** | Nothing forces it (2026-11-13 decision); uBlock Origin stays | | |
| N119 | #119 Sounds | **After 1.0** | Needs a person listening; nothing depends on it; off by default anyway | | |
| N153 | #153 Spike: Privacy Pass | **After 1.0** | Research; serves N152's Kagi part | | |
| N159 | #159 Link previews ("peek") | **After 1.0** | New window surface, large design work | | |
| N164 | #164 Reading list with offline copy | **After 1.0** | A convenience; Reader View and bookmarks remain | | |
| N165 | #165 Feeds in the address bar | **After 1.0** | A convenience; P3 | | |
| N168 | #168 Low power mode | **After 1.0** | Its own issue says it ships only after a measurement shows a clear gain | | |
| N169 | #169 A site as a Linux app | **After 1.0** | Large: app_id, portals, routing inside an app window | | |
| N216 | #216 .onion and Onion-Location | **After 1.0** | Per-profile proxy is the engine's already; Tor outside Tor Browser risks an anonymity promise the vision rules out | | |
| N217 | #217 Network route per profile and site | **After 1.0** | Large, Fable-level, new secrets; the engine's per-profile proxy covers the simple case | | |
| N218 | #218 Mail and calendar links with privacy services | **After 1.0** | Large catalogue; P3 | | |
| N172 | #172 Parent: Orion's features | **Keep, change** | Close it at 1.0 with what was built; the rest moves After 1.0 with its sub-issues | | |
| N219 | #219 Parent: Tor, VPNs, privacy services | **Keep, change** | Keep #220 to #222 in 1.0; #216 to #218 move After 1.0 | | |
| N242 | #242 Image metadata stripped | **After 1.0** | Privacy fit is good, but it re-encodes files the person sends: a large, risky change with no milestone yet | | |
| N241 | #241 Automatic updates offered at first run | Keep (After 1.0, as set) | Updates are a security feature; decided 2026-11-16 | | |
| N249 | #249 Spike: assistant on the opposite side | Keep (After 1.0, as set) | Time-boxed; #346 depends on it | | |
| N319 | #319 Motion map | Keep (After 1.0, as set) | Measurement first | | |
| N321 | #321 Command palette | Keep (After 1.0, as set) | Decided: the engine's address-bar actions, no new surface | | |
| N345 | #345 Imersivo styles (parent) | Keep (After 1.0, as set) | Without N347 | | |
| N346 | #346 Imersivo "Barras" | Keep (After 1.0, as set) | Completes today's mode | | |
| N348 | #348 Spike: Imersivo "Faixa" | Keep (After 1.0, as set) | Decides the default style | | |
| — | #362, #364, #367, #397, #398, #440 | No verdict: not features | #397 closes if U9 is turned off or removed; #398 follows U4; #440 follows N151/N152 | | |

## What costs the most, across features

### The engine's seams

A seam is a place where Nulavio's code reaches into the engine's private shape, so an engine update can break it without any patch failing to apply. Found by a search of the Shell for engine modules, members whose name starts with `_`, and engine methods replaced at run time (verified at the commit; the search is in [How this was done](#how-this-was-done)):

| Seam | Where | Features that rest on it | What happens when the engine changes |
|---|---|---|---|
| The settings page's registry: `SettingGroupManager._data`, `SettingPaneManager._data`, `Preferences._settings`, `SettingPaneManager.registerPane` replaced, the density control's `get`/`set`/`disabled` replaced | `settings/native/panes.mjs` | Every group Nulavio adds to Settings (U1 and most rows below) | A preflight checks the shape and the whole file undoes itself; an edit that throws leaves the engine's pane as it is (verified: `preflight()`, `undo()`, the `catch` in `registerPane`). Settings then has none of Nulavio's groups |
| The identity handler: `gIdentityHandler._refreshIdentityIcons` and `getConnectionSecurityInformation` wrapped, `_pageExtensionPolicy` read | `NulavioWindow.sys.mjs`, `#ownPagesIdentity` | U2 (the Shell's pages named "Nulavio", R65) | Fails safe: the engine's own label stays (verified: the early `return () => {}`) |
| The profile service: `setDefaultProfileForGroup`, `deleteCurrentProfile`, `setShowProfileSelectorWindow` replaced on `SelectableProfileService` | `NulavioProfiles.sys.mjs` | R1, R2, R7 (which profile a plain start opens; the last unprotected profile; the chooser) | Not checked here whether a change of signature is detected; the engine calls these by name |
| Window actors registered at run time: `NulavioAllowCopy`, `NulavioFingerprinting`, `NulavioPageEdit`, `NulavioLookalike` | four modules | U11, P8, U10, P10 | A child module runs in every matching web content process (all frames for allow-copy and fingerprinting) |
| Sidebar and start-up internals: `SidebarController._state`, `BrowserGlue._beforeUIStartup` | `NulavioLayout.sys.mjs` | U3, U4 | Read, not replaced |
| A start-up category the engine calls for each new window, before the tab browser | `NulavioWindow.sys.mjs` (`browser-window-domcontentloaded-before-tabbrowser`) | U2, U4, U13 | The band is drawn before the first paint |

**Engine updates so far** (verified: `git log -- browser/build/engine.json`): three version bumps (to 159.0, 159.0.1 and 160.0). The 160.0 bump (#19) touched `NulavioLayout.sys.mjs` (+33 −5 lines, the sidebar), the window theme and four integration test modules, and dropped a patch. Three bumps are too few to tell which features cost the most per update; the seams above are where the next ones are likely to land (inferred).

### Tests that only a Nulavio build runs

Pull-request CI runs the integration suite against the distribution's Firefox (`ci.yml` sets no `NULAVIO_ENGINE`; verified). Everything the Shell does (every row of Interface, most of Protection and Profiles) runs only against a Nulavio build: locally, in `release.yml`, in the nightly `rehearsal.yml` (#431) and in `asan.yml`. That is how failures reached the release runs and not the pull requests:

- 160.0-0.6's first run (#376): `test_whats_new_browser` 04, `test_vault_profiles`, `test_drm` audio, `test_immersive` 21.
- Its third run: the clean-link menu (#381).
- `test_layout_presets`, nine tests after #391 (#403).
- The first rehearsal: `test_split_view` (all five) and `test_load_line` 04 (#436, open).

Failed pull-request CI runs since 2026-10-25 (96 runs; their logs read on 2026-11-17) were lint and unit tests of the release and review tooling, not feature tests. Flaky or broken feature tests with an issue: #138 (assistant), #209 (profile permissions), #246 (content filter), #280 (profiles), #398 (Imersivo), #409 (motion, profile ink), #436 (split view, load line).

### Performance

What #80's suite measured per feature (verified: [performance](../architecture/performance.md), its baseline of 2026-11-15, and ADR 0019):

- Nulavio's preferences (ETP Strict, the fingerprinting overrides) on Mozilla's Firefox: Speedometer 18.6 against 18.7.
- uBlock Origin off: 12.9 against 12.1, one diagnostic run of 3 iterations, inside the noise the suite states.
- The audio noise (patch 0012): +2 ms per 10 s of rendered audio.
- The gap to Mozilla's Firefox (startup +47 %, Speedometer −32 %) is the build (#364), not a feature.

No other feature has a measurement. The frame budget covers the sidebar, a dialog, a tab switch, the new tab and idle; the load line (#397) and Imersivo were not measured.

### What carries risk because of a feature

Of the 79 residual risks in [residual risks](../security/residual-risks.md), these exist only because of one feature, and leave with it:

| Feature | Risks |
|---|---|
| L1 Track A preview | R1, R4, R5, R12, R13, R17, R19 |
| A1 AI Bridge | R26, R27, R28, R33, R34, R35, R36, R68 |
| A2 Raw automation | R42 |
| A3 Assistant | R43 |
| R8 Phone unlock | R48, R49 |
| R3, R4 Routing | R21, R22, R24, R45, R55 |
| U12 Keep above | R77 |
| U11 Allow copy | R76 |
| L3 Confined mode | R46 |
| L6 Flatpak bundle | R75 |
| I2 KRunner | R44 |

## Evidence: shipped

Each item: **code** (verified sizes), **seams**, **boundaries and risks**, **tests and failures**, **decided by** and open issues, **the engine already** (what Firefox 160.0 offers; checked in its source where it says "verified"), **fit and cost**, and the **recommendation** with what changes for people who use it today. The trust boundaries are in [trust boundaries](../architecture/trust-boundaries.md), the risks in [residual risks](../security/residual-risks.md).

### Protection and privacy

#### P1 Hardened baseline

- **Code:** 674 lines: `browser/config/prefs/baseline.js` (44 prefs, all `@mode seed`: 30 privacy, 7 network, 5 interface, 1 HTTPS, 1 tracking), `seed-history.json`, `guard-rules.json` (19 rules), the launcher's `prefs.py` and `guard.py`, and the build's own policies (`own-policies.json`: telemetry, studies, extension settings).
- **Seams:** prefs and policies only.
- **Boundaries and risks:** TB5, TB8; R63, R78.
- **Tests:** `test_engine_slice` (15), `test_privacy` (4), `test_new_profile_connections` (1); unit `test_prefs_and_guard`.
- **Decided by:** SEC-01 to SEC-09, [hardening](../security/hardening.md).
- **The engine already:** offers each setting. Nulavio's work is choosing them, explaining them (`@why`, `@tradeoff`) and checking that none weakens a protection.
- **Fit and cost:** the vision's first sentence. Cheap per update: an unknown pref fails an integration test.
- **Recommendation: Keep.**

#### P2 Mozilla's AI features, account, Pocket and promotions off

- **Code:** about 16 prefs inside `baseline.js` (`browser.ml.*`, `browser.ai.control.*`, sponsored suggestions, the sidebar chatbot); the branding prefs.
- **Tests:** `test_mozilla_features` (8).
- **Decided by:** D-UX7, D-UX8.
- **Fit and cost:** principle 5. A new Mozilla feature needs a new pref each release (inferred from the list's growth).
- **Recommendation: Keep.**

#### P3 Guard at run time

- **Code:** 1,383 lines (`NulavioGuard.sys.mjs` 994, the review page, the experiment) and about 34 lines of Settings.
- **Seams:** engine modules `SessionStore`, `AddonManager`, `AsyncShutdown`; no private member.
- **Boundaries and risks:** R38 (detection, kept in the profile).
- **Tests:** `test_guard` (6); unit `test_prefs_and_guard`.
- **Failures:** bugs #136, #337, #351 (closed); #387 and #421 open.
- **Decided by:** SEC-18; [hardening](../security/hardening.md#guard-at-run-time-what-it-catches-and-how-it-can-be-bypassed).
- **The engine already:** nothing comparable. Enterprise policies can lock prefs; nothing reports a change made outside the browser.
- **Fit and cost:** answers the vision's problem ("hope none of it silently regresses") and states its limit. Each new protection Nulavio writes (the fingerprinting set, #421) has to be taught to the Guard.
- **Recommendation: Keep.**

#### P4 Content filter: uBlock Origin pinned, with the extra lists

- **Code:** no code of its own beyond the build:
  - `extensions.lock.json` (pins and hashes);
  - `content-filter.json` (the default lists);
  - a copy of uBlock Origin's list registry (`assets.json`, 970 lines of data);
  - `filter-lists.json`;
  - the policy `make_distribution.py` writes;
  - about 34 lines of Settings, which read whether a cookie-notice list is on.
- **Seams:** none in the engine. The extension's registry format is one: #114 asks uBlock Origin for a supported way.
- **Boundaries and risks:** TB3; R6, R39.
- **Tests:** `test_content_filter` (5), `test_engine_slice` 08.
- **Failures:** #246 (intermittent, open). #415 (P1, open): the pinned first-install version is behind a fixed upstream advisory; #416 pins 1.76.4.
- **Decided by:** FR-09; ADR 0012 stays Proposed (#95).
- **The engine already:** ETP blocks trackers, not ads.
- **Fit and cost:** the vision's "blocks ads and trackers from the first launch". Its Speedometer cost was inside the noise of one run.
- **Recommendation: Keep.** The native filter stays After 1.0 (N95).

#### P5 Site exceptions in one place

- **Code:** `NulavioPrivacy.sys.mjs` (413 lines, shared with P6 and P4's reading), its experiment, about 108 lines of Settings.
- **Seams:** the engine's permission store, read; uBlock Origin's own page opened, never edited.
- **Boundaries and risks:** R39.
- **Tests:** `test_settings_exceptions` (3), `test_privacy` (4).
- **Decided by:** FR-18; flow C.
- **The engine already:** each permission type has its own exceptions dialog in Settings (inferred from Firefox's interface, not checked in the source).
- **Fit and cost:** the vision's success sentence ("undo any breakage per site in two clicks"). Small.
- **Recommendation: Keep.**

#### P6 DNS choice

- **Code:** inside `NulavioPrivacy.sys.mjs` (three resolvers, `setDns`), about 145 lines of Settings, a card in the new tab.
- **Boundaries and risks:** R40.
- **Tests:** `test_dns` (5, with a local DoH resolver), `test_settings_dns` (4).
- **Decided by:** FR-29.
- **The engine already:** DNS over HTTPS with four modes. Nulavio's group says the same in three plain choices and leaves the engine's screen behind a button (verified: the comment above the group in `panes.mjs`).
- **Fit and cost:** small. Asking at first run is a question more; that is FR-17's design, not changed here.
- **Recommendation: Keep.**

#### P7 Search: providers and per-engine suggestion consent

- **Code:** 723 lines (`NulavioSearch.sys.mjs` 516, its experiment, `providers.json`, patch 0004 of 68 lines) and about 161 lines of Settings.
- **Seams:** patch 0004 in `SearchSuggestionController`; engine modules `SearchService`, `ConfigSearchEngine`, `UserSearchEngine`.
- **Boundaries and risks:** TB12; R17 (Track A), R20, R72.
- **Tests:** `test_search` (16), `test_settings_search` (2).
- **Decided by:** ADR 0002; SEC-14; FR-21.
- **The engine already:** one switch for suggestions from every engine (R17); adding engines by hand.
- **Fit and cost:** "nothing typed leaves without consent" needs the patch: the engine has no per-engine switch.
- **Recommendation: Keep.** #151 changes it (N151).

#### P8 Fingerprinting additions

- **Code:** 843 lines (`NulavioFingerprinting.sys.mjs` 502, `NulavioFingerprintingChild.sys.mjs` 112, patch 0012 of 229 lines in `nsScreen`, `nsMediaFeatures` and `AudioDestinationNode`) and about 25 lines of Settings.
- **Seams:** patch 0012 (C++); a window actor in every web frame; the engine's `RFPTargetConstants`.
- **Boundaries and risks:** R56.
- **Tests:** `test_fingerprinting` (16), `test_privacytests` (3, PrivacyTests' probes, 25 of 25 on a build with the patch); unit `test_fingerprinting_shell`, `test_privacytests_fixture`; workflow `privacytests.yml`.
- **Decided by:** ADRs 0016 to 0019 (accepted 2026-11-14, #79).
- **Open issues:** #406, #419, #420, #421 (all small).
- **The engine already:** fingerprinting protection and its per-target override list. Patch 0012 adds two targets the engine lacks: audio noise per site, and one screen size per document.
- **Fit and cost:** privacy by default, decided four days ago. The cost is the C++ patch at each update, and two mechanisms for the screen while releases without the patch exist. The Shell's per-tab path runs only where the engine lacks the target or the set leaves it out (verified: `engineDecides()` and `turnsOn()` in the child).
- **Recommendation: Keep, change.** After a release that carries patch 0012 (the next one; 160.0-0.6 was built before #402 merged), remove the Shell's screen fallback, so one mechanism remains. Whether anything still needs it after #400 (launcher-seeded sets) is inferred, not checked.
- **For people who use it today:** nothing visible; the same screen size, from the engine.

#### P9 Firefox's name in the User-Agent, font lists on every Fedora

- **Code:** patches 0009 (32 lines) and 0010 (59 lines).
- **Tests:** none of their own was found by the inventory. The font lists are exercised by the fingerprinting and window tests (inferred from where `font.visibility` and the tiny font appear).
- **Fit and cost:** compatibility (sites that sniff "Firefox") and the font part of fingerprinting. Small.
- **Recommendation: Keep.**

#### P10 Look-alike login warning

- **Code:** 164 lines (two actor modules, the warning page) and about 55 lines of Settings (the sites the person chose to continue on).
- **Seams:** a window actor; the engine's login manager, read.
- **Boundaries and risks:** R41 (only the browser's own manager's logins).
- **Tests:** `test_passwords` 01 to 03 and 06.
- **Decided by:** flow D; SEC-10.
- **The engine already:** shows punycode for some confusable names; it has no warning before typing a password on a near-copy (inferred).
- **Fit and cost:** small. It does nothing for people whose passwords live in an extension (P0 providers), and says so.
- **Recommendation: Keep.**

#### P11 Programs never opened from the downloads UI

- **Code:** 431 lines (patch 0007 of 249 lines, the second largest; the warning page).
- **Seams:** the patch, in the downloads panel and its commands.
- **Boundaries and risks:** compensates R15 (no download protection with Nulavio's Safe Browsing key).
- **Tests:** `test_downloads_indicator` (9), `test_shell` 03 to 05, `test_security_moments` (1).
- **Decided by:** flow E; D9 (R15 accepted for the alpha and 1.0).
- **The engine already:** offers "Open" and "Always open similar files" for any file.
- **Fit and cost:** the compensating control of an accepted risk. The patch is large for what it does: the cost of keeping it is in the update times, not in risk.
- **Recommendation: Keep.**

#### P12 Routing rules offered on a sign-in

- **Code:** `NulavioAccountRules.sys.mjs` (161 lines).
- **Boundaries and risks:** R73 (what Google still sees).
- **Tests:** `test_account_rules` (4).
- **Decided by:** #220, decision 3.
- **Fit and cost:** small, ties P-group privacy to profiles.
- **Recommendation: Keep.**

#### P13 Copy Clean Link with Nulavio's extra parameters

- **Code:** one pref (`privacy.query_stripping.strip_list`), with its sources in [clean links](../research/clean-links.md).
- **Tests:** `test_clean_links` (3, unit and integration).
- **Failures:** #381 (a race in the test, fixed).
- **The engine already:** offers Copy Clean Link; Nulavio adds parameters to its list.
- **Recommendation: Keep.**

#### P14 Copy Link to Highlight shortcut

- **Code:** one command in `manifest.json` (Ctrl+Shift+L) on top of the engine's menu item.
- **Tests:** `test_text_fragments` (6), `test_shortcuts`.
- **Decided by:** #157 (closed).
- **The engine already:** has the item in the context menu.
- **Fit and cost:** the key is the cost. Ctrl+Shift+L is the autofill key of Bitwarden's extension (FR-12) and of other password managers (inferred from their documentation, not checked here). When an extension and a built-in command claim one key, which wins was not checked.
- **Recommendation: Keep, change:** keep the item; change or drop the key.
- **For people who use it today:** the key changes; say so in the release notes.

#### P15 DRM off in a new profile, WebRTC address limit, codecs

- **Code:** prefs (`media.gmp-widevinecdm.*`, `media.peerconnection.ice.default_address_only`), the packages' codec recommendation (#377).
- **Boundaries and risks:** R74.
- **Tests:** `test_drm` (6), `test_webrtc` (3), `test_media_codecs` (1).
- **Failures:** #376 (`test_drm` audio in the release container, fixed).
- **Decided by:** #221, #222.
- **Recommendation: Keep.**

### Profiles

#### R1 Profiles: templates, selector, colours and glyphs

- **Code:** 1,690 lines (`NulavioProfiles.sys.mjs` 974, `NulavioAvatars.sys.mjs`, the profile menu, the experiment, three helpers) and about 589 lines of Settings (the profiles' list and editor).
- **Seams:** three methods of the engine's `SelectableProfileService` are replaced at run time (see [the seams](#the-engines-seams)).
- **Boundaries and risks:** TB13; R18.
- **Tests:** `test_profiles` (15), `test_profile_colors` (5), `test_profile_initialization` (6), `test_settings_profiles` (9).
- **Failures:** #209, #280, #368, #409 (closed).
- **Decided by:** ADR 0003; FR-06; SEC-15.
- **The engine already:** has profiles with a selector, avatars and colours since 2025 (verified: `browser.profiles.enabled` is true in 160.0's `firefox.js`). Nulavio adds the templates, the glyphs, the toolbar button and what the Vault needs (a protected profile is never the start-up one, the last unprotected profile).
- **Fit and cost:** the second promise of the README. The method replacements are the cost at each update.
- **Recommendation: Keep.**

#### R2 The engine's profile chooser unlocks protected profiles

- **Code:** 847 lines (patch 0011 of 164 lines, `browser/shell/chooser/`, its strings).
- **Seams:** the patch, in `about:profilemanager`'s chooser.
- **Boundaries and risks:** R18.
- **Tests:** `test_profile_chooser` (8).
- **Decided by:** #43 (option A, change the engine's chooser).
- **Fit and cost:** without it, a protected profile cannot be chosen when the browser starts. It goes with R7.
- **Recommendation: Keep.**

#### R3 Smart Profile Routing: links from other apps and typed addresses

- **Code:** 1,585 lines (`NulavioRouter.sys.mjs` 309, `NulavioRouting.sys.mjs` 835, the ask and refusal pages, the experiment, patch 0005 of 53 lines) and about 216 lines of Settings.
- **Seams:** patch 0005 in the address bar; the engine's remote service (D-Bus) for command lines; `SelectableProfileService`.
- **Boundaries and risks:** TB14; R21, R22, R23, R55.
- **Tests:** `test_routing` (32), `test_settings_routing` (4).
- **Decided by:** ADR 0003; FR-22.
- **The engine already:** nothing routes a link to a profile. Containers (the Multi-Account Containers extension) separate cookies inside one profile (inferred).
- **Fit and cost:** profiles without routing mean choosing the profile by hand for every link from another app. One of the larger features; its rules engine is pure and tested.
- **Recommendation: Keep.**

#### R4 Routing of links clicked in pages (M5)

- **Code:** inside R3 (a switch, off by default: verified, `NulavioRouter.sys.mjs`, "Opt-in … Default off").
- **Boundaries and risks:** R24, R45; a [security review](../security/routing-m5-review.md) before it was offered.
- **Tests:** `test_routing` 15 to 22.
- **Recommendation: Keep, off by default as today.**

#### R5 Temporary profile

- **Code:** the launcher's `temporary.py` (295 lines) and the Shell's entries in the profile menu and Settings.
- **Boundaries and risks:** R37.
- **Tests:** `test_temporary` (5, unit and integration).
- **Decided by:** FR-28; ADR 0003.
- **The engine already:** private windows. They keep the profile's extensions, saved logins and settings; a temporary profile has none of them and leaves no folder (inferred from the design, not compared here).
- **Fit and cost:** small, and it answers "a window that shares nothing" without a second browser.
- **Recommendation: Keep.**

#### R6 Sensitive-sites profile template

- **Code:** a template inside `NulavioProfiles.sys.mjs` and a `user.js` it writes.
- **Boundaries and risks:** R47.
- **Tests:** `test_profiles` 11.
- **Decided by:** SEC-20; Phase 5.
- **Recommendation: Keep.**

#### R7 Vault: protected profiles

- **Code:** 5,391 lines:
  - the launcher's `vault/` without the phone (`storage.py` 995, `cli.py` 723, `core.py` 538, `profiles.py` 350, `coordinator.py`, `sodium.py`, `providers.py`);
  - the Shell's Vault pages and `NulavioVault.sys.mjs`;
  - `NulavioTools.sys.mjs` and `make_tools.py`, which ship the `nulavio` tools next to the engine.
- **Seams:** gocryptfs (FUSE) and the system libsodium through `ctypes`; the engine's profile service; R2's patch.
- **Boundaries and risks:** TB5, TB11; R30, R31, R32, R70.
- **Tests:** `test_vault_profiles` (4), `test_vault_ui` (20); unit `test_vault`, `test_vault_storage`. FUSE is missing in pull-request CI, so `test_vault_profiles` runs in release runs only (#376, #378).
- **Failures:** #177, #187, #258, #277, #325, #411, #412 (closed); #434 open (P3).
- **Decided by:** ADRs 0006 and 0015; FR-24, FR-25.
- **Reviewed:** the independent review of #224 read it as a whole; every finding is closed ([release criteria](release-criteria.md#the-independent-review-of-the-vault-and-the-release-chain-224-done-every-finding-closed)).
- **The engine already:** a primary password protects saved logins only, not the profile.
- **Fit and cost:** the README's third promise and one of 1.0's two audited areas. The largest feature after the AI Bridge.
- **Recommendation: Keep.**

#### R8 Phone unlock and the Android Companion

- **Code:** 3,749 lines:
  - the launcher's `phone.py`, `phone_session.py` and `link.py` (1,024);
  - the Shell's phone page and QR helper;
  - the Android app and its protocol library (2,414 lines of Java).
- **Release cost:** a second build system (Gradle, with locked dependencies and R53's advisories), a second key in AWS KMS (ADR 0014, TB18), a Companion job in `release.yml`, and F-Droid's recipe.
- **Seams:** Android's Keystore and BiometricPrompt; mDNS on the local network.
- **Boundaries and risks:** R48 (one real phone), R49 (the network sees a phone operation).
- **Tests:** `test_companion_emulator` (5); unit `test_phone_link`, `test_companion_protocol`, `test_companion_build`, `test_companion_version`, `test_apk_sign`.
- **Decided by:** ADR 0005; D10 revised on 2026-11-10: phone unlock "came back in … with the Companion on F-Droid" ([release criteria](release-criteria.md#scope-of-10-decided-2026-11-04)).
- **Open issues:** #207 (F-Droid: ask again from 2027-01-27), #227 (the real phone again, with the signed APK).
- **Today:** pairing a phone is not offered. It is behind `nulavio.vault.phone.pairing`, false by default (verified: `NulavioVault.sys.mjs`); unlocking with a phone already paired does not depend on it.
- **Fit and cost:** a convenience on top of R7, which already has two recovery methods. The condition it came back under (F-Droid) is now after 1.0. It is the one feature that makes Nulavio maintain a second platform.
- **Recommendation: After 1.0, for offering pairing.** Keep the code and the pref as they are. Offer pairing when F-Droid accepts the Companion (#207) and #227 has passed. **Reverses** the 2026-11-10 scope decision: the release criteria and the roadmap's Phase 2c need the amendment.
- **For people who use it today:** nobody can pair from the browser today, so nothing changes in the browser. The README ("comes with the next release") and the landing page ("Coming soon") need new words, and so does the Companion's place in the release (the signed APK keeps being built, or stops until then: a decision for the issue).

### Interface

#### U9 Page-loading line

- **Code:** `NulavioLoadLine.sys.mjs` (129 lines) and its styles in `window-band.css`. Started for every window by the layout experiment; no switch (verified: no pref in the module; `experiments/layout/parent.js` calls `watch()`).
- **What it shows:** always the indeterminate state, because the engine's progress for a web page was found unreliable (verified: the module's header, "measured on 160.0").
- **Tests:** `test_load_line` (5).
- **Failures:** #436 (P1, open): test 04, under reduced motion, fails on a build of `main` in the first rehearsal. #397 (After 1.0): its frame cost is not measured.
- **Decided by:** #318, asked for by the maintainer in the experience review; built in wave 4a.
- **The engine already:** the selected tab shows the engine's loading indicator, and the reload button turns into stop.
- **Fit and cost:** it says "loading" a second time, without progress, on every page of every window. Small code, but a listener per window, a failing test and an unmeasured frame cost, for a cue the engine already gives.
- **Recommendation: Off by default**, with a switch in Settings → Aparência. The alternative is **Remove**; the maintainer asked for it, so the softer step is proposed.
- **For people who use it today:** the line disappears after the update unless they turn it on; one line in the release notes.

#### U10 Edit the page's text

- **Code:** 219 lines (`NulavioPageEdit.sys.mjs` and its child), an item in the page menu and Ctrl+Alt+E.
- **Seams:** a window actor for the top frame of every http, https and file page.
- **Tests:** `test_page_edit` (6).
- **Decided by:** #161 (from Orion's list, #172).
- **The engine already:** `document.designMode = "on"` in the web console does the same, by hand.
- **Fit and cost:** an occasional tool (screenshots, mock-ups). It needs no privilege: an extension's content script can set `designMode`.
- **Recommendation: Optional component, as an extension from AMO** that the documentation names (Nulavio ships none of its own and bundles none). What is lost: the native menu item, the key and the bar that says the page is editable.
- **For people who use it today:** the menu item and Ctrl+Alt+E go away; the release notes name the replacement.

#### U12 Keep above other windows, on KDE

- **Code:** `NulavioKeepAbove.sys.mjs` (286 lines): a KWin script loaded over the session bus, an item in the window's menu and Ctrl+Alt+K.
- **Boundaries and risks:** TB10; R77 (it trusts whatever answers as `org.kde.KWin`).
- **Tests:** `test_keep_above` (4).
- **Decided by:** #170.
- **The desktop already:** KWin offers "Keep Above Others" in every window's menu (Alt+F3) and a configurable shortcut, "Keep Window Above Others" (verified: both strings in `libkwin.so.6` on Fedora 44 KDE, this machine). GNOME has "Always on Top" in the window menu (inferred).
- **Fit and cost:** principle 7 ("Linux-native") is better served by the desktop's own control. The browser's version adds a D-Bus trust for something every window already has.
- **Recommendation: Remove.** Replacement: the desktop's window menu or shortcut.
- **For people who use it today:** Ctrl+Alt+K stops working; the release notes say where KDE's control is.

#### U1 One settings page inside the engine's

- **Code:** 1,332 lines and about 575 lines of `panes.mjs`:
  - the registry plumbing, the page order, the policy line and the navigation;
  - `NulavioSettings.sys.mjs`;
  - what is left of the Shell's own settings page, for the agents and the integrations;
  - the Fluent strings.
- **Seams:** the settings registry, the riskiest seam ([table](#the-engines-seams)).
- **Boundaries and risks:** TB11; R66 (the "managed by your organisation" line hidden while only Nulavio's own policies are in effect).
- **Tests:** `test_settings_native` (14), `test_settings_ui` (10), `test_settings_reflow` (2), `test_settings_policies` (4), `test_settings_layout` (3).
- **Failures:** #108, #128 (closed).
- **Decided by:** ADRs 0008 and 0011.
- **Fit and cost:** "read in one place exactly what Nulavio changed and why" (the vision's success). An engine change to the registry removes every Nulavio group at once, visibly, rather than breaking one.
- **Recommendation: Keep.**

#### U2 The identity band and the Shell's pages named "Nulavio"

- **Code:** 2,338 lines: `NulavioWindow.sys.mjs` (1,610, also carrying U4's window part, U13 and U16's quick actions) and `window-band.css` (728).
- **Seams:** the identity-handler wrap; the early window category; the engine's `gBrowser`, `gNotificationBox`, `CustomizableUI` and quick actions.
- **Boundaries and risks:** R64 (in Imersivo the band names the site), R65 (the Shell's pages named as the browser's own).
- **Tests:** `test_window_band` (15), `test_window_frame` (9), `test_window_title` (5); unit `test_window_band_sheet`, `test_frame_scene`.
- **Decided by:** ADRs 0009, 0010, 0011; UX3A.
- **The engine already:** no row that only the browser can draw and that names the profile.
- **Fit and cost:** it is how a person sees which profile a window belongs to, and what keeps the site on screen in Imersivo.
- **Recommendation: Keep.**

#### U3 Layouts: Lateral, Abas no topo, Foco

- **Code:** 959 lines (`NulavioLayout.sys.mjs` 811, its experiment) and about 71 lines of Settings.
- **Seams:** `SidebarController._state`, `BrowserGlue._beforeUIStartup`, `CustomizableUI`. The 160.0 bump changed this module.
- **Tests:** `test_layout_presets` (23), `test_sidebar_focus` (1).
- **Failures:** #403 (nine tests, closed).
- **The engine already:** owns vertical tabs and the sidebar (verified: `sidebar.revamp`, `sidebar.verticalTabs` in `firefox.js`); the layouts are presets over them.
- **Recommendation: Keep.**

#### U4 Imersivo

- **Code:** inside U3 and U2 (the switch, the holds, the band's role), about 25 lines of Settings, Ctrl+Alt+I and a View menu item.
- **Default:** off (verified: ADR 0009 decision 1; `NulavioLayout.sys.mjs`).
- **Boundaries and risks:** R64.
- **Tests:** `test_immersive` (24 tests, 1,199 lines).
- **Failures:** #238, #239, #344, #376 (test 21) closed; #398 open.
- **Decided by:** ADR 0009; its style family (#345 to #348) is After 1.0.
- **Fit and cost:** an opt-in that costs mostly in tests: pointer journeys and frame traces are the flakiest kind.
- **Recommendation: Keep, off by default as today.** The planned styles are reviewed in N345 to N348.

#### U5 Appearance: density, accent, more contrast, ambience, less transparency

- **Code:** 299 lines (`NulavioPersonalise.sys.mjs`, its experiment, a helper) and about 62 lines of Settings.
- **Tests:** `test_appearance` (14); unit `test_personalisation`.
- **Failures:** #284, #368 (closed).
- **Decided by:** UX6.
- **Fit and cost:** small; "Mais contraste" and "Reduzir transparência" serve accessibility (NFR-01).
- **Recommendation: Keep.**

#### U6 New tab and first run

- **Code:** 1,223 lines (`newtab.js` 901, `newtab.html`).
- **Tests:** `test_newtab_ui` (8), `test_firstrun_stage` (13).
- **Decided by:** FR-08, FR-17; ADR 0010. Open: a brand-new profile's first start loses a link given on the command line (FR-17, execution plan K3).
- **The engine already:** has its own new tab, with sponsored content Nulavio turns off.
- **Recommendation: Keep.**

#### U7 Horizon window theme and the Shell's styles

- **Code:** 3,493 lines:
  - the window theme (`horizon.css` 721, `tokens.css` 258);
  - the Shell's shared styles (`components.css` 743, `pages.css` 715 and others);
  - `ui.js` and the component gallery;
  - patch 0003 (24 lines), which links the theme.
- **Tests:** `test_horizon` (15), `test_horizon_groups` (11), `test_motion` (5), `test_component_gallery` (2); unit `test_horizon_theme`, `test_tokens_v2`, `test_motion_sheet`.
- **Failures:** #409 (motion, closed).
- **Decided by:** release criterion 9 (no Mozilla marks) and the design system.
- **Fit and cost:** needed for the identity and for accessibility (AA tokens). The 160.0 bump touched the theme.
- **Recommendation: Keep.**

#### U8 What's new in this version

- **Code:** 689 lines (`NulavioWhatsNew.sys.mjs` 311, its page and experiment, the per-version records in `packaging/whats-new/`) and about 36 lines of Settings.
- **Tests:** `test_whats_new_browser` (14); unit `test_whats_new`.
- **Failures:** #306 (0.5's start-up failure: an engine module moved), #376 (closed).
- **Decided by:** #198.
- **The engine already:** opens Mozilla's "what's new" page from the network after an update (off in Nulavio).
- **Fit and cost:** local, and its bar is turned off in Settings. #306 shows the engine-module path is a seam.
- **Recommendation: Keep.**

#### U11 Allow copy and paste on a site

- **Code:** 238 lines (`NulavioAllowCopy.sys.mjs` and its child).
- **Seams:** a window actor in every http and https frame, at `DOMWindowCreated`.
- **Boundaries and risks:** R76 (the site's own handlers no longer run where it is on).
- **Tests:** `test_allow_copy` (5).
- **Failures:** #445 (a race in the test, fixed).
- **Decided by:** #160.
- **The engine already:** only a global pref that turns clipboard events off for every site (inferred: `dom.event.clipboardevents.enabled`).
- **Fit and cost:** a per-site choice the person makes. It lets a password manager's paste work where a site forbids pasting, which serves principle 4.
- **Recommendation: Keep.**

#### U13 Hide the page title from the window title

- **Code:** a few lines in `NulavioWindow.sys.mjs` and a switch in Aparência, over the engine's `privacy.exposeContentTitleInWindow` and `.pbm` (verified in 160.0's `firefox.js`).
- **Tests:** `test_window_title` (5).
- **Decided by:** #322 (D-UX17).
- **Recommendation: Keep.**

#### U14 Split view

- **Code:** the engine's (verified: `browser.tabs.splitView.enabled` true in 160.0). Nulavio adds words in its menus and documents it.
- **Tests:** `test_split_view` (5).
- **Failures:** #436 (open, all five fail on a build of `main`).
- **Decided by:** #315.
- **Recommendation: Keep.** The engine maintains it; Nulavio keeps the tests.

#### U15 Tab groups

- **Code:** the engine's (verified: `browser.tabs.groups.enabled` true in 160.0); the engine's AI grouping is off (P2).
- **Tests:** `test_tab_groups` (7).
- **Decided by:** #323.
- **Recommendation: Keep.**

#### U16 Nulavio's keys and address-bar quick actions

- **Code:** seven commands in `manifest.json`, three quick actions in `NulavioWindow.sys.mjs`, and about 284 lines of Settings (Atalhos).
- **Tests:** `test_shortcuts` (14).
- **The engine already:** owns the commands and their remapping view; Nulavio's Atalhos group reads them.
- **Fit and cost:** each feature that leaves (U10, U12) takes its key with it.
- **Recommendation: Keep.**

