# Nulavio design system (Horizon)

**One source:** [`docs/brand/tokens.json`](../brand/tokens.json) (W3C Design Tokens format). `scripts/brand/build_tokens.py` generates two files, and CI fails if either is stale:

| Output | For | Colour switching |
|---|---|---|
| `browser/startpage/tokens.css` | Start page, Shell pages, site, mockups | `prefers-color-scheme` + `[data-theme]` |
| `browser/branding/nulavio/content/theme/tokens.css` | The browser window (Horizon) | `light-dark()`, following the engine's colour scheme |
| `browser/shell/lib/identity-colors.js` | The profile icon the Shell draws for the toolbar | Same in both themes |

`scripts/brand/contrast.py` checks every declared pair (**89/89 pass**, both themes). `tests/integration/test_horizon.py` re-measures contrast on the rendered window. The generator refuses a semantic colour defined for one theme only (it would fall back to an unrelated value in the other), and a unit test checks that every `var(--nv-*)` in the Shell and start-page sheets exists in both themes.

## Colour

Primitives: navy 950–0, mint 700/400/200/100, amber 700/400/100, red 700/400/300/100 (`color.primitive`). Semantic tokens (light / dark):

| Token | Light | Dark | Use |
|---|---|---|---|
| `chrome.toolbox` | navy.100 `#E2EBEE` | navy.950 `#070F18` | Tab strip, window frame |
| `chrome.toolbar` | navy.50 `#F1F7F5` | navy.900 `#0B1623` | Navigation toolbar |
| `chrome.tabSelected` | navy.0 `#FFFFFF` | navy.800 `#183746` | Selected tab |
| `chrome.tabText` | navy.700 `#23495A` | navy.200 `#BFD0D6` | Background-tab labels |
| `chrome.field` | navy.0 `#FFFFFF` | navy.850 `#112432` | Address bar and fields |
| `chrome.icon` | navy.700 `#23495A` | navy.200 `#BFD0D6` | Toolbar icons (≥ 3:1) |
| `text.primary / secondary / muted` | navy.900 / 600 / 500 | navy.50 / 200 / 300 | Text levels |
| `border.control` | navy.450 | navy.400 | Field boundaries (≥ 3:1) |
| `accent.default` | mint.700 `#0F7A68` | mint.400 `#6FE0C5` | Nulavio, "your route", links, the selected-tab mark |
| `focus` | mint.700 | mint.400 | Focus rings |
| `status.warning / critical` | amber.700 / red.700 | amber.400 / red.400 | Warnings and errors, always with an icon and words |
| `status.criticalText` | red.700 `#A8323A` | red.300 `#EE8A8C` | Critical text and icons (errors, dangerous downloads) on surfaces and on `status.criticalTint` |
| `status.secure` | navy.600 | navy.200 | The secure state is **neutral**: no green "safe" |
| `accent.tint` | mint.100 `#DDF8F0` | mint.900 `#0E3B33` | Badges ("Default", "Current profile") under `text.primary` |

### Profile identity colours (`identity.*`)

Six fills a person picks for a profile: mint `#6FE0C5`, sky `#8CCBF5`, violet `#C2B0F7`, rose `#F4A8BD`, sand `#EBC77F`, slate `#BFD0D6`, with `identity.on` (navy.950) for the icon, initial and ring. They are the same in both themes because a chip is self-contained (fill + ring + icon), and colour is never the only cue: the name, icon or initial is always there. Checked pairs: `identity.on` on every fill (≥ 4.5:1), every fill on the dark toolbar and the ring on the light toolbar (≥ 3:1). Sand is not a warning: it never appears without a profile's name.

## Scales

| Scale | Tokens |
|---|---|
| Spacing | 0, 2, 4, 8, 12, 16, 24, 32, 48, 64 px (`space.0`–`space.9`) |
| Type | UI font = desktop font (`system-ui`, Noto Sans, Cantarell: follows KDE/GNOME scaling); pages: Inter/Noto; mono: JetBrains Mono/Noto Sans Mono. Sizes 12, 13, 14, 16, 20, 24, 32, 44 px; weights 400/500/600 |
| Radius | xs 4, sm 6, **md 10** (tabs, buttons), **lg 14** (address bar), xl 20, pill |
| Elevation | 1: `0 1px 2px` (cards); 2: `0 4px 12px` (popovers); 3: `0 12px 32px` (dialogs). The selected tab keeps Firefox's own shadow |
| Motion | fast 120 ms, base 180 ms, slow 280 ms; easing `cubic-bezier(0.2, 0, 0, 1)`; nothing animates under `prefers-reduced-motion` |
| Icons | 16, 20, 24 px; 1.75 px stroke (Nulavio pages); the chrome keeps Firefox's icon set |

## Sizes and densities (`size.*`)

| | Normal | Compact | Touch |
|---|---:|---:|---:|
| Tab height | 34 px | 30 px | 41 px |
| Address bar height | 36 px | 30 px | 40 px |
| Toolbar buttons | upstream sizes (≥ 24 px measured) | upstream | upstream |

The minimum target is 24×24 CSS px (WCAG 2.5.8); `test_06` measures the real buttons. Densities follow `browser.uidensity` (Customize → Density).

## States

| State | Rule |
|---|---|
| Hover | Text colour at 8% over the surface (`state.hoverOverlay`) |
| Pressed | 12% (`state.pressedOverlay`) |
| Focus | 2 px ring in `focus`, 2 px offset. Never removed |
| Disabled | 45% opacity plus no hover |
| Selected (tab) | Raised surface + the **route mark** (16×2 px, `accent.default`, ≥ 3:1) |
| Error / warning | `status.*` colour + icon + words; never colour alone |
| Success | Neutral confirmation text + undo where possible; no green |
| Loading | Throbber in `accent.default` (`--tab-icon-fill-loading`) |

## Components (window)

| Component | Implemented with |
|---|---|
| Tab strip | `--toolbox-*`, `--tab-*` tokens; `--tab-min-height` per density |
| Selected-tab mark | `.tabbrowser-tab[visuallyselected] .tab-background::after`; vertical variant; follows lwtheme text colour; `SelectedItem` in forced colours |
| Toolbar and buttons | `--toolbar-*`, `--toolbarbutton-*` |
| Address bar | `--toolbar-field-*`, `--urlbar-border-radius`, `--urlbar-height`; results view links via `--link-color` |
| Links in the chrome | `--link-color(-hover, -active)` = accent |
| Profile selector (toolbar) | Shell action; icon drawn from `identity-colors.js` (fill, 1 px ring, initial); popup uses the page components below |

## Components (Shell pages)

| Component | Class | Notes |
|---|---|---|
| Identity chip | `.chip`, `--sm/--md/--lg` | `--chip` set to an `identity.*` token; the engine's profile icon in `identity.on`, initial while it loads |
| Row | `.row`, `.row__main`, `.row__end` | Engine and profile lists; one primary action per row, destructive action quiet and confirmed |
| Switch | `.check--switch input[role=switch]` | Track `border.control` (off) / `accent.default` (on); the label and a hint say what turning it on sends, and to whom; native checkbox in forced colours |
| Disclosure | `details.more` | Less frequent edits (alias, profile name/icon/colour) |
| Confirmation | `<dialog>` via `confirmDialog()` | Native modal; Cancel focused first; destructive verb in critical text. **Critical variant** (`critical: true`, `.dialog--critical`) for consents that raise what an agent may do (full control, raw automation): critical icon before the title, which names the agent; body in `text.primary`; `role="alertdialog"` with `aria-describedby` on the body; the text is always the Shell's locale key, never text from the tools |
| Badge | `.badge`, `.badge--quiet` | `accent.tint` / `bg.sunken` with `text.primary`. Agent levels read "Nível: …": `.badge--warning` (Controle total: `status.warningTint`, warning icon), `.badge--outline` (Autônomo: 1 px `status.warning` ring), plain for Restrito and Assistido; Pausado and Revogado are `.badge--quiet` with a pause or blocked icon. Icons come from `icon()` in `lib/ui.js` and sit next to words |
| Callout | `.callout--critical`, `--warning`, `--info` | Icon (`.callout__icon`) + words + level colour (`status.criticalTint`, `status.warningTint`, `bg.sunken`); a 1 px `CanvasText` border in forced colours. `.callout__action` puts one button at the end, as in the emergency-stop callout ("Retomar") |
| Status line | `#status[role=status]` | Results in words with ✓ or ⚠; never colour alone. Progress uses `data-level="busy"`: secondary text, no mark until it is done |
| Held address | `.url` | A link routing held back, shown as text on `bg.sunken` (never a live link); `overflow-wrap: anywhere` |
| Target profile | `.target` | Chip + profile name on the routing pages |
| Links | `a` | `accent.default`, underlined; thicker underline on hover |
| Steps | `#progress` hint + `h1` | Onboarding flows ("Step 2 of 3"); focus moves to the first control of each step |
| Method choice | `.check` with `input[type=radio]` | One line of consequence under each option (what it protects against, what it does not) |
| Secret field | `.input[type=password]` | `autocomplete=current-password/new-password`; cleared after a wrong attempt, focus kept there |
| Recovery code | `.notice.mono` | Shown once; two groups typed back to confirm; removed from the page after confirmation |
| Plain row | `.row--plain`, `.row__note` | Rows without a chip (agents, permissions, activity); a disclosure spans the row; notes in the body font |
| Permission request | `ai/request.html` | Agent and level as a hint ("Nível: …"), the request as the headline, a risk callout by capability (critical / warning / info, `policy.RISK`), the site as `.url`, where the agent acts (its Área de IA or your profile), the expiry as a clock time. **Deny is the filled primary, first and focused**; "Permitir uma vez" secondary; "Permitir até o agente desconectar" quiet. "Gerenciar agentes" opens in a new tab |
| Window agent bar | `NulavioAI.markWorkspace` (notification box, `dismissable = false`) | Names the agent, its level and where it acts, with "Parar agente". Info priority in an Área de IA, warning in one of the user's profiles, critical for raw automation ("Automação bruta: o Nulavio não verifica nem registra…"). Root attribute `nulavio-state` (`ai`, `ai-profile`, `raw`) for the window theme |
| Locked profile | `vault/unlock.html` | Chip + name, held address as `.url`, password first, other methods as secondary/quiet buttons, states in `body[data-state]` |
| Included item (assistant) | `.assistant__chip` | What goes with the next message and the tab it is bound to ("só da aba “title” · host"), on `accent.tint` with an `accent.default` border; a 24 px remove control named after the item. Added only by an explicit action; leaves after Send. When it leaves on its own, `.assistant__drift` says why (words plus an icon) |
| Off state (assistant) | `.assistant__off` | Replaces the composer (private window, emergency stop, paused, revoked): a heading naming the state, one sentence on what is not sent, and the way back (a secondary button to Settings). Panel states in `body[data-state]`: `ready`, `not-configured`, `not-allowed`, `blocked`, `private` |

Screenshots: [settings](screenshots/settings-light.png), [profile selector](screenshots/profile-selector-dark.png), [routing question](screenshots/routing-ask-light.png), [link not opened](screenshots/routing-blocked-dark.png), [routing rules](screenshots/routing-rules-dark.png); AI & Automation (S7): [connect an agent](screenshots/ai-connect-form-light.png), [configuration shown once](screenshots/ai-connect-result-dark.png), [full-control warning](screenshots/ai-full-control-warning-light.png), [permission request](screenshots/ai-permission-request-light.png) ([dark](screenshots/ai-permission-request-dark.png)), [agent permissions](screenshots/ai-agent-permissions-light.png); protected profiles (S6): [locked profile](screenshots/vault-unlock-idle-light.png) ([dark](screenshots/vault-unlock-idle-dark.png)), [wrong password](screenshots/vault-unlock-error-light.png), [computer login unavailable](screenshots/vault-unlock-device-unavailable-dark.png), [recovery only](screenshots/vault-unlock-recovery-required-light.png), [choose protection](screenshots/vault-create-2-protection-dark.png), [recovery code](screenshots/vault-create-3-recovery-light.png), [settings with a locked profile](screenshots/vault-settings-locked-profile-dark.png); phone (S11): [connect a phone](screenshots/vault-phone-code-light.png), [the 6 digits](screenshots/vault-phone-compare-dark.png), [unlock with phone](screenshots/vault-unlock-phone-light.png) ([dark](screenshots/vault-unlock-phone-dark.png)); temporary profile: [selector inside it](screenshots/profile-temporary-light.png) ([dark](screenshots/profile-temporary-dark.png)); Guard: [changes made outside Nulavio](screenshots/guard-review-light.png) ([dark](screenshots/guard-review-dark.png)); [site exceptions](screenshots/site-exceptions-light.png) ([dark](screenshots/site-exceptions-dark.png)); DNS: [new-tab question](screenshots/dns-newtab-choice-light.png) ([dark](screenshots/dns-newtab-choice-dark.png)), [settings](screenshots/dns-settings-light.png) ([dark](screenshots/dns-settings-dark.png)); passwords: [providers](screenshots/password-providers-light.png) ([dark](screenshots/password-providers-dark.png)), [look-alike site](screenshots/password-lookalike-light.png) ([dark](screenshots/password-lookalike-dark.png)); [assistant panel with a page included](screenshots/assistant-panel-light.png) ([dark](screenshots/assistant-panel-dark.png)), [the page left with a tab switch](screenshots/assistant-drift-dark.png), [emergency stop on](screenshots/assistant-stopped-light.png).

State overlays: the `state.*` tokens are opacities; Shell buttons apply them as `color-mix(in srgb, currentColor <n>%, transparent)` (until S6 the hover and pressed overlays were invalid CSS and showed nothing). Buttons use `appearance: none` so the toolkit never paints them in the other scheme.

## Component gallery

Firefox's Storybook (`browser/components/storybook`) needs a large npm dependency tree. That is more supply chain than this project accepts for documentation, and the chrome components it documents are upstream. Equivalent, already in the repository:

- `docs/brand/mockups/index.html`: the brand's components and flows as HTML using the tokens (`scripts/brand/render_mockups.py` renders PNGs).
- `scripts/brand/ui_directions.py`: the window slice per direction, with contrast.
- `scripts/research/shell_screenshots.py`: the real window, theme × scale × resolution matrix and timings.

A Shell gallery page (live components inside the built-in add-on) is planned with the Privacy Center, when there are more Shell components than two.
