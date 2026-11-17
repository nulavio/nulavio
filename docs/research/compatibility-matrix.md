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

## Protected music and video (DRM, #222)

DRM is off in a new profile (ADR 0002); the person turns it on from the engine's prompt or with the DRM switch in Settings. Automated, on the 160.0-0.4 package (`tests/integration/test_drm.py`, 2026-11-14):

| Check | Result |
|---|---|
| DRM off: Widevine for a page | ✅ refused (`NotSupportedError`), and not installed |
| DRM off: ClearKey for a page | the engine's own open key system: granted, with nothing downloaded |
| DRM on: a ClearKey stream through EME and MSE, VP9 video and Opus audio | ✅ plays (video decoded, 23 frames in 1.5 s); a wrong key plays nothing |
| A persistent licence, then "Clear cookies and site data" for the site | ✅ its files under `gmp/…/gmp-clearkey/storage/` are written, then gone |

By hand, on each engine release, with throwaway or family accounts and never in CI. Not run yet: it needs the maintainer's accounts.

| Service | Plays | Video reached | Audio | Release, package | Notes |
|---|---|---|---|---|---|
| Apple Music | ⬜ | | | | |
| Disney+ | ⬜ | | | | |
| Globoplay | ⬜ | | | | |
| Max | ⬜ | | | | |
| Netflix | ⬜ | | | | |
| Prime Video | ⬜ | | | | |
| Spotify | ⬜ | | | | |
| YouTube (paid films) | ⬜ | | | | |
| The same in the Flatpak (`net.nulavio.Nulavio`) | ⬜ | | | | the plugin folder must be writable and the plugin process start inside the sandbox |

Widevine on Linux is the software level (L3); services usually limit it to 720p or lower.

The Widevine network test (`test_drm` test 04 with `NULAVIO_NETWORK_TESTS=1`; never in CI, it downloads Widevine from Mozilla's list and plays from Google's test servers), run by hand on 2026-11-17 on a build of `main` at 68ec0575 (Firefox 160.0; not a released package), on the Fedora 44 host, three times:

| Check | Result |
|---|---|
| DRM on: Widevine from the engine's own list | ✅ 4.10.3112.0 installed |
| The Shaka Player demo's Widevine stream ("Angel One", H.264), **without** a licence | plays its clear start and stops at 7.8 s, waiting for a key: the rest is encrypted |
| The same stream with a licence from Google's test licence server | ✅ plays past the clear start (12 s, 304 frames) |

It says that Widevine installs, gets a licence and decrypts in the Nulavio build. It says nothing about a service: each one adds its own checks (the table above), and the Flatpak is not covered by it.

## Video calls (#221)

On every change, automated: a call on this computer with the engine's fake camera and microphone, and the question before a screen is shared (`tests/integration/test_webrtc.py`). By hand, on each engine release, per service; alphabetical, none preferred. Only what could be done with no account is run so far: Jitsi Meet.

| Service | Join as a guest | Camera and microphone | Audio and video, both ways | Chat | Screen sharing | End-to-end encryption | Release, package | Notes |
|---|---|---|---|---|---|---|---|---|
| Google Meet | ⬜ | | | | | | | not run: no account was used |
| Jitsi Meet | ✅ | 🟡 the engine's fake devices | ✅ | ✅ | ⬜ | not offered, as in Firefox 160.0 | Firefox 160.0, a build of `main` at 68ec0575 (not a released package), 2026-11-17 | below |
| Microsoft Teams | ⬜ | | | | | | | not run: no account was used |
| Proton Meet | ⬜ | | | | | | | not run: no account was used |
| Webex | ⬜ | | | | | | | not run: no account was used |
| Whereby | ⬜ | | | | | | | not run: no account was used |
| Zoom | ⬜ | | | | | | | not run: no account was used |

The Jitsi Meet row, 2026-11-17 ([evidence](evidence/calls-jitsi-2026-11-17.json)): two new profiles on one computer, driven by a script, headless, with a new profile's defaults (tracking protection Strict, only the default route's address offered to peers).

- **On `meet.ffmuc.net`**, a public instance that asks for no account: each guest gets the page before the meeting with the camera's picture and the microphone working, types a name, joins; each sees two people; audio and video arrive on both sides (through the instance's bridge, over UDP, reached directly); a chat message arrives.
- **End-to-end encryption is not offered**: the page's own library says it is not supported, in Nulavio and in Fedora's Firefox 160.0 alike, with the same script. So it is not something Nulavio's settings take away; whether Jitsi offers it to any Gecko browser on that instance was not looked into.
- **On `meet.jit.si`** the page before the meeting works the same, and then the guest waits: a room there starts only when someone signs in ("no moderator has arrived yet"). That is the service's rule, not a failure of the browser; the whole call was not run there.
- **Not run:** screen sharing, background blur, noise suppression, reactions, a real camera and microphone, a call through a VPN or proxy route (#217), the temporary profile, a call that needs a relay, more than two people.

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
