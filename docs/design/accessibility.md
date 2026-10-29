# Accessibility of the Nulavio Shell

Target: WCAG 2.2 AA in both themes, at 100–150 % scaling, with keyboard and screen readers. The rules below are tested where the harness can test them; the rest is listed as pending.

| Requirement | How | Evidence |
|---|---|---|
| Text contrast ≥ 4.5:1 | Token pairs | `scripts/brand/contrast.py`: 220/220 (original 208 preserved) |
| Text contrast on the real window | Rendered colours of the selected/background tab labels, address text | `test_horizon` 02 (light), 03 (dark) |
| Non-text contrast ≥ 3:1 (WCAG 1.4.11) | Field boundary `border.control`; focus ring; selected-tab mark (surface tones alone are below 3:1) | `test_horizon` 02, 03 |
| Focus visible (2.4.7, 2.4.11) | Mint 2 px ring; address bar focus border = focus token | `test_horizon` 08 |
| Native sidebar focus contrast | History, bookmarks and extension-panel header; real focused-state rendering, both themes | `test_sidebar_focus`: 4.60–9.84:1; Horizon off, installed theme and web-content scope checked |
| Target size ≥ 24 px (2.5.8) | Toolbar and tab-strip buttons measured | `test_horizon` 06 |
| No colour-only meaning (1.4.1) | Selection = surface + mark; states use icon + words; "secure" is neutral | design rule, mark tested |
| High contrast | Horizon colours step aside under `prefers-contrast` | `HorizonHighContrastTest` |
| Forced colours | Same guard; the mark uses `SelectedItem` | Not simulable for the window in this harness (pending manual check) |
| Reduced motion | The only Horizon animation (mark entrance) is disabled | `test_horizon` 12 |
| Scaling 100/125/150 % and 1366×768/1920×1080 | Densities in px tokens; text in the desktop font | [matrix-after.png](screenshots/matrix-after.png) |
| Keyboard | Native window navigation; Shell primary actions focused, context removal restores focus, Ctrl+Enter sends | `test_assistant_ui`, `test_ai_ui`, `test_vault_ui`, `test_shell` |
| Screen readers | Labelled controls, answer heading, one polite start/end announcement, digit-by-digit phone comparison | DOM assertions in the Shell integration tests; manual Orca pass pending |
| Right-to-left | Logical properties only (`inset-inline-start`, `inline-size`) | `test_horizon_theme.test_rtl_safe_geometry` |
| User choice | `nulavio.horizon.enabled = false` restores upstream; installed themes keep their colours | `test_horizon` 09, 10 |

Pending: manual Orca pass, forced colours on a real high-contrast GTK theme, 125/150 % on real hardware.

## UX2 Shell component checks

The last CSS layer (`nv-accessibility`) guarantees that page/gallery composition
does not replace keyboard focus, high-contrast borders or forced-colour native
inputs. Reduced motion disables transitions and animations, including pseudo
elements. Critical/warning/refusal signals are opaque and non-animated even when
motion is allowed. Invalid fields have a 2 px critical border and an associated
text error with an octagon; colour is supplemental. Buttons preserve native
disabled semantics, and pressed controls retain a check mark and outline.

The rendered Track B gallery suite measures 1280/390 px in both themes, asserts
focus outline, invalid border, equal primary/secondary radius, and no horizontal
overflow. It separately tests 320/390 px at 200% root font, increased-contrast
focus and forced-colour native switch appearance. Baselines include failure,
refusal and critical-consent specimens. The sample controls are inert and
clearly labelled, so they cannot be mistaken for working permission controls.

The initial component evidence used a copied engine plus `dev_sync.py`;
the [integrated report](design-system.md#ux2-integrated-verification-2026-10-28) identifies the rebuilt package. Neither is
WCAG certification. Automated checks do not prove screen-reader
announcements or physical GTK theme behavior. Manual Orca and real desktop
high-contrast/125–150% checks remain pending. The integrated gallery was
repeated without baseline updates on the rebuilt package after token and
identity integration; all four comparisons were pixel-identical.

The font-enlargement fixture checks actual 320/390 px `innerWidth`; the
forced-colour capture uses browser preferences in a disposable headless window.
The captured document is 378 px wide (390 px viewport minus its scrollbar).
The state inventory also has visually hidden descriptions outside the inert
specimens, so assistive technology can read the examples without exposing fake
actions. The existing 11 px small identity initial is retained (a non-body glyph,
with the profile name beside it); `ui_lint` reports it as the one accepted warning.


## UX3A window checks

The band has a 30 px minimum rather than a fixed height. Names and state words
wrap without removing another warning; interactive controls remain at least
24 × 24 CSS px. The native toolbar order and address/security controls are
retained. Tests measure nonzero geometry, opacity 1, bounds, hit testing,
accessible names, static cues, native keyboard focus/Enter, both themes and
both native tab orientations. Requested 630 px windows remain 638 px wide in
some scaled vertical-tab scenes because of Gecko's native minimum; the
[measurements](screenshots/ux3a/geometry-pt.json) retain actual dimensions.

Temporary/private and agent/raw/Guard combinations are checked through real
owners. The composition test uses a real registry and retained Guard findings,
plus a synthetic live-PID raw marker read by the AI owner; separate Bridge
tests cover actual raw endpoint handover, latch retention, pause and global
stop. This is not evidence that Guard audits new AI Workspaces. Protection
includes a real encrypted/unlocked profile that relocks after its window ends.
The [evidence inventory](screenshots/ux3a/verification.json) distinguishes these
fixtures from real backend operations and records en/pt-BR checks.

Horizon off and an installed theme retain the safety UI while native controls
keep their own appearance. Increased contrast selects system colours; profile SVGs follow the identity
text colour, preserving the glyph on a dark system canvas (the original fixed
ink measured 1.13:1 in the reproduced case). The rendered glyph regression
keeps the 3:1 non-text minimum. Forced-
colour rules preserve border patterns and words. Gecko may exempt chrome from
document forced-colour preferences, so the headless preference check is not a
real GTK forced-colour certification. Reduced motion/transparency leave all
signals opaque and static. Fullscreen's compact line remains visible and
keyboard focus restores its controls; the native fullscreen exit button is
separately hit-tested.

Pending: physical KDE title-bar checks, Orca announcements, real GTK forced
colours/high contrast, hardware scaling and frame-time measurements.
The [rebuilt-package report](screenshots/ux3a/release-verification.json)
records the parent's 207-test local integration run (13 skips) and its
scope; remote CI on distribution Firefox is separate from that evidence.

## UX3B native group checks

The group name remains Gecko's labelled button, with its existing
`aria-expanded`, tab visibility, keyboard collapse/expand and context menu.
A decorative swatch and thin group line do not replace the selected-tab route
mark. Neutral text uses the existing primary-text tokens; all nine group
line/swatch colours use the existing contrast-checked group tokens.

The unavailable orange/purple/red radios and labels are removed together from
the rendered choice set. The currently selected legacy radio remains an honest
visible current-value exception with the original native localized colour name
and tooltip; it is never silently recoloured. Trusted native arrow input skips
unavailable colours, including wraparound and leaving a current legacy value.
The native checked accessible is queried through `nsIAccessibilityService`,
after its asynchronous tree update; focus-visible and the original label/title
are checked too. Native pointer selection, group-label keyboard navigation,
both tab orientations/themes and en-US/pt-BR are covered by
`test_horizon_groups.py`. This does not certify Orca announcements.

Horizon off, an installed theme and the engine accessibility-theme preference
restore all nine choices and the native default-colour behavior. Forced-colour
rules use the same guard; real GTK forced colours remain pending. Main-window
captures exclude native popup widgets, so editor input/accessible-state evidence
is recorded separately in the [verification inventory](screenshots/ux3b/verification.json).
No existing contrast or pixel-comparison threshold is reduced.
