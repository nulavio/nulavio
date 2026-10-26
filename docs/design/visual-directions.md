# Visual directions for the Nulavio Shell

Status: **decided (2026-10-25): Horizon**, with Monoline's density as the compact mode.

The brand itself was chosen earlier ([brand explorations](../brand/explorations.md): Obsidian Current). This page decides how the **browser window** looks. All three directions draw the same slice of the window: tab strip with a pinned tab, a muted tab and the selected tab; toolbar; address bar with the trust and tracking icons; extension buttons. Only tokens and geometry change. Generator: `scripts/brand/ui_directions.py`. It renders the PNGs below with headless Firefox and measures contrast on the pairs the chrome uses.

## The proposed palette, checked against the brand

The brief proposed Deep Ocean `#0C1822`, Slate `#193946`, Mint `#7BE5D0`, Cloud `#F1F7F8`, Amber `#E4AC68`. Each sits within ΔE76 1.5–4.5 of a brand primitive that already passes 29 (now 55) WCAG pairs:

| Proposed | Brand token | ΔE76 |
|---|---|---:|
| Deep Ocean `#0C1822` | navy.900 `#0B1623` | 2.5 |
| Slate `#193946` | navy.800 `#183746` | 1.7 |
| Mint `#7BE5D0` | mint.400 `#6FE0C5` | 4.5 |
| Cloud `#F1F7F8` | navy.50 `#F1F7F5` | 1.5 |
| Amber `#E4AC68` | amber.400 `#E7AE61` | 4.5 |

A difference of about 2.3 is the threshold at which people notice two colours differ. So the brief's palette is the brand palette. We keep the validated primitives instead of adding near-duplicates.

## A. Horizon: ocean and mint

![Horizon, light](assets/directions/horizon-light.png)
![Horizon, dark](assets/directions/horizon-dark.png)

- Tones separate the areas, without lines: deep tab strip, lighter toolbar, raised selected tab.
- The selected tab carries a short mint **route mark**, the line from the Nulavio symbol. It is also the non-colour cue that makes the selection visible at 3:1 (WCAG 1.4.11).
- Address bar 36 px with a 14 px radius, 10 px elsewhere. That is geometric, against the 24 px pills of Firefox 158 ("Nova").
- **Trade-offs:** it relies on tone steps that sit close together in light mode; the route mark carries the selection. Blue-green chrome is common on Linux desktops (Breeze) and may blend in.

## B. Graphite and copper (no blue or green)

![Graphite, light](assets/directions/graphite-light.png)
![Graphite, dark](assets/directions/graphite-dark.png)

- Warm neutrals (paper and graphite), 4–6 px radii, a copper top line on the selected tab.
- **Trade-offs:** distinctive and calm, but it breaks with the logo and site (mint). Copper sits near amber (warning) and red (critical) in hue, so states would rely more on icons and words. It needs a second set of primitives and contrast pairs.

## C. Monoline: dense, neutral, accent only on focus

![Monoline, light](assets/directions/monoline-light.png)
![Monoline, dark](assets/directions/monoline-dark.png)

- 30 px tabs, square tabs with a hairline, flat address bar, mint only on keyboard focus.
- **Trade-offs:** best for 1366×768 and dense work, and the cheapest to carry, but the least memorable. It looks like many minimal themes, and the brand appears only on focus.

## Scoring

Contrast: all three pass **18/18** measured pairs in both themes; the lowest margin is the light placeholder text in each (5.1–5.9 against 4.5). Data: [`assets/directions/contrast.json`](assets/directions/contrast.json).

Scores are 1–5, weighted. The weights follow the brand selection and add implementation cost, because every Firefox release has to carry this.

| Criterion | Weight | Horizon | Graphite | Monoline |
|---|---:|---:|---:|---:|
| Accessibility (AA pairs, non-colour state cues, both themes) | 25% | 5 | 5 | 4 |
| Originality against other browsers (Firefox Nova pills, Chrome, Arc/Zen sidebars, Brave, Vivaldi page colours) | 20% | 4 | 4 | 2 |
| Brand fit (logo, tokens, site) | 20% | 5 | 2 | 3 |
| Implementation and rebase cost (upstream variables only?) | 15% | 5 | 4 | 5 |
| Small screens and density | 10% | 4 | 4 | 5 |
| Harmony with Breeze/Adwaita, light and dark | 10% | 4 | 4 | 4 |
| **Weighted** | | **4.60** | **3.85** | **3.65** |

## Decision

**Horizon**, because it is the brand already chosen and validated. It is implemented entirely by re-valuing upstream variables plus one decorative mark, which is why it was the cheapest to carry. Taken from Monoline: its sizes become the **compact density** (30 px tabs and field). Taken from Graphite: keep warm-neutral surfaces in mind for a future "paper" accent option. That option is not planned until there is demand.
