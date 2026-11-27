# Feature shorts (scripts)

> **Draft, not approved (2026-11-27).** Nothing has been recorded, generated or published ([#176](https://github.com/nulavio/nulavio/issues/176)).

Six shorts of 26–30 s, one per pillar feature. Each is cut 9:16 first, then 1:1 and 16:9, in English and Portuguese, with WebVTT captions made from this script. The recordings (`R…`) are listed in the [trailer's scene table](trailer.md#recordings-the-pipeline-needs); the claims (`C…`) are in the [claims register](claims.md). A line may say less than its claim, never more.

Every short carries the same notices, as the [message house](message-house.md#every-piece-carries) gives them, each where there is time to read it ([reading time](message-house.md#reading-time): at least one second for every 20 characters on screen, in the longer language):

- **The AI notice** (rule 4), small, from the first frame until the first recorded scene ends, which is 8 to 16 s: "Voice and music: AI-generated" / "Voz e música geradas por IA" (29 and 27 characters; it names what the manifest marks as AI-generated). It is on the hook and on the first recording's row of each table below, which do not repeat it.
- **The end card**, 3 s: the lockup, nulavio.net and "Public alpha · Fedora and Ubuntu" / "Alfa pública · Fedora e Ubuntu" (C24). That is 43 characters in English and 41 in Portuguese, 14 a second. Nothing else is on it.
- **In the description**, not on a card: the AI line in full, with what is footage and what is not; the engine line; and the link to the claims, at a commit or tag that contains the register, as the [trailer's](trailer.md#description-text-for-the-video-page) does.

No short names the engine in its voice or its titles, so none carries the engine line on screen. One that did would need 7 s more for it.

Counted on 2026-11-27 with the AI notice included, the fullest moments are the hooks, where the notice sits under the hook's title: 12 to 19 characters a second. The tightest is S5's hook in Portuguese, 58 characters in 3 s. The cards that hold a notice nobody speaks are S2's (50 characters in 3 s) and S3's (103 in 6 s).

Where they play: on a video platform, under its player. On nulavio.net a short is a video with controls that starts only when the person presses play; what moves by itself there is a loop of at most 5 s that plays once ([trailer](trailer.md#what-each-recording-yields)).

Voice-over length, counted on 2026-11-27: 47–57 words in English and 47–62 in Portuguese for 26–30 s, 1.6 to 2.2 words a second over the whole short, and no row above 2.5 in either language. The Portuguese lines are up to 10 % longer. A line that does not fit its row at a clear pace is shortened here first and checked against its claim again; a condition is not dropped to save time. A hook, a motion card and the end card are motion graphics, not footage.

## S1 · Protected from the first launch (29 s)

For Ana and Carla: strong defaults with nothing to set up.

| Time | Picture | On screen (en / pt-BR) | VO en | VO pt-BR | Claims |
|---|---|---|---|---|---|
| 0:00–0:04 | Motion: hook title | "No hardening guide." / "Sem guia de configuração." | "No hardening guide. No extensions to hunt down." | "Sem guia de configuração. Sem caçar extensões." | — |
| 0:04–0:13 | R01 `first-launch` | the welcome card as recorded (it lists uBlock Origin only once it is installed) | "On first launch, Nulavio sets up ad blocking by itself, with Strict tracking protection and HTTPS-Only already on." | "Ao abrir pela primeira vez, o Nulavio configura sozinho o bloqueio de anúncios, já com o modo Estrito e só HTTPS ligados." | C01, C02 (the card on screen) |
| 0:13–0:22 | R02 `site-panel` | the panel as recorded | "The site panel lists the trackers it blocked. If tracking protection breaks a site, turn it off for that site only." | "O painel do site lista os rastreadores bloqueados. Se a proteção contra rastreamento quebrar um site, desligue só nele." | C04 |
| 0:22–0:26 | Motion card | "Each default it changes, with its reason, in writing." / "Cada padrão que ele muda, com o motivo, por escrito." | "Each default it changes comes with its reason." | "Cada padrão que ele muda vem com o motivo." | C03 |
| 0:26–0:29 | End card | as above | — | — | C24 |

"Already on" is said of the two engine settings. uBlock Origin is installed at the first start and blocks once its lists have loaded (C01), so the line says "sets up". The per-site switch is the engine's and does not switch uBlock Origin off (C04), so the line names tracking protection.

## S2 · A profile for each part of life (30 s)

For Bruno and the team lead: work and personal life in separate profiles.

| Time | Picture | On screen (en / pt-BR) | VO en | VO pt-BR | Claims |
|---|---|---|---|---|---|
| 0:00–0:03 | Motion: hook | "Work stays at work." / "Trabalho fica no trabalho." | "Work stays at work." | "Trabalho fica no trabalho." | — |
| 0:03–0:08 | R03 `profile-opens` | profile names as recorded | "Each Nulavio profile has its own cookies, logins, history and extensions." | "Cada perfil do Nulavio tem seus próprios cookies, logins, histórico e extensões." | C06 |
| 0:08–0:18 | R04 `link-routed` | "Your rule picks the profile" / "A sua regra escolhe o perfil" | "Tell it which profile opens a site. Typed, or opened from another app, the site opens there; a locked profile asks to be unlocked first." | "Diga qual perfil abre um site. Digitado, ou aberto por outro aplicativo, o site abre lá; um perfil bloqueado pede o desbloqueio antes." | C07 |
| 0:18–0:24 | R05 `temporary` | "Temporary: deleted when its browser closes" / "Temporário: apagado quando o navegador dele fecha" | "A temporary profile is deleted when you close its last window." | "Um perfil temporário é apagado quando você fecha a última janela dele." | C08 |
| 0:24–0:27 | Motion card | "Profiles keep data apart. They don't hide your IP." / "Perfis separam dados. Não escondem seu IP." | — | — | C20 |
| 0:27–0:30 | End card | as above | — | — | C24 |

The picture of R04 is a typed address, which is what the pipeline records; a link from another app starts outside the window (C07 covers both). The rule in the recording is an "open there" rule for a profile that is not locked, which is why the site opens at once. The line says what happens otherwise for a locked profile; an "ask first" rule, which the short does not show, asks before it loads anything (C07). Nothing here says "every link": a link clicked inside a page stays in the current profile unless in-page routing is turned on (C07).

## S3 · Encrypted profiles, and you hold the key (30 s)

For Bruno: what a protected profile holds stays encrypted while it is locked.

| Time | Picture | On screen (en / pt-BR) | VO en | VO pt-BR | Claims |
|---|---|---|---|---|---|
| 0:00–0:03 | Motion: hook | "Laptop stolen while off?" / "Roubaram o notebook desligado?" | "If your laptop is stolen while off…" | "Se alguém levar seu notebook desligado…" | — |
| 0:03–0:11 | R06 `protected-unlocks` (Banking locked in Settings › Profiles), with the R06b card if the pipeline has it | "Locked: its folder is encrypted on disk" / "Bloqueado: a pasta dele fica criptografada no disco"; small: "Its name and the sites routed to it stay readable" / "O nome dele e os sites roteados para ele continuam legíveis" | "…what is inside a locked protected profile's folder is still encrypted on disk." | "…o que está na pasta de um perfil protegido e bloqueado continua criptografado no disco." | C09 |
| 0:11–0:21 | R06 `protected-unlocks` (the password opens it) | "Password, system login or recovery code" / "Senha, login do sistema ou código de recuperação"; small: "System login: only as strong as your login password" / "Login do sistema: tão forte quanto a sua senha de login" | "Open it with its password, or with your system login. With the login, a program running as you can open it too." | "Abra com a senha dele, ou com o login do sistema. Com o login, um programa rodando como você também consegue abrir." | C09 |
| 0:21–0:27 | Motion card | "No master key. Not even ours." and, under it, "Coming soon: unlock with your phone. Planned: a FIDO2 security key." / "Sem chave mestra. Nem a nossa." e, abaixo, "Em breve: desbloquear com o celular. Planejado: chave de segurança FIDO2." | "There's no master key. Not even ours." | "Não existe chave mestra. Nem a nossa." | C10, C11 (coming soon), C12 (planned) |
| 0:27–0:30 | End card | as above | — | — | C24 |

The short says nothing about what a stolen laptop reveals as a whole. The theft is of a computer that is off: a disk read by someone else, with no session of the person running. The claim is about one locked protected profile's folder: an unlocked profile can be read by a program running as the person, and a locked one still shows its name and the sites routed to it (C09), which the second row says on screen.

What that folder's encryption is worth depends on how the profile opens, and the third row says so. With the profile's own password it is as strong as that password. With the system login the key is in the desktop keyring, which is on the same disk: whoever has the login password opens it, and while the person's session is on, a program running as them can take the key from the unlocked keyring even with the profile locked (C09). The second limit is spoken and the first is on screen, in the row's small line. The recovery code is on screen only.

The card of the fourth row holds two notices nobody speaks ("coming soon", "planned"), so it has 6 s: 96 characters in English and 103 in Portuguese, 16 and 17 a second.

Phone unlock (C11) is said only as "coming soon", on the card, until [#227](https://github.com/nulavio/nulavio/issues/227) closes (the maintainer's [decision of 2026-11-27](https://github.com/nulavio/nulavio/issues/176#issuecomment-7210333283)). It is not recorded and not spoken. When #227 closes, it gets a scene recorded with a test phone and a test pairing, and the card changes.

## S4 · Guard (26 s)

For Ana: she wants to know when something touched her browser.

| Time | Picture | On screen (en / pt-BR) | VO en | VO pt-BR | Claims |
|---|---|---|---|---|---|
| 0:00–0:04 | Motion: hook | "Changed while it was closed?" / "Mudou com ele fechado?" | "Some programs change your browser while it's closed." | "Alguns programas mexem no navegador enquanto ele está fechado." | C14 |
| 0:04–0:16 | R07 `guard` | the Guard review as recorded | "On the next start, Guard shows the changes it watches: a new extension, a new certificate authority, a protective setting. You keep each one, or undo it where Guard can." | "No próximo início, o Guard mostra as mudanças que acompanha: uma extensão nova, uma autoridade certificadora nova, uma configuração de proteção. Você mantém cada uma, ou desfaz quando ele consegue." | C13 |
| 0:16–0:23 | Motion card | "Guard tells you. It doesn't prevent." / "O Guard avisa. Ele não impede." | "Guard tells you; it doesn't prevent. No browser stops malware already running on your computer." | "O Guard avisa; ele não impede. Nenhum navegador detém um programa malicioso que já roda no computador." | C14 |
| 0:23–0:26 | End card | as above | — | — | C24 |

The recorded review holds a `user.js` and a native-messaging finding too. They offer "Show file" and "Keep", with no undo, and a setting outside Guard's list is not reported (C13). So the line says "the changes it watches" and "where Guard can", and "new" of the extension and the certificate authority: Guard reports a certificate authority that was added, not one that was removed (C13). The recording is of an ordinary profile: Guard does not check a temporary profile or a browser an AI agent is driving (C13), and no line here says it does.

## S5 · AI that goes only as far as you let it (30 s)

For Ana and the team lead: agents, without handing over the keys.

| Time | Picture | On screen (en / pt-BR) | VO en | VO pt-BR | Claims |
|---|---|---|---|---|---|
| 0:00–0:03 | Motion: hook | "Let an AI agent browse?" / "Deixar um agente de IA navegar?" | "An AI agent in your browser?" | "Um agente de IA no seu navegador?" | — |
| 0:03–0:12 | R08 `ai-bridge` (connect, workspace band) | "By default: its own profile, away from your logins" / "Por padrão: perfil próprio, longe dos seus logins" | "By default, an MCP client gets a profile of its own, away from your logins, unless you give it one of yours." | "Por padrão, um cliente MCP ganha um perfil só dele, longe dos seus logins, a menos que você dê um dos seus." | C15 |
| 0:12–0:18 | R08 `ai-bridge` (permission, revoke) | the permission panel as recorded | "It has the permissions you grant, and you can take them back." | "Ele tem as permissões que você dá, e você pode retirá-las." | C15 |
| 0:18–0:27 | R08 `ai-bridge` (emergency stop, the next call refused) | "Emergency stop: next calls refused" / "Parada de emergência: próximas chamadas recusadas" | "Its actions are logged, and the emergency stop refuses every agent's next call and closes its workspace." | "As ações ficam registradas, e a parada de emergência recusa a próxima chamada de cada agente e fecha o espaço de trabalho." | C15 |
| 0:27–0:30 | End card | as above | — | — | C24 |

Rule 6: no AI product is named in the voice-over or shown on screen. The client is the project's test client, registered under a neutral name, as in T7.

The stop is said as what it does: the Bridge refuses each agent's next call and closes its workspace. It does not end the agent's own program, which runs outside the browser (C15).

## S6 · Your choices, no partner behind them (28 s)

For Carla and Bruno: the choices are theirs, among the options the build lists.

| Time | Picture | On screen (en / pt-BR) | VO en | VO pt-BR | Claims |
|---|---|---|---|---|---|
| 0:00–0:03 | Motion: hook | "Your choices. No partner." / "Suas escolhas. Sem parceiro." | "Your choices, with no partner behind them." | "Suas escolhas, sem parceiro por trás." | C29 |
| 0:03–0:10 | R09 `password-manager` | the full list as recorded | "Pick one of the listed password managers, through its official extension. Nulavio doesn't build its own." | "Escolha um dos gerenciadores de senhas da lista, pela extensão oficial. O Nulavio não cria um próprio." | C16, C29 |
| 0:10–0:17 | R10 `search-provider` | the full list as recorded (Settings › Search) | "Search suggestions stay off until you allow them, one search engine at a time." | "As sugestões de busca ficam desligadas até você permitir, um buscador de cada vez." | C17 |
| 0:17–0:22 | R11 `dns` | the card as recorded, with both options and their notes | "And your DNS is asked once, on the first tab." | "E o DNS é perguntado uma vez, na primeira aba." | C18 |
| 0:22–0:25 | Motion card | "You can change each choice later." / "Dá para mudar cada escolha depois." | — | — | C16–C18 |
| 0:25–0:28 | End card | as above | — | — | C24 |

Rule 6: each list is shown whole, as the build shows it, and the voice-over names no provider.

- **Password managers.** The welcome lists the browser's own manager and the four Nulavio supports, and marks the browser's own as in use (C29). A manager outside that list is not offered there, so the hook and the line promise a choice among the listed ones, not "whatever you already use" (C16).
- **Search.** The first run has no search step: the scene is Settings › Search. Its list has every provider and every engine by name, in alphabetical order, each with a "Use" button, none preselected and none marked as recommended. One row says "In use in normal and private windows.": in a new profile it is DuckDuckGo's, because that is where a new profile's search starts (C29). The recording shows that row as it is, among the others.
- **DNS.** The first tab's card offers the network's resolver or an encrypted service that falls back to it; each option's own note is on the card. Encrypted-only is in Settings and is not shown (C18). The line says only that the question is asked once.

## Later shorts

- **Copy Link to Highlight** (C27, implemented): can be scripted now from R12 if the maintainer wants a seventh short.
- **The features from #172** (C28, planned): a short is scripted only when the feature ships in a release, with its test in the claims register.
