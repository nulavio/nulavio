# Message house

> **Draft, not approved (2026-11-27).** Nothing has been recorded, generated or published ([#176](https://github.com/nulavio/nulavio/issues/176)).

One page that every script, post and caption builds on. Positioning, personas and voice come from the [brand strategy](../brand/strategy.md). Each proof cites a claim in the [claims register](claims.md), which links the test, ADR or document behind it.

## Positioning

- **en.** For people on Linux who want strong privacy without making a hobby of hardening their browser, Nulavio is the Gecko-based browser that is protected from the first launch, keeps each part of life in its own profile, and explains each choice, including what it cannot do.
- **pt-BR.** Para quem usa Linux e quer privacidade de verdade sem transformar o navegador num projeto de fim de semana, o Nulavio é o navegador com motor Gecko que já vem protegido desde a primeira vez que abre, separa cada parte da vida num perfil e explica cada escolha, inclusive o que ele não consegue fazer.

Used as public copy, the positioning carries the engine line of [claims.md](claims.md#engine-line), because it names the engine. "Protected from the first launch" stands for C01 as written there: the engine's protections are on from the first start, and uBlock Origin starts blocking once its lists have loaded.

Personas (from the [strategy](../brand/strategy.md#audience)): Ana, an SRE on Fedora KDE; Bruno, a journalist; Carla, a designer who is curious about privacy; a small team lead. The trailer speaks to all four. Each short names the persona it serves.

## The promise

| | en | pt-BR |
|---|---|---|
| Line | **Your web. Your rules.** | **A web é sua. Seus dados também.** |
| Promise | Protected from the start, and honest about what it does and what it can't. | Protegido desde o início, e honesto sobre o que faz e o que não consegue fazer. |
| Sign-off | Private by default. Honest by design. | Privado por padrão. Honesto por princípio. |

## Three pillars

### 1. Protected from the first launch · Protegido desde a primeira vez que abre

- **en.** No hardening guide and no extensions to hunt down. On the first launch Nulavio sets up ad and tracker blocking by itself and starts with secure defaults on, and each default it changes is written down with its reason.
- **pt-BR.** Sem guia de configuração e sem caçar extensões. Na primeira vez que abre, o Nulavio configura sozinho o bloqueio de anúncios e rastreadores e já começa com padrões seguros ligados, e cada padrão que ele muda está documentado com o motivo.
- **Proof:** C01 uBlock Origin installed by Nulavio at the first start and blocking once its lists load; Strict and HTTPS-Only on from the first start · C02 the welcome shows only what is really on · C03 each default with its reason and cost · C04 blocked trackers listed by the engine, and a per-site switch for the engine's tracking protection that can be undone · C19 fingerprinting reads differ per site while the protection is on for the site · C21 48 of 50 sites reached with the protections on, November 2026.
- **Trade-offs we say out loud:** blocking breaks a site now and then. When the engine's tracking protection is the cause, the per-site switch is the way out (C04); when a uBlock Origin filter is, the way out is uBlock Origin's own list of trusted sites, which that switch does not touch. And the ad blocking needs the network once: uBlock Origin and its lists are fetched at the first start (C01).

### 2. Each part of your life apart, and locked when you want · Cada parte da vida separada, e trancada quando você quiser

- **en.** Work, banking and personal life each get a profile, and links from other apps and the addresses you type go to the profile your rules name. A protected profile's folder stays encrypted on disk while it is locked. If an extension is added or changed, a certificate authority is added, or a protective setting that Guard watches changes while the browser is closed, Guard tells you at the next start.
- **pt-BR.** Trabalho, banco e vida pessoal ganham cada um seu perfil, e os links vindos de outros aplicativos e os endereços que você digita vão para o perfil que as suas regras indicam. A pasta de um perfil protegido fica criptografada no disco enquanto ele está bloqueado. Se uma extensão for adicionada ou alterada, uma autoridade certificadora for adicionada, ou uma configuração de proteção que o Guard acompanha mudar com o navegador fechado, o Guard avisa no próximo início.
- **Proof:** C06 separate cookies, logins and extensions · C07 your rules route links from other apps and typed addresses: open there, ask first or never switch, with no silent fallback · C08 a temporary profile is deleted when its browser closes · C09 the profile's folder is encrypted while locked · C10 no master key · C13 Guard reports the changes it watches (an extension added, changed or removed; a certificate authority added; a watched setting changed), and undoes the kinds it can.
- **Trade-offs we say out loud:** profiles keep data apart but do not hide your IP address (C20). A link clicked inside a page stays in the current profile unless you turn in-page routing on; an "ask first" rule asks before it opens anything, and a locked profile asks to be unlocked before the site loads (C07). A locked profile still shows its name and the sites routed to it, and an unlocked one can be read by a program running as you. If the system login is one of the ways a profile opens, a program running as you can open it even while it is locked, through your unlocked keyring, and a disk taken together with the keyring opens with your login password (C09). Lose every method and the recovery code, and the profile is gone (C10). Guard tells you; it does not prevent, it watches a list and not every setting, some findings have no undo, and it does not check a temporary profile or a browser an AI agent is driving (C13, C14).
- **Not yet:** phone unlock (C11) and a FIDO2 key (C12) are planned. Phone unlock is said as "coming soon" until [#227](https://github.com/nulavio/nulavio/issues/227) closes (the maintainer's [decision of 2026-11-27](https://github.com/nulavio/nulavio/issues/176#issuecomment-7210333283)), and a FIDO2 key as "planned". Neither is shown as working.

### 3. You choose, and you can check · Você escolhe, e pode conferir

- **en.** A password manager from the supported list, your search engine, your DNS and your AI agents: Nulavio sets each up the way you pick, none of them is a Nulavio partner, and you can change each choice later. The browser has no telemetry and, by itself, contacts no server run by Nulavio. The code, the patches and every package's component list are public.
- **pt-BR.** Um gerenciador de senhas da lista suportada, seu buscador, seu DNS e seus agentes de IA: o Nulavio configura cada um do jeito que você escolher, nenhum deles é parceiro do Nulavio, e dá para mudar cada escolha depois. O navegador não tem telemetria e, sozinho, não contata nenhum servidor mantido pelo Nulavio. O código, os patches e a lista de componentes de cada pacote são públicos.
- **Proof:** C16 one of the supported password managers, through its official extension · C17 suggestions off until you allow them · C18 DNS asked once on the first tab: the network's resolver or an encrypted service with fallback; encrypted-only is set in Settings · C15 agents in their own profile by default, with the permissions you grant, and an emergency stop that refuses their next calls through Nulavio · C29 no partner; the defaults as the build sets them, and a search list with none preselected · C05 no telemetry, no Nulavio server contacted by the browser by itself, every unasked connection listed · C23 signed source, patches, SBOM · C26 MPL-2.0 · C22 the update targets.
- **Trade-offs we say out loud:** a third-party service you pick (a search engine, a password manager, an AI provider) has its own privacy policy; Nulavio does not vouch for it. The welcome offers the password managers Nulavio supports, not every one (C16). A new profile's search starts on DuckDuckGo until you choose another (C29). The encrypted DNS offered on the first tab falls back to the network's resolver when the service does not answer (C18). The project does run a website, whose waitlist form keeps what a person submits, and the package repository; the browser contacts neither by itself (C05). The emergency stop closes what an agent does through Nulavio; the agent's own program runs outside the browser and is not ended by it (C15).

## Boilerplate

- **en (66 words).** Nulavio is a free, open-source browser for Linux, built on Mozilla's Gecko engine. It sets up ad and tracker blocking by itself on the first launch, keeps each part of life in its own profile, keeps the profiles you protect encrypted while they are locked, and has no telemetry and no account. Nulavio is not affiliated with Mozilla. Firefox is a trademark of the Mozilla Foundation.
- **pt-BR (71 palavras).** O Nulavio é um navegador livre e de código aberto para Linux, feito sobre o motor Gecko da Mozilla. Ele configura sozinho o bloqueio de anúncios e rastreadores na primeira vez que abre, separa cada parte da vida num perfil, mantém criptografados os perfis que você protege enquanto estão bloqueados e não tem telemetria nem conta. O Nulavio não é afiliado à Mozilla. Firefox é uma marca registrada da Mozilla Foundation.

The last two sentences are the engine line ([claims.md](claims.md#engine-line)): the boilerplate is never used without them, as the [strategy](../brand/strategy.md#correct-use-of-the-name-and-marks) asks.

Status line to add while it is an alpha: "Public alpha for Fedora and Ubuntu" / "Alfa pública para Fedora e Ubuntu" (C24).

## What we never say

Strikethrough marks phrases we never use (the docs test ignores text inside `~~…~~`). The brand's [words we avoid](../brand/strategy.md#words-we-use--words-we-avoid) apply too.

| We never say | Why | We say instead |
|---|---|---|
| ~~"100% private"~~, ~~"completely secure"~~, ~~"unhackable"~~, ~~"bulletproof"~~ | Absolute claims are false for any browser (rule 2) | "Protected from the start", with the claim it rests on |
| ~~"Anonymous"~~, ~~"invisible online"~~, ~~"hides you"~~ | Nulavio does not hide your IP address (C20) | "Blocks trackers"; "for anonymity, use Tor Browser" |
| ~~"Sends nothing anywhere"~~, ~~"never connects to anything"~~, ~~"no Nulavio server"~~, ~~"no server of ours"~~ | A new profile does contact services (updates, Safe Browsing, lists): they are listed. And the project runs a website with a waitlist form and a package repository (C05) | "No telemetry, and the browser contacts no Nulavio server by itself" / "Sem telemetria, e o navegador não contata nenhum servidor do Nulavio sozinho" |
| ~~"Infostealer-proof"~~, ~~"stops malware"~~ | A browser cannot stop malware already running (C14) | "Guard tells you what changed while the browser was closed" |
| ~~"Always ships in 24 hours"~~ | 24 h is a target (C22) | "A 24-hour target for urgent engine fixes" |
| ~~"Unlock with your phone"~~ (as working today) | Planned: the check on the real phone is open (C11, #227) | "Coming soon: unlock with your phone", until #227 closes |
| ~~"Blocks ads from the first second"~~, ~~"every link"~~, ~~"any change"~~, ~~"undo anything"~~, ~~"stops every agent"~~, ~~"nobody can read it"~~, ~~"works with any password manager"~~, ~~"keep what you already use"~~ | Each feature has a scope, and the claim states it (C01, C07, C09, C13, C15, C16, C18) | The claim's own conditions: "once its lists load", "links from other apps and typed addresses", "a locked profile asks to be unlocked first", "while it is locked", "the changes Guard watches", "undo where Guard can", "refuses their next calls", "one of the supported password managers", "encrypted, with fallback" |
| ~~"Better than Brave"~~, ~~"the most private browser"~~ | No comparison without a dated source (rule 2); the videos make none | Nothing: comparisons stay on the site's dated table |
| ~~"Powered by Firefox"~~, ~~"Firefox Nulavio"~~, a Mozilla logo | The [strategy](../brand/strategy.md#correct-use-of-the-name-and-marks) forbids it (rule 6) | The engine line in [claims.md](claims.md#engine-line) |
| ~~"Works best with Proton Pass"~~, ~~"recommended search: Kagi"~~, any "partner" | No third party is the recommended choice (rule 6) | "A password manager from the list", "the search engine you pick", with the list of options on screen |
| ~~"AI-powered browser"~~ | On the brand's avoid list; the AI is something you connect and limit | "AI that goes only as far as you let it" |
| ~~"Thousands of users"~~, ~~"loved by…"~~, a quote from a person | Invented proof (rule 3) | Real numbers only, dated, from the sources in #176 step 5 |
| ~~"Nunca falha"~~, ~~"proteção total"~~, ~~"100% seguro"~~ (pt-BR) | Absolute claims (rule 2) | "Protegido desde o início" |

## Every piece carries

In the video itself:

- **The AI notice** (rule 4), in its short form. It names exactly what the piece's manifest marks as AI-generated. With an AI voice and AI music: "Voice and music: AI-generated" / "Voz e música geradas por IA". With library music instead: "Voice: AI-generated" / "Voz gerada por IA". It is on screen, small, from the first frame until the first recorded scene ends, which is at least 8 s in every script here.
- **"Alpha"**, on the end card, while Nulavio is an alpha.
- **The engine line**, only in a piece whose voice or titles name the engine (rule 6). It then gets at least 7 s on screen, by the reading rate below. No script here names the engine in the video: the trailer and the shorts have no room for those 7 s, so the line is in their descriptions.

In the description:

- The AI line in full, in two sentences. The first is the notice above as a sentence: "Voice and music are AI-generated." / "A voz e a música foram geradas por IA." (or "Voice is AI-generated." / "A voz foi gerada por IA.", and the music's credit if its licence asks for one). The second says what is footage and what is not: "The browser's interface is recorded from a real build. Titles and cards are motion graphics." / "A interface do navegador foi gravada de uma versão real. Títulos e cartões são animação gráfica."
- The engine line, because the description names the engine ([claims.md](claims.md#engine-line)).
- The link to the [claims register](claims.md) for that piece (rule 2), at a merged commit or a release tag that contains it ([trailer](trailer.md#description-text-for-the-video-page)).

No piece says, in the video or in its description, that everything on screen is recorded: the titles, the cards and the backgrounds are not (rule 1). A motion card built from something the capture step read (a folder listing) is marked as a card on screen.

### Reading time

Text that a piece puts on screen (a title, a card, a notice; not the interface's own text) gets at least one second for every 20 characters, spaces included, counted over everything on screen at that moment and in the longer language. It is the rate the recording pipeline already holds captions to ([#859](https://github.com/nulavio/nulavio/pull/859): "at most 20 characters a second"). A notice that nobody speaks (the AI notice, the status, a limit, "coming soon") is never on a card that fails it. The counts are in [trailer.md](trailer.md#notices-and-their-reading-time) and [shorts.md](shorts.md), made on 2026-11-27 from the text as written; they are checked again on the first sample cut at 9:16, where the text is smallest, before anything is approved.
