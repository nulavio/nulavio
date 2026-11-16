# Split view in the Nulavio build (#315)

Status: checked on 2026-11-16 on the 160.0-0.5 package with the Shell of `main` (dev_sync, not an engine build), headless,
1400×900. Split view is the engine's (`browser.tabs.splitView.enabled` is `true` by default in Firefox 160); Nulavio adds
nothing to it and changes nothing in it. The checks are `tests/integration/test_split_view.py`.

## What works

| Part of the window | In a split | Checked by |
|---|---|---|
| Making a split | The tab menu's items (`context_moveTabToSplitView`, `context_separateSplitView`, `context_reverseSplitView`, in the browser's language) and `gBrowser.addTabSplitView`. Dragging a tab onto the page was not tried | `test_04` (the menu's items are there); the split itself, by the API, in every test |
| Address bar and identity | They follow the **focused** side: selecting the other side changes the address and the identity box at once | `test_01` |
| The side that is not focused | It shows the engine's own footer with its site and the connection ("Não seguro 127.0.0.1:…"), drawn by the engine, not by the page | `test_01`, `test_05` captures |
| The band with Imersivo on | It names the focused side's site, and changes with the focus; the other side keeps its footer | `test_02` |
| Profile | Both sides are tabs of the same window, so of the same profile; the band names the profile once | `test_01` |
| Side tab list (Lateral, Foco) | The two tabs show as one row, each side with its own title; selecting a side selects that tab | `test_01`, captures |
| Tabs on top | The same, in the tab strip | `test_03` |
| Light and dark themes | Nothing of Nulavio's draws over the split; the focused side has the engine's accent outline | `test_05` captures (`NULAVIO_TEST_ARTIFACTS/split-view/`) |

## Routing (ADR 0003)

A link clicked in one side that a rule sends to another profile opens in that profile, as from any tab: it is requested
once, by the other profile, and both sides of the split stay as they were. A link the rules leave alone (same site)
loads in the side it was clicked in, which stays split. Routing decides per link and never looks at the split.
Checked by `test_routing.py` › `test_16b_a_link_clicked_in_a_split_view_side_is_routed_and_the_split_stays` (in-page
routing on, the two-profile setup of that module).

## Keys

None. The engine's commands for a split (`key_addTabSplitView`, `key_separateTabSplitView`) have no key by default in
Firefox 160, and Nulavio gives them none (the maintainer's decision on #315, 2026-11-16): the tab menu's items are the
way in, so no new key competes with the engine's or KDE's. Nothing to add to Nulavio's list of keys.

## Where people read about it

`README.md` and `README.pt-BR.md` ("Also built in"), and the engineering pages (`site/engenharia`, `site/en/engineering`):
5.2 says what the address bar and the band name in a split, 5.4 that routing works the same in either side.

## Not checked

- Dragging a tab onto the page to make a split (the tab menu and the engine's API were used).
- An engine build: the checks ran on the 0.5 package with `main`'s Shell.
