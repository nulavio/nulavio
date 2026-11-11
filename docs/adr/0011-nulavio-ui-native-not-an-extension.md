# ADR 0011 — Nulavio's own interface reads as the browser, not as an extension

- **Status:** Proposed (2026-11-11). The maintainer asked for this direction on 2026-11-11; the first two steps are built (below). Not merged.
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
2. **Lists and editors are described by the page's own registry**, the way the engine describes its lists (containers, custom home pages): one setting whose rows come from `getControlConfig`, made of the engine's rows, buttons, fields and pickers, with clicks read from the row's button. Nothing is built from markup strings, and the page's search finds the words. Step 1 used a custom element for the list; step 2 found the registry does it and replaced it. A custom element stays the fallback for something the registry cannot describe; none is needed so far.
3. **One set of words for an action.** A button, a confirmation or an error says the same thing wherever it is offered: the settings page takes those words from the Shell's own messages (`_locales`), the ones the band, the menu and the Shell's pages use. Fluent (`settings.ftl`) holds what only this page says: its panes, groups and row descriptions.
4. **The security moments stay unprivileged pages**: unlock, create, the Guard's review, consent, warnings, the new tab. The band names them ("Nulavio · Desbloqueio"); that naming is drawn by privileged code and is the part a page cannot fake.
5. **How those pages look in the address bar is a separate, small question**, listed for the maintainer: the label patch, the `about:` addresses with one hashed inline script per page, or leaving it. They are not made privileged pages.
6. **Code moves into the engine tree only piece by piece**, when a piece cannot be done from a module, a theme sheet or the settings registry. Each such piece is a patch with its own reason, as today.

## What stays undecided (maintainer)

- **The address bar on the security moments.** Recommendation: the label patch first (it is one condition in one engine file, and the result reads like the browser's own pages); `about:` addresses only if the inline script and its hash are accepted as an exception to the Shell's rules. Either needs a real build to verify, so neither is done here.
- **Whether any Shell page should become privileged.** Recommendation: none. The boundary is a protection; removing it is the kind of change this project lists instead of making.

## Step 1 (2026-11-11): the profiles of the group, listed by the settings page

Branch `agent/claude/feat-settings-profiles-native`, on the alpha's engine by `dev_sync` (no engine build).

![The "Perfis e proteção" pane with one row per profile, pt-BR light and en-US dark](../design/screenshots/experience-2026-11/settings-profiles-sheet.png)

- `nulavio-profile-list`, at this step a custom element (replaced by a registry list in step 2, see decision 2): one row per profile with its protection as it is now ("Este perfil. Sem senha.", "Protegido e bloqueado: criptografado no disco."), built from the engine's rows with the DOM. The profile's name goes in as a Fluent argument, never as markup.
- It follows the group: a profile created, renamed, locked or removed elsewhere shows without a reload. A list that cannot be read is not drawn and the group says so.
- The page's own search finds a profile by its name.
- `test_settings_native` `test_06b` covers the list with unprotected profiles, the update without a reload, the search and the failed read. The rows of a protected profile (locked, unlocked) are drawn from the same read but no test creates a protected profile here yet.

Still the old page's after this step: creating, renaming, protecting and removing a profile, and the routing rules.

## Step 2 (2026-11-11): everything a person does with a profile, in the settings page

Branch `agent/claude/feat-settings-profile-actions`, on the alpha's engine by `dev_sync` (no engine build).

![The "Perfis e proteção" pane: the list with each profile's actions, the editor open under a row, and the new-profile row; pt-BR light and en-US dark](../design/screenshots/experience-2026-11/settings-profile-actions-sheet.png)

- **The list is a registry list** (decision 2). Each row shows the profile's own icon in its own colours (the engine's profile icons; tile and glyph from the design tokens, through the sheet Nulavio already gives the engine's pages) and the actions that profile can take now: open, or unlock when it is locked; lock now; the ways it unlocks; edit; delete. Each button's accessible name says whose it is ("Abrir Trabalho").
- **Editing opens under the row**: name, icon and colour, with the engine's visual picker (the profile's icon in every choice, each choice named), and the engine's Cancel/Save pair in the desktop's order. Only what changed is written.
- **A new profile is the last row of the list**: a template only fills a free name ("Trabalho 2") and never replaces a name the person typed; nothing exists before "Criar perfil".
- **Confirmations are the engine's own prompt**, with the Shell's words and Cancel as the default button: deleting a profile, and locking the profile in use (it closes its windows).
- **The Vault's moments stay the Vault's pages** (decision 4): unlocking, the ways a profile unlocks, and creating a protected profile (its recovery code is shown once) open those pages; the settings page never asks for a password.
- **Every change goes through `NulavioProfiles` and `NulavioVault`**, the modules the Shell's pages call, with the same checks; a refusal is said in the Shell's words for its code ("Esse nome já está em uso."). A group that cannot be used (a temporary profile, profiles turned off, a window started with `--profile`) says why and offers nothing.
- The Shell's old page keeps its profiles section by address only: it left that page's navigation and search, and its "Criar perfil" link in the routing rules opens the settings page.

**Independent review** (Codex gpt-6-astra, high effort, read-only, 2026-11-11; 0 high, 4 medium, 3 low). Each point was checked against the code before anything changed; all seven were true.

| Point | What was wrong | What changed |
|---|---|---|
| A save could put an old name back | The editor compared its fields with the profile as read now, not as it was when the editor opened: renamed elsewhere, a save of the colour alone sent the old name too | The editor keeps what it opened with and writes only what the person changed since. A field they did not touch follows the profile while the editor is open; one they changed keeps what they typed |
| A save closed another row's editor | The editor that was open when a save answered was closed, whichever it was | A save closes only its own editor |
| A click while an action ran was dropped unseen | One action at a time, and a second click did nothing, with its button still enabled | While an action runs, the list's buttons are disabled |
| Words that outlived what they said | "Trabalho está bloqueado." stayed after it was unlocked elsewhere | What an action said stays while the list stays as that action left it, and leaves when the list changes again |
| Focus after a deletion | The profile before the deleted one was found by object, lost when the list was read again under the prompt | Found by its key |
| A prompt taken away | A rejected prompt was an unhandled rejection | Nothing was confirmed: logged, and nothing happens |
| A length limit that limited nothing | `maxlength` on the engine's text field is not passed to its input | Removed; the module's own check answers ("Informe um nome (até 60 caracteres).") |

The review also named the weakest assertions (a colour only had to be non-empty): the tests now compare the row's and the picker's colours with the design tokens. `test_05b` covers the first four points. Not covered by a test: the focus after a deletion with the list re-read under the prompt, and a rejected prompt (the test driver cannot act while the engine's prompt is open).

`tests/integration/test_settings_profiles.py` (7 tests) acts as a person does and reads the result from the module: the actions per row and their names, opening and a refusal, the doors around the list; editing with a taken name, saving name, icon and colour, cancelling, writing only what changed; deleting with the prompt cancelled and then accepted; creating with and without a template; a group that cannot be used. The rows and actions of a **protected** profile are checked with a list the test gives the module and with the Vault's entries replaced: no protected profile is created there (that needs the Vault's tools), so locking and unlocking for real stay covered by the Vault's own tests.

Still the old page's after this step: the routing rules (step 4). Then search, passwords, exceptions and the assistant, and the removal of the old page's sections with their tests.

## Step 3 (2026-11-11): what the content filter blocks, one row away

Branch `agent/claude/feat-settings-filter-lists`.

![The "Proteções do Nulavio" group with the row that opens uBlock Origin's filter lists](../design/screenshots/experience-2026-11/settings-filter-lists.png)

Ads, trackers and cookie notices are blocked by uBlock Origin's lists, and nothing in Settings led to them. "Privacidade e Segurança" now has a row that opens uBlock Origin's own "Filter lists" page. Nulavio reads only whether uBlock Origin is on (the add-on manager's answer, as before) and never its data: which lists are ticked is said on its page, not guessed here. With uBlock Origin off or missing, the row says so and opens "Extensões e temas". `test_settings_native` `test_06a` covers both states and the address the module opens.

Not decided (maintainer): showing the real state in the row ("cookie notices: hidden" or "shown") means reading uBlock Origin's own settings. Recommendation: allow reading, never writing, and say so in the words that today promise Nulavio "never alters" its data.

## Step 4 (2026-11-11): which site opens in which profile

Branch `agent/claude/feat-settings-routing-native`.

![The routing rules in the "Perfis e proteção" pane, pt-BR light and en-US dark](../design/screenshots/experience-2026-11/settings-routing-sheet.png)

- The routing rules are a group of the profiles pane, under the profiles they point to: the two switches (use the rules; also for links clicked in pages, off unless the person turns it on), the default destination for links from other apps, the rules, and a new rule as the last row of the list.
- A rule's row shows the icon of the profile it opens in, the site, and what it does ("Bancos · Abrir nele"); a rule whose profile was deleted says so. A default destination that was deleted keeps its own disabled entry and a warning, as on the old page: a profile created later can take the same id and must never become the destination by itself.
- With one profile there is nowhere to send a site: the group says so and offers no empty form; the list above it is where a profile is made.
- Every change goes through `NulavioRouting`, which checks each rule as before; a refusal is said in the Shell's words ("Esse endereço de site não é válido.").
- The list and the working state share one small helper with the profiles (`workbench`: what the page holds while the person works, one action at a time, the bars).
- The old page's routing section left its navigation and search; it still opens by address, and the pages that explain a routed link ("As regras ficam em Configurações, em Perfis e proteção") already named this pane.

`tests/integration/test_settings_routing.py` (3 tests): a refused site, a rule added, "never switch" without a profile, a rule made elsewhere joining the list, a rule removed (and where the keyboard goes), a rule whose profile was deleted; the switches and what they disable; the default destination chosen, deleted and reset; one profile alone, then a second one.

Still the old page's: search, passwords, exceptions, DNS and the assistant, and the removal of the old page's sections with their tests.

