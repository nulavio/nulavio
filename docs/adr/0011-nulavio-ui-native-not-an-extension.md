# ADR 0011 — Nulavio's own interface reads as the browser, not as an extension

- **Status:** Proposed (2026-11-11). The maintainer asked for this direction on 2026-11-11; the first step is built (below). Not merged.
- **Related:** [ADR 0001](0001-engine-selection.md) (patch policy), [ADR 0008](0008-one-settings-page.md) (one settings page), [extension model](../architecture/extension-model.md).

## Context

The maintainer's question, after using the alpha: why is Nulavio's own interface an extension, with its settings in an extension page, when only the engine is someone else's? "Only the engine is needed; everything else should be ours to change."

What is an extension today, and what is not:

- **Not an extension in any sense that matters**: the identity band, the Vault, the Guard, profiles, routing, the layout and the theme. About 8,400 lines of privileged modules (`browser/shell/modules/*.sys.mjs`) and the theme sheet run as parts of the browser. The built-in add-on is how they are packaged and started.
- **An extension in what a person sees**: fifteen HTML pages (new tab, the Vault's screens, the Guard's review, the consent and warning pages, the old settings page). Each opens at `moz-extension://<random id>/…`, and the address bar labels it "Extensão (Nulavio Shell)". The engine does that for any page whose address belongs to an add-on (`browser-siteIdentity.js`: `WebExtensionPolicy.getByURI(uri)`, class `extensionPage`).

The split exists because of ADR 0001's patch policy ("patches only for what prefs, policies, branding or built-in add-ons cannot do": nine patches today; Zen carries 272). It was a maintenance decision, and it bought a second thing that is easy to miss: **the pages are not privileged**. They reach the modules only through declared interfaces whose arguments the engine validates, under a strict content security policy. A mistake in a page cannot run code as the browser.

## What was checked on the engine (Firefox 160)

| Route | Checked | Result |
|---|---|---|
| Settings drawn by the engine's own page | Built (ADR 0008, slices 1 and after) | Works with no patch. Runs with the page's own (system) privilege; draws no markup from strings and uses the engine's widgets |
| An `about:` address for a Shell page | The engine's own built-in add-on does it (`webcompat` registers `about:compat` from a process script, loading its page with the add-on's principal) | Possible with no patch, **but** the page's address becomes its base for relative links, so every page needs a `<base>` set by an inline script, allowed by a hash added to the content security policy (the engine's page does exactly that). Two of the Shell's own rules forbid it: no inline script, no change to the policy (`test_shell`) |
| The Shell's pages as privileged (`chrome:`) pages | Not built | Gives the address and removes the extension label, and removes the boundary described above: a page's mistake becomes the browser's |
| The label only | Read in the engine's source | One small engine patch could show the brand ("Nulavio", as on the settings page) for pages of the built-in Shell. The address would still be `moz-extension://…`. Needs an engine build to verify |

## Decision

1. **Everything that is a setting is drawn by the browser's settings page**, natively, until the Shell's settings page is gone (ADR 0008). This is where "one place, part of the browser" is fully reachable with no patch and no relaxed rule.
2. **Lists and editors that the registry cannot describe** (profiles, routing rules, agents) are custom elements registered by the same module, built with the engine's widgets and the DOM, never from markup strings, and they render their words so the page's search finds them. Step 1 below is the first.
3. **The security moments stay unprivileged pages**: unlock, create, the Guard's review, consent, warnings, the new tab. The band names them ("Nulavio · Desbloqueio"); that naming is drawn by privileged code and is the part a page cannot fake.
4. **How those pages look in the address bar is a separate, small question**, listed for the maintainer: the label patch, the `about:` addresses with one hashed inline script per page, or leaving it. They are not made privileged pages.
5. **Code moves into the engine tree only piece by piece**, when a piece cannot be done from a module, a theme sheet or the settings registry. Each such piece is a patch with its own reason, as today.

## What stays undecided (maintainer)

- **The address bar on the security moments.** Recommendation: the label patch first (it is one condition in one engine file, and the result reads like the browser's own pages); `about:` addresses only if the inline script and its hash are accepted as an exception to the Shell's rules. Either needs a real build to verify, so neither is done here.
- **Whether any Shell page should become privileged.** Recommendation: none. The boundary is a protection; removing it is the kind of change this project lists instead of making.

## Step 1 (2026-11-11): the profiles of the group, listed by the settings page

Branch `agent/claude/feat-settings-profiles-native`, on the alpha's engine by `dev_sync` (no engine build).

![The "Perfis e proteção" pane with one row per profile, pt-BR light and en-US dark](../design/screenshots/experience-2026-11/settings-profiles-sheet.png)

- `nulavio-profile-list`, the first custom element in the settings page (decision 2): one row per profile with its protection as it is now ("Este perfil. Sem senha.", "Protegido e bloqueado: criptografado no disco."), built from the engine's rows with the DOM. The profile's name goes in as a Fluent argument, never as markup.
- It follows the group: a profile created, renamed, locked or removed elsewhere shows without a reload. A list that cannot be read is not drawn and the group says so.
- The page's own search finds a profile by its name.
- `test_settings_native` `test_06b` covers the list with unprotected profiles, the update without a reload, the search and the failed read. The rows of a protected profile (locked, unlocked) are drawn from the same read but no test creates a protected profile here yet.

Still the old page's: creating, renaming, protecting and removing a profile, and the routing rules. They are the next steps of decision 1, each with its confirmations as they are today.
