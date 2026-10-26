# Nulavio Shell: UI architecture

The Nulavio Shell is everything a person sees of Nulavio around and inside the browser window. It keeps the Gecko and Firefox back end (tabs, sessions, sync, extensions, permissions, security UI) and changes how it looks and what Nulavio adds. Track B (the Nulavio build) only; the Track A preview keeps its recolouring `userChrome.css`.

## Layers

| Layer | What | Where | How it reaches the browser |
|---|---|---|---|
| **Window theme: Horizon** | Colours, geometry, densities and the selected-tab mark of the browser window | `browser/branding/nulavio/content/theme/horizon.css` + generated `tokens.css` | Branding jar (`chrome://branding/content/theme/`), loaded last by `browser.xhtml` (**patch 0003**, one `<link>`) |
| **Shell pages** | Nulavio's own pages: new tab, download warning; next: Privacy Center, Providers, onboarding | `browser/shell/` (WebExtension, built in) | Built-in system add-on `shell@nulavio.net`, packaged from the branding directory ([build](../architecture/build.md#nulavio-shell-built-in-add-on)) |
| **Upstream components, re-valued** | Tab strip, toolbar, address bar, panels, sidebar and vertical tabs, `moz-*` widgets, Settings | Firefox source, unmodified | Design tokens set by the window theme |
| **Patches** | Only when the DOM must change. Today: the stylesheet link | `browser/patches/` | `scripts/build/apply_patches.py` |

No React, QML or other framework is added to the chrome. Shell pages are plain HTML, CSS and JS modules. Adding a framework needs an ADR that shows a concrete need.

## How the window theme overrides Firefox without forking it

Firefox 158 defines its look as **design tokens in CSS cascade layers**:

```
tokens-foundation < tokens-browser-theme < tokens-foundation-brand
  < tokens-foundation-nova < tokens-browser-theme-nova < tokens-foundation-brand-nova
  < tokens-prefers-contrast(-nova) < tokens-forced-colors(-nova)
```

(`toolkit/themes/shared/design-system/dist/tokens-shared.css`, `browser/themes/shared/tabbrowser/tab.tokens.css`, `browser/themes/shared/urlbar/urlbar.tokens.css`).

Rules in `horizon.css`, enforced by `tests/unit/test_horizon_theme.py`:

1. **Geometry tokens** (radii) go into `tokens-foundation-brand-nova`, the last brand layer. The accessibility layers declared after it keep winning.
2. **Colours** are assigned only under `@media not ((forced-colors) or (prefers-contrast))` and `:root:not([lwtheme])`. Firefox's default theme on Linux uses GTK colours (`-moz-native-theme` is true). Horizon deliberately replaces them, because it is the Nulavio look.
3. **Unlayered component variables** (`--tab-min-height`, `--urlbar-height`) are re-valued per density (normal, compact, touch), as upstream does.
4. Everything sits inside `@media -moz-pref("nulavio.horizon.enabled")` (default true, `firefox-branding.js`). Setting it to false restores the upstream look, GTK colours included, without a restart.
5. Security UI (trust icon, tracking protection, permissions, remote control, notifications) is never targeted; `test_07` checks it is identical with Horizon on and off.
6. Values come only from `tokens.css`, which `scripts/brand/build_tokens.py` generates from `docs/brand/tokens.json`. The file has no literal colours and no `!important`.

### Themes and settings that win over Horizon

| User state | Result | Verified by |
|---|---|---|
| Default theme ("System theme — auto") | Horizon light or dark, following the desktop | `test_02`, `test_03` |
| Built-in Light / Dark themes (`[theme-in-app]` in 158) | Horizon light / dark | `test_10` |
| Colourful or installed themes (`[lwtheme]`), e.g. Alpenglow | The theme's colours; Horizon keeps its geometry; the mark uses the theme's text colour | `test_10` |
| High-contrast preference (`prefers-contrast`) | Upstream colours | `HorizonHighContrastTest` |
| Forced colours | Upstream colours; mark in `SelectedItem` | same media guard (not simulable here) |
| `nulavio.horizon.enabled = false` | Upstream look, including GTK colours | `test_09` |
| Reduced motion | No mark animation | `test_12` |
| Vertical tabs (`sidebar.verticalTabs`) | Mark on the inline-start edge | `test_13` |

### The launcher and Track B

The launcher used to copy the preview `userChrome.css` into every profile. It uses `!important` and would override the built-in theme. With the Nulavio engine (`Engine.builtin_theme`), the launcher no longer installs it. It removes only the copy it wrote itself, identified by its header, and never a file the user made.

## Extension points verified in the 158.0.1 source

| Area | Real entry points | Use by the Shell |
|---|---|---|
| Window document | `browser/base/content/browser.xhtml`, `navigator-toolbox.inc.xhtml` (`#navigator-toolbox`, `#TabsToolbar`, `#nav-bar`, `#urlbar-container`, `#PersonalToolbar`), `browser-box.inc.xhtml` | Stylesheet link (patch 0003) |
| Skin and tokens | `chrome://browser/skin/` → `browser/themes/linux/browser.css` → `browser-shared.css` (imports `tab.tokens.css`, `tabs.css`, `urlbar.css`, `toolbarbuttons.css`, `browser-colors.css`); `toolkit/themes/shared/design-system/dist/tokens-{shared,brand,platform}.css` | Re-valued tokens |
| Tabs | `browser/components/tabbrowser/content/` (`tabs.mjs`, `tab.js`, tab groups, split view, `drag-and-drop.js`), DOM `tab.tabbrowser-tab > .tab-stack > (.tab-background, .tab-content)` | Tokens; `.tab-background::after` mark |
| Address bar | `browser/components/urlbar/content/` (`UrlbarInput.mjs`, `SmartbarInput.mjs`), DOM `moz-urlbar#urlbar > .urlbar-background + .urlbar-input-container`, results view `view-nova.css` | Tokens only |
| Toolbar layout | `browser/components/customizableui/CustomizableUI.sys.mjs` (`browser.uiCustomization.state`) | Untouched; default layout kept |
| Sidebar and vertical tabs | `browser/components/sidebar/`, prefs `sidebar.revamp` (true), `sidebar.verticalTabs` (false) | Supported by the theme |
| Shared widgets | `toolkit/content/widgets/moz-*` (button, toggle, card, page-nav, box-item, message-bar, select…) with `*.tokens.css` | For Shell pages and Settings (next milestones) |
| Component docs | `browser/components/storybook/` (needs a large npm install) | Not adopted; see [design system](design-system.md#component-gallery) |
| New tab / home | Built-in `newtab@mozilla.org`; Nulavio overrides the new tab with the Shell add-on | Shell page |
| Settings | `browser/components/preferences/` (`preferences.xhtml`, `*.inc.xhtml`, `config/`) | Planned (M5) |
| Onboarding | `browser/components/aboutwelcome/` (`browser.aboutwelcome.enabled`) | Planned (M6) |
| Warnings and errors | `toolkit/content/aboutNetError.{html,mjs}`, `net-error-card.mjs`, `browser/base/content/blockedSite.xhtml`, `browser/components/controlcenter/`, `browser-siteProtections.js` | Planned (M6); criteria untouched |

## Rebase notes

- **Patch 0003** adds one line after the `letterboxing.css` link. If the head of `browser.xhtml` moves, the context changes. `apply_patches.py` fails loudly; re-anchor the line after the last stylesheet.
- **Variable names** change between releases (Firefox 158 renamed many for "Nova"). `test_horizon` checks rendered colours, sizes and the mark on the real build, so a renamed variable fails a test instead of silently reverting the look.
- **Layer names** come from Mozilla's token build. If `tokens-foundation-brand-nova` disappears, `test_horizon_theme` (static) still passes, but `test_02` and `test_03` (rendered) fail.
- `nulavio.horizon.enabled` is the escape hatch while a rebase is in progress.
