# Compatibility matrix

Last run: 2026-10-24 on Fedora 44 KDE Plasma 6.7.5 (Wayland), kernel 7.2, SELinux enforcing.

Legend: ✅ verified by automated test or recorded evidence · 🟡 partially verified / manual pending · ❌ fails · ⛔ blocked (cause given) · ⬜ not tested.

## Extensions × engines

| Extension (version tested) | Gecko 158.0.1 (Nulavio Track A) | Qt WebEngine 6.11.2 (Chromium 140) | Evidence |
|---|---|---|---|
| **uBlock Origin** 1.75.0 (AMO, GPL-3.0) | ✅ blocks EasyList first-party match, reversible, control path verified | ⬜ (MV2 not supported by Qt). uBO Lite 2026.1021.1354 loads; enabling crashes ❌ | `test_08`; [qt evidence](evidence/qt-webengine-6.11.2-extensions.json) |
| **Proton Pass** 1.41.1 AMO (Firefox: MV3) / 1.42.0 CWS | ✅ install, signed, background, popup (sign-in screen). 🟡 login/autofill manual | ❌ loads; `setExtensionEnabled` segfaults | [gecko evidence](evidence/gecko-158-password-extensions.json) |
| **KeePassXC-Browser** 1.10.4.1 | ✅ install, signed, background, popup. ✅ **association + autofill end to end** with KeePassXC 2.8.0 (Fedora 44 container) | ❌ loads; enabling crashes; native messaging undocumented | same |
| **Bitwarden** 2026.10.0 | ✅ install, signed, background, popup (onboarding). 🟡 login/biometrics manual | ❌ loads; enabling crashes | same |

## Platform behaviour (Gecko, Track A)

| Behaviour | Result | Evidence |
|---|---|---|
| Content sandbox (seccomp-bpf on every thread + own user namespace) | ✅ content, RDD, utility, socket processes; forkserver unsandboxed by design | `test_04`, ADR E3 |
| Effective content sandbox level | ✅ ≥ 4 (observed 6) | `test_04` |
| Fission (site isolation) | ✅ on | `test_11` |
| Wayland app_id / KDE desktop-file association | ✅ `nulavio-preview` (KWin `getWindowInfo`) | ADR E3 |
| Remoting (second launch opens in the running instance) | ✅ | manual check 2026-10-24 (launcher log `launch.forward`) |
| User's Firefox profile registry untouched | ✅ byte-identical `profiles.ini`/`installs.ini` | integration teardown |
| Localised UI (pt-BR) via the distribution langpack | ✅ extension popups rendered in pt-BR | password-extension evidence |
| Chrome theme (userChrome.css, Firefox 158 variables) | ✅ visually verified in a real window | [screenshot](../brand/assets/review/preview-window-kde-wayland.png) |
| HTTPS-Only + revocable exception | ✅ | `test_06` |
| Downloads 0600, no auto-open | ✅ | `test_07` |

## Environments

| Environment | Status | Notes |
|---|---|---|
| Fedora 44 KDE Plasma 6.7.5, Wayland, x86_64 | ✅ reference | Firefox 158.0.1 RPM |
| Ubuntu 26.10 container, Firefox 158.0.1 from **Mozilla's APT repository** (key fingerprint verified) | ✅ **15/15** integration tests (run twice), incl. sandbox, uBO with approval flow, all three password extensions | [`ci/containers/ubuntu-itest.Containerfile`](../../ci/containers/ubuntu-itest.Containerfile). Host kernel is Fedora's: Ubuntu's AppArmor user-namespace restriction still needs a real Ubuntu host |
| Ubuntu KDE (Kubuntu) host | ⬜ | Default Firefox is a **Snap** and cannot read `~/.local/share` (hidden dirs); the launcher refuses it. Use Mozilla's APT repository |
| GNOME | ⬜ | Symbolic icon uses `currentColor` + KDE class; GNOME recolouring to verify |
| **Nulavio 158.0.1 Track B dev build** on the Fedora 44 host | ✅ 17/17 with network tests (2026-10-25) | Own Safe Browsing key: page lists active, download reputation unavailable (R15) |
| Fedora 44 container (rootless podman, default seccomp, unprivileged user) | ✅ 14/14 integration tests incl. sandbox | Rehearsal of the CI integration job; KeePassXC end-to-end spike runs here |
| Flatpak Firefox / Flatpak Nulavio | ⬜ | Native messaging needs host access; see [hardening](../security/hardening.md) |

## Test-integrity notes

- Marionette's "recommended preferences" disable Safe Browsing, tracking protection, the password manager and extension updates. All Nulavio integration tests set `remote.prefs.recommended=false`, so they exercise the real configuration.
- Processes spawned by the engine's fork server rewrite `argv` into a single string. Sandbox checks match on the joined command line.
- Sideloaded profile XPIs: **Fedora's** package enables them without a prompt (`extensions.autoDisableScopes=0`, a Fedora default). **Mozilla's** builds (Ubuntu/Mozilla APT, Nulavio Track B) keep them disabled until the user approves (default 15). `test_08` asserts the engine's behaviour and, where approval is required, approves as the user would.
- Mozilla's official build returned the *current* handle from `WebDriver:NewWindow` and hung on `SwitchToWindow` with `focus: true` in headless mode. The Marionette client identifies new tabs by diffing handles and switches without focus.
