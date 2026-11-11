# Nulavio design system (Horizon)

**One source:** [`docs/brand/tokens.json`](../brand/tokens.json) (W3C Design Tokens format). `scripts/brand/build_tokens.py` generates four files, and CI fails if any is stale:

| Output | For | Colour switching |
|---|---|---|
| `browser/startpage/tokens.css` | Start page, Shell pages, site, mockups | `prefers-color-scheme` + `[data-theme]` |
| `browser/branding/nulavio/content/theme/tokens.css` | The browser window (Horizon) | `light-dark()`, following the engine's colour scheme |
| `browser/shell/lib/identity-colors.js` | The strong identity fills, for drawing | Same in both themes |
| `browser/shell/shared/sidebar-focus.css` | Focus rings in native sidebar documents | `light-dark()`, scoped to internal sidebar URLs |

`scripts/brand/contrast.py` checks every declared pair (**220/220 pass**, both themes; the original 208 pairs are preserved). `tests/integration/test_horizon.py` re-measures contrast on the rendered window. The generator refuses a semantic colour defined for one theme only (it would fall back to an unrelated value in the other), and a unit test checks that every `var(--nv-*)` in the Shell and start-page sheets exists in both themes.

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

Six fills a person picks for a profile: lima `#C5E384`, sky `#8CCBF5`, violet `#C2B0F7`, coral `#F4A8BD`, sand `#FDCF8B`, slate `#BFD0D6`. `identity.on` and `identity.ring` use opaque navy.950 ink (`#070F18`); the ring is 1 px. They are the same in both themes because a chip is self-contained (fill + ring + icon), and the name, icon or initial is always there. The palette migration and its Settings note are described in [ADR 0003](../adr/0003-nulavio-profiles-and-routing.md#farol-identity-upgrade-ux2-2026-10-28). Mint is reserved for Nulavio/active controls. The temporary state has its own neutral fill and dashed edge. Checked pairs include icon/text on every fill (≥ 4.5:1) and the ring against light surfaces (≥ 3:1).

## Scales

| Scale | Tokens |
|---|---|
| Spacing | 0, 2, 4, 8, 12, 16, 24, 32, 48, 64 px (`space.0`–`space.9`) |
| Type | UI font = desktop font (`system-ui`, Noto Sans, Cantarell: follows KDE/GNOME scaling); pages: Inter/Noto; mono: JetBrains Mono/Noto Sans Mono. Sizes 12, 13, 14, 16, 20, 24, 32, 44 px; weights 400/500/600 |
| Radius | xs 4, sm 6, **md 10** (tabs, buttons), **lg 14** (address bar), xl 20, pill |
| Elevation | 1: `0 1px 2px` (cards); 2: `0 4px 12px` (popovers); 3: `0 12px 32px` (dialogs). The selected tab keeps Firefox's own shadow |
| Motion | fast 120, base 180, slow 280, expand 220, collapse 160, fade 80 and spin 900 ms; easings standard `cubic-bezier(0.2, 0, 0, 1)`, enter `(0, 0, 0, 1)` and exit `(0.3, 0, 1, 1)`. Under `prefers-reduced-motion` nothing moves, but what appears after a delay still appears; security cues never move (`security.duration` 0). See "UX7: motion and performance budget" |
| Icons | 16, 20, 24 px; 1.75 px stroke (Nulavio pages); the chrome keeps Firefox's icon set |

## Sizes and densities (`size.*`)

| | Normal | Compact | Touch |
|---|---:|---:|---:|
| Tab height | 34 px | 30 px | 41 px |
| Address bar height | 36 px | 30 px | 40 px |
| Toolbar buttons | upstream sizes (≥ 24 px measured) | upstream | upstream |

The minimum target is 24×24 CSS px (WCAG 2.5.8); `test_06` measures the real buttons. Densities follow `browser.uidensity`, chosen in Nulavio Settings → Aparência (Automático, Normal, Compacto, Toque) or in about:preferences.

## States

| State | Rule |
|---|---|
| Hover | 8% over the surface (`state.hoverOverlay`); overlay colour depends on the component variant |
| Pressed | 12% (`state.pressedOverlay`), with the same contrast-preserving variant colour |
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
| Profile selector (toolbar) | Shell action; monochrome in the toolbar's icon colour: the profile's solid glyph (or initial) on a 14 % square (`lib/profile-icon.js`); the colour shows once per window, in the band; popup uses the page components below |

## Components (Shell pages)

| Component | Class | Notes |
|---|---|---|
| Identity chip | `.chip`, `--sm/--md/--lg/--xl` | Calmaria: a soft tile (`identityTile.*`, corners 30 %) with the profile's solid glyph or initial in `identityGlyph.*` (≥ 6.3:1); no ring; `--chip` keeps the strong fill for alert rows; `.chip--temporary` is dashed with the hourglass |
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

State overlays: `state.*` tokens are opacities. Ordinary buttons use their text colour; primary buttons use `text.primary`, and destructive buttons use `bg.canvas`. These variant overlays preserve text contrast in both themes. The exact composited checks include hover and pressed states; rendered pixel samples separately check primary hover/pressed and destructive pressed. Buttons use `appearance: none` so the toolkit follows the page theme.

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
development surface, labelled as artificial examples in en/pt-BR. Its only
script runs the existing localisation helper; specimens stay inert and no
product API is called. It imports production CSS and follows the system theme.
The rendered test sets the generated token sheet's existing `data-theme` override for both themes.
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

PNG baselines live in `tests/baselines/component-gallery/`. The integrated
pt-BR baselines include tokens v2, the six identity fills and reserved temporary
fill, rem roles and localisation. Final verification uses rebuilt Nulavio 159.0,
BuildID `20261028184647`, SourceStamp `5add844c26613d7e4d84c799d6e23cf987b1240d`.
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
Font/engine changes require a reviewed refresh; the integrated baselines were
reviewed again after type, palette and localisation changes. The final run
compares them without the update flag on the rebuilt package.

Integrated tokens v2: the Shell consumes `type.body` (1 rem/400),
`type.label` (.875 rem/500), `type.caption` (.8125 rem/400), `type.title`
(1.5 rem/600), `type.section` (1.25 rem/600), and `type.code` (.875 rem/400).
Legacy font variables remain available. Identity chips and swatches now use
the opaque ink ring; selection and dialog scrims use their themed tokens.
Manual Orca and real GTK high-contrast themes remain separate obligations.

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


### UX2 integrated verification (2026-10-28)

The production package is Nulavio 159.0, BuildID `20261028184647`, tarball
SHA-256 `e93223bccb3f1845da63b439193ae734721c3cc6ac6756b1eb19016d8afecebf`.
All 93 packaged Shell/theme source entries were compared byte-for-byte with
the integration sources. The gallery's four theme/width baselines have zero
pixel difference; their negative controls detect removal of the critical
callout and of its octagon. [Measurements](screenshots/ux2/gallery-measurements.json)
and the [exact 208 composited contrast checks](screenshots/ux2/contrast-pairs.json)
are recorded separately.

The actual 318 × 616 px assistant panel was audited on included-page and blocked
states, both themes: zero runtime UI-audit errors. The Inter fallback and iOS
input-zoom warnings have the same scope as UX1; manual Orca/GTK checks stay open.
[Audit](screenshots/ux2/assistant-audit.json).

Before/after captures use the verified UX1 package and the rebuilt UX2 package:
[before, light](screenshots/ux2/ux2-before-light-1366x768@100.png),
[after, light](screenshots/ux2/ux2-after-light-1366x768@100.png),
[before, dark](screenshots/ux2/ux2-before-dark-1366x768@100.png),
[after, dark](screenshots/ux2/ux2-after-dark-1366x768@100.png).
The quick timing sample (two fresh sessions, three new tabs each) measured
51.4 ms before and 49.4 ms after median new-tab opening. It ran alongside other
verification, so it is a budget observation, not evidence of an improvement.
The canvas is solid and no blur is applied.

Critical/destructive native dialogs now use Cancel as the filled primary,
focused first, with confirmation outlined in the critical colour. A rendered
regression reproduced the missing primary on full-control consent before
the fix, and covers both full-control and separate raw-automation consent.
The gallery palette uses data attributes plus external CSS; the original
no-inline-style/no-inline-script guard remains unchanged.

Rendered overlay regression: the prior primary pressed state measured 4.18:1 in light, and destructive pressed measured 4.32:1 in dark. After correction they measure 6.15:1 and 5.46:1 respectively. The original 4.5:1 minimum is unchanged.

The independent integration review found one future-schema guard defect: version 3 without the current `mint` array could be treated as version 0. The real Gecko regression reproduced it with renamed and retyped payloads. The reader now respects a future version before inspecting its payload, preserving both stored strings exactly; all five migration tests pass after the fix. No unresolved review finding remains from that pass.

English gallery verification uses a disposable en-US profile: 1280/390 px in both themes and 320/390 px at 200% root font, with no horizontal overflow. [Measurements](screenshots/ux2/english-measurements.json) and [English narrow/dark](screenshots/ux2/gallery-en-390-dark.png).

Final integrated results on the reviewed package: 600 unit tests OK (1 skip), 194 Track B integration tests OK (13 skips), 208 declared contrast combinations, Ruff/generated-file checks and all six security scans. [Capture provenance](screenshots/ux2/capture-provenance.json); archived previous page captures are kept under `screenshots/ux2/before/`.


## UX3A: trusted band and window safety (local implementation, 2026-10-28)

This is the band and safety grammar slice of UX3, implemented on base
`cf548dfb19868c319f8164c6ba469b5e473fbeee`. Tab groups, downloads badge/patch
0007, layout/personalisation onboarding and Shell/assistant flow redesigns
remain later slices. This slice does not mark the whole UX3 programme complete.
The initial task-copy evidence is preserved below; the parent's rebuilt-package
result follows it. Local checks and remote CI are separate evidence.

`NulavioWindow` owns the `nulavio-band` CustomizableUI toolbar area and its
non-removable custom widget. It inserts only its own toolbar before
`TabsToolbar`, leaving the native controls and their parents intact. The widget
uses a XUL `hbox`, accepted by Gecko 159's custom-widget API: unlike a
`toolbaritem`, CustomizeMode does not wrap it in a draggable, event-blocking
palette item. The native-window author sheet keeps this area visible even when
CustomizableUI sets `collapsed`; it is independent of the cosmetic Horizon
preference. It neither resets customization nor changes native security icons.

The solid band uses `band.bg` (light `#BFD0D6`, dark `#04080D`), a 30 px minimum
and wrapping content. The actual profile name, colour and engine avatar (or
initial) are enclosed by the opaque identity ink ring. An AI Workspace uses
its actual agent name and the reserved ink flag. Protection comes directly
from `profileLockState` for the current profile directory: protected/unlocked,
unprotected, or unknown on read failure. An unavailable profile identity is
named as such. The identity button opens the existing native Shell action
popup; if its original action was removed, the same real selector opens as a
Shell tab without restoring that action. Protection opens the existing
profile-management page. The current
Vault API refuses `lock(current)` with `is-current`, so this slice does not
invent a one-click current-profile lock. The real unlock and relock-on-last-
window-close workflows remain authoritative.

A trusted system-page label requires the selected top document's
`principal.addonPolicy.id === "shell@nulavio.net"`, the Shell host, a fixed
known pathname and the committed current document URI. Loading documents get
no header. Titles, body text, query parameters and fragments never supply its
words. Navigation clears text, accessible name and tooltip together; tab
switches recompute synchronously. Page-title preferences are unchanged,
retaining native KDE title-bar behaviour per D-UX17, which supersedes the
older title-hiding proposal in the mockup rationale.

Each warning composes independently: temporary (dashes and deleted-on-close
words), private (plum/dots and assistant-off words), agent (name, actual level,
lines and double content frame), raw automation (critical diagonal sample and
explicit unchecked/unlogged words), and Guard (pending count and real Review
entry). `NulavioAI.windowWarning()` reads the same raw session latch as the
original non-dismissible bar; `windowState()` adds registry identity/level and
an explicit unavailable result. A successful registry read also supersedes the
old bar's cached paused flag, so an explicit backend resume is reflected. A synchronous warning event and a revision
check prevent an older idle/status result from erasing a newer warning. Failed
refreshes preserve known raw/agent identity and label status unavailable.
Guard changes signal a read of its existing findings; this does not start a
new Guard audit in an AI Workspace, where the existing backend skips checks.

Pause calls the real per-agent pause API. **Stop all agents and assistant**
calls the real global emergency stop; both locales and accessible names state
its scope. Raw opt-in, grants, pause/revoke and backend policy are unchanged.
The original AI, temporary and Guard notification bars and their safety
assertions remain in place. This slice adds the band without claiming that
those bars have been consolidated or redesigned.

Fullscreen has a separate chrome flow element outside the collapsing toolbox,
above web content and below native security popovers. Its persistent 3 px line
has independent segments, so one state cannot replace another pattern. The
worded notice appears for four seconds on entry/state change, on a trusted
mouse movement at the top edge, or on keyboard focus. Focus inside it retains
the actionable notice; leaving permits it to compact again. No safety cue
animates, fades or blurs. Native fullscreen exit warnings keep their own
popover and input handling.

Lifecycle is idempotent: startup enumerates restored windows and observes new
ones; unload/stop remove the progress/tab listeners, observers, stylesheet,
owned elements and notice timers. A generation check rejects work completed
after stop/restart. The pre-existing scoped sidebar-focus agent stylesheet
keeps its original registration and theme/accessibility guards.

The [UX3A evidence](screenshots/ux3a/verification.json) records commands,
results, source/package hashes, fixture provenance and captures. These are
headless checks of a task-owned application copy with `dev_sync.py`, not a
fresh engine build or accessibility certification. The parent subsequently
performed the rebuild and complete integration recorded below.

## UX3A rebuilt-package verification (2026-10-29)

The production sources at `baa432b5b544597ecf908eb4054cb5553691f727` were
rebuilt through `build_nulavio.sh 159.0`, extracted into a disposable install
and populated with the real distribution and Nulavio tools. This package was
not modified with `dev_sync.py`. All 94 checked Shell, theme, preference and
branding-module entries match their source bytes. Package BuildID:
`20261029043253`; runtime BuildID: `20261029043250`. Tarball SHA-256:
`5b0db884cd414c7a794cf29511bf75b3695367b1f78a2707c6f07d3272c1c55b`.

The complete local suites passed: **600 unit tests (1 skip)** and **207 Track B
integration tests (13 skips)**. Ruff, all four generated-file checks and
**220/220** contrast pairs passed. The 23 security-tooling tests also passed
after recording two exact Gitleaks fingerprints: both flagged the public
SHA-256 of `docs/brand/tokens.json`, verified against that file. The remaining
scanners passed; no rule, scan scope or security threshold was relaxed.
The [release report](screenshots/ux3a/release-verification.json) records exact
commands, logs, hashes and skip reasons. External agents, real Android,
network opt-ins and visible-window cases are not claimed as executed.

An independent automated review of the base/head found no actionable defect
in this scope. Its bounded stop/restart probe passed six assertions that an
old agent/raw refresh cannot repaint after teardown. This is an AI review,
not human approval or desktop accessibility certification.

Fresh captures on the rebuilt package preserve the original task evidence:
[light](screenshots/ux3a/release-after-light.png),
[dark](screenshots/ux3a/release-after-dark.png),
[composed warnings](screenshots/ux3a/release-composition-dark.png),
[real raw handover](screenshots/ux3a/release-real-raw-dark.png) and
[fullscreen line](screenshots/ux3a/release-compact-dark.png).
The composed scene uses a real registry, retained Guard findings and a
synthetic live-PID marker read by the AI owner; the raw-handover scene comes
from an actual Bridge-owned endpoint. The normal before/after captures use
the same local page, profile name, native vertical tabs and 1366 × 768 window.
Native automation stripes remain visible.

Remote CI is tracked separately by the published full SHA. Its Fedora/Ubuntu
jobs use distribution Firefox; privileged Track B verification is the local
rebuilt-package run above. Physical KDE/GTK, Orca, hardware scaling and frame
times remain pending. Later UX3 and UX4–UX7 work is not closed by this slice.

## UX3B: native tab groups (local application-copy verification, 2026-10-29)

Built on `25e591d8ef8184a4aaf0da6b535bf7d86c1248d6`. Horizon renders the
existing group button as neutral name + small colour swatch + thin native group
line, in horizontal and vertical tabs, with expanded/collapsed group semantics
kept by Gecko. The active tab retains its separate mint route mark. All nine
native colour families map to the already generated `group.*` tokens, including
the low-chroma legacy orange, purple and red values. Ink, inverse surfaces,
pale/text and hover roles remain distinct for native action consumers. Token
values, colour names and Fluent resources are unchanged. The native group list
uses the same ink variables.

D-UX16 filters both the unavailable native radio **and** its adjacent label.
Hiding only the label was reproduced as an invisible keyboard destination.
The selected native legacy radio is deliberately an explicit current-value
exception: its original localized name, tooltip, neutral swatch and checked
state remain visible/accessible until the user chooses an available colour.
Opening or dismissing the editor preserves the stored colour. Once replaced,
that legacy colour disappears from the choices and cannot be reached with the
arrows. No group data is migrated, renamed or rewritten.

CSS cannot affect Gecko 159's `nextUnusedColor` getter: it still picks from all
nine names, even after hiding inputs. A small per-window adaptation in
`NulavioWindow` filters the default candidate set, first choosing an unused
available colour and then reusing an available colour when exhausted. It wraps
only the existing editor instance and restores its getter on teardown. Explicit
and restored colours remain native. There is no engine patch, parallel picker
or keyboard interception. Both the CSS and getter yield immediately to Horizon
off, installed themes and high/forced contrast. Native focus/ARIA/navigation,
user placements and all security controls remain owned by Gecko.

[UX3B verification](screenshots/ux3b/verification.json) identifies the exact
source/package bytes, commands, results, input probes, captures and remaining
limits. This is a task-owned copy of the parent's UX3A package synchronized with
`dev_sync.py`, **not** a new production build. The parent owns the rebuild,
publication and CI. Native popup widgets are absent from the main-window
headless screenshot surface (also checked with `Capture.canvas`/`drawView`);
editor evidence is real trusted input, geometry, computed focus and Gecko
accessibility state, not a claim that those popup pixels were captured. Orca,
physical KDE/GTK/forced colours, hardware scaling and frame time remain pending.

The parent's UX3A publication is separately recorded at
`25e591d8ef8184a4aaf0da6b535bf7d86c1248d6`, with all six jobs successful in
[CI run 40819764438](https://github.com/nulavio/nulavio/actions/runs/40819764438).
Its local privileged engine opt-in run passed 15 tests with zero skips, including
live Safe Browsing phishing blocking, per the supplied
`network-engine-verification.json`. These are parent release results, distinct
from UX3B's new local checks and from distribution-Firefox CI. The committed
UX3A `release-verification.json` and its original hashes/history are preserved.

The organisation idea drawn from Zen solves the user's need to keep related
pages together without turning every group into a separate profile. Nulavio
adapts it through Gecko's existing groups, with neutral names, thin colour lines
and a separate trusted profile band. Group colour never claims profile
isolation or a security state. No reference-browser code, assets, labels or
distinctive layout were reused.

### UX3B parent contrast correction

The independent automated review found one introduced P2: the Proton
address-bar action for switching to a named group had identical foreground and
background colours (1:1). A real native-action regression reproduces that
failure before the correction. Native colour families now retain distinct text
and surface roles, including Nova and drag-feedback consumers. Hover uses an
opaque 92% group-ink / 8% canvas mix plus underline; native focus and pressed
outlines are preserved. All nine colour families are measured in 108 native
action states (two themes × two native UIs × three interaction states).
The contrast declaration set grows from 220 to 256 expanded combinations,
retaining every previous declaration and threshold. No engine patch, behaviour
JavaScript, security assertion or stored group data changes in this correction.
The original child verification above remains an immutable pre-correction
record. The [parent real-build report](screenshots/ux3b/release-verification.json)
records 94 matching source entries, 218 integration tests (13 skips), the English
11-test group suite, 15 engine opt-in checks, 256 contrast combinations and
actual native editor pixels in both themes. Four fresh registered profiles ran
inside an isolated Xvfb container; the six-colour picker and named current
legacy colour are visibly captured. These virtual-screen pixels do not certify
a physical KDE/GTK desktop or Orca.

The first parent full-suite attempt had one Vault creation timeout and three
cascading errors. The isolated create and all nine Vault tests passed on the
same package, followed by one green full-suite repeat. Cause remains UNKNOWN;
only the failed-wait diagnostic now includes inline error text. No production
Vault code, time limit or state assertion changed. Both the failed run and the
successful repeat remain hashed evidence. Publication/CI are post-commit gates,
separate from this local verification snapshot.


## UX3C: native downloads type warning (2026-10-29)

D-UX18 adds the native warning triangle to the existing downloads button when
its public/private **current Downloads API list** contains at least one program
file. The filename-only extension policy stays identical to the Shell's
`risky.js`; archives are not inspected. This is a type warning, not a reputation
verdict, malware classification, critical state or verification claim (R15).

The criterion is list membership, without an expiry or completion requirement:
in-progress, completed, canceled, paused and failed program items qualify,
including items Gecko restores into that list. Viewing/closing the panel does
not dismiss the type warning. Removing the last eligible item, Clear Downloads
for removable items, or clearing the private list at its last-window close
clears the marker and supplemental accessible description. An active/paused
item that Gecko keeps during Clear Downloads keeps the warning too. Deleting
through the existing Shell warning removes both file and list item. Deleting a
file externally leaves its list entry until the user removes it; the words
refer to downloads, never assert that a complete file exists.

Patch 0007 passes membership from the privacy-scoped `DownloadsData` to the
native indicator view. That data owner stays linked to the real list while no
indicator is attached. The indicator's own weak-map cache can retain removed
objects during detachment; a deterministic regression keeps such an object
alive, removes it while detached, adds a regular item and reconnects. Using
that stale cache was reproduced as a ghost badge; using the current data
owner clears it without changing Gecko's native caches or attention algorithm.

The view composes a warning with native attention: none/success/info gain the
triangle, warning remains warning, **severe remains severe** with its native
icon and colour. No download's attention, error, verdict or progress is changed.
Panel acknowledgement keeps its native effect on native attention; only the
type warning persists. A small native CSS rule keeps the badge visible during
start/finish notifications, including an overriding native severe badge.
Progress and its animations keep their native implementation. Horizon uses the
existing `downloads.attention.warning` token; installed themes, Horizon off and
increased contrast retain native warning colours. No new token or threshold.

The original localized button name, shortcut tooltip and descriptions are
retained. A hidden, referenced description adds “Aviso: há downloads de arquivos
de programa. Confira a origem antes de abrir pela pasta.” / “Warning: downloads
include program files. Check their origin before opening them from their
folder.” Other `aria-describedby` references survive activation and cleanup.
The native panel still supplies the filename, state/error and safe actions.
All original Open/Always Open guards, Show in folder and Delete remain intact.
No new picker, parallel list, generic monkeypatch, telemetry or reputation API.

[Before light](screenshots/ux3c/before-light.png),
[after light](screenshots/ux3c/after-light.png),
[before dark](screenshots/ux3c/before-dark.png),
[after dark](screenshots/ux3c/after-dark.png),
[active light](screenshots/ux3c/progress-light.png),
[active dark](screenshots/ux3c/progress-dark.png),
[native severe precedence](screenshots/ux3c/native-severe-priority.png),
[narrow window](screenshots/ux3c/narrow-warning.png),
[English](screenshots/ux3c/after-en-light.png).
The [verification inventory](screenshots/ux3c/verification.json) identifies the
exact base, package, native/Shell source matches, commands, retained failed
attempts and limits. Before uses an untouched copy of the supplied UX3B package.
After uses an actual incremental Track B rebuild from a task-owned source and
object/toolchain copy; **no `dev_sync.py` rewrite** supplies engine hunks.
The assembler was used read-only to compare packaged source entries.

The render–critique pass inspected both themes and the active notification:
the small native triangle is distinct, the original toolbar/control spacing
stays intact, and no content or native security indicator is occluded. Native
keyboard navigation reaches the button after any address-bar page actions;
Enter opens the native panel and focus uses the native badge-stack outline.
These main-window captures do not contain native popup-widget pixels. The
fixture downloads contain inert text, never executed; explicit native
attention-state inputs test precedence without inventing a reputation backend.
Manual Orca, physical KDE/GTK forced colours, hardware scaling and frame times
remain pending. Local implementation/testing does not close UX3 or constitute
publication, remote CI, independent review or human approval.


### Initial candidate verification (before parent correction)

The first UX3C full integration attempt ran 227 tests (13 existing skips), with
one Vault creation failure and three dependent errors. The inline diagnostic
reported the protection step and “Algo deu errado. Nada foi alterado.” All nine
UX3C tests passed in that run. The isolated nine-test Vault module then passed
on the same package, without changes to its code, assertions or 90 s deadline.
Cause remains **UNKNOWN**, consistent with the supplied prior symptom but not
established as the same root cause. Neither this slice nor the repeat is a
Vault fix. The [inventory](screenshots/ux3c/verification.json) retains failed
attempts and records the bounded full-repeat result separately.

The single bounded repeat also ran all 227 tests (13 existing skips) and failed at
the same Vault create step, again with three dependent errors. The full
integration gate is **BLOCKED**, even though the isolated Vault module and all
nine UX3C tests in both locales pass. Both failed full logs are committed beside
the inventory. No additional full-suite retry was used to obtain green, and no
Vault/protection/pixel assertion, deadline or skip was changed.


### Parent correction: first profile-store initialization

The parent captured the original exception in a disposable profile while
running the test prefix: `SelectableProfileService.#setDBPref` attempted to use
a null connection, about 2.5 ms into `createProtected`, before encryption.
The 90 s observation was the UI test's wait for recovery, not a demonstrated
cryptography timeout. The earlier uninstrumented failures retain their original
UNKNOWN classification; their identical UI text alone does not establish cause.

A short real-Gecko regression forces the same interleaving: pause
`initProfilesData` after preparing the first store, then read the identity.
Normal `init(false)` sees an empty database, resets it and leaves the first
writer without a connection. This reproduced the same exception without a full
suite. The Shell now coordinates store preparation for profile mutations,
manager/current-page entry points and routing preference writes. Earlier normal
initialization finishes first; new readers await the shared setup. The promise
is cleared on success and failure. This coordinates Shell callers; it does not
replace the engine service or claim to repair every native caller.

Regressions use the real service and SQLite database, with controlled scheduling
at public method boundaries: identity reads during first profile creation,
identity reads during the first routing write, concurrent routing/profile
writers and retry after a preparation error. No cryptographic method, profile
availability gate, timeout, state assertion or existing skip changes.
The independent review found the Routing caller outside the first version of
the coordinator; a focused RED/GREEN case confirmed and corrected that gap.

The [parent release verification](screenshots/ux3c/release-verification.json)
records the final package, source/test hashes, retained diagnostic failures,
review scope and current test gates separately from the initial candidate
inventory above. Publication and exact-SHA CI remain post-commit gates.


The parent final real-package run passed **231 integration tests (13 skips)**,
including all four store-initialization regressions and the full Vault UI flow.
The final downloads fixture additionally identifies the exact newly requested
private Chrome window by browsing-context ID, rather than the first new tab
handle: a controlled concurrent public-tab reproduction showed that the latter
can select a public window. It verifies `private=true` explicitly and retains
the list/badge assertions. All nine cases passed in both locales after this
fixture strengthening; the full-run fixture snapshot is retained separately.
The original English failure had no window-identity trace and remains recorded
without attributing a production privacy defect. No product source changed for
this test correction. Final local checks also passed 600 unit tests (1 skip),
15 opt-in engine tests including live phishing blocking, all six security scans
and 256 contrast combinations. The release report records their exact source,
package and harness versions; publication/remote CI remain separate gates.

## UX3D: explicit native layout presets (2026-10-29)

Base: `419f5ec99137d601a885d66cbaab3780e27908e0`. Settings adds a labelled
native radio group with three immediate choices and their consequences. It
reuses Shell `.card`, `.stack`, `.check`, hints, focus and error styles. No new
Horizon CSS, token, asset, shortcut or native patch is needed. The problem is
switching tab organisation without hiding browser controls. The organisation
and focus ideas in the approved references are adapted to Gecko's own tab
strip and sidebar; no proprietary code or distinctive third-party layout is
copied.

| Choice | Gecko159 profile configuration | Actual window state |
|---|---|---|
| Lateral | `sidebar.verticalTabs=true`, `sidebar.visibility=always-show` | Visible, expanded launcher; hover mode off |
| Abas no topo / Tabs on top | `sidebar.verticalTabs=false`, `sidebar.visibility=hide-on-close` | Native horizontal tab strip |
| Foco / Focus | `sidebar.verticalTabs=true`, `sidebar.visibility=expand-on-hover` | Visible compact native launcher with hover expansion enabled |
| Personalizado / Custom | Any other arrangement | No preset claimed or forced |

`SidebarManager` normalizes orientation-exclusive visibility values; the bridge
sets orientation before the explicit visibility. `sidebar.expandOnHover` is
the native customizer's feature gate, not the runtime expansion state, and is
preserved. Position, dimensions, tools, bookmarks, density, themes, title
settings, tab/group data and all security/AI policies are outside the writer's
allowlist. The native service can update its own related state when switching
orientation; the Shell has no generic preference-writing API.

`NulavioLayout` writes only on an explicit choice, serializes concurrent
choices, checks the native feature and managed prefs before writing, and
applies launcher expansion to the profile's open browser windows. It preserves
an open assistant panel; opening the assistant does not collapse the list
(D-UX22). Native profile prefs retain orientation/visibility. Gecko session
restore retains per-window expansion and dimensions, with `sidebar.backupState`
as fallback. No parallel preset-name pref, startup writer, default change or
migration pretends to supply that persistence. Independent profiles retain
their own choices. Native controls can subsequently customize each window.

The read API derives the selection from native prefs, actual tab orientation,
launcher state and the hover attribute. Native toolbar pinning in Foco disables
hover, so the window becomes Custom; transient hover expansion remains Foco.
The native toolbar keyboard path can expand/pin the list, and the compact tab
strip retains native keyboard navigation. No new shortcut is added: D-UX23
remains for UX6 after KDE/GNOME/Orca auditing.

Preference observers and narrowly scoped mutation observers update each
Settings document. The experiment resolves the calling window, never the most
recent window. Unsubscribe/window unload and page hide remove observers;
restoring a cached page reconnects and rereads. Late reads cannot override a
new choice or repaint a departed page. Loading and failures have inline text,
unavailable/managed controls are disabled, and a failed read offers Retry.
An interrupted transition can have applied native changes, so its error does
not claim a rollback; the page rereads actual state.

D-UX2 is still the approved direction: Lateral for **new** profiles with a
first-run choice. Safe initial adoption/migration/onboarding is the next slice;
UX3D deliberately leaves Gecko159's horizontal default untouched. UX3 remains
open, as do D-UX13, D-UX17, D-UX23 and the other excluded personalisation work.

The [verification inventory](screenshots/ux3d/verification.json) records the
real rebuild, exact packaged/source bytes, locales, captures, full-suite
results, retained failed attempts and fixture corrections. Real security owners
are reused for ordinary/private/temporary/protected and Guard states. The
agent composition uses a real registry and the original explicitly synthetic
live-PID raw marker, not a new raw-backend claim. Existing Bridge tests cover
the actual handover separately. The band, native trust/address/navigation
controls and fullscreen line retain their existing assertions and ownership.
Headless checks do not establish physical KDE/GTK rendering, Orca speech,
hardware scaling, frame times, publication, remote CI or human approval.

The final real package is 159.0, package BuildID `20261029192933`, runtime
BuildID `20261029192930`: 98 Shell/branding entries match source, and all three
sidebar plus five downloads native entries match the immutable parent.
Local gates passed: 601 unit tests (1 skip), 241 integration tests (13 skips),
10 UX3D cases per locale, 256 unchanged contrast pairs and all four generated
outputs. The inventory preserves the exact full-run harness and separately
records the two new test-only fixture strengthenings rerun in both locales;
no production bytes changed after that full run.

A [real same-profile upgrade](screenshots/ux3d/upgrade-verification.json) starts
with an untouched copy of the parent package, saves a native collapsed/custom
arrangement and unrelated adjustments, then reopens that artificial profile
with the final build. All sampled preferences and window expansion/visibility
are unchanged; the new Settings API is live and correctly shows Custom.

Rendered Settings text has a 6.615:1 minimum (6.62:1 rounded) in the two themes. The actual
Gecko159 accessibility fixture uses `ui.useAccessibilityTheme` with restart;
`ui.prefersContrast` is not a native contrast control. All three chrome media
queries (motion, transparency and contrast) are verified. The Shell document's
reduced-transparency query remains false under the engine's fingerprinting
protection; no protection is disabled to change that result. Its surfaces
remain solid. The [render review](screenshots/ux3d/render-review.json) separates
native and content measurements, visual critique and pending desktop checks.

[Parent release verification](screenshots/ux3d/release-verification.json)
records the integrated `main` rebuild (`1165765b7c2564602ce800ccf838dc9d413619d0`,
package BuildID `20261029205320`, `browser/omni.ja` byte-identical to the child
final build across all 98 Shell/branding entries and all eight native entries):
241 integration tests (13 skips), 601 unit tests (1 skip), 10 UX3D cases per
locale, 15 opt-in engine tests including live phishing blocking, all six
security scans, 256 contrast pairs, 12 canonical release captures and an
independent static review (0 P1, 0 P2, 4 P3 deferred). Publication and
exact-SHA remote CI remain separate post-commit gates.

## UX3E: Lateral for new profiles and the first-run choice (2026-11-02)

D-UX2 rolled out without touching existing profiles.

**Who is adopted.** At Shell startup, `NulavioLayout.adoptInitialLayout()` runs once per profile (`nulavio.layout.adoptionVersion`). It runs before the privacy seeding marks the profile as used. It treats the profile as existing, and changes nothing, when any of these signals predates this start:
- the privacy seed (`nulavio.privacy.seeded`);
- a user value for `sidebar.verticalTabs`, `sidebar.backupState` or `sidebar.new-sidebar.has-used`, or a `sidebar.visibility` other than the engine's own normalisation;
- `nulavio-guard.json`, `xulstore.json` or `sessionstore.jsonlz4`;
- `times.json` `firstUse`;
- `browser.migration.version` or `sidebar.*` in `prefs.js`/`user.js`.

File checks compare with the time this process locked the profile, so files written during the first start do not count.

**What it writes.** On a genuinely new profile it writes `sidebar.verticalTabs = true` and `sidebar.visibility = "always-show"`. It waits until both tab-strip areas are registered, so the first switch back to horizontal tabs works, and then expands the launcher natively. Locked prefs or a disabled sidebar revamp mean no adoption. If Lateral can no longer be written when the commit runs, the choice is not offered either, so the card never claims a start that did not happen. Only those two native prefs and the two `nulavio.layout.*` markers are ever written; a unit test pins that list.

**The choice.** The first new tab shows "Escolha como organizar as abas" (en: "Choose how tabs are arranged"):
- the three presets apply live, through the same serialised queue as Settings, and stay in sync with Settings and the native sidebar controls;
- "Manter Lateral" / "Manter Abas no topo" / "Manter Foco" closes it (`dismissChoice()`), and so does choosing in Settings;
- it is never shown in private windows, temporary profiles or Áreas de IA, or when the layout is locked or unavailable;
- keyboard focus stays on the radio being previewed and returns to the search field when the card closes.

**UX3D follow-ups.**
- **Event registration.** Settings and the new tab register `onChanged` defensively; a failure shows Retry instead of a dead page.
- **Tabs moved between windows.** The API resolves the caller's live `<browser>`, and subscriptions follow `SwapDocShells`. A tab moved to another window reads, applies and listens to its new window.

**Tests.**
- **Real upgrade.** `test_layout_presets` upgrades a profile created by the 5a98bd7 build (`NULAVIO_REFERENCE_ENGINE`; a missing binary fails the test, and only an unset variable falls back to a persisted-prefs fixture). The profile keeps "Abas no topo" and no prompt.
- **Customised profile.** A pre-existing customised profile keeps Personalizado.
- **First run.** The choice is covered by keyboard, sync, persistence across restart and 200 % reflow tests, in pt-BR and en-US.

Not covered by a deterministic test: the race in which Lateral becomes unwritable between adoption and commit. Physical KDE/GTK, Orca and hardware scaling checks remain manual, as in earlier slices.

### UX3E QA follow-up (2026-11-02)

The functional QA of build `20261102120448` found 1 high, 3 medium and 11 low issues (verdict "not fit"). Fixed on this branch:

- **A-1, the queue.** Closing another window up to ~200 ms after a choice left Settings or the card on "Aplicando layout…" and every later choice queued behind it. Each window step now ends when it finishes, when its window unloads, or after 4 s (`WINDOW_STEP_TIMEOUT_MS`); a window that goes away is left out, and the whole apply has a 20 s deadline after which it writes nothing. The first-run expansion uses the same bound.
- **M-1, policies.** Any enterprise `Preferences` policy on a `sidebar.*` pref, in any Status (`default`, `user`, `clear` or locked), now means no adoption and no card, on every run. A policy that is not locked still lets the person choose in Settings.
- **M-2, the first contact.** The session's first window, on an untouched start, shows the Shell's new tab with the card, and the engine's "Your new tab has changed" notice no longer covers it: the Shell records, for its own id only, the confirmation the notice's "Keep changes" button writes. This is the functional part of UX3F A3, taken unchanged so that branch rebases without a second copy. While the choice is pending, Settings > Layout also offers "Manter …", so it never stays pending out of reach.
- **M-3, Foco by keyboard.** Expanding Foco with the sidebar button (the route its hint gives) stays Foco; natively the button pins the launcher open and pauses hover until pressed again (WCAG 2.1.1).
- **Lows.** B-2: outside Lateral the card no longer claims "you can keep this layout" about Lateral. B-3: a locked `choicePending` marker never shows a card that cannot close. B-7: "Manter …" stays focusable while a preset applies, so Tab follows the visual order. B-8: a keyboard change applies once the person pauses (500 ms), radios and checkboxes get a 3 px focus ring. B-9: the hints use the engine's own terms ("Abas na vertical/horizontal") and the link names "Configurações do Nulavio".

Recorded, not changed here:
- **B-1** (`this._openPopups is undefined` in the console on adopted profiles): the engine's own `sidebar.visibility` observer runs before the first window's sidebar has started. Avoiding it means committing Lateral after the first paint (a visible horizontal-to-vertical switch) or patching the engine; no visible effect was observed.
- **B-11** (card below the fold at 150 %): closed in UX6 (2026-11-04). On short viewports the card also tightens its gaps and padding, and `test_layout_presets` measures "Manter …" inside the first screen at 150 % on 1280 x 800 and 1366 x 768.
- **B-4, B-5, B-6** (product decisions): a profile returns to Lateral when an admin lock written after the first run is removed; adoption is evaluated by two callers (harmless once the marker is written); "Abas no topo" keeps the collapsed launcher visible.
- **B-10, B-12** (native sidebar panel and its "Manage … settings" link), **B-13** (address-bar placeholder on about:home, which the first window no longer shows on a fresh start) and **B-14** (`platform.ini` carries the app BuildID in a repack) are outside the Shell.
- Whether "Lateral" needs another English name is open.

## UX3F: visual review against Zen, and polish (2026-11-02)

Input: the visual QA of build 20261102120448 (Nulavio 159 next to Zen 1.24b), with 18 items (5 high, 8 medium, 5 low). Zen was a reference for patterns only: no Zen asset, icon, CSS or brand was copied or reused.

| QA item | State | What changed |
|---|---|---|
| A1 identity band | Done | 24 px neutral row on the window surface, subtle bottom edge; outlined identity chip (control edge, medium weight) with the profile colour as a disc; "Perfil padrão" when no profile is registered. Private, temporary, agent and raw rows keep the filled chip and every fill, pattern and seal |
| A2 internal pages | Done, two parts open | `shared/in-content.css` (generated, agent sheet like `sidebar-focus.css`) re-values Nova's violet and tinted neutrals with mint and navy on exact about: URLs; Nulavio artwork replaces the Kit fox (chrome overrides); no "Firefox Suggest" heading (`browser.urlbar.groupLabels.enabled`), Labs pane hidden by default. Open: the Fluent terms themselves, the grey `moz-promo` surface (shadow DOM) |
| A3 one new tab | Mostly done | The session's first window shows the Shell's new tab (so the choice appears at first use), no "Your new tab has changed" notice over it, no bookmarks bar, color-scheme + inline canvas colour; Ctrl+T paints the page at ~137 ms. Open: serving it as an internal about: page. Until then the address bar keeps the "Extensão (Nulavio Shell)" chip, and the engine's initial about:blank frame (~60 ms after Ctrl+T) is white with "Não seguro"; later windows (Ctrl+N) and the Home button still open about:home |
| A4 layout choice | Done | Three option cards with 160 x 96 token-drawn miniatures, plain-language lines, accent edge + tint when selected, hidden live status, compact hero; CTA ends <= 600 px at 1280 x 800 |
| A5 vertical tabs | Done | 40 px step; 3 x 20 route mark on the inner edge (outside the tile when collapsed); 224 px Lateral on adoption; label fade; the curve and collapse time in Horizon (patch 0008 until Firefox 159) |
| M1 sidebar button | Done | Accent icon on accent tint |
| M2 address bar | Partly | Accent ring + elevation 1 when focused; radius 10. The rest edge stays at the control colour (3.5:1): the subtle edge suggested by the QA fails WCAG 1.4.11, which `test_horizon` asserts |
| M3 radius scale | Partly | 6 / 10 / 14; address bar and panels at 10. Open: the content area still gains a radius only while the sidebar animates (engine clip) |
| M4 sidebar motion | Done | `cubic-bezier(0.2, 0, 0, 1)`, 220 ms expand / 160 ms collapse; reduced motion: none |
| M5 menus and panels | Done (chrome side) | Raised surface, primary text, subtle edges, shared hover. Native GTK menus on Linux may still draw their own colours; radii and shadows need a compositor to check |
| M6 dark surfaces | Done | Toolbox #060C14, toolbar #0F1C2A, field #15293A, selected tab #1E4252 |
| M7 pinned tab | Done | 40 px tiles from the start edge |
| M8 placeholder | Done | `text.muted`, >= 4.5:1 |
| B1 titles | Partly | English title "New Tab". The band still names system pages ("Nulavio · Nova aba · página do sistema"): it is the trusted-surface label and stays |
| B2 sidebar logo | Done | Monochrome route-mark glyph in the chrome icon colours |
| B3 result pills | Open | Nova draws the pill without a border; a rule on `border-color` had no effect and was removed |
| B4 vertical mark motion | Done | `nulavio-route-in-v` (scaleY) |
| B5 main menu icons | Done | The engine's own 16 px glyphs, context-fill |

**Kept (QA section 7).** The selected result row (tint + 2 px ring, 11:1), toolbar icons (>= 8.9:1), the 2 px focus ring, the tab hover preview and the explicit security UI are unchanged.

### Polish

- **Icons.** One family: the engine's own 16 px glyphs, drawn with `-moz-context-properties` in the chrome icon colour, now also in the main menu; the assistant tool in the sidebar is a monochrome route mark instead of the brand mint; promo cards use Nulavio artwork.
- **Colour.** Accent, focus, links and canvas are the same teal and navy in the window, Settings, the add-ons manager and about:home; the dark theme has four distinct surface steps.
- **Spacing.** A 4 px rhythm: 24 px band, 40 px tab step, 40 px pinned tiles, card padding 12–24.
- **Type.** The band uses the 12 px step at medium weight; the choice card uses the section title (20/600) in sentence case instead of small caps.
- **Corners and shadows.** Three radii (6 / 10 / 14); only the focused address bar gains elevation 1.
- **Motion.** Motion tokens only: 120 ms hover transitions, label fades, 220/160 ms sidebar on the standard curve, scaleY route mark; all off under reduced motion. The security band and seals never animate (unchanged).

### Mechanisms and security notes

- **No new permission, CSP unchanged.** The manifest only changes the sidebar icon path. The new tab's inline `<style>` is allowed by the extension CSP, which restricts scripts.
- **The "new tab changed" notice.** At startup the Shell records, for its own id only, the confirmation that the notice's "Keep changes" button writes (`ExtensionSettingsStore`, type `newTabNotification`); the notice re-checks it before opening. Other add-ons that take over the new tab still get it. A first draft used the distribution-add-on pref `extensions.installedDistroAddon.shell@nulavio.net`; review found that `XPIInstall.installDistributionAddon` also reads that pref's effective (default) value and would skip a distribution XPI with that id, and that it silences the home-page and hidden-tabs notices too, so it was replaced by this narrower record before release.
- **Start page.** Only the session's first window, and only an untouched start: one tab, no history, the home-page pref at its default, the Shell page still the new tab, not private. It loads with the Shell's own principal (not the system principal). Later windows, session restore, links from other apps and a chosen home page are untouched; the Home button still opens about:home. Applying it to every new window raced the native sidebar (a collapse right after switching to Lateral was undone in `test_layout_presets`), so it was narrowed to the first window.
- **Security indicators.** No identity or security code was changed. The new tab is still identified as the Shell extension page; the transient "Não seguro" on the engine's initial about:blank is unchanged. No web page or third-party extension page loses or changes an indicator.
- **If the person restores the engine's new tab** (another new-tab page or add-on), the first-run card is no longer reachable from Ctrl+T; Settings → Layout still offers the same three presets. Left to the UX3E round (functional QA M-2).
- **`in-content.css`** uses literal values and no `--nv-*` names, scoped by `@-moz-document` to exact about: prefixes, so web pages never see it (no fingerprinting surface); it steps aside for forced colours, a contrast preference, installed themes and `nulavio.horizon.enabled=false`.
- **Patch 0008** is the minimum for the motion fix: two prefs read by `browser-sidebar.js` (curve, validated with a fallback, and collapse duration). Reduced motion keeps the engine's no-animation path. Firefox 160 replaced that code with a view transition timed in CSS; since then Horizon re-values its variables (`--motion-dur-sidebar-enter`, `-exit`, `--motion-ease-emphasized`) and the patch is gone.
- **Not touched:** Vault, AI, Guard and downloads beyond colours. The UX3E functional QA findings (A-1 "Aplicando layout…" hang, M-1 policy) are left to the UX3E round.

Captures (outside the repository, 1280 x 800, light and dark, Xvfb without a compositor; Marionette's remote-control stripes removed only for the capture): `before-*` from 8880bdd (BuildID 20261102120448) and `after-*` from the UX3F build (BuildID 20261102153026, commit 02c691f).

**Verification** on a real incremental Track B 159.0 build (BuildID 20261102153026), installed as an application copy (tarball + `make_distribution.py` + `make_tools.py`), each suite run alone:

| Check | Result |
|---|---|
| Integration | 246 run, 13 skips, 1 failure: `test_ai_bridge` 13, which fails identically on the 8880bdd build in this run's environment (the test looks for the disposable workspace under the test process's TMPDIR, set to `/var/tmp` here, while the bridge, started with only PATH and HOME, creates it under `/tmp`). No new failure |
| `test_layout_presets` | 15/15 in pt-BR and 15/15 in en-US (14 UX3E cases + the UX3F first-window case) |
| Unit | 607 (3 skips) |
| Contrast pairs | 266 |
| Generated tokens | current (5 outputs) |
| ruff | clean |
| Security scans | all six |

**Rebased onto the UX3E QA fixes (2026-11-02).** The first window and the "new tab changed" notice now come from the base (UX3E QA M-2, the version this review narrowed), so UX3F keeps no second copy of that logic and drops the distribution-add-on pref in its own history too. Real incremental 159.0 build of the rebased branch (BuildID 20261102172613), installed the same way, each suite alone: 251 integration run (13 skips) with three failures: `test_ai_bridge` 13 as above, `test_temporary` 01 intermittent under full-suite load (passes alone), and the UX3E card-text check, which looked for the word "Lateral" that UX3F rewrites (the test now compares with the messages); then `test_layout_presets` 20/20 in pt-BR and en-US, 608 unit (3 skips), 266 contrast pairs, current tokens, ruff and six scans. New `after-*` captures: startup, new tab, window and sidebar, light and dark; at 150 % the card's main action still ends below the first screen (B-11 stays open).

A first integration attempt used a bare tarball without the distribution and tools; its AI failures were environmental and are not counted. A second, on the intermediate build 1300efa, found intended-value test updates and one real regression (start-page replacement in every new window), fixed in 02c691f.

## UX5: the assistant's parts (2026-11-03)

| Part | Class | Rule |
|---|---|---|
| Context item | `.assistant__chip` in `.assistant__chips` | One per kind: a page (`data-kind="page"`) and a selection (`data-kind="selection"`). Each names its tab ("só da aba “title” · host"), its size in characters, and the frame's site when a selection came from another one. It says when the item was cut ("Página longa: vão só os primeiros 60.000", "pode estar cortada"). Its remove control is named after it. It leaves after Send, on removal, or when its tab goes elsewhere (`.assistant__drift`, also announced) |
| Send line | `#send-line` (`.hint--on`) | Above Send: the recipient (host:port), the model and the whole size, Nulavio's instructions included. In Task mode it says the size is known only afterwards. Above 200 000 characters a warning callout replaces Send's action with two choices |
| Conversation | `.assistant__turns` / `.assistant__turn` | Earlier turns, oldest first, on `bg.sunken`. Each shows the question, the answer (safe Markdown), its size and recipient, and "Copiar". The latest answer stays under "Resposta". The line above the list says what goes with the next question, and "Deixar a página de fora" and "Começar conversa nova" are next to it |
| Streaming answer | `.assistant__answer` + `.assistant__cursor` | Text painted once per frame in a region that is not live, with a still block cursor (no animation). Markdown is rendered only when the answer is whole. A stopped or failed answer keeps what came, under a warning callout that says why |
| Permission card | `.callout.assistant__approval` | The risk tier's callout with its icon. It names who asks, what, the risk in words, the site, where the agent acts and the expiry time. "Negar" is the filled primary, first and focused. "Permitir uma vez" is secondary and "Permitir até esta tarefa terminar" quiet; both are disarmed for ~1 s. The icon sits beside the text at every width |
| Timeline | `.assistant__steps` | Each step by its tool's name in the person's language: em andamento, feito, negado, não deu certo, interrompido. Negado and não deu certo use `status.criticalText` |
| Sources | `.assistant__sources` / `.assistant__source-quote` | "Trecho citado da página “title” · host", the heading above it, and the passage as a quote with an `accent.default` edge. "Mostrar a aba" only selects that tab while it shows that address |
| Band: task acting | `.nv-band-activity` | Agent ink, solid (not the agent's double line): "Assistente agindo na Área de IA · N ações", or "aguardando você". Two quiet controls that only tighten: "Parar tarefa", "Pausar assistente". The full-screen line has a solid segment |
| Band: agent connected | `.nv-band-connected` | A seal with a double agent-ink edge: "Agente conectado: nome" (or how many); it opens Settings → IA e automação. Not in private windows, nor in the window that agent drives |

Gallery: the "Conversa e execuções do assistente" card shows a selection item, the send line, a turn, the permission card, the timeline and a source, at 1280 and 390 px in both themes.

## Calmaria: identity and state glyphs (2026-11-04)

From the icons-and-chrome direction workflow (three directions, two judges, one synthesis; the
spec and its measurements are kept with the session evidence). Two grammars, no silhouette in both:

- **Solid = who you are.** Each profile is a solid one-tone glyph on a soft tile in its colour:
  `modules/NulavioAvatars.sys.mjs` is the one source (24-unit grid, live area 3.5–20.5, one path,
  evenodd, parts and gaps ≥ 1.75 units), drawn inline by Shell pages, by the band and on the toolbar
  canvas. The ids stay the engine's (`NulavioProfiles.AVATARS`): storage is unchanged and
  about:profiles keeps the engine's drawings. A name with no glyph shows its first letter or digit
  (`Intl.Segmenter`, symbols and emoji skipped), and the person glyph when there is none; never "?",
  which means "unknown".
- **Outline = what is happening.** State glyphs are outline icons (1.5 px at 16 px, 1.75 px at 24 px),
  followed by words: the band draws them as SVG masks (`shared/icons/*.svg`), Shell pages as masks
  (`shared/icon-*.svg`). No Unicode pseudo-icons in messages or in CSS `content` (◇ ⌑ ◷ ◈ ▤ ⯃ ⚠ ■ Ⅱ ✓ ? ● ▸
  are gone): they changed with the desktop font and were read aloud.
- **Tokens.** `color.{light,dark}.identityTile.<c>` and `identityGlyph.<c>` (OKLCH from the six
  primitives; sand moved away from the Guard amber), glyph on tile ≥ 6.3:1, checked by
  `scripts/brand/contrast.py`. The tile against the surface is 1.2–1.9:1 on purpose: it is a soft
  fill, not a boundary; forced colours give it a 1 px edge.
- **Chrome.** The neutral band identity is a ghost button (no frame, no ring), "Sem senha" is the one
  term for a profile without a password, and a protected profile reads "Protegido" with
  "Protegido · desbloqueado" as its accessible name. Alert rows keep every strong cue (fill, pattern,
  frame, words, fixed place, no motion). The toolbar button is monochrome; the open sidebar keeps its
  accent glyph without a tinted block; the address bar takes the 14 px radius.
- **Choosing an icon.** Settings and the create sheet choose the icon on a grid of glyph tiles
  (`avatarPicker` in `lib/ui.js`, a radio group, seven to a row). The others stay quiet on the sunken
  surface; the chosen one wears the colour chosen next to it (`tintAvatars`, updated before saving)
  and a ring, with its name as the radio's label. Forced colours show the radio and a framed tile.

## UX6: safe personalisation (2026-11-04)

Everything a person can change about Nulavio's look and keys, and where routing sends links from
other apps, without lowering a protection.

- **One list.** `browser/shell/shared/options.json` declares every option once (id, kind, the pref it
  writes, values, default, writer, where its control is, marked `data-option`).
  `tests/unit/test_personalisation.py` proves from it that no option writes a guarded pref (the
  Guard's lists, the forbidden map, guard-rules.json, the "Sensitive sites" prefs, every non-UI
  baseline pref, and prefixes for privacy, network, security, search, passwords, extensions,
  updates, telemetry, the system's `ui.*` LookAndFeel and Nulavio's own AI/Guard/Vault/routing
  prefs), that the check fails closed, and pins every privileged pref writer by its first argument.
  `test_appearance` walks every value of every option in the real build and sees no other pref or
  permission change.
- **Aparência** (Settings, "Este perfil"), written by `NulavioPersonalise.sys.mjs` through
  `nulavioPersonalise`:
  - *Densidade da janela*: the engine's Automático (no user value), Normal, Compacto, Toque.
  - *Cor de destaque*: Menta (default) or Azul. A token variant (`$extensions["nulavio.variants"]`):
    the generator re-emits every token whose value changes, for Shell pages as
    `:root[data-accent="blue"]` and for the window and about: pages behind
    `-moz-pref("nulavio.appearance.accent", "blue")`. Azul keeps OKLab 0.106 from every identity,
    status and private colour (mint: 0.082). Focus, the "acting" seal, the private chrome, status,
    identity, group, fullscreen, band and download tokens never follow a variant (the generator
    refuses one that reaches them), and the private-browsing page keeps its colours.
  - *Mais contraste*: text 7:1 or more and borders 3:1 or more on every surface, solid frost, on
    Nulavio's own surfaces only. It never writes the system's LookAndFeel prefs, which websites
    see; when the system already asks for high contrast or forces colours, the switch shows that
    and why.
  - *Fundo suave na nova aba* (off by default, D-UX10): a gradient from the canvas to the accent's
    tint with frosted cards, never in a private window; *Reduzir transparência* makes the cards
    solid, and says why when it cannot change anything (nothing transparent, or already solid by
    the system or by more contrast).
  - Every contrast pair passes in every combination (theme × accent × contrast: 1224 rows).
  - Shell pages load `lib/appearance.js` first; it only sets `data-accent`, `data-contrast`,
    `data-ambience` and `data-transparency` on `<html>`.
- **Atalhos** (D-UX23). Ctrl+Alt+F toggles Foco and returns to the preset it came from; Ctrl+Alt+B
  opens the profile menu with the same "Bloquear agora" confirmation as its button (Cancel focused).
  Both are free in Firefox 159's Linux chrome, the local Plasma and GNOME keybindings and Orca, and
  neither is a page access-key combination; Ctrl+Alt+L stays out (screen lock on older KDE and
  Ubuntu). Settings → Atalhos lists the four commands with their current keys, "Mudar…" opens the
  engine's extension shortcuts view (which checks clashes; the Shell's card is there as "Nulavio
  Shell"), "Restaurar" puts the default back, and a link opens about:keyboard. The menu hint and the
  new tab's "Atalhos e ajuda" read the keys from `commands.getAll()`.
- **Ações rápidas** after ">": "Abrir as configurações do Nulavio" and "Ligar ou desligar o layout
  Foco", next to the assistant's; none in an AI Workspace, none that locks, unlocks, resumes, grants
  or turns anything off.
- **Destino padrão** for links from other apps with no rule (ADR 0003, step 4 for M4a only): the last
  profile used (default) or a chosen profile, through the M4a hand-off (unlock page for a locked
  profile, warning page for a missing one), announced in the target's band.


## UX7: motion and performance budget (2026-11-04)

Every movement Nulavio adds comes from the motion tokens, and nothing it adds moves under reduced
motion. Security cues, warnings and critical consent never move.

| Element | What moves | Tokens | Never moves | Reduced motion |
|---|---|---|---|---|
| Sidebar launcher | width | expand 220 / collapse 160 ms, standard curve (Horizon on the engine's view transition; patch 0008 until Firefox 159); Foco's expand-on-hover 220 ms after the engine's 200 ms intent delay | — | The engine skips it |
| Tab labels, route mark, hover | opacity, scale, colour | fade, base, fast | — | Off |
| Plain dialogs and the profile create sheet | opening only: opacity and `translate: 0 8px → 0`; the backdrop's opacity | base, enter | `.dialog--critical`, `.dialog--danger` ("Bloquear agora", deletions) | Instant |
| Toasts | appearing only: opacity and `translate: 0 4px → 0` | fast, enter | warn and error levels, inline results | Instant |
| The profile's arrival | the identity chip in the new tab's "Você está em" line, once the page paints | base, enter | the band, state badges, the temporary chip | Off |
| Progress spinner | rotation | spin 900 ms, linear | — | Static |
| Band, fullscreen line, security badges, warning and critical surfaces | nothing, ever | `security.duration` 0 | — | — |

Closing a sheet, removing a chip and hiding a toast are instant, so focus never waits on an
animation. Under reduced motion the guard in `shared/accessibility.css` sets every duration to 0 but
keeps delays, so what appears after a delay (the new tab's fallback, list placeholders, "still
loading") still appears. `test_motion` 01–05 and `tests/unit/test_motion_sheet.py` check both.

### Budget

`scripts/research/frame_scene.py` measures it on a real Track B build against the previous one:
headful on a private Xvfb (1920×1080, software WebRender), a fresh profile per run, the two builds
alternating, frame intervals from the compositor's frame-time recording (the dialog from
requestAnimationFrame in the page). Xvfb timings are a regression gate, not a measure of real
hardware; frame times in a visible KDE or GNOME window stay with the maintainer.

Two measurements, 5 runs × 10 samples per scene on each build, run on 2026-11-04 (BuildID
20261104151506, the UX6/UX7 build at `e95fba6`, against 20261104061818; the fixes after `e95fba6`
change no measured scene):

- [perf.json](screenshots/ux7/perf.json): both builds **without** their distribution, so no
  extension is installed. This is what Nulavio's own code costs, and what the budget is read on.
- [perf-with-ublock.json](screenshots/ux7/perf-with-ublock.json): both builds as shipped, with uBlock
  Origin installed by the distribution. In a fresh profile uBlock downloads and compiles its lists for
  the first minutes, and that work lands on the new tab and the idle minute of both builds alike.

| Gate | Budget | This build (no extensions) | Previous build | As shipped (uBlock), this / previous | Result |
|---|---|---|---|---|---|
| Sidebar collapse, frame interval | p95 ≤ 20 ms, max ≤ 50 ms | p95 18.4, max 19.7 | 18.4, 20.9 | 19.0, 35.0 / 18.6, 35.1 | Pass |
| Sidebar expand | p95 ≤ 20 ms, max ≤ 50 ms | 18.6, 21.6 | 18.4, 20.8 | 18.5, 21.0 / 18.5, 20.8 | Pass |
| Settings dialog opening (rAF in the page) | p95 ≤ 20 ms, max ≤ 50 ms | 17.4, 17.6 | 17.4, 17.6 | 17.4, 17.6 / 17.4, 17.6 | Pass |
| Tab switch | p95 ≤ 20 ms, max ≤ 50 ms | 18.4, **121.6** | 18.3, 122.6 | 18.2, 122.4 / 18.4, 121.8 | Exception (below) |
| Ctrl+T to the new tab's `nv-painted` | p95 ≤ 150 ms | p50 52, p95 62, max 65 | — (no mark) | p50 57, p95 **251** / — | Pass; exception as shipped (below) |
| Ctrl+T, polled on both builds (5 ms) | compared only | p50 61, p95 69 | p50 57, p95 69 | p50 66, p95 284 / p50 63, p95 217 | — |
| 60 s idle on a page with the band | 0 chrome reflows, 0 frames constructed | 0 and 0 in every run | 0 and 0 | 0 in 4 of 5 runs, **380 and 7** in one / 372 and 7 in one | Pass; exception as shipped (below) |
| Against the previous build | flag a median > 10 % worse when the runs do not overlap | none flagged | — | none flagged | Pass |

**Exceptions** (to be accepted by the maintainer):

- *Tab switch, max.* About half the samples on both builds hold one 117–123 ms interval: the window
  waits for the background tab's content before it composites it (the engine's tab switcher with
  software WebRender). No Nulavio motion runs in that scene, the p95 stays at 18 ms, and the previous
  build is the same to the millisecond.
- *As shipped, the new tab's p95 and one idle minute* come from uBlock Origin's first-run work in a
  fresh profile: the medians stay at 57–66 ms, the same samples are slow on the previous build with
  the same distribution, and without extensions every one of these lines passes. A first comparison
  against an extracted package that had no `distribution/` read this as a Nulavio regression;
  `frame_scene.py` now records each build's extensions and refuses to compare builds that differ.

The sidebar scenes measure the curve and durations of patch 0008 (Horizon since Firefox 160) on both builds, so they compare like
with like. Re-run with:

```sh
env -u WAYLAND_DISPLAY xvfb-run -a -s "-screen 0 1920x1080x24" env GDK_BACKEND=x11 MOZ_ENABLE_WAYLAND=0 \
  NULAVIO_TEST_HEADFUL=1 NULAVIO_ENGINE=<build>/nulavio/nulavio \
  python3 -I scripts/research/frame_scene.py --baseline-engine <previous>/nulavio/nulavio --runs 5 --out <dir>
```

For the "no extensions" reading, copy both packages without `distribution/`; for "as shipped", give
both the same `distribution/`.

### Captures

[screenshots/ux7/](screenshots/ux7/matrix.png) holds the window with the first-run new tab, Settings →
Layout, Settings → Aparência, the assistant panel, the look-alike site warning and the Guard review, at
100/125/150 % in both themes on a 1366×768 screen, with reduced motion on (36 shots, 7.4 MB). They
come from the X server's pixels, because WebDriver's own window screenshot drops masked content (the
disclosure chevrons and the narrow Settings rail). The [manifest](screenshots/ux7/manifest.json) holds
each file's sha256 and size, the build and the commit whose Shell was synced onto it.
`scripts/research/ux7_captures.py` takes them again.

## Experience 2026-11: one surface, the stage, hidden chrome, sounds, and the rules

From the experience review of 2026-11 ([references](references/2026-11/README.md), [journeys](journey-2026-11.md), [ADR 0008](../adr/0008-one-settings-page.md), [ADR 0009](../adr/0009-immersive-layout.md), [ADR 0010](../adr/0010-experience-direction.md)). Tokens, type, spacing and components above stay as they are; this section adds what the review decided and how each rule is checked. Parts marked *prototype* are on the prototype branches and not in the shipped theme yet.

### The frame (direction A, prototype)

| Part | Rule | Tokens |
|---|---|---|
| Frame: band, toolbar, tab column, the margin around the page | One tone. No rule line between them; the band's own border appears only when the band is a full row with a state to state | `color.chrome.toolbar` for all four |
| Page | A card inside the frame: margin on the sides that have no chrome, a radius, a thin outline. Never a shadow that reaches the page's own pixels | `space.3` (8 px), `radius.md` (10 px), `color.border.subtle`, `elevation.1` |
| Selected tab | The only raised surface in the frame, with the route mark | as UX3F |
| Accent | One primary action per group of actions, and at most one accent-filled control in the frame. Mint is for the selected state and the primary action, never for a whole surface | `test_experience_rules` (one main action per group) |

### The band is the constant

In every layout, mode and page the band is the one row only the browser draws. What it carries, left to right: the profile and its protection; in the middle, the trusted name of a Nulavio page **or**, when the address bar is out of view, the site (host as the engine displays it, the registrable part emphasised, the connection state in words when it is not secure); the state seals on the right. No mode hides it, shrinks it to nothing or makes it translucent (`test_experience_rules`: no mode hides the band). The registrable domain is never cut: the row grows first, and if that is not enough the toolbar stays.

### The stage (first run)

A stage is a page that owns the window for a sequence the person must finish or dismiss. Today there is one: the first run.

| Rule | Value |
|---|---|
| Window | The band and the page. The toolbar and the tabs are out of view and return to the pointer and the keyboard, as in Imersivo. The band names the stage ("Nulavio · Boas-vindas") |
| Card | One, centred, the same size and place on every step: 64 rem wide at most, 34 rem high. Two panes, 5 to 6: on the left what is asked and, at the bottom, the actions; on the right, on the sunken tone, the choice itself. Below 52 rem of width or 40 rem of height the panes stack (asked, choice, actions), the page scrolls, and the actions stay at the bottom of the window so the main one is never below the fold |
| Parts | Every card has the same three, in reading and keyboard order: `.firstrun__say` (title, at most two sentences), `.firstrun__show` (the choice or the picture), `.firstrun__do` (errors, then the actions). No part cuts its content: `test_firstrun_stage` checks it on every step and in a short window |
| Content | One decision per step. A choice is drawn as the thing itself when it can be: the layouts as miniatures, the band as this window drawn small with the real profile and state, read and never invented. An example (a protected profile's band) is labelled as one and is not read to assistive technology |
| Options | A choice among a few things, each said in a line or two: `.options` of `.option`. A radio card when one is picked and applied by the main action (DNS); a row with its own secondary button when choosing acts at once (password managers). The one in use wears the accent, a ring and a word ("Como está agora", "em uso"), never colour alone. An option that gives a protection up says so in its name |
| Actions | In one place on every step: the bottom of the left pane, the main one first, full width. One primary. "Agora não" and "Decidir depois" are quiet buttons, never links in the text. Nothing changes before the main action, except where the step says the choice applies at once (the layout, a manager's "Usar este") |
| First screen | What the product is in one sentence that points at the band; two exits, "set up" and "use the defaults", and the defaults said in one line under them. A profile that is not the browser's first says "Perfil novo: …" instead of welcoming again |
| Facts | Only what was read and is true now. A fact still arriving is not shown as a warning and not shown as done: it is read again where the sequence ends |
| Progress | "Etapa N de M" centred under the card; its line keeps its height on the steps that have no number |
| Focus | When a step comes after an answer, the keyboard goes to it: to the main action where going on is the likely answer (welcome, layout, default browser, summary), to the title as a reading position (an underline, not a ring) where the step asks to read first (DNS, passwords, the protected profile) |
| Motion | None between steps. The card does not slide, fade or resize |
| Who is never staged | Private windows, temporary profiles, AI Workspaces, any tab other than the first run's. A page the first run opens (the Vault's steps) is an ordinary tab with the address bar |

### Immersive: who decides (ADR 0009)

CSS draws two states; the window decides them. Three attributes on the window's root say what was decided, and nothing else may hide the toolbar:

| Attribute | Meaning |
|---|---|
| `nulavio-immersive` | The mode is drawn: the person turned it on (or the first run's stage asked for it) and nothing below holds it back |
| `nulavio-immersive-off="agent \| popup \| sharing \| page"` | The mode is wanted and the full window is shown anyway, with the first reason that applies |
| `nulavio-immersive-hold="toolbar"`, `"tabs"` or both | A panel or a menu anchored there is open: that part stays shown for its whole life |

A new way to hide chrome goes through the same decision: it adds a reason or a hold, never a selector of its own.

### Motion: chrome that hides (ADR 0009)

Added to the UX7 table. The times come from the motion tokens; `motion.duration.hold` (600 ms) is new.

| Element | What moves | Tokens | Never moves | Reduced motion |
|---|---|---|---|---|
| Toolbar in Imersivo and on the stage | `translate` and `opacity`, over the page; the page never reflows | reveal: `fast`, `enter`; leave: `base`, `exit`, after `hold` | The band, the origin in it, the seals | No transition: shown and hidden at once |
| Tab list in Imersivo | `translate`, over the page | the same | — | The same |
| A prompt, a warning, a device being shared | The chrome is in place **before** the engine anchors anything to it, and stays for as long as it is open | — | — | — |

`tests/unit/test_motion_sheet.py` already enforces the first two columns for every sheet (movement only under `prefers-reduced-motion: no-preference`, times and curves only from tokens); the Immersive prototype failed it until it was brought to these rules.

### Sounds

Nulavio plays no sound today, and none of the browsers studied did. The rules for the first one:

1. **Off unless the system says yes.** A sound is played only through the engine's system event sounds (`nsISound.playEventSound`), which follow the desktop's sound theme and its "event sounds" switch. Nulavio ships no audio file and never opens an audio device itself.
2. **One switch, easy to find**: "Sons do Nulavio" in Acessibilidade of the one settings page, and it is off in a new profile until the maintainer decides otherwise.
3. **Only for something that happened while the person was not looking**, and at most once per event: a download that needs a decision, an agent waiting for consent, a profile that locked itself. Never for a click, a navigation, a success, a tab or a hover.
4. **Never the only cue.** Every sound has its visible state, in words, in the band or the page.
5. **Never for security theatre.** No sound for "secure", none that imitates the system's own alerts for something that is not one.
6. **One module.** `NulavioSound.sys.mjs` is the only file that may play anything (`test_experience_rules`: no sound outside the sound module).

Not verified: nothing here could be heard on the private display. The first sound ships only after it has been heard on a real desktop.

### Rules for whoever changes the interface, person or model

Each rule has a check. A change that breaks a check is not finished; a rule with no check yet says so.

| # | Rule | Check |
|---|---|---|
| 1 | Work from something seen: a capture of the engine before and after, at the same size, in both themes and both languages. Never describe a state that was not captured | Captures in the pull request; reference PNGs updated on purpose |
| 2 | Never weaken a protection and never show a state that was not read. An unknown is said as unknown | `shared/options.json` test (no option writes a protection pref); Shell unit tests; `test_security_moments` |
| 3 | The band is never hidden, and nothing else does its job | `test_experience_rules`, `test_window_band` |
| 4 | Colours, sizes, radii, times and curves come from `docs/brand/tokens.json`. No literal | Token tests in `test_brand_and_docs`; `test_motion_sheet` |
| 5 | Movement only under "no preference"; security cues never move | `test_motion_sheet`, `test_motion` |
| 6 | One primary action per group; the safe action is the primary one in a warning | `test_experience_rules`; component gallery |
| 7 | pt-BR and en-US change together, in the same commit | Locale parity tests; `test_experience_rules` for Fluent |
| 8 | One settings page. A new option is a group in the pane where the person would look for it, never a new page | `test_settings_native` (ADR 0008) |
| 9 | One decision per screen in a sequence; the card and its actions keep their place | `test_firstrun_stage` (the card's rectangle is the same on every step; it caught a 14 px jump in the prototype) |
| 10 | No sound outside `NulavioSound.sys.mjs`, and none by default | `test_experience_rules` |
| 11 | Ideas from other browsers are re-derived, never copied: no file, asset, name or wording. GPL code is never read into the product | Review; `LICENSES.md` when a file is ever taken |
| 12 | A second opinion (a reviewer model, a critique from captures) is a hypothesis: check it on the engine or the source before changing anything, and record what was checked | The "independent review" tables in the ADRs |
