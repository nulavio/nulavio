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

Captures, Lateral, a group in each colour offered, the last one gray: [light](../design/screenshots/tab-groups-323/groups-light.png),
[dark](../design/screenshots/tab-groups-323/groups-dark.png) (from `test_04`).

## Per arrangement

| Arrangement | Create, rename, colour | Collapse and expand |
|---|---|---|
| Lateral (side tab list) | Works | Works: the group's tabs leave the list and come back |
| Foco (side list, opens on hover) | Works | Works |
| Abas no topo | Works | Works |

## Restore

| How | Result | Checked by |
|---|---|---|
| A group closed from its menu ("Excluir grupo"), then reopened from the closed groups | Comes back with its name, colour and tabs, and leaves the closed list | `test_05` |
| A restart with "Abrir janelas e abas anteriores" on (`browser.startup.page` = 3) | The group comes back with its name, colour, tabs and collapsed state; the band names the profile | `test_07` |

The earlier attempt asked the session store for the closed group before the close had finished:
`gBrowser.removeTabGroup` returns a promise, and the group is in the closed list once it resolves. After a restart the
group's tabs wait unloaded until selected, and the session keeps what each tab had loaded: a tab restarted before its
page arrived comes back blank (the test waits for the pages first). Nulavio keeps the
engine's `browser.sessionstore.max_tabs_undo` (25); with 0 the engine would keep no closed group.

## Imersivo

With Imersivo on, a collapsed group stays collapsed, with its name, colour and tabs, and the band keeps the profile's
name; turned off again, the group is as it was and expands. Checked by `test_06`.

## Not checked

- **Routing (ADR 0003).** A link that a rule sends to another profile opens in that profile's window; whether it was
  opened from a grouped tab makes no difference to the decision, which is made per link (the same holds in a split,
  `test_routing` test 16b). Not run with a group.
- Saved groups ("Salvar e fechar") and groups across windows.
- An engine build: the checks ran on the 0.5 package with `main`'s Shell.

## Where people read about it

`README.md` and `README.pt-BR.md` ("Also built in").
