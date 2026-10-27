# Windows and iOS: evaluation (U10)

- **Date:** 2026-10-27 (desk evaluation; nothing was built for these platforms)
- **Question:** what it would take to ship Nulavio on Windows and the Companion on iPhone, given what exists for Linux and Android, and what blocks it.
- **Decision:** neither is in the Linux 1.0 scope. Both are feasible on the current design; each needs things only the maintainer can provide (a code-signing identity; a Mac and an Apple developer account). The protocol, the AI Bridge and the Shell need no redesign. Revisit after the Linux 1.0 release.

## Windows

| Part | Today (Linux) | On Windows | Effort / blocker |
|---|---|---|---|
| Engine (Track B) | Firefox source build in a Linux container | Mozilla builds the Windows Firefox it ships with clang-cl and cross-compiles it on Linux ([background](https://glandium.org/blog/?p=4020)); a Windows mozconfig with `--enable-bootstrap` fetches the Visual Studio sysroot and Windows SDK into `~/.mozbuild` ([Mozilla docs](https://firefox-source-docs.mozilla.org/contributing/build/working_with_esr_115.html), [cross-compiling](https://firefox-source-docs.mozilla.org/build/buildsystem/cross-compile.html)) | A second build target in the same container. Not tried here: the Visual Studio sysroot comes with Microsoft's licence terms, to be accepted by the maintainer |
| Patches 0001–0007, Shell, branding | Linux | Platform-neutral except 0006 (system Mozilla directory, Linux only) | Small |
| Nulavio tools (Python launcher, Vault, AI Bridge, Connect) | Python 3 from the distribution | Not part of Windows; needs an embedded, signed Python or a rewrite of the tools the browser calls | **Medium–large** |
| Protected profiles | gocryptfs (FUSE) | No gocryptfs; the Windows equivalents need a third-party file-system driver (WinFsp) or a different design (per-file encryption inside the profile) | **Large; new ADR** |
| Unlock methods | Password, recovery code, OS keyring (Secret Service), phone | DPAPI as the "computer login" method (same limits as the keyring: same-user malware reads it); Windows Hello can gate a TPM-held key, which would be a hardware-bound method the Linux side does not have | Medium, and a real gain |
| Phone (Companion) | Avahi resolves the phone's mDNS name | Windows 10 and later resolve DNS-SD names natively (DnsServiceResolve); outbound connections need no firewall change | Small (the protocol is unchanged) |
| Desktop integration (KDE, portals, KRunner) | Plasma | Not applicable; default-browser registration and notifications through Windows' own APIs | Medium |
| Packages and updates | RPM, .deb, signed repository | MSIX or an installer, Authenticode signing; without an established signing reputation, SmartScreen warns on first downloads | **Blocker: a code-signing identity** (maintainer) |
| Same-user infostealers (threat S11) | Not stopped; bubblewrap confines the browser only | Same limit; Windows' app containers do not apply to a desktop browser's profile | — |

## iOS (Companion only)

The desktop browser stays on Linux and Windows; on iPhone only the Companion matters (unlock).

| Part | Android | iOS | Effort / blocker |
|---|---|---|---|
| Primitives | Tink (X25519, Ed25519, XChaCha20-Poly1305) + Bouncy Castle (BLAKE2b) | Apple's CryptoKit has X25519 key agreement and Ed25519 signatures ([Apple](https://developer.apple.com/documentation/cryptokit/curve25519)) but not XChaCha20 or keyed BLAKE2b; libsodium (the desktop's own library, through a Swift binding) covers all four | Small; the fixed vectors (`tests/fixtures/nv1-vectors.json`) apply as they are |
| Key storage | Keystore key with per-use biometrics or device credential, StrongBox when present | A Keychain item with an access control that requires biometrics or the passcode for each use; the Secure Enclave holds P-256 keys only (suite v2's case) | Small |
| Transport | Listen + announce over mDNS (NSD), `ACCESS_LOCAL_NETWORK` on Android 17 | The Network framework can listen and advertise a Bonjour service; iOS 14+ asks for local-network access and expects the service type declared in Info.plist (`NSBonjourServices`, `NSLocalNetworkUsageDescription`) — to be checked against Apple's documentation when the work starts | Small |
| Distribution | F-Droid first (reproducible), Play Store later | App Store only for most users; no reproducible-build verification by the store | **Blocker: a Mac with Xcode and an Apple developer account** (maintainer) |
| Testing | JVM cross test, browser pages, device run pending | Same desktop tests; needs a device or simulator on a Mac | — |

## What would change in the docs and code

- Windows: an ADR for protected-profile storage without FUSE and for shipping the tools; a build target; signing and update channel. The AI Bridge's MCP server is plain stdio and works unchanged where its runtime exists.
- iOS: a second Companion client against the same `nv1` vectors and the same cross tests (driven from a Mac).

Residual risk R50 records that Windows and iOS are not supported, so nothing in the product or the site claims them.
