# Frontend audit after the alpha (2026-11-10)

Every Nulavio surface a person sees, audited on the real engine after `v160.0-0.1`: the window (band, Horizon, cues), the Shell pages, the launcher's start page and nulavio.net. One finding per item, with severity, evidence, cause and the proposed fix. Corrections follow in separate pull requests, MEDIUM first (no HIGH finding was confirmed).

**Result: 0 HIGH, 9 MEDIUM, 13 LOW**, plus one product decision for the maintainer (N-01). S-06 was LOW on the audited build and became MEDIUM on 2026-11-11, when connecting a phone was turned on (#42). The one HIGH carried in from the browser review of 2026-11-09 (V1, the unlock page offered the profile's password to the engine's password manager) is fixed on `main` (#15) and was verified again here.

## How it was done

- **Engine.** Nulavio 160.0, the alpha's build (BuildID `20261110215350`), copied to a scratch directory, with this tree's Shell, theme, branding and tools put in by `scripts/build/dev_sync.py` (commit `3b8b7a8`). No new engine build. Throwaway profiles only, headless.
- **States.** The integration suite drives every page into its states (`body[data-state]`, band cues, dialogs) with real backends: gocryptfs volumes, the AI bridge, Guard findings, a stand-in phone. It ran twice on that package, pt-BR: once plain (368 tests, 349 passed, 19 skipped, none failed) and once with a read-only rendered audit attached to every screenshot a test takes (318 audited captures: 188 of pages, 130 of the window).
- **Matrix.** A second pass opened each page's base and error states (45 scenes) in pt-BR and en-US, light and dark, and again in pt-BR with `prefers-contrast: more`, with forced colours and with reduced motion, each in both themes: 10 runs, 450 captures, with a keyboard pass over every focusable control.
- **Site and start page.** A local build of `site/` at 1366 and 390 CSS px, both themes, 12 pages and form states; the published site's response headers; the start page as the launcher renders it with the Nulavio engine, in both languages.
- **Rendered checks.** Composited text contrast (4.5:1, 3:1 for large text), glyph and field-boundary contrast (3:1), accessible names, target size (24 px), truncated or clipped text, horizontal overflow, dangling `aria-*` references, focus indicator and its contrast, headings, live regions, password fields.
- **Static checks.** Locale keys and placeholders in both languages, ids of the paired site pages, CSS classes with no user and classes with no rule, tokens used but not defined, inline code against each page's CSP, hard-coded colours, markup built from strings.
- **Reading.** `browser/shell/**` pages and shared sheets, `NulavioWindow.sys.mjs`, `window-band.css`, `horizon.css`, `browser/startpage/**`, `site/**`.

Evidence captures are in [`screenshots/audit-2026-11/`](screenshots/audit-2026-11); the full capture sets, the audit scripts and the raw JSON stayed outside the repository.

**Limits.** Headless only: no real KDE or GNOME session, no screen reader, no real high-contrast GTK theme (forced colours came from the engine's preference, with the default system palette). The assistant's panel was audited as rendered pixels in its sidebar and as a document only in a tab. Two assistant tests (`test_assistant_ui` 29 and 32) timed out once in the instrumented run and passed in the plain one; the audit hook slows every screenshot, so this is recorded as a test note, not a finding.

## Severity

| Level | Meaning |
|---|---|
| HIGH | A security cue or a consent is wrong or missing in a way that can change a safety decision, or a person cannot complete one (keyboard, screen reader) |
| MEDIUM | A surface shows a state that is not true, a requirement of `accessibility.md` fails on a real state, or text is cut |
| LOW | Inconsistency with the design system, a degraded edge with the words still there, dead code, polish |

## What was checked and holds

- **Contrast.** No text, glyph or field-boundary pair below its ratio in any base state: both themes, both languages, `prefers-contrast: more` and reduced motion. `scripts/brand/contrast.py`: 306/306 pairs.
- **Focus.** Every focusable control on every page shows the 2 px ring (3 px on radios and checkboxes, and under more contrast) at 3:1 or better. Under forced colours the ring is the system's `Highlight`, whose contrast belongs to the person's theme.
- **Languages.** en and pt-BR have the same keys and placeholders; no key is referenced and missing; no Portuguese text in the controls, headings and status lines of the en-US pages; `lang` follows the UI language. The four paired site pages have identical ids.
- **Markup safety.** No `innerHTML`, `insertAdjacentHTML` or `eval` in Shell pages or the site; no inline handler or script. The Shell declares no `web_accessible_resources`, so a web page cannot open or frame a Shell page. The site's pages have no script and pass their CSP as written.
- **Consent.** Deny is first, filled and focused on agent requests (page and assistant card); Cancel is on critical and destructive dialogs; risk tiers carry their glyph and words; the full-control and raw-automation consents are critical dialogs.
- **V1 (review 2026-11-09).** Saving is off for the Shell's own origin and no "save password" prompt appears after a typed password (`test_vault_ui` 02, on this package). The other pages that take a secret share that origin.
- **Window cues.** Private, temporary, agent, raw, Guard and their compositions keep their seals, patterns and words in both layouts and themes, and in fullscreen (the suite's own measurements, unchanged).
- **A theme change with a page open** repaints buttons as expected; the light buttons seen in some dark test captures come from how those tests switch the theme, not from the product.

## Findings

### Window

#### W-01 · MEDIUM — Pause, stop and protection text sit on the agent line pattern

In a window an agent drives, the band's row is ruled with horizontal lines. The seals and the page name have a solid fill, but "Sem senha", "Pausar agente …" and "Parar todos os agentes e assistente" are text buttons with no fill, so the lines run through their letters. In the light theme "Sem senha" reads as struck through.

- **Evidence.** [light](screenshots/audit-2026-11/w01-agent-band-light.png), [dark](screenshots/audit-2026-11/w01-agent-band-dark.png) (`test_layout_presets`, agent + Guard fixture, Lateral, 2× crop).
- **Cause.** `browser/shell/shared/window-band.css:222-227` draws the pattern on the row and gives only `.nv-band-header` the band fill; buttons are `background: transparent` (`:47-63`). The private row already fills these same controls (`:316-321`).
- **Fix.** In `[data-agent="true"]` rows, give the protection, route, pause, stop, task-stop and assistant-pause controls the opaque band fill. The pattern stays on the row; nothing gets weaker.
- **Test.** Rendered: in an agent window each of these controls has an opaque background equal to the band's (fails today: `rgba(0, 0, 0, 0)`).

#### W-02 · MEDIUM — A failed identity or protection read is cut to a few letters in the navigation row

With tabs on the side and no alert, the band lives in a fixed 224 px column of the navigation row and the profile name gives way to the protection state. That is right for "Sem senha" and "Protegido". When the protection read fails, the state is "Proteção desconhecida" (143 px) and even "Pessoal" becomes "Pess…"; when the identity read fails, the name itself is the message "Identidade do perfil indisponível", cut the same way. The two failure messages are the ones a person most needs whole.

- **Evidence.** [four rows](screenshots/audit-2026-11/w02-band-neutral-states.png): name 43 px wide needs 43 and gets 37 next to "Proteção desconhecida" (measured in the window; the unknown glyph takes 20 px more).
- **Cause.** `NulavioWindow.sys.mjs:544-548` (`#neutral`) counts alerts, a failed action and a routing notice, but not `#profileUnavailable` or an unknown protection; `window-band.css:359-409` then clips the column.
- **Fix.** A failed profile or protection read is not neutral: the band takes its own full row, as it does for a failed action.
- **Test.** Integration: with the profile read made to fail, the band drops `nv-neutral` and the name is not clipped (`scrollWidth <= clientWidth`).

#### W-03 · LOW — The band's initial is 10 px

`window-band.css:99` sets the tile's letter to 10 px; `accessibility.md` records 11 px as the one accepted exception. Decide which is right and make the document and the sheet agree.

#### W-04 · LOW — One rule of the band sheet is outside its `@-moz-document` scope

`window-band.css:416` (`:root[nulavio-own-page-pending] #identity-box.notSecure`) is the only rule not inside `@-moz-document url("chrome://browser/content/browser.xhtml")`. The sheet is loaded per browser window, so nothing else sees it today; the header comment says the sheet is "scoped strictly to the native window". Move the rule inside the block.

#### W-05 · LOW — The new tab's identity box still says "Extensão (Nulavio Shell)"

Known since the October audit (WCS-08) and deferred with the Home milestone in `component-inventory.md`. Recorded here because it is the first thing next to the address on every new tab; no change proposed in this round.

### Shell pages

#### S-01 · MEDIUM — Error states of five security moments keep dead controls or a false headline

A page that cannot do its job should say so and offer only what still works. Five states do not:

| Page and state | What it shows | Evidence |
|---|---|---|
| `ai/request.html`, `error` (a request that no longer exists: answered elsewhere, a restored tab) | No headline, no agent, and "Negar", "Permitir uma vez", "Permitir até o agente desconectar", none of which does anything | [capture](screenshots/audit-2026-11/s01-request-error.png) |
| `passwords/lookalike.html`, `invalid` | The warning headline, an empty alert, an empty address, a filled primary button with no text and no accessible name, and "Continuar e não avisar de novo para este par" with no handler | [capture](screenshots/audit-2026-11/s01-lookalike-invalid.png) |
| `vault/unlock.html`, a profile that no longer exists | "Este perfil está bloqueado" above "Não encontrado" | [capture](screenshots/audit-2026-11/s01-unlock-unknown.png) |
| `vault/methods.html`, same | A field asking for the password or recovery code, and "Gerar novo código de recuperação" and "Adicionar uma senha", for no profile | [capture](screenshots/audit-2026-11/s01-methods-unknown.png) |
| `warning/warning.html`, after "Excluir" fails | The error and nothing else: "Mostrar na pasta" is hidden too, on a file a verdict may have called dangerous | `warning/warning.js:32-39` |

- **Cause.** `ai/request.js:98-105` hides the buttons only for `expired`; `passwords/lookalike.js:47-49` sets the state and nothing else; `vault/unlock.js:230-241` and `vault/methods.js:245-248` announce the error over the page's normal markup; `warning.js` `finish()` hides `#actions` for both results.
- **Fix.** One rule for these pages: in an error state the headline names the error, controls that cannot work are hidden, and what can still help stays (close the tab, "Mostrar na pasta", "Tentar de novo" where the page lists it). No new state is invented: `error`, `invalid` and `unavailable` exist already.
- **Test.** Integration, per page: in the error state no enabled button without a handler is visible, every visible control has a name, and the headline is not the normal one. The lookalike test asserts the unnamed button today.

#### S-02 · MEDIUM — The new tab shows a check mark before "Proteções ativas neste perfil"

`pages.css:56-57` says "A state is not a 'safe' seal: the line carries no mark when all is on" and sets `content: none`. The mark is drawn anyway: the shared rule at `pages.css:39` (`:is(.facts dd, .here__summary, .firstrun__facts li)[data-level]::before`) takes the specificity of its most specific argument (0,2,2) and beats `.here__summary[data-level="ok"]::before` (0,2,1). The principle is "no green 'safe' and no 'tudo certo'" (`ux-principles.md`).

- **Evidence.** [capture](screenshots/audit-2026-11/s02-newtab-summary.png); computed `content: ""` with the check mask on `#here-summary[data-level="ok"]::before`.
- **Fix.** Make the exception win (`:where()` around the shared list, or the exception written with the same list); the facts under "Detalhes" keep their marks.
- **Test.** Integration: with every protection on, the summary's `::before` has `content: none`; with one off, the warning mark is there.

#### S-03 · MEDIUM — Settings › IA e automação scrolls sideways once an agent's configuration is shown

The configuration (`#ai-config`) and the wizard's command (`#ai-wizard-command`) are `<pre>` blocks with paths in them. They do not wrap or scroll on their own, so the card, the section and the page grow: at a 1141 px viewport the document was 1312 px wide, with the cards past the right edge. The token file's path alone is about 90 characters in a real home.

- **Evidence.** `test_ai_ui` 01 after "Conectar agente": `scrollWidth 1312 > clientWidth 1129`, in both themes (the capture shows a local path and is not published).
- **Cause.** `settings/settings.html:537,546` use `.notice.mono`; `.notice` (`components.css:184-190`) has no overflow rule and the grid item has `min-width: auto`.
- **Fix.** The block scrolls inside itself (`overflow-x: auto; max-inline-size: 100%; min-inline-size: 0`), keeping the text copyable as one line per line.
- **Test.** Integration: after connecting an agent, `document.documentElement.scrollWidth <= innerWidth` at 1141 px and at the narrow layout.

#### S-04 · MEDIUM — Refused fields are not marked on the Vault's forms

`accessibility.md`: "Invalid fields have a 2 px critical border and an associated text error". The unlock page and the confirmation field of the methods page do this since #15. These do not: the two password fields and the two recovery groups of `vault/create.html`, the new-password fields and the recovery groups of `vault/methods.html`, and the secret on `vault/phone.html`. The error text appears (in a separate `role="alert"` paragraph) and focus moves to the field, but the field has no `aria-invalid`, no critical edge and no `aria-describedby` to the message, and the message stays after the person types again.

- **Evidence.** [create, step 2](screenshots/audit-2026-11/s04-create-error-en-dark.png): "Use at least 8 characters." under a field with the ordinary border. `vault/create.js:138-147,193-194`, `vault/methods.js:159-160,209-219`, `vault/phone.js:93-95`.
- **Fix.** One helper in `lib/ui.js` that marks a field, ties it to its message and clears both on the next input; used by these forms (and by unlock, replacing its local copy).
- **Test.** Integration: a short password on create step 2 gives `aria-invalid="true"` and `aria-describedby` on the field; typing clears both.

#### S-05 · MEDIUM — The Guard review drops keyboard focus after each decision

"Desfazer" or "Manter" resolves a finding and the list is rebuilt; the button that had focus is gone and focus falls to the document. Only the last decision moves focus (to "Fechar"). A keyboard or screen-reader user reviewing eight changes starts from the top of the page eight times, on the page where each button changes a security setting.

- **Evidence.** `guard/review.js:85-88` (`render(left)` then `announce`), `:126-152` (focus only when the list is empty).
- **Fix.** After a decision, focus goes to the title of the finding that took its place (the next one, or the previous when the last of the list was resolved). The audit first asked for that finding's first action, and that is how it was built; the review before landing showed that a second Enter would then undo or keep a change nobody had read, so the title has the focus and the actions are one Tab away.
- **Test.** Integration (the Guard fixture of `test_guard`): after resolving the first of several findings, `document.activeElement` is the title of a finding inside the list, and Enter pressed again settles nothing.

#### S-06 · MEDIUM (was LOW) — The phone page takes the profile's secret without pointing at the band

`vault/phone.html` asks for "Senha ou código de recuperação deste perfil". The other pages that take a secret open with "Antes de digitar uma senha, confira o alto da janela…"; this one does not, because `lib/moment.js:31` lists `unlock`, `create` and `methods` only. It was LOW while connecting a phone was off (`nulavio.vault.phone.pairing`, D10 as audited). #42 turned it on (2026-11-11), so the page is now reachable by everyone with a protected profile: MEDIUM. Fixed together with S-04.

- **Evidence.** [capture](screenshots/audit-2026-11/s06-phone-no-band-line.png).
- **Fix.** Add `phone` to `SECRET_KINDS`; a test that every Shell page with a password field has the line.

#### S-07 · LOW — Five warning callouts have no triangle

The design system: "Warning: `status.warning` + ⚠ + words". These have the tint, the edge and the words only: `#few` on `vault/methods.html:26` ([capture](screenshots/audit-2026-11/s07-methods-few.png)) and `#thread-moved`, `#too-large`, `#truncated`, `#interrupted` on `assistant/panel.html:59,68,126,132`. Add the icon (`icon("warning", "callout__icon")`); a unit test that every `.callout--warning` and `.callout--critical` in the Shell has one.

#### S-08 · LOW — Unicode pseudo-icons left in the assistant's panel

#25 removed them elsewhere. Left: `⊘` in the private-window refusal (`assistant/panel.html:19`), `ⓘ` in the drift notice (`:47`), and "+" and "×" as text in `panel.js:241,258`. They change with the desktop font. Use `icon()` or the mask icons the rest of the Shell uses.

#### S-09 · LOW — Under forced colours, marks painted with a token colour disappear

Mask glyphs filled with `currentColor` survive forced colours; those filled with a token are painted in the canvas colour and vanish, leaving a gap: the check of `ok` facts, results and inline results (`components.css:118-129`, `pages.css:43`), the warning mark of first-run facts (`pages.css:337`), the "aberto" dot of the profile menu (`pages.css:225`). The words stay, so no state is lost. `accessibility.css:54-56` already repairs the error marks; extend that block.

- **Evidence.** [new tab under forced colours](screenshots/audit-2026-11/s09-forced-newtab.png): the six facts have no mark.

#### S-10 · LOW — An error in Settings leaves the page after 12 seconds

`lib/ui.js:306,371-374` clears the status line after 4 s, or 12 s for an error, and the inline mark after 4 s. The control shows the real value again, so nothing is misreported, but the reason is gone for someone who looked away. Keep an error until the next action or until dismissed.

#### S-11 · LOW — The look-alike page takes the "real site" from its own address

`passwords/lookalike.js:21-29` builds the primary action "Ir para {similar}" from query parameters. The page is opened only by the engine's own actor with the system principal and is not web-accessible, so a web page cannot reach it. As defence in depth, ask `nulavioPasswords` to confirm the pair before offering the button; an agent with navigation rights is the case the security review of 2026-11-10 is looking at.

#### S-12 · LOW — Small leftovers

- `.card__head` (`components.css:166`) has no user.
- `aria-labelledby` on plain `<div>`s (`newtab/newtab.html:190,208`) names nothing: a `div` has no role.
- `warning/warning.html` keeps its state on `<html>` (`warning.js:38,65,117`) while every other page uses `<body data-state>`; `lib/moment.js` reads both, the suite's helpers differ per page.
- Profile-state badges (`.badge--security`) are pills; warning badges and seals use the 4 px corner.

### Start page

#### P-01 · MEDIUM — With the Nulavio engine the start page contradicts itself, and one shortcut is wrong

The launcher's start page (profiles made by `bin/nulavio`) on Nulavio 160.0 says, in both languages:

- "Motor: Nulavio 160.0, compilado pelo Nulavio a partir do código-fonte verificado do Firefox (build de desenvolvimento)" and, in the footer, "roda sobre o motor Gecko do Mozilla Firefox, sem modificações". The engine carries the patch series, and the release build is not a development build.
- "Extensões: Ctrl Shift A". In this engine add-ons are Ctrl+Shift+F (`key_openAddons`, read from the window); the Shell's new tab is tested against the engine's keys, the start page is static.

- **Evidence.** [capture](screenshots/audit-2026-11/p01-startpage-pt.png). `browser/startpage/strings.json` (`T_FOOTER`, `T_ENGINE_NOTE_NULAVIO`), `browser/startpage/index.html:44`, `launcher/nulavio_launcher/profile.py:306-327` (only `T_ENGINE_NOTE` follows the engine).
- **Fix.** The footer follows the engine like the note does; the note for the Nulavio engine drops "development build" unless the build says it is one; the add-ons line is chosen from the engine's version or removed.
- **Test.** Unit (`render_startpage` with a Nulavio engine context): the page does not contain "sem modificações"/"unmodified"; the shortcut matches the table for that version.

#### P-02 · LOW — A repository path as a reference, and titles in another style

The footer sends the reader to `docs/security/residual-risks.md`, a path that exists only in a checkout. Card titles are small caps here and sentence case in the Shell since UX3G (`startpage.css`).

### nulavio.net

#### N-01 · DECISION (would be MEDIUM) — The landing describes phone and security-key unlock as available next to a download that says they are not

Since 2026-11-09 the landing sells the intended launch in the present tense, by the maintainer's decision. On 2026-11-10 the alpha became downloadable from the same page ("Alpha para o Fedora · Baixar"). The page says a protected profile opens with "uma chave de segurança FIDO2 ou a biometria do celular", shows both in the unlock mock-up and lists them in the comparison table ("Sim: senha, sistema, chave FIDO2 ou celular"); the alpha it links to says "ainda não disponível nesta versão" for both (D10, #13). "Pacotes assinados para Fedora e Ubuntu" has the same shape (Ubuntu is next, the page says so elsewhere).

Nothing here is an invented proof (no testimonial, count or audit), and the numbers in the proof row are backed by the repository. It is a product decision whether the landing keeps the launch tense now that a release exists: see "Decisions" below. No change is made in this round. #42 has since turned phone unlock on in `main`; once a release with it is out and the Companion can be installed, the phone half of this finding goes away. The security key and Ubuntu stay.

- **Evidence.** `site/index.html` (feature text, the `role="img"` unlock panel, the "Perfis cifrados no disco" row) and `site/en/index.html`; `vault/methods.html` "not yet" line.

#### N-02 · LOW — The published site sends Cloudflare's error-report headers

Responses from nulavio.net carry `report-to` and `nel` pointing at `a.nel.cloudflare.com` (checked 2026-11-11 00:01 UTC with a browser user agent). Browsers that implement Network Error Logging report failed requests there. The pages say "Este site não usa scripts, cookies nem análise de visitas", which is true of the pages (no script was injected: the Web Analytics beacon is off) and close to untrue of the host. Turn Network Error Logging off in the zone's dashboard; `scripts/site/verify_live.py` can then check for the header.

#### N-03 · LOW — Mock-up labels cut at 390 px, and three dead classes

In the agent-permissions mock-up, "Autônomo" and "Controle total" end in an ellipsis at 390 px (pt-BR and en). `.tile-coral` and `.tile-slate` (`landing.css`) and `.shot-frame` (`site.css`) have no user.

#### N-04 · LOW — "50 sites populares testados" carries no date

The figure comes from `docs/research/site-regression-2026-10.md`, run in October on the previous engine. Say when ("em outubro de 2026") or run it again on 160.

## Corrections

One slice per pull request, each with a test that fails before it, run on the packaged build with `dev_sync`. Every MEDIUM finding has a pull request open (2026-11-11); none is merged yet.

| Slice | Findings | Pull request |
|---|---|---|
| Error states of the security moments | S-01 | [#46](https://github.com/nulavio/nulavio/pull/46) |
| The band in an agent's window and after a failed read | W-01, W-02, W-04 | [#47](https://github.com/nulavio/nulavio/pull/47) |
| The new tab's summary mark | S-02 | [#49](https://github.com/nulavio/nulavio/pull/49) |
| Refused fields on the Vault's forms; the band line on the phone page | S-04, S-06 | [#50](https://github.com/nulavio/nulavio/pull/50) |
| Focus in the Guard review | S-05 | [#51](https://github.com/nulavio/nulavio/pull/51) |
| The agent's configuration block in Settings | S-03 | [#52](https://github.com/nulavio/nulavio/pull/52) |
| The start page with the Nulavio engine | P-01 | [#53](https://github.com/nulavio/nulavio/pull/53) |

LOW findings were fixed where a slice already touched the same lines (S-06 with S-04, W-04 with W-01). The others (W-03, W-05, S-07 to S-12, P-02, N-02 to N-04) wait for a polish round or for a decision below.

The audit ran on the build of `v160.0-0.1`. `main` has since moved to `v160.0-0.2` (the security release, #44); the corrections were rebased on it and verified on that release's build with `dev_sync`.

## Decisions for the maintainer

- **N-01.** Keep the launch tense on the landing now that the alpha is downloadable, or mark what the alpha does not have yet (phone and security-key unlock, Ubuntu packages).
- **N-02.** Turn off Network Error Logging for the nulavio.net zone (dashboard only).
- **W-03.** 10 px or 11 px for the band's initial.
- **N-04.** Date the compatibility figure or rerun it on 160.
