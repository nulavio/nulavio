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

**Use.** Nulavio has no telemetry, so nobody knows how many people use a feature. Every item says "Use: unknown, the maintainer's judgment and public feedback", and no recommendation rests on a guess about use.

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
| P14 | Copy Link to Highlight shortcut (#157) | **Keep, change** | Keep the engine's item; decide the key: Ctrl+Shift+L is also 1Password's default (#81) | | |
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

