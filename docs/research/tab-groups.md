# Tab groups in the Nulavio build (#323)

Status: checked on 2026-11-16 on the 160.0-0.5 package with the Shell of `main` (dev_sync, not an engine build),
headless. Tab groups are the engine's (`browser.tabs.groups.enabled`, on by default in Firefox 160); Nulavio keeps the
AI "smart" grouping off (`browser.tabs.groups.smart.enabled=false` in `baseline.js`). The checks are
`tests/integration/test_tab_groups.py`.

## What Nulavio already does to them

- **Colours.** Horizon draws the group colours from Nulavio's tokens (`--nv-color-group-*` in `horizon.css`). The
  palette Nulavio offers for a new group leaves out orange, purple and red, the hues of Nulavio's warning, agent and
  critical states: the engine's group editor hides their swatches (`horizon.css`; a group that already has one keeps
  it and shows it), and the colour the engine picks by itself for a new group skips them (`NulavioWindow`,
  `#groupPalette`).
- **Profile.** The profile is told by the band (its name, its glyph and its colour), never by a group: a group's colour
  does not change the band, in either theme.

## Per arrangement

| Arrangement | Create, rename, colour | Collapse and expand |
|---|---|---|
| Lateral (side tab list) | Works | Works: the group's tabs leave the list and come back |
| Foco (side list, opens on hover) | Works | Works |
| Abas no topo | Works | Works |

## Not checked

- **Restore.** Neither a restart nor reopening a closed group was checked: driving the session store's
  `undoCloseTabGroup` from a test was not reliable here (the group was not yet in its list when asked). It is the
  engine's own feature, which Nulavio does not touch; a follow-up issue tracks the check.
- **Imersivo.** With the mode on, the tab list (and its groups) leaves the view and comes back as for ungrouped tabs;
  no group-specific behaviour was looked for.
- **Routing (ADR 0003).** A link that a rule sends to another profile opens in that profile's window; whether it was
  opened from a grouped tab makes no difference to the decision, which is made per link. Not run.
- **User docs**: not changed here.
