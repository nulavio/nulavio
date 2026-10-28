# Migration plan: from Firefox's look to the Nulavio Shell

> Superseded on 2026-10-27 by the [UX redesign programme](../product/execution-plan.md#ux-redesign-programme-from-2026-10-27) (slices UX0–UX7). The open milestones below (M2 remainder, M3–M7) are folded into it; this page stays as history.

Rule for every step: build on the Nulavio build, run the full integration suite (both tracks), capture before/after with `scripts/research/shell_screenshots.py`, keep patches minimal and documented.

| Milestone | Scope | Status |
|---|---|---|
| **M0 Audit** | UI entry points, token layers, extension points, current screenshots | **Done** ([architecture](architecture.md), [screenshots](screenshots/)) |
| **M1 Directions and tokens** | Three directions, decision, chrome tokens, contrast | **Done** ([directions](visual-directions.md), [design system](design-system.md)) |
| **M2 Window: tab strip, toolbar, address bar** | Horizon theme, densities, route mark, launcher change | **First slice done** (2026-10-25). Remaining: address-bar results surfaces, panels/popups tokens, tab group palette, overflow arrows |
| M3 Nulavio Home | Fix the "Extensão (Nulavio Shell)" identity chip on the new tab; favourites and recent sessions (opt-in, nothing personal shown by default); default top sites without Mozilla entries; new-tab budget ≤ 150 ms median (today 121 ms) | Next |
| M4 Privacy Center and menus | Shell page reading real signals (content-blocking log, permissions, exceptions, site data, connection) through the upstream APIs; app menu and panels in Horizon; workspaces data-model proposal | **Per-site part done (S14)**: the engine's trust panel is the per-site panel (it already reads the content-blocking log, the per-site switch and site data); Settings → Site exceptions lists every exception. Menus and panel tokens: planned |
| M5 Settings and Providers | Organised sections; Providers page showing only real integrations (extension installed and enabled, native-messaging host registered); no fake toggles | Planned |
| M6 Onboarding, motion, states | Flow A (theme, tab layout, search engine, privacy, passwords); loading motion; error-page styling with criteria untouched | Planned |
| M7 QA | Real KDE Wayland and GNOME review, Orca screen-reader pass, 125/150 % on hardware, performance budget in CI | Planned |

## Decisions for the maintainer

Found during the audit; they change behaviour, not just looks, so they are not made silently:

1. **Address-bar suggestions send keystrokes to the search engine.** Typing "nul" showed Google's trending searches: search suggestions and trending (`browser.search.suggest.enabled`, `browser.urlbar.trending.*`) are upstream defaults that Nulavio does not change. Options: off by default with an onboarding choice (privacy first), or keep on.
2. **Default search engine is Google** (upstream default for pt-BR). To be chosen in onboarding (M6).
3. ~~**Default top sites include "Add-ons for Firefox"** (Mozilla's shortcut list).~~ Done in UX1 (2026-10-28): the build ships no default shortcuts on about:home (`browser.topsites.useRemoteSetting=false`, empty `default.sites`); sites the person visits still appear.

## Track A (preview)

The preview keeps `browser/theme/userChrome.css` (recolouring only). Aligning it with `tokens.json` (generate it from the same tokens) is cheap and planned with M2's remaining work. Geometry and the route mark stay Track B only.
