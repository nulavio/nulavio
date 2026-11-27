# Message house

> **Draft, not approved (2026-11-27).** Nothing has been recorded, generated or published ([#176](https://github.com/nulavio/nulavio/issues/176)).

One page that every script, post and caption builds on. Positioning, personas and voice come from the [brand strategy](../brand/strategy.md). Each proof cites a claim in the [claims register](claims.md), which links the test, ADR or document behind it.

## Positioning

- **en.** For people on Linux who want strong privacy without making a hobby of hardening their browser, Nulavio is the Gecko-based browser that is protected from the first launch, keeps each part of life in its own profile, and explains each choice, including what it cannot do.
- **pt-BR.** Para quem usa Linux e quer privacidade de verdade sem transformar o navegador num projeto de fim de semana, o Nulavio é o navegador com motor Gecko que já vem protegido desde a primeira vez que abre, separa cada parte da vida num perfil e explica cada escolha, inclusive o que ele não consegue fazer.

Personas (from the [strategy](../brand/strategy.md#audience)): Ana, an SRE on Fedora KDE; Bruno, a journalist; Carla, a designer who is curious about privacy; a small team lead. The trailer speaks to all four. Each short names the persona it serves.

## The promise

| | en | pt-BR |
|---|---|---|
| Line | **Your web. Your rules.** | **A web é sua. Seus dados também.** |
| Promise | Protected from the start, and honest about what it does and what it can't. | Protegido desde o início, e honesto sobre o que faz e o que não consegue fazer. |
| Sign-off | Private by default. Honest by design. | Privado por padrão. Honesto por princípio. |

## Three pillars

### 1. Protected from the first launch · Protegido desde a primeira vez que abre

- **en.** No hardening guide and no extensions to hunt down. A new profile opens with blocking and secure defaults on, and every default is written down with its reason.
- **pt-BR.** Sem guia de configuração e sem caçar extensões. Um perfil novo já abre com bloqueio e padrões seguros ligados, e cada padrão está documentado com o motivo.
- **Proof:** C01 blocking, Strict and HTTPS-Only in a new profile · C02 the welcome shows only what is really on · C03 each default with its reason and cost · C04 blocked trackers listed by the engine, a per-site switch that can be undone · C19 fingerprinting reads differ per site · C21 48 of 50 sites reached with the protections on, November 2026.
- **Trade-off we say out loud:** blocking breaks a site now and then (C04 is the way out).

### 2. Each part of your life apart, and locked when you want · Cada parte da vida separada, e trancada quando você quiser

- **en.** Work, banking and personal life each get a profile, and links go to the right one by your rules. A protected profile stays encrypted on disk until you unlock it. If something changes while the browser is closed, you hear about it.
- **pt-BR.** Trabalho, banco e vida pessoal ganham cada um seu perfil, e os links vão para o certo pelas suas regras. Um perfil protegido fica criptografado no disco até você desbloquear. Se algo mudar com o navegador fechado, você fica sabendo.
- **Proof:** C06 separate cookies, logins and extensions · C07 routing by your rules, no silent fallback · C08 temporary profiles deleted on close · C09 encrypted while locked · C10 no master key · C13 Guard reports changes made outside.
- **Trade-offs we say out loud:** profiles keep data apart but do not hide your IP address (C20). Lose every method and the recovery code, and the profile is gone (C10). Guard tells you; it does not prevent (C14).
- **Not yet:** phone unlock (C11, to confirm) and a FIDO2 key (C12, planned). They are said as "coming", never shown as working.

### 3. You choose, and you can check · Você escolhe, e pode conferir

- **en.** Your password manager, your search engine, your DNS and your AI agents: Nulavio sets each up the way you pick, with no partner preselected, and every choice can be undone. There is no telemetry and no Nulavio server. The code, the patches and every package's component list are public.
- **pt-BR.** Seu gerenciador de senhas, seu buscador, seu DNS e seus agentes de IA: o Nulavio configura cada um do jeito que você escolher, sem parceiro pré-escolhido, e tudo dá para desfazer. Não há telemetria nem servidor do Nulavio. O código, os patches e a lista de componentes de cada pacote são públicos.
- **Proof:** C16 password manager through its official extension · C17 suggestions off until you allow them · C18 DNS asked once · C15 agents in their own profile, with permissions and an emergency stop · C05 no telemetry, every unasked connection listed · C23 signed source, patches, SBOM · C26 MPL-2.0 · C22 the update targets.
- **Trade-off we say out loud:** a third-party service you pick (a search engine, a password manager, an AI provider) has its own privacy policy; Nulavio does not vouch for it.

## Boilerplate

- **en (49 words).** Nulavio is a free, open-source browser for Linux, built on Mozilla's Gecko engine. It blocks ads and trackers from the first launch, keeps each part of life in its own profile, encrypts the profiles you protect, and has no telemetry and no account. Nulavio is not affiliated with Mozilla.
- **pt-BR (56 palavras).** O Nulavio é um navegador livre e de código aberto para Linux, feito sobre o motor Gecko da Mozilla. Ele bloqueia anúncios e rastreadores desde a primeira vez que abre, separa cada parte da vida num perfil, criptografa os perfis que você protege e não tem telemetria nem conta. O Nulavio não é afiliado à Mozilla.

Status line to add while it is an alpha: "Public alpha for Fedora and Ubuntu" / "Alfa pública para Fedora e Ubuntu" (C24).

## What we never say

Strikethrough marks phrases we never use (the docs test ignores text inside `~~…~~`). The brand's [words we avoid](../brand/strategy.md#words-we-use--words-we-avoid) apply too.

| We never say | Why | We say instead |
|---|---|---|
| ~~"100% private"~~, ~~"completely secure"~~, ~~"unhackable"~~, ~~"bulletproof"~~ | Absolute claims are false for any browser (rule 2) | "Protected from the start", with the claim it rests on |
| ~~"Anonymous"~~, ~~"invisible online"~~, ~~"hides you"~~ | Nulavio does not hide your IP address (C20) | "Blocks trackers"; "for anonymity, use Tor Browser" |
| ~~"Sends nothing anywhere"~~, ~~"never connects to anything"~~ | A new profile does contact services (updates, Safe Browsing, lists): they are listed (C05) | "No telemetry and no Nulavio server" |
| ~~"Infostealer-proof"~~, ~~"stops malware"~~ | A browser cannot stop malware already running (C14) | "Guard tells you what changed while the browser was closed" |
| ~~"Always ships in 24 hours"~~ | 24 h is a target (C22) | "A 24-hour target for urgent engine fixes" |
| ~~"Unlock with your phone"~~ (as working today) | Not confirmed for the release (C11) | "Coming: unlock with your phone" |
| ~~"Better than Brave"~~, ~~"the most private browser"~~ | No comparison without a dated source (rule 2); the videos make none | Nothing: comparisons stay on the site's dated table |
| ~~"Powered by Firefox"~~, ~~"Firefox Nulavio"~~, a Mozilla logo | The [strategy](../brand/strategy.md#correct-use-of-the-name-and-marks) forbids it (rule 6) | The engine line in [claims.md](claims.md#engine-line) |
| ~~"Works best with Proton Pass"~~, ~~"recommended search: Kagi"~~, any "partner" | No third party is the recommended choice (rule 6) | "Your password manager", "the search engine you pick", with the list of options on screen |
| ~~"AI-powered browser"~~ | On the brand's avoid list; the AI is something you connect and limit | "AI that goes only as far as you let it" |
| ~~"Thousands of users"~~, ~~"loved by…"~~, a quote from a person | Invented proof (rule 3) | Real numbers only, dated, from the sources in #176 step 5 |
| ~~"Nunca falha"~~, ~~"proteção total"~~, ~~"100% seguro"~~ (pt-BR) | Absolute claims (rule 2) | "Protegido desde o início" |

## Every piece carries

- The AI line, spoken or on the end card, and in the description: "Voice and music are AI-generated. Everything shown on screen is recorded from the real browser." / "A voz e a música foram geradas por IA. Tudo o que aparece na tela foi gravado do navegador de verdade." (rule 4)
- The engine line, when the engine is named (rule 6).
- "Alpha" while Nulavio is an alpha.
- In the description, the link to this file's claims for that piece (rule 2).
