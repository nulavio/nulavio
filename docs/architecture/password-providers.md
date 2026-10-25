# Password providers (Nulavio Bridge)

Nulavio does **not** implement a password manager. It makes the user's chosen manager work well and keeps only one manager offering to save or fill.

## Model

- A profile has exactly one **credential provider**: `builtin` (engine), `proton-pass`, `keepassxc` or `bitwarden`. Source: [`browser/config/providers.json`](../../browser/config/providers.json).
- Choosing an external provider turns **off** the engine's save prompts, autofill and generator (`signon.rememberSignons`, `signon.autofillForms`, `signon.generation.enabled`) for that profile. **Saved engine logins are not deleted.** The CLI says this before applying, and `nulavio provider set builtin` reverts it.
- Provider prefs are applied only while the profile is closed, so the choice is never half-applied.
- The provider's **official** extension is installed only on explicit request (`--install-extension`), from the pinned, hash-verified AMO file.
- Nulavio never reads vault data, never calls undocumented vendor APIs, never exports secrets, and never creates a second persistent password store.

## Status per provider (Firefox 158 engine, updated 2026-10-25)

| Priority | Provider | Integration path | Verified automatically | Pending (manual / blocked) |
|---|---|---|---|---|
| P0 | **Proton Pass** | Official AMO extension (MV3 on Firefox), unmodified | Installs as a normal extension, Mozilla-signed, background running, popup renders the sign-in screen ([evidence](../research/evidence/gecko-158-password-extensions.json)). **On the maintainer's desktop** (Fedora 44 KDE Wayland, Track A, 2026-10-25): profile created by `nulavio setup --provider proton-pass --install-provider-extension`, extension active, **signed in to a real account**; the engine's own manager stays off (`signon.*` false, no `logins.json`) | Autofill on a real site, unlock after restart, autosave, aliases, passkeys |
| P0 | **KeePassXC** | Official KeePassXC-Browser + native messaging host `org.keepassxc.keepassxc_browser` | **End to end in a Fedora 44 container** (KeePassXC 2.8.0 package, Xvfb): association accepted, popup "connected", **username and password autofilled** on a fixture page from a throwaway database ([evidence](../research/evidence/keepassxc-2.8.0-native-messaging.json), [spike](../../scripts/research/keepassxc_native_messaging_spike.py)) | Manual desktop certification: **not planned by the maintainer** (does not use KeePassXC); the container end-to-end test runs in CI on every push. Community testers welcome: Ubuntu KDE, Flatpak KeePassXC with a host browser |
| P1 | **Bitwarden** | Official AMO extension. Optional desktop-app native messaging for biometric unlock | Installs, signed, background running, popup renders. Its onboarding offers to disable the browser's own manager through the `privacy` permission, consistent with our single-provider rule | Manual certification **not planned by the maintainer** (does not use Bitwarden); community testers welcome. Desktop-app host `com.8bit.bitwarden` and allowed extension ID **verified** in Bitwarden's source (`apps/desktop/src/main/native-messaging.main.ts`) |
| P1 | Secret Service / GNOME Keyring | `org.freedesktop.secrets` | `doctor` detects the provider (on the reference machine: `ksecretd`, KDE) | Not used to store web logins (see below) |
| P1 | KDE Wallet | `kwalletd6` | `doctor` detects it | Same as above |
| P2 | Other WebExtension / native-messaging managers | Same contract as above | — | Case by case |

## KeePassXC specifics

- Firefox looks for per-user manifests in `~/.mozilla/native-messaging-hosts/<name>.json`, and system-wide in `/usr/lib64/mozilla/native-messaging-hosts/` or `/usr/lib/mozilla/native-messaging-hosts/` ([MDN](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests)). Verified in the 158 engine code: user dir first, then system dir.
- Because Track A runs the Firefox engine, Nulavio profiles see the same manifests as your regular Firefox. Enabling "Firefox" in KeePassXC's browser integration settings is enough. Nulavio never writes these manifests itself.
- KeePassXC as a Flatpak with a host browser needs the manifest to point at the exported Flatpak command. This is a known-fragile setup and will be tested before it is documented as supported.
- Track B: verified in the 158.0.1 source that user manifests are always read from `~/.mozilla/native-messaging-hosts`, even for a rebranded build (`nsXREDirProvider.cpp`, "forcing the legacy path for compatibility"). KeePassXC and Bitwarden desktop integrations therefore need no Nulavio-specific setup.
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
