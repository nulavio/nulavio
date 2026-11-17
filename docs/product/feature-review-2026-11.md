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

**Reverses** marks a recommendation that goes against a decision the maintainer recorded (on the issue, in an ADR or in the release criteria), including one that only moves a decided item out of 1.0 ("timing"). **Amends** marks one that changes part of an accepted ADR.

Each item's evidence separates:

- **Verified**: read in the code at the commit above, or the output of a command, with the path or the command.
- **Inferred**: a judgement or a fact not checked here; said as such.

**Use.** Nulavio has no telemetry, so nobody knows how many people use any of these features. Use is the maintainer's judgment and public feedback, for every item; no recommendation below rests on a guess about it, and the items do not repeat this.

**Sizes.** Lines of whole files (`wc -l`, comments and blank lines included), counted at the commit above with a feature-to-files map that leaves no Shell file, launcher module, patch or integration test module unclaimed. Two files are shared by many features and are split by their section comments: `browser/shell/settings/native/panes.mjs` (2,677 lines) and `browser/shell/modules/NulavioWindow.sys.mjs` (1,610 lines). Their shares are marked `~` and are approximate. Locale strings are not counted.

## Summary

In each table, the recommendations other than "Keep" come first; the [evidence](#evidence-shipped) follows them. An ID is stable: the issues opened after the decisions will name it.

### Shipped

| ID | Feature | Recommendation | Reason, in one line | Decision | Issue |
|---|---|---|---|---|---|
| U9 | Page-loading line (#318) | **Off by default** | Always indeterminate (the engine's progress was unreliable), repeats the tab's own loading indicator, has no switch, and its frame cost is not measured (#397). Asked for by the maintainer (#318) | | |
| U10 | Edit the page's text (#161) | **Optional component** (AMO extension) | `document.designMode` needs no privilege; a built-in window actor and a key for an occasional tool | | |
| U12 | Keep above other windows, on KDE (#170) | **Remove** | KWin already offers it for every window (window menu "Keep Above Others", and a shortcut); Nulavio's version adds a D-Bus trust (R77) | | |
| I2 | KRunner plugin | **Remove** | KDE's own runners open addresses and searches in the default browser; the plugin is a service any program can call (R44). **Amends** ADR 0004 (P1) | | |
| I3 | KDE Connect "send link to device" | **Remove** | Plasma Browser Integration, which Nulavio already detects, has its own KDE Connect plugin. **Amends** ADR 0004 (P1) | | |
| A2 | Raw automation (WebDriver BiDi endpoint) | **Remove** | The one agent path outside Nulavio's per-call policy and its activity record (R42); agents keep the MCP tools. **Amends** ADR 0007 (decision 1, A13) | | |
| L6 | Flatpak bundle attached to releases | **After 1.0** | The bundle never updates itself (R75): a browser that does not update; ship it with Flathub (#88 to #91). **Reverses** #274 (D3) | | |
| L1 | Track A preview (distribution Firefox with Nulavio's profile, chrome theme and start page) | **Remove** (the user-facing preview) | Signed packages replaced it; it alone carries R1, R4, R5, R12, R13, R17, R19. The launcher stays as the packaged tools and the test harness. **Amends** ADR 0001 (Track A) | | |
| L3 | Confined mode (`--confined`) | **After 1.0** | Reachable only from the preview launcher (#283), refuses on Ubuntu (R46), partial; out of the 1.0 promise until a package can start it | | |
| L4 | `nulavio desktop install` | **Remove** (with L1) | Packages install the menu entry; only the preview needed it | | |
| L2 | `nulavio doctor` | **Keep, change** | Make it reachable from a package install: the packaged `nulavio` command starts the browser, so `doctor` is out of reach of the people #81's decision and #377 send to it (#283) | | |
| P8 | Fingerprinting additions | **Keep, change** | Keep; once a release carries patch 0012, remove the Shell's per-tab screen fallback where the engine decides, so there is one mechanism | | |
| P14 | Copy Link to Highlight shortcut (#157) | **Keep, change** | Keep the engine's menu item; choose another key: Ctrl+Shift+L is the autofill key of password-manager extensions Nulavio supports (Bitwarden; inferred, not checked). **Reverses** #157's decision of 2026-11-14 (the key) | | |
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
| R8 | Phone unlock and the Android Companion | Keep | Offered since 160.0-0.3 and in 1.0's scope with the signed APK (#205, #227). Costs a second platform and is verified on one phone (R48): the largest cut available if 1.0 must be smaller | | |
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
| I1 | Integrations status page (Connect P0) | Keep | A package install cannot run `nulavio doctor` (the packaged `nulavio` command starts the browser), so this pane is where people read these facts without a terminal | | |
| I4 | Meeting links per profile (#221) | Keep | 56 lines, decided in #221 | | |
| I5 | Password provider choice (flows B, H) | Keep | Principle 4, "your tools, not ours" | | |
| A1 | AI Bridge: MCP, autonomy levels, AI Workspaces, audit | Keep | Off until an agent is added; the policy outside the model is the design | | |
| A3 | Built-in assistant | Keep | Same policy as outside agents; per-profile consent | | |
| L5 | RPM and APT packages and repositories | Keep | How 1.0 ships | | |
| L7 | The site and the waitlist | Keep | The waitlist is the project's only server, outside the browser (TB17) | | |

### Planned, not built

| ID | Issue | Recommendation | Reason, in one line | Decision | Issue |
|---|---|---|---|---|---|
| N166 | #166 Toolbar buttons you define | **Do not build** | Bookmarks with keywords (`%s`) and bookmarklets on the toolbar already open an address built from the page. **Reverses** the 2026-11-14 decision (its form) | | |
| N162 | #162 Per-site CSS | **Do not build** | Unprivileged extensions (AMO) do it; the Guard would need an exception for it | | |
| N163 | #163 Notes per site | **Do not build** | No fit with the vision's problem; AMO extensions exist | | |
| N317 | #317 Pinned sites per profile | **Do not build** | Pinned tabs are already per profile: each profile is its own instance and session | | |
| N316 | #316 Acrylic window | **Do not build** | Taste, against "calm" and the opaque security grammar; `browser.tabs.allow_transparent_browser` is off in the engine | | |
| N347 | #347 Imersivo "Painel" | **Do not build** | Moves the engine's navigation toolbar and its indicators into a side panel: the most invasive style, and #348 is the maintainer's preferred default | | |
| N155 | #155 Sidebar chatbot providers | **Do not build** | A second chat surface next to the assistant (A3); the chatbot is a provider's web page in the sidebar. **Reverses** the 2026-11-14 decision | | |
| N151 | #151 Search provider in one step (PR #442) | **Keep, change** | Keep the chooser and "Entrar"; drop "carry this search to other profiles", which writes into other profiles' folders (a new boundary and R81 in the PR) | | |
| N152 | #152 Account search in private windows and temporary profiles | **Keep, change** | Keep the generic part (the warning, refusing session tokens in templates); Kagi's extension and Privacy Pass wait for #153, After 1.0. **Reverses** the 2026-11-14 decision for Kagi (timing) | | |
| N154 | #154 Page summaries (PR #443) | **After 1.0** | Built and tested, but one preset service (Kagi) and the assistant already summarises; a new privileged module shared with N156. **Reverses** the 2026-11-16 decision (timing) | | |
| N156 | #156 Translation with a web service (PR #443) | Keep | On-device stays the default; web services on a named click, none preselected | | |
| N81 | #81 1Password | Keep | Decided P1 on 2026-11-16; principle 4 | | |
| N171 | #171 Privacy report | **After 1.0** | Option A shows the layer the engine already reports per site (the shield's panel, FR-18) and per week (`about:protections`); what is new is one place and a pointer to uBlock Origin. **Reverses** the 2026-11-16 decision (timing) | | |
| N95 | #95 Spike: native content filter | **After 1.0** | Nothing forces it (2026-11-13 decision); uBlock Origin stays | | |
| N119 | #119 Sounds | **After 1.0** | Needs a person listening; nothing depends on it; off by default anyway | | |
| N153 | #153 Spike: Privacy Pass | **After 1.0** | Research; serves N152's Kagi part | | |
| N159 | #159 Link previews ("peek") | **After 1.0** | New window surface, large design work. **Reverses** the 2026-11-14 decision (timing) | | |
| N164 | #164 Reading list with offline copy | **After 1.0** | A convenience; Reader View and bookmarks remain | | |
| N165 | #165 Feeds in the address bar | **After 1.0** | A convenience; P3 | | |
| N168 | #168 Low power mode | **After 1.0** | Its own issue says it ships only after a measurement shows a clear gain | | |
| N169 | #169 A site as a Linux app | **After 1.0** | Large: app_id, portals, routing inside an app window | | |
| N216 | #216 .onion and Onion-Location | **After 1.0** | Per-profile proxy is the engine's already; Tor outside Tor Browser risks an anonymity promise the vision rules out. **Reverses** the 2026-11-14 decision (timing) | | |
| N217 | #217 Network route per profile and site | **After 1.0** | Large, Fable-level, new secrets; the engine's per-profile proxy covers the simple case. **Reverses** the 2026-11-14 decision (timing) | | |
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
- The first rehearsal (2026-11-16): `test_split_view` (all five) and `test_load_line` 04 (#436). #439 fixed both tests before the reviewed commit; they passed in a local run of the whole suite on a build of `main`, and the issue stays open until a nightly rehearsal is green.

Of the 96 failed `ci` runs since 2026-10-25 (logs read on 2026-11-17), the 43 whose logs name what failed were mostly lint and unit tests of the release and review tooling. Feature tests among them: the phone link's unit tests in four runs (R8), and one run each of `test_engine_slice` 09, `test_shell` 03 (P11) and KeePassXC's `test_password_extensions` (I5). The other 53 logs matched nothing searchable and are not classified here. Flaky or broken feature tests with an issue: #138 (assistant), #209 (profile permissions), #246 (content filter), #280 (profiles), #398 (Imersivo), #409 (motion, profile ink), #436 (split view, load line).

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
- **Recommendation: Keep, change.** After a release that carries patch 0012 (the next one: the tag `v160.0-0.6` is at `7b94d699` and does not contain #402's `7f9e6f52`, verified with `git tag --contains`), remove the Shell's screen fallback, so one mechanism remains. Whether anything still needs it after #400 (launcher-seeded sets) is inferred, not checked.
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
- **Decided by:** #157 (closed). Ctrl+Shift+L was proposed after a check of the keys the engine, the Shell and KDE use, and the maintainer accepted it on 2026-11-14 (verified: #157's comments). Password-manager extensions were not part of that check.
- **The engine already:** has the item in the context menu.
- **Fit and cost:** the key is the cost. Ctrl+Shift+L is the autofill key of Bitwarden's extension (FR-12) and of other password managers (inferred from their documentation, not checked here). When an extension and a built-in command claim one key, which wins was not checked.
- **Recommendation: Keep, change:** keep the item; change or drop the key. **Reverses** #157's decision on the key.
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
- **The engine already:** has profiles with a selector, avatars and colours (verified: `browser.profiles.enabled` is true in 160.0's `firefox.js`). Nulavio adds the templates, the glyphs, the toolbar button and what the Vault needs (a protected profile is never the start-up one, the last unprotected profile).
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
- **Decided by:** ADR 0005; D10 revised on 2026-11-10 ([release criteria](release-criteria.md#scope-of-10-decided-2026-11-04)): phone unlock is in 1.0, checked on the real phone with the signed APK (#227), since F-Droid waits until 2027.
- **Open issues:** #207 (F-Droid: ask again from 2027-01-27), #227 (the real phone again, with the signed APK).
- **Today:** pairing is offered. `nulavio.vault.phone.pairing` is false in the module and true in the build's branding prefs since #42 (verified: `firefox-branding.js`; the security changelog of 160.0-0.3). The signed APK is attached to releases since 160.0-0.5. Unlocking with a phone already paired never depends on the pref.
- **Fit and cost:** a convenience on top of R7, which already has two recovery methods. It is the one feature that makes Nulavio maintain a second platform, and it is verified on one phone. The maintainer already weighed F-Droid's delay and kept it in 1.0 with the APK.
- **Recommendation: Keep.** If 1.0 has to be smaller, this is the cut with the most release machinery behind it: turning the pref off would stop new pairings and leave paired phones working.

### Interface

#### U9 Page-loading line

- **Code:** `NulavioLoadLine.sys.mjs` (129 lines) and its styles in `window-band.css`. Started for every window by the layout experiment; no switch (verified: no pref in the module; `experiments/layout/parent.js` calls `watch()`).
- **What it shows:** always the indeterminate state, because the engine's progress for a web page was found unreliable (verified: the module's header, "measured on 160.0").
- **Tests:** `test_load_line` (5).
- **Failures:** #436: test 04, under reduced motion, failed in the first rehearsal; #439 fixed the test before the reviewed commit, and the issue waits for a green nightly. #397 (After 1.0): its frame cost is not measured.
- **Decided by:** #318, asked for by the maintainer in the experience review; built in wave 4a.
- **The engine already:** the selected tab shows the engine's loading indicator, and the reload button turns into stop.
- **Fit and cost:** it says "loading" a second time, without progress, on every page of every window. Small code, but a progress listener per window and an unmeasured frame cost, for a cue the engine already gives.
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
- **Failures:** #436: all five failed in the first rehearsal; fixed by #439 before the reviewed commit, open until a green nightly.
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

### Integrations

#### I1 Integrations status page (Nulavio Connect P0)

- **Code:** 900 lines (`NulavioConnect.sys.mjs` 478, its experiment, the launcher's `connect.py` 236, `integrations.json`), the Integrations pane in Settings and its part of the Shell's own settings page.
- **What it does:**
  - **Status:** shows, with evidence, whether Plasma Browser Integration, the portals, a Secret Service and the default-browser setting are in place.
  - **Default browser:** makes Nulavio the default browser on request, with a way back.
- **Seams:** `Subprocess` (it runs helper programs), `AddonManager`.
- **Boundaries and risks:** TB10; R11.
- **Tests:** `test_connect` (9, unit and integration).
- **Failures:** #273 (two menu entries after "make default" on a package install, closed).
- **Decided by:** ADR 0004; FR-23.
- **The rest of Nulavio already:** `nulavio doctor` checks the Secret Service, KWallet and the native-messaging hosts (verified: `check_secrets`, `check_native_messaging` in `doctor.py`). But a package install cannot run it: the packaged `nulavio` command starts the browser (verified: `packaging/rpm/nulavio.spec`, `make_deb.sh`), and the tools inside the package are not on `PATH` (#283).
- **Fit and cost:** the default-browser action is something a person does; the status rows are diagnostics. Moving them to `doctor` would ask for a terminal, which the vision's success sentence rules out, and `doctor` is out of reach of package users anyway. The screen-cast, security-key, notification and activity rows (P1/P2, `connect_p1.py`) stay with this pane.
- **Recommendation: Keep.**

#### I2 KRunner plugin

- **Code:** `krunner.py` (102 lines) and its part of `connect_p1.py`: a D-Bus service that opens a web address or a search.
- **Boundaries and risks:** TB10; R44 (any program of the user can call it).
- **Tests:** unit `test_connect_p1`.
- **Decided by:** ADR 0004, P1.
- **The desktop already:** KDE's own runners open a typed address or a web-search keyword in the default browser (inferred; not checked on this machine).
- **Recommendation: Remove.** Replacement: KDE's runners, with Nulavio as the default browser. The plugin itself only opens an address or a search and leaves the profile to routing (verified: the header of `krunner.py`), so routing still applies. **Amends** ADR 0004 (P1).
- **For people who use it today:** "Add to KRunner" wrote two files under `~/.local/share` (ADR 0004); the update does not remove files in a home folder, so the release notes give the two paths to delete.

#### I3 KDE Connect "send link to device"

- **Code:** the link menu in `background.js` and `connect_p1.py`'s device list and share (`kdeconnect-cli`).
- **Boundaries and risks:** TB10.
- **Tests:** unit `test_connect_p1`.
- **The desktop already:** Plasma Browser Integration, which I1 detects, ships a KDE Connect plugin in its host (verified: `KDEConnectPlugin` in `plasma-browser-integration-host` on this machine). Its "send to device" menu needs its extension from AMO (inferred).
- **Recommendation: Remove.** Replacement: Plasma Browser Integration, which I1 keeps detecting; its extension asks for broader permissions than one menu item needs (inferred from its AMO listing, not checked). **Amends** ADR 0004 (P1).
- **For people who use it today:** the menu item goes; the release notes point to Plasma Browser Integration.

#### I4 Meeting links per profile

- **Code:** `NulavioMeetings.sys.mjs` (56 lines) and a group in the Integrations pane, which moves with I1's change.
- **Tests:** `test_meetings` (4).
- **Open issues:** #389 (accessibility of a locked choice).
- **Decided by:** #221.
- **Recommendation: Keep.**

#### I5 Password provider choice

- **Code:** 796 lines (`NulavioPasswords.sys.mjs` 381, its experiment, the launcher's `extensions.py`, the pages) and about 115 lines of Settings.
- **Boundaries and risks:** TB3, TB4; R8, R9, R10.
- **Tests:** `test_passwords` (7), `test_password_extensions` (3), `test_settings_passwords` (2); unit `test_engine_extensions_desktop`.
- **Decided by:** FR-10 to FR-13; flows B and H.
- **Open issues:** #225 (Proton Pass checklist), #81 (1Password).
- **The engine already:** its own manager; extensions install from AMO by hand. Nulavio installs the pinned official extension after one confirmation and turns the engine's prompts off.
- **Fit and cost:** principle 4.
- **Recommendation: Keep.**

### AI

#### A1 AI Bridge: MCP, autonomy levels, AI Workspaces, audit

- **Code:** the largest feature:
  - the launcher's `ai/` without the assistant: 6,747 lines (`tools.py` 1,531, `registry.py` 595, `cli.py` 536, `policy.py` 388, `workspace.py`, `mcp.py`, `bidi.py`, `websocket.py`, `connect.py`, `audit.py`);
  - the Shell's `NulavioAI.sys.mjs` (1,285), the request page, its experiment and the agents' part of the old settings page.
- **Seams:** WebDriver BiDi to the engine; `ExtensionParent`.
- **Boundaries and risks:** TB15; R26, R27, R28, R33, R34, R35, R36, R68.
- **Tests:** `test_ai_bridge` (25, unit and integration), `test_ai_ui` (13), `test_ai_agents_real` (2, real Claude Code); unit `test_fake_llm`.
- **Decided by:** ADR 0007; FR-26; SEC-17.
- **Open issues:** #243.
- **Off until used:** `nulavio ai serve` refuses an agent that was not registered with `nulavio ai add` (verified: `_serve` in `ai/cli.py`). Nothing listens before that.
- **The engine already:** WebDriver BiDi and Marionette, behind command-line switches, with no per-call policy.
- **Fit and cost:** not in the vision's problem statement, but one of the README's five highlights. It is the only feature with risks that same-user programs can use (R27, R33). If the maintainer wants a smaller 1.0, this is the largest single cut available: an optional package (`nulavio-ai`) for the launcher half is feasible. The Shell half (requests, the bars of a driven window, the emergency stop) needs the Shell's privileges, so it would stay or keep a narrow API (inferred).
- **Recommendation: Keep.**

#### A2 Raw automation

- **Code:** no file of its own. It runs through the registry (`set_raw_automation`), the policy (`RAW_CAPABILITY`), the tools (`raw_automation`), the workspace's marker, the Shell's critical bar and the switch in the agents' page (verified by `grep raw launcher/nulavio_launcher/ai`).
- **Boundaries and risks:** R42: outside the per-call policy and the activity record.
- **Tests:** `test_ai_bridge` 20.
- **Decided by:** ADR 0007, decision 1 ("A as an explicit raw automation option") and its amendment of 2026-10-28, which took it out of Full control.
- **Fit and cost:** it hands an agent the engine's whole automation endpoint. That is exactly what the bridge exists to put a policy in front of. Agents keep the MCP tools, which cover browsing, forms, downloads and uploads.
- **Recommendation: Remove.** Replacement: the MCP tools; for an agent's own library, a separate Firefox profile outside Nulavio. **Amends** ADR 0007.
- **For people who use it today:** an agent with "Privileged debugging" loses it at the update. The release notes say so; the agents' page shows the switch gone.

#### A3 Built-in assistant

- **Code:** 2,265 lines (the launcher's `assistant.py` 879, the side panel 1,189, `markdown.js`) and about 142 lines of Settings.
- **Boundaries and risks:** R43.
- **Tests:** `test_assistant_ui` (42 tests, 1,834 lines), `test_settings_assistant` (3); unit `test_assistant`, `test_assistant_stream`.
- **Failures:** #138 (closed).
- **Decided by:** FR-27.
- **Open issues:** #249 (side), N155 (the engine's chatbot, below).
- **The engine already:** a sidebar chatbot that loads a provider's web page (off in Nulavio, P2).
- **Fit and cost:** the same policy as outside agents, per-profile consent, the key in the system keyring. It is a second large AI surface; with N155 it would be a third.
- **Recommendation: Keep**, as the one chat surface (see N155).

### Launcher and packaging

#### L1 Track A preview

- **What it is:** `bin/nulavio setup` and `run` on the distribution's unmodified Firefox, with Nulavio's profile, a `userChrome.css` chrome theme and a local start page (README, "Try the preview without building").
- **Code:** the parts that exist only for it: `browser/theme/userChrome.css`, `browser/startpage/`, `browser/config/prefs/theme.js` (953 lines in all) and the distribution-Firefox paths of `engine.py`. The rest of the launcher (about 1,450 lines in `cli.py`, `profile.py`, `engine.py`, `paths.py`) is also the `nulavio` tools the packages ship, and stays.
- **Boundaries and risks:** R1, R4, R5, R12, R13, R17, R19 exist only for it.
- **Tests:** the integration harness itself starts profiles through the launcher on the distribution's Firefox in pull-request CI, so the harness keeps that path (verified: `ci.yml` runs the suite with no Nulavio build).
- **Fit and cost:** signed RPM and APT packages are out (160.0-0.6). The preview offers people a Nulavio without the Shell, the Vault UI, routing, the patches or the fingerprinting work, under the same name.
- **Recommendation: Remove the preview as a way to use Nulavio:** the README section, the chrome theme and the start page. Keep running the distribution's Firefox as the test harness's engine.
- **For people who use it today:** they move to the RPM or the APT package. Their profile under `~/.local/share/nulavio` is not opened by the packaged browser by itself (inferred: the package's profiles are the engine's own), so the release notes need a migration step, or the issue decides on one.

#### L2 nulavio doctor

- **Code:** `doctor.py` (307 lines).
- **Tests:** unit `test_engine_extensions_desktop`, `test_profile_and_paths`; `test_media_codecs`.
- **Reach:** the packaged `nulavio` command starts the browser (verified: `packaging/rpm/nulavio.spec` writes `%{_bindir}/nulavio` as the engine's launcher; `make_deb.sh` the same), and the tools inside the package are not on `PATH` (#283). Yet #81's decision (the 1Password `sudo` line) and #377 (the codec check) send people to `nulavio doctor`.
- **Recommendation: Keep, change:** make `doctor` reachable from a package install (for example `nulavio --doctor`, or the tools on `PATH` under another name), as #283's first point; or point those two at Settings instead.
- **For people who use it today:** only source-checkout users can run it now; nothing is taken away.

#### L3 Confined mode

- **Code:** `confine.py` (149 lines): bubblewrap around the engine, seeing only the profile and Downloads.
- **Boundaries and risks:** R46 (opt-in, partial; refuses on Ubuntu 26.04).
- **Tests:** `test_confined` (4); unit `test_confine`.
- **Failures:** #282, #312 (closed).
- **Decided by:** SEC-19; Phase 5 spikes.
- **Open issues:** #283 (package installs cannot start it, After 1.0).
- **Fit and cost:** a person who installed a package has no way to reach it. With L1 gone it would have none at all.
- **Recommendation: After 1.0.** Keep the code. Take SEC-19 out of the 1.0 promise until #283 gives packages a way to start it.
- **For people who use it today:** only preview users can; see L1.

#### L4 `nulavio desktop install`

- **Code:** `desktop.py` (95 lines).
- **Tests:** unit `test_engine_extensions_desktop`.
- **Fit and cost:** the packages install the menu entry; only the preview needs this.
- **Recommendation: Remove, with L1.**

#### L5 RPM and APT packages and repositories

- **Code:** `packaging/rpm/`, `packaging/linux/` (the menu entry, the AppArmor profile for the engine's user namespaces on Ubuntu) and the release scripts (`make_rpm.sh`, `make_deb.sh`, the signing and publishing steps).
- **Boundaries and risks:** TB8, TB18, TB19, TB21, TB22; R57, R58, R60, R61.
- **Tests:** `test_build_resources`, `check_rpm.sh`, `check_deb.sh`; unit release tests.
- **Failures:** #417, #377 (closed).
- **Recommendation: Keep.**

#### L6 Flatpak bundle attached to releases

- **Code:** `packaging/flatpak/`, `flatpak_manifest.py`, `check_flatpak*.{py,sh}`, the release's Flatpak job.
- **Boundaries and risks:** R75: trusted as far as Flathub's runtime, and **it never updates itself**.
- **Tests:** unit `test_flatpak`, `test_check_flatpak_bundle`.
- **Failures:** #324 (closed by #338).
- **Decided by:** #274 (D3, in 1.0: a Flatpak section on the download pages).
- **Open issues:** #88 to #91 (Flathub, After 1.0).
- **Fit and cost:** a browser installed from it stays on the version it was installed at until the person downloads another bundle. The update policy's 24 to 72 hours mean nothing for those people.
- **Recommendation: After 1.0,** with Flathub, which updates. Stop attaching the bundle and take the section off the download pages until then. **Reverses** #274's decision (D3).
- **For people who use it today:** they are on a version that does not update. The release notes and the download page tell them to move to the RPM or APT package, or to wait for Flathub.

#### L7 The site and the waitlist

- **Code:** `site/` (11 pages; `_worker.js`, 220 lines, the waitlist).
- **Boundaries and risks:** TB17; R69, R71.
- **Tests:** unit `test_site`, `test_site_discovery`.
- **Open issues:** #173, #199, #437 (wave 5).
- **Recommendation: Keep.**

## Evidence: planned

Each item: what the issue asks, its milestone, the maintainer's recorded decision where there is one (quoted from the issue's comments), what the engine already offers, and the recommendation. Nobody uses a planned item, so "what changes for people" is left out. An item marked **Reverses** goes against a decision recorded on its issue.

### Under construction in the other session

#### N151 Choose a profile's search provider in one step (#151, pull request #442)

- **As it stood** at `92dde400` (+905 −13 lines in 17 files, not merged):
  - a chooser at the top of Settings → Pesquisa;
  - `NulavioSearch.choose()`, and `accounts()`, which reads whether a provider's sign-in cookie exists, by its name;
  - a search choice for a new profile;
  - Ecosia, Qwant and Startpage added on request;
  - **"Levar esta pesquisa para outros perfis"**, which writes `nulavio-search-choice.json` into other profiles' folders for their Shell to apply at their next start. The pull request records this as a new trust boundary and residual risk, after its review found that a planted file could make an attacker's host the default.
- **The engine already:** default engine, separate private default, adding and removing engines; nothing about accounts.
- **Fit and cost:** the chooser serves ADR 0002. The cross-profile channel is the costly part: a file one profile writes and another trusts, for something each profile can now do in one step.
- **Recommendation: Keep, change:** merge the chooser and the new-profile choice; leave out "carry to other profiles".

#### N152 An account search provider in private windows and temporary profiles (#152)

- **As it stood:** no pull request or code on `main`; reviewed from the issue.
- **Decided (2026-11-14):** a warning before choosing; for Kagi, Privacy Pass or Kagi's extension with a Session Link; `validateTemplate` refuses a template that carries a session token.
- **Fit and cost:** the warning and the refusal are generic and cheap. The Kagi paths are one provider's mechanism, and Privacy Pass is still a spike (#153).
- **Recommendation: Keep, change:** the generic part in 1.0; the Kagi-specific part After 1.0, with N153.

#### N156 Translate with a web service you add (#156) and N154 Page summaries (#154), pull request #443

- **As it stood** at `fe60b580` (+1,760 −1 lines in 20 files, not merged; two integration runs still queued in its description):
  - a new privileged module, `NulavioServices.sys.mjs` (545 lines), with a new experiment;
  - menu items in `background.js`;
  - 22 known addresses and 14 templates;
  - groups in Idiomas and Assistente;
  - `test_web_services`, 478 lines.
- **Trust boundary:** the pull request adds one and numbers it TB22, which `main` already uses for #430's pre-check (a clash to fix in that pull request, not here).
- **Decided:** #156 on 2026-11-14 (on-device by default, preset list approved, none preselected); #154 on 2026-11-16 (the engine's on-device summary stays off; the assistant and web services by address).
- **The engine already:** translates pages and selections on the device (verified: `browser.translations.enable` and `browser.translations.select.enable` true in 160.0). The assistant (A3) already answers about a page.
- **Fit and cost:**
  - **Translation:** adds services people pick by name, on a click that names them. It is small next to what is built.
  - **Summaries:** one preset (Kagi's) beside the assistant, which already summarises.
  - Both share the new module, so splitting them is a little work in #443.
- **Recommendation:**
  - **N156: Keep.**
  - **N154: After 1.0.** If splitting the pull request costs more than keeping both, keep both: the reason against N154 is overlap, not risk.

#### N81 1Password (#81)

- **As it stood:** no pull request or code on `main`; reviewed from the issue.
- **Decided (2026-11-16):** P1 like Bitwarden; not certified; `nulavio doctor` shows the `sudo` line for `custom_allowed_browsers`, and no package edits another vendor's configuration.
- **Fit and cost:** principle 4. One more provider in I5's pattern.
- **Recommendation: Keep.** Check its key against P14.

### Wave 4b and 4c, milestone 1.0

| ID | Issue | Decision recorded | The engine already | Recommendation and reason |
|---|---|---|---|---|
| N95 | #95 Spike: native content filter | 2026-11-13: ADR 0012 stays Proposed, the spike does not start now | uBlock Origin is the filter | **After 1.0.** Nothing forces it, and the 1.0 waves do not need it |
| N119 | #119 Sounds | none | the desktop's event sounds | **After 1.0.** Off by default by design; needs a person listening; nothing depends on it |
| N153 | #153 Spike: Privacy Pass | none | no | **After 1.0.** Research; serves N152's Kagi part |
| N155 | #155 Sidebar chatbot: more providers and any address | 2026-11-14: option (a), more providers in a neutral order plus "another address"; the chatbot stays blocked by default | the chatbot sidebar with Mozilla's provider list (verified: `browser.ml.chat.provider` in `firefox.js`) | **Do not build.** **Reverses** the decision. A provider's web page in the sidebar is a second chat surface next to A3, with the provider's own cookies |
| N159 | #159 Link previews ("peek") | 2026-11-14: option (c), a panel loaded only on a click, Zen's Glance as the model | Link Preview with AI (off in Nulavio) | **After 1.0.** A new window surface and its design: wave-5-sized work |
| N162 | #162 Per-site CSS | none | user styles only by hand (`userContent.css`) | **Do not build.** Unprivileged AMO extensions do it; the issue itself has to exempt it from the Guard |
| N163 | #163 Notes per site | none | no | **Do not build.** Outside the vision's problem; extensions exist |
| N164 | #164 Reading list with an offline copy | none | Reader View, bookmarks | **After 1.0.** A convenience |
| N165 | #165 Feeds in the address bar | none | no (removed with live bookmarks) | **After 1.0.** A convenience |
| N166 | #166 Toolbar buttons you define | 2026-11-14: no "run code"; an address template or a fixed browser command | bookmarks with a `%s` keyword, bookmarklets on the bookmarks toolbar | **Do not build.** The engine covers "open an address built from the page" |
| N168 | #168 Low power mode | none | tab unloading under memory pressure | **After 1.0.** The issue says it ships only after a measurement shows a clear gain |
| N169 | #169 A site as a Linux app | none | taskbar tabs, Windows only (verified: `browser.taskbarTabs.enabled` false off Windows) | **After 1.0.** Large: app_id, the DynamicLauncher portal, routing inside an app window |
| N171 | #171 Privacy report | 2026-11-16: option A, the engine's layer only, kept in the profile | per site, the shield's panel with the engine's log of blocked trackers (FR-18); per week, `about:protections` (verified in 160.0's `AboutRedirector.cpp`). Its Lockwise, mobile-app and VPN cards default on in `firefox.js`, and Nulavio sets none of their prefs; how the page reads in Nulavio was not checked | **After 1.0.** **Reverses** the decision (timing). The issue knew of `about:protections`; option A adds one place and a pointer to uBlock Origin over what the engine reports. Before 1.0, checking `about:protections` and turning off its Mozilla cards is the cheaper step |
| N216 | #216 .onion and Onion-Location | 2026-11-14: a Tor the person runs first, off by default, a ".onion available" button | a per-profile SOCKS proxy with remote DNS (inferred from the engine's settings) | **After 1.0.** Tor in a browser that is not Tor Browser identifies the person by its fingerprint, close to the vision's non-goal; the words need care, and the work is large |
| N217 | #217 Network route per profile and site | 2026-11-14: Direct, Proxy, provider extension and Tor first; WireGuard after a spike; secrets in the keyring | per-profile proxy | **After 1.0.** Fable-level work with new secrets and a new boundary |
| N218 | #218 Mail and calendar links with privacy services | none | `mailto:` handlers | **After 1.0.** A large catalogue, P3 |
| N172 | #172 Parent: Orion's features | — | — | **Keep, change.** Close it at 1.0 with what was built (#157, #158, #160, #161, #167, #170 and what is kept above); its remaining sub-issues move After 1.0 or close |
| N219 | #219 Parent: Tor, VPNs, privacy services | — | — | **Keep, change.** #220 to #222 stay in 1.0 (wave 3); #216 to #218 move After 1.0 |

### Waves 4b and 4c, milestone After 1.0 or none

| ID | Issue | Decision recorded | Recommendation and reason |
|---|---|---|---|
| N241 | #241 Automatic updates offered at first run | 2026-11-16: option A (a disabled timer in the packages, offered through polkit) | **Keep, After 1.0 as set.** Updates are a security feature; a candidate to bring forward, the maintainer's call |
| N242 | #242 Image metadata stripped (no milestone) | none | **After 1.0.** A good privacy fit, but it rewrites the files a person sends; large and risky before a freeze |
| N249 | #249 Spike: the assistant on the opposite side | 2026-11-16: After 1.0, time-boxed | **Keep, After 1.0 as set** |
| N316 | #316 Acrylic window | none | **Do not build.** Taste against "calm" and the opaque security grammar; the engine keeps `browser.tabs.allow_transparent_browser` off (verified) |
| N317 | #317 Pinned sites per profile | none | **Do not build.** Pinned tabs are already per profile: each profile is its own instance and session (ADR 0003). What is left is a grid's look |
| N319 | #319 Motion map | none | **Keep, After 1.0 as set** |
| N321 | #321 Command palette | 2026-11-16: option A, the engine's address-bar actions | **Keep, After 1.0 as set** |
| N345 | #345 Imersivo styles (parent) | the maintainer asked for it, 2026-11-14 | **Keep, After 1.0 as set**, without N347 |
| N346 | #346 Imersivo "Barras" | — | **Keep, After 1.0 as set** |
| N347 | #347 Imersivo "Painel" | — | **Do not build.** It moves the engine's navigation toolbar and its indicators into a side panel: the most invasive style, and ADR 0009's decision 5 (the engine's indicators stay its own) is what it would strain. #348 is the maintainer's preferred default |
| N348 | #348 Spike: Imersivo "Faixa" | 2026-11-14: if it is a go, it becomes Imersivo's default style | **Keep, After 1.0 as set** |

### Not features

#362 (memory of a new profile's extension process), #364 (the build's speed), #367 (`perf.yml` as a gate), #397 (the load line's frame cost), #398 (Imersivo's test), #440 (a test of a search sign-in across a Vault lock). These get no product verdict:

- #397 closes if U9 is turned off or removed.
- #398 follows U4.
- #440 follows N151 and N152.

## Decisions and documents a recommendation reverses or amends

Where the maintainer accepts one of these, the issue for it carries the amendment:

| ID | Recommendation | Reverses or amends |
|---|---|---|
| A2 | Remove raw automation | ADR 0007: decision 1 ("A as an explicit raw automation option") and the amendment of 2026-10-28; FR-26; R42 closes |
| I2, I3 | Remove KRunner and KDE Connect | ADR 0004 (P1's KRunner and KDE Connect); FR-23; R44 closes |
| P14 | Another key for Copy Link to Highlight | #157's decision of 2026-11-14 |
| L1, L4 | Remove the Track A preview and `nulavio desktop` | ADR 0001 (Track A as the preview); README, FR-20; R1, R4, R5, R12, R13, R17, R19 close |
| L3 | Confined mode After 1.0 | SEC-19 in the requirements |
| L6 | Flatpak bundle After 1.0 | #274's decision of 2026-11-14 (D3); the download pages; R75 |
| N155 | Do not build | #155's decision of 2026-11-14 |
| N171 | After 1.0 | #171's decision of 2026-11-16 (timing) |
| N152, N154, N159 | After 1.0 (N152: the Kagi part) | The decisions on #152 and #159 (2026-11-14) and #154 (2026-11-16), timing only |
| N166 | Do not build | #166's decision of 2026-11-14 (its form) |
| N216, N217, N218 | After 1.0 | #216's and #217's decisions (2026-11-14) stay as they are; only the milestone moves (timing) |
| N95, N119, N153, N164, N165, N168, N169 | After 1.0 | Only the milestone (the roadmap's wave 4b and 4c lists) |

No recommendation reverses an accepted ADR other than ADR 0001, 0004 and 0007, as amendments. ADRs 0008, 0009 and 0011 stand: U1, U2 and U4 are kept as they are.

## After the decisions

1. The maintainer fills in **Decision** for each row.
2. For every decision other than "Keep" (and "Keep (… as set)"), an issue: the change, what replaces it, what the release notes tell people, and the amendment where the table above names one. Its number goes in the **Issue** column.
3. Planned items moved After 1.0 change milestone; items not to be built are closed with the reason, by the maintainer.
4. The roadmap's wave lists for 4b and 4c are updated in the same pull request as this table's decisions.

## How this was done

- **Worktree:** `origin/main` at `68ec0575`, without the design screenshots.
- **Inventory:** a feature-to-files map over the Shell (modules, experiments, pages, shared styles), the launcher, the patches, the configuration, the packaging and all 71 integration test modules. It fails on any Shell file, launcher module, patch or integration test module that no feature claims (configuration and packaging files are mapped but not checked that way); none was left. Patches 0001, 0002 and 0006 and the Shell's bootstrap (`background.js`, `manifest.json`, the locales) are plumbing every feature uses and are not reviewed as features. Sizes with `wc -l`; test counts are `def test_` per module.
- **Seams:** a search of the Shell for engine modules (`resource:///modules/…`, `resource://gre/modules/…`, `moz-src:///…`), members with a leading `_` on engine objects, engine methods assigned at run time, and `registerWindowActor`.
- **Engine updates:** `git log -- browser/build/engine.json`, and the files each bump touched.
- **Failures:**
  - the 96 failed `ci` runs since 2026-10-25 (`gh run list --workflow ci --status failure`, then `gh run view --log-failed`);
  - the failed `release`, `rehearsal` and `asan` runs (their failed steps, and the issues and pull requests that fixed them: #376, #381, #403, #436);
  - the 47 issues with the label `bug`.
- **Decisions:** the comments of every planned issue ("Maintainer's decision, …"), the ADRs' status lines, the requirements and the release criteria.
- **The engine:** Firefox 160.0's source as Nulavio builds it, read-only, for the prefs and pages named "verified"; the desktop facts on this machine (Fedora 44 KDE) where marked.
- **Not done:** no build, no test run (nothing here needed the integration machine), no reading of the other session's branches beyond the two pull requests, no use data (there is none).
