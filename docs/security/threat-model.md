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
| Preventive | Upstream sandbox; SELinux enforcing on Fedora (host); fast patching. **Evaluated:** bubblewrap or Flatpak confinement of the whole browser (see [hardening](hardening.md)): not adopted until native messaging, portals and KDE integration are proven |
| Detective | None reliable inside the browser |
| Limitations | Out-of-browser containment is the only further layer |
| Tests | Sandbox presence only (we cannot test escapes) |
| Residual | **Low likelihood, critical impact** |

### S6 — Phishing and lookalike domains

| Field | |
|---|---|
| Assets | A2, A3, A4 |
| Adversary | T-WEB |
| Preconditions | User lands on a lookalike or deceptive login page |
| Boundary | User perception; TB3 for autofill |
| Impact | Credential theft; MFA bypass via real-time proxy |
| Preventive | **Now:** Safe Browsing (phishing/malware) kept ON (lists downloaded from Google and matched locally; only hash prefixes leave the device; verified end to end by `test_14`); IDN punycode display rules; password managers fill only on matching origins (vendor behaviour; to certify). **Planned:** "suspicious login" interstitial (flow D in [ux-flows](../brand/ux-flows.md)): confusables and edit distance against the user's own saved-site list, computed locally; passkeys preferred |
| Detective | Safe Browsing warnings |
| Limitations | Brand-new phishing domains; AiTM proxies on exact-match lookalikes |
| Tests | Guard rule for Safe Browsing prefs; integration `test_12` (key present) and `test_14` (Google's test phishing page is blocked); planned unit tests for the lookalike heuristic |
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
| Detective | **Now:** Guard detects weakened security prefs before launch; doctor lists unpinned extensions. **Planned:** extension-set change alert; profile integrity manifest (hashes of `user.js`, `extensions/`) checked at launch |
| Limitations | **Fundamental.** Detection can be bypassed by malware that also edits Nulavio's state. Sandboxing the browser does not stop malware outside the sandbox from reading the browser's files |
| Tests | Guard unit tests; `test_10_guard_refuses_test_profile` |
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
| Boundary | TB8 |
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
| Preventive | **Planned:** onboarding warning when extensions with all-site access are installed next to a password manager; "sensitive sites" container where only the chosen provider is allowed **(B, policy-based)** |
| Detective | doctor inventory |
| Limitations | Engine has no per-field isolation from extensions with host access |
| Tests | Planned |
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
| Limitations | Track A has one global switch (R17); DNS is not measured by the test (R20) |
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
| Limitations | Same-UID processes can read every profile (TB6, S11); routing rules (next slice) must never move a session |
| Tests | `test_profiles` 05, 06, 08; `test_routing` |
| Residual | **Low** |

---

See the [threat matrix](threat-matrix.md) for the at-a-glance view and [residual risks](residual-risks.md) for what users must know.
