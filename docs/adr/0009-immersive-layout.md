# ADR 0009 — Immersive layout: the chrome hides, the band and the origin never do

- **Status:** Proposed (2026-11-11), with a prototype on the engine (below). Not merged. One point needs the maintainer (see "Decision needed").
- **Related:** [references](../design/references/2026-11/README.md), [UX principles](../design/ux-principles.md), [design system: UX3A band](../design/design-system.md), [ADR 0008](0008-one-settings-page.md).

## Context

In the default layout (Lateral) Nulavio gives the page 80 % of a 1440×900 window: a 44 px row on top and a 224 px column of tabs. Measured on the same day, Zen gives 85 % by default and 97 % in compact mode; Helium about 99 % in frameless mode. The maintainer asks for a mode that hides what is not needed and shows it when needed.

Both references hide everything, the address included. A page that owns every pixel can draw an address bar, a padlock and a permission prompt of its own. Fullscreen has the same problem, which is why browsers announce it. Nulavio's rule so far: "the address-bar trust, tracking and permission indicators stay exactly as upstream; a layout, density, theme or fullscreen never hides them".

Nulavio already has something the references lack: the band, a row only the browser can draw, which names the profile and its protection and is never hidden.

## Options

| Option | Page area at 1440×900 | Origin while hidden | Notes |
|---|---|---|---|
| A. Hide everything until an edge is hovered (Helium, Zen) | 97–99 % | none | Spoofable; breaks the rule above |
| B. **Hide the toolbar and the tabs; the band stays and carries the origin** | 97 % (876 of 900 px high, full width) | host, connection state and profile, always | One 24 px row. The band already exists |
| C. Hide the tabs only (today's Foco) | 84 % | the whole address bar | Already shipped; not what was asked |
| D. Hide all, show a 3 px state line (as in fullscreen) | 99.7 % | state only, no host | The host is the anti-spoofing fact; a colour line is not enough |

## Decision

1. **B, as "Imersivo".** It is a switch on top of the chosen tab layout (Lateral, Abas no topo or Foco), per profile, off by default, with a key and an entry in the layout card. It is never applied by itself and never the default of a new profile.
2. **What never hides.** The band's row: profile and protection on the left, **the origin in the middle**, the state seals (private, temporary, agent, raw automation, Guard) on the right. The origin is the committed document's host with its registrable part emphasised, a connection glyph and, when the connection is not secure, the words. It comes from the engine's own state for the selected tab (`currentURI`, `securityUI.state`), never from the page. For Nulavio's own pages the band's trusted name ("Nulavio · Desbloqueio") is the origin.
3. **What hides.** The navigation toolbar, the tab list (side or top) and the bookmarks bar. They are taken out of the layout and drawn over the page when revealed, so the page never moves.
4. **What reveals them.**
   - the pointer on the band or at the top edge brings the toolbar down; at the side edge, the tab list in;
   - the keyboard: anything that focuses the toolbar (Ctrl+L, Ctrl+T, F6, Alt) or the tab list;
   - the browser itself, while something anchored there is open: the address results, a permission or download panel, a menu, an extension popup, the identity panel;
   - an event the person did not cause: a permission request, a download warning, a blocked pop-up, a tab opened in the background. The toolbar shows for as long as the engine shows its panel, or briefly for a background tab.
   They leave 600 ms after the pointer and the focus are gone. Reveal takes 150 ms, leave 200 ms; with reduced motion both are instant.
5. **What it never does.** No protection pref is written (`shared/options.json` and its test apply). The engine's indicators are not removed or restyled: the toolbar is the engine's own, moved out of view. Camera, microphone and screen sharing get a seal in the band while active, because their toolbar indicators are out of view.
6. **Where it is off.** Fullscreen keeps its own rules (the 3 px line). Customize mode, an AI Workspace and a window under raw automation show the full chrome: those are states where the person must see everything.
7. **Mechanism.** No engine patch. A root attribute (`nulavio-immersive`) set by `NulavioLayout` from a pref; CSS in the band's sheet takes the toolbar and the tab list out of the flow (`position: fixed`, `translate`) and brings them back on `:hover`, `:focus-within` and `:has([open])`; a thin hot zone at the side edge; the band draws the origin from a progress listener it already has. Timings come from the motion tokens.

## Decision needed (maintainer)

Immersive hides the engine's tracking-protection and permission icons while the toolbar is out of view. The origin, the connection state, the profile and active camera/microphone/screen use stay on screen in the band; everything else is one pointer move or one key away, and the browser shows the toolbar itself for every prompt.

This contradicts the letter of the current principle ("a layout never hides them"). **Recommendation: accept it for an opt-in mode, with the four guarantees above written into the principle** ("in Immersive the band carries the origin, the connection state and active device use; the toolbar returns by itself for every prompt"). The alternative is option C, which Nulavio already ships, and the request stays unanswered.

## Consequences

- The page gets 97 % of the window with an honest origin always on screen, which neither reference has.
- The band becomes the product's signature: the one row that is always there and always true.
- The band's centre holds the origin in Immersive and the trusted page name on Nulavio's own pages; it must update on every committed navigation and security change, synchronously, and show nothing rather than something stale while a load is committing.
- More states to test: every cue of the security-visibility matrix repeats with Immersive on.
- Extensions and password managers keep their toolbar buttons; their popups reveal the toolbar while open.

## Prototype (2026-11-11)

On the alpha's engine (160.0-0.2 build, `dev_sync`), branch `agent/claude/feat-immersive-layout`: see the captures and measurements in the pull request.
