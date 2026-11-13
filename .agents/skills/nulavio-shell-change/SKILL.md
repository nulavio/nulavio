---
name: nulavio-shell-change
description: Use before changing Nulavio's Shell pages, privileged modules, window theme, start page or design tokens (browser/shell, browser/branding/nulavio/content/theme, browser/startpage, docs/brand/tokens.json). Covers the page and module rules the tests enforce, both locales, tokens and contrast, accessibility states, and the fast loop without an engine build.
---

# Changing the Nulavio Shell

The Shell is a built-in add-on with privileged experiments. Its rules protect
users, so the unit tests reject most mistakes; this skill says them before you
write the code. Read the documents that apply to the change:
[ux-principles](../../../docs/design/ux-principles.md),
[design-system](../../../docs/design/design-system.md),
[accessibility](../../../docs/design/accessibility.md),
[component-inventory](../../../docs/design/component-inventory.md), and for HTML,
CSS or JavaScript the `modern-web-guidance` skill. Confirm every API or CSS
feature in the Gecko version Nulavio ships, not in Chrome or Baseline tables.

## Structure

- Privileged logic lives in `browser/shell/modules/*.sys.mjs`, which validates
  everything it receives. `experiments/<name>/parent.js` stays a thin bridge to
  the module, with a schema; pages call only the documented APIs
  (`tests/unit/test_shell.py` lists them).
- Every error code a module returns has an `err_*` message in both locales.
- Search providers, layout presets and profile templates are curated lists in
  the modules; their tests say what may be added and how.

## Page rules (enforced by `test_shell.py` and the opengrep rules)

- No network requests from the Shell: no `fetch(`, `XMLHttpRequest`,
  `WebSocket`, `sendBeacon`, `newChannel` or `loadSubScript`. The one resource a
  module reads itself is the engine's profile icons, by `NetUtil.asyncFetch`
  with a constant `chrome://` URI.
- No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval` or
  `new Function`; no inline scripts or `style=` attributes; no remote resources.
- Icons come from `browser/shell/shared/icons` and the `icon-*.svg` files,
  never Unicode pseudo-icons.
- Colours are `var(--nv-*)` design tokens, defined for both themes.

## Strings: both locales, every time

- WebExtension strings: `browser/shell/_locales/{en,pt_BR}/messages.json`.
  Fluent strings: `browser/shell/l10n/{en-US,pt-BR}/`. The same keys and the
  same placeholders in both; the unit tests compare them.
- Portuguese runs longer: check the pt-BR rendering for truncation and wrapping.
- Security cues tell the truth: never a state the code has not confirmed
  ([CONTRIBUTING](../../../CONTRIBUTING.md) non-negotiable 5).

## Tokens, theme and contrast

1. Change values in `docs/brand/tokens.json`, never in CSS. Run
   `python3 -I scripts/brand/build_tokens.py` and
   `python3 -I scripts/brand/contrast.py`; add a contrast pair for every new
   foreground and background use.
2. Window theme (`horizon.css`): geometry in the `tokens-foundation-brand-nova`
   layer, colours inside the accessibility guard, no literal colours, no
   `!important`, no selectors on security UI (`tests/unit/test_horizon_theme.py`).
3. Check light and dark, `prefers-contrast`, `forced-colors`,
   `prefers-reduced-motion`, keyboard navigation and visible focus.

## Fast loop, then the real check

- Iterate without an engine build:
  `python3 -I scripts/build/dev_sync.py --install <copy of a packaged build>`
  copies the Shell, branding theme, branding prefs and modules into that copy's
  `omni.ja` (`--reset` restores it). Use a copy you own, never another session's
  build tree, and fresh test profiles, never a real one.
- Before/after evidence for visual changes:
  `NULAVIO_ENGINE=<build>/nulavio/nulavio python3 -I scripts/research/shell_screenshots.py --out <dir> --label after`.
- Then the tests of the pages you touched (`tests/integration/test_*_ui.py`,
  `test_settings_*.py`, `test_component_gallery.py`, `test_horizon.py`) against
  a build, as the `nulavio-engine-verification` skill says. `dev_sync` results
  are rechecked with a real build before anything ships.
