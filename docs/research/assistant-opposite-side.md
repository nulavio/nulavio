# Spike: the assistant on the side opposite the vertical tabs (#249)

- **Status:** done, 2026-11-18. Nothing here changes what Nulavio ships.
- **Tracking:** [issue #249](https://github.com/nulavio/nulavio/issues/249). It feeds [#346](https://github.com/nulavio/nulavio/issues/346), Imersivo "Barras": the assistant's own edge.
- **Read on:** Firefox 160.0's source (the engine Nulavio 160.0 is built on), and Mozilla's release tags `FIREFOX_155_0_RELEASE` to `FIREFOX_160_0_RELEASE` on [mozilla-firefox/firefox](https://github.com/mozilla-firefox/firefox).

## The question

Can the assistant's panel (the Shell's `sidebar_action`) open on the other side of the page, while the launcher and the vertical tabs stay where they are, with a patch that is small and stable across releases? And should Nulavio offer that layout?

## How the engine places the sidebar today

`#browser` is a flex row. In DOM order its children are:

| # | Element | What it is |
|---|---|---|
| 1 | `#sidebar-container` (`<sidebar-main>`) | the launcher, with the vertical tabs in it |
| 2 | `#sidebar-launcher-splitter` | resizes the launcher |
| 3 | `#sidebar-box` | **the panel**: the assistant, bookmarks, history, any extension's sidebar |
| 4 | `#sidebar-splitter` | resizes the panel |
| 5 | `#tabbrowser-tabbox` | the page |
| 6 | `#ai-window-splitter` | Firefox's own AI window (off: `browser.smartwindow.enabled` is false) |
| 7 | `#ai-window-box` | the same |

`SidebarController.setPosition()` (`browser/components/sidebar/browser-sidebar.js`) gives every child an inline `style.order`. With `sidebar.position_start` true the order is the DOM order (1 to 7); with it false the order is reversed, so the launcher, the tabs and the panel all move to the right together. Then it toggles `sidebar-positionend` on the root, the panel, the launcher, the page and the toolbar button. A dozen CSS rules read that attribute (borders, margins, rounded corners, the expand-on-hover launcher). `setPosition()` runs at startup and whenever the pref changes.

Two facts make a small change possible:

- **The panel's splitter works in any order.** `nsSplitterFrame` resolves `resizebefore="sibling"` in DOM order but decides "before" and "after" in CSS `order` order (`layout/xul/nsSplitterFrame.cpp`, `CSSOrderAwareFrameIterator`). Placed after the page with the panel after it, the splitter still resizes the panel, mirrored. This is how `position_start=false` already works.
- **The engine already docks one panel on the other side.** Its AI window box sits after the page. Since 158, `content-area.css` rounds the page's corner on whichever side has chrome, `ai-window-open` included. So the content area's styles already accept chrome on both sides at once.

## Mechanism: two `order` values

The smallest change puts `#sidebar-splitter` and `#sidebar-box` after `#tabbrowser-tabbox` in flex order, and marks the root. Launcher, tabs and page keep their places. As an engine patch, it goes at the end of `setPosition()`'s ordering loop, behind a pref:

```js
    // Nulavio (#249): the panel and its splitter on the other side of the
    // page, while the launcher and the vertical tabs stay where they are.
    const opposite = Services.prefs.getBoolPref(
      "nulavio.sidebar.panelOpposite",
      false
    );
    if (opposite) {
      const last = browser.children.length + 1;
      const end = this._positionStart ? last : 0;
      this._splitter.style.order = this._positionStart ? last - 1 : 1;
      this._box.style.order = end;
    }
    document.documentElement.toggleAttribute("nulavio-panel-opposite", opposite);
```

That is 13 lines in one function of one file. The CSS that follows from it is Nulavio's own (below), not a change to Mozilla's stylesheets.

### Without a patch

`NulavioWindow` could make the same two assignments after the engine's, and watch `#sidebar-box`'s `style` with a `MutationObserver` to make them again whenever `setPosition()` resets them. It works for a prototype (the probe below does exactly that), but it is the kind of wrap [#242](https://github.com/nulavio/nulavio/issues/242) rules out:
- if a release orders `#browser` some other way (a grid, a CSS-only `:root[sidebar-positionend]` rule), the observer never fires again and the panel silently returns to the tabs' side;
- between the engine's reset and the observer's callback, one frame can draw the panel on the old side.

The patch fails at build time instead, when its context no longer applies.

## Cost on each release

**The patch:** replayed with `patch --fuzz=0` on the six release tags 155.0 to 160.0. **It applies to all six, with no conflict;** only its line offset changes (-30 to 0 lines). `setPosition()` changed in 158 (two lines) and in 160 (five lines), both after the loop the patch follows. `#browser`'s seven children have kept the same ids and order since 155.

**The CSS:** this is where the churn is. Mozilla's sidebar and content-area styles move a lot, and Nulavio's rules for the opposite side have to follow them:

| Release | `sidebar.css` lines changed | `content-area.css` lines changed | rules reading `sidebar-positionend` (sidebar + content area) |
|---|---|---|---|
| 155 | | | 28 + 3 |
| 156 | 247 | 207 | 16 + 2 |
| 157 | 30 | 71 | 18 + 3 |
| 158 | 65 | 109 | 20 + 5 |
| 159 | 0 | 102 | 20 + 6 |
| 160 | 288 | 7 | 30 + 6 |

(Lines of `diff` against the previous release; rule counts are matches of the attribute.)

The rules Nulavio would add are its own, in `horizon.css` and `window-band.css`. They cannot conflict at rebase, but they can stop matching. Each release needs a look, and the integration test below is what notices.

## What breaks, and what Nulavio's own CSS has to cover

From reading the rules, and from the prototype captures in [the evidence folder](evidence/assistant-opposite-side-2026-11-18/):

The prototype ([`probe249.py`](evidence/assistant-opposite-side-2026-11-18/probe249.py)) made the patch's two assignments from chrome on a Nulavio 160.0 build (patches 0001–0012, this tree's Shell), re-applied them when the engine re-ordered `#browser`, and captured the window with the assistant open, today and with the panel opposite. It ran in pt-BR and en-US, at 1366×768 and 1440×900, in both themes, in the three layouts, with the engine's own bookmarks panel, with the tabs on the right (`sidebar.position_start=false`) and in Imersivo. Every capture is from that build; the measures are in [`measure-pt-BR.json`](evidence/assistant-opposite-side-2026-11-18/measure-pt-BR.json) and [`measure-en-US.json`](evidence/assistant-opposite-side-2026-11-18/measure-en-US.json).

**What works without more than the two assignments:**

| | Today | Panel opposite |
|---|---|---|
| Lateral, 1366×768 ([today](evidence/assistant-opposite-side-2026-11-18/pt-BR-lateral-1366x768-light-today.png), [opposite](evidence/assistant-opposite-side-2026-11-18/pt-BR-lateral-1366x768-light-opposite.png)) | tabs 0–224, panel 224–564, page 572–1358 | tabs 0–224, page 224–1010, panel 1026–1366 |
| Lateral, 1440×900, dark, en-US ([today](evidence/assistant-opposite-side-2026-11-18/en-US-lateral-1440x900-dark-today.png), [opposite](evidence/assistant-opposite-side-2026-11-18/en-US-lateral-1440x900-dark-opposite.png)) | page 860 px wide | page 860 px wide, between the tabs and the panel |
| Foco, expand on hover ([opposite](evidence/assistant-opposite-side-2026-11-18/pt-BR-focus-1366x768-light-opposite.png)) | collapsed column, panel, page | collapsed column, page, panel |
| Abas no topo ([opposite](evidence/assistant-opposite-side-2026-11-18/pt-BR-top-1366x768-light-opposite.png)) | panel on the left | panel on the right |
| Tabs on the right ([opposite](evidence/assistant-opposite-side-2026-11-18/pt-BR-lateral-positionend-opposite.png)) | tabs and panel on the right | panel on the left, tabs on the right: the patch follows `position_start` |
| Imersivo ([opposite](evidence/assistant-opposite-side-2026-11-18/pt-BR-immersive-opposite.png)) | panel beside the tab list's edge | the tab list leaves at the left, the panel stays at the right |

- **The page keeps its width:** 786 px at 1366 and 860 px at 1440, in both arrangements. Only the order changes, so the page is never narrower than today.
- **Splitter and keyboard:** the panel's splitter, its keyboard shortcut and the switcher are the engine's own, untouched. The splitter resolves its sibling in DOM order and its side in `order` (above), as with the engine's own `position_start=false`.
- **The engine's own panels go to the same side** ([bookmarks](evidence/assistant-opposite-side-2026-11-18/en-US-lateral-bookmarks-opposite.png)). The setting moves "the sidebar panel", not only the assistant. That is the simpler rule to explain, and the only one the engine's single panel box allows.

**What breaks, all of it in Nulavio's own CSS** (`horizon.css`, `window-band.css`):

1. **The panel touches the window's edge.** Horizon gives the page a margin on the window's side (`#tabbrowser-tabbox { margin-inline: 0 var(--nv-space-3) }`, the other side under `[sidebar-positionend]`). With the panel opposite, that margin ends up between the page and the panel, so the gap there is doubled, and the panel's card has no margin at the window's edge ([capture](evidence/assistant-opposite-side-2026-11-18/pt-BR-lateral-1366x768-light-opposite.png)). Fix: under `:root[nulavio-panel-opposite]` with the panel open, the margin goes to `#sidebar-box`'s outer side and the page has none there. That is about four rules, for both `position_start` values.
2. **Imersivo:** `window-band.css` gives `#sidebar-box` the frame margin on the launcher's side (`#browser > #sidebar-box { margin-inline: var(--nulavio-frame-margin) 0 }`). Opposite, it needs the other side, and the page needs the frame margin at its start, where the tab list left. That is two rules.
3. **The engine's rules for the panel's own edges** (`sidebar.css`: which border goes when the launcher is hidden; the expand-on-hover margins under `[sidebar-panel-open]`) read `sidebar-positionend`, which stays false. The captures show no visible defect from them in Nulavio's layouts, because Horizon draws the panel as a card with its own outline. They are the rules to look at again on each release.

Not seen in the captures, and not measured:
- **A drag of the splitter:** the probe's synthetic drag failed (`windowUtils.sendMouseEvent` is gone in 160), so only the code reading above supports it.
- **RTL:** `order` is logical, so the arrangement mirrors as `position_start` does. Not captured.
- **The first run's layout step:** unaffected (it shows no panel).
- **Firefox's own AI window:** off in Nulavio (`browser.smartwindow.enabled` false). With it on, it would share the panel's side.

## Recommendation

**Go**, as a separate setting, not a layout preset, with the default as today (the panel beside the tabs).

- **The mechanism:** the 13-line patch to `setPosition()`, behind `nulavio.sidebar.panelOpposite`. It applied without conflict to six releases, and it fails at build time rather than silently. The no-patch route (a `MutationObserver` in `NulavioWindow`) is the wrap [#242](https://github.com/nulavio/nulavio/issues/242) rules out.
- **Nulavio's CSS:** about six rules under `:root[nulavio-panel-opposite]` in `horizon.css` and `window-band.css`, the two defects above. An integration test reads the geometry for each layout, for both `position_start` values and in Imersivo:
  - the panel after the page;
  - the margin at the window's edge;
  - the gap between page and panel;
  - the page's width the same as with the setting off.
  That test is what notices when Mozilla's sidebar CSS changes under it, which it did in four of the last five releases.
- **Why a setting and not a preset:** it combines with every preset and with the tabs' side, and a preset would multiply the layout card's options by two.
- **Its place:** Aparência, next to the layout card: "Painel lateral do outro lado das abas" / "Side panel opposite the tabs", with a line that says the bookmarks and history panels go there too.
- **#346** then gives the panel its own edge in Imersivo "Barras".

The implementation issue is [#527](https://github.com/nulavio/nulavio/issues/527), with this design. The default and the setting's existence are the maintainer's to confirm.

## Not verified

- A drag of the splitter with the panel opposite (the probe's synthetic drag failed on 160; see above).
- RTL, and the engine's AI window turned on.
- Real desktops: the captures are headless, software-rendered, in the release test container. The arrangement does not depend on the compositor, but the window manager's own edge was not seen.
- The CSS fixes themselves: the defects are described from the captures and the rules, not fixed and captured again (that is the implementation's work).
