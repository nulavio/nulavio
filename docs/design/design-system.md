# Nulavio design system (Horizon)

**One source:** [`docs/brand/tokens.json`](../brand/tokens.json) (W3C Design Tokens format). `scripts/brand/build_tokens.py` generates four files, and CI fails if any is stale:

| Output | For | Colour switching |
|---|---|---|
| `browser/startpage/tokens.css` | Start page, Shell pages, site, mockups | `prefers-color-scheme` + `[data-theme]` |
| `browser/branding/nulavio/content/theme/tokens.css` | The browser window (Horizon) | `light-dark()`, following the engine's colour scheme |
| `browser/shell/lib/identity-colors.js` | The profile icon the Shell draws for the toolbar | Same in both themes |
| `browser/shell/shared/sidebar-focus.css` | Focus rings in native sidebar documents | `light-dark()`, scoped to internal sidebar URLs |

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
| Selected (toggle) | `[aria-pressed=true]`: `accent.tint` surface, `accent.default` edge and a ✓; a `Highlight` outline in forced colours |
| Selected (address-bar result) | `accent.tint` under `text.primary` (≥ 4.5:1, URL and secondary text inherit it) + the 2 px `focus` ring in the row's gutter (≥ 3:1 on the panel) |
| Pressed tool (sidebar launcher) | `accent.tint` + 1 px `accent.default` edge; the Nulavio symbol stays ≥ 3:1 on it |
| Warning | `status.warning` + ⚠ + words |
| Error / critical | `status.criticalText` + the octagon icon + words; never the warning triangle, never colour alone |
| Success | Neutral confirmation text + undo where possible; no green |
| Loading | Throbber in `accent.default` (`--tab-icon-fill-loading`) |
| Progress (pages) | A neutral spinner before the words in the status line (static under reduced motion); no ✓ until there is a result |

## Components (window)

| Component | Implemented with |
|---|---|
| Tab strip | `--toolbox-*`, `--tab-*` tokens; `--tab-min-height` per density |
| Selected-tab mark | `.tabbrowser-tab[visuallyselected] .tab-background::after`; vertical variant; follows lwtheme text colour; `SelectedItem` in forced colours |
| Toolbar and buttons | `--toolbar-*`, `--toolbarbutton-*` |
| Address bar | `--toolbar-field-*`, `--urlbar-border-radius`, `--urlbar-height`; results view links via `--link-color`; selected and hovered results via `--urlbarview-*` (not the system `SelectedItem`) and the focus ring on `.urlbarView-row[selected]` |
| Sidebar launcher | The open tool's `moz-button` re-valued inside `sidebar-main` (`--button-background-color*`, `--button-border-color*`); closed tools are ghost buttons |
| Native sidebar focus | A scoped agent sheet registered by `NulavioWindow` through the Shell's existing startup lifecycle; the focus token replaces the stock blue. It steps aside for installed themes, Horizon off, forced colours and increased contrast. No rule matches web content. `test_sidebar_focus` measures the actual native button background span: 4.60–5.24:1 in light, 8.87–9.84:1 in dark |
| Nulavio symbol | `shared/nulavio-symbol-adaptive.svg` (generated by `build_logo.py`): Mint 700, mint under a dark colour scheme; the tab icon of Shell pages, the toolbar button and the sidebar launcher. Firefox draws it with the window's scheme (≥ 3:1 measured on every surface by `test_horizon`) |
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
| Status line | `#status[role=status]` | `announce(text, level)`: `info` (no mark), `progress` (spinner), `ok` (✓, only for a result that happened), `warn` (⚠, `status.warning`), `error` (`status.criticalText` + octagon icon). A hint already on the page is not repeated there |
| Native controls | `:root { accent-color }` | Radios and checkboxes in `accent.default`, not the toolkit's blue |
| Download warning | `warning/warning.html` | A program: **Show in folder** primary and focused, Delete secondary. A dangerous verdict: **Delete file** primary and focused, `.callout--critical` with the octagon and its own headline. Never Open |
| Look-alike login | `passwords/lookalike.html` | Go to the real site primary and focused; "Continue and don't warn again for this pair", with what it changes and where to undo it right under the buttons (Settings › Passwords › Sites you confirmed) |
| Phone comparison | `vault/phone.html` | Focus on the 6 digits (read one by one to screen readers) and their question; both answers secondary, same weight |
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

## Shell cascade and component gallery (UX2)

`shared/base.css` is owned by the Shell. It contains reset, inherited type,
solid canvas and `.page` layout. The launcher/site continue to use the independent
`browser/startpage/startpage.css`; the Shell build no longer copies that sheet
under the name `base.css`.

Existing pages keep exactly three links: generated `tokens.css`, `base.css`,
and `shell.css`. The last is an entry point with one import each for
`components.css`, `pages.css` and `accessibility.css`. All rules live in named
layers, ordered `nv-base`, `nv-components`, `nv-pages`, `nv-gallery`,
`nv-accessibility`. Gallery composition cannot override the accessibility layer.
New page sheets must use `nv-pages`, never unlayered overrides. Avoid `!important`
except visibility and the global reduced-motion guard. Important declarations
reverse layer priority; do not add competing important rules in earlier layers.

Components own buttons, fields, switches, rows, cards, identity chips, status,
callouts, dialogs and assistant context/refusal parts. Page composition owns
hero/facts, Settings header/navigation, routing, download layout, phone pairing
and popup dimensions. The canvas and components are solid; optional new-tab
ambience/translucency remains UX6.

Buttons (including primary), fields and context chips use the existing 10 px
`radius.md`; security callouts, critical consent, refusal/drift and warning badges
use opaque 4 px `radius.xs`, without animation. Warning keeps the triangle;
validation errors use critical text plus the octagon, matching `aria-invalid`
borders. Progress is neutral and never carries the success check. Native switch
semantics stay intact, with native appearance restored in forced colours.

The real built-in gallery is `dev/gallery/index.html` below the Shell extension
origin (replace `/newtab/newtab.html` in the built-in new-tab URL). It is a
development surface, labelled **Artificial examples only**, has no script or
privileged API and keeps all specimens inert. It imports production CSS, rather
than copying component styling. It follows the system theme; the rendered test
sets the generated token sheet's existing `data-theme` override for both themes.
Hover/focus/active specimens use engine pseudo-class locks in the test, not fake
state selectors in production CSS. The safe consent choice is first and primary.
The mockups in `docs/brand/mockups` remain design references, not this gallery's
implementation.

`tests/integration/test_component_gallery.py` checks real 1280/390 CSS-pixel
viewports × light/dark, production state styles, no horizontal overflow, safe
ordering, inert controls, reduced motion, 320/390 px reflow with 200% root font,
high contrast, and native switches under forced colours. Track B is required:
stock Firefox does not prove the built-in origin or packaging. Unit tests cover
packaging and the source/import boundaries without an engine.

PNG baselines live in `tests/baselines/component-gallery/`. They use the copied
Nulavio 159.0 Linux engine, BuildID `20261028130348`, SourceStamp
`5add844c26613d7e4d84c799d6e23cf987b1240d`, with dev-synced Shell sources.
Window chrome is excluded. The 390 px fixture removes the native window's 500 px
minimum only inside its disposable test window and asserts actual `innerWidth`.
Reduced motion freezes the neutral progress indicator. Repeated captures must
be identical. `pngdiff` samples every pixel; dimensions must match exactly;
mean difference ≤ 0.1 grey level and changed share ≤ 0.001 (threshold 40).
These small allowances accommodate raster drift, not layout changes. A negative
control hides the critical callout and must fail the same oracle in every case.
Each critical callout also has a cropped baseline and must reject removal of
its octagon, so a missing glyph cannot be diluted by the full page. No
pre-existing pixel/security assertion was relaxed.

To propose baselines, run with `NULAVIO_UPDATE_GALLERY_BASELINES=1`, inspect all
four full-page PNGs and their four critical-callout crops, then rerun without that flag. Never regenerate them just to clear CI.
Font/engine changes require a reviewed refresh. Parent integration must rebuild
the real package and repeat the gallery suite after the tokens v2 merge.

Token dependency: this slice uses only the existing variable API. Tokens v2
will migrate identity colours and rem type roles. Suggested role replacements
for the current sizes are `type.body`, `type.label`, `type.heading`, and
`type.caption`; no such undefined aliases are emitted here. Existing heading
size tokens have rem floors so text enlargement already works. Manual Orca,
real GTK high-contrast themes and the final rebuilt release remain separate
verification obligations.

## UX1 verification (2026-10-28)

The assistant's page item is consumed per message. Pending Include and Summarise replies are invalidated by Send, mode changes and page changes; a delayed reply cannot attach a page to a later message or start a second request. The real sidebar regression test holds the experiment reply, sends a question, releases it, and checks both the item and the provider's received messages. It failed before the fix and passes after it.

Rendered QA covers a 318 px assistant panel inside a 1366×768 window, both system themes, a long page title, included context and the emergency-stop state. No overflow or automatic audit errors were found. The audit's iOS input-zoom warning does not apply to this Linux surface; the Inter fallback is intentional and documented in the brand guidelines. Manual Orca and real desktop contrast-mode checks remain pending. The registered sidebar sheet only changes keyboard-focus colour; the full panel styling belongs to UX3.

During verification, one run timed out waiting for the recovery-unlocked profile to unmount after its engine was terminated. Three isolated replays passed, with unmounts in 0.34–0.62 s; the original cause was not established. The shutdown assertion and its deadline were kept unchanged.

Captures: [included page, narrow/light](screenshots/assistant-narrow-context-light.png), [emergency stop, narrow/dark](screenshots/assistant-narrow-stopped-dark.png), [critical agent request](screenshots/ai-permission-request-critical-dark.png), [separate raw-automation consent](screenshots/ai-raw-automation-warning-light.png).

### UX2 render review

The reviewed narrow/light and narrow/dark captures keep the inventory in one
column; long context and consent copy wrap, actions stay in reading order, and
warning/critical glyphs remain inside their callouts. The wide captures use two
aligned columns. The initial excess spacing inside the button specimen was
removed; invalid-field helper text now matches the critical border and octagon.
The forced-colour/font-enlargement capture preserves words, glyphs and native
switches without clipping. The gallery is new, so no same-route before image
exists; existing page behavior is checked by the integration modules.

Visual rubric (0–3): hierarchy 3, layout 2, type 2, colour 3, spacing 2,
states 3, reflow 3, accessibility 2, copy 3, distinctiveness 2; mean 2.5.
This is a scoped visual assessment, not accessibility certification.

Run the existing Vault, assistant and AI integration modules **sequentially**
when they share one engine copy: Vault's `test_06_tools_missing` temporarily
renames that copy's `nulavio-tools` directory. Parallel execution can make the
other modules report missing tools. A recovery-unmount timeout was also observed
under concurrent load; a later sequential full Vault run passed with the original
30-second assertion unchanged. Its cause is not established by that replay.
