# UX audit 2026-10-27: every finding

Generated from the audit agents' structured output. Severity: blocker > major > minor > polish. Cost: S/M/L. Evidence labels: Observed (pixels or code), Specified (docs), Inferred. Paths under `audit-captures/` refer to audit captures that were not kept (tmpfs); the integration-test artifacts of the same build are reproducible with the integration suite.


## Window chrome and security states (WCS)

The Horizon window theme is a tidy, well-guarded token layer. It is behind a pref, lives in the last brand layer, steps aside for installed themes, high contrast and forced colours, and its route mark respects reduced motion. But it stops at browser.xhtml's tokens. Results rows, panels, the app menu and sidebar documents still use stock or system colours. In the headless captures, the selected address-bar result is white on #3399FF (2.9:1) and the dark sidebar's focus ring is #0060DF on #2B2A33 (2.4:1). Mozilla promos and marks remain: the account dot, the app-menu Sync promo with a fox, and the about:home "Add-ons for Firefox" tile.

Security states are the weak point. Three are fine:
- address-bar trust indicators: upstream and untouched;
- the engine's remote-control stripes: kept;
- the download warning page: opens as an active tab.

Every state Nulavio adds is weak or missing:
- **Raw automation (blocker):** no distinct cue at all. The only Nulavio words in that window say the agent acts "dentro das permissões que você deu no Nulavio", which is false in raw mode.
- **AI Workspace, temporary profile and Guard:** each is shown only by a generic notification bar the user can dismiss. Guard has no other way back to its review page.
- **Agent driving your own profile:** gets the same "AI Workspace" words as an isolated workspace.
- **Current profile:** the colour and initial in a 16 px circle. It can overflow or be unpinned into the extensions panel. Pessoal and Pesquisa are both "P" and differ only by hue.
- **Protected profiles:** no cue in the window, although the backend already reports `encrypted`.
- **Private windows:** an icon-only mask button with no words. With an installed theme or forced colours, the private tint goes too.

Most fixes need no new engine patch:
- Prefs already exist that Horizon can read via -moz-pref(): `nulavio.profile.temporary` and `nulavio.ai.workspace`.
- Privileged Shell modules can set root attributes and create a non-removable, non-overflowing CustomizableUI widget, a "state pill" with words.
- Bars can be made persistent with the existing `dismissable` argument.
- Cues must use borders or pseudo-elements, not toolbar colour variables, because installed themes set those inline.

A small patch is justified only for giving Nulavio's own pages a non-spoofable "Nulavio" identity in the address bar instead of "Extensão (Nulavio Shell)".


### WCS-01 · blocker · cost M — AI Workspace window under raw automation (raw_automation tool)

- **Issue:** Raw automation has no distinct window state. The window looks identical to a normal, policy-checked AI Workspace: same engine stripes, same robot icon, same Nulavio bar. The bar's words state the opposite of the truth.
- **Impact:** A user watching the window believes Nulavio is still enforcing their permissions, site list and activity log. In fact nothing is checked or logged, and the window never tells them. This is a hidden-state, dark-pattern-adjacent failure of the 'raw automation always distinguishable' rule.
- **Fix:** 1) When raw_automation is granted, the bridge writes a marker the engine can see, for example `<workspace>/nulavio-raw.json` or a registry field. 2) NulavioAI (privileged) watches it (IOUtils poll or callTool) and replaces the workspace bar with a PRIORITY_CRITICAL, non-dismissable bar: 'Automação bruta: o Nulavio não verifica nem registra o que acontece nesta janela', with a 'Parar' button wired to the existing emergency stop/revoke. 3) NulavioAI also sets a root attribute (`nulavio-state~=raw`) that Horizon draws as a critical solid frame around the content area plus a state pill. These must work under lwtheme and forced colours (border plus words). 4) Reword the normal workspace bar so it cannot be true in one mode and false in the other.
- **Mechanism:** Launcher marker + Shell privileged module (notification + root attribute) + Horizon CSS; no engine patch
- **Evidence:** Specified: launcher/nulavio_launcher/ai/tools.py:163-166 and :172-176 (RAW_WARNING: 'Nulavio does not check, ask about or log what is done through this endpoint'); tools.py:461-476 hands over the endpoint, and the text goes only to the agent. Observed: the Shell's bar text is _locales/pt_BR/messages.json:390 'aiWorkspaceBar … dentro das permissões que você deu no Nulavio', set once by background.js:121-130 → NulavioAI.sys.mjs:256-266. Nothing in browser/shell reacts to raw mode (grep 'raw' finds nothing for the window). Observed: the engine stripes mean only 'a remote agent is listening' (browser/themes/shared/urlbar.css:1032-1053; browser.js:4150-4180), so before/window/ai-workspace-*.png and raw-automation-*.png carry the same cue.


### WCS-02 · major · cost S — AI Workspace window and an agent driving one of the user's own profiles (ProfileTarget)

- **Issue:** The only Nulavio cue is a standard info bar: a generic purple 'i', full width, and the user can close it with '×'. It has no Stop or Pause action. Once closed, the window keeps only the engine stripes plus a 16 px robot whose words are a tooltip. When an agent drives the user's own profile (with its cookies and logins), the window gets the same pref and the same 'AI Workspace de X' wording, so 'isolated workspace' and 'agent inside my real profile' cannot be told apart.
- **Impact:** After one click on ×, the user can no longer read in words that an agent controls this window. A user cannot tell whether an agent session runs in a disposable workspace or in their logged-in profile, which is the higher-risk case.
- **Fix:** Pass dismissable=false (5th argument), or re-append from eventCallback('dismissed'). Better: keep a dismissable explanatory bar but add the persistent state pill from Proposal 1. Add 'Pausar' and 'Parar' buttons: the backend already has pause, revoke and emergency stop. Have the launcher write the target kind (for example `nulavio.ai.target` = workspace|profile) so the words differ: 'Agente X está usando o seu perfil Trabalho'. Horizon should key the frame off an attribute the Shell sets only after its pid liveness check (NulavioAI.sys.mjs:63-73), not off the raw pref, which can be stale.
- **Mechanism:** Shell privileged module (notification args, root attribute) + launcher pref + Horizon CSS
- **Evidence:** Observed: before/window/ai-workspace-light.png and -dark.png (bar with × at the right; '(i)' icon). Observed in code: NulavioAI.sys.mjs:265 calls appendNotification with 3 arguments, so dismissable defaults to true (engine toolkit/content/widgets/notificationbox.js:145-151); the bar is re-added only for new windows (:270). Specified: launcher/nulavio_launcher/ai/workspace.py:188-196 (ProfileTarget = 'one of the user's own profiles') and :225-230 (writes the same `nulavio.ai.workspace` pref) → the same background.js:121-130 message. Note: the 'P' chip in ai-workspace-*.png comes from the capture harness naming the profile 'Pessoal' (scripts/common.py:32), so what a real workspace shows in the chip is not verified.


### WCS-03 · major · cost M — Current profile identity in the window (toolbar action chip)

- **Issue:** Spec vs implementation:
- Specified: a profile pill with its name in the tab strip, and tabs carrying the profile colour.
- Implemented: a 16 px coloured circle with the profile's initial, among extension icons.

The extra problems below build on the established '~16 px chip' finding:
- The chip is an extension action, so it overflows into the unified-extensions panel on narrow windows, and the user can unpin it. Either way the window loses every profile cue.
- The toolbar always draws the initial, never the chosen avatar. Two of the five built-in pt-BR templates, Pessoal (mint) and Pesquisa (violet), both render 'P' and differ only by hue.
- A collapsed vertical tab group draws the same grammar: a coloured circle with an initial ('P' for the group 'Pesquisa').
- **Impact:** Users acting in the wrong profile (banking vs personal, work vs research) is the core risk profiles exist to prevent. Colour-only distinction fails colour-blind users and breaks the design system's own rule. The cue can vanish entirely without the user noticing why.
- **Fix:** 1) A privileged Shell module sets `nulavio-profile-color` and `nulavio-profile-name` on each window's root (same observer pattern as markTemporary). Horizon then draws a 2-3 px identity edge on the toolbox and a light tint via border or pseudo-element, not via toolbar colour variables, so it survives lwtheme. 2) Show the name and avatar in a non-removable, non-overflowing state pill (Proposal 1); keep the action chip only as the switcher. 3) Draw the avatar glyph, not the initial, in the toolbar icon, or disambiguate initials. 4) Restyle tab-group labels as rounded rectangles in Horizon so that circle-plus-initial is reserved for profiles.
- **Mechanism:** Shell privileged module (root attributes, CustomizableUI widget) + Horizon CSS + identity tokens; no engine patch
- **Evidence:** Specified: docs/brand/ux-flows.md:18 and :96 ('A pill in the tab strip shows the active profile, and tabs carry its colour'); docs/design/component-inventory.md:34 ('Active-profile tint in the window frame (M4)'); docs/design/design-system.md:35 ('colour is never the only cue'). Observed in code: browser/shell/lib/profile-icon.js:11 (initial only) and :8-34; NulavioProfiles.sys.mjs:49-55 (templates personal=mint, research=violet; pt-BR names Pessoal and Pesquisa). Observed in engine: extension widgets overflow to #webExtList (CustomizableUI.sys.mjs:8005-8007); the pin-to-toolbar toggle is at browser-addons.js:2854 and :3003. Observed: before/window/vertical-tabs-group-collapsed-light.png (blue 'P' circle at left, x≈26 y≈214, vs the green 'P' chip at top right). Inferred render: window-chrome/crops/profile-icons-16px-light.png (PIL replica of profile-icon.js at 16 px).


### WCS-04 · major · cost S — Protected profile (unlocked, current window) and locked profiles, as seen from the chrome

- **Issue:** This builds on the established SPA-02/SB-04 finding, which is not repeated here; this entry adds the chrome evidence.
- The window has no protected or locked cue at all, although the data is already there: NulavioProfiles reports `encrypted` and `locked` for every profile, but background.js passes the current profile to drawProfileIcon, which ignores both fields.
- 'Bloquear agora' exists only deep in Settings.
- A locked profile never has a window. Its only representation is a Shell page in a tab of another profile, whose address bar says 'Extensão (Nulavio Shell)' (see WCS-08).
- **Impact:** A user cannot see in the window that the current profile is encrypted, or that it is open (unlocked) right now. They also cannot lock it from where they are. That is exactly the moment ADR 0006's protection does not apply.
- **Fix:** Feed `encrypted` into the state pill and the toolbar icon: a lock glyph plus the word 'Protegido', with the pill's menu offering 'Bloquear agora' (the backend exists in NulavioVault). Set a root attribute `nulavio-state~=protected` for Horizon; in forced colours use a double border plus the word, never colour alone.
- **Mechanism:** Shell background + privileged module + Horizon CSS; backend already exists
- **Evidence:** Observed: NulavioProfiles.sys.mjs:242-253 (`encrypted: lock !== 'plain'`, `locked`); background.js:53-59 draws only colour and initial; settings/settings.js:336 is the only 'lock' action; _locales/pt_BR/messages.json:362 'vaultProtectedBadge' is defined but referenced nowhere in browser/shell (grep). Observed: before/from-tests/vault-ui/settings-locked-profile-light.png (the 'Bloqueado' badge exists only in Settings and the popup).


### WCS-05 · major · cost S — Temporary profile window

- **Issue:** Two cues, both weak:
- an info bar the user can dismiss;
- a dashed ring on the 16 px toolbar circle: 1.6 px dashes on a slate 'T', near the sky 'T' a 'Trabalho' profile gets.

The launcher already writes `nulavio.profile.temporary=true` into the profile, but Horizon never reads it, so the window frame looks like a normal profile. This state was not captured in a window: only popup artifacts exist.
- **Impact:** After the bar is closed, someone may keep logging in or saving work in a window whose data is deleted on close, and the only reminder is a barely visible dashed ring.
- **Fix:** Add a Horizon rule `@media -moz-pref("nulavio.profile.temporary")` that draws a dashed toolbox edge (border-style survives forced colours). Add the state pill with 'Temporário · apagado ao fechar'. Keep the bar as a one-time explanation. Use a distinct glyph, not the initial, for the temporary icon.
- **Mechanism:** Existing pref + Horizon CSS + Shell pill; no patch
- **Evidence:** Observed in code: NulavioProfiles.sys.mjs:207-223 (3-argument appendNotification, PRIORITY_INFO_MEDIUM, so it can be dismissed); lib/profile-icon.js:21-25 (dashed ring); launcher/nulavio_launcher/temporary.py:45 (`"nulavio.profile.temporary": True  # the Shell shows the temporary identity`); horizon.css has no -moz-pref for it (read in full). Inferred render: window-chrome/crops/profile-icons-16px-light.png (temporary 'T' vs Trabalho 'T'). Observed: before/from-tests/temporary/popup-temporary-*.png (the words appear only inside the popup).


### WCS-06 · major · cost S — Private window

- **Issue:** Under 158's 'Nova' design the private indicator is an icon-only button: the labelled version is hidden, and in vertical tabs the label is always hidden. So the window never says 'privativa' in words.
- Default or in-app theme: the engine substitutes its purple private theme and Horizon steps aside entirely. The light and dark captures are identical, in stock Firefox purple.
- Installed lwtheme: the engine leaves the theme unchanged, so the only cue is the 16 px mask button.
- Forced colours: the lwtheme is overridden, which leads to the same result as with an installed theme (Inferred).

The mask artwork (pbm-logo.svg) is Mozilla's private-browsing logo.
- **Impact:** With a custom theme or a high-contrast setup, a private window and a normal window look nearly identical. Screen-reader and low-vision users get no words. The private state relies on Mozilla iconography in a Nulavio build.
- **Fix:** Set `browser.theme.dark-private-windows=false` so Horizon owns the private look. Add Horizon `:root[privatebrowsingmode="temporary"]`: a distinct Nulavio private tone and edge, plus the state pill 'Janela privativa'. The edge and pill sit on their own layer, so they also apply under lwtheme and forced colours (border plus words). Replace the icon via `list-style-image` on `.private-browsing-indicator-button` with a Nulavio glyph. Keep tokens contrast-checked with contrast.py.
- **Mechanism:** Pref + Horizon CSS (+ Shell pill for words); no patch
- **Evidence:** Observed: before/window/private-window-page-light.png = -dark.png (purple, mask button top right, no label); crop window-chrome/crops/private-right.png. Engine: browser/themes/shared/browser-shared.css:836-858 (label hidden; 'Nova replaces this labeled indicator with the icon-only button'); toolkit/modules/LightweightThemeConsumer.sys.mjs:366-384 ('Other themes are unchanged'). Inferred: forced-colours override of lwthemes (pref browser.theme.forced-colors-override.enabled, :235).


### WCS-07 · major · cost S — Guard warning (changes made outside Nulavio)

- **Issue:** Guard's only window cue is a warning bar the user can dismiss. Its 'Revisar' button is the only link to guard/review.html anywhere in the Shell. After ×, pending findings have no indicator until a restart or a new window. This was not captured in a window: the capture profile had no pending findings.
- **Impact:** A user who closes the bar, for example while busy, loses the only path to a security review of out-of-band changes to their profile. The warning effectively disappears.
- **Fix:** Add a persistent indicator while findings are pending: an amber 'Guard · 2' segment in the state pill, or at least `browser.action.setBadgeText` plus an amber badge colour on the Shell action (WebExtension API, no patch). Add a Guard entry in Nulavio Settings and on the new tab's protection status. Bar text should have real plurals.
- **Mechanism:** Shell background/privileged module + Horizon CSS
- **Evidence:** Observed in code: NulavioGuard.sys.mjs:671-704 (the URL is built only at :673; appendNotification at :695 without dismissable=false; the observer adds it only to new windows). grep across browser/shell: 'guard/review.html' appears nowhere else (no Settings, new tab or menu entry). Observed: before/shell/guard-review-dark.png (empty state, reachable only by URL in the capture).


### WCS-08 · major · cost M — Address-bar identity and trust indicators (upstream, untouched), including for Nulavio's own pages

- **Issue:** This adds the window angle to the established M3/SB-06 finding.
- **New tab and Shell pages:** every Nulavio page, the new tab included, shows the generic 'Extensão (Nulavio Shell)' chip with a puzzle icon. The pages that ask for vault passwords and agent permissions get exactly the chip any third-party add-on page gets. Extension names are not unique, so an add-on named 'Nulavio Shell' would produce the same chip (Inferred).
- **Loopback HTTP:** the same 127.0.0.1 page gets a shield-check in the address bar and 'Não seguro' in the split-view pane footer.
- **Under automation:** the stripes are red, so in an agent-driven window an insecure page's 'Não seguro' chip sits on red stripes and loses its distinctiveness.
- **Spec gap:** ux-flows specifies 'Not secure' with warning colour; upstream shows grey text with only the red slash on the icon.
- **Impact:** The address bar cannot vouch for Nulavio's most sensitive pages, and spoofing a vault unlock page is plausible for a malicious add-on. Mixed signals about HTTP security in split view.
- **Fix:** A small patch is unavoidable for an unspoofable identity. In browser-siteIdentity.js, treat pages of the built-in, privileged shell@nulavio.net like chrome UI: label 'Nulavio' with the brand glyph and no puzzle icon. Alternative: serve Shell pages under about:nulavio-* registered from the privileged experiment (feasibility Inferred). Also hide the chip on the new tab. Keep the upstream trust logic; consider Horizon colouring only the 'Não seguro' label with status.warning, and record that as a deliberate exception to Horizon rule 4.
- **Mechanism:** One small engine patch (identity label) or a runtime about: registration; Horizon CSS for the label colour
- **Evidence:** Observed: before/window/horizontal-tabs-*.png and urlbar-focused-empty-*.png (chip occupies about 200 px of the new-tab address bar); window-chrome/crops/split-trust-light.png (shield-check in the bar vs 'Não seguro' in the footer, from before/window/split-view-light.png); window-chrome/crops/notsecure-chip.png (from zen/shots/vertical-splitview-light.png). Specified: docs/brand/ux-flows.md:30; docs/design/component-inventory.md:22.


### WCS-09 · major · cost M — Horizon coverage: address-bar results, app menu and panels, sidebar panels and launcher

- **Issue:** Horizon re-values only browser.xhtml's chrome tokens, so several surfaces fall back to system or stock colours:
- **Address-bar results:** the selected (keyboard-focused) row uses the system SelectedItem colour. In the light capture this is white text on #3399FF (2.94:1, fails 1.4.3); in dark it is a bright cyan #00DDFF row in navy chrome.
- **Sidebar documents:** history, bookmarks and the assistant sidebar header use stock #FFFFFF / #2B2A33 and a #0060DF focus ring in both themes. On #2B2A33 that ring is about 2.4:1, below 3:1.
- **App menu:** stock #2B2A33 with a purple promo.
- **Pressed buttons:** a neutral grey (#ABB3B6 / #505A62).
- **Impact:** Keyboard users lose a compliant focus indicator in the results list and sidebars. The window looks like two products (navy/mint frame, grey/purple/blue panels), which works against calm and recognisability.
- **Fix:** In horizon.css (same guards), set --urlbarview-background-color-selected and -hover, plus --urlbarview-text-color-selected, from accent.tint/text.primary; this is cheap and in browser.xhtml. Add panel tokens (--panel-background-color, --arrowpanel-*) and the sidebar box background (M4 'panel tokens'). For sidebar documents, have a privileged Shell module register an AGENT sheet via nsIStyleSheetService, scoped with @-moz-document url-prefix("chrome://browser/content/sidebar/"), that re-values --focus-outline-color and surfaces (feasibility Inferred). Use a link patch only if that is rejected. Extend test_horizon to measure these surfaces.
- **Mechanism:** Horizon CSS + Shell-registered scoped sheet; patch only as fallback
- **Evidence:** Observed (measured on headless captures; real-desktop values depend on the GTK SelectedItem/AccentColor, Inferred): window-chrome/crops/urlbar-row-light.png from before/window/urlbar-results-typed-light.png; urlbar-results-typed-dark.png (row #00DDFF); before/window/sidebar-viewHistorySidebar-dark.png (panel #2B2A33, ring #0060DF); app-menu-reconstructed-dark.png (rgb 43,42,51, per log-extras-dark.json). Engine: browser/themes/shared/urlbar/urlbarview.tokens.css:16,24,44,64-66 (SelectedItem under -moz-native-theme). horizon.css:60-94 sets no --urlbarview-*, panel or sidebar tokens.


### WCS-10 · major · cost S — Mozilla marks, promos and services in the Track B chrome

- **Issue:** The default chrome still promotes Mozilla services and shows Mozilla artwork:
- **Account button:** a blue attention dot in every capture.
- **App menu:** opens with 'Sincronize seus dados em qualquer lugar / Entrar' and a fox illustration.
- **Account panel CTAs:** Mozilla Monitor, Relay and VPN are enabled by default (popup not drawable headless).
- **Startup tab:** about:home (Activity Stream) shows an 'Add-ons for Firefox' tile with the Firefox logo, in English. Its search box, top sites and purple '+' differ from the Shell new tab, so Nulavio has two different home pages.
- **Private window:** the Mozilla mask logo (WCS-06).
- **Impact:** These promos break the non-negotiable 'no Mozilla or third-party marks in Track B UI'. The attention dot is a mild dark pattern pulling toward an account sign-up. Two homes confuse users.
- **Fix:** Use prefs in firefox-branding.js or Track B defaults:
- identity.fxaccounts.toolbar.defaultVisible=false (or hide the button until signed in);
- identity.fxaccounts.toolbar.pxiToolbarEnabled=false;
- appMenuSignInPromo.dismissed=true.
If Sync is not a product feature, set identity.fxaccounts.enabled=false. Point the startup page and about:home to the Shell new tab, or empty Activity Stream default sites. Replace the private icon (WCS-06).
- **Mechanism:** Prefs only
- **Evidence:** Observed: before/window/horizontal-tabs-*.png (account dot at x≈1200, rgb 0,179,244); app-menu-reconstructed-light.png and -dark.png (promo, fox); startup-first-tab-light.png ('Add-ons for Firefox' tile, startup url about:home per log-light.json). Engine defaults: browser/app/profile/firefox.js:3122-3140 (identity.fxaccounts.toolbar.*, pxiToolbarEnabled.monitor/relay/vpn = true; appMenuSignInPromo.dismissed=false). Nulavio sets none of these (grep 'fxaccounts' in browser/ and launcher/: no hits). docs/design/migration-plan.md:22 already lists the top-sites item.


### WCS-11 · major · cost S — Nulavio symbol in light chrome: new-tab favicon, sidebar launcher entry, default action icon

- **Issue:** The Shell ships one mint-on-dark symbol (#6FE0C5) and uses it on light surfaces: the tab favicon on a white tab, the launcher icon on #E2EBEE, and the same icon on the launcher's pressed grey. Contrast is about 1.3–1.6:1, which fails 1.4.11 for an icon-only control. It also breaks the brand's own prohibition.
- **Impact:** In light theme, the entry point to the Nulavio assistant is nearly invisible, and so is the Nulavio identity in the tab strip.
- **Fix:** Make the symbol scheme-aware. Either add an internal `@media (prefers-color-scheme: light)` that switches the stroke to Mint 700, or use context-fill with -moz-context-properties (the Shell is a privileged built-in add-on; Inferred). Use `theme_icons` for the action. Check the result with contrast.py on toolbox, toolbar, tab and pressed backgrounds.
- **Mechanism:** Shell assets + manifest
- **Evidence:** Observed: before/window/horizontal-tabs-light.png (tab 'Nova aba'); vertical-tabs-expanded-light.png (launcher, bottom right of the sidebar); assistant-sidebar-ask-filled-light.png (mint N on #ABB3B6). Specified: docs/brand/guidelines.md:50 ('Placing the mint symbol on light backgrounds (1.47:1 contrast); use Mint 700'). Code: browser/shell/manifest.json action and sidebar_action default_icon 'shared/nulavio-symbol.svg'; scripts/build/make_shell.py:27-28 already ships nulavio-symbol-dark-on-light.svg, which goes unused.


### WCS-12 · minor · cost S — Download warning in the engine downloads panel (patch 0007) and toolbar

- **Issue:** The Shell warning page is strong: it opens as the active tab, with an amber callout, icon and words. In the downloads panel, a program row differs from a normal completed download only by its status text. Patch 0007 already tags the row with `[nulavio-program]`, but Horizon never styles it, and the toolbar downloads button gives no warning cue. The panel is a popup, so this was not drawable headless.
- **Impact:** When the user returns to the panel later, a risky file looks routine apart from one line of grey text. The design rule 'icon + words + colour' is not met. Behaviour stays safe (no Open), so the consequence is limited.
- **Fix:** In horizon.css (the downloads panel lives in browser.xhtml), style `.download[nulavio-program] .downloadDetails` with status.warning plus a warning icon via ::before (chrome://global/skin/icons/warning.svg). Add a forced-colours variant (Mark/CanvasText). No new patch.
- **Mechanism:** Horizon CSS on an attribute patch 0007 already sets
- **Evidence:** Observed in code: browser/patches/0007-downloads-never-open-a-program-from-the-downloads-ui.patch (toggleAttribute('nulavio-program'), showStatus with the label from browser/branding/nulavio/NulavioDownloads.sys.mjs:31,45). horizon.css has no [nulavio-program] rule. Observed: before/shell/download-warning-light.png. Specified: docs/design/design-system.md:67.


### WCS-13 · minor · cost S — Overall chrome calm at 1366×768 (densities, bars, furniture)

- **Issue:** Chrome height by layout:
- normal web page: 92 px (12% of 768 px);
- new tab or about:home: 122 px (16%), because the bookmarks bar shows an empty placeholder sentence;
- compact density: 78 px;
- vertical tabs: 44 px.

Every Nulavio state bar adds a full-width 48 px row. Guard plus a temporary or agent bar can stack to about 190 px (Inferred). The toolbar also carries a pressed-grey account button with a dot, uBlock's red shield (reads like an alarm next to security cues), list-all-tabs, extensions and the menu. In vertical mode the launcher shows six tools, including Mozilla's chatbot (established).
- **Impact:** There is more noise than the 'content is the focus' principle allows, and warnings compete with promos and furniture. Stacked bars push content down on small screens and train users to dismiss them.
- **Fix:** Use prefs: bookmarks bar 'never' unless the user adds a bookmark, plus WCS-10. Replace persistent state bars with the state pill and one-time bars (Proposals 1-3). Curate sidebar.main.tools. Consider leaving uBlock in the extensions panel by default.
- **Mechanism:** Prefs + Shell + Horizon
- **Evidence:** Observed: before/window/horizontal-tabs-light.png (rows 0-46, 46-92, 92-122); compact-density-light.png (0-78); vertical-tabs-expanded-light.png (0-44); ai-workspace-light.png (bar 92-140). Engine default browser.toolbars.bookmarks.visibility='newtab' (firefox.js:3100). Specified: docs/design/ux-principles.md:7.


### WCS-14 · polish · cost S — Sidebar host chrome for the Nulavio assistant

- **Issue:** The sidebar header 'Assistente Nulavio' sits on a stock grey band (#F0F0F0 / #23222B), directly above the page's own uppercase eyebrow 'ASSISTENTE NULAVIO'. The title repeats, and two surface colours meet at the seam.
- **Impact:** This is minor visual noise and looks inconsistent with Horizon.
- **Fix:** Drop the in-page eyebrow when the page runs in the sidebar, and give the sidebar header Horizon tokens (WCS-09).
- **Mechanism:** Shell page CSS + Horizon
- **Evidence:** Observed: before/window/assistant-sidebar-ask-filled-light.png and -dark.png (measured header rgb 240,240,240 / 35,34,43).


**Proposals**

- 1. Persistent 'state pill' (the window's single source of truth). A privileged Shell module creates it with CustomizableUI.createWidget({type:'custom', removable:false, overflows:false, defaultArea:'nav-bar'}); the engine API supports both flags (CustomizableUI.sys.mjs:4375-4430), so no patch is needed (feasibility Inferred). It shows the avatar, profile name and state words in priority order: Automação bruta > Agente X > Privativa > Temporário > Protegido > profile name. It has role=status and its keyboard action opens the profile popup or an explanation. It never overflows and cannot be removed, which fixes WCS-03/04/05/06 together; the existing action chip becomes just the switcher.
- 2. Window frame from attributes and prefs, drawn by Horizon. The Shell sets root attributes on each window via the same browser-delayed-startup-finished observer already used for bars: nulavio-profile-color, nulavio-state~='temporary protected agent raw guard'. Horizon also reads @media -moz-pref("nulavio.profile.temporary") directly. Draw cues with border, outline or ::before layers, never with --toolbar-* colour variables: installed themes set those inline on :root (LightweightThemeConsumer.sys.mjs:675-677), and Horizon allows no !important. Under forced colours, use system colours plus border-style patterns and the pill's words. Check new pairs in contrast.py.
- 3. One pattern language for the states, so each is distinguishable by more than hue: - profile: solid identity edge plus name; - temporary: dashed edge plus 'Temporário · apagado ao fechar'; - private: Nulavio private tone (set browser.theme.dark-private-windows=false so Horizon owns it) plus 'Janela privativa'; - agent: engine stripes kept, plus 'Agente X · Pausar · Parar', with different words for an isolated workspace and for the user's own profile; - raw automation: critical solid frame around the content, plus 'Automação bruta · sem verificação · Parar'; - protected: lock glyph plus 'Protegido · Bloquear'; - Guard: amber 'Guard · N' segment until reviewed. Infobars become one-time explanations; the pill persists.
- 4. Zen- or Arc-like organisation using only native 158 features and prefs, offered as layout presets in onboarding flow A rather than as a silent default change (ux-principles.md:14): - Clássico: horizontal tabs. - Vertical: sidebar.verticalTabs=true. - Foco: vertical tabs, sidebar.visibility='expand-on-hover', browser.uidensity=1, bookmarks bar 'never'. The nav-bar is never auto-hidden in any preset, unlike Zen's compact mode, so the address-bar trust indicators and the state pill stay visible. Profiles play the role of Arc and Zen 'spaces', with stronger isolation, through the pill plus Alt+Shift+P.
- 5. Calm defaults by prefs, with no patch: - hide the Mozilla account button and promos (WCS-10); - curate sidebar.main.tools (bookmarks, history, Nulavio assistant) and turn off Mozilla's chatbot (established); - bookmarks bar only when it has bookmarks; - Horizon tokens for the app menu, panels, address-bar result rows and the tab-group label shape (rounded rectangle, so circle-plus-initial stays reserved for profiles).
- 6. Command bar: register a Nulavio address-bar provider from the privileged Shell module (UrlbarProvidersManager; feasibility Inferred) for 'switch to profile X', 'lock this profile', 'new temporary window', 'ask the assistant (without page)'. Each result shows the profile chip, and nothing is sent anywhere.
- 7. Translucency (Opera Air) only on calm, content-neutral surfaces such as the sidebar background. It is never applied under the state pill, the address bar or warning bars. Use solid fallbacks under prefers-reduced-transparency and prefers-contrast, and measure the cost (DS-02 covers the token foundation).
- 8. Where a small patch is unavoidable: - (a) An unspoofable identity in the address bar for Nulavio's own pages (WCS-08): treat shell@nulavio.net pages as browser UI in browser-siteIdentity.js, labelled 'Nulavio' with the brand glyph. The alternative is about:nulavio-* pages registered at runtime. - (b) A one-line stylesheet link in the sidebar documents, only if the nsIStyleSheetService route in WCS-09 is rejected. Everything else above is prefs, Horizon CSS or Shell work.


**Open questions**

- Is Mozilla Sync (accounts) a kept product feature? That decides between hiding only the promos and dot, or setting identity.fxaccounts.enabled=false.
- Should private windows keep the engine's purple, which is familiar to Firefox users, or adopt a Nulavio private tone? Either way it needs words and must survive installed themes.
- How should raw-automation state reach the engine: a file in the workspace, a registry field read through callTool, or another channel? Should a raw-mode bar be impossible to dismiss?
- Should the explanatory bars stay dismissable once a persistent state pill exists? The recommendation is yes for the bar and no for the pill.
- Real-desktop check still needed (M7): the KDE Breeze SelectedItem/AccentColor contrast for result rows and sidebar focus, forced colours on a real high-contrast GTK theme, and whether forced colours drop the remote-control stripe gradients.
- What does the toolbar chip show in a real AI Workspace? Probably the default mint N, since the workspace profile is not in the profile group. The capture used a profile named 'Pessoal', so this is unverified.
- Do generated-content labels (::before content: attr()) count as acceptable state words for screen readers, or must every state have a real DOM element (the CustomizableUI widget)? The recommendation is the widget.


## Shell pages A: new tab, settings, profiles popup, routing (SPA)

The Shell pages share one honest, well-engineered component layer: tokens.css + base.css + shell.css, no innerHTML, labelled inputs, role=switch with a forced-colours fallback, motion gated on reduced motion, a 2 px focus ring everywhere, confirm dialogs that focus Cancel first, and error copy that says what happened and that nothing was changed. The en and pt_BR locales match exactly: 771 keys each, with identical placeholders. The weak points are structure and state. Nulavio settings is one very long page: 3.7k px with only two sections in docs/design/screenshots/settings-light.png and 4.5k px with an agent's permissions open in tests/artifacts/ai-ui/agent-permissions-light.png. Its pill nav wraps, is not sticky, has no search and has no entry for Smart routing. The only status line sits at the top of the page, and the page claims every setting belongs to "this profile" even where that is untrue. Several security states are missing or hard to tell apart. Protected but unlocked profiles look the same as plain ones, the locked state is dropped from accessible names, and "Full control" agents get the same badge as "Restricted" ones. The full-control consent text is shown in English in the pt-BR UI. The new tab mostly shows a tagline, a duplicate search box, generic shortcuts and help text; at 1366×768 the live protection status falls below the fold, and the page never shows which profile you are in. In the DNS one-time card, the button labelled "Manter…" turns encrypted DNS off when the engine default is already encrypted. The profile popup works with keys 1–9, but switching is not fluid. Templates create a profile in one click and look identical to the existing profiles listed just above them. The popup grows past a normal popup height, and each "switch" opens a window. The routing pages are clear and load nothing, but they never name the current profile. When the target profile is locked, the ask page dead-ends instead of offering to unlock. Long `<pre>` blocks in the AI wizard break the layout horizontally. The docs screenshots are partly stale, and no Shell page has been captured at 125% or 150%.


### SPA-01 · blocker · cost S — Settings → IA e automação → full-control confirmation dialog

- **Issue:** The consent body for 'Controle total' is a hard-coded English string from the launcher, shown inside an otherwise pt-BR dialog.
- **Impact:** A pt-BR user authorises the most dangerous agent privilege without understanding the warning. This breaks informed consent under ADR 0007 and the rule that pt-BR and en must match.
- **Fix:** Add an aiFullControlBody key to both locales and render it with t(). Keep the backend string for the CLI only, or have the backend return a code instead. Add a test that fails when any dialog body is not a locale key.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/ai-ui/full-control-warning-dark.png and docs/design/screenshots/ai-full-control-warning-light.png (pt-BR title and buttons, English body). Observed: browser/shell/settings/ai.js:36 `body: state.fullControlWarning`; launcher/nulavio_launcher/ai/policy.py:63 FULL_CONTROL_WARNING (English); launcher/nulavio_launcher/ai/cli.py:261 sends it to the UI.


### SPA-02 · blocker · cost M — Profile popup and Settings → Perfis list (protected / locked states)

- **Issue:** A protected (encrypted) profile that is unlocked looks exactly like a plain profile: no badge, no glyph, and nothing on the current profile either. Locked profiles get only a text badge, styled differently in each place: accent tint in the popup, quiet grey in settings. Chips never carry a lock glyph.
- **Impact:** Users cannot tell which profiles are protected, so they may browse sensitive sites in a profile they believe is protected. This violates the non-negotiable that the 'protected or locked profile' state must always be visible and distinguishable.
- **Fix:** Create one security-state badge family with icon + word: Protegido (open lock), Bloqueado (closed lock), Temporário (dashed ring). Add a small lock overlay to the chip. Use the same badge on the current profile, the popup rows, the settings rows and the routing/unlock pages. Add the state to accessible names.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/settings.js:356-361 (badges only for current and locked); browser/shell/profiles/popup.js:65 (popup shows only a locked badge, class 'badge'); settings.js:360 ('badge badge--quiet'); browser/shell/lib/ui.js:77-87 (chip changes only for temporary). Observed: tests/artifacts/vault-ui/settings-locked-profile-light.png ('Bloqueado' grey pill, no glyph).


### SPA-03 · major · cost S — New tab → one-time DNS card

- **Issue:** When DNS is already encrypted by the engine default (encryptedNow), the body text says 'você pode manter assim', but the button 'Manter o resolvedor do computador' calls setDns({choice:'system'}), which turns encryption off. No button keeps the current encrypted default.
- **Impact:** A user who clicks a button that looks like 'keep' silently downgrades to unencrypted DNS. This privacy downgrade behind misleading wording borders on a dark pattern.
- **Fix:** Make the buttons depend on state. When encryptedNow, offer 'Manter criptografado (padrão atual)' (records the choice), 'Escolher outro resolvedor…' and 'Usar o resolvedor do computador (sem criptografia)'. When not encrypted, keep the current three. Word the downgrade as a change, not as 'keep'.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/newtab/newtab.js:99 (body switches to dnsChoiceBodyEncrypted) and :108 (keep button → setDns system); newtab.html:36-38; _locales dnsKeepSystem 'Manter o resolvedor do computador' and dnsChoiceBodyEncrypted 'Você pode manter assim, escolher outro resolvedor ou usar o resolvedor do seu computador'.


### SPA-04 · major · cost M — Settings: information architecture

- **Issue:** All 7 sections sit on one scrolling page. The nav pills are not sticky and wrap to 2 lines in pt-BR at about 1354 px. Nothing marks the current section, and there is no search. Smart routing has no nav entry (it is a card inside Perfis). Search, which needs the least care, comes first; AI with its emergency stop comes last. The search engine list alone runs about 1,400 px at 8 engines × about 170 px.
- **Impact:** Users struggle to find DNS, routing, AI or Vault controls. Keyboard users face 100+ tab stops, and orientation is lost once the nav scrolls away.
- **Fix:** Use two panes: a sticky left rail (a sticky top segmented nav at narrow widths) with aria-current, grouped as Este perfil (Busca, Senhas, DNS, Exceções de sites) / Todos os perfis (Perfis, Roteamento, IA e automação) / Este computador (Integrações). Show one section per hash (#dns etc. keep working). Add a local 'Buscar nas configurações' filter over headings and labels. Make Roteamento its own entry.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/settings.html:19-27 (nav), :146 (routing card inside #profiles); tests/artifacts/vault-ui/settings-locked-profile-light.png (nav wraps); tests/artifacts/ai-ui/agent-permissions-light.png (4499 px tall); docs/design/screenshots/settings-light.png (3731 px with 2 sections). Specified: docs/design/migration-plan.md:90 'M5 Organised sections'.


### SPA-05 · major · cost S — Settings header and section scope

- **Issue:** The intro says 'Estas configurações pertencem a este perfil', but routing rules are shared by every profile in the group, agents and integrations are per computer, and the profile list is global. The header never shows which profile is being configured.
- **Impact:** Users misjudge reach: they think a routing rule or agent permission affects only this profile, or change DNS or passwords in the wrong profile. 'Você sabe onde está' fails inside Settings.
- **Fix:** Put the current profile chip, name and state badge (Protegido / Temporário) in the header. Tag each section 'Este perfil' / 'Todos os perfis' / 'Este computador'. Rewrite the intro to match.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/settings.html:16-18 (no identity in header); _locales settingsIntro; browser/shell/modules/NulavioRouting.sys.mjs:87 '// -- rules (shared by every profile of the group)'.


### SPA-06 · major · cost M — Settings: feedback for changes

- **Issue:** There is one global #status line at the top of the page. Every auto-saved switch, select, row action and row-action error announces 'Salvo.' or '⚠ …' there, often thousands of pixels away from the control.
- **Impact:** Sighted users see no confirmation, or miss errors such as err_locked or err_in_use. Screen-reader users hear it but cannot tell which control it refers to.
- **Fix:** Show the confirmation inline next to the control or row (as the existing .form-error already does), plus a fixed bottom toast area for errors. Keep a single polite live region, but write the control name into it ('Sugestões do Google: salvo').
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/settings.html:31; browser/shell/lib/ui.js:118-124 (announce writes to #status); settings.js:22-41 (run() falls back to the global status); tests/artifacts/ai-ui/agent-permissions-light.png shows '✓ Salvo.' under the header while the edited permission is about 2,000 px lower.


### SPA-07 · major · cost S — routing/ask.html and routing/blocked.html

- **Issue:** The pages show the target profile (chip + name) but never the current one. The secondary action reads 'Abrir neste perfil' or 'Abrir neste perfil mesmo assim' without naming the profile, and there is no 'Por que estou vendo isto?'.
- **Impact:** Faced with a bank link, the user cannot compare where they are with where the rule wants to go, so 'open here anyway' is an uninformed choice.
- **Fix:** Lay the page out as 'current chip + name → target chip + name' above the held address, with labels 'Abrir em {atual}' and 'Abrir em {destino}'. Add a 'Por que isto apareceu?' disclosure naming the rule and how to edit it.
- **Mechanism:** Shell page
- **Evidence:** Observed: docs/design/screenshots/routing-ask-light.png, routing-blocked-dark.png; browser/shell/routing/page.js:90,105 (routingOpenHere / routingOpenHereAnyway); ask.html:16-29. Specified: docs/brand/ux-flows.md:9 (safe primary + informed secondary + 'why').


### SPA-08 · major · cost S — routing/ask.html when the target profile is locked

- **Issue:** 'Abrir em Bancos' calls routing.openIn, which fails with 'locked'. The page then shows 'Esse perfil está bloqueado. Desbloqueie primeiro.' and offers no unlock action. The automatic path (#handOff) already opens vault/unlock.html in this situation.
- **Impact:** The most likely setup, a protected bank profile with an 'ask' rule, dead-ends. The user is pushed toward 'Abrir neste perfil', the less safe path.
- **Fix:** Read the target's lock state in render(). If it is locked, make the primary 'Desbloquear {perfil} e abrir', which opens vault/unlock.html?p=&u= with the held address, and keep 'open here' secondary.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/modules/NulavioRouting.sys.mjs:214-216 (openIn fails 'locked') vs :532-535 (handOff opens vault/unlock.html with u=); browser/shell/routing/page.js:43-56, 87; _locales err_locked.


### SPA-09 · major · cost S — Template buttons (Settings → Novo perfil, popup → Novo perfil)

- **Issue:** Clicking a template creates a persistent profile at once; in the popup it also opens a window. The hint says 'Um modelo só preenche nome, ícone e cor', which suggests the form gets prefilled. In the popup, the 'Bancos' and 'Trabalho' templates sit right under existing 'Bancos' and 'Trabalho' profiles with the same icon and colour.
- **Impact:** Users who mean to open a profile create 'Bancos 2' instead, which clutters profiles and erodes trust; the copy promises a preview that never happens.
- **Fix:** Make templates prefill a create sheet (name, icon, colour, protected yes/no, then Criar). In the popup, replace the template chips with a single '+ Novo perfil…' entry that opens the sheet or Settings.
- **Mechanism:** Shell page
- **Evidence:** Observed: docs/design/screenshots/profile-selector-light.png (Bancos and Trabalho in both lists); browser/shell/profiles/popup.js:86-91; browser/shell/settings/settings.js:395-412; settings.html:127 (profilesTemplatesNote).


### SPA-10 · major · cost S — Accessible names of profile buttons

- **Issue:** In the popup, every profile button has aria-label 'Abrir {nome}', which overrides the visible 'Bloqueado' badge. In Settings, a locked profile's button shows 'Desbloquear…' but keeps aria-label 'Abrir {nome}'.
- **Impact:** Screen-reader users cannot perceive the locked state and hear an action different from the one shown and performed (fails WCAG 2.5.3 Label in Name; the security state is not exposed).
- **Fix:** Build the name from the visible text: 'Bancos, bloqueado, desbloquear' or 'Abrir Bancos (protegido)'. Drop the aria-label override, or keep it in sync with textContent and the state badges.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/profiles/popup.js:60,65; browser/shell/settings/settings.js:303,311-313.


### SPA-11 · major · cost S — Settings → IA e automação → agent list and emergency stop

- **Issue:** The autonomy badge uses the same accent-tint .badge for Restrito, Assistido, Autônomo and Controle total. Revoked and Paused are quiet grey. The emergency stop is an ordinary switch, and no page-level banner appears while agents are stopped.
- **Impact:** An agent with full control looks no riskier than a restricted one, and 'all agents stopped' is easy to miss, so automation states are visible but not distinguishable.
- **Fix:** Use the security-state badge family: Controle total (warning tint, icon and word), Autônomo (warning outline), Pausado and Revogado (neutral with icon). While stopped, show a persistent status-warning callout at the top of the AI section with a 'Retomar' button. Consider a prominent 'Parar todos os agentes' button instead of a switch.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/ai.js:147-152; tests/artifacts/ai-ui/agent-permissions-light.png and wizard-light.png ('Total · Controle total' badge styled like 'Restrito'); settings.html:260-263.


### SPA-12 · major · cost M — Settings → agent → Permissões (capability matrix)

- **Issue:** Each of the 16 rows has a mode select and a duration select. The duration select only takes effect if it is set before the mode; changing it alone does nothing. It always shows 'Até mudar' even when the note says 'Sua escolha, até {hora}'. All 16 duration selects share the accessible name 'Por quanto tempo'.
- **Impact:** Users believe a grant is temporary when it is permanent, or the reverse. Screen-reader users cannot tell which duration belongs to which capability. The matrix runs about 1,700 px.
- **Fix:** Use one control per capability: Permitir / Perguntar / Bloquear, plus a 'por tempo limitado…' option that opens a small duration choice, showing the real expiry. Name it 'Duração: {capacidade}'. Group capabilities by risk (Leitura, Ação, Sensível), with a compact table layout.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/ai.js:53-64 (listener only on the mode select; the duration select has no selected state), :65-71 (meta text), :84, :55 (shared aria-label); tests/artifacts/ai-ui/agent-permissions-light.png.


### SPA-13 · major · cost S — Settings → Conectar um agente (wizard command and config)

- **Issue:** `<pre class='notice mono'>` blocks have no overflow or wrap rule, and they sit in grid sections without minmax(0,1fr). A long command or path widens the whole AI section past the 52rem column and the viewport.
- **Impact:** At 1366×768 the page scrolls horizontally, and buttons and text drift off screen right at the moment the user has to read and approve a command that changes their agent's config.
- **Fix:** Add `pre.notice{overflow-x:auto; white-space:pre-wrap; overflow-wrap:anywhere; max-inline-size:100%}` and `.section,.card{min-inline-size:0}` with `grid-template-columns:minmax(0,1fr)`. Add a 'Copiar' button beside the command as well.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/ai-ui/wizard-light.png (AI card spans past the viewport while Integrações stays at 52rem); tests/artifacts/ai-ui/connect-result-light.png (1402 px wide capture); browser/shell/settings/settings.html:320,329; shell.css has no pre rule.


### SPA-14 · major · cost M — New tab

- **Issue:** Most of the page is not live information: a logo and a slogan headline, a second search box that duplicates the address bar (the hint even says 'ou use a barra de endereço'), generic shortcuts (Ctrl+T on a page you just opened with it), three troubleshooting steps and a legal/limits footer on every tab. With the DNS card, the live protection status starts below the fold at 1366×768. The page never says which profile you are in, and the address bar shows 'Extensão (Nulavio Shell)'.
- **Impact:** The tab's purpose is unclear within 3 seconds, and users learn to ignore the content, including a real warning (uBlock off) that ends up at the fold. Profile identity, the main safety cue in a multi-profile browser, is missing.
- **Fix:** Build a calm home. Top: a profile strip (chip, name, Protegido/Temporário badge). Next: one protection summary line that is collapsed when all is well ('Tudo ativo neste perfil') and expands only warnings with an action. Then the search field, or rely on the address bar. Move shortcuts, 'Se um site quebrar' and the footer behind a '?' link or into Settings/help. Show one-time decision cards above the summary.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/shell-newtab.png (1366×645: hero + DNS card only); docs/design/screenshots/after-light-1366x768.png (the uBlock ⚠ warning cut at the fold; 'Extensão (Nulavio Shell)' chip); browser/shell/newtab/newtab.html:16-29,56-80; startpage.css:25 (8vh top padding). Specified: docs/design/component-inventory.md:22 (identity chip known issue).


### SPA-15 · major · cost S — Settings: how changes are saved

- **Issue:** Most switches and selects save on change (search defaults, suggestions, routing, emergency stop). The assistant switch 'Este perfil pode enviar perguntas e páginas ao modelo' only applies after the form's 'Salvar'. DNS radios need 'Usar este', and profile edits need 'Salvar'. Nothing marks unsaved changes.
- **Impact:** A user who turns the assistant permission off and leaves the page keeps it on. The mixed save models make every control's behaviour uncertain.
- **Fix:** Switches always save on change (the assistant permission switch calls assistantAllow on change), and forms with text fields keep an explicit Save plus a dirty-state hint. Document the rule in design-system.md.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/ai.js:399-418 (allowed saved only on submit); settings.js:186-194, 499-504 (instant save); settings.html:241 (dnsSave 'Usar este'), :285-291.


### SPA-16 · major · cost S — Entry points to Nulavio settings

- **Issue:** There is no app-menu or about:preferences entry for 'Configurações do Nulavio'. The page is reachable only from the popup ('Gerenciar perfis'), the new tab's search link, the routing/vault/AI pages, or Add-ons → Nulavio Shell → Opções. The ☰ 'Configurações' item opens the upstream preferences.
- **Impact:** Users looking for DNS, Passwords, AI permissions or Vault end up in upstream about:preferences and may never find Nulavio's controls.
- **Fix:** Now: add a persistent 'Configurações do Nulavio' link to the new tab and the popup footer, and an omnibox keyword. Later: decide whether a minimal link from about:preferences is worth a patch.
- **Mechanism:** Shell page
- **Evidence:** Observed: grep of browser/ for settings/settings.html or openOptionsPage finds only Shell pages (newtab.html:29,37; popup.js:157; routing/*.html:28; vault/create.js:141; ai/request.html:27; assistant/panel.js:102); manifest options_ui only. Inferred: user path via ☰ → Configurações.


### SPA-17 · minor · cost M — Profile popup: switching fluidity and length

- **Issue:** The heading says 'Trocar para', but each click launches or opens a window of that profile, and nothing shows which profiles are already running. Every opening repeats a static isolation paragraph. 'Este site', 5 template buttons and 3 stacked quiet footer buttons push the pt-BR popup past about 700 px. There is no arrow-key navigation and no filter. In a temporary profile, focus lands on 'Gerenciar perfis', which leads to an 'unavailable' notice.
- **Impact:** Switching is slower and less predictable than Arc-like expectations, and the popup scrolls (Inferred: Firefox caps action popups at about 600 px).
- **Fix:** Rows show chip, name and state glyphs (lock, 'aberto' dot). Arrows, Enter and 1–9 work, and typing filters. Label the group 'Abrir perfil', and when a window is already running, focus it rather than adding one if the engine allows. Move the note behind '?'. Use one '+ Novo perfil…' entry, a compact footer ('Gerenciar', 'Configurações') and a ≤ 600 px budget. In a temporary profile, focus 'Nova janela temporária' and explain how to get back.
- **Mechanism:** Shell page
- **Evidence:** Observed: popup.js:1-3 comment ('opens another profile in its own window'), :172 (focus order); Observed (static reconstruction of popup.html with the shipped CSS in the installed build): audit-captures/shell-pages-a/render/popup-shot.png (content exceeds 720 px); tests/artifacts/temporary/popup-temporary-light.png (focus on Gerenciar perfis).


### SPA-18 · minor · cost S — Shared CSS: card titles and heading scale

- **Issue:** Card titles (h2/h3) render as 13 px uppercase muted labels. They come out smaller and lower in contrast than field labels and body text, so flagship areas ('ROTEAMENTO INTELIGENTE', 'ASSISTENTE NULAVIO') read as captions. The new tab's DNS card puts its question in this label style with 16 px body text below.
- **Impact:** The hierarchy is inverted, users scan past the key sections, and the question is not the first thing read.
- **Fix:** Introduce heading tokens (h3 = 18–20 px semibold text.primary). Keep uppercase micro-labels only for popup group labels and facts' dt.
- **Mechanism:** tokens
- **Evidence:** Observed: browser/startpage/startpage.css:56-63; tests/artifacts/vault-ui/settings-locked-profile-light.png; tests/artifacts/dns/newtab-choice-dark.png.


### SPA-19 · minor · cost S — Badges across pages

- **Issue:** The accent-tint .badge stands for unrelated meanings: Padrão, Perfil atual, em uso, Disponível (integrations), every autonomy level, and Bloqueado in the popup. The Integrations default-browser row says 'Disponível' while its text says links open in Firefox.
- **Impact:** A colour that should signal 'yours / selected' also marks risk and availability, which weakens every state.
- **Fix:** Split badges into info (neutral), selected (accent) and security-state (icon + word, warning tint where risky). Map integration states to words that describe the user's situation ('Outro navegador é o padrão').
- **Mechanism:** Shell page
- **Evidence:** Observed: shell.css:156-167; settings.js:51-52, 359-360; ai.js:149; popup.js:65; settings.js:607; docs/design/screenshots/integrations-light.png.


### SPA-20 · minor · cost S — pt-BR copy across these pages

- **Issue:** Search uses four different terms (Busca, Pesquisa/Pesquisar, buscador, mecanismo de busca). Anglicisms appear throughout: 'Padrão do engine' (while the footer says 'motor'), workspace/AI Workspace, endpoint, alias, build, checksum. Plurals are faked: 'login(s)', 'sessão(ões)'. 'Bloqueado' means a locked profile while 'Bloquear' is an agent mode and the routing 'blocked' case. Hint paragraphs run 4+ lines (routingIntro, routingInPageHint, aiProfilesHint).
- **Impact:** The text reads as translated rather than native, and the same word names different security concepts. Long text raises the reading load.
- **Fix:** Write a pt-BR glossary in docs/brand. Use one search term ('pesquisa' / 'mecanismo de pesquisa'), 'motor' for engine, and 'Impedir' or 'Negar' for the block mode. Decide whether 'AI Workspace' is a product name. Choose plural keys in JS (_one/_other). Cut hints to one sentence and put details behind 'Saiba mais'.
- **Mechanism:** Shell page
- **Evidence:** Observed: _locales/pt_BR/messages.json keys dnsStatusDefault, dnsNowDefault, aiDisposable, aiStopHint, assistantUrlLabel, passwordsEngineLogins, aiConnectedNow, profilesLocked, aiMode_block, routingIntro, routingInPageHint; tests/artifacts/dns/newtab-choice-dark.png ('Padrão do engine').


### SPA-21 · minor · cost S — AI wizard, activity log, integration evidence

- **Issue:** Backend and internal strings reach the UI unlocalised: the wizard target 'Claude Code user settings (~/.claude.json): available in all your projects' inside a pt-BR sentence, activity reasons such as 'recusado (preset:assisted)', raw tool names (evaluate, navigate), and English evidence lines.
- **Impact:** Mixed languages and jargon make the agent log hard for non-developers to act on.
- **Fix:** The backend returns codes and the Shell maps them to locale keys (aiReason_preset, aiTool_navigate…), keeping the raw detail in a 'Detalhes técnicos' disclosure.
- **Mechanism:** Shell privileged module
- **Evidence:** Observed: tests/artifacts/ai-ui/wizard-light.png; launcher/nulavio_launcher/ai/connect.py:23; launcher/nulavio_launcher/ai/policy.py:98; browser/shell/settings/ai.js:367-368; docs/design/screenshots/integrations-light.png.


### SPA-22 · minor · cost S — Screen-reader semantics in settings rows

- **Issue:** Repeated buttons have no object in their accessible name: 'Usar este' (passwords), 'Bloquear agora' and 'Celulares' (profiles), 'Pausar', 'Revogar', 'Remover', 'Nova chave' (agents). The agent sub-headings 'Seus perfis que este agente pode usar' and 'Sites que este agente abre…' are `<p class=subhead>`, not headings. The agent site field has no visible label, only a placeholder and aria-label.
- **Impact:** A screen reader's button list shows many identical 'Revogar' entries, and heading navigation skips the agent sub-areas.
- **Fix:** Use `aria-label='{verb} {object}'` consistently (as engine and rule removal already do), turn the subheads into h4, and give visible labels to inline fields.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/settings.js:334,343,677; ai.js:116,137,140,187-220.


### SPA-23 · minor · cost S — New tab: protection status live region

- **Issue:** The facts list is `<dl aria-live=polite>`, and it is filled right after load by replacing the '…' placeholders.
- **Impact:** Screen readers will probably announce six status values every time a new tab opens.
- **Fix:** Fill the list before exposing it (no aria-live at load). Announce only real changes after load, for example a warning that appears.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/newtab/newtab.html:45; newtab.js:14-18 (show()). Inferred: announcement behaviour.


### SPA-24 · minor · cost S — routing/ask.html: remember option and focus

- **Issue:** 'Lembrar para este site' sits after the action buttons, so in tab order it comes after the buttons it modifies, and focus starts on the primary button. Ticking it with 'Abrir neste perfil' quietly rewrites the rule to 'Nunca trocar de perfil'. On load, focus jumps to the primary button and skips the explanation.
- **Impact:** Keyboard users act before they see the option, and the permanent rule change is never stated.
- **Fix:** Move the checkbox above the buttons, word it for the chosen action ('Sempre abrir em {destino}' / 'Nunca perguntar de novo para {site}'), and tie the explanation to the primary button with aria-describedby.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/routing/ask.html:22-26; page.js:27-30 (setRuleAction 'stay'), :115 (focus).


### SPA-25 · minor · cost S — Settings → Roteamento inteligente → rules

- **Issue:** Rules cannot be edited, only removed and added again. The Perfil select stays enabled for 'Nunca trocar de perfil', which ignores it. Rule chips show initials while profile rows show icons. A rule whose target is missing shows '⚠ ⚠' (the string's ⚠ plus .form-error::before). Domain and host rules give no hint about which wins.
- **Impact:** Rules are clumsy to change, the controls are confusing, and the visuals are inconsistent.
- **Fix:** Add an inline Edit per rule, disable or hide Perfil when the action is 'stay', pass the avatar to chip(), remove the ⚠ from the string, and show precedence ('o endereço exato vence o domínio').
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/settings.js:455-457,466,509; settings.html:171-179; shell.css:122; _locales routingTargetMissing; docs/design/screenshots/routing-rules-light.png.


### SPA-26 · minor · cost M — States vs the specified state rules

- **Issue:** Errors use status.warning (amber) instead of status.critical. Removals offer no undo. Loading is shown only through aria-busy, with no visible sign. Engine 'Remover' is disabled without saying why. 'Apagar histórico' stays enabled when the history is empty.
- **Impact:** Error and warning look alike, and slow checks (Integrations) look broken.
- **Fix:** Errors use criticalText with an icon. Use skeleton rows in bg.sunken (a spinner only after 400 ms). Show an 'Desfazer' toast for rule, exception and engine removal. Disabled controls get an inline reason. Empty lists disable their clear action.
- **Mechanism:** Shell page
- **Evidence:** Observed: shell.css:117-122; settings.html:196,205,249 (aria-busy only); settings.js:110,454; tests/artifacts/assistant/settings-light.png. Specified: docs/brand/guidelines.md:86,88 (skeleton; critical icon for errors); docs/brand/ux-flows.md:125 (success + undo).


### SPA-27 · minor · cost S — Settings in an AI Workspace window

- **Issue:** In an AI Workspace window the whole AI section returns early and stays hidden, with no notice.
- **Impact:** A user who opens Settings there finds AI controls (including the emergency stop) missing with no explanation.
- **Fix:** Show a notice in the AI section: 'Este é o AI Workspace de {agente}; gerencie agentes na sua própria janela', with no controls.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/settings/ai.js:428-430.


### SPA-28 · minor · cost S — Font scaling

- **Issue:** Headings use px tokens (32/24/20 px) while body text uses rem, and the popup width is 20rem.
- **Impact:** When users raise the default font size (not zoom), body text grows and headings do not, so the hierarchy flattens or inverts. No Shell page has been verified at 125% or 150%.
- **Fix:** Generate rem font-size tokens for pages (keep px for chrome) and add Shell pages to the 100/125/150% matrix.
- **Mechanism:** tokens
- **Evidence:** Observed: browser/startpage/tokens.css:8-15 (px sizes); shell.css:71,198,210,261. Specified: docs/design/accessibility.md:31 (scaling checked for chrome only).


### SPA-30 · minor · cost S — Docs and test evidence

- **Issue:** docs/design screenshots predate S6/S12. The popup capture lacks the 'Novo perfil protegido…' and 'Nova janela temporária' buttons, settings-*.png shows 2 nav items, and routing-rules-*.png has the old intro. Dark captures force data-theme, so the `<picture>` symbol stays in its light variant (dark teal on navy). No Shell pages are captured at 125% or 150%, or at 1366×768 with a real window.
- **Impact:** Reviews and regressions are judged against images that no longer match the build.
- **Fix:** Regenerate the screenshots from the integration tests on each Shell change. Force dark with ui.systemUsesDarkTheme, as test_horizon does, instead of data-theme. Add Shell pages to the matrix.
- **Mechanism:** docs/tests
- **Evidence:** Observed: git log (screenshots 9ce65dc 02:06 vs popup cd5b55d 21:49 on 2026-10-26); tests/artifacts/dns/newtab-choice-dark.png (symbol); tests/integration/test_dns.py:82 (data-theme forcing); docs/design/screenshots/matrix-after.png (chrome only).


### SPA-32 · minor · cost S — Settings → Integrações

- **Issue:** About 10 rows, mostly 'Indisponível' with a '–' mark, get the same weight as the actionable ones. The default-browser row is labelled 'Disponível' while it actually means 'another browser is the default'.
- **Impact:** Users have to scan noise to find the two or three actions that matter.
- **Fix:** Show the actionable and in-use items first, and fold 'Indisponível neste computador (n)' into a disclosure. Use state words that describe the situation.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/ai-ui/wizard-light.png (Integrações list); docs/design/screenshots/integrations-light.png; settings.js:595-619.


### SPA-29 · polish · cost S — Shape language

- **Issue:** The principles reject Nova-style pills, yet primary buttons, settings nav items and the new-tab search field are full pills, while secondary buttons use a 10 px radius, so the shapes are mixed.
- **Impact:** The look is inconsistent, and the result contradicts the stated identity.
- **Fix:** Choose one radius policy (md 10 px for all buttons, lg 14 px for search) or update the principle; apply it through tokens.
- **Mechanism:** tokens
- **Evidence:** Specified: docs/design/ux-principles.md:14. Observed: shell.css:30,47-51,200-207; tests/artifacts/dns/settings-light.png ('Usar este' pill next to rectangular secondary buttons).


### SPA-31 · polish · cost S — Shared card hover

- **Issue:** `.card:hover` changes the border colour on every card, interactive or not.
- **Impact:** It suggests the card can be clicked when it cannot.
- **Fix:** Limit the hover border to cards that are links or buttons (e.g. `.card--interactive`).
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/startpage/startpage.css:95-97.


**Proposals**

- Rebuild Settings as two panes: a sticky left rail grouped by scope (Este perfil: Busca, Senhas, DNS, Exceções de sites · Todos os perfis: Perfis, Roteamento, IA e automação · Este computador: Integrações), one section per hash, aria-current, and a local 'Buscar nas configurações' filter over locale strings. The header shows the current profile chip, name and state badge. Shell page only; existing deep links (#dns, #routing, #ai-assistant) keep working.
- Create one security-state component family (icon + word, never colour alone): Protegido, Bloqueado, Temporário, Janela privativa, AI Workspace, Controle total, Pausado, Revogado. Add a lock overlay on the identity chip. Use it identically in the popup, Settings, routing, unlock and new-tab pages, and include the state in accessible names.
- Make the profile switcher Arc-like but honest about separate windows: chip rows with state glyphs and a running dot, type-to-filter, arrow keys and 1–9, focus an existing window before opening another, and a single '+ Novo perfil…' that opens a create sheet. Templates prefill name, icon and colour plus a 'Proteger com senha' option. Keep the popup ≤ 600 px.
- Make the new tab a calm home (Opera Air / Zen calm): a profile strip, one line of protection status that expands only when something is off, one-time decision cards with real headings, optional search hand-off. Move shortcuts, help and the footer behind '?'. Any translucency must respect prefers-reduced-transparency and prefers-contrast.
- Recompose the routing ask/blocked pages as 'current → target': two chips with names, the held address as text, primary 'Abrir em {destino}' (or 'Desbloquear {destino} e abrir' via vault/unlock.html?p=&u=), secondary 'Abrir em {atual}', tertiary 'Não abrir' (closes the tab), with 'Lembrar' above the buttons and a 'Por que isto apareceu?' disclosure.
- Split IA e automação into sub-areas (Agentes · Conectar · Assistente · Atividade). The emergency stop becomes a prominent button plus a persistent banner while active. The permission matrix becomes a compact risk-grouped table with one control per capability and visible expiry. All consent and warning copy lives in _locales, with the backend returning codes only.
- Add a token and CSS pass: heading tokens in rem (h3 18–20 px semibold text.primary), one radius policy, badge tiers (info / selected / security), and pre blocks that wrap or scroll inside their card. Add inline per-control save confirmations plus an undo toast, and skeleton loading in bg.sunken.
- Write a pt-BR glossary in docs/brand (pesquisa, motor, perfil protegido / bloqueado, impedir vs bloquear, AI Workspace yes or no) with plural keys, and lint the locales for ⚠ inside strings, '(s)' plurals and untranslated tokens.


**Open questions**

- Should Nulavio settings stay a separate Shell page reached from the new tab and popup, or should a minimal patch link it from about:preferences or the app menu (the patch stack must stay minimal)?
- Should templates keep their one-click speed (create and open) or move to prefill-then-confirm? The current copy promises the latter.
- Can switching focus an existing window of a running profile instead of always opening a new one (upstream SelectableProfileService.launchInstance behaviour), and is that wanted?
- Is the in-page search box on the new tab wanted at all, given that the address bar searches with the same engine?
- Is 'AI Workspace' a product name to keep untranslated in pt-BR, or should it become 'Espaço de trabalho de IA'?
- Should the 'no pills' rule in ux-principles.md:14 change, or should the CSS change to match it?
- Should agents at the 'Autônomo' level also get warning styling, or only 'Controle total'?


## Shell pages B: protected profiles and warnings (SB)

These pages are honest and safe in their underlying behaviour. The held address is shown only as text and never loaded. No "Open" button exists for executables. If encryption fails, the half-made protected profile is removed. AI Workspace windows can never answer requests. Guard lists the most serious changes first and states its limits. The lookalike page gets the pattern right: the safe action is primary and focused, risk is stated in words, icon and colour, and a "why" explains it. The other pages break that same pattern in several security moments. On the AI request, "Allow once" is the filled primary while "Deny" is a borderless quiet button (only keyboard focus defaults to Deny). The download warning has no primary at all, and "Delete" is the weakest button even when Safe Browsing recommends deleting. The 6-digit comparison pre-focuses "They match". The strongest consent in the product, the full-control warning, appears in English inside the pt-BR UI. It also omits that full control turns on raw automation, which is never checked or logged. Protection state is visible only while a profile is locked: an open protected profile has no badge or glyph anywhere (the "Protected" string exists but is never used). The backend can replace the recovery code and add or remove methods, but no UI exposes this. So a recovery code lost when the tab closes, or the recovery-only state, has no way forward in the UI. Several things break keyboard and screen-reader flow: focus is lost after dynamic re-renders (Guard, phone unlock, cancel), the status line puts a ✓ on progress text and instructions, and accessible names contradict the visible labels for locked profiles. Visually the pages share tokens with Horizon. But heading scale, button shapes (pill primary next to 10 px secondary, against ux-principles), card use and severity glyphs vary from page to page. Pages that ask for a vault password are labelled "Extensão (Nulavio Shell)" by the chrome. So they do not yet feel like one product with the window chrome, and visually they can be spoofed. Light and dark are at parity in every capture. The en and pt-BR locale files have the same 771 keys, but strings coming from the backend bypass them. None of these pages respond to forced colours or prefers-contrast.


### SB-01 · blocker · cost S — ai/request.html (agent permission request)

- **Issue:** Visual hierarchy favours allowing. "Permitir uma vez" is the filled mint primary, "Permitir nesta sessão" is a bordered secondary, and "Negar" is a borderless quiet button. Only keyboard focus defaults to Deny. The page also has no risk icon or colour. This breaks the rule that every warning has a safe primary action.
- **Impact:** A mouse user, or anyone reacting to a tab that just stole focus, is drawn to the prominent Allow pill. This is the very moment a prompt-injected agent is asking for something the user did not request. Even "allow for the session" looks heavier than "deny".
- **Fix:** Make "Negar" the filled primary, first in order and focused. Make "Permitir uma vez" secondary and "Permitir nesta sessão" quiet or behind a disclosure. Add a warning or critical callout (icon + words) whose level depends on the capability. Add a test that checks button classes, not only focus.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/ai-ui/permission-request-light.png and -dark.png (Negar shown as a plain text button with only a focus ring). browser/shell/ai/request.html:398-400; request.js:457 focuses deny. Specified: docs/brand/ux-flows.md:9; docs/design/design-system.md:101.


### SB-02 · blocker · cost S — settings/ai.js full-control confirmation dialog

- **Issue:** The dialog body is an English constant from the Python launcher (policy.FULL_CONTROL_WARNING via cli.py "fullControlWarning"). It does not come from _locales, so pt-BR users see an English paragraph under a Portuguese title and buttons. The document lang is pt-BR, so screen readers read the English text with a Portuguese voice.
- **Impact:** The single most consequential consent in the product (ADR 0007) cannot be understood by pt-BR users, the primary locale, which defeats informed consent. It also breaks the identical-keys rule.
- **Fix:** Add aiFullControlBody (en and pt-BR) to _locales and render that string. Keep the Python constant for the CLI only. Add a test that dialog bodies on Shell pages come only from browser.i18n.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/ai-ui/full-control-warning-light.png and -dark.png. browser/shell/settings/ai.js:33-39 (body: state.fullControlWarning); launcher/nulavio_launcher/ai/policy.py:63-67; launcher/nulavio_launcher/ai/cli.py:261; browser/shell/lib/i18n.js:9 sets lang to the UI language.


### SB-03 · major · cost M — Full-control warning (content)

- **Issue:** The full_control preset allows every capability, including "debugging". That capability is what unlocks raw automation (BiDi), which the bridge does not check, ask about or log. The warning only says "sensitive operations without asking" and never mentions this. The aiLevelHint_full_control text ("Everything you allow") suggests the user still picks what is allowed.
- **Impact:** Users accept full control without knowing they are also enabling an unaudited automation channel. ADR 0007 requires that this mode "says plainly" that it bypasses the per-call policy.
- **Fix:** List concretely in the dialog what full control turns on, including "automação direta: nada do que o agente fizer por ela é verificado nem registrado". Better: remove debugging from the preset and require a separate explicit opt-in with its own confirmation.
- **Mechanism:** Shell page
- **Evidence:** Inferred from code: launcher/nulavio_launcher/ai/policy.py:37 (debugging), :61 (full_control = all capabilities). Specified: docs/adr/0007-ai-bridge.md:28 and :86. Observed: the warning text in full-control-warning-light.png has no such mention.


### SB-04 · major · cost M — Settings › Profiles rows, profile selector popup, toolbar profile icon

- **Issue:** "Protected" is never shown. Only locked profiles get a badge ("Bloqueado"). An open protected profile, including the one in the current window, looks exactly like an unprotected one. The toolbar icon draws no protection mark. The vaultProtectedBadge string exists but is unused, and status().protection (password/os/phone) is returned but never rendered.
- **Impact:** Users cannot tell whether the window they are typing bank credentials into is the encrypted profile. This breaks the non-negotiable that protected and locked states are always visible.
- **Fix:** Add a protected glyph overlay to the identity chip and the toolbar icon (lock-open vs lock-closed, plus words). Add a "Protegido · senha, celular" badge and note in Settings and the popup, built from status().protection. Use the same marker in the .target chip on unlock and phone pages.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/vault-ui/settings-locked-profile-light.png (only the Bloqueado badge). browser/shell/settings/settings.js:357-361; browser/shell/profiles/popup.js:65; browser/shell/lib/profile-icon.js:8-35; browser/shell/modules/NulavioVault.sys.mjs:105 (protection); _locales/en/messages.json:362 vaultProtectedBadge (no reference in any .js or .html file).


### SB-05 · major · cost S — warning/warning.html (download warning, flow E)

- **Issue:** There is no primary action. "Mostrar na pasta" is secondary and "Excluir" is a quiet text button, even in the Safe Browsing state whose copy says "Recomendamos excluí-lo". No initial focus is set. The critical state reuses the warning triangle. In light mode .callout--critical uses --nv-color-status-criticalText, which is defined only for dark, so text and icon fall back to navy. Only a light, generic capture exists.
- **Impact:** The recommended safe action is the least visible one. The path towards running the file is the most visible. A flagged download looks almost like a routine one.
- **Fix:** Choose actions by severity. When flagged: "Excluir arquivo" as focused primary with a critical icon (octagon) and a specific reason per danger type. When generic: "Fechar" or "Manter sem abrir" as primary, with "Mostrar na pasta" and "Excluir" secondary. Add a light criticalText token (or a fallback) and capture both states in both themes.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/shell-download-warning.png. browser/shell/warning/warning.html:283-286; warning.js:357-361; browser/shell/shared/shell.css:88; browser/startpage/tokens.css:76-79 (light has no criticalText) vs :113 and :150. Specified: docs/brand/ux-flows.md:9 and :79 ("Safe Browsing verdicts ... replace the generic text with the specific reason"; only one generic warnDanger string exists).


### SB-06 · major · cost M — vault/unlock.html and vault/phone.html (pages that take the profile password or recovery code)

- **Issue:** These pages ask for vault secrets inside an ordinary tab. The chrome labels them "Extensão (Nulavio Shell)", which the component inventory already calls confusing. Nothing in the chrome says "this is Nulavio". Any website can draw a pixel-identical card, and Guard's own copy teaches users that extensions are risky.
- **Impact:** Users get used to typing their protected-profile password into a page labelled as an extension. That makes a convincing phishing target for any site or malicious add-on, and lowers trust in the real page.
- **Fix:** Short term: rename extName to "Nulavio" and add a small header with the Nulavio mark and the page type to every security page. Proper fix: have a privileged module present shell@nulavio.net pages in the identity box as "Nulavio" with the route mark. Later, consider a tab-modal chrome sheet for secret entry.
- **Mechanism:** Shell privileged module
- **Evidence:** Specified: docs/design/component-inventory.md:59. browser/shell/_locales/en/messages.json:2 (extName "Nulavio Shell"). Inferred: the vault pages have no in-page brand header and their screenshots are content-only.


### SB-07 · major · cost S — vault/phone.html, 6-digit comparison (SAS)

- **Issue:** "São iguais" is the filled primary and gets focus automatically (phone.js:100). "São diferentes" is secondary. Making the confirming answer the default trains users to approve without comparing. A keyboard user can confirm with a single Enter.
- **Impact:** This weakens the only check against someone else scanning the QR (the copy itself says "Outra pessoa pode ter lido o código").
- **Fix:** Give both answers equal weight and focus the digits or question, not a button. Better: compare-and-choose, where the computer shows three 6-digit options and the user picks the one on the phone. Read the digits to screen readers as separate digits.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/vault-ui/phone-compare-light.png and -dark.png. browser/shell/vault/phone.html:35-36; browser/shell/vault/phone.js:93-101.


### SB-08 · major · cost M — vault/create.html step 3 (recovery code)

- **Issue:** On entering the step, focus jumps to the first input ("Grupo 3 do código"), below the code. Screen-reader users are never taken to the code or the new heading. The code is one 28-character mono string with unnumbered groups, so users must count to groups 3 and 6. There is no save, print or copy aid and no guard against leaving. The profile already exists at this point, so closing the tab loses the code.
- **Impact:** Users may finish with a protected profile whose only recovery secret was never seen or saved. This is the main way people get permanently locked out (ADR 0006: no master key).
- **Fix:** Focus the step heading, then the code region. Render the 7 groups as a numbered grid and read them group by group. Offer "Salvar em arquivo…" and "Imprimir" (check clipboard use against ADR 0006). Add a beforeunload guard. If the step is abandoned, mark the profile "código de recuperação não confirmado" in Settings with a "Gerar novo código" action (see SB-09).
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/vault-ui/create-3-recovery-light.png and -dark.png. browser/shell/vault/create.html:62-78; create.js:119 (focus on first input), :186-192 (profile created before step 3), :203-214.


### SB-09 · major · cost M — Settings › Profiles (managing a protected profile's methods)

- **Issue:** NulavioVault.change() supports new-recovery-code, add-password, add-keyring and remove-method. The UI exposes only "Bloquear agora" and "Celulares" (remove-method for phones only). Users cannot see a profile's unlock methods, replace a lost or leaked recovery code, add a password to a keyring-only profile, or leave the "only the recovery code works now" state.
- **Impact:** Recovery and hardening paths exist in the backend but are unreachable. After a keyring loss or an abandoned onboarding, the user stays one secret away from losing the profile.
- **Fix:** Turn phone.html into a "Métodos de desbloqueio" page (vault/methods.html). It lists every envelope with its kind and date and offers add, replace and remove under a fresh re-authentication. It warns below two methods and offers to add a new password right after a recovery-code unlock.
- **Mechanism:** Shell page
- **Evidence:** browser/shell/modules/NulavioVault.sys.mjs:29 (CHANGES), :154-170; browser/shell/settings/settings.js:333-345. Specified: docs/adr/0006-nulavio-vault.md Lifecycle (add or remove method, warn below two). Observed: tests/artifacts/vault-ui/unlock-recovery-required-light.png.


### SB-10 · major · cost M — passwords/lookalike.html (flow D)

- **Issue:** "Continuar em paypa1.example" permanently stops future warnings for that pair of sites in this profile (pref nulavio.passwords.lookalikeDismissed, keeps 200 entries). This is said only in the third bullet of the collapsed "Por que estou vendo isto?" disclosure. Settings has no list where users can review or undo these dismissals.
- **Impact:** One hurried click, possibly on an actual phishing site, silently turns off the protection for that site with no way back. The consequence is hidden inside a disclosure.
- **Fix:** State the consequence on or next to the button ("Continuar e não avisar de novo para este par"), or remember it for the session only. Add "Sites que você confirmou" under Settings › Senhas, each with a remove action. Handle dismiss() errors.
- **Mechanism:** Shell page
- **Evidence:** browser/shell/modules/NulavioPasswords.sys.mjs:29 and :315-319; browser/shell/passwords/lookalike.html:201-208; _locales/en/messages.json:658 (lookalikeWhy3); lookalike.js:242-245. Observed: tests/artifacts/passwords/lookalike-light.png.


### SB-11 · major · cost S — guard/review, vault/unlock, vault/phone

- **Issue:** Keyboard focus is lost after the UI changes. In Guard, act() re-renders the whole list after Undo or Keep, so the clicked button disappears and focus falls to the body. In unlock, "Desbloquear com o celular" hides the focused alternatives block without moving focus, and phone outcomes (declined or expired) leave focus nowhere. In the phone page, Cancel hides itself. In recovery-required, "Voltar" focuses a hidden password field.
- **Impact:** Keyboard and screen-reader users are thrown to the top of the document in the middle of a security task and must find their place again. With eight Guard findings this happens eight times.
- **Fix:** After resolving a Guard finding, focus the next card's heading (or the empty notice). In unlock and phone, focus the panel heading or the new primary control on every state change. Add activeElement assertions to test_guard and test_vault_ui for these transitions.
- **Mechanism:** Shell page
- **Evidence:** browser/shell/guard/review.js:114 and :151-153; browser/shell/vault/unlock.js:89-94, :142-151, :164-168, :171-180; browser/shell/vault/phone.js:79-86 and :183.


### SB-12 · major · cost S — Status line (#status) on unlock, phone, create, request

- **Issue:** announce() defaults to level "ok", so progress text and instructions get a ✓: "✓ Desbloqueando…", "✓ Esperando o celular ler o código…", "✓ Leia este código…" and "✓ Agora só o código de recuperação desbloqueia este perfil." The phone-unlock instruction is duplicated (hint and status). Errors use the amber warning colour instead of the critical style the guidelines give errors.
- **Impact:** A success tick next to a degraded or waiting state misstates security status. Duplicates are announced twice to screen readers. Users cannot tell errors from warnings.
- **Fix:** Add levels info, progress, ok, warn and error, with ✓ only for ok, a neutral spinner or dots (reduced-motion aware) for progress, and critical style for error. Do not repeat the hint in the status line. Show recovery-required as a warning with the reason and the next step.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/vault-ui/unlock-phone-light.png, phone-qr-dark.png, unlock-recovery-required-light.png. browser/shell/lib/ui.js:308-313; browser/shell/shared/shell.css:116-118; browser/shell/vault/unlock.js:104, :180, :230; browser/shell/vault/phone.js:126. Specified: docs/design/design-system.md:92 (✓ for results); docs/brand/guidelines.md:88 (error = status.critical).


### SB-13 · major · cost S — vault/phone.html copy

- **Issue:** The copy contradicts itself and overstates. phoneExplain says "this computer cannot open the profile without it", which is false because password and recovery code still work. phoneKeyHint says pairing needs "the recovery code and one other method", while the field accepts "password or recovery code". The CTA "Mostrar o código" sits under a "código de recuperação" field and reads as "show my recovery code". vaultNoMasterKey (the footer on every vault page) lists password, computer login and recovery code but not the phone.
- **Impact:** Users misread what pairing changes and might think they must keep the phone forever. Some may hesitate, fearing the CTA will reveal their recovery code.
- **Fix:** Rewrite: "O celular vira mais um jeito de desbloquear; a senha e o código de recuperação continuam valendo." Rename the CTA to "Mostrar QR para o celular". Align the hint with the real rule (needs-two-methods). Add the phone to vaultNoMasterKey.
- **Mechanism:** Shell page
- **Evidence:** _locales/en/messages.json:747 (phoneExplain), :755 (phoneKeyHint); phoneCurrentLabel and phoneShowCode. Observed: tests/artifacts/vault-ui/phone-idle-light.png.


### SB-14 · major · cost S — vault/create.html step 2 and vault/unlock.html success

- **Issue:** The password option claims it "Protege os arquivos do perfil neste computador e em cópias deles" without saying "while locked". ADR 0006 states that an unlocked profile is readable by any program running as the user. After unlocking, the page closes within 800 ms and never says when the profile locks again (when its last window closes, or after 2 minutes if not opened).
- **Impact:** Users overestimate the protection while the profile is open and do not know they must close its windows to re-lock it.
- **Fix:** Change the hint to "Enquanto bloqueado, protege…; aberto, programas rodando como você podem ler os arquivos." Change the success message to "… desbloqueado. Ele volta a bloquear quando você fechar a última janela dele." Mirror the same wording in Settings next to "Bloquear agora".
- **Mechanism:** Shell page
- **Evidence:** _locales/en/messages.json:342 (vaultChoosePasswordHint); browser/shell/vault/unlock.js:96-101. Specified: docs/adr/0006-nulavio-vault.md Consequences and S6 "Lock when the window closes".


### SB-15 · major · cost M — guard/review.html

- **Issue:** Each finding's title is an h2 with .card__title, an eyebrow style (13 px, uppercase, muted, letter-spaced). The most important line is therefore the least prominent, and names are distorted ("PROTON PASS: FREE PASSWORD MANAGER", "NET.NULAVIO.GUARD_TEST"). A new root CA and a user.js edit look identical: there is no severity icon, colour or word, no count and no timestamp. Preference findings show raw values ("browser.safebrowsing.malware.enabled: padrão → false") with one generic explanation.
- **Impact:** Users cannot see at a glance which changes are dangerous (a MITM root CA, Safe Browsing turned off) and which are benign.
- **Fix:** Use a real card heading style (16-20 px, primary, sentence case) and a severity badge with icon and words (Crítico for root, module and protective prefs off; Atenção for others). Add a summary line with counts and human titles per watched pref ("Proteção contra malware desligada"), keeping the raw key as detail.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/guard/review-light.png and -dark.png. browser/shell/guard/review.js:80 and :144; browser/startpage/startpage.css:56-63.


### SB-16 · major · cost S — vault/phone.html, removing a phone

- **Issue:** "Remover" acts immediately, with no confirmation dialog and no warning about how many methods remain. It reuses the pairing form's secret field (labelled for "Mostrar o código") as its re-authentication, and shows an error if the field is empty.
- **Impact:** A mis-click silently removes an unlock method. The interaction model is confusing because the input belongs to another action.
- **Fix:** Use a confirmDialog naming the phone, with its own secret field inside the dialog and a warning when fewer than two methods would remain. Announce the result and focus the list afterwards.
- **Mechanism:** Shell page
- **Evidence:** browser/shell/vault/phone.js:134-151. Specified: docs/design/design-system.md:87 (destructive action quiet and confirmed); docs/adr/0006-nulavio-vault.md (remove method warns below two).


### SB-17 · major · cost S — Settings › Profiles and profile popup (locked profiles)

- **Issue:** Accessible names contradict what is shown. In Settings, the button for a locked profile shows "Desbloquear…" but keeps aria-label "Abrir <nome>". In the popup, each row's aria-label ("Abrir <nome>") replaces its content, so the "Bloqueado" badge is never announced.
- **Impact:** Screen-reader users are not told a profile is locked, and voice-control users cannot say the visible label.
- **Fix:** Build aria-label from the visible words ("Desbloquear <nome>…", "<nome>, bloqueado"), or drop aria-label and use aria-describedby for the badge.
- **Mechanism:** Shell page
- **Evidence:** browser/shell/settings/settings.js:299-313; browser/shell/profiles/popup.js:56-66. Fails WCAG 2.5.3 Label in Name and 1.3.1.


### SB-18 · minor · cost S — vault/create.html step 1 (profile kind)

- **Issue:** Template buttons set aria-pressed, but no CSS styles [aria-pressed]. All five chips look identical, so the only sign of the choice is the auto-filled name.
- **Impact:** Sighted users cannot see which kind, colour and icon the protected profile will get. That identity is what later tells them which window they are in.
- **Fix:** Make it a radio group of chips with a selected style (accent ring and ✓, raised surface) and a preview chip next to the name field.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/vault-ui/create-1-profile-light.png and -dark.png. browser/shell/vault/create.js:122-131 (grep finds no aria-pressed rule in shell.css or startpage.css).


### SB-19 · minor · cost S — Unavailable, invalid and error states (create, unlock, guard, lookalike)

- **Issue:** Several states are left undesigned. create.js "unavailable" leaves the h1 empty. unlock storage-unavailable leaves a blank gap (empty #who and #explain), has no retry and no install command, and shows "Este perfil está bloqueado" before data loads. Guard's error state keeps aria-busy="true" forever and has no retry. Lookalike "invalid" renders two empty buttons and an empty role=alert. In recovery-required, "Voltar" loops back to a single "Usar o código" button and nothing says why only the code works.
- **Impact:** Users hit dead ends without a way forward, and screen readers meet empty headings and buttons.
- **Fix:** Use one state template per page: a titled headline, a reason, and an action such as Tentar de novo, Fechar or a copyable install command (e.g. dnf install gocryptfs fuse3 libsodium). Show a skeleton while loading, hide unusable controls, and remove aria-busy on error.
- **Mechanism:** Shell page
- **Evidence:** browser/shell/vault/create.js:254-258; Observed: tests/artifacts/vault-ui/unlock-storage-unavailable-dark.png. browser/shell/vault/unlock.html:18; browser/shell/guard/review.js:167-170; browser/shell/passwords/lookalike.html:198-199 with lookalike.js:248-250; browser/shell/vault/unlock.js:89-94 and :228-231. Specified: docs/brand/guidelines.md:85-88 (loading skeleton; error = icon, title, explanation, action, what happens next).


### SB-20 · minor · cost S — Form errors (create step 2, unlock, phone)

- **Issue:** Errors are not tied to their fields: no aria-invalid and no aria-describedby, and the field keeps its normal style. On create step 2 the message sits below both radio options, far from the password fields. On unlock it appears after the alternatives buttons.
- **Impact:** Users have to search for what went wrong. Screen readers announce the alert but do not connect it to the field.
- **Fix:** Put the error right under the field, set aria-invalid and aria-describedby, and add an error border token. Add a show-password toggle and a Caps Lock hint for secret fields.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/vault-ui/create-2-protection-light.png and tests/artifacts/vault-ui/unlock-error-light.png. browser/shell/vault/create.html:55; browser/shell/vault/unlock.html:44.


### SB-21 · minor · cost M — ai/request.html (context)

- **Issue:** The page gives too little context. All capabilities look the same ("ler páginas" vs "fazer compras e pagamentos" vs "executar JavaScript"). There is no countdown, although requests expire after 120 s. It does not show which profile or workspace the agent acts in. "Gerenciar agentes e permissões" navigates the same tab away, and the request (marked .seen) can never be found again. "Permitir nesta sessão" is ambiguous (browser session or agent session). The tab is opened with win.focus(), which steals focus.
- **Impact:** Users decide without the facts that matter and can lose a pending request by following the page's own link.
- **Fix:** Use risk tiers per capability (icon, words, critical style for transactions, execute_js, local_resources, private_tabs, multiple_profiles), show the expiry as "expira em 1:52 — sem resposta = negado", and add the profile chip and workspace name. Open "Gerenciar" in a new tab. Rename the session button to "Permitir até o agente desconectar".
- **Mechanism:** Shell page
- **Evidence:** browser/shell/ai/request.js:445-458; browser/shell/ai/request.html:403; launcher/nulavio_launcher/ai/registry.py:369-380 (120 s expiry); browser/shell/modules/NulavioAI.sys.mjs:162-186.


### SB-22 · minor · cost S — confirmDialog for full control

- **Issue:** The generic confirm dialog has no warning icon and does not name the agent ("este agente"). It does not list what changes, and the body text uses the secondary colour. One click grants the most dangerous level. Cancel being focused and the red-outlined confirm button are correct.
- **Impact:** The risk gets the same visual weight as removing a search engine.
- **Fix:** Add a danger variant of the dialog with a critical icon and the agent name in the title. List the newly allowed capabilities, including raw automation, and use primary-colour body text. Consider a confirmation checkbox ("Entendo que ações já feitas podem ser irreversíveis").
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/ai-ui/full-control-warning-light.png. browser/shell/lib/ui.js:280-305; browser/shell/shared/shell.css:262.


### SB-23 · minor · cost S — passwords/lookalike.html (comparison)

- **Issue:** The two hostnames appear only inside a proportional-font sentence, and the differing character (1 vs l) is not highlighted. The page does not say which profile's saved login matched.
- **Impact:** Users must spot the difference themselves, which is exactly what the attack relies on them failing to do.
- **Fix:** Show the two names side by side in mono with the differing characters highlighted, plus screen-reader text ("‘1’ no lugar de ‘l’"). Add the profile chip.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/passwords/lookalike-light.png. browser/shell/passwords/lookalike.js:235.


### SB-24 · minor · cost M — All pages in this area vs Horizon chrome and other Shell pages

- **Issue:** The pages are inconsistent with each other and with the chrome. Create uses an unstyled h1 (UA 2em with large margins) while unlock, phone, lookalike, warning and request use the 20 px warning__headline. Guard has no card while the others do. Primary buttons are pills next to 10 px secondary buttons, which goes against ux-principles' "not 24 px pills". Warning and critical share one triangle glyph. The mint radial glow (mint means "your route") sits behind danger warnings.
- **Impact:** These security moments do not read as one product family with the window chrome, and severity loses visual meaning.
- **Fix:** Create one "security moment" template (see proposals) with a fixed heading scale, 10 px radius for all buttons, glyphs per severity (info, warning triangle, critical octagon) and a neutral canvas without the mint glow on warning pages.
- **Mechanism:** Shell page
- **Evidence:** browser/shell/vault/create.html:18 vs browser/shell/vault/unlock.html:18; browser/shell/guard/review.html:16; browser/shell/shared/shell.css:47-51; browser/startpage/startpage.css:17-19. Specified: docs/design/ux-principles.md:14; docs/brand/guidelines.md:44. Observed across all captures listed above.


### SB-25 · minor · cost S — Accessibility media features on Shell security pages

- **Issue:** Only the switch has a forced-colors rule. Callout tints vanish in forced colours. Primary buttons have transparent borders and may lose all distinction (Inferred). Nothing responds to prefers-contrast. docs/design/accessibility.md covers only the window chrome.
- **Impact:** High-contrast users may not see which action is safe or that a callout is a warning.
- **Fix:** Add forced-colors rules (primary = 2 px ButtonText border plus Highlight fill, callouts = CanvasText border, icons kept) and prefers-contrast rules (stronger borders, no tints). Extend accessibility.md and the tests to cover Shell pages.
- **Mechanism:** Shell page
- **Evidence:** browser/shell/shared/shell.css:347-350; docs/design/accessibility.md:16-37. Inferred, not yet verified on a real high-contrast theme.


### SB-26 · minor · cost S — Copy (pt-BR and en)

- **Issue:** Plurals are faked: "1 login(s)" and "$COUNT$ mudança(s) feita(s)". pt-BR is inconsistent: "Por que estou vendo isso?" vs "…isto?". warning.html ships English fallback text that flashes before localisation. Guard shows raw values ("false", "1"), and request.js falls back to the raw key for unknown capabilities.
- **Impact:** The copy feels unpolished at moments that need confidence.
- **Fix:** Add singular and plural keys (or Intl.PluralRules), unify on "isto", remove the inline English and hide the page until it is localised, map known values to words, and add a lint for raw keys.
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/artifacts/passwords/settings-light.png ("1 login(s)"). _locales/en/messages.json:529 and :642; pt_BR warnWhy (line 58) vs lookalikeWhy (line 655); browser/shell/warning/warning.html:258-290.


### SB-27 · minor · cost S — Tests and docs for these surfaces

- **Issue:** Several states have no capture: the Safe Browsing (critical) download state, the download warning in dark mode, Guard empty and error, phone unavailable (Avahi) or not protected, create unavailable, lookalike invalid, and AI request expired. docs/design/screenshots/vault-settings-locked-profile-dark.png is stale (old nav, no "Celulares"). The component inventory does not list vault, Guard, lookalike or AI request pages.
- **Impact:** Regressions in the most sensitive states go unnoticed, and redesign work starts from outdated references.
- **Fix:** Capture every body[data-state] in both themes. Refresh the docs screenshots from tests/artifacts. Add inventory rows for these pages.
- **Mechanism:** docs/tests
- **Evidence:** Observed: the tests/artifacts listing; docs/design/screenshots/vault-settings-locked-profile-dark.png vs tests/artifacts/vault-ui/settings-locked-profile-light.png; docs/design/component-inventory.md:42-78.


**Proposals**

- One "security moment" template for unlock, phone, lookalike, download, Guard and the AI request. It has a context header (Nulavio mark, page type, target profile chip with protected glyph), a severity glyph (info, warning triangle, critical octagon) with words, the headline, an evidence block (.url or mono), a one-sentence consequence, a focused safe primary, an informed secondary, a "why" disclosure and a limits footer. Every body[data-state] is designed (skeleton after 400 ms, error with retry, unavailable with a next step). Calm, Opera-Air-like neutral surfaces without the mint glow; 10/14 px radii matching the chrome.
- Make protection a first-class identity attribute, Arc-style "spaces with identity". The chip gains a lock overlay (open or closed). The toolbar icon and an optional window-frame tint carry it. Settings rows show "Protegido · senha, celular" built from status().protection, and the selector shows "Bloqueado" or "Aberto — bloqueia ao fechar".
- A trusted surface for secrets: the identity box shows "Nulavio" with the route mark for shell@nulavio.net pages (privileged module). Later, a tab-modal chrome sheet for unlock so the password field cannot be imitated by web content.
- A recovery-code ceremony: a numbered 7-group grid, screen-reader reading group by group, "Salvar em arquivo" and "Imprimir", a leave guard, and two groups typed back. In Settings, a "Métodos de desbloqueio" page (an extended phone.html) to replace the code, add a password or keyring, pair or remove phones, with a warning below two methods.
- SAS by compare-and-choose: the computer shows three 6-digit options and the user picks the one on the phone, so there is no "They match" button to click by habit.
- A Dia-like contextual permission sheet for agents. It shows the agent's stated task, what it wants and where, the profile and workspace chip, a risk tier and an expiry countdown. Deny is primary; Allow once is secondary; Allow for the agent's session sits behind a disclosure. A "why this was asked" disclosure maps the request to the autonomy preset.
- A Guard review dashboard: a summary of counts by severity, human titles with raw detail on demand, "Desfazer todas as críticas" (confirmed), focus moving to the next card, and a dated history of decisions that can be reopened from Settings.
- Lookalike comparison and control: hostnames side by side in mono with the difference highlighted. Continue says it will not warn again (or remembers for the session only). Settings › Senhas lists the confirmed pairs with remove actions.
- Download warning by severity: when flagged, Delete is the critical primary and the specific verdict is shown. When generic, "Manter sem abrir" or "Fechar" is primary, with Show in folder and Delete secondary. Optionally show a local SHA-256 next to the file to compare with the publisher (no network).


**Open questions**

- Captures of programmatically focused inputs (unlock-idle, create-1, phone-idle) show no focus ring, while buttons do (guard, lookalike, ai-request), even though the tests assert activeElement. When the unlock page is opened from the selector or routing via openTrustedLinkIn, is the content area really focused, or could a typed password land in the address bar? This needs a manual check on the installed build.
- Does the brand rule against Mozilla or third-party marks also cover nominative text such as "addons.mozilla.org", "assinatura da Mozilla", "Firefox" (the KeePassXC instruction) and "Safe Browsing" in Shell copy? These look necessary for honesty, but the rule should be stated explicitly.
- Should the lookalike "Continue" choice be remembered permanently, per session, or until the user removes it in Settings?
- Should Full control keep including the "debugging" capability (raw automation), or should raw automation always need a separate opt-in with its own confirmation?
- Is copying the recovery code to the clipboard acceptable under ADR 0006, which bans the DEK from the clipboard but does not mention the recovery code? Or should only save-to-file and print be offered?
- Should Guard's "Manter" for a new root CA or PKCS#11 module need a confirmation, given that these findings allow interception of encrypted traffic?


## Assistant and AI Bridge (AI)

The assistant's main job is to answer a question about the page the user is on, and to make clear what was sent to which provider. That does not work in the shipped Track B build. The side panel cannot find the current page because experiments/ai/parent.js:20 uses `ownerGlobal`, which Firefox 158 no longer has (it is now `documentGlobal`). So "Incluir esta página" and "Resumir esta página" are always disabled, even on http(s) pages. Observed in 2 captures and confirmed by a probe. The tests do not catch it because they call the module with a chrome window or open the panel as a tab.

The rest of the model contract was read from code:
- Answers are not streamed. The backend makes one blocking urllib call, and callTool reads one JSON reply on stdout.
- Each question is sent alone: the backend keeps no conversation history.
- Tasks are an 8-step loop inside a single 600 s call. There is no cancel and no progress. Anthropic answers are capped at 1024 tokens and page text at 60,000 characters, and neither cut is flagged.

The model-state matrix has big gaps:
- No stop or cancel.
- No streaming state.
- No step progress or "waiting for your approval" state. Approvals open a separate tab, probably in the background because browser.tabs.loadInBackground is true by default.
- No partial or truncated state. A finished task shows a "✓" before "Trabalhando…" (Observed).
- Rate limits (429) and auth errors show the same "confira a chave e o modelo" message.
- A timed-out task says "Nada foi alterado", even though the agent may already have acted.

Consent is sticky. The include checkbox stays ticked after Send and when the user switches tabs, and the page text is read from whichever tab is selected at Send. This only becomes reachable once the window bug is fixed, so the two fixes must ship together.

Pause, revoke, the emergency stop and agent activity exist only in Settings. The user's own windows show nothing while an agent works. In the AI Workspace window, the only marks are a dismissible bar and Gecko's remote-control stripes.

Mozilla's chatbot sends selection and page text to third-party sites outside Nulavio's per-profile consent, recipient line and audit. It is reachable from:
- a page context-menu item (`context-ask-chat`, Observed);
- a selection shortcut (Observed);
- its sidebar, whose onboarding has an unreadable white heading, blank provider names and third-party logos.

The good parts are worth keeping:
- The API key lives only in the system keyring.
- Each profile decides whether it may send anything.
- Page text comes from the engine's extractor and is marked untrusted.
- Answers are plain text.
- The recipient host and model are named.
- The assistant's own agent starts at Restricted and cannot use raw automation.
- Deny is focused on the permission request.
- There is no sparkle or purple in Nulavio's own AI UI.

The Dia-like proposal below keeps to ADR 0007. Everything in it works with today's WebExtension, Shell and pref APIs, or with a named small change in the launcher and Shell. None of it needs an engine patch. The few items that would need one (an inline address-bar answer row, real citations) are marked as future.


### AI-01 · blocker · cost S — Assistant side panel (sidebar_action) → nulavioAI.assistantPage / assistantAsk

- **Issue:** The side panel never finds 'this page'. windowOf() reads context.xulBrowser.ownerGlobal, which does not exist in Firefox 158 (renamed documentGlobal). So assistantPage() always returns null: 'Incluir esta página' is disabled with the label 'Não há página web nesta aba para incluir.' on every http(s) page, 'Resumir esta página' is disabled, and assistantAsk(…, true) would fail with no-page.
- **Impact:** The assistant's main value event (asking about the page the user is on) is unavailable in the shipped build. The panel tells the user something false about their tab.
- **Fix:** In experiments/ai/parent.js use `context.xulBrowser?.documentGlobal?.browsingContext?.topChromeWindow` (or the context's own appWindow/currentWindow). Add an integration test that opens the real sidebar (SidebarController.show('shell_nulavio_net-sidebar-action')) on an http fixture and checks that the include label names the page title. Ship together with AI-02 and AI-15: this fix makes those behaviours reachable.
- **Mechanism:** Engine API rename (Node.ownerGlobal → documentGlobal) in Gecko 158; the optional chaining turns the TypeError into a silent null.
- **Evidence:** Observed: audit-captures/ai-assistant/probe3.json (sidebar browser: ownerGlobalType 'undefined'; documentGlobal → browser.xhtml whose selected tab is http://127.0.0.1:…/page/Artigo). Observed: audit-captures/before/window/assistant-sidebar-empty-light.png and audit-captures/ai-assistant/sidebar-ready-light.png (http page plus the 'no page' label); probe-facts.json probe2 'label=Não há página web… disabled=true'. Code: browser/shell/experiments/ai/parent.js:20,52-53 (same bytes in the installed omni.ja). Engine: dom/webidl/Node.webidl:116-117 (documentGlobal), toolkit/components/extensions/ExtensionParent.sys.mjs:838 (the engine itself uses xulBrowser.documentGlobal). Why tests miss it: tests/integration/test_assistant_ui.py:111-114 call the module with the chrome `window`; test_03 (121-131) opens panel.html as a tab, not in the sidebar.


### AI-02 · major · cost S — Assistant composer: 'Incluir esta página' checkbox and 'Resumir esta página'

- **Issue:** Consent to include the page is sticky, not per message. (a) After Send or Summarize the checkbox stays ticked, so every follow-up resends the page text. (b) It stays ticked across tab switches and navigations: showPage() only unticks when there is no page. The text is extracted at Send time from whichever tab is selected then, so consent given for page A carries over to page B. (The label does update to B's title, so this is not hidden, but the choice is not re-made.)
- **Impact:** Page text can go to the provider for messages and pages the user did not explicitly choose. This weakens ADR 0007's 'page text only when the user includes it explicitly' and the threat-model control AI-T33.
- **Fix:** Replace the checkbox with a context chip tied to {tabId, URL, title}, added only by an explicit action. Clear chips after each Send by default (an optional per-chip 'manter nas próximas perguntas' pin, off by default). Mark a chip stale if its tab navigates. Small module change: assistantAsk(question, {tabId, url}) resolves that tab through the extension's tabManager, extracts it, and refuses with 'page-changed' if the URL no longer matches.
- **Mechanism:** UI state tied to the panel rather than to a specific tab and message; extraction tied to the selected tab at Send time.
- **Evidence:** Code (Observed): browser/shell/assistant/panel.js:60-70 (only unticks when !page), 105-129 (send() never resets #include-page), 131-136, 143-147 (Summarize ticks it and leaves it ticked), 152-153 (re-label on tab change, state kept). browser/shell/modules/NulavioAI.sys.mjs:237-247 (extracts from win.gBrowser.selectedBrowser at Send). Inferred at runtime: not reachable today because of AI-01. Specified: docs/adr/0007-ai-bridge.md:84; docs/security/threat-model-ai.md AI-T33.


### AI-03 · major · cost M — Assistant\: Ask (180 s) and Task (600 s) requests

- **Issue:** There is no stop or cancel. The only feedback is a disabled Send button and a static status line. When the 600 s timer kills the tools process, the user sees err_helper_failed: 'As ferramentas do Nulavio não responderam. Nada foi alterado.' That is false for a task that may already have opened tabs, typed or submitted in the AI Workspace. Cancellation is not told apart from rollback.
- **Impact:** The user cannot stop a slow or wrong answer, or an agent run, from where they started it. After a timeout they are told nothing happened when it might have.
- **Fix:** Named backend change: give each assistant request a handle, add nulavioAI.assistantCancel(handle) → proc.kill(), and add a SIGTERM handler in `nulavio ai assistant` that sets the Bridge cancel Event, closes the bridge and returns {cancelled:true, steps:[…]}. UI: Send becomes 'Parar' while running. A cancelled Ask says 'Cancelado; nada foi enviado depois disso'. A cancelled or timed-out Task lists the steps already done and links to Atividade. Never use 'Nada foi alterado' for tasks.
- **Mechanism:** One blocking JSON request/response over a subprocess, with no handle exposed to the page.
- **Evidence:** Code (Observed): browser/shell/modules/NulavioAI.sys.mjs:248 (180000 ms), 253 (600000 ms); browser/shell/modules/NulavioTools.sys.mjs:35-36 (kill on timer), 50-55 (unparseable output → helper-failed); _locales/pt_BR err_helper_failed; panel.js:110,127 (only Send is disabled; Summarize and the mode radios stay live). Backend hook already exists: launcher/nulavio_launcher/ai/tools.py:273 Bridge.call(..., cancel: threading.Event).


### AI-04 · major · cost M — Assistant task mode ('Fazer uma tarefa') and the agent permission request

- **Issue:** The task run is opaque. (1) For up to 10 minutes the panel shows only '✓ Trabalhando com <host> no AI Workspace…', with the completion check mark from .status[data-level=ok]. (2) There are no per-step progress events. (3) There is no 'waiting for you' state: Restricted asks before click and type, but the request opens as a tab via openTrustedLinkIn(url, 'tab') without inBackground, so with browser.tabs.loadInBackground=true (engine default, not overridden) it probably opens behind the current tab. The window has already claimed the request (.seen), so the KDE fallback does not fire and the request silently denies after 120 s. (4) Steps appear only at the end, as raw tool ids ('tab_new — não permitido ou falhou'). (5) Hitting the 8-step limit returns answer '' and the panel says 'O modelo não devolveu texto.'
- **Impact:** Users cannot tell progress from a hang, miss approvals or have them denied silently, cannot see what the agent did in human words, and are misled about why a task ended.
- **Fix:** (a) Today: pass {inBackground:false} in #open; show a state-specific status without ✓ until done; map steps to localised tool titles plus the target origin; show 'Parou após 8 passos sem concluir' for stopped:'step-limit'; show the request's expiry time on request.html. (b) Named backend change: `nulavio ai assistant` streams NDJSON events (step started/ok/denied, approval-pending with the request id, done). The panel then shows a run timeline and an inline approval card built on the existing ai.request(id)/ai.answer(id, …), with Deny focused. This is safe because the panel only works in the user's windows: #assistant refuses in an AI Workspace.
- **Mechanism:** No progress channel between the tools process and the page; approval UI decoupled from the run that asked for it.
- **Evidence:** Observed: audit-captures/ai-assistant/sidebar-task-running-dark.png ('✓ Trabalhando com 127.0.0.1 no AI Workspace…'); browser/shell/shared/shell.css:116; panel.js:111 (announce at level 'ok'), 114-121. Code: NulavioAI.sys.mjs:179-187 (#open), launcher/nulavio_launcher/ai/registry.py:369-398 (4 s notice, 120 s timeout, .seen claim); engine toolkit/modules/BrowserUtils.sys.mjs:681-695 and modules/libpref/init/StaticPrefList.yaml:2156-2158 (loadInBackground true). assistant.py:278-303 (step limit returns answer ''), tools.py:121-167 (human tool titles exist, English only). Background-tab behaviour is Inferred; tests/integration/test_ai_ui.py:165-166 switches to the tab explicitly, so it would not catch it.


### AI-05 · major · cost M — User's own browser windows (toolbar/chrome) and Settings → IA e automação

- **Issue:** Agent activity, pause, revoke and the emergency stop exist only inside Settings. The emergency stop is a switch in the first card. Nothing in the user's windows shows that an external agent or the assistant is working right now, waiting for approval, or using raw automation. The architecture doc says this is by design ('Pause, revoke and stop live in the user's own Settings').
- **Impact:** The most important safety controls take several steps to reach during an incident. An active agent session is invisible unless the user opens Settings ('Conectado agora') or happens to see the workspace window.
- **Fix:** A privileged Shell widget (CustomizableUI from NulavioAI.sys.mjs, no engine patch), shown in user windows only and never in an AI Workspace. It appears while any agent session is active or an assistant task runs. It uses an automation pattern plus text (never colour alone), lists agents with state (trabalhando / aguardando você / automação bruta) and offers Pausar, Revogar (confirmed), 'Parar todos os agentes' (fail-safe, no confirm) and 'Ver atividade'. Add a Shell `commands` shortcut for the emergency stop. Named backend change: a cheap session status the module can read every 1.5 s (for example ai/sessions/<agent>.json written by the bridge on connect and disconnect), because overview() starts the tools process.
- **Mechanism:** Controls placed where the agent cannot click them (correct), but only on one deep page.
- **Evidence:** Code (Observed): browser/shell/settings/ai.js:427-454 (the only place that calls setStopped/pause/revoke); browser/shell/background.js:121-130 (the user window only watches for requests). Specified: docs/architecture/ai-bridge.md 'Activity indicator' paragraph. Observed: tests/artifacts/ai-ui/agent-permissions-dark.png (stop switch inside a card).


### AI-06 · major · cost M — AI Workspace window (and a user profile opened for an agent)

- **Issue:** The only Nulavio mark is a dismissible info notification bar with a violet info icon. Once it is closed, the window looks like a user window except for Gecko's own remote-control stripes and robot icon, which come from the engine. The theme, title format and toolbar are the same. Closing the bar does not stop the agent.
- **Impact:** The user can confuse a window an agent drives with their own, and type or approve things there. This breaks 'AI Workspace window … always visible and distinguishable'.
- **Fix:** Pass dismissable=false to markWorkspace. Add a boolean pref nulavio.ai.workspace.mark=true to WORKSPACE_PREFS and a Horizon `@media -moz-pref("nulavio.ai.workspace.mark")` block that draws an automation band: a hatched token that is not in the identity palette, not private-window purple and not violet, with the label 'AI Workspace · <agente>'. Prefix the window title from the privileged module. Ship a desktop entry and icon for WM class nulavio-ai-workspace so Plasma's taskbar tells it apart (verify on real Plasma). Keep Gecko's remote-control marks untouched.
- **Mechanism:** Workspace identity relies on one dismissible notification plus upstream automation marks.
- **Evidence:** Observed: audit-captures/before/window/ai-workspace-dark.png (bar with ×; approximated by setting nulavio.ai.workspace on a normal session, audit-captures/scripts/capture_before.py:538). Code: NulavioAI.sys.mjs:256-271 (appendNotification with the default dismissable=true; engine toolkit/content/widgets/notificationbox.js:145-151 accepts dismissable=false); launcher/nulavio_launcher/ai/workspace.py:32-43 (no visual pref), 104-108 (--class nulavio-ai-workspace); browser/branding/nulavio/content/theme/horizon.css:26 (keeps the remote-control indicator, correctly).


### AI-07 · major · cost S — Mozilla genai chatbot (browser.ml.chat.*) coexisting with the Nulavio Assistant

- **Issue:** Building on the already-established sidebar conflict: Mozilla's chatbot also owns the context entry points a Dia-like assistant needs. It adds a page context-menu item (context-ask-chat) and a selection shortcut, and browser.ml.chat.menu/shortcuts/page are all true because Nulavio overrides none of them. It sends the selection or page to a third-party website in the sidebar, outside the Nulavio per-profile allowance, the recipient line and the audit. Its onboarding fails basic quality: white heading on a near-white card, blank provider names, third-party logos (Anthropic, Gemini, Mistral), and a Mozilla-blue CTA inside Track B.
- **Impact:** There are two AI paths with different privacy rules. The one that bypasses Nulavio's consent model is the one closest to hand (right-click, selection). It also brings third-party marks and an unreadable screen into the product.
- **Fix:** Prefs only, in browser/config/prefs/baseline.js: browser.ml.chat.enabled=false, browser.ml.chat.menu=false, browser.ml.chat.shortcuts=false, browser.ml.chat.page=false; keep 'aichat' out of the default sidebar tools. Then give those entry points to the Nulavio Assistant through the Shell `menus` API (see proposals). List every AI feature in the build (assistant, Link Preview key points, smart tab groups) with its data path on Settings → IA e automação.
- **Mechanism:** Upstream feature left at its defaults; engine UI and third-party provider list shipped in Track B.
- **Evidence:** Observed: audit-captures/ai-assistant/probe3.json (context-ask-chat present; shortcuts element present; prefs at engine defaults with no user value); facts.json (sidebar.main.tools includes 'aichat' above shell@nulavio.net). Observed: audit-captures/before/window/sidebar-viewGenaiChatSidebar-light.png. Engine defaults: browser/app/profile/firefox.js:2338-2357. Repo: browser/config/prefs/baseline.js and theme.js contain no browser.ml.* lines.


### AI-08 · minor · cost S — Assistant answers (partial/truncated states)

- **Issue:** Cut-off output and context are shown as if complete. Anthropic answers are capped at max_tokens 1024, and stop_reason and finish_reason are ignored. Page text is cut at 60,000 characters without saying so; the count is reported only after sending ('60000 caracteres desta página foram enviados').
- **Impact:** Users trust summaries that stopped mid-answer, or that were based on the first part of a long page only.
- **Fix:** Small backend change: return truncated:true when stop_reason='max_tokens' or finish_reason='length', and pageTruncated:true. UI: 'Resposta cortada pelo limite do provedor' with 'Continuar' (one follow-up turn), and on the page chip, before sending: 'Página longa: vão os primeiros 60.000 caracteres'.
- **Mechanism:** Provider stop reasons and the local limit are not surfaced.
- **Evidence:** Code (Observed): launcher/nulavio_launcher/ai/assistant.py:39 (MAX_PAGE_CHARS), 195 (max_tokens 1024), 199-204 and 209-219 (stop reasons not read), 222-224 and 245 (silent cut); panel.js:122 (post-hoc count only).


### AI-09 · minor · cost S — Assistant error states

- **Issue:** Every HTTP error, including 429 rate limit, 401/403, 404 unknown model and 5xx, becomes 'provider-refused': 'O provedor recusou o pedido (confira a chave e o modelo).' A timeout becomes 'Não foi possível falar com o provedor.' The backend's detail ('HTTP 429') is dropped by callTool. There is no retry timing.
- **Impact:** Rate-limited or overloaded users are sent to check their key. A slow local model looks unreachable.
- **Fix:** Distinct codes and strings in en and pt_BR: provider-rate-limited (with Retry-After when the provider sends it), provider-auth, provider-model-missing, provider-timeout, provider-error. Keep the question and chips in the composer (the text already survives) and offer 'Tentar de novo' after the stated time. No automatic retries.
- **Mechanism:** Error taxonomy collapsed into two codes; detail dropped at the IPC boundary.
- **Evidence:** Code (Observed): assistant.py:165-174; launcher/nulavio_launcher/ai/cli.py:362-363 (detail returned); NulavioTools.sys.mjs:56-58 (only answer.error kept); _locales/*/messages.json err_provider_refused / err_provider_unreachable. Probe note: a 429 was scripted in audit-captures/ai-assistant/observe.py but never reached the provider because of AI-01 (facts.json requests = 1); the mapping is read from code.


### AI-10 · minor · cost S — Emergency stop, Pause and Revoke vs the assistant

- **Issue:** The scope of stop, pause and revoke differs from what their labels suggest. ask() checks only provider and profile allowance, so after 'Revogar' or 'Pausar' on the 'Nulavio Assistant' agent row, or with the emergency stop on ('Bloqueia todos os agentes de uma vez'), the panel still sends questions and page text. With the stop on, run_task keeps calling the provider after its tool calls are denied (up to 8 model turns).
- **Impact:** A user who reaches for the stop or revoke to shut AI off still has an assistant that sends content, and a stopped task keeps spending provider calls.
- **Fix:** Decide and state it. Recommended: the emergency stop and the assistant agent's pause or revoke also block Ask, with the panel showing 'Assistente pausado / parada de emergência ativa' and a link to resume. run_task breaks before the next model turn when stopped, revoked or paused. Otherwise, say in aiStopHint that questions still work.
- **Mechanism:** Policy Decision Point covers tool calls only; the Ask path bypasses the registry state.
- **Evidence:** Code (Observed): assistant.py:227-250 (no revoked/paused/stopped check in ask), 278-303 (loop does not check registry.stopped()); tests/unit/test_assistant.py:171-184 (expects a second model turn while stopped); locale aiStopHint.


### AI-11 · minor · cost S — Settings → IA e automação (assistant-related rows)

- **Issue:** (a) The assistant's agent row badge falls back to the raw key 'aiClient_nulavio_assistant': the client is 'nulavio-assistant', there is no locale key, and t() returns the key. (b) After saving the assistant, the agents list is not refreshed and still says 'Nenhum agente conectado ainda.' (c) Activity rows show raw tool ids such as 'assistant.ask' and 'tab_new'.
- **Impact:** Internal identifiers in the UI, and a stale list right after the user created an agent.
- **Fix:** Add aiClient_nulavio_assistant in en and pt_BR; call renderAgents() after assistantConfigure; map tool ids to localised titles in Activity and in the panel's steps.
- **Mechanism:** Missing i18n key with key fallback; partial re-render.
- **Evidence:** (a) Inferred from code: launcher/nulavio_launcher/ai/registry.py:30, browser/shell/settings/ai.js:148, browser/shell/lib/i18n.js:5; _locales/pt_BR has only aiClient_claude_code/codex/other (lines 466-468). (b) Observed: tests/artifacts/assistant/settings-light.png; code ai.js:410-414 (renderAssistant only). (c) Code: ai.js:367.


### AI-12 · minor · cost S — Assistant panel accessibility and states

- **Issue:** (a) In-progress status shows '✓' (generated content, likely in the accessible name). (b) The answer is written into a hidden aria-live container that is then unhidden, and the status is cleared with announce('') when no page went. A screen reader may announce nothing when the answer arrives (Inferred). (c) No Ctrl+Enter to send. (d) The disabled 'Resumir esta página' quiet button is nearly invisible (opacity 0.45 on secondary text) in the tab capture and not visible in the sidebar captures. (e) The title appears twice: the sidebar header 'Assistente Nulavio' plus an h1 'ASSISTENTE NULAVIO', which uses about 50 px of a 340 px panel.
- **Impact:** Screen-reader and keyboard users get unclear completion signals; low-vision users miss controls; space is wasted in a narrow panel.
- **Fix:** Use text status per state with no glyph until complete. One polite announcement at start ('Enviado para <host>') and one at end ('Resposta pronta'). Keep the answer region non-live, reachable by a heading. Add Ctrl+Enter. Hide unavailable quick actions and explain why, rather than leaving them faint. Visually hide the inner h1. Test with Orca, 200% zoom, forced colours and prefers-reduced-motion.
- **Mechanism:** Generic status component reused for an async AI state; live region toggled through hidden.
- **Evidence:** Observed: tests/artifacts/assistant/panel-light.png; audit-captures/ai-assistant/sidebar-ready-light.png and crop-send-row.png; sidebar width 340 px (facts.json). Code: browser/shell/assistant/panel.html:15,39-40; panel.js:114-115,122; shell.css:116,147; docs/brand/tokens.json:684-686.


### AI-13 · minor · cost S — Assistant answer: provenance and history

- **Issue:** Answers carry no provenance. The only record of what was sent ('N caracteres desta página foram enviados para <host>') is a transient status line, overwritten by the next action. The answer card has no 'based on <page>', model or time. Each question is sent on its own; the previous answer is hidden on the next Send. There is no copy or retry affordance.
- **Impact:** Users cannot check what an answer was based on or where the data went, which encourages automation bias. Follow-ups lose context with no warning.
- **Fix:** Answer card footer: the page chip (title · origin) as a button that switches to that tab, characters sent, host, model and time; Copiar; 'Tentar de novo' (states that it re-reads the page). Return page {url, title} from the module (Shell-only change). Keep a session-only thread in panel memory, never persisted. Multi-turn context is a named backend change (a history parameter on ask) plus an explicit rule that earlier page text is not resent unless re-attached.
- **Mechanism:** Single-shot request with a status-line receipt.
- **Evidence:** Code (Observed): panel.js:106-109 (hides the previous answer), 122; assistant.py:243-244 (single user message); NulavioAI.sys.mjs:246 (url and title known but not returned to the page). Observed: audit-captures/ai-assistant/sidebar-answer-light.png and tests/artifacts/assistant/panel-light.png (answer box only).


### AI-14 · minor · cost S — Task mode disclosure

- **Issue:** The task note explains permissions but not the data flow. Text the assistant reads in its AI Workspace (page_read and page_snapshot results, up to 20,000 characters per tool result) goes to the provider, and the task cannot see the user's current page. The page option is simply hidden in task mode.
- **Impact:** Users may expect 'resuma esta página' to work as a task, or may not realise that what the agent reads is sent to the provider.
- **Fix:** Copy: 'O que o assistente ler no AI Workspace vai para <host>; suas abas não'. Optional explicit chip 'Levar o endereço desta página' (URL only, shown in full with an option to drop query parameters). Small backend change: run_task(task, url) adds it as user-supplied context.
- **Mechanism:** Disclosure written from the permission angle, not the data angle.
- **Evidence:** Code (Observed): _locales/pt_BR assistantTaskNote; panel.js:76-84; assistant.py:258-261 (tool text to the model, screenshots excluded), 294-302.


### AI-15 · minor · cost S — Assistant in private windows

- **Issue:** The panel works in private windows with no private-specific cue (Shell incognito 'spanning'). assistantPage() accepts any http(s) tab without checking private browsing, so once AI-01 is fixed, private-tab text could go to the provider under the normal profile's allowance.
- **Impact:** Private content could leave the device with the same one-tick consent as a normal tab.
- **Fix:** In the module, refuse page and selection inclusion when PrivateBrowsingUtils.isWindowPrivate(win), and show the reason in the panel. Product decision on whether Ask works at all in private windows; other auditors proposed 'never available in private windows'.
- **Mechanism:** Page eligibility checks only the URL scheme.
- **Evidence:** Observed: audit-captures/before/window/private-window-assistant-sidebar-light.png. Code: browser/shell/manifest.json 'incognito': 'spanning'; NulavioAI.sys.mjs:230-234. Inferred: reachable after AI-01 is fixed.


### AI-16 · polish · cost S — Assistant identity, terminology and design-system coverage

- **Issue:** The sidebar launcher uses the Nulavio brand symbol as the assistant icon, so the brand mark stands for one AI feature. 'AI Workspace' stays in English inside pt-BR sentences. The assistant panel, context chips and automation states are absent from docs/design/component-inventory.md and design-system.md.
- **Impact:** Brand and feature are confused in the rail. The pt-BR UI mixes languages. There is no shared spec for AI states, so they will drift.
- **Fix:** A dedicated assistant glyph (not a sparkle, not the brand N). A pt-BR term decision for 'AI Workspace' (keep it as a named product term with a one-time explanation, or translate). Add 'Assistant panel', 'Context chip', 'Run timeline', 'Approval card', 'Automation band' and their state tables to the component inventory and design system.
- **Mechanism:** Feature shipped before its design-system entry.
- **Evidence:** Code: browser/shell/manifest.json sidebar_action.default_icon shared/nulavio-symbol.svg; locales aiWorkspaceBar, assistantTaskNote, assistantWorking. Observed: the 'N' in the sidebar rail in audit-captures/before/window/assistant-sidebar-empty-light.png. Docs: no assistant entries in docs/design/*.md (grep).


**Proposals**

- VALUE EVENT and evidence: the user gets a correct answer about the page or selection they chose, and can see what was sent, to which host and model, and what the answer was based on. A task's value event is that it finished in the AI Workspace, with every step visible and nothing done outside its grants. There is no telemetry by policy, so evidence comes from local integration tests plus moderated usability sessions (task success, whether users can say what was sent and where, time to stop an agent). Guardrail: no content leaves without a Send on the message it belongs to.
- ENTRY POINTS (Shell only, today's APIs): (1) Side panel plus a keyboard shortcut via manifest commands._execute_sidebar_action; pick a chord confirmed free in about:keyboard (Alt+Shift+P is already the profile selector). (2) Page context menu 'Perguntar ao Assistente sobre esta página' and selection menu 'Perguntar sobre a seleção' through the `menus` API (permission already granted). browser.menus.onClicked counts as user input, so it can call browser.sidebarAction.open() and hand a pending chip to the panel with runtime messaging. Nothing is sent and the question is not prefilled-and-sent. These items are hidden in private windows and AI Workspaces. selectionText carries up to 16,384 characters (toolkit/modules/SelectionUtils.sys.mjs:143). (3) Address bar: Firefox 158 has no extension urlbar-results API (only browser/components/extensions/schemas/omnibox.json), so the only option today is an `omnibox` keyword (for example 'ia <pergunta>'). It only opens the panel with the question in the composer, never sends, and the keyword-mode text must be verified not to reach search suggestions. An inline urlbar 'ask' row or quick action would need an engine patch: FUTURE. Other auditors already established that typed text must never be routed to AI automatically.
- COMPOSER WITH CONTEXT CHIPS: a chip is added only by an explicit click ('+ Esta página', 'Usar seleção', or a context-menu entry). Each chip shows its kind, title, origin and approximate characters, using local extraction for the count (that never leaves the device). Each is removable with an × whose accessible name is 'Remover <título> do envio', is bound to {tabId, URL}, goes stale if its tab navigates, and is cleared after Send by default. Directly above Send, a line linked to the button with aria-describedby: 'Vai para api.openai.com · gpt-…: sua pergunta + 1 página (≈12.400 caracteres)', or 'Só sua pergunta'. The panel header shows the current profile's colour and icon (via nulavioProfiles.list) plus protected and private markers. Context chips need their own outlined 'context token' component so they are never confused with the existing profile identity .chip. Quick actions ('Resumir', 'Explicar a seleção') may send in one click only from inside the panel when the chip and recipient line are already visible. From the context menu they prefill only. Backend change for selection (small, named): assistant.ask accepts a `selection` {url, title, text} block marked untrusted like the page block; NulavioAI.assistantAsk and schema.json gain the parameter.
- ANSWERS, TODAY (non-streaming, stated plainly in the spec): 'Aguardando <host>…' plus elapsed seconds (visual only, updated every 5 s, never a determinate bar) and a 'Cancelar' button (needs the small request-handle plus kill change from AI-03; cancelling an Ask has no side effects). The answer card is plain text, or a safe Markdown subset built with DOM nodes and no innerHTML (decision). Its provenance footer shows the page chip as a button to that tab, characters sent, host, model and time. Actions: Copiar; Editar (the question stays in the composer); Tentar de novo (says it re-reads the page). Flags for truncated answers and truncated pages (AI-08). A session-only thread lives in panel memory and is never written to disk.
- STREAMING (named backend change, size M, no engine patch): set `stream: true` on both provider kinds and parse SSE (OpenAI choices[].delta.content; Anthropic content_block_delta). `nulavio ai assistant` writes NDJSON lines ({type:'delta'|'step'|'approval'|'done'|'error'}) and flushes. NulavioTools gets callToolStream(), which reads proc.stdout.readString() incrementally (today it buffers everything, NulavioTools.sys.mjs:40-48). NulavioAI exposes the events through an experiment event (ExtensionCommon.EventManager) and assistantCancel(handle). UI: Send becomes 'Parar'. Stopping keeps the partial text, labelled 'Interrompida — resposta parcial'. The streaming region is not aria-live; one announcement at start and one at end. No typing animation or blinking caret, so prefers-reduced-motion needs nothing extra.
- TASKS AS AGENT RUNS: a run card in the panel ('Tarefa no AI Workspace · Assistente Nulavio · Restrito'). It holds a step timeline from the NDJSON events, with localised tool titles taken from tools.py titles, target origin and decision (permitido / negado: precisa de '<capacidade>' / aguardando você). It also holds an inline approval card that uses the existing ai.request(id)/ai.answer(id, once|session|deny), with Deny focused and the same 120 s expiry shown as a clock time. When the panel is closed, the request tab still opens, now in the foreground. Controls: 'Parar tarefa' (cancel this run), 'Pausar assistente' (registry pause), and a link to the emergency stop. The end state names its reason (concluída, parou no limite de 8 passos, cancelada, negada, tempo esgotado), lists the steps done, and never claims rollback. Disclosure line: 'O que o assistente ler no AI Workspace vai para <host>'. Optional chip 'Levar o endereço desta página' sends the URL only (small run_task change).
- AGENT ACTIVITY IN THE CHROME (user windows only): a privileged CustomizableUI widget created by NulavioAI.sys.mjs, so Shell code and no engine patch. It appears while any agent session or assistant task is active and shows a hatched automation token plus a count and text, never colour alone. Its panel lists each agent with client, level and state (trabalhando, aguardando você, automação bruta: nada é verificado), with Pausar, Revogar (confirm), 'Parar todos os agentes' (no confirm: fail-safe; resuming happens in Settings) and 'Ver atividade'. A Shell commands shortcut also triggers the emergency stop. The widget is never created where workspaceAgent() is set. Needs the small session-status file described in AI-05.
- TELLING AI WORKSPACE WINDOWS APART: a non-dismissible bar (appendNotification 5th argument false) naming the agent and its level. A pref-gated Horizon band (nulavio.ai.workspace.mark=true in WORKSPACE_PREFS → `@media -moz-pref(...)` in horizon.css) using a dedicated automation token with a hatch pattern, kept out of the identity palette (mint, sky, violet, rose, sand, slate), away from private purple, and including its forced-colours and prefers-contrast variants. A window title prefix 'AI Workspace · <agente>'. A separate taskbar identity through a desktop entry for WM class nulavio-ai-workspace (packaging). Gecko's remote-control stripes and robot stay as they are. Nulavio's own pages in a workspace keep refusing approvals and the assistant (already implemented).
- MOZILLA CHATBOT CONFLICT: turn it off with prefs in browser/config/prefs/baseline.js (browser.ml.chat.enabled=false, plus menu, shortcuts and page set to false as a safeguard), keep 'aichat' out of the default sidebar tools, and give its entry points (context menu, selection) to the Nulavio Assistant. On the 'IA e automação' Settings page, add a short 'Recursos de IA neste navegador' list showing, for each feature, where its data goes: Assistente → host chosen by you; Link Preview key points and smart tab groups → on this device (they download a model on first use: open question).
- MODEL-STATE MATRIX for the spec and the tests: blocked (not configured / profile not allowed / AI Workspace / private window / assistant paused or revoked / emergency stop) → ready → composing (chips, recipient line) → sending → waiting (non-streaming, elapsed time, Cancelar) | streaming (Parar) → tool activity (step timeline) → awaiting approval (inline card, expiry time) → partial (answer truncated, page truncated, step limit, cancelled with steps done) → complete (provenance, Copiar, Tentar de novo) → failed (unreachable, timeout, auth, model missing, rate limited with Retry-After, tools missing). A provider refusal is shown as the model's text, with no invented policy detail. The question and chips always survive failures.
- VISUAL FINGERPRINT: the panel stays calm and Horizon-native: neutral surfaces, mint accent only for the primary action, the answer on bg-sunken, and a monospace origin in chips. No sparkle, no purple or blue glow, no glass. Automation is the one deliberate differentiator: a hatched band and token used the same way in the chrome widget, the workspace band and the run card. Give the assistant its own glyph instead of the brand N.
- TESTS TO ADD before redesign work lands: the real sidebar includes a page (catches AI-01); a chip is cleared after Send and goes stale after a tab switch or navigation; a private window refuses chips; cancel kills the request and reports steps; the truncated flags; the approval tab opens in the foreground; the workspace bar cannot be dismissed; the chrome widget never appears in an AI Workspace; en and pt_BR keys stay identical.


**Open questions**

- Should the emergency stop and the assistant agent's pause or revoke also block Ask (questions and page text), so the stop means 'stop all AI'? Recommended: yes (AI-10).
- Private windows: turn the assistant off entirely, or allow Ask without page and selection chips? Other auditors lean to 'never in private windows'.
- Follow-up turns: should earlier questions and answers (text only) go to the provider as history? If so, the recipient line must say so, and earlier page text should never be resent unless the chip is re-attached.
- Mozilla's Link Preview AI key points and smart tab groups run on-device but download models from Mozilla's servers on first use. Keep them, turn them off, or list them in Settings? Product decision outside the assistant.
- Which keyboard chord should open the panel, and which should trigger the emergency stop? Both must be checked free against about:keyboard in 158.
- Keep 'AI Workspace' as an English product term in pt-BR, or translate it?
- Render a safe Markdown subset in answers, or keep plain text only?
- Answer approvals inline in the panel as well as on the request tab? The panel only works in user windows, so it is as safe as the tab against AI-T29; AI-T28 (same-user process) applies in both.
- Plasma taskbar identity for WM class nulavio-ai-workspace needs checking on a real Plasma session; the capture used here approximated the workspace by setting the pref on a normal session.


## Design system, accessibility, tests (DS)

The design system has one source of truth. docs/brand/tokens.json produces three generated files, CI fails when any of them is stale (build_tokens.py --check), and all 86 declared contrast pairs pass. Horizon (horizon.css) is cheap to carry: it sits behind a pref, uses Mozilla's last brand layer, steps aside for lwtheme, prefers-contrast and forced-colors, and a static test guards it. Rendered checks in test_horizon.py cover contrast, densities, the route mark, reduced motion and high contrast. The richer system the redesign needs does not exist yet. There are no translucency, z-index, scrim, selection, page-density, component or typography-role tokens, and no reserved security-state cues. Elevation uses one navy shadow colour in both themes, and only one easing is defined. Shell CSS reinvents the type scale with 12 raw rem values, two of them off-scale. The start-page stylesheet doubles as the Shell's base.css, and page h1s use six different classes. A few component states are broken or missing. Selected template buttons look the same as unselected ones. The light critical download callout loses its red because criticalText exists only in dark. Native radios show Firefox blue #0060DF. aria-invalid is never used. Shell pages ignore an OS high-contrast setting (no prefers-contrast handling), and on Linux, content never gets forced colours by default. prefers-reduced-transparency is handled nowhere. In Gecko 158 it is not even parsed in Shell (moz-extension) pages without a pref, and on GTK it only mirrors high contrast. The biggest process risk: every Track B rendered test skips in CI, because CI runs distribution Firefox. Beyond that, test_07 cannot catch a compact or auto-hide layout that pushes security indicators off-screen. pngdiff pins no UI, docs counts and screenshots have drifted, and the perf script has no frame-time metric to measure backdrop-filter cost. i18n parity is good: 771/771 keys with matching placeholders, enforced by a test.


### DS-01 · major · cost L — CI / Track B rendered tests (tests/integration/test_horizon.py, Shell UI integration tests)

- **Issue:** The rendered visual and a11y guards never run in CI. The integration matrix uses distribution Firefox: Fedora RPM, plus Mozilla's APT build on Ubuntu. test_horizon skips unless appinfo.name == 'Nulavio', and 8 integration modules branch on the Nulavio build. As a result, rendered contrast, densities, route mark, security-UI parity and high-contrast tests only run on a developer machine.
- **Impact:** A window or Shell redesign can merge with broken contrast, hidden security indicators or broken densities, and CI stays green.
- **Fix:** Add a Track B integration job: a self-hosted runner, or the artifact from the ci/containers/fedora-build image. It should run test_horizon plus the Shell UI tests (vault_ui, ai_ui, routing, profiles, temporary, dns, guard, passwords, assistant). Until it exists, require an attached local run log for any PR that touches horizon.css, tokens.json, shell.css or startpage.css.
- **Mechanism:** docs/tests
- **Evidence:** Observed: .github/workflows/ci.yml:65-92 (fedora-itest/ubuntu-itest only); ci/containers/fedora-itest.Containerfile:6-7 (dnf install firefox); tests/integration/test_horizon.py:81-83 and 291-292 (SkipTest 'Horizon ships in the Nulavio build only'). Specified: docs/design/migration-plan.md:3 asks to 'run the full integration suite (both tracks)', which is a manual step.


### DS-02 · major · cost M — Tokens + Horizon + Shell pages: translucency foundation

- **Issue:** Nothing is in place for translucency. 1) No tokens for surface alpha, blur radius or solid fallback. 2) prefers-reduced-transparency is handled nowhere (0 grep hits in the repo). 3) In Gecko 158 that media feature is parsed only in UA/chrome sheets. In Shell moz-extension pages it is disabled unless layout.css.prefers-reduced-transparency.enabled (default false) is set, and that pref also exposes it to the web. 4) On GTK the value is true only when high contrast is on, because KDE/GNOME have no dedicated setting. 5) The tooling cannot check translucent surfaces: contrast.py accepts only #RRGGBB, and the rgb() helper in test_horizon drops alpha.
- **Impact:** Translucent chrome à la Opera Air or Zen would ship with no reduce-transparency path and no measurable contrast. Computed: a light surface at 80% alpha over a black page takes text.muted from 4.71:1 to 2.95:1 (3.34:1 over red), which fails WCAG 1.4.3.
- **Fix:** 1) Tokens: add surface.{chrome,panel,overlay}.{alpha,blur,solid}. Each translucent rule gets a solid fallback, plus a minimum alpha chosen so the worst-case composite keeps text ≥4.5:1 and boundaries ≥3:1. 2) Contrast: contrast.py composites each pair over white, black and a saturated backdrop. 3) A Settings toggle, pref nulavio.ui.reduceTransparency: in the chrome it sets ui.prefersReducedTransparency; in Shell pages the privileged module sets a root data attribute, so no web-exposed pref is needed. 4) Test: an integration test like test_12 that uses ui.prefersReducedTransparency=1 and asserts opaque surfaces.
- **Mechanism:** tokens
- **Evidence:** Observed (engine): servo/components/style/queries/feature_expression.rs:320-328; modules/libpref/init/StaticPrefList.yaml:11257-11260; widget/gtk/nsLookAndFeel.cpp:1132-1137; widget/nsXPLookAndFeel.cpp:147 (ui.prefersReducedTransparency override). Observed (repo): scripts/brand/contrast.py:29-32; tests/integration/test_horizon.py:62-70 ('alpha ignored'). Inferred: the composite ratios above, computed with contrast.ratio over white, black and red backdrops.


### DS-03 · major · cost M — Security-state guard tests (test_07, test_horizon_theme)

- **Issue:** Problem 1: test_07 compares only computed display and visibility of 5 address-bar indicators with Horizon on and off. It collects width but never asserts it, and it checks no opacity, position, on-screen or occlusion state. It also ignores the toolbar profile chip, the private-window indicator, the AI Workspace and Guard notification bars, the remote-control stripe and the downloads warning. So a Zen-like compact or auto-hide toolbar (transform, margin or opacity) would pass with the trust icon off-screen. Problem 2: test_horizon_theme bans display:none and visibility:hidden anywhere in horizon.css, and any #identity- selector. That blunt rule also blocks safe layout rules. Its colour guard checks only custom properties, so direct colour declarations outside the a11y guard pass unchecked, e.g. horizon.css:119.
- **Impact:** A redesign could hide or occlude security states while tests stay green, or be pushed to work around a blunt rule.
- **Fix:** Strengthen first, then refine. 1) Add a rendered 'security states visible' test that runs once per layout: horizontal tabs, vertical tabs, compact, auto-hide (revealed and hidden), private window, AI Workspace window and automation on. It asserts each indicator's bounding rect is inside the window, opacity is 1, elementFromPoint returns the indicator, and size matches within ±1 px. 2) Extend the colour guard to direct colour properties (background, color, border-color, box-shadow, backdrop-filter, fill) outside the guard, with an explicit allowlist. 3) Only after 1) exists, scope the display:none ban to rules near security selectors. 4) Add one capture variant that keeps remotecontrol.
- **Mechanism:** docs/tests
- **Evidence:** Observed: tests/integration/test_horizon.py:181-199 (w collected at :189, never asserted); tests/unit/test_horizon_theme.py:12-20, 45-53, 60-65; browser/branding/nulavio/content/theme/horizon.css:119; scripts/research/shell_screenshots.py:53-56 (removes the remotecontrol attribute in every capture). The Guard and AI Workspace bars are upstream notification boxes: browser/shell/modules/NulavioGuard.sys.mjs:695, NulavioAI.sys.mjs:265.


### DS-04 · major · cost S — Shell: critical download warning (warning/warning.html) and token generator

- **Issue:** status.criticalText exists only in the dark theme. .callout--critical uses it with no fallback, so in light the callout falls back to inherited text.primary. Text and icon lose the critical colour, and the icon is the same triangle used by the warning callout. In light, critical differs from warning only by tint hue and wording. Separately, build_chrome() emits a one-theme token as a plain value for both themes. The chrome then defines criticalText #EE8A8C in light as well, at 2.43:1 on white (latent; unused in horizon.css today).
- **Impact:** In light theme, the engine-flagged dangerous download looks like the ordinary 'can run programs' warning. This is a security warning whose severity is carried mostly by colour hue.
- **Fix:** 1) Add color.light.status.criticalText (red.700) and its contrast pairs. 2) Make build_tokens.py fail on a semantic token defined for one theme only. 3) Give critical a distinct icon and heading. 4) Add a unit test that every var(--nv-*) used in shell.css and startpage.css resolves in both the light and dark blocks.
- **Mechanism:** tokens
- **Evidence:** Observed: docs/brand/tokens.json:236 (criticalText under color.dark only); browser/startpage/tokens.css:113,150 (dark blocks only); browser/shell/shared/shell.css:88 (no fallback; compare :150, which has one); browser/shell/warning/warning.js:57-59; browser/shell/warning/warning.html:27-28 (one icon for both); scripts/brand/build_tokens.py:84-89; browser/branding/nulavio/content/theme/tokens.css:77.


### DS-05 · major · cost S — Shell: Vault create step 1 (profile type template buttons)

- **Issue:** Template buttons get aria-pressed, but shell.css has no [aria-pressed] or other ARIA-state selector. The pressed template looks the same as the others.
- **Impact:** Sighted users cannot see which template is applied, including 'Sites sensíveis', which clears data on shutdown. Screen readers get the state; visual users only see the pre-filled name.
- **Fix:** Add a .button[aria-pressed="true"] style: accent tint background, accent.default border and a ✓ glyph, plus a forced-colors Highlight outline. Add a 'Selected (toggle)' row to the states table in design-system.md, and an integration assertion that the computed styles differ.
- **Mechanism:** Shell page
- **Evidence:** Observed: browser/shell/vault/create.js:32-36 and :57 (a template is always pre-selected); shell.css has no aria-pressed selector (grep); tests/artifacts/vault-ui/create-1-profile-light.png (banking chosen, name 'Bancos', all 5 buttons identical).


### DS-06 · major · cost M — Shell pages under OS high contrast and forced colours

- **Issue:** Shell CSS has no prefers-contrast handling and only one forced-colors block (the switch). On Linux the default browser.display.document_color_use=1 means content documents, Shell moz-extension pages included, never get forced colours. prefers-contrast still matches when the OS high-contrast theme is on. So under KDE/GNOME high contrast the window steps aside to system colours, but Shell pages keep Nulavio tints: card borders at 1.59:1 and muted text at 4.7:1. When forced colours do apply (document_color_use=2), Gecko drops box-shadow and background-color. The selected-swatch ring, identity fills and hover overlays then disappear, so the colour picker shows no selection.
- **Impact:** High-contrast users get an inconsistent experience between the chrome and Nulavio pages, and the profile colour picker shows no visible selection under forced colours.
- **Fix:** 1) Generate a prefers-contrast:more override block in tokens.css: muted→secondary, border.subtle→border.control, tints→surface plus a 1 px control border, focus ring 3 px. 2) Under forced colours: set forced-color-adjust:none on .chip and .swatch__fill with a CanvasText ring, and give the checked swatch an outline in Highlight. 3) Tests: run the Shell pages with ui.useAccessibilityTheme=1 and with browser.display.document_color_use=2.
- **Mechanism:** tokens
- **Evidence:** Observed: browser/shell/shared/shell.css:243-245 (box-shadow ring), :347-350 (the only forced-colors block); horizon.css:60. Observed (engine): StaticPrefList.yaml:1581-1587; layout/style/PreferenceSheet.cpp:160-176; layout/style/nsMediaFeatures.cpp:323-343; servo/components/style/properties/longhands.toml (box-shadow and background-color are ignored_when_colors_disabled). Specified: docs/design/accessibility.md:14 says forced colours are 'not simulable'. That holds for the window, but Shell pages can be tested with document_color_use=2.


### DS-07 · major · cost M — Shell CSS architecture: typography, base layer, component shapes

- **Issue:** 1) make_shell copies startpage.css as shared/base.css, so every Shell page inherits the start page's body gradient and .page/.hero/.card. 2) Page h1s use six classes; .warning__headline (the download-warning component) is the h1 on 8 pages, and the assistant panel h1 uses .card__title. 3) The CSS uses 12 raw font sizes, including off-scale 15 px (0.9375rem ×7), 11 px and 40 px. Meanwhile the font.size xs/sm/md/lg/4xl tokens are unused. 4) Headings use px tokens while body text uses rem. 5) Button shapes are inconsistent: primary is a pill and other buttons use 10 px, while design-system.md says buttons use md 10. Fields use pill (search), 6 px (input) and 14 px (address bar). 6) Guard findings, which are security-critical, are titled in 13 px uppercase muted .card__title.
- **Impact:** There is no single place to restyle for the redesign, so every page needs edits. With a larger default font size, headings can end up smaller than body text (Inferred). Security-relevant headings get the least emphasis.
- **Fix:** 1) Define rem-based composite type roles in tokens: display, title, heading, body, label, caption, mono. 2) Split base.css (reset, roles, links, focus) from startpage.css. 3) Order the CSS with @layer tokens, base, components, pages. 4) Add component tokens (button, field, chip, card, callout), each with a documented shape rule. 5) Add an alert/finding card variant with a severity icon and a heading-level title.
- **Mechanism:** tokens
- **Evidence:** Observed: scripts/build/make_shell.py:25-26; grep of heading classes (8× h1.warning__headline; h1.card__title in assistant/panel.html:15); shell.css:38,41,47-51,71,198,210,261; startpage.css:58-62; docs/design/screenshots/guard-review-light.png; tests/artifacts/assistant/panel-dark.png. Specified: docs/design/design-system.md:43; docs/brand/ux-flows.md:11 ('rem units').


### DS-09 · major · cost S — Security-state identity vs profile identity (tokens)

- **Issue:** There are no reserved tokens or patterns for the security states that must always be distinguishable: private window, AI Workspace, raw automation, temporary profile, locked profile, Guard warning. Profile identity colours are free fills, including violet #C2B0F7 and sand #EBC77F, near the purple private indicator and amber warnings. Only the temporary profile has a reserved pattern (dashed ring).
- **Impact:** Arc-style profile-tinted frames or tabs could make a profile look like a private, warning or AI-driven state, or hide the real one (Inferred).
- **Fix:** Add a security.* token group with reserved hue, pattern and position for each state (e.g. stripes = automation, dashed = temporary, lock glyph = locked), and a rule that identity tints never use those cues and never exceed a set alpha in the chrome. Contrast.py should assert that identity and security cues stay distinct.
- **Mechanism:** tokens
- **Evidence:** Observed: tokens.json identity group (sand's description says it is 'not a warning'); shell.css:188-193 (dashed temporary ring). The Guard and AI Workspace bars are upstream notification boxes: NulavioGuard.sys.mjs:695, NulavioAI.sys.mjs:265.


### DS-08 · minor · cost M — Token set (docs/brand/tokens.json): gaps and dead tokens

- **Issue:** Missing: z-index scale; scrim (dialog::backdrop borrows identity.on at 45%); ::selection colours; focus ring for accent-filled controls; page density (only chrome tab and field sizes have densities); motion enter, exit and emphasized easings (one curve today) and reduced-motion alternatives; theme-aware elevation (the same navy rgba shadows in dark, where they are invisible). Hover is hard-coded as 8% in two rules instead of the state token. Transitions animate background-color while .button hover is an inset box-shadow, so button hover never animates. The DTCG shadow type is given as a string. Unused tokens: elevation-2, font-size xs/sm/md/lg/4xl, icon size and stroke, motion slow, radius xl and appIcon, space 0 and 9.
- **Impact:** A Zen- or Arc-style redesign (overlays, command bar, compact mode, split view) has no shared values to build on, so one-off values will spread.
- **Fix:** Add these groups: z.*, scrim.*, selection.*, focus.onAccent, density.{compact,normal,touch}.{space,control}, motion.easing.{enter,exit,emphasized}, motion.reduced.*, elevation.{light,dark}.{shadow,tint,border}, plus component tokens. Use state tokens everywhere and transition the property that actually changes. Remove or adopt dead tokens.
- **Mechanism:** tokens
- **Evidence:** Observed: tokens.json (flattened: elevation.1-3 single rgba; motion has 3 durations and 1 easing; no z, scrim, selection or density keys); shell.css:55-56, 208, 259, 293, 301-303. The unused list comes from comparing the generated tokens.css with every var() in shell, startpage and horizon (identity colours are used dynamically via ui.js:80).


### DS-10 · minor · cost S — Contrast tooling (scripts/brand/contrast.py, test_brand_and_docs)

- **Issue:** The 86 declared pairs are hand-picked rather than derived from usage, and the unit test only requires at least 25 pairs, so dropping a pair is not caught. Undeclared combinations below 4.5:1 exist in light: text.muted on bg.sunken 4.22, accent.default on bg.sunken 4.33, text.muted on canvas under the 8% hover overlay 4.0. border.control on sunken is 3.14. All are latent today. Hover and pressed composites and the 35% chip ring on light surfaces (3.45-4.04) are not checked.
- **Impact:** Once the redesign adds tinted or sunken surfaces, sub-AA text can ship while 86/86 still passes.
- **Fix:** Generate the required pairs from a component × state × theme usage map, and assert the exact set instead of a count floor. Add composited checks (state overlays, alpha surfaces) and a forbidden-combination list, e.g. muted on sunken.
- **Mechanism:** tokens
- **Evidence:** Observed: tests/unit/test_brand_and_docs.py:33-37; tokens.json $extensions['nulavio.contrast']; shell.css:178, 208, 293. Inferred: the ratios above, computed with scripts/brand/contrast.ratio.


### DS-11 · minor · cost S — Shell native form controls (assistant panel, checkboxes in dark)

- **Issue:** accent-color is set only on .check input. The assistant panel's mode radios are not inside .check and render Firefox's default blue #0060DF. Unchecked native checkboxes and radios in dark use Firefox's in-content greys (#2B2A33 fill, #949297 border) instead of navy tokens.
- **Impact:** A Mozilla visual trace in the Track B UI, off-palette next to the mint accent.
- **Fix:** Set :root { accent-color: var(--nv-color-accent-default) } in base. Draw tokenised checkboxes and radios with appearance:none and a native fallback under forced colours, like the switch at shell.css:316-350.
- **Mechanism:** Shell page
- **Evidence:** Observed: pixels sampled from tests/artifacts/assistant/panel-dark.png (radio dot #0060DF) and tests/artifacts/vault-ui/create-2-protection-dark.png (#2B2A33 and #949297); browser/shell/assistant/panel.html:26-29; shell.css:144.


### DS-12 · minor · cost M — Component state matrix (inputs, loading, nav, badges)

- **Issue:** Components are missing states. Inputs and selects have no hover, disabled or invalid state; aria-invalid is used 0 times, and errors are tied to fields once (settings.html:154). On the Vault unlock page the wrong-password message sits in #status below the alternatives, away from the field. guidelines §8 specifies skeleton loading in bg.sunken with a spinner after 400 ms, but the new tab shows '…' and body[data-state=loading] has no styling. Settings nav has no current-section indicator, and .popup__item has no :active. The badge--state--* classes have no CSS. Non-interactive start-page cards change border on hover, which suggests they are clickable.
- **Impact:** Weaker error recovery for keyboard and screen-reader users, inconsistent feedback, and misleading hover affordance.
- **Fix:** Publish a state matrix per component (default, hover, active, focus, selected, disabled, loading, error). Add .input[aria-invalid] (critical border plus an icon message linked with aria-describedby), skeleton blocks, aria-current on the nav and styles for badge--state. Remove the hover affordance from static cards.
- **Mechanism:** Shell page
- **Evidence:** Observed: shell.css:128-140, 200-208, 278-293; vault/unlock.html:21-27, 44; tests/artifacts/vault-ui/unlock-error-light.png; newtab.html:46-51; settings.js:607; startpage.css:95-98. Specified: docs/brand/guidelines.md:80-90 (states table).


### DS-13 · minor · cost S — Exact assertions a window/page redesign would touch (update intentionally, never loosen)

- **Issue:** These are the tests that pin today's look; each must be updated in the same PR as an intentional change. Two of them also have weaknesses noted below.
- test_horizon_theme.py: no hex, rgb()/hsl() or !important (L28-32); everything inside -moz-pref('nulavio.horizon.enabled') with nothing before it (L34-43); colour custom properties only inside the not(forced-colors or prefers-contrast) + :root:not([lwtheme]) guard (L45-53); the tokens-foundation-brand-nova layer (L55-58); no #trust-icon, #tracking-protection, #identity-, permission, remote-control, notification-popup or urlbar-label selectors, and no display:none or visibility:hidden (L60-65); no left/right properties (L67-69); jar.mn and the patch 0003 link (L71-77); every var(--nv-*) defined (L79-83).
- test_horizon.py: exact light colours navbar #F1F7F5, toolbox #E2EBEE, selected tab #FFFFFF (L126-128); dark navbar #0B1623, selected #183746 (L141-142); contrast ≥4.5 for selected and background tab labels and address text, ≥3 for field border, focus (light only) and mark (L129-134, 143-147); mark is '' at 16×2 px in the accent colour and absent on other tabs (L153-156); tab heights 34/30/41 px, urlbar max(30px,1.4em) and max(40px,1.4em), selected tab ≥34 px (L158-167); six buttons ≥24 px (L170-179); security UI display and visibility identical on and off (L181-199); urlbar focus colour equals the focus token (L201-211); pref off restores the upstream look (L214-223); built-in Dark gives #0B1623, Alpenglow gives non-Horizon colours, mark follows text colour (L237-254); animation name nulavio-route-in, and none under reduced motion (L256-262); vertical mark 2×16 px (L264-275); high contrast gives non-Horizon colours with the mark kept (L286-303).
- test_engine_slice.py:115-116 (.card radius 14px), 117-133 (.hero__symbol source swap), 131 (dark canvas rgb(11,22,35)).
- test_shell.py integration 137-169 ([data-status] levels, label+placeholder on #search-input, data-ready).
- test_vault_ui.py:261-263: hover must be a box-shadow, not 'none'.
- test_temporary.py:194-201: #current .chip has chip--temporary.
- Unit test_shell.py:49-55 (no style= or inline script in HTML, no innerHTML), 84-102 (locale parity and referenced keys), 285-292 (colours = identity tokens).
- test_brand_and_docs.py:33-48 (all pairs pass, ≥25 pairs, startpage tokens.css current, secure ≠ accent), 134-142 (relative links, including screenshots).
- test_track_b.py:163-165 (≤10 patches).
- CI ci.yml:34-37 (build_tokens --check, contrast.py) and :46 (unit tests).
- Integration tests also select by class: .section, .row__title, .popup__name, .popup__item, .chip, .badge, .button--primary/--secondary, .finding__detail, .row__end, .card.
Weaknesses: test_horizon's rgb() ignores alpha, and the expected colours are hard-coded hex values instead of being read from tokens.json.
- **Impact:** Without this map, an intentional redesign risks someone 'fixing' tests by lowering thresholds or deleting assertions.
- **Fix:** 1) Derive the expected values in test_horizon and test_engine_slice from tokens.json (contrast.resolve) instead of hex literals. 2) Composite alpha before measuring. 3) In test_vault_ui, assert 'hover changes the computed background or shadow' instead of naming the mechanism. 4) Keep thresholds (4.5/3/24 px) as fixed constants that a redesign may not change. 5) Update class selectors in the same PR as any renames.
- **Mechanism:** docs/tests
- **Evidence:** Observed: the files and lines listed in the issue.


### DS-14 · minor · cost S — Docs and screenshot freshness

- **Issue:** Docs counts have drifted: design-system.md says 'generates two files' but lists three, and says 81/81; accessibility.md says 55/55; actual is 86/86. guidelines §10 is labelled 'generated' but has 29 rows. docs/design/screenshots/settings-light.png shows 2 of today's 7 settings sections. guidelines §8 says errors use status.critical, while the Shell uses status.warning for errors. No test checks docs or screenshot freshness; only relative links are checked.
- **Impact:** Reviewers judge the redesign against outdated pictures and numbers.
- **Fix:** Generate the counts and the §10 table with contrast.py --report and verify them with a --check in CI. Keep a screenshot manifest that records the hash of the CSS and HTML each image was taken from, and fail when it is stale. Reconcile the error colour rule.
- **Mechanism:** docs/tests
- **Evidence:** Observed: docs/design/design-system.md:3,11; docs/design/accessibility.md:7; docs/brand/guidelines.md:105-137; browser/shell/settings/settings.html:19-26 vs the screenshot; shell.css:117,120; tests/unit/test_brand_and_docs.py:134-142.


### DS-15 · minor · cost M — Visual regression (tests/lib/pngdiff.py) and capture fidelity

- **Issue:** pngdiff is used only by the opt-in real-site regression (Nulavio vs stock) and pins no Shell or window visuals. Screenshots are written for human review only. Shell captures force [data-theme], but <picture> follows prefers-color-scheme, so dark captures show the light-theme logo (mint-700 on navy, 3.47:1); real users would see the dark asset. All window captures also strip the remote-control indicator.
- **Impact:** Unintended visual changes go unnoticed, and the review artifacts misrepresent dark mode and the automation state.
- **Fix:** Build the planned Shell component gallery (design-system.md:116) and pin it with pngdiff baselines per theme, with mean and changed thresholds. Capture with layout.css.prefers-color-scheme.content-override, as test_engine_slice.py:123 already does, instead of data-theme. Add an automation-on capture.
- **Mechanism:** docs/tests
- **Evidence:** Observed: tests/regression/run_sites.py:30,128; tests/integration/test_vault_ui.py:143-159; tests/integration/test_dns.py:80-89; tests/artifacts/dns/newtab-choice-dark.png; browser/shell/newtab/newtab.html:17-20; scripts/research/shell_screenshots.py:56.


### DS-16 · minor · cost M — Performance: translucency cost and measurement (scripts/research/shell_screenshots.py)

- **Issue:** The perf script would not show what translucency costs. It records firstPaint, sessionRestored and newTabMs only. newTabMs resolves on contentTitle && !busy, but the page has a static English <title> before localisation and the live status render, so it finishes before newtab.js sets data-ready. The harness runs --headless by default, so the real compositor is never exercised. Engine facts: backdrop-filter is enabled in Gecko 158 and not blocklisted on Linux, where it also runs on software WebRender. Upstream notes a WebRender limit of about 4096 device px, beyond which the blur silently drops. Inferred: a blur over the content area re-samples remote content on every scroll frame, and native popup panels are separate widgets that cannot blur the page behind them. No perf budget is enforced in CI.
- **Impact:** Translucent chrome could add jank on scroll or tab switch, especially with software WebRender or on 5K and ultrawide screens, with nothing to detect it.
- **Fix:** Add a --frames scene, run headful (NULAVIO_TEST_HEADFUL=1) on real KDE Wayland. Record chrome requestAnimationFrame intervals for 10 s during: scripted scrolling of a long fixture page under the translucent region; 20 tab switches; urlbar view open and close; opening the profile popup. Report p50/p95/p99 frame time and the share of frames over 16.7 ms. Run an A/B matrix of translucency pref on/off × gfx.webrender.software true/false (it is read once at startup, and each capture is a new session). Include a 5120 px-wide window to confirm the blur fallback, and use gfx.webrender.debug.highlight-backdrop-filters to verify which surfaces blur. Change newTabMs to wait for documentElement.dataset.ready. Budget: translucent p95 within +10% of opaque.
- **Mechanism:** docs/tests
- **Evidence:** Observed: shell_screenshots.py:36-48, 84-102; browser/shell/newtab/newtab.js:118; tests/lib/harness.py:354-356. Engine: StaticPrefList.yaml:11033-11042 and 8828-8831; widget/GfxInfoBase.cpp:1423-1426; gfx/thebes/gfxPlatform.cpp:3475-3499 and 558 (highlight-backdrop-filters debug flag); browser/components/aiwindow/ui/components/ai-chat-content/ai-chat-content.css:53-54, 100-102. Specified: docs/design/migration-plan.md:14 (M7 budget in CI planned).


### DS-17 · polish · cost S — i18n (browser/shell/_locales, lib/i18n.js)

- **Issue:** Parity is good: en and pt_BR both have 771 keys with identical placeholder sets, enforced by test_shell. Gaps: 292 keys are referenced only through template literals (aiCap_${…}, connect_${…}, color_${…}) and are not statically verified, except err_*. t() returns the raw key when a message is missing. Four HTML <title>s carry English fallback text that shows until the module runs. Hard-coded example placeholders include https://api.openai.com/v1 (settings.html:281) and ai.js:116,174. i18n.js sets lang but never dir.
- **Impact:** A missing dynamic key would show a raw identifier, and pt-BR users see a brief flash of English titles.
- **Fix:** Declare the dynamic key families and enumerate them in a test. Have t() log and fall back to the en string, never the raw key. Leave titles empty in HTML. Set document.dir from i18n.getMessage('@@bidi_dir').
- **Mechanism:** Shell page
- **Evidence:** Observed: tests/unit/test_shell.py:84-102, 167-172; browser/shell/lib/i18n.js:4-9; newtab.html:7, settings.html:7, warning.html:7, popup.html:6; settings.html:72-101, 163, 237, 281.


### DS-18 · polish · cost S — RTL, raw px and small details (shell.css, startpage.css, horizon.css)

- **Issue:** Shell CSS still uses physical properties in 4 rules, and no RTL test covers the Shell (Horizon has one). horizon.css uses raw 8px literals, despite its rule 5 that every value comes from tokens. The route-mark keyframe uses scaleX(0.4) for the 2×16 px vertical mark too, so its entrance is only a fade. .more > summary is about 21 px tall with no padding and meets the 24 px target only through the spacing exception.
- **Impact:** Minor RTL breakage if an RTL locale arrives, small motion inconsistency, and marginal target size.
- **Fix:** Switch to padding-inline-start and margin-inline-start, and extend the RTL check to the Shell CSS. Tokenise the icon half-width. Add a scaleY keyframe for vertical tabs. Give summary block padding so it reaches min-height 24px.
- **Mechanism:** Shell page
- **Evidence:** Observed: shell.css:95, 97, 370; startpage.css:89; horizon.css:115, 144-155; shell.css:306-312; tests/unit/test_horizon_theme.py:67-69 (Horizon only).


**Proposals**

- Token schema v2, in DTCG composite form: type.role.* (rem-based display/title/heading/body/label/caption/mono); surface.{chrome,panel,overlay}.{alpha,blur,solid}; elevation.{light,dark}.{shadow,tint,border}; motion.easing.{standard,enter,exit,emphasized} plus motion.reduced.*; focus.{ring,onAccent}; selection.*; scrim.*; z.{base,sticky,overlay,popover,toast,modal}; density.{compact,normal,touch}.{space,control}; security.* reserved cues; component tokens for button, field, chip, card and callout.
- Generator changes: fail on any semantic token defined for one theme only; emit identity colours from both themes and assert they are equal; consider a single light-dark() output for both the Shell and the chrome (Gecko 158 supports light-dark() in content); generate a prefers-contrast:more override block; order the Shell CSS as @layer tokens, base, components, pages, with base.css split out of startpage.css.
- Contrast v2: derive the required pairs from a component × state × theme usage map; assert the exact set instead of '≥25'; composite hover and pressed overlays and alpha surfaces over worst-case backdrops (white, black, saturated); enforce a minimum alpha so a translucent surface without its blur still keeps text ≥4.5:1.
- Translucency stays optional and degrades safely: a Settings toggle (pref) that sets ui.prefersReducedTransparency for the chrome and a root data attribute for Shell pages, with no web-exposed pref. Default it to opaque when gfx.webrender.software is active, if measurements justify that. Blur only overlays (command bar, popovers inside the window), never surfaces that hold security indicators.
- A security-visibility test matrix: for each layout (horizontal, vertical, compact, auto-hide revealed and hidden) and each state (private, temporary, locked, AI Workspace, automation, Guard bar, download warning), assert that indicators are on-screen, unoccluded, at opacity 1 and the same size. Only after it exists, refine the blunt display:none ban.
- A Shell component gallery page, built from real components with no backend-less controls shown as functional: each component in every state, light, dark, prefers-contrast and forced colours (browser.display.document_color_use=2). Pin it with pngdiff baselines, and capture with the content-override pref instead of data-theme.
- A Track B CI lane (self-hosted, or reusing the fedora-build artifact) for test_horizon and the Shell UI tests, plus a perf job that runs the new shell_screenshots --frames scene headful, with the budget: new-tab ≤150 ms measured to data-ready, and translucent p95 frame time within +10% of opaque.


**Open questions**

- Should translucency ever be on by default on Linux, where some systems fall back to software WebRender? This needs --frames data on real Fedora KDE and Ubuntu hardware first.
- Will the redesign offer a Nulavio theme override (light, dark or system) independent of the OS? If so, assets switched by <picture media> must follow it, and the Shell needs the data-theme or content-override path as a real feature.
- Can CI afford a Track B build, or can a nightly or release artifact be downloaded and checksum-verified for the integration lane?
- Is RTL in scope for the foreseeable future? It decides whether to add Shell RTL tests now or only fix the 4 physical properties.
- Will Inter be bundled (SBOM entry pending), or will the type roles be designed around system-ui/Noto Sans metrics?
- Should page density (compact Shell pages) follow browser.uidensity, or have its own setting?
