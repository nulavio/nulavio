# UX principles of the Nulavio Shell

These extend the principles and flows in [`docs/brand/ux-flows.md`](../brand/ux-flows.md); they are the rules used to judge Shell changes.

| Principle | What it means in the Shell | How we check |
|---|---|---|
| Content is the focus | Chrome uses quiet tones and no decoration; the only brand mark is the 16 px route under the selected tab | Screenshots before/after |
| You know where you are | Selected tab = raised surface + mark; the address bar is the widest, tallest control | Rendered contrast tests |
| Security visible, not alarming | Trust, tracking and permission indicators stay exactly as upstream; "secure" is neutral, warnings use amber/red + icon + words | `test_horizon` 07 |
| Frequent controls within reach | Upstream layout kept (back, forward, reload, address, extensions, menu); targets ≥ 24 px | `test_horizon` 06 |
| Advanced without overload | Densities, vertical tabs, themes and the Horizon switch exist but are not pushed | Defaults |
| Perceived performance is design | No added scripts in the window; new tab ≤ 150 ms median; first paint not slower | `shell_screenshots.py` metrics |
| Extensions and small screens are first-class | Password-manager popups unchanged; 1366×768 at 150 % checked | Integration suite, matrix |
| Original, not borrowed | Geometric 10/14 px radii (not Firefox Nova's 24 px pills), ocean tones, route mark; no page-colour tabs, no sidebar-first layout | [Directions](visual-directions.md) |
| Honest | Shell pages show only signals read from real APIs; no score, no fake toggles | Shell unit tests |
