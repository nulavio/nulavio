# Accessibility of the Nulavio Shell

Target: WCAG 2.2 AA in both themes, at 100–150 % scaling, with keyboard and screen readers. The rules below are tested where the harness can test them; the rest is listed as pending.

| Requirement | How | Evidence |
|---|---|---|
| Text contrast ≥ 4.5:1 | Token pairs | `scripts/brand/contrast.py`: 55/55 |
| Text contrast on the real window | Rendered colours of the selected/background tab labels, address text | `test_horizon` 02 (light), 03 (dark) |
| Non-text contrast ≥ 3:1 (WCAG 1.4.11) | Field boundary `border.control`; focus ring; selected-tab mark (surface tones alone are below 3:1) | `test_horizon` 02, 03 |
| Focus visible (2.4.7, 2.4.11) | Mint 2 px ring; address bar focus border = focus token | `test_horizon` 08 |
| Target size ≥ 24 px (2.5.8) | Toolbar and tab-strip buttons measured | `test_horizon` 06 |
| No colour-only meaning (1.4.1) | Selection = surface + mark; states use icon + words; "secure" is neutral | design rule, mark tested |
| High contrast | Horizon colours step aside under `prefers-contrast` | `HorizonHighContrastTest` |
| Forced colours | Same guard; the mark uses `SelectedItem` | Not simulable for the window in this harness (pending manual check) |
| Reduced motion | The only Horizon animation (mark entrance) is disabled | `test_horizon` 12 |
| Scaling 100/125/150 % and 1366×768/1920×1080 | Densities in px tokens; text in the desktop font | [matrix-after.png](screenshots/matrix-after.png) |
| Keyboard | No shortcut or focus order changed (no DOM changes) | Upstream behaviour |
| Screen readers | No DOM changes; the mark is a decorative pseudo-element, not exposed | Upstream accessibility tree; Orca pass pending (M7) |
| Right-to-left | Logical properties only (`inset-inline-start`, `inline-size`) | `test_horizon_theme.test_rtl_safe_geometry` |
| User choice | `nulavio.horizon.enabled = false` restores upstream; installed themes keep their colours | `test_horizon` 09, 10 |

Pending: manual Orca pass, forced colours on a real high-contrast GTK theme, 125/150 % on real hardware.
