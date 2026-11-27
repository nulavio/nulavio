# Launch trailer (script)

> **Draft, not approved (2026-11-27).** Nothing has been recorded, generated or published ([#176](https://github.com/nulavio/nulavio/issues/176)).

- **Length:** about 85 s in English and up to 90 s in Portuguese (the window is 60–90 s). Exports in 16:9, 1:1 and 9:16, in English and Portuguese, with WebVTT captions and a transcript made from this script.
- **For:** all four personas in the [message house](message-house.md#positioning).
- **Built from:** real recordings of a Nulavio build (scene IDs `R…`, listed [below](#recordings-the-pipeline-needs)), plus motion titles, motion cards and abstract backgrounds. The interface is never generated (rule 1). AI may make the voice, the music, the sound effects, the titles and the transitions; what it did make in a given cut is what that cut's manifest says.
- **Claims:** each scene cites IDs from the [claims register](claims.md). A line may say less than its claim, never more. A line whose claim changes status is rewritten before the render.
- **Voice-over:** 185 words in English and 193 in Portuguese, counted on 2026-11-27. The scenes with a recording run at 2.0 to 2.4 words a second in English and up to 2.5 in Portuguese, which is the top of what a voice says clearly (2.3–2.5), so there is no slack. The times below are a plan and are set against the recorded voice in the edit. If a line does not fit its scene at a clear pace, in either language, the line is shortened here first and checked against its claim again; the voice is not sped up and a condition is not dropped to save time.
- **Where it plays:** on a video platform, under that platform's player. On nulavio.net it is a video with controls that starts only when the person presses play, with captions and a transcript; nothing longer than 5 s moves by itself there ([below](#what-each-recording-yields)).

## Scenes

Times are for the English cut. The Portuguese cut keeps the same scenes and stretches the motion scenes (T1, T9, T10) by up to 5 s in all. A recording is never sped up or slowed down.

### T1 · 0:00–0:06 · Opening

- **Picture:** motion only. The route symbol draws itself and its trail dissolves ([guidelines](../brand/guidelines.md); final art after [#175](https://github.com/nulavio/nulavio/issues/175)). No interface.
- **On screen:** "Your web. Your rules." / "A web é sua. Seus dados também."
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
- **Note:** the picture shows a typed address, which is what the pipeline records. A link from another app starts outside the browser window and is not recorded; the line names it because C07 covers it (`test_04`). The line does not say "every link": a link clicked inside a page stays where it is unless in-page routing is turned on (C07).

### T5 · 0:35–0:44 · Encrypted while locked

- **Picture:** R06 `protected-unlocks`: Settings › Profiles with Banking locked; Unlock; the profile's password (an artificial one, typed on the unlock page) opens it, and its window comes up with the band "Banking · Protected". If #173 adds R06b `locked-folder`, a motion card shows the locked folder's encrypted names first; without it the title carries the point.
- **On screen:** "Encrypted on disk while locked" / "Criptografado no disco enquanto bloqueado"
- **VO en:** "Protect a profile and its folder stays encrypted on disk while it's locked. There's no master key, not even ours."
- **VO pt-BR:** "Proteja um perfil e a pasta dele fica criptografada no disco enquanto ele está bloqueado. Não existe chave mestra, nem a nossa."
- **Claims:** C09, C10.
- **Not shown:** phone unlock (C11, "coming soon" until #227 closes) and a FIDO2 key (C12, planned). The trailer names neither; the encrypted-profiles short carries the "coming soon" card.

### T6 · 0:44–0:55 · Guard

- **Picture:** R07 `guard`: after changes made while the browser was closed, the Guard review lists them; the cursor undoes one that has an undo (the proxy setting) and keeps another.
- **On screen:** the review as recorded. Title: "Changed while closed? Guard shows it." / "Mudou com ele fechado? O Guard mostra."
- **VO en:** "If an extension or a setting Guard watches changes while the browser is closed, Guard shows it. You keep it, or undo it where Guard can."
- **VO pt-BR:** "Se uma extensão ou uma configuração que o Guard acompanha mudar com o navegador fechado, o Guard mostra. Você mantém, ou desfaz quando o Guard consegue."
- **Claims:** C13 (the limit C14 is on a card of the Guard short).
- **Note:** the recorded review also holds a `user.js` and a native-messaging finding, which offer "Show file" and "Keep" and no undo (C13). The line therefore says "where Guard can", and "a setting Guard watches", not "anything".

### T7 · 0:55–1:05 · AI under your control

- **Picture:** R08 `ai-bridge`: a neutral test client connects through MCP; the agent works in its own workspace (the band says so); the cursor presses the emergency stop, and the client's next call is refused.
- **On screen:** "AI that goes only as far as you let it" / "IA que vai só até onde você deixa"
- **VO en:** "By default, AI agents work in a profile of their own, with the permissions you grant, and the emergency stop refuses their next calls."
- **VO pt-BR:** "Por padrão, agentes de IA trabalham num perfil só deles, com as permissões que você dá, e a parada de emergência recusa as próximas chamadas."
- **Claims:** C15.
- **Rule 6:** no agent product is named or shown. The client is the project's test client, registered under a neutral name ("Test agent" / "Agente de teste"), which is all Nulavio's interface shows of it.
- **Notes:** "by default" is spoken, because an agent given one of your profiles works there (C15); that case is not shown. The stop is said as what it does: it refuses calls through Nulavio and closes the workspaces. It does not end the agent's own program (C15).

### T8 · 1:05–1:12 · Your choices

- **Picture:** quick cuts of R09 `password-manager`, R10 `search-provider` and R11 `dns`, each showing the full list of options as the build shows it. The search list marks its starting default (DuckDuckGo, C29) as the build marks it, beside the others; the password manager list marks the one in use (the browser's own in a new profile, C29). The voice-over names none.
- **On screen:** "Your choice, and you can change it" / "Você escolhe, e pode mudar depois"
- **VO en:** "Your password manager, your search engine, your DNS: you choose, and you can change your mind."
- **VO pt-BR:** "Seu gerenciador de senhas, seu buscador, seu DNS: você escolhe, e pode mudar de ideia."
- **Claims:** C16, C17, C18, C29.

### T9 · 1:12–1:19 · Honest limits

- **Picture:** motion card on an abstract background. No interface.
- **On screen:** "No telemetry. No account. No Nulavio server." then "It doesn't hide your IP address. For that, use Tor Browser." / "Sem telemetria. Sem conta. Sem servidor do Nulavio." then "Ele não esconde seu IP. Para isso, use o Tor Browser."
- **VO en:** "No telemetry, no account, no server of ours. And we tell you what it can't do."
- **VO pt-BR:** "Sem telemetria, sem conta, sem servidor nosso. E a gente diz o que ele não consegue fazer."
- **Claims:** C05, C20, C26.

### T10 · 1:19–1:25 · End card

- **Picture:** the lockup, nulavio.net, and the status.
- **On screen:**
  - "Free and open source · Public alpha for Fedora and Ubuntu" / "Livre e de código aberto · Alfa pública para Fedora e Ubuntu" (C24, C26)
  - The engine line from [claims.md](claims.md#engine-line), small.
  - The AI line, as the [message house](message-house.md#every-piece-carries) gives it: "Voice and music are AI-generated. The browser's interface is recorded from a real build. Titles and cards are motion graphics." / "A voz e a música foram geradas por IA. A interface do navegador foi gravada de uma versão real. Títulos e cartões são animação gráfica." (rule 4; the first sentence follows the cut's manifest)
- **VO en:** "Nulavio. Protected from the start. Honest by design."
- **VO pt-BR:** "Nulavio. Protegido desde o início. Honesto por princípio."

## Description text (for the video page)

- **en:** "Nulavio is a free, open-source browser for Linux, in public alpha for Fedora and Ubuntu. Every claim in this video, with the test or document behind it: <link to claims.md>. <AI line as on the end card: what is AI-generated, then> The browser's interface is recorded from a real build. Titles and cards are motion graphics. Built on Mozilla's Gecko engine. Nulavio is not affiliated with Mozilla. Firefox is a trademark of the Mozilla Foundation."
- **pt-BR:** "O Nulavio é um navegador livre e de código aberto para Linux, em alfa pública para Fedora e Ubuntu. Cada afirmação deste vídeo, com o teste ou documento que a sustenta: <link para claims.md>. <linha de IA como no cartão final: o que foi gerado por IA, e então> A interface do navegador foi gravada de uma versão real. Títulos e cartões são animação gráfica. Feito sobre o motor Gecko da Mozilla. O Nulavio não é afiliado à Mozilla. Firefox é uma marca registrada da Mozilla Foundation."
- **The link to claims.md** is a permanent link to a commit on `main`, or to a release tag, that contains the file as the piece was checked against it. The tag `v160.0.1-0.3` does not contain it: the register was added after that release. Before publishing, the link is opened and the file read at that commit.
- The platform's AI label is set on upload ([tools-and-budget.md](tools-and-budget.md#ai-disclosure)).

## Recordings the pipeline needs

The pipeline is built in [#173](https://github.com/nulavio/nulavio/issues/173), once, for the site and for this material. This list is what the trailer and the [shorts](shorts.md) need from it. It does not build anything.

### What #173's pipeline records today

Read on 2026-11-27 from [pull request #859](https://github.com/nulavio/nulavio/pull/859) at its head `83a4e98b`, which is open and not merged; its files are not in this branch, so they are named here and not linked.

- **Capture.** `scripts/site/record_site.py` drives a headless build in the release test container through Marionette, on throwaway profiles, and writes the browser window's own pixels as PNG frames with a timeline. The frames are few and are held: the three samples have 22 to 61 captured frames for scenes of 9 to 11 s. The frames are 1920×1200 (a 1280×800 window at 1.5).
- **Compose.** On the host, with Pillow and FFmpeg, it draws the cursor (eased paths) and a ripple on each click, and writes the files [below](#what-each-recording-yields).
- **Recorded, in pt-BR and en-US:** `profile-opens`, `link-routed` and `protected-unlocks`, as samples from a development package (this tree's Shell on the 160.0.1-0.2 engine).
- **Planned in its specification, not recorded:** the first launch, Guard, the search provider, Copy Link to Highlight and the AI Bridge.
- **Not in its list:** the site panel, a temporary profile, the password manager step, the DNS question and the listing of a locked folder. They are asked for here.
- **What a recording changes, and says in its manifest:** the automation cue removed from the window; the cursor drawn afterwards; typing shown at a fixed pace, each key really typed; the time a new instance takes to start cut out; and what the script set up before the scene (the profiles, a routing rule, a local test search engine).

Consequences for these scripts:

- **Only the browser window is recorded.** Anything outside it (a folder on disk, another app sending a link) is not footage. It can be shown only as a motion card built from what the capture step read, with the real names, and marked as a motion card. The capture step reads no folder listing today (R06b, R05).
- **Hover states do not show,** because the cursor is drawn afterwards. That the cursor is drawn in the compose step is settled in #859.
- **Size and frame rate.** #176 asks for 4K at 60 fps. The pipeline writes 1280×800 at 30 fps from held frames captured at 1920×1200, which is 16:10. Composing a 16:9 export at 1080p from those frames (the compose step has a `--width` option) was not tried, and 4K needs a larger capture, not tried either. Sixty real frames a second needs a private X display (Xvfb) in the test container, which changes a container and is the maintainer's to decide with this tool list. Recommendation: cut a sample from what the pipeline gives, and decide on Xvfb only if the held frames read poorly in it.
- **Aspect ratios.** A 1280×800 window does not fill a 9:16 or 1:1 frame. The shorts need either a crop that follows the cursor (each crop recorded in the manifest) or a second recording in a narrow window; #173 decides which, and the narrow window must be one of Nulavio's real layouts.

### What each recording yields

For each scene and language the pipeline writes:

| File | What it is | Where it is used |
|---|---|---|
| The full video | The whole scene, as a VP9 WebM and an H.264 MP4, muted and with no audio track | On the site, in a player with controls that starts only when the person presses play (never autoplay, nothing downloaded before). In the trailer and the shorts, cut in the edit with the voice and the music added there |
| The loop | At most 5 s of the scene, the part its script marks as the highlight, as an animated WebP at 10 frames a second that plays once and stops | On the site and in the README, where something may move by itself |
| The poster | One still frame | Under reduced motion, and before a video plays |
| Captions and transcript | WebVTT, and a transcript read from the interface | With every video |
| The manifest entry | Hashes and sizes, the build ID and engine version, the commit, the cuts, the notes above | Beside the files |

This follows the maintainer's [decision of 2026-11-27 on #173](https://github.com/nulavio/nulavio/issues/173#issuecomment-7210333555): **loops of at most 5 s that stop by themselves, and the full video with controls.** For this material it means:

- The trailer and the shorts are full videos. On nulavio.net and in the press kit each one sits in a player with controls, with captions and a transcript, and never starts by itself.
- Anything from this material that moves by itself on the site or in the README is one of the loops: 5 s at most, played once, silent. A trailer teaser, if one is wanted, is such a loop.
- No scene is planned around a loop longer than 5 s. A scene's point has to be readable inside its loop window, or the scene is shown only as a video.

### For every recording

- **A real build.** For the published pieces, a published Nulavio release; a development package of a merged commit only for samples, as #859's are. The manifest records the build ID, the engine version and the commit.
- **Throwaway everything.** A new HOME and registered engine profiles, on `tests/lib/harness.GeckoProfileSession`. Profile names in the recording's language, as the pipeline names them: Personal, Work, Banking / Pessoal, Trabalho, Bancos.
- **Fixture sites only.** Pages served locally by the pipeline, with neutral names and original text, never a real site with a real account (rule 7). The pipeline must not switch off a protection to make them load (I1 in [REVIEW.md](../../REVIEW.md)); a fixture is marked as a tracker only through the engine's test-entries pref in a test profile, as [`test_privacy.py`](../../tests/integration/test_privacy.py) does.
- **No real provider shown alone (rule 6).** In a scene that is not about search, the pipeline keeps a real search provider out of frame: a new window gets a fixture page first, and the profile where an address is typed searches with a local test engine. Each of these is a note in the manifest.
- **The automation cue.** The only change allowed to the interface is removing the window's `remotecontrol` attribute (the striped address bar), recorded in the manifest's `dom_changes`.
- **Cursor.** Eased moves and a visible ripple on each click, the same on every render, drawn in the compose step.
- **Same scene in both languages.** Each scene is recorded once per locale (en-US and pt-BR), with the same actions, so the cuts match.
- **Frame check.** Before a scene is used, every frame is checked for anything personal: notifications, other windows, file paths outside the throwaway HOME, a real e-mail address or account (rule 7). Today the compose step refuses a manifest that holds the home directory, the user name or the host name, and #859's frames were looked at by hand; the manifest has no field for a frame check. One is asked of #173.
- **Media size.** For the site, #859 keeps each file under 2 MB. The trailer's and the shorts' exports are heavier. Where they are kept (release assets, the site, not the git history) is decided in #173 against the 250 MB budget of [ADR 0013](../adr/0013-repository-layout.md).

### Scenes

"In #859" says whether the pipeline records the scene today (with the sample's length), plans it, or does not list it.

| ID | In #859 | What is recorded | The test it can start from | Used in |
|---|---|---|---|---|
| R01 `first-launch` | Planned ("First launch") | A new profile starts; the welcome card lists the protections that are on, as the build shows them; "use the defaults" | [test_firstrun_stage.py](../../tests/integration/test_firstrun_stage.py) `test_01`, `test_03` | T2, S1 |
| R02 `site-panel` | Not listed | A fixture page with a fixture tracker; the site panel lists it with the engine's count; tracking protection off for that site, then on | [test_privacy.py](../../tests/integration/test_privacy.py) `test_02`, `test_03` | T3, S1 |
| R03 `profile-opens` | Recorded (sample, 9 s) | Settings › Profiles lists Personal and Work; a click on Open for Work; the Work window opens, its band reading "Work · No password" | [test_profiles.py](../../tests/integration/test_profiles.py) | T4, S2 |
| R04 `link-routed` | Recorded (sample, 10 s) | In Personal, the work intranet's address is typed in the address bar; it opens in the Work window, whose band says "Opened by your rule · Change". A link sent by another app is not recorded: it starts outside the window | [test_routing.py](../../tests/integration/test_routing.py) `test_11`, `test_04b` | T4, S2 |
| R05 `temporary` | Not listed | A temporary window is opened; its last window closes. The folder's removal happens outside the window: it could only be a motion card, from a listing the capture step does not write today | [test_temporary.py](../../tests/integration/test_temporary.py) `test_01` | S2 |
| R06 `protected-unlocks` | Recorded (sample, 11 s) | Settings › Profiles with Banking locked; a click on Unlock; the artificial password typed on the unlock page, which says the profile locks again when its last window closes; the Banking window opens, its band reading "Banking · Protected" | [test_vault_profiles.py](../../tests/integration/test_vault_profiles.py) | T5, S3 |
| R06b `locked-folder` | Not listed | Not a recording: the names in the locked profile's folder, read by the capture step into the manifest, for a motion card. Until the pipeline writes it, T5 and S3 use their titles alone | [test_vault_profiles.py](../../tests/integration/test_vault_profiles.py) `test_profile_data_is_unreadable_when_locked` | T5, S3 |
| R07 `guard` | Planned ("Guard") | Changes made while closed (as in `test_02`: a proxy, malware protection off in `user.js`, a native-messaging manifest, a throwaway test CA); the Guard review; the proxy setting undone, another finding kept. The `user.js` and native-messaging cards show "Show file" and "Keep", with no undo | [test_guard.py](../../tests/integration/test_guard.py) `test_02` | T6, S4 |
| R08 `ai-bridge` | Planned ("AI Bridge") | A test MCP client connects; approval; the agent reads a fixture page in its workspace; a permission is revoked; the emergency stop; the client's next call is refused and its workspace closes | [test_ai_bridge.py](../../tests/integration/test_ai_bridge.py) `test_05`, `test_06` | T7, S5 |
| R09 `password-manager` | Not listed | The welcome's password manager step with every option listed and the one in use marked as the build marks it (the browser's own in a new profile); no account signed in | [test_firstrun_stage.py](../../tests/integration/test_firstrun_stage.py) `test_07` | T8, S6 |
| R10 `search-provider` | Planned ("Search provider") | The search choice with every provider listed and the starting default marked as the build marks it; the per-provider consent for suggestions; typing a neutral query | [test_search.py](../../tests/integration/test_search.py) `test_04`, `test_05` | T8, S6 |
| R11 `dns` | Not listed | The first tab's DNS question with every option listed | [test_dns.py](../../tests/integration/test_dns.py) `test_01` | T8, S6 |
| R12 `copy-link-to-highlight` | Planned ("Copy Link to Highlight") | A fixture article; a passage selected; the link copied and opened at the passage | [test_text_fragments.py](../../tests/integration/test_text_fragments.py) | a later short |

Every scene yields the files of [the table above](#what-each-recording-yields): the full video, and a loop of at most 5 s that plays once.

Rule 6 for R08–R11: every list shows all its options as the build shows them, nothing is added to present one as recommended, and no third-party account is signed in. A default the build sets (search, C29) is shown as the build marks it. Where a third party's name appears, it is because the list shows it, beside its alternatives.

One point to check before R10 is recorded: #859's specification describes the search scene as "every alternative shown and none preselected", and a new profile's search starts on DuckDuckGo (C29, `test_search.py` `test_04`). Which screen that scene records, and whether that screen marks a default, was not checked here. The scene records what the build shows on that day, and the voice-over names no provider either way.
