# Launch trailer (script)

> **Draft, not approved (2026-11-27).** Nothing has been recorded, generated or published ([#176](https://github.com/nulavio/nulavio/issues/176)).

- **Length:** about 80 s in English and up to 88 s in Portuguese (the window is 60–90 s). Exports in 16:9, 1:1 and 9:16, in English and Portuguese, with WebVTT captions and a transcript made from this script.
- **For:** all four personas in the [message house](message-house.md#positioning).
- **Built from:** real recordings of a Nulavio build (scene IDs `R…`, listed [below](#recordings-the-pipeline-needs)), plus motion titles and abstract backgrounds. AI makes only the voice, the music, the sound effects, the titles and the transitions (rule 1).
- **Claims:** each scene cites IDs from the [claims register](claims.md). A line whose claim changes status is rewritten before the render.
- **Voice-over:** about 170 words in each language, counted on 2026-11-27. Over about 75 s of speech that is 2.2 words a second in English, under the 2.3–2.5 a voice can say clearly. Portuguese is slower when spoken, so its cut stretches the motion scenes (T1, T9, T10) by up to 8 s.

## Scenes

Times are for the English cut. The Portuguese cut keeps the same scenes and stretches the motion parts, never the recordings.

### T1 · 0:00–0:06 · Opening

- **Picture:** motion only. The route symbol draws itself and its trail dissolves ([guidelines](../brand/guidelines.md); final art after [#175](https://github.com/nulavio/nulavio/issues/175)). No interface.
- **On screen:** "Your web. Your rules." / "A web é sua. Seus dados também."
- **VO en:** "A browser should work for you, from the very first launch."
- **VO pt-BR:** "Um navegador deveria trabalhar para você, desde a primeira vez que abre."
- **Claims:** none (brand line).

### T2 · 0:06–0:16 · Protected from the first launch

- **Picture:** R01 `first-launch`: a new profile starts and the welcome card lists the protections that are on.
- **On screen:** "Protected from the first launch" / "Protegido desde a primeira vez que abre"
- **VO en:** "Nulavio opens with ad and tracker blocking, Strict tracking protection and HTTPS-Only already on. Every default says why it's there."
- **VO pt-BR:** "O Nulavio já abre bloqueando anúncios e rastreadores, com proteção contra rastreamento no modo Estrito e só HTTPS. Cada padrão diz por que está ali."
- **Claims:** C01, C02, C03.

### T3 · 0:16–0:24 · When a site breaks

- **Picture:** R02 `site-panel`: on a fixture page the site panel lists what the engine blocked, with the engine's own count. The cursor turns protection off for that site, then on again.
- **On screen:** the panel as recorded. Title: "Off for one site, never for all" / "Desligue num site, não em todos"
- **VO en:** "If a site breaks, you turn protection off for that site only, and back on whenever you like."
- **VO pt-BR:** "Se um site quebrar, você desliga a proteção só nele, e liga de novo quando quiser."
- **Claims:** C04.
- **Note:** the landing's "two clicks" stays off the voice-over unless the recording shows exactly two clicks.

### T4 · 0:24–0:34 · A profile for each part of life

- **Picture:** R03 `profiles`, then R04 `routing`: switching from Personal to Work, the band naming the profile; a link from another app opens in the Work profile, and the band says the rule opened it there.
- **On screen:** profile names as recorded (Personal, Work, Banking / Pessoal, Trabalho, Banco).
- **VO en:** "Work, banking and personal life each get their own profile, and every link opens in the one your rules choose."
- **VO pt-BR:** "Trabalho, banco e vida pessoal ficam cada um no seu perfil, e cada link abre no perfil que as suas regras escolhem."
- **Claims:** C06, C07.

### T5 · 0:34–0:43 · Encrypted while locked

- **Picture:** R06 `unlock`: a locked Banking profile; a motion card shows its folder's encrypted names, read by the capture step; the profile's password (a test password, masked) opens it.
- **On screen:** "Encrypted on disk while locked" / "Criptografado no disco enquanto bloqueado"
- **VO en:** "Protect a profile and it stays encrypted on disk until you unlock it. There's no master key, not even ours."
- **VO pt-BR:** "Proteja um perfil e ele fica criptografado no disco até você desbloquear. Não existe chave mestra, nem a nossa."
- **Claims:** C09, C10.
- **Not shown:** phone or FIDO2 unlock (C11 to confirm, C12 planned).

### T6 · 0:43–0:51 · Guard

- **Picture:** R07 `guard`: after changes made while the browser was closed, the Guard review lists them; the cursor undoes one and keeps another.
- **On screen:** the review as recorded. Title: "Changed while closed? You decide." / "Mudou com ele fechado? Você decide."
- **VO en:** "If something changes while the browser is closed, Guard shows it, and you undo it or keep it."
- **VO pt-BR:** "Se algo mudar com o navegador fechado, o Guard mostra, e você desfaz ou mantém."
- **Claims:** C13 (the limit C14 is on the end card of the Guard short).

### T7 · 0:51–1:00 · AI under your control

- **Picture:** R08 `ai-bridge`: a neutral test client connects through MCP; the agent works in its own workspace (the band says so); the cursor presses the emergency stop.
- **On screen:** "AI that goes only as far as you let it" / "IA que vai só até onde você deixa"
- **VO en:** "AI agents work in a profile of their own, with the permissions you grant, and one click stops them all."
- **VO pt-BR:** "Agentes de IA trabalham num perfil só deles, com as permissões que você dá, e um clique para todos eles."
- **Claims:** C15.
- **Rule 6:** no agent product is named or shown. The client on screen is the project's test client.

### T8 · 1:00–1:08 · Your choices

- **Picture:** quick cuts of R09 `password-manager`, R10 `search-provider` and R11 `dns`, each showing the full list of options, none highlighted as recommended.
- **On screen:** "Your choice, and you can undo it" / "Você escolhe, e pode voltar atrás"
- **VO en:** "Your password manager, your search engine, your DNS: you choose, and you can change your mind."
- **VO pt-BR:** "Seu gerenciador de senhas, seu buscador, seu DNS: você escolhe, e pode mudar de ideia."
- **Claims:** C16, C17, C18.

### T9 · 1:08–1:15 · Honest limits

- **Picture:** motion card on an abstract background. No interface.
- **On screen:** "No telemetry. No account. No Nulavio server." then "It doesn't hide your IP address. For that, use Tor Browser." / "Sem telemetria. Sem conta. Sem servidor do Nulavio." then "Ele não esconde seu IP. Para isso, use o Tor Browser."
- **VO en:** "No telemetry, no account, no server of ours. And we tell you what it can't do."
- **VO pt-BR:** "Sem telemetria, sem conta, sem servidor nosso. E a gente diz o que ele não consegue fazer."
- **Claims:** C05, C20, C26.

### T10 · 1:15–1:22 · End card

- **Picture:** the lockup, nulavio.net, and the status.
- **On screen:**
  - "Free and open source · Public alpha for Fedora and Ubuntu" / "Livre e de código aberto · Alfa pública para Fedora e Ubuntu" (C24, C26)
  - The engine line from [claims.md](claims.md#engine-line), small.
  - "Voice and music are AI-generated. Everything on screen is recorded from the real browser." / "A voz e a música foram geradas por IA. Tudo na tela foi gravado do navegador de verdade." (rule 4)
- **VO en:** "Nulavio. Protected from the start. Honest by design."
- **VO pt-BR:** "Nulavio. Protegido desde o início. Honesto por princípio."

## Description text (for the video page)

- **en:** "Nulavio is a free, open-source browser for Linux, in public alpha for Fedora and Ubuntu. Every claim in this video, with the test or document behind it: <link to claims.md at the release tag>. Voice and music are AI-generated; everything on screen is recorded from the real browser. Built on Mozilla's Gecko engine. Nulavio is not affiliated with Mozilla. Firefox is a trademark of the Mozilla Foundation."
- **pt-BR:** "O Nulavio é um navegador livre e de código aberto para Linux, em alfa pública para Fedora e Ubuntu. Cada afirmação deste vídeo, com o teste ou documento que a sustenta: <link para claims.md na tag da versão>. A voz e a música foram geradas por IA; tudo na tela foi gravado do navegador de verdade. Feito sobre o motor Gecko da Mozilla. O Nulavio não é afiliado à Mozilla. Firefox é uma marca registrada da Mozilla Foundation."
- The platform's AI label is set on upload ([tools-and-budget.md](tools-and-budget.md#ai-disclosure)).

## Recordings the pipeline needs

The pipeline is built in [#173](https://github.com/nulavio/nulavio/issues/173), once, for the site and for this material. This list is what the trailer and the [shorts](shorts.md) need from it. It does not build anything.

What #173 has so far (read on 2026-11-27 from its branch, not yet merged): `scripts/site/record_site.py` captures the browser window's own pixels frame by frame from a headless build in the release test container, draws the cursor and click ripples afterwards, and writes WebM, MP4, an animated WebP, a poster, WebVTT and a manifest. Its scenes are `profile-opens`, `link-routed` and `protected-unlocks`, at 1280×800 CSS pixels scaled 1.5 and 30 fps. Three consequences for these scripts:

- Only the browser window is recorded. Anything outside it (a folder on disk, another app) is shown as a motion card built from what the capture step read, with the real names, and the manifest says so.
- Hover states do not show, because the cursor is drawn afterwards.
- #176 asks for 4K at 60 fps; the pipeline records 1920×1200 at 30 fps. Whether that is enough for the trailer is #173's and the maintainer's call.

### For every recording

- **A real build.** A published Nulavio release, or a dev package of a merged commit. The manifest records its version and build ID, as [`site/assets/shots/manifest.json`](../../site/assets/shots/manifest.json) does.
- **Throwaway everything.** A new HOME and registered engine profiles, as [`scripts/site/capture_site.py`](../../scripts/site/capture_site.py) does with `tests/lib/harness.GeckoProfileSession`. Profile names in the recording's language: Personal, Work, Banking / Pessoal, Trabalho, Banco.
- **Fixture sites only.** Pages served locally by the pipeline, with neutral names and text, never a real site with a real account (rule 7). The pipeline must not switch off a protection to make them load (I1 in [REVIEW.md](../../REVIEW.md)); a fixture is marked as a tracker only through the engine's test-entries pref in a test profile, as [`test_privacy.py`](../../tests/integration/test_privacy.py) does.
- **The automation cue.** The only change allowed to the interface is removing the window's `remotecontrol` attribute (the striped address bar), recorded in the manifest's `dom_changes`, as `capture_site.py` already does.
- **Cursor.** A path file per scene: eased moves and a visible ripple on each click, the same on every render. It is drawn in post-production, or by the automation itself; #173 decides.
- **Same scene in both languages.** Each scene is recorded once per locale (en-US and pt-BR), with the same actions, so the cuts match.
- **Frame check.** Before a scene is used, every frame is checked for anything personal: notifications, other windows, file paths outside the throwaway HOME, a real e-mail address or account (rule 7). The check is recorded in the manifest.
- **Media size.** Exports are heavy. Where they are kept (release assets, the site, not the git history) is decided in #173 against the 250 MB budget of [ADR 0013](../adr/0013-repository-layout.md).

### Scenes

| ID | #173 scene (in brackets: named in the issue, not yet recorded) | What is recorded | The test it can start from | Used in |
|---|---|---|---|---|
| R01 `first-launch` | (first launch) | A new profile starts; the welcome card lists the protections that are on; "use the defaults" | [test_firstrun_stage.py](../../tests/integration/test_firstrun_stage.py) `test_01`, `test_03` | T2, S1 |
| R02 `site-panel` | (new) | A fixture page with a fixture tracker; the site panel lists it with the engine's count; protection off for that site, then on | [test_privacy.py](../../tests/integration/test_privacy.py) `test_02`, `test_03` | T3, S1 |
| R03 `profiles` | `profile-opens` | The profile selector; switching Personal → Work; the band names each one | [test_profiles.py](../../tests/integration/test_profiles.py); `capture_site.py` C2 `bands` | T4, S2 |
| R04 `routing` | `link-routed` | A link opened from outside the browser lands in the rule's profile; the band says the rule opened it there | [test_routing.py](../../tests/integration/test_routing.py) `test_04`, `test_04b` | T4, S2 |
| R05 `temporary` | (new) | A temporary window from the selector; it closes; a motion card shows its folder before and after, from the capture step's listing | [test_temporary.py](../../tests/integration/test_temporary.py) `test_01` | S2 |
| R06 `unlock` | `protected-unlocks` | A locked protected profile; a motion card shows its folder's encrypted names, from the capture step's listing; the test password opens it; it locks again when its last window closes | [test_vault_profiles.py](../../tests/integration/test_vault_profiles.py) `test_profile_data_is_unreadable_when_locked`; `capture_site.py` C1 | T5, S3 |
| R07 `guard` | (Guard) | Changes made while closed (as in `test_02`: a proxy, malware protection off in `user.js`, a native-messaging manifest, a throwaway test CA); the Guard review; one undone, one kept | [test_guard.py](../../tests/integration/test_guard.py) `test_02`; `capture_site.py` C3 | T6, S4 |
| R08 `ai-bridge` | (the AI Bridge) | A test MCP client connects; approval; the agent reads a fixture page in its workspace; a permission is revoked; the emergency stop | [test_ai_bridge.py](../../tests/integration/test_ai_bridge.py) `test_05`, `test_06`. `capture_site.py` could not capture the agent's band without a live session: the pipeline needs one | T7, S5 |
| R09 `password-manager` | (new) | The welcome's password manager step with every option listed, none signed in | [test_firstrun_stage.py](../../tests/integration/test_firstrun_stage.py) `test_07` | T8, S6 |
| R10 `search-provider` | (choosing a search provider) | The search choice with every provider listed; the per-provider consent for suggestions; typing a neutral query | [test_search.py](../../tests/integration/test_search.py) `test_04`, `test_05` | T8, S6 |
| R11 `dns` | (new) | The first tab's DNS question with every option listed | [test_dns.py](../../tests/integration/test_dns.py) `test_01` | T8, S6 |
| R12 `copy-link-to-highlight` | (Copy Link to Highlight) | A fixture article; a passage selected; the link copied and opened at the passage | [test_text_fragments.py](../../tests/integration/test_text_fragments.py) | a later short |

Rule 6 for R08–R11: every list shows all its options, with none presented as recommended, and no third-party account is signed in. Where a third party's name appears, it is because the list shows it, beside its alternatives.
