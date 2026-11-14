# ADR 0001 — Engine selection: Gecko (Firefox) first, delivered in two tracks

- **Status:** Accepted for Phases 0–3. Re-evaluated at the Phase 4 gate (password-provider certification) and whenever a reversal criterion fires.
- **Date:** 2026-10-24
- **Deciders:** Nulavio maintainers (tech lead / security architect role)
- **Evidence collected on:** Fedora 44 KDE Plasma 6.7.5 (Wayland), Firefox 158.0.1 (Fedora RPM), Qt / Qt WebEngine 6.11.2 (Fedora RPM), PySide6 6.11.2.

## Context

Nulavio needs a mature, sandboxed web engine with first-class WebExtensions so that:

1. the **official** Proton Pass (P0), KeePassXC-Browser (P0) and Bitwarden (P1) extensions work unmodified, including native messaging for KeePassXC;
2. a mature, auditable content blocker (uBlock Origin) works with its full feature set;
3. upstream security fixes reach users fast with a small team;
4. the UI can be fully rebranded without using third-party trademarks.

Writing an engine is out of scope (non-negotiable principle). The options were:

- **A. Gecko** — Firefox source build with Nulavio branding and a minimal patch stack, or a configuration/distribution layer over an unmodified Firefox.
- **B. Qt 6.10+ / Qt WebEngine + Qt Quick/QML + C++.** Qt 6.10 added `QWebEngineExtensionManager`, which supports only Manifest V3.
- **C. Chromium fork**, only if there is a concrete justification.

## Decision

**Gecko.** It is delivered in two tracks that share one configuration source (`browser/config/`):

| | Track A — *Nulavio Preview* (now) | Track B — *Nulavio* source build (Phase 2+) |
|---|---|---|
| Engine | Unmodified distribution Firefox (Fedora RPM), updated by the distribution | Official Firefox release tarball, signature-verified, built with `--with-branding=browser/branding/nulavio` |
| Nulavio layer | Launcher + isolated profile + seeded prefs + preview chrome theme + local start page + pinned uBO | Same config compiled in as defaults (`distribution/policies.json`, default prefs), built-in add-ons (new tab, onboarding, privacy panel), own name/icons/app ID |
| Patches to Gecko | **None** | Minimal patch stack, only for what prefs, policies, branding or built-in add-ons cannot do |
| Distribution | Not distributed as a browser; runs locally on the user's own Firefox package | RPM first, DEB later; Flatpak only after native messaging is solved |
| Trademark | Mozilla's Firefox is used as installed; Nulavio pages state "not affiliated with Mozilla" | No Mozilla marks anywhere (required for modified builds) |

Track A exists because the Phase 0 brief asks for a reproducible customisation/distribution POC before committing CPU-hours to a fork. It also lets us validate UX, privacy defaults, provider integrations and the test harness on the engine version users already run.

## Evidence

Every item below was produced in this session and can be reproduced with the commands listed.

| ID | What we checked | Result | Reproduce / artefact |
|---|---|---|---|
| E1 | Host resources | 8C/16T Ryzen 7 5825U, 30 GiB RAM, 325 GB free, SELinux enforcing, unprivileged user namespaces available. **No C/C++ compiler, Rust or `make` installed.** | `bin/nulavio doctor` |
| E2 | Gecko vertical slice (Track A), headless | **11/11 integration tests pass.** Seeded prefs take effect, and every pref exists in the engine. ETP Strict is effective. Content, RDD, utility and socket processes run with seccomp-bpf on every thread and their own user namespace. Navigation, tabs and back/forward work. A download lands in mode 0600. HTTPS-Only upgrades plain HTTP, and its per-site exception is revocable. uBO blocks a first-party EasyList match (`/adbanners/*$image`), the block is reversible, and a control request proves the network path. Profile is 0700 with no group/other bits on any file. The user's Firefox `profiles.ini`/`installs.ini` are byte-identical before and after. | `python3 -I tests/run.py integration` → [`tests/integration/test_engine_slice.py`](../../tests/integration/test_engine_slice.py) |
| E3 | Same slice in a real KDE Plasma Wayland window | KWin reports `resourceClass=nulavio-preview`, `desktopFile=nulavio-preview`. Sandbox checks match E2 (forkserver unsandboxed by design). | [`docs/brand/assets/review/preview-window-kde-wayland.png`](../brand/assets/review/preview-window-kde-wayland.png) |
| E4 | Official password managers on Gecko 158 | Proton Pass 1.41.1 (**MV3** on Firefox), KeePassXC-Browser 1.10.4.1 and Bitwarden 2026.10.0 install as normal extensions with Mozilla signatures (`signedState=2`). Backgrounds run and popups render: Proton sign-in, Bitwarden onboarding, and KeePassXC "cannot connect to KeePassXC" because no host is installed yet. | `NULAVIO_NETWORK_TESTS=1 python3 -I tests/run.py integration` → [`evidence/gecko-158-password-extensions.json`](../research/evidence/gecko-158-password-extensions.json) |
| E5 | Qt WebEngine 6.11.2 extension spike (Chromium 140 base) | `loadExtension()` loads the Chrome builds of Proton Pass 1.42.0, KeePassXC-Browser, Bitwarden and uBO Lite with no error and exposes popup URLs. **`setExtensionEnabled()` segfaults in `libQt6WebEngineCore.so.6` for all four** (offscreen, wayland and xcb, called directly or deferred). A QML attempt also crashed. Not isolated (PySide6 binding vs. Qt core). Extensions load disabled by design, so none could run. | [`scripts/research/qt_extension_spike.py`](../../scripts/research/qt_extension_spike.py) → [`evidence/qt-webengine-6.11.2-extensions.json`](../research/evidence/qt-webengine-6.11.2-extensions.json) |
| E6 | Qt documentation | "Only ManifestV3 extensions are supported." "Extensions can't be loaded into off-the-record profiles." Native messaging is not mentioned anywhere in the extension API docs. | [QWebEngineExtensionManager](https://doc.qt.io/qt-6.10/qwebengineextensionmanager.html), [QWebEngineExtensionInfo](https://doc.qt.io/qt-6/qwebengineextensioninfo.html) |
| E7 | Where Firefox reads policies (code from the installed 158 `omni.ja`) | `/etc/firefox/policies/policies.json` or `<install>/distribution/policies.json`. The per-user policy directory is honoured only `Cu.isInAutomation`. Fedora's `browser.policies.perUserDir` pref has no effect. Track A therefore uses profile prefs; Track B ships `distribution/policies.json`. | `EnterprisePoliciesParent.sys.mjs` → `_getLocalConfigurationFile()` |
| E8 | Extension sideloading default (**corrected 2026-10-25**) | **Fedora's** Firefox package sets `extensions.autoDisableScopes=0`: a signed XPI dropped into `<profile>/extensions/` is enabled at next start without a prompt. **Mozilla's own build** (Ubuntu via Mozilla APT, and Nulavio Track B) keeps the default **15**: the extension stays disabled until the user approves it from the menu. The first version of this ADR wrongly called 0 the Firefox default. Nulavio never lowers the value; Guard warns if a user pref does | Fedora: `browser/defaults/preferences/firefox.js` in `browser/omni.ja`; Mozilla build: runtime default branch, `test_08` on both |
| E9 | Fedora `/usr/bin/firefox` wrapper | It writes langpack links into `~/.config/mozilla/extensions/`, forces `MOZ_APP_REMOTINGNAME=org.mozilla.firefox` and sets `MOZ_ALLOW_DOWNGRADE=1`. The launcher runs `/usr/lib64/firefox/firefox` directly, strips those variables and installs the distribution's signed langpack into the Nulavio profile instead. | `launcher/nulavio_launcher/engine.py` |
| E10 | Mozilla release signing, a prerequisite for Track B supply chain | `SHA256SUMS` for 158.0.1 has a valid signature by subkey `827E…7AA3` of primary `14F2 6682 D091 6CDD 81E3 7B6D 61B7 B526 D98F 0353`, pinned in the script. | `python3 -I scripts/upstream/verify_firefox_release.py 158.0.1` |
| E11 | Mozilla trademark distribution policy | "you may not distribute a modified form of Firefox and continue to call it Firefox". Adding extensions or changing defaults counts as modification. | [Distribution policy](https://www.mozilla.org/en-US/foundation/trademarks/distribution-policy/) |
| E12 | Proton's own statement | "Proton Pass for Firefox also works with many Firefox-based browsers, such as LibreWolf." | [Proton Pass browser extension](https://proton.me/support/pass-browser-extension) |
| E14 | **KeePassXC end to end** (Fedora 44 container: firefox-158.0.1, keepassxc-2.8.0) | Profile created by `nulavio setup --provider keepassxc --install-provider-extension`. Popup before: "has not been configured". Association dialog answered (simulating the user). Popup after: "connected … identifier: nulavio-spike". **Username and password autofilled** on a fixture login page from a throwaway database | [`scripts/research/keepassxc_native_messaging_spike.py`](../../scripts/research/keepassxc_native_messaging_spike.py) → [`evidence/keepassxc-2.8.0-native-messaging.json`](../research/evidence/keepassxc-2.8.0-native-messaging.json) |
| E15 | CI integration job rehearsed locally (rootless podman, Fedora 44, **default seccomp profile**, unprivileged user) | 14/14 integration tests pass, including the sandbox test (nested user namespaces work in rootless podman) | [`ci/containers/fedora-itest.Containerfile`](../../ci/containers/fedora-itest.Containerfile) |
| E16 | Track B facts read from the verified 158.0.1 source | (a) User native-messaging manifests are always read from `~/.mozilla/native-messaging-hosts`, even for rebranded builds. (b) **Without a Google Safe Browsing API key, Safe Browsing providers are skipped** (phishing/malware lists inactive). (c) Extension signing is implied only for release/beta milestones. (d) The `unofficial` branding relaxes the console Self-XSS gate | [build.md](../architecture/build.md#facts-verified-in-the-15801-source) |
| E17 | **Track B first build** (2026-10-24/25): verified 158.0.1 source + Nulavio branding + 1 patch, rootless podman | Full build ≈ **52 min**, **23 GB** disk in total. `Vendor/Name=Nulavio`, add-on ID unchanged. About dialog fully Nulavio-branded, with the Mozilla-only links hidden via branding CSS. Defaults: sideload prompt kept (15), signing required, Self-XSS gate on, policies + `distribution.ini` active. Integration **14/15**; the only failure is the missing Safe Browsing key (E16b) | [build.md](../architecture/build.md#measured-on-the-reference-machine-ryzen-7-5825u-8c16t-30-gib-nvmeluks), [`evidence/trackb-158.0.1-branding.json`](../research/evidence/trackb-158.0.1-branding.json), [about dialog](../brand/assets/review/trackb-about-dialog.png) |
| E18 | **Ubuntu userspace** (26.10 container, Firefox 158.0.1 from Mozilla's APT repo with fingerprint-checked key) | Integration **15/15**, twice. Revealed: Mozilla builds keep sideloaded extensions disabled until approved (E8 corrected), and Marionette tab-handle quirks (test client fixed) | [`ci/containers/ubuntu-itest.Containerfile`](../../ci/containers/ubuntu-itest.Containerfile) |
| E19 | **Track B with a Google Safe Browsing key** (2026-10-25): dedicated Cloud project `nulavio`, key restricted to the Safe Browsing API, mounted read-only into the build | Integration **17/17** with network tests. Found and fixed on the way: (a) one batch per provider and `mwb-4b`/`csdda-32b` are not served to non-partner keys (HTTP 404), so every list update failed until the branding prefs requested only available lists; (b) the remote download check needs a partner-only API (HTTP 403) and is off; (c) non-`MOZILLA_OFFICIAL` builds enable `devtools.chrome.enabled` and `devtools.debugger.remote-enabled` by default, now restored to `false`; (d) new content processes run ~30 ms before seccomp applies (normal Gecko startup; `test_04` re-checks instead of sampling once) | [evidence](../research/evidence/trackb-158.0.1-safebrowsing.json), [build](../architecture/build.md#google-safe-browsing-key) |
| E20 | **Nulavio Shell as a built-in add-on** (2026-10-25) | Firefox 158 registers any `builtin-addons/<name>/manifest.json` in `browser.jar` at build time; building it from the branding directory needs **no patch**. The built-in add-on is active, system, hidden and not removable from the profile. New tab override works even with `browser.newtabpage.enabled=false`. Integration: Nulavio build 22/22; Fedora Firefox runs the same Shell tests with a temporary install | `tests/integration/test_shell.py`, [build](../architecture/build.md#nulavio-shell-built-in-add-on) |
| E21 | **Track B in Portuguese** (2026-10-25) | `mach package-multi-locale` with pt-BR from the firefox-l10n revision pinned in the verified source (3.5 MB, 2 s). Firefox maps only the official branding for translation, so localizing Nulavio's brand needs patch 0002 (3 lines in `l10n.toml`). Integration 24/24 on the build, including `test_15` (no "Firefox" in pt-BR UI strings) | [build](../architecture/build.md#languages) |
| E22 | **Nulavio Horizon window theme** (2026-10-25) | Firefox 158 keeps its look in design tokens organised in cascade layers, with accessibility layers last. Re-valuing tokens in the last brand layer, plus one stylesheet link (patch 0003), restyles the tab strip, toolbar and address bar with no component forked. On Linux the default theme uses GTK colours (`-moz-native-theme`), so Horizon replaces them behind the pref `nulavio.horizon.enabled`. Integration 37/37 on the build (13 Horizon tests, rendered contrast); first paint and new tab not slower | [design architecture](../design/architecture.md), [screenshots](../design/screenshots/) |
| E23 | **Search and profiles on the engine's own services** (2026-10-26) | The built-in Shell gets privileged experiment APIs (allowed for built-in add-ons) over the Search Service and the profile service. One patch (0004, +17 lines) adds per-engine consent at the single remote-suggestion fetch point, because upstream lets an alias send keystrokes to any engine once suggestions are on. Profiles reuse `SelectableProfileService` (switching through the engine's remote service or an argument list). Integration 59/59 on the build (the 4 network tests run separately) | [ADR 0002](0002-nulavio-search.md), [ADR 0003](0003-nulavio-profiles-and-routing.md) |
| E24 | **Command-line handler from the branding directory** (2026-10-26) | `components.conf` + `EXTRA_JS_MODULES` in `browser/branding/nulavio/` register a JS command-line handler at build time (static components), with no Mozilla file changed. It runs before the browser's own handler, so Smart Profile Routing decides links from other apps before any request. On Linux the engine's remote service uses the session D-Bus; the test harness provides a private bus | [ADR 0003](0003-nulavio-profiles-and-routing.md) |
| E25 | **Address-bar routing hook** (2026-10-26) | The 158 address bar starts every load in one parent-side method (`UrlbarParentController.loadURL`); patch 0005 (+20 lines) asks Smart Profile Routing there before loading. The patch stack is 5 patches, within the ~10 threshold of the reversal criteria | [ADR 0003](0003-nulavio-profiles-and-routing.md) |
| E26 | **Programs never opened from the downloads UI** (2026-10-27) | The panel (`downloads.js`) and the Library (`DownloadsViewUI.sys.mjs`) decide "open" in four places: the default command, two `isCommandEnabled` implementations and the panel's click handler, which also toggles "open when done" for a running download. Patch 0007 consults `NulavioDownloads.sys.mjs` (branding directory) in each; the Shell's flow E page stays | `test_shell` 03–04 on the Nulavio build |
| E13 | Firefox build requirements | 64-bit Linux, "4GB RAM minimum, 8GB+ recommended", "At least 30GB of free disk space". No build-time figure is published. | [Linux build docs](https://firefox-source-docs.mozilla.org/setup/linux_build.html) |

## Comparison

Legend: ✅ demonstrated here · 🟡 documented or plausible, not demonstrated · ❌ demonstrated or documented failure / blocker · ⬜ not evaluated.

| Criterion | A. Gecko | B. Qt WebEngine 6.11 | C. Chromium fork |
|---|---|---|---|
| Proton Pass (official) | ✅ installs, runs, popup (E4). Login is a manual test pending. | ❌ loads but cannot be enabled (crash, E5) | 🟡 the Chrome build exists; no fork built |
| KeePassXC-Browser + native messaging | ✅ association + autofill end to end (E14, container); 🟡 on the user's own desktop | ❌ native messaging undocumented (E6) and enabling crashes | 🟡 Chromium supports native messaging |
| Bitwarden | ✅ installs, runs, popup (E4) | ❌ same crash | 🟡 |
| uBlock Origin (full, with dynamic filtering) | ✅ blocks and is reversible (E2); Firefox keeps the blocking `webRequest` API | ❌ MV3 only, so uBO Lite at best | ❌ MV2 removed upstream, so uBO Lite only |
| WebExtensions surface (popup, content scripts, background, permissions) | ✅ mature, AMO-signed ecosystem | 🟡 new (6.10); API coverage undocumented | ✅ broad |
| Extensions in private windows | ✅ per-extension opt-in | ❌ not in off-the-record profiles (E6) | ✅ |
| Linux sandbox | ✅ seccomp-bpf + user namespaces verified per process (E2, E3) | 🟡 Chromium sandbox inside Qt; not measured | 🟡 strong upstream, not measured |
| Wayland / KDE integration | ✅ app_id, portals, PipeWire camera (Fedora default) | ✅ native Qt (KDE's own toolkit) | 🟡 |
| UI customisation | 🟡 Track B: branding dir, built-in add-ons, CSS, frontend patches. Track A: limited (preview theme) | ✅ total (own QML UI) | 🟡 heavy C++/WebUI patches |
| Build size / time / host requirements | 🟡 30 GB+ disk, est. 60–120 min first build here (not measured, see below) | ✅ links system Qt; light | ❌ ~100 GB+ checkout, multi-hour builds |
| Upstream security updates | ✅ Track A rides the distribution package; 🟡 Track B needs a rebase within an SLA | 🟡 depends on Qt's Chromium backport cadence (weeks behind Chrome stable is typical; to verify) | 🟡 fast upstream, heavy rebase |
| Fork complexity | 🟡 low if patch stack stays minimal (prior art: LibreWolf, Zen, Floorp, Mullvad Browser) | ✅ no fork; ❌ but we own the whole browser UI and its security UX | ❌ high |
| Passkeys / WebAuthn | 🟡 Firefox supports WebAuthn and passkeys incl. via extensions (Proton Pass, Bitwarden); to test | ⬜ | 🟡 |
| Licensing & trademark | ✅ MPL-2.0 file-level copyleft; ❌ no Firefox marks in modified builds (E11), so full rebrand needed | ✅ LGPL/GPL Qt; Chromium BSD | 🟡 BSD; Google marks |
| Packaging RPM / DEB / Flatpak | ✅ RPM/DEB straightforward. Flatpak: native messaging needs host access (blocked until a portal solution is validated) | 🟡 | 🟡 |
| Small-team operating cost | 🟡 moderate (rebase every 4 weeks, or ESR) | 🟡 low engine cost, high UI/security-UX cost | ❌ highest |

### Build cost estimate for Track B (estimate before E17; measured: ≈ 52 min, 23 GB)

- **Disk:** about 45 GB in total: a source tarball extracted (~4–5 GB) or a git checkout (larger), the `~/.mozbuild` toolchains (~5 GB), and an object directory (~10–20 GB), on top of Mozilla's 30 GB minimum. Available: 325 GB.
- **RAM:** 30 GiB available, above the recommended 8 GB+. Linking `libxul` is the peak.
- **CPU/time:** Mozilla publishes no figure. For an 8-core, 16-thread 15–25 W laptop part we estimate **60–120 min** for the first full build and minutes for incremental frontend builds. This is an estimate; Phase 1 records the real time.
- **Host changes:** the build needs a compiler toolchain that is not installed. Plan: build inside a disposable `podman`/`toolbox` Fedora container so nothing is installed on the host; `./mach bootstrap` downloads Mozilla's toolchains into the container. **This needs the maintainer's go-ahead** (multi-GB download, hours of CPU).

## Consequences

- Positive: P0 extensions run unmodified today. uBO keeps its full blocking capability. Sandboxing is upstream's and verified. Security updates for Track A come from Fedora with zero Nulavio involvement.
- Negative: Track A cannot rename the app internals (window title says "Mozilla Firefox", About dialog is Firefox). The chrome theme uses fragile CSS variables (verified for 158). A built-in new tab is not possible without signing. All of this is resolved only by Track B.
- Track B commits the project to a security rebase SLA (see [update policy](../architecture/update-policy.md)) and to a full rebrand.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Track B lags Mozilla security releases | Medium | High | Patch stack kept minimal and declarative-first; CI rebuild on each release tag; SLA targets; fall back to Track A distribution model if the SLA is missed repeatedly |
| Proton/KeePassXC behaviour differs in a rebranded Gecko (app ID, native-messaging path, AMO access) | Medium | High | Keep Firefox's application ID for add-on compatibility (prior art: other Gecko forks; legal check pending); keep `~/.mozilla/native-messaging-hosts` lookup or document a symlink; certify each provider per release |
| Mozilla changes extension sideloading or prefs used by Track A | Medium | Medium | Integration test fails loudly on any unknown pref (E2 test 02); Track A is a preview, not the product |
| Fedora wrapper bypass misses a future distro fix | Low | Medium | `doctor` reports the engine package; re-review the wrapper on each Fedora major |
| Track B ships without working Safe Browsing | Was real: key missing, then lists failing in one batch (E19) | High | Key from a secret; only lists Google serves to it; `test_12` (key) and `test_14` (end to end) |
| AMO terms or trademark issues for a fork | Low/unknown | High | Legal review before any public Track B release (open item) |
| Qt crash is a PySide6-only bug and Qt is better than measured | Medium | Low (decision unaffected: MV2 and private-profile limits remain) | Re-test with a C++ reproducer if Qt is ever reconsidered |

## Reversal criteria

Reopen this ADR if **any** of these holds:

1. An official P0 extension (Proton Pass, or KeePassXC-Browser with native messaging) cannot work on a rebranded Gecko build after a documented attempt with the vendor (two consecutive releases).
2. Track B misses the security SLA (critical/high MFSA fixes shipped within 72 h of Mozilla's release) for two consecutive security releases because of fork/rebase cost.
3. Mozilla removes blocking `webRequest`, or AMO stops serving extensions to Gecko derivatives.
4. Qt WebEngine documents and demonstrates: native messaging, extensions in off-the-record profiles, a working `setExtensionEnabled`, and security-patch latency comparable to Gecko. Proton Pass must then pass the same smoke test as E4.
5. A Chromium base is required for a P0 capability that Gecko cannot offer (none identified).

## Open items

1. ~~Go-ahead for the Track B build spike~~ **Done (E17):** built in ≈ 52 min using 23 GB. Next: Mozilla-hosted URL audit (help/support links), built-in new tab, RPM packaging.
2. **Release vs ESR base for Track B.** Recommendation: follow **Release** (latest web-compat and WebAuthn work), and switch to ESR only if the patch stack exceeds about 10 non-branding patches or a rebase exceeds one working day. **Decided 2026-11-14 by the maintainer:** follow Release, even past ten patches ("não vejo problema em manter na release mesmo que passe de 10 patches. temos de considerar que hoje temos IA"). The count stood for the cost of rebasing the stack on each release, and coding agents now do most of that work. What still limits the stack: a pref, policy, branding or built-in add-on is still preferred, each patch has its own reason and owner, a new patch comes with a test of what it changes, and an engine update still fits the [update policy](../architecture/update-policy.md)'s times, build and test runs included. Reversal criterion 2 reopens this ADR when it does not.
3. **Application ID and AMO for a rebranded build.** Keep Firefox's add-on application ID for compatibility; confirm the policy and legal position before public distribution. **Decided 2026-11-10 by the maintainer:** keep it and install from addons.mozilla.org, on the prior art of other Gecko-based browsers (LibreWolf, Waterfox); Proton Pass from AMO works on the Nulavio build. Not reviewed by counsel; revisit if Mozilla's AMO or trademark terms say otherwise.
4. ~~Native messaging path in Track B~~ **Resolved (E16a):** rebranded builds keep reading `~/.mozilla/native-messaging-hosts`. Pairing demonstrated in a Fedora container (E14). Still to do: the maintainer's own desktop, Ubuntu KDE, and Flatpak KeePassXC.
5. **Manual login/autofill certification** for Proton Pass, KeePassXC and Bitwarden with real accounts (maintainer).
6. **Ubuntu:** the default Firefox is a Snap that cannot read hidden directories, so the preview requires Mozilla's APT package. To verify on Ubuntu KDE.
7. ~~Google Safe Browsing key for Track B~~ **Resolved (E19).** Remaining: Google quota review before a public release, and download protection (residual risk R15).
8. Brand and domain status are tracked in [brand strategy](../brand/strategy.md#trademark-and-availability-status); trademark matters are handled privately by the maintainer.

## References

- Firefox Linux build: <https://firefox-source-docs.mozilla.org/setup/linux_build.html>
- Firefox source docs: <https://firefox-source-docs.mozilla.org/>
- Enterprise policies: <https://mozilla.github.io/policy-templates/> and <https://firefox-admin-docs.mozilla.org/reference/policies/extensionsettings/>
- Mozilla distribution policy: <https://www.mozilla.org/en-US/foundation/trademarks/distribution-policy/>
- Native manifests (native messaging): <https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests>
- Proton Pass extension: <https://proton.me/support/pass-browser-extension>
- KeePassXC docs: <https://keepassxc.org/docs/>
- Bitwarden browser extension: <https://bitwarden.com/help/getting-started-browserext/>
- Secret Service API: <https://specifications.freedesktop.org/secret-service/latest-single/>
- Qt `QWebEngineExtensionManager`: <https://doc.qt.io/qt-6.10/qwebengineextensionmanager.html>
