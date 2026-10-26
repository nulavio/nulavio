# Nulavio design system (Horizon)

**One source:** [`docs/brand/tokens.json`](../brand/tokens.json) (W3C Design Tokens format). `scripts/brand/build_tokens.py` generates two files, and CI fails if either is stale:

| Output | For | Colour switching |
|---|---|---|
| `browser/startpage/tokens.css` | Start page, Shell pages, site, mockups | `prefers-color-scheme` + `[data-theme]` |
| `browser/branding/nulavio/content/theme/tokens.css` | The browser window (Horizon) | `light-dark()`, following the engine's colour scheme |

`scripts/brand/contrast.py` checks every declared pair (**55/55 pass**, both themes). `tests/integration/test_horizon.py` re-measures contrast on the rendered window.

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
| `status.secure` | navy.600 | navy.200 | The secure state is **neutral**: no green "safe" |

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

## Component gallery

Firefox's Storybook (`browser/components/storybook`) needs a large npm dependency tree. That is more supply chain than this project accepts for documentation, and the chrome components it documents are upstream. Equivalent, already in the repository:

- `docs/brand/mockups/index.html`: the brand's components and flows as HTML using the tokens (`scripts/brand/render_mockups.py` renders PNGs).
- `scripts/brand/ui_directions.py`: the window slice per direction, with contrast.
- `scripts/research/shell_screenshots.py`: the real window, theme × scale × resolution matrix and timings.

A Shell gallery page (live components inside the built-in add-on) is planned with the Privacy Center, when there are more Shell components than two.
