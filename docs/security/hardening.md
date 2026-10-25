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
| Privacy defaults | 23 annotated prefs: telemetry and studies off, ETP Strict, HTTPS-Only, GPC, no speculative connections, WebRTC default-route only. Each has a written rationale and trade-off | `browser/config/prefs/baseline.js` | `test_02_baseline_prefs_are_applied_and_exist_in_engine`; `nulavio prefs explain` |
| Reversibility | Seed prefs are written once; later user changes stick | `profile.prepare_for_launch()` | `test_seeds_apply_once_and_user_js_holds_only_enforced` |
| Guard | Pre-launch audit of effective prefs against [`guard-rules.json`](../../browser/config/guard-rules.json). **Critical findings block the launch** unless `--allow-weakened` is passed | `guard.py`, `cli.cmd_run()` | guard unit tests, `test_10_guard_refuses_test_profile` |
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
| DNS | Fedora disables DoH (`network.trr.mode=5`) to respect the system resolver. Nulavio keeps that; DoH will be an explicit onboarding choice |
| `privacy.resistFingerprinting` | Breaks time zones, window sizes and many sites. ETP Strict's fingerprinting protection is used instead; RFP may become an opt-in "hardened" mode |

## Host-level options evaluated (not adopted yet)

| Option | Benefit | Blockers found | Status |
|---|---|---|---|
| **Flatpak** | Filesystem confinement and portals | Native messaging (KeePassXC, Bitwarden biometrics) needs host binaries outside the sandbox. A portal-based solution must be validated first. Nested sandbox interplay with Gecko's user-namespace sandbox | Phase 5 spike |
| **bubblewrap wrapper** | Hide `~` except the profile and Downloads from the browser process | Same native messaging problem. Interaction with Gecko's own namespaces. File chooser needs portals | Phase 5 spike |
| **SELinux policy module** | Mandatory access control for the browser domain on Fedora | Needs policy authoring and maintenance; Fedora's Firefox runs unconfined | Phase 5 evaluation |
| **Secret Service / KWallet for engine logins** | OS keyring storage | Gecko on Linux does not use it for `logins.json`. The spec does not enforce per-application access: any same-user process can usually read an unlocked collection | Not a security gain against T-LOCAL; see [password providers](../architecture/password-providers.md) |

## User recommendations (shown in docs and onboarding)

1. Prefer an external manager that locks (KeePassXC, Proton Pass, Bitwarden) over engine-stored passwords. If you keep engine passwords, set a **Primary Password**.
2. Keep the system updated (`dnf upgrade`): in Track A, the engine's security fixes come from there.
3. Review extensions with "access your data for all websites" next to a password manager.
4. Use a separate Nulavio profile for work (flow G).
