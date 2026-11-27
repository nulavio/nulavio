# Nulavio threat model

Version: 2026-10-24 (Phase 0). Applies to the Track A preview and to Track B unless noted. Rows marked **(B)** need Track B.

## Scope and honest boundaries

Nulavio defends against threats that **arrive through the web, through extensions, and through the software supply chain**. It reduces, but **cannot eliminate**, damage from software that **already runs on the machine as the same user or as root**.

- A process running as your user can read your profile (cookies, session tokens, `logins.json` + `key4.db`), inject extensions, change preferences, read process memory (subject to `ptrace` restrictions) and log keystrokes on many setups. No browser can prevent that by itself.
- A process running as root can do all of the above and defeat every control in this document.
- Nulavio never claims "infostealer-proof". It aims for: minimal data at rest, early detection of tampering where cheap, and clear guidance.

### Assets

| ID | Asset | Where it lives |
|---|---|---|
| A1 | Session cookies and tokens | Profile `cookies.sqlite`, storage dirs, process memory |
| A2 | Saved credentials: engine password manager | Profile `logins.json` + `key4.db` (encrypted by Primary Password if set) |
| A3 | Vault data of external managers | Outside Nulavio (Proton/Bitwarden servers + extension storage; KeePassXC database) |
| A4 | Autofill data in transit | DOM of the page at fill time; extension ↔ page messaging |
| A5 | Browsing history, bookmarks, downloads | Profile `places.sqlite`, `downloads` dir |
| A6 | Integrity of the browser and its configuration | Engine package (root-owned), profile prefs, extensions, launcher checkout |
| A7 | Camera, microphone, location, screen | OS devices via portals/PipeWire |
| A8 | Local files | User's home directory |

### Adversaries

| ID | Adversary | Capability |
|---|---|---|
| T-WEB | Malicious or compromised website / ad network | Arbitrary HTML/JS in a content process, redirects, phishing UIs |
| T-EXT | Malicious or compromised extension (incl. hijacked update) | WebExtension APIs within granted permissions |
| T-NET | Network attacker | Observe/modify traffic, DNS spoofing, captive portals |
| T-LOCAL | Malware running as the same user (infostealer) | Same file and IPC access as the user |
| T-ROOT | Malware with root | Everything |
| T-SUPPLY | Supply-chain attacker | Tamper with dependencies, extension updates, build or package |

### Trust boundaries (summary; details in [trust-boundaries.md](../architecture/trust-boundaries.md))

TB1 web content ↔ sandboxed content process · TB2 content process ↔ parent process (IPC) · TB3 extension ↔ browser APIs/pages · TB4 browser ↔ native messaging host (process outside the sandbox) · TB5 browser/launcher ↔ filesystem (profile) · TB6 user session ↔ other local processes · TB7 network ↔ browser (TLS) · TB8 update/supply channels ↔ installation.

---

## Scenarios

Each scenario lists: assets · adversary · preconditions · trust boundary · impact · preventive controls · detective controls · limitations · tests · residual risk. "Now" means implemented and verified in the Track A preview.

### S1 — Malicious web page

| Field | |
|---|---|
| Assets | A1, A4, A5, A7, A8 |
| Adversary | T-WEB |
| Preconditions | User visits the page (directly, via ad, redirect or link) |
| Boundary | TB1, TB2 |
| Impact | Script execution limited to the origin; tracking; fingerprinting; drive-by exploit attempts |
| Preventive | **Now:** upstream site isolation (Fission), content sandbox level ≥ 4 with seccomp-bpf and user namespaces; ETP Strict; uBO; HTTPS-Only; permission prompts for devices. **Planned:** per-site permission dashboard (Shell) |
| Detective | Engine crash/hang reporting stays local; Guard flags a weakened sandbox or Fission |
| Limitations | Logic bugs in sites; zero-day engine exploits until patched |
| Tests | `test_04_content_processes_are_sandboxed`, `test_03_tracking_protection_strict_is_effective`, `test_08_ublock_blocks_and_is_reversible`, guard unit tests |
| Residual | **Medium.** Depends on engine patch latency (Track A: Fedora; Track B: our SLA) |

### S2 — Malicious or compromised extension

| Field | |
|---|---|
| Assets | A1, A2, A4, A5 |
| Adversary | T-EXT, T-SUPPLY (hijacked developer account or update) |
| Preconditions | User installed it, or an installed extension pushes a malicious update |
| Boundary | TB3 |
| Impact | With `<all_urls>`: read and modify every page, exfiltrate typed credentials, cookies via the `cookies` API |
| Preventive | **Now:** only Mozilla-signed extensions load; one default extension (uBO), pinned by SHA-256; Mozilla's add-on blocklist (Remote Settings) left enabled; extensions are off in private windows unless the user allows them. **Planned:** permission review screen in onboarding; "high-risk permission" labels; allow-list mode for managed profiles **(B)** |
| Detective | **Now:** `nulavio doctor` lists extensions and flags any not pinned by Nulavio. **Planned:** alert when a new extension appears outside the browser UI; diff permissions on updates |
| Limitations | Users can grant any extension broad access; we cannot audit closed-source update behaviour |
| Tests | `test_lock_is_well_formed`, `test_validation_rejects_untrusted_sources`, `test_tampered_cache_is_not_installed` |
| Residual | **Medium-high.** Extensions with broad host permissions remain the largest in-browser credential risk |

### S3 — Legitimate extension with excessive permissions

| Field | |
|---|---|
| Assets | A1, A4, A5 |
| Adversary | Negligent developer; later T-SUPPLY |
| Preconditions | Extension requests broader permissions than needed |
| Boundary | TB3 |
| Impact | Larger blast radius if compromised later |
| Preventive | **Now:** the lock records reviewed permissions; `refresh_extensions_lock.py` flags new ones before merge. **Planned:** UI explaining host permissions; recommend per-site access (Firefox optional host permissions, MV3) |
| Detective | Lock diff in code review; doctor inventory |
| Limitations | Password managers legitimately need `<all_urls>` |
| Tests | Lock unit tests |
| Residual | **Medium** |

### S4 — Compromised renderer (content process)

| Field | |
|---|---|
| Assets | A1 (other sites), A8 |
| Adversary | T-WEB with a memory-corruption exploit |
| Preconditions | Unpatched engine bug |
| Boundary | TB1 → TB2 |
| Impact | Code execution inside the sandbox; cross-site data only if isolation also fails |
| Preventive | **Now:** Fission (one site per process), seccomp-bpf syscall filter, user namespace (no filesystem view beyond brokered paths), no sandbox-disabling env vars (stripped by the launcher). **Planned (B):** CI gate that rebuilds and ships each security release |
| Detective | Crash reports kept local (no automatic submission); Guard |
| Limitations | Sandbox escapes exist in the wild periodically |
| Tests | `test_04_content_processes_are_sandboxed`, `test_env_strips_sandbox_and_remote_knobs` |
| Residual | **Medium.** Patch latency is the main lever |

### S5 — Sandbox escape

| Field | |
|---|---|
| Assets | All user-level assets (A1–A8) |
| Adversary | T-WEB with a chained exploit |
| Preconditions | Renderer compromise (S4) plus a parent/IPC or kernel bug |
| Boundary | TB2, kernel |
| Impact | Equivalent to T-LOCAL (see S13) |
| Preventive | Upstream sandbox; fast patching; **opt-in outer confinement** `nulavio run --confined` (bubblewrap; from a source checkout only, not part of 1.0, #283, #466): the browser sees only its profile and Downloads in the home folder, its writes elsewhere stay in memory, its runtime folder holds only the display and sound sockets (no session bus, no user service manager, no X server; a session with X11 only is refused), its `/dev` is bubblewrap's own with only the GPU and cameras put back, its System V IPC is its own, Nulavio's other profiles are not there wherever the data folder is, and the engine's sandbox is unchanged on Fedora ([spikes](phase5-spikes.md#bubblewrap)); on Ubuntu the `.deb`'s AppArmor profile keeps user namespaces available to the engine's sandbox, except inside the confined mode, where Ubuntu's bubblewrap policy removes them, so the confined mode refuses to start there (R46, [#282](https://github.com/nulavio/nulavio/issues/282)). Flatpak not now, SELinux module not adopted ([spikes](phase5-spikes.md)) |
| Detective | None reliable inside the browser |
| Limitations | Out-of-browser containment is the only further layer |
| Tests | Sandbox presence only (we cannot test escapes); `test_confine`, `test_confined` (what a confined browser can reach) |
| Residual | **Low likelihood, critical impact** |

### S6 — Phishing and lookalike domains

| Field | |
|---|---|
| Assets | A2, A3, A4 |
| Adversary | T-WEB |
| Preconditions | User lands on a lookalike or deceptive login page |
| Boundary | User perception; TB3 for autofill; TB25 for the look-alike check's window actors |
| Impact | Credential theft; MFA bypass via real-time proxy |
| Preventive | **Now:** Safe Browsing (phishing/malware) kept ON (lists downloaded from Google and matched locally; only hash prefixes leave the device; verified end to end by `test_14`); IDN punycode display rules; password managers fill only on matching origins (vendor behaviour; to certify); the look-alike login warning (flow D in [ux-flows](../brand/ux-flows.md), `NulavioPasswords`): when the person clicks, taps or types in a password field, in the tab's page or in any frame of it, the site of the field's document and of each document around it up to the tab's page (the address the engine gives each document, or for about:blank, about:srcdoc and blob: its principal's site) is compared with the sites of the logins kept in the browser's own password manager, locally, nearest first. It is suspicious when a part of its name reads like a saved site's name (confusable characters, "rn" for "m"), is one change away from it (a letter added, missing or replaced, or two letters swapped; two changes for a name of 8 letters or more), or joins it with a login word ("paypal-secure-login"). The same site is never warned, and a saved name shorter than 4 letters is not compared. A Nulavio page then replaces the tab's page and asks before the person goes on; "Continue" is remembered for the pair the page showed, only while the saved logins still give that pair for the address (otherwise nothing is remembered and the page stays), and for a field in a frame goes back to the tab's page. In a private window it is kept in memory for private windows only, until the last one closes, and nothing is written to the profile. **Planned:** passkeys preferred |
| Detective | Safe Browsing warnings; the look-alike warning page |
| Limitations | Brand-new phishing domains; AiTM proxies on exact-match lookalikes; the look-alike warning sees only the browser's own password manager and its fixed rules ([R41](residual-risks.md)); in Immersive, an opt-in layout, the address bar and the identity indicator are out of view over web pages and the band names the site instead ([R64](residual-risks.md), [ADR 0009](../adr/0009-immersive-layout.md)) |
| Tests | Guard rule for Safe Browsing prefs; integration `test_12` (key present) and `test_14` (Google's test phishing page is blocked). Look-alike warning: the rules in integration `test_passwords` `test_01_lookalike_rules`, the warning and "Continue" in `test_02_lookalike_site_shows_the_warning_and_continue_is_remembered` and the cases after it (in a private window: `test_06b`); fields in frames (a look-alike frame in another site's page, srcdoc, data: and blob: frames) in `test_01f` to `test_01j`; the window actors in unit `test_lookalike_actors`; the read of the saved logins (Primary Password, one look-alike pair) in unit `test_lookalike_logins`. No unit test checks the rules case by case |
| Residual | **Medium-high** (largest real-world credential loss vector) |

### S7 — Malicious downloads

| Field | |
|---|---|
| Assets | A6, A8, all |
| Adversary | T-WEB |
| Preconditions | User downloads and runs a file |
| Boundary | TB5, then the user |
| Impact | Local compromise (becomes S13) |
| Preventive | **Now:** files saved, never auto-opened; Safe Browsing download checks left on in Track A (Track B: page lists only, download reputation is partner-only, see R15); downloads written with mode 0600 (launcher umask). **Planned:** flow E warning for executable types; "show in folder" instead of "open" for scripts and AppImages |
| Detective | Download history |
| Limitations | Linux has no Mark-of-the-Web equivalent honoured by all file managers |
| Tests | `test_07_download_lands_privately` |
| Residual | **Medium** |

### S8 — Cookie/session leakage

| Field | |
|---|---|
| Assets | A1 |
| Adversary | T-WEB (cross-site), T-NET, T-LOCAL |
| Preconditions | Third-party contexts, HTTP, or local access |
| Boundary | TB1, TB7, TB5 |
| Impact | Account takeover via stolen sessions |
| Preventive | **Now:** Total Cookie Protection (cookieBehavior 5); ETP Strict; HTTPS-Only; profile 0700 / files 0600. **Planned:** optional "clear cookies on close" per site; container tabs per profile (flow G) |
| Detective | None for local theft |
| Limitations | Same-user malware reads `cookies.sqlite` (encryption at rest would not help: the key would also be readable by the user) |
| Tests | `test_03_…`, `test_09_profile_files_are_private`, `test_06_https_only_…` |
| Residual | **High against T-LOCAL**, low against T-WEB/T-NET |

### S9 — Autofill exfiltration

| Field | |
|---|---|
| Assets | A2, A4 |
| Adversary | T-WEB (hidden fields, injected iframes), T-EXT |
| Preconditions | Autofill fills without explicit user action, or into invisible fields |
| Boundary | TB3 |
| Impact | Silent credential capture |
| Preventive | **Now:** one provider at a time (`nulavio provider set` turns engine save/fill off for external providers); engine `signon.autofillForms.http` stays at its default (off). **Planned:** require a user gesture for fills on first use per site; never fill cross-origin iframes (certify providers) |
| Detective | Planned: fill log (origin + time only, no values) in Nulavio Guard |
| Limitations | Behaviour of third-party extensions is theirs; we can only certify and document |
| Tests | `test_provider_switch_is_reversible`; manual provider certification |
| Residual | **Medium** |

### S10 — Compromised native messaging host

| Field | |
|---|---|
| Assets | A2, A3 |
| Adversary | T-LOCAL replacing the host binary or its manifest; T-SUPPLY |
| Preconditions | Writable manifest or binary path |
| Boundary | TB4 |
| Impact | Host can impersonate KeePassXC towards the extension, or exfiltrate |
| Preventive | **Now:** `doctor` validates manifests: absolute path, binary exists, not group/world-writable, `allowed_extensions` shown. Native messaging is limited to the manifest's allowed extension IDs (engine). KeePassXC uses its own key exchange and association. **Planned:** warn if the host binary is user-writable and not package-owned |
| Detective | `doctor` |
| Limitations | `~/.mozilla/native-messaging-hosts` is user-writable by design; T-LOCAL can always swap it |
| Tests | Doctor checks (unit tests planned with fixtures) |
| Residual | **High against T-LOCAL**, low otherwise |

### S11 — Local malicious process as the same user (infostealer)

| Field | |
|---|---|
| Assets | A1, A2, A5, A6 |
| Adversary | T-LOCAL |
| Preconditions | Malware runs as the user (pirated app, malicious package, compromised dev dependency) |
| Boundary | TB6 (there is no boundary between same-user processes on a default desktop) |
| Impact | Theft of cookies/sessions, saved passwords (if no Primary Password, or after capturing it), extension injection (E8: sideloaded XPIs auto-enable), pref tampering |
| Preventive | Data minimisation: recommend an external vault (KeePassXC locks; Proton/Bitwarden time out) over engine-stored passwords; recommend a Primary Password if the engine store is used; profile 0700 (protects from *other* users only). **Planned:** short session lifetimes for sensitive sites (container + clear on close) |
| Detective | **Now:** Guard detects weakened security prefs before launch; doctor lists unpinned extensions; **Guard at run time (Track B)** reports changes made outside the browser since the last run: extensions, protective settings, certificate authorities, security modules, native-messaging hosts and their programs, policies, `user.js`, search engines ([hardening](hardening.md#guard-at-run-time-what-it-catches-and-how-it-can-be-bypassed)) |
| Limitations | **Fundamental.** Detection can be bypassed by malware that also edits Nulavio's state. Sandboxing the browser does not stop malware outside the sandbox from reading the browser's files |
| Tests | Guard unit tests; `test_10_guard_refuses_test_profile`; `test_guard` (tampered closed profile on the real engine) |
| Residual | **High. Out of scope for prevention; documented in [residual-risks](residual-risks.md)** |

### S12 — Malware with root

| Field | |
|---|---|
| Assets | All |
| Adversary | T-ROOT |
| Preconditions | Privilege escalation or malicious root package |
| Boundary | None |
| Impact | Total |
| Preventive | None within the browser. Host hygiene (updates, SELinux, signed packages) |
| Detective | None within the browser |
| Limitations | Absolute |
| Tests | n/a |
| Residual | **Accepted; out of scope** |

### S13 — Supply-chain attack on dependencies

| Field | |
|---|---|
| Assets | A6, then all |
| Adversary | T-SUPPLY |
| Preconditions | Compromised upstream artefact, dependency or CI |
| Boundary | TB8 |
| Impact | Malicious code shipped to users |
| Preventive | **Now:** launcher is stdlib-only Python (zero third-party runtime dependencies); extension XPIs pinned by SHA-256 + size + host allow-list + Mozilla signature; Firefox source releases verified against Mozilla's pinned key (E10); SBOM generated; CI actions pinned by commit SHA. **Planned (B):** hermetic container builds, reproducibility checks, signed RPMs, release provenance |
| Detective | Lock refresh shows hash and permission diffs; SBOM |
| Limitations | Mozilla and AMO are trusted roots |
| Tests | Extension integrity unit tests; `verify_firefox_release.py` |
| Residual | **Medium** |

### S14 — Attack on updates and packages

| Field | |
|---|---|
| Assets | A6 |
| Adversary | T-SUPPLY, T-NET |
| Preconditions | Unsigned or downgradeable update channel |
| Boundary | TB8, TB18 (signing in CI), TB19 (build on Blacksmith) |
| Impact | Malicious engine or extension installed; rollback to a vulnerable version |
| Preventive | **Now:** engine updates via Fedora's signed RPM repositories; AMO updates over HTTPS and signed; launcher removes `MOZ_ALLOW_DOWNGRADE` (keeps profile-downgrade protection). **Planned (B):** signed RPM repo, metadata expiry, no silent downgrade |
| Detective | `doctor` reports engine package ownership |
| Limitations | The Track A launcher itself is a git checkout (writable by the user) |
| Tests | `test_env_strips_sandbox_and_remote_knobs` |
| Residual | **Low-medium** |

### S15 — Third-party extensions stealing credentials

| Field | |
|---|---|
| Assets | A2, A4 |
| Adversary | T-EXT |
| Preconditions | A non-provider extension with `<all_urls>` reads password fields as they are filled |
| Boundary | TB3 |
| Impact | Credential capture regardless of which manager filled them |
| Preventive | **Sensitive sites profile** (template): its own profile, so other profiles' extensions never see its pages; web pages cannot install extensions in it; cookies, site data and history deleted when it closes; routing rules send chosen sites there ([spikes](phase5-spikes.md#sensitive-sites)). **Planned:** onboarding warning when extensions with all-site access are installed next to a password manager |
| Detective | doctor inventory |
| Limitations | Engine has no per-field isolation from extensions with host access |
| Tests | `test_profiles` 11 |
| Residual | **Medium-high** |

### S16 — Cross-origin redirects

| Field | |
|---|---|
| Assets | A1, A4 |
| Adversary | T-WEB (open redirects, OAuth mix-ups) |
| Preconditions | Chains of redirects across origins during login or payment |
| Boundary | TB1 |
| Impact | Token leakage via `Referer` or URL; phishing landing |
| Preventive | **Now:** default `strict-origin-when-cross-origin` referrer policy (engine default, not weakened); HTTPS-Only blocks downgrade hops; query-parameter stripping (part of ETP Strict); providers fill by final origin. **Planned:** surface "you were redirected from X" on login pages in flow D |
| Detective | History |
| Limitations | Site-side bugs |
| Tests | `test_06_https_only_upgrades_and_exception_is_revocable` |
| Residual | **Medium** |

### S17 — Typed text sent to search providers

| Field | |
|---|---|
| Assets | A3 (browsing history and intent) |
| Adversary | Search provider, anyone it shares data with |
| Preconditions | Remote search suggestions or trending searches on; typing in the address bar, including with an alias such as `@engine` |
| Boundary | TB12 |
| Impact | Every keystroke, including text never searched for (pasted passwords, private URLs), reaches a third party |
| Preventive | **Now:** suggestions and trending off by default (both tracks); Track B requires per-provider consent at the single fetch point (patch 0004), so consent for one engine does not cover others reached through aliases; the settings page names the host that receives the text |
| Detective | Nulavio settings show which providers receive typed text |
| Limitations | The preview had one global switch (R17, resolved: removed in #464); DNS is not measured by the test (R20) |
| Tests | `test_search` 02, 03, 05 |
| Residual | **Low** (Track B) / **Medium** (Track A with suggestions turned on) |

### S18 — Data crossing profiles

| Field | |
|---|---|
| Assets | A1 (sessions), A2 (credentials) |
| Adversary | A site the user visits in another profile; a mistaken switch |
| Preconditions | Several profiles (personal, work, banking) |
| Boundary | TB13 |
| Impact | A session or tracker cookie set in one profile is visible in another; a running profile deleted under the user's feet |
| Preventive | **Now:** each profile is a separate engine instance and directory; switching passes only an activation command, never cookies or storage; the engine's lock refuses deleting a running profile; switching reuses a running instance. Links from other apps are routed by the user's rules before any request; if the target cannot take a link, nothing is loaded and opening it elsewhere is an explicit choice |
| Detective | Toolbar shows the active profile's colour, icon and name |
| Limitations | Same-UID processes can read every profile (TB6, S11); routing moves only an address, never a session; with in-page routing on, a page chooses that address ([R45](residual-risks.md), [review](routing-m5-review.md)) |
| Tests | `test_profiles` 05, 06, 08; `test_routing`; for a new profile's search choice (#151): `test_search` 16 and `test_settings_search` 04 (the file is a provider key only, 0600; read at the first start only, removed unread later; a link never followed) |
| Residual | **Low** |

### S19 — Malicious or mistaken change reaching `main`

| Field | |
|---|---|
| Assets | A6, then everything users install |
| Adversary | T-SUPPLY through a pull request; a coding agent misled by content it read (prompt injection) or simply wrong; a stolen maintainer or agent token; a hosted service installed as a GitHub App with write access (the Codex connector, Blacksmith, CodeRabbit), compromised or misled |
| Preconditions | Write access to the repository (agents work with the maintainer's token); branch protection on `main` requires a pull request and four status checks but no approval; from 2026-11-12 agents review and merge their own pull requests |
| Boundary | TB16, TB20, TB8 |
| Impact | Weakened protections, a backdoor or a leaking workflow shipped in a build; secrets read by a workflow pushed to any branch |
| Preventive | **Now:** [pull request flow](../process/pull-requests.md) and branch naming (convention; opt-in pre-push hook); a recorded review before every merge and a second, independent review for the security-sensitive paths (convention); actions pinned by commit and least-privilege workflow permissions (unit test); fork pull requests get no secrets; the advisory AI review runs from `main` with read-only tools and posts through a fixed script, and is never a required check. branch protection on `main` (pull request required, administrators included; four required checks; linear history; no force push). **Proposed:** a fine-grained agent token without the Workflows permission and agent permission rules ([agent guardrails](../process/agent-guardrails.md)); the engine integration result as a required check |
| Detective | CI on every pull request; the AI review comment, including text that looks like prompt injection; a CI check that reports commits on `main` without a merged pull request (on; it reports after the push, it does not stop it) |
| Limitations | No person reads every change before it is merged: the agent that wrote it reviews and merges it, so a misled agent can carry a change all the way to `main`, and a token that can push a branch can merge a pull request whose required checks pass. The rule that only the maintainer approves a release is not enforced against that same token: the `release` environment's reviewer is the shared account, which may approve its own runs; administrators cannot bypass it since 2026-11-15 (both read on 2026-11-26), so the approval is required but does not tell the maintainer from an agent ([R60](residual-risks.md), [R62](residual-risks.md)); the engine integration result is read by hand; the AI review can miss problems or be misled; the AI review sends the diff and the files it reads to Anthropic's API; CodeRabbit takes its instructions from the pull request's own branch, and its App, like the Codex connector's and Blacksmith's, may write contents, workflows and pull requests whatever the repository's files say ([R67](residual-risks.md)) |
| Tests | `test_ai_review`, `test_post_ai_review`, `test_repo_hygiene`, `test_coderabbit_config` |
| Residual | **Medium** |

### S20 — Release metadata advertises an unverified or older build

| Field | |
|---|---|
| Assets | A6; integrity of download links and public release history |
| Adversary | T-SUPPLY; forged event data, tampered tag or manifest, stolen metadata token |
| Preconditions | Release metadata automation is deployed; PR creation additionally requires its optional dedicated token |
| Boundary | TB21, TB8 |
| Impact | Misleading download version or release notes; a repository write with a compromised token |
| Preventive | Implemented: trusted main checkout; published release fetched from GitHub; manifest build-provenance verification; tag/commit/engine-pin agreement; numeric versions compared before changing the site; public notes treated as text; only CHANGELOG.md and packaging/release.json staged; PR instead of main push; no signing or publication authority in this workflow |
| Detective | Unit tests execute workflow shell blocks with a fake GitHub CLI and disposable remote; CI and review on the generated PR; recovery artifact and explicit warning when the token is absent |
| Limitations | Provenance identifies a build workflow, not an honest build machine (TB19). Notes still need editorial review; no security or SLA verdict is inferred. A repository write token can propose other changes if stolen; its repository scope and lack of Workflows permission must be set by the maintainer. Activation and live post-publication execution remain unverified until configured |
| Tests | `test_release_metadata`, `test_release_metadata_workflow`, `test_release_notes` |
| Residual | Existing supply-chain and shared-account limits (S13, S19); this automation does not accept or reduce those risks by itself |

### S21 — A program on the session bus posing as KWin (keep above, #170) — removed

The item was removed before it shipped (#460, 2026-11-17): Nulavio no longer asks KWin for anything, so this scenario has no surface left. The table below is the record of what it was.

| Field | |
|---|---|
| Assets | Which pages are open (a window's id and its stacking); the profile's path |
| Adversary | T-LOCAL: any program of the same user, which can own the name `org.kde.KWin` on the session bus where KWin does not run, or replace KWin |
| Preconditions | The person opens the View menu (the item reads its state: the first time in a window, that sends the random caption and gets the window's id), or uses the item or Ctrl+Alt+K (which also sends the script, with the profile's path) |
| Boundary | TB10 |
| Impact | The program receives what Nulavio asks KWin: the absolute path of the profile (in `loadScript`'s argument), the random caption used to find the window, and the window's id; it decides whether the menu item is enabled and what state it shows; it can answer falsely about that one window's stacking. It does not receive page content or addresses (the caption is a random mark, not the page's title) |
| Preventive | Only on the person's action (opening the View menu, the item, the key). The script holds only an id checked as a UUID and a boolean, from a new 0600 file in a new 0700 directory of the profile that the run itself creates, both removed after the run; one change at a time. The window counts only when the answer names this process's id and the random caption |
| Detective | The state shown is read back from what answers; a false answer is not detected |
| Limitations | A same-user program can already do much more (S11); this adds no way in, only one more thing it can watch |
| Tests | `test_keep_above` (elsewhere: refused and said; the script refuses an injected id; on Plasma by hand: KWin's own state read back) |
| Residual | Low; listed as R77 |

### S22 — A record that says the Rust code was checked when it was not (#430)

| Field | |
|---|---|
| Assets | The release's guard against Rust code that talks to the network around the engine's own stack, and so around a proxy the person set |
| Adversary | Whoever can get a change to `browser/build/networking-check.json` merged: a mistaken or misled author of a pull request, an agent on the shared account (S19, R62), or a compromised build laptop that writes a false record |
| Preconditions | A pull request that writes the record: one that moves the engine pin, changes a patch or the mozconfig, or only the record. The record says "passed" without a reading, or with a reading of another build; or it says "accepted" with an issue number, which nothing checks beyond its spelling |
| Boundary | TB22 |
| Impact | The engine pin, a patch or the configuration lands on `main` without the Rust code having been read for networking imports. Since #455 that does not reach a release by itself: the signing job requires the `networking-check.yml` workflow's attestation of the reading for the release's source and inputs (a new gate, not yet exercised by a release when this was written). Nothing is exposed by the record itself: the harm needs Rust code that does import such a function, which Mozilla's own builds would also carry. Since #364 the release build is cross-language and runs no engine check of its own: Nulavio's reading (the record in a pull request, the workflow's attestation for a release) is the only guard on what the shipped Rust code imports |
| Preventive | The record is on a CODEOWNERS path: by the project's rule a second, independent review reads it before it is merged; that rule is a convention the agents keep, which GitHub does not enforce (R62). It must name the pinned release and source digest, and carry the digests of the mozconfig, the variant and the patch stack of the tree it sits in (`test_track_b`, and `release_manifest.py verify` at the manifest's base commit). The script that writes it refuses a tree that is not the pinned release, a build made from another mozconfig, a build whose library says nothing, and a reading that looks empty. A unit test keeps Rust code and its build files out of Nulavio's patches |
| Detective | The record carries the SHA-256 of the library that was read: anyone with a build of the same inputs can compare. `networking-check.yml` makes the reading itself whenever the configuration, the pin or the patch stack changes on `main`: a false record is contradicted by a failed run there, and by a release that cannot be signed |
| Limitations | CI cannot tell that the build and the reading happened: the record is a statement. "Accepted" is the maintainer's word only because a reviewer checks that the issue it names says so; it is bound to the mozconfig, variant and patch stack it was accepted for, like a reading. Nothing but the review rule stops the shared account from merging a false record (S19); what stops a release built on one is the attestation, which the shared account can obtain by making the workflow pass, or by changing what the workflow runs: the workflow itself (`.github/`), the reading, the claim and the patch applier (`scripts/build/networking_check.py`, `apply_patches.py`), the build script and the one that builds its image (`scripts/build/build_nulavio.sh`, `build_image.sh`) or the build container's file (`ci/containers/fedora-build.Containerfile`). All of them are CODEOWNERS paths, so such a change is one the project's rule sends to a second review, which is a convention and not enforced (S19, R62). The shipped binary itself is not read. The reading build and the release build may get two versions of the Rust compiler from the container's package manager: the claim names the compiler, so that is a release the signing job refuses until a reading is made with the same one (#472), and what names it is each build's own configuration, on the build machine. No engine check stands behind the reading: it ran in every release build up to 160.0-0.6 and runs in none since #364 |
| Tests | `test_networking_check`, `test_track_b` (`NetworkingCheckRecordTest`), `test_release_manifest` |
| Residual | Low; listed as R79. It takes Rust code of Mozilla's that imports one of those functions and, for a release, a run of the workflow that says it does not (the Limitations say who could make it say so). The engine's build checks for that in any release-mode build that is not cross-language; whether Mozilla's own automation makes such a build of each release was not verified, so nothing here leans on it. The attestation gate is new (#455): until a release has been signed through it, read this as Low to Medium |

---

### S23 — What a click sends to a translation service (#156)

| Field | |
|---|---|
| Assets | The text the person selects; the address of the page they act on, and what it carries (a token in a query) |
| Adversary | T-WEB: a page that steers what is selected; a service the person added (it keeps what it receives); a service address the person was told to type |
| Preconditions | The person added a web service in Settings (none is added by default) and clicks a menu item that names it |
| Boundary | TB23 |
| Impact | The service receives the selected text (at most 5,000 characters) or the page's address with its query, on that click. A page can arrange what is selected, but not make the click |
| Preventive | Nothing before the click; items only for services the person added, each naming its service; the address's fragment is removed; literal addresses of this computer and of private, shared, link-local and reserved ranges (IPv4, and IPv6 including the forms that carry an IPv4 address) and names without a dot or with a listed local suffix are refused; private windows show the items only when allowed; a typed service must be https with a host not built from the page |
| Detective | The item says the service and, when refused, why; Settings says what each service receives |
| Limitations | A local name not on the suffix list (a LAN host named like a public one) is not recognised: names are not resolved to decide. A token a site put in its own query goes with the address |
| Tests | `test_web_services` (addresses, refusals, the request recorded and cancelled, private windows) |
| Residual | Medium for the token in a query; listed as R80 |


### S24 — Nulavio's automatic updates run as root (#241)

| Field | |
|---|---|
| Assets | The system: what runs as root; the installed browser's version |
| Adversary | T-LOCAL: a program of the person's account; a repository or mirror answering for Nulavio's |
| Preconditions | The RPM or .deb package is installed and the person turned automatic updates on (the administrator's password, through polkit) |
| Boundary | TB24 |
| Impact | At midnight and noon, as root, the package manager updates the `nulavio` package: with dnf from Nulavio's repository only (`--from-repo=nulavio`), with APT from the highest version among the system's sources |
| Preventive | Off after the install; nothing runs at install. Turning it on or off is the only privileged step, with the administrator's password every time, and runs one fixed helper that takes only `on` or `off`. The service and the timer require the flag file, update only the `nulavio` package, and use the package manager's own signature checks (`gpgcheck` and `repo_gpgcheck` in Nulavio's RPM repository, `Signed-By` in its APT source). With dnf, signing keys are imported only from the key the RPM installed (`/usr/share/nulavio/nulavio-packages.asc`), never from the repository file's `gpgkey` address: a key served there that the person has not accepted is not imported, and the run fails |
| Detective | `systemctl status nulavio-update.timer`, `journalctl -u nulavio-update`; the package manager's own history |
| Limitations | With APT the update trusts every source the system has: one the administrator added that also offers a `nulavio` package could provide it (R83). An update may pull in new dependencies from the system's repositories, as a manual update does; it never removes a package (`--no-remove`; dnf refuses without `--allowerasing`). At a change of release key the automatic updates on Fedora stop, failing in the journal, until a release signed with the current key carries the new one or the administrator accepts it in a manual `dnf upgrade` (R58). The pin is on where keys are imported from: keys already imported stay trusted, and a copy installed before this change runs its old script once more. The flag file survives the package's removal, so a later install updates again without asking unless it was deleted (the download pages' removal steps delete it). A program of the person's account can start `pkexec` too, but gets nothing without the administrator's password |
| Tests | `test_track_b`, `check_rpm.sh`, `check_deb.sh`, `test_update_key.sh` (with dnf: a changed repository key refused, a new key carried by a signed release accepted) |
| Residual | Low: the same trust as a manual `dnf upgrade nulavio` or `apt upgrade`, on a schedule; R83 |

### S25 — Another extension opens Nulavio's own pages

| Field | |
|---|---|
| Assets | A1, A2; the separation between profiles |
| Adversary | T-EXT: an extension installed in the profile, malicious or compromised |
| Preconditions | The extension knows the Shell's `moz-extension:` address (any extension with the `tabs` permission sees it on a new tab) |
| Boundary | TB3, TB11 |
| Impact | The engine lets an extension open another extension's page as a top-level tab with any query string. Nulavio's ask, blocked, unlock and look-alike pages are genuine pages under the window band's own name; if they took the link, the profile or the sites to name from their address, a click on them could open an address the extension chose in another profile, or make the look-alike warning recommend a site it chose |
| Preventive | The ask, blocked and unlock pages take no link, rule or site from their address, and the look-alike page only the address it checks. A link held back by routing is kept by `NulavioRouting` under a random id, and the ask, blocked and unlock pages get only that id and read the link, the rule, the profile and the reason back, each for its own kind of page; the unlock page also takes a profile to unlock, and a held link's own profile wins over it. The look-alike page gets the site's address (only its origin for a field in a frame) and, for a field in a frame, a flag with no address (`in=frame`) that makes "continue" go back in the tab's history, offered only on a warning the engine's actor opened in that tab, at the entry it took; `NulavioPasswords` finds the saved site it imitates again, and "continue" remembers the pair the module finds. Its title is the same whether or not the module finds a pair. Other extensions cannot read or script the pages, and websites cannot open them (no `web_accessible_resources`) |
| Detective | None |
| Limitations | R87: the unlock page names its profile in its address (a profile to unlock, with no link); a page for a held link can be opened again by an extension that saw its address, showing the same decision; held links do not outlive a restart, and only the newest 64 are kept; other Shell pages take a profile, an id or a prefilled name from their address and are not covered here |
| Tests | `test_held_links`, `test_shell.RoutingTest.test_pages_for_a_held_link_read_it_from_the_module`, `test_shell.PasswordsTest.test_the_warning_page_names_only_what_the_module_finds` |
| Residual | **Low** |

---

See the [threat matrix](threat-matrix.md) for the at-a-glance view and [residual risks](residual-risks.md) for what users must know.
