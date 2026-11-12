# Hardening

What the Track A preview applies today, how each item is verified, and which host-level options were evaluated. Nothing here disables or relaxes an upstream protection.

## Applied now (verified)

| Area | Control | Where | Verified by |
|---|---|---|---|
| Engine integrity | Runs the distribution's root-owned binary (`/usr/lib64/firefox/firefox`). Snap builds are refused because they cannot read hidden dirs | `engine.py` | `doctor` (binary integrity), unit test `test_snap_engine_is_refused` |
| Downgrade protection | `MOZ_ALLOW_DOWNGRADE` (set by Fedora's wrapper) is removed, so the engine's "profile used by a newer version" check stays active | `engine.launch_env()` | `test_env_strips_sandbox_and_remote_knobs` |
| Sandbox | Variables that disable or relax sandboxes (`MOZ_*SANDBOX*`) and remote control (`MOZ_MARIONETTE*`, `MOZ_REMOTE*`) are stripped. Content, RDD, utility and socket processes are checked for seccomp-bpf on every thread plus their own user namespace | `engine.launch_env()` | `test_04_content_processes_are_sandboxed`; manual check in a real Wayland window (ADR E3) |
| Site isolation | Fission must be on | engine default | `test_11_record_environment` |
| No remote control | The launcher never forwards arbitrary flags. Marionette, remote debugging, `--headless`, `--jsconsole` and similar are rejected. Only http(s)/file URLs are accepted | `engine.build_command()` | `test_dangerous_urls_are_rejected`, `test_command_has_identity_and_no_remote_control` |
| Profile isolation | Profile under `$XDG_DATA_HOME/nulavio/profiles/<name>`, never `~/.mozilla` or `~/.config/mozilla`; launched with `--profile` so the engine's profile registry is untouched | `paths.py`, `profile.py` | `test_xdg_layout_never_touches_mozilla_dirs`, integration teardown (registry hashes) |
| Permissions | Directories 0700, files 0600, created atomically, symlinks refused, other-user ownership refused; launcher `umask 077` inherited by the engine (downloads 0600) | `paths.py`, `cli.main()` | `test_09_profile_files_are_private`, `test_07_download_lands_privately`, path unit tests |
| Privacy defaults | 43 annotated prefs: telemetry and studies off, ETP Strict, HTTPS-Only, GPC, no speculative connections, no region lookup at Mozilla's location service, no question to Google's update service about a DRM module that is off, WebRTC default-route only, no remote search suggestions or trending while typing, separate private search default. Each has a written rationale and trade-off | `browser/config/prefs/baseline.js` | `test_02_baseline_prefs_are_applied_and_exist_in_engine`; `nulavio prefs explain`; `test_search` 01–03; `test_mozilla_features` 03b, 03c; Track B: `test_privacy` checks that every pref the build's `distribution.ini` sets is in effect in an engine profile, that tracking protection is Strict (set once by the Shell as a user value, since the engine recomputes a default category), and that a classified tracker is really blocked |
| Fingerprinting (Track B) | The User-Agent is Firefox's own, not the build's name (patch 0009). Canvas, offscreen-canvas and WebGL reads differ per site and per day; pages are not given the graphics card's model, the size of the toolbars and the sidebar, the window's position, the desktop theme's colours or motion-sensor readings; the processor count is reported in tiers. Fonts a person installed are hidden from pages on Fedora and Ubuntu (patch 0010 makes the engine's lists apply on Fedora). A site exempted with the shield is exempt from these. Time zone, language, screen and window size are not changed | `firefox-branding.js` and `baseline.js` (`privacy.fingerprintingProtection.overrides`), patches 0009 and 0010 | `test_fingerprinting` (seven tests on the real engine, plain values read in the same session); `test_prefs_and_guard`; [measurements and limits](../research/fingerprinting.md) |
| Typed text (Track B) | Remote suggestions need per-provider consent at the single fetch point, so an alias cannot send keystrokes to an engine the user did not choose | patch 0004, `NulavioSearch.sys.mjs` | `test_search` 05 |
| Reversibility | Seed prefs are written once; later user changes stick | `profile.prepare_for_launch()` | `test_seeds_apply_once_and_user_js_holds_only_enforced` |
| Guard | Pre-launch audit of effective prefs against [`guard-rules.json`](../../browser/config/guard-rules.json). **Critical findings block the launch** unless `--allow-weakened` is passed | `guard.py`, `cli.cmd_run()` | guard unit tests, `test_10_guard_refuses_test_profile` |
| Guard at run time (Track B) | Each start compares the profile with the record of the last run: extensions (added, replaced, turned on, removed), protective and traffic-routing settings, certificate authorities in the profile's own store, security modules, native-messaging/PKCS#11/managed-storage manifests and the programs they start, managed policies, `user.js`, the default search engines. Changes are listed in a bar and a review page; the user undoes or keeps each one. Changes made in the browser during a session are followed, never reported; an extension another program places in the profile is never taken into the record unseen | `NulavioGuard.sys.mjs`, `guard/review.html` | `test_guard` (real engine: proxy in prefs.js, `user.js`, a CA added with `certutil`, a module with `modutil`, a native-messaging manifest, a sideloaded extension; undo and keep; nothing reported after in-browser changes), `test_shell.GuardModuleTest` |
| Extensions | Only pinned SHA-256 + size + `addons.mozilla.org` sources; Mozilla signature enforced by the engine; tampered cache discarded | `extensions.py` | extension unit tests |
| Logs | Local JSONL, 0600, URLs reduced to scheme, secret-looking values masked, home path shown as `~`; engine stdout/stderr discarded by default | `log.py` | `test_urls_secrets_and_home_are_redacted` |
| Start page | Static local HTML, CSP `default-src 'none'`, no scripts, no remote resources, values HTML-escaped | `browser/startpage/` | `test_start_page_escapes_values_and_has_no_scripts`, `test_01` |
| Crash data | Never auto-submitted (`browser.crashReports.unsubmittedCheck.autoSubmit2=false`) | baseline | `test_02` |

## Deliberately **not** changed

| Upstream protection | Why it stays |
|---|---|
| Safe Browsing (phishing, malware, downloads) | Removing it weakens anti-phishing. A privacy-preserving replacement must be proposed and evaluated first (ADR candidate) |
| Remote Settings (OneCRL, CRLite, add-on blocklist) | Certificate revocation and malicious-extension blocking depend on it |
| Extension auto-updates | Security fixes for extensions |
| Engine updates | Delivered by the distribution package (Track A) or our SLA (Track B) |
| DNS | Track A: Fedora disables DoH (`network.trr.mode=5`) to respect the system resolver, and Nulavio keeps that. Track B (S15): the new tab asks once how to look up sites: the computer's resolver (mode 5, "off by choice", which also keeps Mozilla's regional roll-out off), encrypted DNS with fallback (mode 2) or encrypted only (mode 3), through Cloudflare (the engine's default, [Mozilla's resolver program](https://wiki.mozilla.org/Security/DOH-resolver-policy)), [Quad9](https://quad9.net/doh-quad9-dns-servers/), [Mullvad](https://mullvad.net/en/help/dns-over-https-and-dns-over-tls) or an https:// address of the user's. Until the user answers, the engine's default applies. Nulavio runs no resolver; the UI says the chosen resolver sees the lookups. `test_dns` proves lookups reach the chosen resolver and that "encrypted only" fails closed |
| `privacy.resistFingerprinting` | Breaks time zones, window sizes and many sites. The engine's fingerprinting protection for the Strict category is used instead, with the additions that do not break sites ([measured](../research/fingerprinting.md)); RFP may become an opt-in "hardened" mode |

## Host-level options evaluated

| Option | Benefit | Blockers found | Status |
|---|---|---|---|
| **Flatpak** | Filesystem confinement and portals | Native messaging: the host-side proxy (`xdg-native-messaging-proxy`) now ships in Fedora 44 and Ubuntu 26.04+, so it is solvable; a second packaging and update path for no gain over bubblewrap | **Not now** ([spikes](phase5-spikes.md#flatpak-and-native-messaging)) |
| **bubblewrap wrapper** | Hide `~` except the profile and Downloads from the browser process | Measured: the engine's sandbox is unchanged inside it; uploads only from Downloads; the session bus is not filtered | **Adopted as opt-in** `nulavio run --confined` ([spikes](phase5-spikes.md#bubblewrap)) |
| **SELinux policy module** | Mandatory access control for the browser domain on Fedora | Needs root on every machine and per-release maintenance; the browser runs `unconfined_t` like Fedora's Firefox; bubblewrap covers the filesystem part without root | **Not adopted** ([spikes](phase5-spikes.md#selinux)) |
| **Secret Service / KWallet for engine logins** | OS keyring storage | Gecko on Linux does not use it for `logins.json`. The spec does not enforce per-application access: any same-user process can usually read an unlocked collection | Not a security gain against T-LOCAL; see [password providers](../architecture/password-providers.md) |

## User recommendations (shown in docs and onboarding)

1. Prefer an external manager that locks (KeePassXC, Proton Pass, Bitwarden) over engine-stored passwords. If you keep engine passwords, set a **Primary Password**.
2. Keep the system updated (`dnf upgrade`): in Track A, the engine's security fixes come from there.
3. Review extensions with "access your data for all websites" next to a password manager.
4. Use a separate Nulavio profile for work (flow G).

## Guard at run time: what it catches and how it can be bypassed

Phase 5 asks for a bypass analysis of each control. Guard is **detection**: it tells the user what changed outside the browser since the last run, so persistence left by tools and generic malware does not go unnoticed. It does not stop a program running as the user from reading cookies or passwords ([threat model S11](threat-model.md#s11--local-malicious-process-as-the-same-user-infostealer)).

| Check | Typical abuse it surfaces | Bypass | Residual |
|---|---|---|---|
| Extensions (added, replaced, turned on, removed) | A malicious extension dropped into the profile, or a disabled one turned on by editing `extensions.json` | Edit Guard's record (`nulavio-guard.json`) too; install through a policy (reported as a policy change instead); act while the browser runs and wait for the user to install something | Nulavio-aware malware can hide; the engine's own sideload prompt still applies to dropped XPIs |
| Settings that protect or route traffic (proxy, DNS over HTTPS, TLS, sandbox, signatures, Safe Browsing, HTTPS-Only, tracking protection, home page, remote debugging) | A proxy for interception, Safe Browsing turned off, remote debugging enabled to dump cookies | Edit the record; change a setting not on the list | The list is short on purpose; `guard-rules.json` prefs are all on it (unit test) |
| Certificate authorities in the profile's store | A root added for TLS interception (`certutil -A`) | Edit the record; add the root to the system store instead (needs root) or through a new security module (reported as such) | System trust stores are outside the profile |
| Security modules (PKCS#11) | A module loaded into the browser process | Edit the record | — |
| Native-messaging, PKCS#11 and managed-storage manifests, and the program each starts (digest) | A fake password-manager host, a swapped host binary | Edit the record; replace a host binary larger than 64 MB (checked by size and time only) | Hosts in system directories need root to change |
| Managed policies | `ExtensionSettings` force-installing an extension, settings locked by policy | Edit the record; change policies in the same update as Nulavio itself (a new build's policies are not reported) | The policies file of a user-owned install is user-writable; packaged installs are root-owned (S18) |
| `user.js` | Preferences forced at every start | Edit the record | Undoing a setting that `user.js` forces lasts until the next start; the page says to edit the file |
| Default search engines | Search hijacking | Edit the record | — |

**Limits shared by every check.** The record lives in the profile (encrypted at rest for protected profiles, and unreadable while locked), so any program running as the user while the profile is unlocked can rewrite it; Guard reports at the next start, not the moment a file changes; certificate authorities and modules added through the browser's own certificate manager are reported at the next start as well (one "Keep"); Track A has no Shell, so this check exists only in the Nulavio build; temporary profiles and profiles an agent is driving are not checked. Changes to the installed browser itself (`omni.ja`, `libxul.so`) are out of reach of a check that runs inside it: packaged, root-owned installs are the answer (S18). See [R38](residual-risks.md).
