# Residual risks and known limitations

Plain-language list of what Nulavio does **not** protect against today. It is linked from the start page and shown in plain language in the README.

## Out of scope by nature

1. **Malware already running as your user.** An infostealer that runs with your account can read your Nulavio profile (cookies, sessions, history), read engine-saved passwords if no Primary Password is set (or capture it when typed), add extensions, change settings and read memory of your processes on many systems. Profile permissions (0700/0600) protect against *other* accounts, not against your own. *Nulavio Guard* only detects cheap, accidental or legacy weakening; malware can bypass it.
2. **Malware with root access.** Everything is exposed.
3. **Physical access to an unlocked session.**

## Specific to the Track A preview

| # | Limitation | Consequence | Plan |
|---|---|---|---|
| R1 | Track A: the engine is Mozilla Firefox as packaged by your distribution | Security fixes arrive when the distribution ships them (`dnf upgrade`). The window title and About dialog say "Mozilla Firefox" | Track B builds are branded (dev build exists); releases need the update SLA, signing and a Safe Browsing key |
| R2 | On **Fedora's** Firefox package (`extensions.autoDisableScopes=0`), any signed XPI dropped into `<profile>/extensions/` is enabled at next start. Mozilla's builds and Track B ask the user first | On Fedora, a same-user process can silently add an AMO-signed extension | Planned: extension-set change alert. Track B keeps Mozilla's default (prompt) |
| R3 | The launcher runs from a git checkout writable by your user | A same-user process could modify the launcher | Packaging into root-owned `/usr` (Phase 6) |
| R4 | Preview chrome theme uses `userChrome.css` and engine CSS variables that change between releases | Cosmetic breakage after engine updates. No security impact (CSS cannot run code; security indicators are not touched) | `nulavio theme off`; built-in theme in Track B |
| R5 | No built-in Nulavio new tab yet (needs a signed or built-in add-on) | New tabs are blank; the start page opens on launch and Home | Track B built-in add-on |
| R6 | uBlock Origin is a third-party extension (GPL-3.0) | False positives and negatives exist; lists update over the network | Per-site toggle; flow C |
| R7 | ETP Strict can break some embeds or logins | Site breakage | Per-site toggle via the shield icon; Mozilla's compatibility exceptions stay on |
| R8 | Password-manager login/autofill not yet certified with real accounts | Only install, signature, background and popup are proven | Manual certification (Phase 4) |
| R9 | KeePassXC pairing proven only in a Fedora container, not yet on a real desktop session or Ubuntu | Desktop-specific issues (Flatpak KeePassXC, portals) may remain | Test on the maintainer's desktop and Ubuntu KDE |
| R10 | Native messaging hosts are shared with your regular Firefox (`~/.mozilla/native-messaging-hosts`) | The same host binaries serve both browsers (still limited to allowed extension IDs) | By design: the engine always reads this path, also in Track B builds (verified in source); `doctor` checks host binaries |
| R11 | Secret Service / KWallet do not isolate applications from each other | Any same-user process can query an unlocked collection | Not used to store web logins; documented |
| R12 | No signed releases, no update channel for the launcher | Users update with `git pull` | Phase 6 |
| R13 | Ubuntu's default Firefox is a Snap and cannot read hidden directories | The preview refuses it; you need the Mozilla APT package | Verify on Ubuntu KDE |
| R14 | Integration tests use Marionette with `--remote-allow-system-access` on throwaway profiles | None for users: the launcher refuses profiles containing automation prefs | Kept test-only |
| R15 | Track B uses its own Google Safe Browsing key, which gets page lists but **not download protection** (malicious-binary list and remote download check are partner-only) | Executable downloads are not checked against Google's download reputation. Page-level phishing/malware protection is active (`test_14`). Track A (distribution Firefox) keeps full download protection | Flow E warning **implemented** (Nulavio Shell): installers and scripts get a warning page with Show in folder / Delete and no Open; downloads are saved without execute permission and never auto-opened (`test_shell`). Still to do: request access to Google's download-protection API. Remote check stays off meanwhile so download details are not sent for nothing ([build](../architecture/build.md#google-safe-browsing-key)) |
| R16 | Track B's Safe Browsing key is under Google's **non-commercial** terms and a default quota | A commercial Nulavio would need another arrangement; a large user base needs a quota review | Recorded as release gate items |
| R17 | Track A (distribution Firefox) has no per-provider consent for suggestions: the engine has one switch for all engines | If the user turns suggestions on in Settings, typing with an alias (e.g. `@google`) also sends keystrokes to that engine | Remote suggestions and trending ship off; Track B adds per-provider consent (patch 0004, `test_search` 05) |
| R18 | Engine profile behaviours Nulavio keeps: creating the first extra profile renames the current one to "Original profile" and turns on the profile chooser at start-up | Surprise on first use | Rename in Nulavio settings; the chooser has its own "don't ask" option. Changing upstream behaviour would need a patch |
| R19 | Profiles started with `--profile <dir>` (Track A launcher, test harness) are not in profiles.ini, so the engine's profile switching is off for them | No selector in Track A | The selector explains this; Track A keeps launcher profiles (`nulavio --profile`) |
| R20 | The "nothing sent while typing" test measures the HTTP(S) requests the browser starts, not DNS | A typed word that looks like a host could still be resolved | Speculative connections and single-word DNS lookups are off (baseline, upstream default `dnsResolveSingleWordsAfterSearch=0`) |
| R21 | An explicit `-P <profile>` on the command line is consumed by the engine before Nulavio sees the link | A link given with `-P` still follows the routing rules | Turn routing off, or use a "Never switch" rule; explicit choices inside the browser carry the routed flag (ADR 0003) |
| R22 | A link that starts the browser (no instance running) is held until the group's rules are loaded | When it stays in that profile it opens in a new tab next to the start page | Kept on purpose: the alternative is reading the group database synchronously at start-up |
| R23 | Any same-user process can send command lines to a running instance (engine remote service over the session D-Bus) | It can open URLs, as any app can | Same-user processes are out of the browser's reach (TB6, S11); routing only moves plain web links and never moves sessions |
