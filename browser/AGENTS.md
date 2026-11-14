# browser/: the engine's configuration, patches, branding and the Shell

Read the root [AGENTS.md](../AGENTS.md) first; its rules apply here and are not repeated.

## What is here

- `patches/` and `patches/series`: changes to Firefox's source. `build/engine.json` pins the Firefox release they apply to; `build/mozconfig` is the build's configuration.
- `config/`: default prefs (`prefs/baseline.js`), the Guard's rules (`guard-rules.json`), search and integration lists.
- `shell/`: the Shell, a built-in add-on with privileged experiments: modules, pages, locales.
- `branding/nulavio/`: the window theme (`content/theme/horizon.css`), names and icons. `startpage/`: the local start page. `distribution/`: bundled extensions and the content filter's lists.

## Rules that apply here

- Patches (invariants I1, I6): each has `Owner:` and `Upstream:` headers and a line in `patches/series`. Prefer a pref, a policy, branding or a built-in add-on to a patch. Nothing weakens the sandbox, site isolation, TLS and certificate checks, extension signatures, Safe Browsing, Remote Settings or updates. No `MOZILLA_OFFICIAL`, no Mozilla or third-party trademarks.
- Prefs and Guard rules (I1, I2): every pref in `config/prefs/baseline.js` carries `@mode`, `@category`, `@why` and `@tradeoff`. No pref that weakens a protection, turns on telemetry, remote control or a privileged console, or sends data to a new endpoint; no `guard-rules.json` change that loosens a rule.
- The Shell (I10, I7, I2): modules under `shell/modules/` validate everything they receive, and `shell/experiments/*/parent.js` stays a thin bridge with a schema. No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `eval` or computed module address; no network request, remote script or remote font. A page never shows a state the engine did not report (protected, locked, private, connected), and an error is shown as an error. Strings exist in both locales with the same ids, and every error code has its `err_*` message in both.
- Theme and branding: colours and sizes come from `docs/brand/tokens.json` through tokens; no literal colours, no `!important`, no selector that restyles or hides security UI (identity and permission indicators, warnings, private browsing and agent cues).
- The start page is static and local (I2): no request, no remote resource, no claim about protection that the engine did not report.

Documents: [extension model](../docs/architecture/extension-model.md), [update policy](../docs/architecture/update-policy.md), [build](../docs/architecture/build.md), [hardening](../docs/security/hardening.md), and for the Shell and the theme the [design system](../docs/design/design-system.md), [UX principles](../docs/design/ux-principles.md) and [accessibility](../docs/design/accessibility.md). Skills: [nulavio-shell-change](../.agents/skills/nulavio-shell-change/SKILL.md) before a Shell, theme or start-page change; [nulavio-engine-verification](../.agents/skills/nulavio-engine-verification/SKILL.md) to verify it.

## Checks

- `python3 -I tests/run.py unit` (here mostly `test_shell.py`, `test_prefs_and_guard.py`, `test_horizon_theme.py`, `test_build_guard.py`).
- The matching `tests/integration/test_*.py` against a Nulavio build for prefs, policies, the Shell and the window; a real build (`scripts/build/build_nulavio.sh`) for patches. CONTRIBUTING's "Common changes" table says what each kind of change runs.
- Shell code without an engine build: `scripts/build/dev_sync.py` (the shell-change skill says how).

## Not here

The launcher that starts the engine is `launcher/`; build and release scripts are in `scripts/`; the tests are in `tests/`; design documents and tokens are in `docs/`.
