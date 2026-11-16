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

## What is not done yet

- **Per-site routing (ADR 0003) inside a split** is not tested: a link in one side that a rule sends to another profile.
  Routing decides per link and opens the link in the other profile's window, so it should leave the split alone, but
  this needs the two-profile setup of `test_routing`, which this check does not have. Follow-up in the issue.
- **Keys.** The engine's commands for a split (`key_addTabSplitView`, `key_separateTabSplitView`) have no key by
  default, so there is nothing to list in Nulavio's keys yet. Giving them one is a choice for after this check.
- **User docs and the site's feature list**: not changed here (the site's comparison changes in both languages, with
  its own tests).
