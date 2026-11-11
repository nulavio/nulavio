# ADR 0009 — Immersive layout: the chrome hides, the band keeps the origin on screen

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
5. **What it never does.** No protection pref is written (`shared/options.json` and its test apply). The engine's indicators are not removed or restyled: the toolbar is the engine's own, moved out of view. It is never described as spoof-proof: a page can still draw a fake bar under the band; what it cannot do is draw in the band.
6. **Where it is off: full chrome whenever something must be seen in full or the band cannot vouch for the page.**
   - Fullscreen keeps its own rules (the engine's warning and the 3 px line). Immersive's guarantee about the origin is for windowed browsing only, and Immersive resumes after fullscreen only once the band has the selected document's identity again.
   - Customize mode, an AI Workspace, a window under raw automation.
   - A pop-up or any window without the full toolbar, and picture-in-picture: never Immersive.
   - While the camera, the microphone or the screen is being shared from the window: the engine's own indicators are the cue, so the toolbar stays.
   - Any document the band has no defined label for. Defined today: `http`, `https`, `file`, Nulavio's own named pages and the engine's `about:` pages. Not defined yet, so full chrome: `about:blank` with an inherited principal, `data:`, `blob:`, `view-source:`, and anything the engine's identity box calls unknown.
   - When the registrable domain, a non-default port and the seals do not fit the row: the registrable domain is never cut; the row grows to two lines, and if that is not enough the toolbar stays.
   - At startup and after session restore, until the band, its listeners and the selected tab's committed identity are ready. A restored preference alone hides nothing.
7. **Mechanism.** No engine patch. CSS draws the two states (in the band's sheet: the toolbar and the tab list leave the flow and return over the page; times from the motion tokens, `hold` 600 ms; no transition under reduced motion). A **per-window controller** in `NulavioWindow` decides them, because CSS alone cannot: it computes eligibility (decision 6) and keeps a set of *holds* that keep the chrome shown: pointer, keyboard focus, a pin toggled from the band (the way in for touch and for anyone who cannot hover), the address results, every open panel and its anchor, permission, authentication and before-unload prompts, download warnings, a drag over the edge, an extension popup. The chrome is shown **before** the engine positions a prompt on it and stays for the prompt's whole life. It leaves only when no hold remains. The band's origin comes from one snapshot of the selected tab (committed URI, principal, the engine's identity verdict), taken on location, security and tab-switch events; a stale answer is dropped, and while there is none the chrome is shown.

## Decision needed (maintainer)

Immersive hides the engine's tracking-protection and permission icons while the toolbar is out of view. The origin, the connection state, the profile and active camera/microphone/screen use stay on screen in the band; everything else is one pointer move or one key away, and the browser shows the toolbar itself for every prompt.

This contradicts the letter of two current principles ("a layout never hides them", "there is no toolbar autohide"). **Recommendation: accept it for an opt-in mode, with the guarantees written into the principle** ("in Immersive the band carries the origin and the connection state; the toolbar is back by itself for every prompt, while a device is shared and whenever the band cannot name the page"). The alternative is option C, which Nulavio already ships, and the request stays unanswered.

## Independent review (2026-11-11)

Reviewed from the source by a second model (Codex, read-only) before the prototype was committed; verdict "accept the opt-in direction with changes". Checked point by point:

| Point | Checked | Result |
|---|---|---|
| The band had no web origin and no security-change listener | Stale: the prototype has both (`#origin`, `onSecurityChange`, the engine's `#identity-box` classes) | None |
| Special schemes, pop-ups, picture-in-picture, session restore, long hosts, ports, bidi | True: the prototype labels only `http`, `https`, `file` and `about:` and cuts nothing but has no rule for overflow | Decision 6 |
| "Never hides" was untrue in fullscreen | True | Title and decision 6 |
| `:has([open])` is not a lifetime contract for prompts; the toolbar must be in place before a prompt is anchored | True: seen in the prototype with the tab list's context menu, which closes the list | Decision 7 (controller and holds) |
| A device-use seal was promised and not built | True | Replaced by a simpler rule: full chrome while capturing (decision 6) |
| Hover-only reveal excludes touch | True | The pin in the band (decision 7) |
| It contradicts "no toolbar autohide" and "a layout never hides them" in the UX principles | True | The maintainer's decision below; the principles change in the same pull request as the feature, not before |

The prototype implements decisions 1 to 5 and the CSS of 7. The controller, the pin and the eligibility rules of 6 are the slice's work, and the security-visibility matrix repeats with Immersive on before it ships.

## Consequences

- The page gets 97 % of the window with an honest origin always on screen, which neither reference has.
- The band becomes the product's signature: the one row that is always there and always true.
- The band's centre holds the origin in Immersive and the trusted page name on Nulavio's own pages; it must update on every committed navigation and security change, synchronously, and show nothing rather than something stale while a load is committing.
- More states to test: every cue of the security-visibility matrix repeats with Immersive on.
- Extensions and password managers keep their toolbar buttons; their popups reveal the toolbar while open.

## Prototype (2026-11-11)

On the alpha's engine (160.0-0.2 build, `dev_sync`), branch `agent/claude/feat-immersive-layout`, at 1440×900:

- Page area 1440×876 (97.3 %); today's Lateral gives 1216×856 (80 %).
- The band shows `en.`**`wikipedia.org`**; an expired certificate shows "Não seguro" before the host; `localhost` is neutral, as in the address bar.
- The pointer on the band brings the toolbar down over the page; the left edge brings the tab list; Ctrl+L shows the toolbar with the address field focused.
- Known gaps: everything the review table sends to the slice; the tab list closes under its own context menu; tabs on top and a tab list on the right are not done.
