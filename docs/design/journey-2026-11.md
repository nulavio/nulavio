# The journeys, as they are and as they should be (2026-11)

Seven journeys a person takes with Nulavio, each walked on the alpha (160.0-0.2 build with `main` by `dev_sync`, 1440×900, pt-BR and en-US) and set against what was seen in the [references](references/2026-11/README.md). Three sources, kept apart:

- **Walked here**: driven with real pointer and keys on a private display, with captures.
- **New-user QA**: a second model (Codex) walked the journeys in a clean profile from a closed brief, with real clicks and its own captures. Its findings are numbered F1–F9 below. Each was checked before it was used; one was a limit of the test launcher and is marked.
- **Not walked**: said so. Nothing is inferred for those.

The complaint that started this: "it looks like nobody thought about the journey". The table at the end says where that is true.

## 1. Install

**Not walked in this round.** The browsers here ran from unpacked packages. What a person meets between the site and the first window (the repository file, the package manager's key prompt, the launcher entry) needs a clean machine or a container with a desktop session. It is the first slice's first task, because the first run below starts where the install ends.

## 2. First use

| | |
|---|---|
| Today | The first window is a new tab: a search field, then a welcome card, then a status card. On the first frame the card says "Você já começa protegido" while the status says "Precisa de atenção: Filtro de conteúdo, Senhas" in the warning colour: the content filter is still being installed and is there about 20 s later (F1; walked here too). Four steps follow in the same card, which changes size and place between them (it moves down for the DNS step, where the symbol appears, and back up for the passwords step). The steps are layout, DNS, passwords, default browser. Nothing shows the band, profiles or protection, which is what the product is for |
| Where the person gets lost | Protected or not? (F1). "Resolvedor" and encrypted DNS with no recommendation in plain words (F2). Three password managers named with no reason to pick one. "Regras de roteamento" mentioned in the last step and never explained. The toolbar, the tab column and the page all compete while a question is being asked |
| References | Zen: the welcome owns the window, one decision per screen, the choice drawn as the thing itself. Helium: "Use defaults / Configure" on the first screen with the consequence of the default in one line; every option with its trade-off; a password-manager step |
| To be | **The first run is a stage** ([ADR 0010](../adr/0010-experience-direction.md)): the window shows the band and one card of a fixed size. First screen: what Nulavio is in one sentence that points at the band, then "Configurar em 1 minuto" or "Usar os padrões", with the defaults said in one line. Only facts that are already true are listed; something still arriving (the filter) is read again for the summary, where a real problem is reported as one. Each step keeps the card's place and size and its actions' place. Prototype on the engine: [light, pt-BR](screenshots/experience-2026-11/stage-sheet-pt-light.png), [dark, en-US](screenshots/experience-2026-11/stage-sheet-en-dark.png) |
| Still to do in the slice | The DNS step in plain words with a recommendation ("Deixar como está" first, said as what it means); the password step with one line per manager and what it costs; a step that shows the band and offers to protect the profile now or later; the choices as pictures in a second pane, as the layout step already is; tests |

## 3. Create and protect a profile

| | |
|---|---|
| Today | Reached from "Perfis" in Nulavio's settings, from the band's menu or from the profile manager. Creating, the recovery code, locking and unlocking exist as their own pages, named in the band ("Nulavio · Desbloqueio") |
| Walked | **Not walked end to end in this round.** The clean-profile launcher starts with `--profile`, and in that mode the profile manager refuses to switch and says so in the launcher's terms (F6). That refusal is correct, but the page still offers "Abrir o gerenciador completo", which leads to the same refusal |
| Where the person gets lost | The first run never says profiles exist. A person who finds "Perfil padrão · Sem senha" in the band has no next step offered there. Under `--profile` the manager link is a dead end |
| To be | The first run's band step. In the band's menu, "Sem senha" is followed by "Proteger este perfil". In the unified settings, "Perfis e proteção" is the second pane ([ADR 0008](../adr/0008-one-settings-page.md)). Under `--profile` the manager link is not offered; the page says in plain words that this window was opened for one profile |

## 4. Unlock

**Not walked in this round** (it needs a protected profile, see 3). The frontend audit of 2026-11 covered the unlock page's states and found no HIGH or MEDIUM defect in the page itself. Its journey (cold start to first page, a wrong password, the phone) is part of the profile slice's QA.

## 5. Configure

| | |
|---|---|
| Today | Two pages: the engine's `about:preferences` and "Configurações do Nulavio". "Aparência" exists in both; "Pesquisa" in one is "Busca" in the other. The address bar calls Nulavio's page "Extensão (Nulavio Shell)" |
| New-user QA | Changing the search engine, the layout and the contrast took about 7 clicks and one miss: choosing "Foco" moves the settings navigation under the pointer (F4). "Mais contraste" says it is for Nulavio's windows and that site contrast is "nas configurações do navegador", without saying where (F5). A panel opened in the side bar was clipped behind the tab rail once (F9, not reproduced) |
| References | Zen puts its panes inside `about:preferences`. Floorp keeps a second hub with a banner pointing at it: the same split, and the clearest argument against it |
| To be | **One page** (ADR 0008): Nulavio's options are native groups inside the engine's panes, ordered by what the person is doing. Proven on the engine: the layout choice is the first card of "Aparência", and the page's search finds the engine's "Contraste de sites" and Nulavio's "Cores do Nulavio" together, which answers F5. F4 goes away with the page: the engine's settings navigation does not move with the tab layout |

## 6. Daily use

| | |
|---|---|
| Today | Lateral gives the page 1216×856 of 1440×900, 80 %. The frame has three tones (band, toolbar, tab column). "Foco" collapses the tab column to icons (84 %); the names need a hover (F7) |
| References | Zen 85 % by default and 97 % compact; Helium about 99 % frameless. Both hide the address completely |
| Where the person gets lost | Not lost: crowded. The request is a mode that shows only what is needed |
| To be | **One surface** for the frame and the page as a card (direction A), and **Imersivo** as an opt-in mode on top (direction B, [ADR 0009](../adr/0009-immersive-layout.md)): the toolbar and the tabs leave, the band stays with the site's name, 97 % for the page. Prototypes: [light, pt-BR](screenshots/experience-2026-11/dir-sheet-pt-light.png), [dark, en-US](screenshots/experience-2026-11/dir-sheet-en-dark.png) |

Opening pages, switching tabs, a private window and back all worked for the new user without help (QA section 4).

## 7. Assistant

| | |
|---|---|
| Today | An "N" button in the toolbar opens the profile menu, not the assistant. The assistant is set up under "IA e automação" in Nulavio's settings: a provider form with "Compatível com OpenAI", service address, model and API key |
| New-user QA | The chat was not found in about 5 actions and 60–90 s (F8). The form assumes the person knows what a provider, a model and a key are |
| Where the person gets lost | At the first step: nothing says where the assistant is. Then at the form |
| To be | One entry with a name ("Assistente") in the side bar and in the quick actions. Opened with no provider, it says what it does, what leaves the computer and when (nothing before "Enviar"), and offers "Conectar um serviço" as a short sequence: pick a service from a list, paste the key, test. The raw fields stay under "Avançado". The consent rules of ADR 0007 do not change. Not prototyped in this round |

## Where nobody thought about the journey

| # | Moment | Journey | Evidence | Answered by |
|---|---|---|---|---|
| 1 | Two settings pages; the person guesses which one owns an option | Configure | walked; F5 | ADR 0008, proof of concept and first tests |
| 2 | "Protegido" beside a warning on the first frame | First use | walked; F1 | Stage prototype: only true facts on the welcome, the filter read again for the summary |
| 3 | The first run never shows profiles, protection or the band | First use, profile | walked | Stage: the first sentence points at the band; the band step is the slice's |
| 4 | The assistant cannot be found, then asks for a provider form | Assistant | F8 | To do |
| 5 | DNS asked in the vocabulary of the implementation | First use | F2 | To do (copy, in the first-run slice) |
| 6 | The page gets 80 % and there is no mode that gives more with the names kept | Daily use | measured | ADR 0009 prototype (97 %) |
| 7 | A link that leads to a refusal under `--profile` | Profile | F6 (launcher mode only) | To do (small) |
| 8 | The card and the navigation move under the pointer | First use, configure | walked; F4 | Stage (fixed card); ADR 0008 |
| 9 | Install: unknown | Install | not walked | First task of the first-run slice |

The pink stripes on the address field in the QA captures (F3) are the engine's "under remote control" cue of the test session. A person never sees them; they are not a finding.
