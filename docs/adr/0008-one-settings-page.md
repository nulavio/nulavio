# ADR 0008 — One settings page: Nulavio's options inside the engine's about:preferences

- **Status:** Proposed (2026-11-11), with a working proof of concept on the engine (below). Not merged.
- **Related:** [references](../design/references/2026-11/README.md), the frontend audit of 2026-11 (pull request #41), [ADR 0003](0003-nulavio-profiles-and-routing.md), [ADR 0007](0007-ai-bridge.md), [UX principles](../design/ux-principles.md).

## Context

Nulavio has two settings pages. The engine's `about:preferences` holds search, privacy, passwords, appearance, tabs, languages and the rest. "Configurações do Nulavio" is a page of the Shell add-on (`moz-extension://…/settings/settings.html`) with layout, appearance, shortcuts, search, passwords, site exceptions, DNS, profiles, routing, AI and integrations. Seen on 2026-11-11 (160.0-0.2, `main` at `388800e`, pt-BR):

- Two navigations, two card styles, two type scales. "Aparência" exists in both. "Pesquisa" in one is "Busca" in the other. "Senhas e preenchimento automático" in one, "Senhas" in the other.
- The address bar calls Nulavio's page "Extensão (Nulavio Shell)". It reads as an add-on, because it is one.
- The engine's page opens on "Conta e sincronização", which Nulavio has turned off, and offers "Controles de inteligência artificial" and "Firefox Labs" for features Nulavio has turned off.
- A person who wants to hide the tab strip has to guess which page owns that.

The options were grouped by who wrote the code. The person does not care who wrote it.

What others do, seen on the same day: **Zen** puts its panes into `about:preferences` (one page; it does so with engine patches, and its panes use an older widget set than the page around them). **Floorp** keeps a separate "Hub" and a banner that sends people there: the same split Nulavio has. **Helium** extends its engine's settings page in place.

Firefox 160's settings page is built from data: a pane is a list of groups (`SettingPaneManager`), a group is a list of controls (`SettingGroupManager`), a control reads and writes a `Preferences` setting, and the engine's own widgets draw them (`moz-visual-picker`, `moz-toggle`, `moz-radio-group`, `moz-box-link`…). The page's search indexes whatever is registered.

## Options

| Option | For | Against |
|---|---|---|
| A. **Native panes and groups registered by a privileged Shell module** | One page, one look, the engine's own widgets and search; no engine patch; ships through `dev_sync` and a normal build alike; the engine's panes keep their code | Depends on the page's internal registry (`SettingPaneManager`, `SettingGroupManager`), which can change between engine releases; complex screens (profiles, agents) need custom elements |
| B. Engine patch that adds the panes to `preferences.xhtml` (Zen's way) | Same result for the person | A patch to carry on every engine update, against the patch policy ("prefer prefs, policies, branding or built-in add-ons over patches"); every copy change needs an engine build |
| C. A Nulavio hub that absorbs the engine's options and replaces `about:preferences` | Full control of the look | Re-implements hundreds of engine settings, including security ones; each engine release can add or change one silently; a missed option is a protection people cannot reach; the largest surface to keep honest |
| D. Keep two pages, restyle and cross-link | Cheap | Still two places (Floorp's banner). Does not answer the complaint |

## Decision

1. **A.** The Shell registers its settings in `about:preferences` as native groups and panes. `about:preferences` is the one settings page. The add-on page is retired section by section and then removed.
2. **Mechanism.** `NulavioSettings.sys.mjs` observes `chrome-document-global-created`. For a system-principal `about:preferences` (or `about:settings`) document, and nothing else, it imports `settings/native/panes.mjs` into that document's own global at `DOMContentLoaded`, before the page's own listener, through the window's own module loader (`win.ChromeUtils.importESModule(…, { global: "current" })`, a fixed `resource://` address). No script loader and no evaluated text: the Shell's rule against `loadSubScript` stands. The module calls the same registry the engine's panes call. Words are Fluent (`l10n/<locale>/nulavio/settings.ftl`, registered as an `L10nFileSource`), en-US and pt-BR together.
3. **One seam.** The page registers its own panes right after our module runs, so an engine pane that gains a Nulavio group is edited as it is registered (a wrapper around `SettingPaneManager.registerPane`). That is the only place the page's code is intercepted, and `test_settings_native` fails if the seam stops working.
4. **What happens when it fails, stated as a contract and not as a promise.**
   - *Before anything is registered* (the module cannot load, the registry is missing or has another shape): a preflight checks the registry's functions first; nothing is changed and the page is the engine's stock page.
   - *While registering*: every Nulavio group and pane is added inside one guarded step that records what it added; on an exception the wrapper is removed, what was added is unregistered, and the page continues as the engine's. A Nulavio option that could not be shown is reachable from the band's menu until the old page is removed, and after that from a plain fallback page.
   - *After the page is built* (a setting cannot be read or written): the control shows the unknown or failed state in words and is disabled; it never shows a value it did not read.
   - Nothing of the engine is hidden before Nulavio's part is in place, in any of the three.
   The proof of concept implements the first and the last line; the middle two are part of slice 1.
5. **Organised by what the person is doing**, not by origin. A Nulavio group goes into the engine pane it belongs to; a pane is new only when the engine has no home for it:

   | Order | Pane | Engine groups | Nulavio groups |
   |---|---|---|---|
   | 1 | Início | default browser, import | where you are (profile, protection), continue the first-run steps |
   | 2 | Aparência | website appearance, theme, density | **tabs and window layout** (first), Nulavio colours |
   | 3 | Perfis e proteção (new) | — | profiles, protection methods, temporary profiles, routing rules |
   | 4 | Privacidade e segurança | as today | site exceptions, DNS, what changed outside Nulavio (Guard) |
   | 5 | Pesquisa | as today | engines with per-engine suggestion consent |
   | 6 | Senhas | as today | which manager is in use |
   | 7 | Assistente e IA (new) | — | assistant, agents, emergency stop, activity |
   | 8 | Abas e navegação, Página inicial, Downloads | as today | — |
   | 9 | Atalhos (new) | — | Nulavio's keys and the link to the engine's |
   | 10 | Acessibilidade, Idiomas, Permissões e dados | as today | — |
   | 11 | Integrações (new) | — | desktop integrations |
   | 12 | Sobre o Nulavio | as today | — |

6. **Nothing that is a protection moves or changes meaning.** The engine's privacy, security, permissions and password panes keep their code, order and wording. Nulavio adds groups next to them; it never replaces one.
7. **Three ways to host a Nulavio section**, chosen per section:
   - *Declarative* (layout, colours, DNS choice, search consent, shortcuts list): settings and groups only. This is the default.
   - *Custom element* in a group (profiles list, routing rules, agents): a small web component registered by the same script, drawn with the engine's widgets and tokens.
   - *Not embedded*: the existing security moments (unlock, create a protected profile, agent request, Guard review) stay their own pages with the band naming them. Settings link to them; they are not settings.
8. **Entry points.** Every "Configurações do Nulavio" entry (band, new tab, quick action, profile menu, add-ons manager) opens `about:preferences` at the right pane. The old address redirects while sections remain there.

## What stays undecided (maintainer)

- **"Seu navegador está sendo gerenciado pela sua organização."** Everyone sees it, because Nulavio ships its own `policies.json`. It is true and it trains people to ignore a line that would also be the only sign of a policy someone else added. Recommendation: keep the line only when the active policies differ from the ones Nulavio ships (the Guard already tracks policy changes), and say "Nulavio aplica N políticas próprias" in "Sobre" otherwise. It touches a security cue, so it is not changed without a decision.
- **"Conta e sincronização", "Controles de inteligência artificial", "Firefox Labs".** Recommendation: hide each only while the feature behind it is unavailable **as read at that moment** (accounts disabled by policy, every engine AI feature off, no experiment offered), never on the assumption that it is; a pane with one live control stays, and its address keeps working. With accounts off the landing pane becomes "Início". Nulavio's "Assistente e IA" pane sits next to the engine's AI controls when both exist; it does not replace them.

## Consequences

- One address, one navigation, one search. A person finds "tabs on the side" under Aparência whoever wrote it.
- Nulavio's settings are drawn by the engine's widgets: its focus, contrast, forced-colours and RTL behaviour come with them, and the Shell's own form components shrink to the security moments.
- The Shell depends on the settings page's registry. It is not a public API. Each engine update needs the settings tests to pass before release; if the registry changes shape, the panes need porting (option B remains the fallback for that release).
- The injected script runs with the system principal, like the page it extends. It loads only from the Shell's own `resource://` path, never takes text from the web, and builds no markup from strings.
- `shared/options.json` and its test (no option may write a protection pref) keep applying: the same options, a different host.
- The retired add-on page removes about 2,000 lines of form code once every section is moved.

## Proof of concept (2026-11-11)

On the alpha's engine (Nulavio 160.0-0.2 build, `dev_sync`, no engine build), branch `agent/claude/feat-unified-settings`:

- `NulavioSettings.sys.mjs` (about 70 lines) and `settings/native/panes.mjs` (about 170 lines) register: the layout choice (Lateral, Abas no topo, Foco) as the first group of the engine's Aparência pane, drawn by `moz-visual-picker`; "Cores do Nulavio" (accent, more contrast, new-tab background) after the engine's density group; and a new "Perfis e proteção" pane with its navigation entry.
- Choosing "Abas no topo" in that card moved the tabs of the real window (`sidebar.verticalTabs` false, checked in the window).
- pt-BR and en-US, light and dark: the same card style as the engine's groups; the previews follow the colour scheme.
- The page's search for "contraste" lists the engine's "Contraste de sites" and Nulavio's "Cores do Nulavio" in one result page.
- When the script threw (the first attempt did, on a pane that was not registered yet), the page opened as the engine's stock page.

- `tests/integration/test_settings_native.py` (three tests, on the package after `dev_sync`): the layout group is first in the engine's Aparência pane with every engine group still there in order; the card changes `sidebar.verticalTabs`; the words come in pt-BR and en-US. The same tests fail on the package without this change.

Not yet proven: the rollback of a failure halfway; session restore, `about:settings`, two windows and the back-forward cache; a custom element for the profiles list; the redirect of the old address; removal of the add-on page; the page under a screen reader.

## Independent review (2026-11-11)

Reviewed from the source by a second model (Codex, read-only); verdict "accept with changes". Each point was checked before it changed this record:

| Point | Checked | Result |
|---|---|---|
| The fail-open promise was universal; it holds only before registration | True: a throw halfway left the wrapper installed | Decision 4 rewritten as a contract; slice 1 implements it |
| The ordering against the page's own listener is observed, not a contract (session restore, the `about:settings` alias, two windows, a document from the back-forward cache) | True for the cases not run | Listed under "not yet proven"; each gets a test in slice 1 |
| Management, account and AI controls must not be hidden on assumptions | Agreed | Rewritten above; still the maintainer's decision |
| A setting backed by an async read shows its default until the read returns | True in `panes.mjs` (`layout` starts as "lateral") | Slice 1: the control is disabled and says "lendo…" until the first read; a stale answer is dropped |
| `stop()` leaves open settings pages extended; the layout subscription is tied to the window the tab was in | True | Slice 1 |
| Search finds only what is rendered | True: a custom element must render its words to be found | A rule for decision 7's custom elements |

Found while answering the review: the first proof of concept used `loadSubScript`, which the Shell's own static check forbids. It now imports a module through the page's loader (decision 2), and the check passes.

## Implementation order

1. The host module, the layout and colours groups, the navigation order, tests (this proof of concept, hardened).
2. Search, DNS, site exceptions, passwords provider, shortcuts (declarative).
3. Profiles and protection, routing (custom elements).
4. Assistant and agents (custom elements; the consent dialogs stay as they are).
5. Entry points and the redirect; remove the add-on page.
