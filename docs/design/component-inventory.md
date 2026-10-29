# Component inventory: current vs Horizon

Status per component of the browser window and Nulavio's own pages. "Upstream" means Firefox 158's component, unmodified. Milestones refer to the [migration plan](migration-plan.md).

| Component | Upstream implementation | Status (2026-10-25) | Next |
|---|---|---|---|
| **Tab strip** | `tabbrowser-tabs`, `tab.tabbrowser-tab` | **Horizon**: tones, 10 px radius, 34/30/41 px heights, background-tab text colour | Tab hover preview, overflow arrows (M2) |
| Selected tab | `[visuallyselected]` | **Horizon**: raised surface + route mark | — |
| Pinned tab | `[pinned]` | Horizon tokens; mark centred | — |
| Sound / muted tab | `.tab-audio-button`, `[soundplaying]`, `[muted]` | Upstream icons, Horizon colours | — |
| Loading tab | `.tab-throbber`, `[busy]` | Throbber in accent | Nulavio loading motion with the symbol's dots (M6, reduced-motion aware) |
| Crashed tab | `[crashed]` | Upstream | Review copy and icon (M6) |
| Tab groups | Native `tab-group`, editor, list and address-bar actions | UX3B: neutral names, token swatches/thin lines, native semantics; new reserved colours filtered, current legacy value preserved | Physical KDE/Orca checks; see [release evidence](screenshots/ux3b/release-verification.json) |
| Containers | `.tab-context-line`, usercontext | Upstream | — |
| Vertical tabs | `sidebar.verticalTabs`, `#tabbrowser-tabs[orient="vertical"]` | **Horizon**; vertical mark | Layout choice in onboarding (M6) |
| Tab search | List all tabs (`alltabs-button`) | Upstream | Keep; promote in onboarding tips |
| Workspaces | — (tab groups and containers exist) | Not started | Data model proposal before UI (M4+) |
| **Toolbar** | `#nav-bar`, CustomizableUI | **Horizon** colours, 10 px buttons | — |
| Back / forward / reload | `#back-button`, `#forward-button`, `#stop-reload-button` | Horizon; ≥ 24 px measured | — |
| **Address bar** | `moz-urlbar#urlbar` | **Horizon**: 36 px, 14 px radius, ≥ 3:1 border, mint focus ring | Results view surfaces (M2) |
| Trust / tracking / permission icons | `#trust-icon-container`, `#tracking-protection-icon-container`, `#identity-permission-box` | **Untouched by design** (`test_07`) | Privacy Center entry point (M4) |
| New-tab identity chip | identity box for `moz-extension://` | **Shows "Extensão (Nulavio Shell)"** on the new tab: confusing | Fix with the Home milestone (M3) |
| Address bar results | `view-nova.css` | Links in accent; rest upstream | Default top sites without Mozilla entries (M3) |
| Extensions button and actions | `#unified-extensions-button`, extension `browserAction`s | Upstream behaviour, Horizon colours; Proton Pass, KeePassXC, Bitwarden popups unchanged | — |
| App menu / overflow | `#PanelUI-menu-button`, `panelUI.css` | Upstream | Panel tokens (M4) |
| Context menus | `contextmenu.css`, native menus | Upstream (GTK) | Decide native vs Horizon menus (M4) |
| Bookmarks toolbar | `#PersonalToolbar` | Horizon colours, links in accent | — |
| Window controls / CSD | `customtitlebar`, GTK decorations | Upstream; KDE Wayland server-side decorations by default | Screenshot review on real KDE (M7) |
| **New tab (Nulavio Home)** | Shell page | Search, live protection status, shortcuts, "if a site breaks" | Favourites, recent sessions, timing budget (M3) |
| Download warning | Shell page (flow E) and the engine's downloads panel (patch 0007: no Open, shown in its folder, status line) | Done | — |
| Privacy Center | `browser-siteProtections.js`, `controlcenter/` (upstream panels) | Upstream panels | Per-site: upstream trust panel, verified with a real blocked tracker (`test_privacy`); all exceptions: Settings → Site exceptions (Shell) |
| Settings | `about:preferences` | Upstream | Organised sections, Providers (M5) |
| **Nulavio settings** | Shell page (`settings/settings.html`, also Add-ons → Nulavio Shell → Options) | **Done**: Search (defaults, engines, per-provider suggestions, aliases, SearXNG/custom/OpenSearch) and Profiles (edit, open, delete with confirmation, templates) | Smart Routing rules, Integrations (M4–M5) |
| **Profile selector** | Shell toolbar action (`shell_nulavio_net-browser-action`) | **Done**: colour + initial icon, popup with current profile, others (keys 1–9), templates; Alt+Shift+P | Active-profile tint in the window frame (M4) |
| **Routing pages** | Shell pages `routing/ask.html`, `routing/blocked.html` | **Done**: the address as text, nothing loaded, explicit choices (open there, open here, remember) | — |
| **Smart routing rules** | Settings → Profiles → Smart routing; selector "This site" | **Done** (links from other apps, typed addresses, links clicked in pages as an opt-in) | — |
| Link menu "Open link in profile" | Shell `menus` item (content area context menu) | **Done**: lists the other profiles; hidden in private windows | Profile colours as menu icons |
| **Integrations** | Settings → Integrations (Shell) | **Done (P0)**: state in words and a mark, evidence on request, make default / restore | P1/P2 integrations |
| Upstream profile menu | App menu → Profiles, `about:profilemanager`, `about:editprofile`, `about:deleteprofile` | Upstream, linked from Nulavio settings | — |
| Onboarding | `about:welcome` | Upstream | Nulavio flow A (M6) |
| Error pages | `aboutNetError`, `blockedSite.xhtml` | Upstream | Horizon styling, criteria untouched (M6) |

## UX2 Shell system (2026-10-28)

The built-in `dev/gallery/index.html` uses the same production CSS and markup
primitives as the Shell. All states are artificial, labelled and inert.

| Family | Enumerated states | Production owner |
|---|---|---|
| Buttons | Primary / secondary / quiet, native hover / focus / active, disabled, pressed, busy | `shared/components.css` |
| Fields | Default, invalid with associated error, readonly, disabled select | `shared/components.css` |
| Switches | Off, on, disabled on; native checkbox fallback in forced colours | `shared/components.css` |
| Rows / identity | Named initial, temporary named initial with reserved dashed ring, disabled action, narrow stacking | `shared/components.css`, responsive composition in `pages.css` |
| Status | Progress, completed, warning, error with octagon | `shared/components.css` |
| Security | Warning triangle, critical octagon, critical consent with safe-first primary | `shared/components.css` |
| Assistant | Included item, changed-page removal notice, paused/private refusal, progress | `shared/components.css` |
| Accessibility | Focus, reduced motion, increased contrast, forced colours, hidden state | `shared/accessibility.css` (last layer) |

Both themes and narrow/wide renders have reviewed PNG baselines. The gallery
shows visual contracts, not an alternate product UI: real stop/pause/revoke,
consent, private refusal and tab binding remain covered by the existing assistant,
AI and Vault integration modules. No new framework, dependency or telemetry.
