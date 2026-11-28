# Launch trailer (script)

> **Draft, not approved (2026-11-27).** Nothing has been recorded, generated or published ([#176](https://github.com/nulavio/nulavio/issues/176)).

- **Length:** about 85 s in English and up to 90 s in Portuguese (the window is 60–90 s). Exports in 16:9, 1:1 and 9:16, in English and Portuguese, with WebVTT captions and a transcript made from this script.
- **For:** all four personas in the [message house](message-house.md#positioning).
- **Built from:** real recordings of a Nulavio build (scene IDs `R…`, listed [below](#recordings-the-pipeline-needs)), plus motion titles, motion cards and abstract backgrounds. The interface is never generated (rule 1). AI may make the voice, the music, the sound effects, the titles and the transitions; what it did make in a given cut is what that cut's manifest says.
- **Claims:** each scene cites IDs from the [claims register](claims.md). A line may say less than its claim, never more. A line whose claim changes status is rewritten before the render.
- **Voice-over:** 189 words in English and 197 in Portuguese, counted on 2026-11-27. The scenes with a recording run at 2.0 to 2.4 words a second in English and up to 2.5 in Portuguese, which is the top of what a voice says clearly (2.3–2.5), so there is no slack. The times below are a plan and are set against the recorded voice in the edit. If a line does not fit its scene at a clear pace, in either language, the line is shortened here first and checked against its claim again; the voice is not sped up and a condition is not dropped to save time.
- **Where it plays:** on a video platform, under that platform's player. On nulavio.net it is a video with controls that starts only when the person presses play, with captions and a transcript; nothing longer than 5 s moves by itself there ([below](#what-each-recording-yields)).

## Scenes

Times are for the English cut. The Portuguese cut keeps the same scenes and stretches the motion scenes (T1, T9, T10) by up to 5 s in all. A recording is never sped up or slowed down.

### T1 · 0:00–0:06 · Opening

- **Picture:** motion only. The route symbol draws itself and its trail dissolves ([guidelines](../brand/guidelines.md); final art after [#175](https://github.com/nulavio/nulavio/issues/175)). No interface.
- **On screen:** "Your web. Your rules." / "A web é sua. Seus dados também." And, small, the AI notice, which stays until T2 ends (16 s): "Voice and music: AI-generated" / "Voz e música geradas por IA" (rule 4; it names what the cut's manifest marks as AI-generated).
- **VO en:** "A browser should work for you, from the very first launch."
- **VO pt-BR:** "Um navegador deveria trabalhar para você, desde a primeira vez que abre."
- **Claims:** none (brand line).

### T2 · 0:06–0:16 · Protected from the first launch

- **Picture:** R01 `first-launch`: a new profile starts and the welcome card lists the protections that are on. The card lists uBlock Origin only once it is installed, so the recording shows it there or not as the build does at that moment; nothing is staged to make it appear.
- **On screen:** "Protected from the first launch" / "Protegido desde a primeira vez que abre", then, small: "Each default Nulavio changes is written down, with its reason" / "Cada padrão que o Nulavio muda está documentado, com o motivo"
- **VO en:** "On first launch, Nulavio sets up ad and tracker blocking by itself, with Strict tracking protection and HTTPS-Only already on."
- **VO pt-BR:** "Ao abrir pela primeira vez, o Nulavio configura sozinho o bloqueio de anúncios e rastreadores, já com o modo Estrito e só HTTPS ligados."
- **Claims:** C01, C02, C03.
- **Note:** "already on" is said of the two engine settings only. uBlock Origin is installed at that first start and blocks once its lists have loaded (C01), so the line says "sets up", not "blocks".

### T3 · 0:16–0:24 · When tracking protection breaks a site

- **Picture:** R02 `site-panel`: on a fixture page the site panel lists what the engine's tracking protection blocked, with the engine's own count. The cursor turns that protection off for the site, then on again.
- **On screen:** the panel as recorded. Title: "Tracking protection: off for one site only" / "Proteção contra rastreamento: desligue só num site"
- **VO en:** "If tracking protection breaks a site, turn it off for that site only, and back on when you like."
- **VO pt-BR:** "Se a proteção contra rastreamento quebrar um site, desligue só nele, e ligue de novo quando quiser."
- **Claims:** C04.
- **Notes:** the switch is the engine's. It does not switch uBlock Origin off, which has its own list of trusted sites (C04), so the line names tracking protection and does not promise a fix for any breakage. The landing's "two clicks" stays off the voice-over unless the recording shows exactly two clicks.

### T4 · 0:24–0:35 · A profile for each part of life

- **Picture:** R03 `profile-opens`, then R04 `link-routed`. In Settings › Profiles the cursor opens Work, and the Work window comes up with its band. Then, in Personal, the work intranet's address is typed, and it opens in the Work window, whose band says the rule opened it there.
- **On screen:** profile names as recorded (Personal, Work / Pessoal, Trabalho).
- **VO en:** "Work, banking and personal life each get their own profile, and your rules send typed addresses and links from other apps to the right one."
- **VO pt-BR:** "Trabalho, banco e vida pessoal ficam cada um no seu perfil, e as suas regras mandam endereços digitados e links de outros aplicativos para o perfil certo."
- **Claims:** C06, C07.
- **Note:** the picture shows a typed address, which is what the pipeline records. A link from another app starts outside the browser window and is not recorded; the line names it because C07 covers it (`test_04`). The line does not say "every link": a link clicked inside a page stays where it is unless in-page routing is turned on (C07). The rule in the picture is an "open there" rule for a profile that is not locked. The line says where the rules send an address, not that the site loads at once: an "ask first" rule for another profile asks, and a locked profile asks to be unlocked, before anything loads (C07). The profile short says the locked case aloud.

### T5 · 0:35–0:44 · Encrypted while locked

- **Picture:** R06 `protected-unlocks`: Settings › Profiles with Banking locked; Unlock; the profile's password (an artificial one, typed on the unlock page) opens it, and its window comes up with the band "Banking · Protected". If #173 adds R06b `locked-folder`, a motion card, marked as a card, shows first the encrypted names that R06b reads from the profile's Vault folder (while the profile is locked its own folder is empty); without it the title carries the point.
- **On screen:** "Encrypted on disk while locked" / "Criptografado no disco enquanto bloqueado"
- **VO en:** "Protect a profile and its folder stays encrypted on disk while it's locked. There's no master key, not even ours."
- **VO pt-BR:** "Proteja um perfil e a pasta dele fica criptografada no disco enquanto ele está bloqueado. Não existe chave mestra, nem a nossa."
- **Claims:** C09, C10.
- **Note:** the line says that the folder's contents stay encrypted on disk while the profile is locked, which holds for every way of opening it. It does not say who can open it. With the system login, a program running as the person, or someone with the login password, can (C09): the encrypted-profiles short says so, and the trailer does not name the system login.
- **Not shown:** phone unlock (C11, "coming soon" until #227 closes) and a FIDO2 key (C12, planned). The trailer names neither; the encrypted-profiles short carries the "coming soon" card.

### T6 · 0:44–0:55 · Guard

- **Picture:** R07 `guard`: after changes made while the browser was closed, the Guard review lists them; the cursor undoes one that has an undo (the proxy setting) and keeps another.
- **On screen:** the review as recorded. Title: "Changed while closed? Guard shows it." / "Mudou com ele fechado? O Guard mostra."
- **VO en:** "If an extension is added or a watched setting changes with the browser closed, Guard shows it. You keep it, or undo it where Guard can."
- **VO pt-BR:** "Se uma extensão for adicionada ou uma configuração acompanhada mudar com o navegador fechado, o Guard mostra. Você mantém, ou desfaz quando o Guard consegue."
- **Claims:** C13 (the limit C14 is on a card of the Guard short).
- **Note:** the recorded review also holds a `user.js` and a native-messaging finding, which offer "Show file" and "Keep" and no undo (C13). The line therefore says "where Guard can", and "a watched setting", not "anything". Of an extension it says "added": one that was only switched off is not reported (C13). The recording is of an ordinary profile: Guard does not check a temporary profile or a browser an AI agent is driving (C13).

### T7 · 0:55–1:05 · AI under your control

- **Picture:** R08 `ai-bridge`: a neutral test client connects through MCP; the agent works in its own workspace (the band says so); the cursor presses the emergency stop, and the client's next action, a page read, is refused.
- **On screen:** "AI that goes only as far as you let it" / "IA que vai só até onde você deixa"
- **VO en:** "By default, AI agents work in a profile of their own, with the permissions you grant, and the emergency stop refuses their next actions."
- **VO pt-BR:** "Por padrão, agentes de IA trabalham num perfil só deles, com as permissões que você dá, e a parada de emergência recusa as próximas ações."
- **Claims:** C15.
- **Rule 6:** no agent product is named or shown. The client is the project's test client, registered under a neutral name ("Test agent" / "Agente de teste"), which is all Nulavio's interface shows of it.
- **Notes:** "by default" is spoken, because an agent given one of your profiles works there (C15); that case is not shown. The stop is said as what it does: it refuses calls to browser tools through Nulavio and closes the workspaces; the status call still answers, and says the session is stopped. It does not end the agent's own program (C15).

### T8 · 1:05–1:12 · Your choices

- **Picture:** quick cuts of R09 `password-manager`, R10 `search-provider` and R11 `dns`, each showing the full list of options as the build shows it. The search list is the one in Settings › Search, in the new profile recorded: every provider and engine by name, each with a "Use" button, none preselected, and one row that says "In use in normal and private windows.", which in a new profile is DuckDuckGo's (C29). The password manager list marks the one in use (the browser's own in a new profile, C29). The DNS card shows its two options with their notes (C18). The voice-over names none.
- **On screen:** "Your choice, and you can change it" / "Você escolhe, e pode mudar depois"
- **VO en:** "Password manager, search engine, DNS: you choose among the options, and you can change your mind."
- **VO pt-BR:** "Gerenciador de senhas, buscador, DNS: você escolhe entre as opções, e pode mudar de ideia."
- **Claims:** C16, C17, C18, C29.
- **Note:** "among the options" is spoken because the welcome offers the password managers Nulavio supports, not every one (C16). The lists on screen are those options.

### T9 · 1:12–1:20 · Honest limits

- **Picture:** motion card on an abstract background. No interface.
- **On screen:** "No telemetry. No account. The browser contacts no Nulavio server by itself." then "It doesn't hide your IP address. For that, use Tor Browser." / "Sem telemetria. Sem conta. Sozinho, o navegador não contata nenhum servidor do Nulavio." then "Ele não esconde seu IP. Para isso, use o Tor Browser."
- **VO en:** "No telemetry. No account. By itself, the browser contacts no server of ours. And we say what it can't do."
- **VO pt-BR:** "Sem telemetria. Sem conta. Sozinho, o navegador não contata nenhum servidor nosso. E a gente diz o que ele não consegue fazer."
- **Claims:** C05, C20, C26.
- **Note:** the claim is about the browser, and "by itself" is spoken and on screen. The next card sends the viewer to nulavio.net, which the project runs, with a waitlist form that keeps what a person submits, and Nulavio is installed from the project's package repository (C05). So neither the card nor the voice says there is no Nulavio server. At 8 s the English line runs at 2.5 words a second; the Portuguese cut gives this scene 9 s, which is 2.4.

### T10 · 1:20–1:25 · End card

- **Picture:** the lockup, nulavio.net, and the status.
- **On screen:** "Free and open source · Public alpha for Fedora and Ubuntu" / "Livre e de código aberto · Alfa pública para Fedora e Ubuntu" (C24, C26). Nothing else: the AI notice was on screen from T1 to T2, and the engine line and the AI line in full are in the description.
- **VO en:** "Nulavio. Protected from the start. Honest by design."
- **VO pt-BR:** "Nulavio. Protegido desde o início. Honesto por princípio."

### Notices and their reading time

The rate is the [message house's](message-house.md#reading-time): at least one second for every 20 characters on screen, spaces included, in the longer language. Counted on 2026-11-27 from the text above, with nulavio.net as 11 characters.

| Where | Text a piece adds on screen | Characters (en / pt-BR) | Time | Characters a second |
|---|---|---|---|---|
| T1 | The line and the AI notice | 50 / 58 | 6 s | 8 / 10 |
| T2 | The title, the small line and the AI notice | 121 / 127 | 10 s | 12 / 13 |
| T9 | The two cards | 134 / 140 | 8 s (9 s in Portuguese) | 17 / 16 |
| T10 | nulavio.net and the status | 68 / 71 | 5 s | 14 / 14 |

- The trailer names the engine in no voice-over and in no title, so the engine line is not on a card: it is in the description, which does name the engine. Showing it would take 7 s (122 characters in English and 127 in Portuguese), and the Portuguese cut is already at 90 s.
- If the maintainer wants the engine named in the video, the 7 s come from a scene, and the line goes on a card of its own. That is a choice about the script, listed in the pull request.

## Description text (for the video page)

- **en:** "Nulavio is a free, open-source browser for Linux, in public alpha for Fedora and Ubuntu. Every claim in this video, with the test or document behind it: <link to claims.md>. <the AI line in full: what is AI-generated, as a sentence, then> The browser's interface is recorded from a real build. Titles and cards are motion graphics. Built on Mozilla's Gecko engine. Nulavio is not affiliated with Mozilla. Firefox is a trademark of the Mozilla Foundation."
- **pt-BR:** "O Nulavio é um navegador livre e de código aberto para Linux, em alfa pública para Fedora e Ubuntu. Cada afirmação deste vídeo, com o teste ou documento que a sustenta: <link para claims.md>. <a linha de IA completa: o que foi gerado por IA, numa frase, e então> A interface do navegador foi gravada de uma versão real. Títulos e cartões são animação gráfica. Feito sobre o motor Gecko da Mozilla. O Nulavio não é afiliado à Mozilla. Firefox é uma marca registrada da Mozilla Foundation."
- **The link to claims.md** is a permanent link to a commit on `main`, or to a release tag, that contains the file as the piece was checked against it. The tag `v160.0.1-0.3` does not contain it: the register was added after that release. Before publishing, the link is opened and the file read at that commit.
- The platform's AI label is set on upload ([tools-and-budget.md](tools-and-budget.md#ai-disclosure)).

## Recordings the pipeline needs

The pipeline is built in [#173](https://github.com/nulavio/nulavio/issues/173), once, for the site and for this material. This list is what the trailer and the [shorts](shorts.md) need from it. It does not build anything.

### What #173's pipeline records today

Read on 2026-11-27 from [pull request #859](https://github.com/nulavio/nulavio/pull/859) at its head `9fdb4ff2`, which is open and not merged; its files are not in this branch, so they are named here and not linked.

- **Capture.** `scripts/site/record_site.py` drives a headless build in the release test container through Marionette, on throwaway profiles, and writes the browser window's own pixels as PNG frames with a timeline. The frames are few and are held: the three samples have 22 to 57 captured frames for scenes of 11 to 13 s. The frames are 1920×1200 (a 1280×800 window at 1.5).
- **Compose.** On the host, with Pillow and FFmpeg, it draws the cursor (eased paths) and a ripple on each click, and writes the files [below](#what-each-recording-yields). It refuses a scene whose captions cannot be read (more than 20 characters a second) or whose loop runs longer than 5 s or more than once.
- **Recorded, in pt-BR and en-US:** `profile-opens`, `link-routed` and `protected-unlocks`, as samples from a development package (this tree's Shell on a Firefox 161.0 engine built from its pins, build 20261127145149).
- **Planned in its specification, not recorded:** the first launch, Guard, the search provider, Copy Link to Highlight and the AI Bridge.
- **Not in its list:** the site panel, a temporary profile, the password manager step, the DNS question and the listing of a locked folder. They are asked for here.
- **What a recording changes, and says in its manifest:** the automation cue removed from the window; the cursor drawn afterwards; typing shown at a fixed pace, each key really typed; the time until the window a scene cuts to is up cut out (a new instance starting, or one already running opening the link); and what the script set up before the scene (the profiles, a routing rule, a local test search engine).

Consequences for these scripts:

- **Only the browser window is recorded.** Anything outside it (a folder on disk, another app sending a link) is not footage. It can be shown only as a motion card built from what the capture step read, with the real names, and marked as a motion card. The capture step reads no folder listing today (R06b, R05). For a locked protected profile the names to read are not in the profile's own folder, which is empty while it is locked, but in the Vault folder beside it (R06b).
- **Hover states do not show,** because the cursor is drawn afterwards. That the cursor is drawn in the compose step is settled in #859.
- **Size and frame rate.** #176 asks for 4K at 60 fps. The pipeline writes 1280×800 at 30 fps from held frames captured at 1920×1200, which is 16:10. Composing a 16:9 export at 1080p from those frames (the compose step has a `--width` option) was not tried, and 4K needs a larger capture, not tried either. Sixty real frames a second needs a private X display (Xvfb) in the test container, which changes a container and is the maintainer's to decide with this tool list. Recommendation: cut a sample from what the pipeline gives, and decide on Xvfb only if the held frames read poorly in it.
- **Aspect ratios.** A 1280×800 window does not fill a 9:16 or 1:1 frame. The shorts need either a crop that follows the cursor (each crop recorded in the manifest) or a second recording in a narrow window; #173 decides which, and the narrow window must be one of Nulavio's real layouts.

### What each recording yields

For each scene and language the pipeline writes:

| File | What it is | Where it is used |
|---|---|---|
| The full video | The whole scene, as a VP9 WebM and an H.264 MP4, muted and with no audio track | On the site, in a player with controls that starts only when the person presses play (never autoplay, nothing downloaded before). In the trailer and the shorts, cut in the edit with the voice and the music added there |
| The loop | At most 5 s of the scene, the part its script marks as the highlight, as an animated WebP at 10 frames a second at most that plays once and stops | On the site and in the README, where something may move by itself |
| The poster | One still frame | Under reduced motion, and before a video plays |
| Captions and transcript | WebVTT, at most 20 characters a second, and a transcript read from the interface | With every video |
| The manifest entry | Hashes and sizes; for the capture, its time, the build ID, the engine version and git's id of the recording script as it ran; for the compose step, the checkout that drew and encoded the files; the cuts, the captions and the notes above | Beside the files |

This follows the maintainer's [decision of 2026-11-27 on #173](https://github.com/nulavio/nulavio/issues/173#issuecomment-7210333555): **loops of at most 5 s that stop by themselves, and the full video with controls.** For this material it means:

- The trailer and the shorts are full videos. On nulavio.net and in the press kit each one sits in a player with controls, with captions and a transcript, and never starts by itself.
- Anything from this material that moves by itself on the site or in the README is one of the loops: 5 s at most, played once, silent. A trailer teaser, if one is wanted, is such a loop.
- No scene is planned around a loop longer than 5 s. A scene's point has to be readable inside its loop window, or the scene is shown only as a video.

### For every recording

- **A real build.** For the published pieces, a published Nulavio release; a development package of a merged commit only for samples, as #859's are. The manifest records the capture's build ID and engine version and the recording script's git id, and the commit of the checkout that composed the files. In #859 the capture itself names no commit, because it runs on a copy of the tree without git's data; for a published piece the release's version and build ID say which build it was.
- **Throwaway everything.** A new HOME and registered engine profiles, on `tests/lib/harness.GeckoProfileSession`. Profile names in the recording's language, as the pipeline names them: Personal, Work, Banking / Pessoal, Trabalho, Bancos.
- **Fixture sites only.** Pages served locally by the pipeline, with neutral names and original text, never a real site with a real account (rule 7). The pipeline must not switch off a protection to make them load (I1 in [REVIEW.md](../../REVIEW.md)); a fixture is marked as a tracker only through the engine's test-entries pref in a test profile, as [`test_privacy.py`](../../tests/integration/test_privacy.py) does.
- **No real provider shown alone (rule 6).** In a scene that is not about search, the pipeline keeps a real search provider out of frame: a new window gets a fixture page first, and the profile where an address is typed searches with a local test engine. Each of these is a note in the manifest.
- **The automation cue.** The only change allowed to the interface is removing the window's `remotecontrol` attribute (the striped address bar), recorded in the manifest's `dom_changes`.
- **Cursor.** Eased moves and a visible ripple on each click, the same on every render, drawn in the compose step.
- **Same scene in both languages.** Each scene is recorded once per locale (en-US and pt-BR), with the same actions, so the cuts match.
- **Frame check.** Before a scene is used, every frame is checked for anything personal: notifications, other windows, file paths outside the throwaway HOME, a real e-mail address or account (rule 7). Today the compose step refuses a manifest that holds the home directory anywhere, or the user or host name as a whole word in a transcript, and #859's frames were looked at by hand; the manifest has no field for a frame check. One is asked of #173.
- **Media size.** For the site, #859 keeps each file under 2 MB. The trailer's and the shorts' exports are heavier. Where they are kept (release assets, the site, not the git history) is decided in #173 against the 250 MB budget of [ADR 0013](../adr/0013-repository-layout.md).

### Scenes

"In #859" says whether the pipeline records the scene today (with the sample's length), plans it, or does not list it.

| ID | In #859 | What is recorded | The test it can start from | Used in |
|---|---|---|---|---|
| R01 `first-launch` | Planned ("First launch") | A new profile starts; the welcome card lists the protections that are on, as the build shows them; "use the defaults" | [test_firstrun_stage.py](../../tests/integration/test_firstrun_stage.py) `test_01`, `test_03` | T2, S1 |
| R02 `site-panel` | Not listed | A fixture page with a fixture tracker; the site panel lists it with the engine's count; tracking protection off for that site, then on | [test_privacy.py](../../tests/integration/test_privacy.py) `test_02`, `test_03` | T3, S1 |
| R03 `profile-opens` | Recorded (sample, 11 s) | Settings › Profiles lists Personal and Work; a click on Open for Work; the Work window opens, its band reading "Work · No password" | [test_profiles.py](../../tests/integration/test_profiles.py) | T4, S2 |
| R04 `link-routed` | Recorded (sample, 12 s) | In Personal, the work intranet's address is typed in the address bar; it opens in the Work window, whose band says "Opened by your rule · Change". The rule is an "open there" rule and Work is not locked. A link sent by another app is not recorded: it starts outside the window | [test_routing.py](../../tests/integration/test_routing.py) `test_11`, `test_04b` | T4, S2 |
| R05 `temporary` | Not listed | A temporary window is opened; its last window closes. The folder's removal happens outside the window: it could only be a motion card, from a listing the capture step does not write today | [test_temporary.py](../../tests/integration/test_temporary.py) `test_01` | S2 |
| R06 `protected-unlocks` | Recorded (sample, 13 s) | Settings › Profiles with Banking locked; a click on Unlock; the artificial password typed on the unlock page, which says the profile locks again when its last window closes; the Banking window opens, its band reading "Banking · Protected" | [test_vault_profiles.py](../../tests/integration/test_vault_profiles.py) | T5, S3 |
| R06b `locked-folder` | Not listed | Not a recording: the encrypted names in the locked test profile's Vault folder, read by the capture step into the manifest, for a motion card. For a profile folder `P` that is `P.vault/cipher`, beside it: while the profile is locked `P` itself is empty, so a listing of `P` would show nothing ([ADR 0006](../adr/0006-nulavio-vault.md), "Layout"). Until the pipeline writes it, T5 and S3 use their titles alone | [test_vault_profiles.py](../../tests/integration/test_vault_profiles.py) `test_profile_data_is_unreadable_when_locked` | T5, S3 |
| R07 `guard` | Planned ("Guard") | Changes made while closed: a proxy on loopback in `prefs.js`, a line in `user.js` that sets the home page to a fixture page, a native-messaging manifest that starts `/usr/bin/true`, and a throwaway test CA whose private key is deleted before the browser starts, so it can sign nothing. Then the Guard review; the proxy setting undone, another finding kept. The `user.js` and native-messaging cards show "Show file" and "Keep", with no undo. **No protection is switched off:** `test_02` writes a Safe Browsing pref in `user.js`, which I1 allows only to that test, by name, because its subject is that finding; a recorder is not that test, so its `user.js` line sets a watched setting that is not a protection (`browser.startup.homepage`) | [test_guard.py](../../tests/integration/test_guard.py) `test_02` | T6, S4 |
| R08 `ai-bridge` | Planned ("AI Bridge") | A test MCP client connects; approval; the agent reads a fixture page in its workspace; a permission is revoked; the emergency stop; the client's next page read is refused and its workspace closes | [test_ai_bridge.py](../../tests/integration/test_ai_bridge.py) `test_05`, `test_06` | T7, S5 |
| R09 `password-manager` | Not listed | The welcome's password manager step with every option listed and the one in use marked as the build marks it (the browser's own in a new profile); no account signed in | [test_firstrun_stage.py](../../tests/integration/test_firstrun_stage.py) `test_07` | T8, S6 |
| R10 `search-provider` | Planned ("Search provider") | Settings › Search in a new profile: the list of every provider and engine, in alphabetical order, each with "Use", none preselected; the one row that says "In use in normal and private windows." (DuckDuckGo's in a new profile). Then a local test engine on loopback, added by the script and noted in the manifest, is chosen with "Use" with the suggestions box ticked, and a neutral query is typed: what is typed goes to loopback only, as in `test_05`. No real provider is given the consent, and nothing is typed while a real provider is the default | [test_settings_search.py](../../tests/integration/test_settings_search.py) `test_03`, [test_search.py](../../tests/integration/test_search.py) `test_04`, `test_05` | T8, S6 |
| R11 `dns` | Not listed | The first tab's DNS question with both options and their notes: the network's resolver, or an encrypted service that falls back to it. Encrypted-only is in Settings and is not in this scene | [test_dns.py](../../tests/integration/test_dns.py) `test_01` | T8, S6 |
| R12 `copy-link-to-highlight` | Planned ("Copy Link to Highlight") | A fixture article; a passage selected; the link copied and opened at the passage | [test_text_fragments.py](../../tests/integration/test_text_fragments.py) | a later short |

Every scene yields the files of [the table above](#what-each-recording-yields): the full video, and a loop of at most 5 s that plays once.

Rule 6 for R08–R11: every list shows all its options as the build shows them, nothing is added to present one as recommended, and no third-party account is signed in. What the build says of its own state is shown as it says it: the search row "In use", the password manager "in use" (C29). Where a third party's name appears, it is because the list shows it, beside its alternatives.

### The search scene, settled on 2026-11-27

#859's specification plans the search scene as "The choice in one step, with every alternative shown and none preselected", and `test_search.py` `test_04` shows DuckDuckGo as a new profile's default. Both are true, of different things:

- **What a new profile starts with.** At a profile's first start Nulavio adds Brave Search and Mojeek and makes DuckDuckGo the default for normal and private windows (`NulavioSearch.sys.mjs`, `migrate`; [ADR 0002](../adr/0002-nulavio-search.md), decision 3; `test_04`). The first run asks about the layout, the DNS, the password manager, the default browser, updates and a protected profile. It has no search step.
- **What the choice looks like.** "The choice in one step" is the list at the top of Settings › Search (`test_settings_search.py` `test_03`). Every provider Nulavio knows and every engine the profile has is there by name, in alphabetical order, each row with a "Use" button in a new profile (a provider whose name another engine of the profile already holds gets none). No row has a radio button or a tick box, so none is preselected, and none is marked as recommended ([search providers](../research/search-providers.md): "with none marked"). The row of the engine in use says "In use in normal and private windows.", and exactly one row says it.

So R10 records that list in a new profile, with DuckDuckGo's row saying "In use" among the others, and then a choice made with "Use". The engine chosen there is a local test engine, so the consent for suggestions and the typed query reach no real provider (rule 7, and #859's own rule for typed addresses). It does not record the form for a new profile, whose first option reads "Nulavio's default (DuckDuckGo)": that is the one control that names the default as a choice already made. The voice-over names no provider (rule 6), and C29 says where a new profile's search starts.

For #173: its wording "none preselected" is right for the list's controls and says nothing of the "In use" row. A sentence there that a new profile shows DuckDuckGo "In use" would keep the scene's description from being read as "no default".
