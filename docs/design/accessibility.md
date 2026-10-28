# Accessibility of the Nulavio Shell

Target: WCAG 2.2 AA in both themes, at 100–150 % scaling, with keyboard and screen readers. The rules below are tested where the harness can test them; the rest is listed as pending.

| Requirement | How | Evidence |
|---|---|---|
| Text contrast ≥ 4.5:1 | Token pairs | `scripts/brand/contrast.py`: 208/208 |
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
