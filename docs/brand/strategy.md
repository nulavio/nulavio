# Brand strategy — Nulavio

## Name

**Nulavio** blends *null* (`/dev/null`, where unwanted data goes), *navio* (Portuguese for "ship") and *navegação* ("navigation"). It suggests a vessel for moving through the web that leaves nothing useful behind for trackers.

- Pronunciation: PT-BR /nuˈla.vju/ ("nu-LA-viu"); EN "noo-LAH-vee-oh".
- In running text: **Nulavio** (capital N). The wordmark is lowercase: **nulavio**.
- The preview is called **Nulavio Preview** (Track A). Never "Nulavio Firefox" or "Firefox Nulavio".

## Mission

Make private, secure browsing the calm default on Linux, working with the tools people already trust.

## Vision

A web where the browser's defaults serve the person using it, every protection is explained, and every choice can be undone.

## Unique value proposition

**The Gecko browser that ships protection on day one, works with your password manager, explains every choice, and never phones home.**

Proof points (all verifiable in this repository): upstream sandbox verified per process; ad blocking tested and reversible; official Proton Pass / KeePassXC / Bitwarden extensions; 27 documented defaults; no Nulavio server.

## Audience

| Persona | Need | What wins them |
|---|---|---|
| **Ana, SRE on Fedora KDE** | Strong defaults without maintaining a `user.js` hobby; auditable config | `nulavio doctor`, annotated prefs, Guard, tests |
| **Bruno, journalist** | Fewer trackers, safer logins, clear warnings without panic | Calm UX, suspicious-login flow, honest limits |
| **Carla, designer, privacy-curious** | A browser that looks good and doesn't nag | Premium visual identity, quiet indicators |
| **Small team lead** | Consistent, reviewable browser profiles | Profiles, policies (Track B), SBOM |

## Positioning

For **privacy-conscious Linux users** who want strong protection without a hardening hobby, **Nulavio** is the **Gecko-based browser** that ships blocking and secure defaults, explains them, and plugs into their password manager. Unlike hand-tuned Firefox setups, it does not silently regress. Unlike "private browsers" that overpromise, it states what it cannot do.

## Tone of voice

Strikethrough marks phrases we never use (the docs test ignores text inside `~~…~~`).

**Precise, calm, plain, confident without bravado.** We inform, offer an action, and show the way back.

| Do | Don't |
|---|---|
| "Blocked 1 tracker on this page." (a real count from the engine) | ~~"You're 100% protected!"~~ |
| "This site isn't using HTTPS. Continue only if you trust your network." | ~~"DANGER! Hackers can see everything!"~~ |
| "Proton Pass will fill passwords. Firefox's own prompts are now off — you can switch back anytime." | ~~"Optimised your security settings."~~ |
| "A browser can't stop malware already running on your computer." | ~~"Infostealer-proof."~~ |
| PT-BR: "Este site não usa HTTPS. Continue só se confiar na sua rede." | ~~PT-BR: "PERIGO! Você está sendo hackeado!"~~ |

## Manifesto

> **EN** — The web should work for you. Not for the trackers following you, not for the ads chasing you, not for the defaults someone else chose. Nulavio blocks what watches you, keeps what you trust, and tells you plainly what it does and what it can't. Your route is yours. The trail behind you is nobody's business.
>
> **PT-BR** — A web deveria trabalhar para você. Não para os rastreadores que te seguem, nem para os anúncios que te perseguem, nem para padrões escolhidos por outros. O Nulavio bloqueia quem vigia, preserva o que você confia e diz com clareza o que faz e o que não consegue fazer. O caminho é seu. O rastro não é da conta de ninguém.

## Slogans

| EN | PT-BR | Use |
|---|---|---|
| **Your web. Your rules.** | **A web é sua. Seus dados também.** | Primary |
| Browse forward. Leave no trail. | Navegue adiante. Não deixe rastro. | Symbol story (the dissolving route) |
| Private by default. Honest by design. | Privado por padrão. Honesto por princípio. | Docs, about page |
| Calm protection for the open web. | Proteção serena para a web aberta. | Onboarding |

## Words we use · words we avoid

| Use | Avoid |
|---|---|
| protect, block, isolate, verify, explain, choose, undo, local, limits, trade-off, your data | ~~unhackable, military-grade, bulletproof, 100%, guaranteed, zero-risk, invisible, anonymous (unless technically true), "AI-powered", fear words ("hackers are watching")~~ |
| "tracker", "ad", "fingerprinting" (with one-line explanations) | jargon without explanation ("CNAME cloaking") in primary UI |
| "Nulavio isn't affiliated with Mozilla" (when the engine is mentioned) | "powered by Firefox" as a badge; any Mozilla logo |

## Correct use of the name and marks

- Use the official SVGs in [`assets/logo/`](assets/logo/). Never retype the wordmark in a font.
- Follow [guidelines.md](guidelines.md) for clear space, minimum sizes and prohibited uses.
- When mentioning the engine: "built on Mozilla's Gecko engine" or, for the preview, "runs on the unmodified Mozilla Firefox engine" plus "Nulavio is not affiliated with Mozilla. Firefox is a trademark of the Mozilla Foundation."

## Trademark and availability status

**Nulavio is a candidate name. It is not registered by this project, and nothing here should be read as clearance.** Before any public launch:

| Item | Status (observed 2026-10-24, updated 2026-10-25) | Action |
|---|---|---|
| INPI (Brazil), classes 9 and 42 | **No mark "nulavio"** (pePI brand search by the maintainer, 2026-11-10 18:44, data current to 2026-11-10) | A search does not clear the mark: INPI examines registrability when an application is filed. File in classes 9 and 42 if the name is kept |
| USPTO / EUIPO / WIPO | **No mark "nulavio"**, live or dead (USPTO trademark search, TMview "contains", WIPO Global Brand Database, by the maintainer on 2026-11-10) | Exact-word searches only; similar-sounding or design marks were not searched and no counsel reviewed them |
| **`nulavio.net`** | **Registered on 2026-10-25 and configured** (Cloudflare Registrar and DNS): site on Cloudflare Pages (`nulavio.pages.dev`), `www` → apex 301; Always Use HTTPS, minimum TLS 1.2, HSTS 6 months without preload; DNSSEC on (DS published, answers validate); Email Routing receives only `security@nulavio.net` (forwarded to the maintainer, catch-all off); SPF, DKIM and DMARC `p=reject`; Certificate Transparency monitoring on. Expires 2027-10-25 | Keep auto-renew on. Some DNS filters block newly registered domains for weeks (seen on the maintainer's network): test with DNS-over-HTTPS |
| `nulavio.com` | Registered on 2026-10-18 by someone else as far as this project knows (RDAP: registrar lock, nameservers `*.share-dns.*`); not used by the project | Watch for confusion or abuse; consider `.com.br` as a defensive registration |
| `nulavio.org`, `.dev`, `.app`, `.io`, `.com.br` | NXDOMAIN via public DNS (likely unregistered; `.org` RDAP 404) | Optional defensive registrations |
| GitHub `nulavio` | **Organization created and the repository moved there** (2026-11-10); `nulavio/nulavio` is public | Verify `nulavio.net` for the organization |
| Mastodon / Bluesky / X handles | Not checked | Reserve |
| Reverse-DNS app ID (Flathub, D-Bus) | **`net.nulavio.Nulavio`** (domain controlled since 2026-10-25). The preview keeps `nulavio-preview` until Track B packaging | Apply with the RPM (desktop file, AppStream metainfo, Wayland app_id) |
