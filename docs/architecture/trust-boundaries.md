# Trust boundaries

Zero Trust here means: every boundary states **who is on each side, how identity is established, what may cross, and what enforces it**. Nothing is trusted just because it runs locally.

| ID | Boundary | Untrusted side | Identity / authentication | What may cross | Enforced by | Verified |
|---|---|---|---|---|---|---|
| TB1 | Web content ↔ content process | Any website | Origin (scheme+host+port); TLS certificate | HTML/JS/CSS/media | Gecko site isolation (Fission), same-origin policy, CSP | `test_04`, `test_06` |
| TB2 | Content process ↔ parent | Possibly compromised renderer | Process identity of the IPC channel | IPC messages validated by the parent | seccomp-bpf, user namespace, IPC validation (upstream) | `test_04` (presence) |
| TB3 | Extension ↔ browser and pages | Any extension, incl. pinned ones | Mozilla signature (AMO); extension ID | WebExtension API calls within granted permissions | Engine permission model, private-browsing opt-in, blocklist | lock tests, `test_08` |
| TB4 | Browser ↔ native messaging host | Host binary outside the sandbox | Manifest name + `allowed_extensions` ID list; the app's own pairing (e.g. KeePassXC association keys) | JSON messages over stdio | Engine (manifest lookup), host app | `doctor` (manifest sanity) |
| TB5 | Browser/launcher ↔ filesystem | Other local accounts | Unix UID | Profile files | 0700/0600 modes, symlink refusal, umask 077 | `test_09`, path tests |
| TB6 | User session ↔ other same-UID processes | Any process of the same user | **None** (same UID) | Everything | Nothing in the browser. Host hygiene only | Documented: [residual risks](../security/residual-risks.md) |
| TB7 | Network ↔ browser | Network | TLS (WebPKI, CRLite/OCSP), HTTPS-Only | HTTP(S) | Engine TLS stack; HTTPS-Only | `test_06` |
| TB8 | Update and supply channels ↔ installation | Mirrors, CDNs, registries | RPM GPG signatures (distribution), AMO signatures, Mozilla release key (pinned), SHA-256 pins | Packages, XPIs, source tarballs | dnf, engine, `extensions.py`, `verify_firefox_release.py` | integrity unit tests |
| TB9 | Launcher ↔ engine | Environment variables and URL arguments from a desktop entry or link | n/a | A validated URL, fixed flags | `build_command()` allow-list, `launch_env()` stripping | engine unit tests |
| TB10 | Browser ↔ desktop services (portals, Secret Service, KWallet) | Session bus peers | D-Bus sender (not application-isolated for Secret Service) | Portal requests (file chooser, camera via PipeWire), secret lookups | Portal frontends; Secret Service collection lock state | `doctor` reports providers |
| TB11 | Nulavio Shell pages ↔ privileged modules (Track B) | Input typed into Shell pages (engine names, URLs, profile names) | Built-in add-on `shell@nulavio.net` packaged in `omni.ja` (not installable or replaceable from outside); experiment APIs exist only for it | Schema-typed calls to `nulavioSearch` / `nulavioProfiles`; error codes back | API schemas; second validation in `NulavioSearch.sys.mjs` / `NulavioProfiles.sys.mjs` (https-only templates, alias and name patterns, colour/icon allow-lists); the engine's Search Service and profile service | `test_search` 08, `test_profiles` 03, `test_shell.PrivilegedApiTest` |
| TB12 | Address bar ↔ search providers | Search providers | TLS; engine id | Search terms when the user searches. Typed text **while typing** only to engines listed in `nulavio.search.suggest.optin` | Seed prefs (suggestions, trending off) and patch 0004 at the single remote-suggestion fetch point | `test_search` 02, 03, 05 |
| TB13 | One profile's instance ↔ another's (same UID) | Another instance, any same-user process (see TB6) | Profile directory and its engine lock | Activation command lines only (`--profiles-activate`, `-new-tab <url>`), over the engine's local remote service or as an argument list; never cookies, sessions or storage | Engine remote service, profile lock (`launchInstance`, `deleteProfile`) | `test_profiles` 05 |

## Rules derived from the boundaries

1. Anything crossing TB3 or TB4 is treated as untrusted by Nulavio code. Nulavio never reads vault contents, intercepts provider messages, or scrapes extension storage.
2. A boundary without enforcement (TB6) is documented as residual risk, never presented as protected.
3. Configuration that could weaken TB1, TB2 or TB7 is detected by Guard and blocks the launch at critical severity.
4. New integrations must add a row here before they merge.
