# Password providers (Nulavio Bridge)

Nulavio does **not** implement a password manager. It makes the user's chosen manager work well and keeps only one manager offering to save or fill.

## Model

- A profile has exactly one **credential provider**: `builtin` (engine), `proton-pass`, `keepassxc`, `bitwarden` or `1password`. Source: [`browser/config/providers.json`](../../browser/config/providers.json).
- Choosing an external provider turns **off** the engine's save prompts, autofill and generator (`signon.rememberSignons`, `signon.autofillForms`, `signon.generation.enabled`) for that profile. **Saved engine logins are not deleted.** The CLI says this before applying, and `nulavio provider set builtin` reverts it.
- Provider prefs are applied only while the profile is closed, so the choice is never half-applied.
- The provider's **official** extension is installed only on explicit request (`--install-extension`), from the pinned, hash-verified AMO file.
- Nulavio never reads vault data, never calls undocumented vendor APIs, never exports secrets, and never creates a second persistent password store.

## Status per provider (Firefox 158 engine, updated 2026-10-25)

| Priority | Provider | Integration path | Verified automatically | Pending (manual / blocked) |
|---|---|---|---|---|
| P0 | **Proton Pass** | Official AMO extension (MV3 on Firefox), unmodified | Installs as a normal extension, Mozilla-signed, background running, popup renders the sign-in screen ([evidence](../research/evidence/gecko-158-password-extensions.json)). **On the maintainer's desktop** (Fedora 44 KDE Wayland, Track A, 2026-10-25): profile created by `nulavio setup --provider proton-pass --install-provider-extension`, extension active, **signed in to a real account** and **autofilled username and password on a real site** (confirmed by the maintainer); the engine's own manager stays off (`signon.*` false, no `logins.json`) | Unlock after restart, autosave, aliases, passkeys |
| P0 | **KeePassXC** | Official KeePassXC-Browser + native messaging host `org.keepassxc.keepassxc_browser` | **End to end in a Fedora 44 container** (KeePassXC 2.8.0 package, Xvfb): association accepted, popup "connected", **username and password autofilled** on a fixture page from a throwaway database ([evidence](../research/evidence/keepassxc-2.8.0-native-messaging.json), [spike](../../scripts/research/keepassxc_native_messaging_spike.py)) | Manual desktop certification: **not planned by the maintainer** (does not use KeePassXC); the container end-to-end test runs in CI on every push. Community testers welcome: Ubuntu KDE, Flatpak KeePassXC with a host browser |
| P1 | **Bitwarden** | Official AMO extension. Optional desktop-app native messaging for biometric unlock | Installs, signed, background running, popup renders. Its onboarding offers to disable the browser's own manager through the `privacy` permission, consistent with our single-provider rule | Manual certification **not planned by the maintainer** (does not use Bitwarden); community testers welcome. Desktop-app host `com.8bit.bitwarden` and allowed extension ID **verified** in Bitwarden's source (`apps/desktop/src/main/native-messaging.main.ts`) |
| P1 | **1Password** | Official AMO extension (proprietary). Optional desktop-app native messaging (`com.1password.1password`); the Nulavio build needs its name in `/etc/1password/custom_allowed_browsers`, which `nulavio doctor` explains and Nulavio never writes | Installs, signed, background running, popup renders (`test_password_extensions`, with the network). Provider choice, engine prompts off, CLI (#81, 2026-11-16) | Manual certification **deferred** (the maintainer does not use 1Password). Desktop integration not measured on any package. [Specifics](#1password-specifics) |
| P1 | Secret Service / GNOME Keyring | `org.freedesktop.secrets` | `doctor` detects the provider (on the reference machine: `ksecretd`, KDE) | Not used to store web logins (see below) |
| P1 | KDE Wallet | `kwalletd6` | `doctor` detects it | Same as above |
| P2 | Other WebExtension / native-messaging managers | Same contract as above | — | Case by case |

## 1Password specifics

Added 2026-11-16 (#81), at the level of Bitwarden: **P1**, and manual certification deferred (the maintainer's decision of 2026-11-16: he does not use 1Password; community testers welcome).

- **The extension** is 1Password's own from addons.mozilla.org (`{d634138d-c276-4fc8-924b-40a0ea21d284}`), pinned with its SHA-256 in `browser/distribution/extensions.lock.json` and installed only when the person chooses 1Password. It is proprietary (AMO: "All Rights Reserved"); Nulavio does not redistribute it. It works on its own with a sign-in in the browser.
- **The desktop app** (unlock with the app, system authentication) talks to the extension through native messaging, host `com.1password.1password`, whose manifest the app writes when its browser integration is on. The app also accepts only browsers it knows. Distribution Firefox (Track A) is one of them. The Nulavio build (Track B) is not, so its binary name, `nulavio`, has to be in `/etc/1password/custom_allowed_browsers`, written by root, one name per line, then 1Password quit and opened again ([1Password](https://support.1password.com/additional-browsers/), read 2026-11-16).
- **Nulavio never writes that file** (the maintainer's decision of 2026-11-16, option a): `nulavio-doctor` (a package install; `nulavio doctor` in a source checkout, #470) says when the app is installed and the name is missing, with the exact command (`echo nulavio | sudo tee -a /etc/1password/custom_allowed_browsers`), and the person runs it. No package of Nulavio changes another vendor's configuration. The line trusts any executable named `nulavio`, not only Nulavio's; so `doctor` gives it only when the engine and the folders above it are root's alone (the RPM and DEB packages, or the archive unpacked as root), and for an engine the person's account can change (such as the archive unpacked in the home folder) says why it gives none, or warns if the name is already listed; what that leaves open is [R82](../security/residual-risks.md).
- **Permissions it asks for, accepted as the official extension's own** (the lock's `reviewed_permissions`, read from 8.12.44.33): `<all_urls>`, `scripting` and `webRequest`/`webRequestBlocking` to fill forms on any site; `nativeMessaging` for the desktop app; `privacy`, which lets it turn the engine's own password manager off (as Bitwarden does), consistent with the one-manager rule; it is a required permission here (optional for Bitwarden), so the extension may also change other privacy settings while the browser runs, which the Guard follows as changes made in the browser and does not report (R81); `management`, which lets it list other extensions: in Firefox 160 it cannot turn one off (`management.setEnabled` works only for themes and for extensions installed by policy, `ext-management.js`), so it cannot turn uBlock Origin off; why it needs the list was not checked; `http://localhost/*` (what it reaches there was not checked); `downloads` and `clipboardWrite` for exports and copying a field; `declarativeNetRequestWithHostAccess` for its own sign-in pages. A version that asks for more is a diff in the lock that `refresh_extensions_lock.py` flags for review; no test yet compares the installed extension's permissions with the lock.
- **Shortcuts:** the extension asks for Ctrl+Period (open) and Ctrl+Shift+L (lock). Ctrl+Shift+L is also Nulavio's "copy link to highlight" (#157); which one the engine gives the key when both are present was not checked. Either can be changed in Settings › Atalhos.
- **Not measured** (needs the app and an account): that the desktop integration works on the RPM, the tarball and the Flatpak bundle; which binary name 1Password checks (the engine's executable, `nulavio`, is what doctor uses: community reports say links are not followed); whether 1Password refuses a browser binary that root does not own, as it does on macOS and Windows. Community reports say the integration fails when the browser or 1Password is a Flatpak or a Snap.

## KeePassXC specifics

- Firefox looks for per-user manifests in `~/.mozilla/native-messaging-hosts/<name>.json`, and system-wide in `/usr/lib64/mozilla/native-messaging-hosts/` or `/usr/lib/mozilla/native-messaging-hosts/` ([MDN](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests)). Verified in the 158 engine code: user dir first, then system dir.
- Because Track A runs the Firefox engine, Nulavio profiles see the same manifests as your regular Firefox. Enabling "Firefox" in KeePassXC's browser integration settings is enough. Nulavio never writes these manifests itself.
- KeePassXC as a Flatpak with a host browser needs the manifest to point at the exported Flatpak command. This is a known-fragile setup and will be tested before it is documented as supported.
- Track B: verified in the 158.0.1 source that user manifests are always read from `~/.mozilla/native-messaging-hosts`, even for a rebranded build (`nsXREDirProvider.cpp`, "forcing the legacy path for compatibility"). KeePassXC and Bitwarden desktop integrations therefore need no Nulavio-specific setup.
- If the browser starts before KeePassXC is ready, the extension's first key exchange fails and the popup shows "Cannot connect to KeePassXC" until **Reload** is pressed. Observed on the slower GitHub runner (one Reload needed); the end-to-end test waits for KeePassXC's socket and presses Reload like a user would. A future Nulavio hint for this state belongs in flow B ([ux-flows](../brand/ux-flows.md)).
- In the container test the association prompt was answered automatically to simulate the user. In real use the prompt is the user's explicit consent: Nulavio never answers it.

## Secret Service and KWallet: what they are and are not

- They store **local secrets** for applications. They are not a web credential manager with origin matching, autofill or phishing resistance.
- The Secret Service specification does not require per-application access control. With a typical backend, **any process of the same user can read items from an unlocked collection**. They do not protect against an infostealer running as the user.
- Gecko on Linux does not use them for `logins.json`. Engine passwords are protected only by the optional Primary Password (`key4.db`).
- Nulavio's use (planned, P1): show the backend status, and possibly hold Nulavio's own non-credential secrets in the future. **No autofill from Secret Service in the MVP**, and no copying of vault data into it.
- Absence or failure of the service is handled by flow I in [ux-flows](../brand/ux-flows.md): nothing breaks, because Nulavio does not depend on it.

## UX rules (from the product brief)

1. The user picks the provider in onboarding or settings; the default is the engine's own manager until a choice is made.
2. Never two autofills at once: an external provider disables engine prompts in the same step.
3. Warn about suspicious origins at login time (flow D). Never show vault data in Nulavio surfaces.
4. Switching back is one action and loses nothing.

## Certification checklist (per provider, per engine release)

`install signed` · `background running` · `popup renders` (automated) · `login` · `unlock after restart` · `autofill username+password on matching origin` · `no fill on lookalike origin` · `no fill into cross-origin iframe` · `autosave new login` · `generator` · `passkey create/use` · `private window behaviour` (manual, with throwaway accounts only, never real secrets in CI).
