# Phone unlock: compatibility report (2026-10-26)

Question: can a phone (Android or iPhone, biometrics/PIN) **release the key** that decrypts a Nulavio profile, on Linux and Windows? Three options were studied: WebAuthn hybrid + PRF, a dedicated Nulavio Companion app, and approval-only. Decision: [ADR 0005](../adr/0005-phone-profile-unlock.md). Nothing below was tested on a phone yet; every cell says where its state comes from.

States: `SUPPORTED_AND_TESTED`, `DOCUMENTED_NOT_TESTED`, `EXPERIMENTAL`, `UNSUPPORTED`, `UNKNOWN`.

## A. WebAuthn hybrid + PRF (a passkey on the phone)

What is needed for key release, not just sign-in: the desktop side must act as a WebAuthn client over the **hybrid** transport and obtain a **PRF** (CTAP2 `hmac-secret`) output from the phone's passkey, then derive a wrapping key from it.

### Facts from official or primary sources

| # | Fact | Source |
|---|---|---|
| A1 | Firefox supports hybrid only where the OS provides it (recent Windows and macOS). On Linux it is **not supported**; Mozilla prefers an OS-level Linux service and says it is "not currently a priority" | [Bugzilla 1543674](https://bugzilla.mozilla.org/show_bug.cgi?id=1543674) |
| A2 | Hybrid needs **Bluetooth and the Internet on both devices**; Bluetooth only proves proximity | [Microsoft: passkeys in Windows](https://learn.microsoft.com/en-us/windows/security/identity-protection/passkeys/) |
| A3 | After the QR code and BLE advert, the connection runs **through a tunnel server operated by the phone side**: Apple for iPhones, Google for Android with Play Services | [A Tour of WebAuthn, hybrid chapter](https://www.imperialviolet.org/tourofwebauthn/tourofwebauthn.html) |
| A4 | PRF inputs are hashed with the `"WebAuthn PRF"` context before reaching the authenticator; over hybrid they arrive already hashed, so Android passes a synthetic `prfAlreadyHashed` extension to providers. That extension is **not specified** (W3C issue opened 2026-10-15, no reply) | [Tour of WebAuthn, PRF section](https://www.imperialviolet.org/tourofwebauthn/tourofwebauthn.html); [w3c/webauthn#2489](https://github.com/w3c/webauthn/issues/2489) |
| A5 | PRF results come from authentication (`get()`), not registration; the output must be treated as input keying material (HKDF), and a robust recovery path is "non-negotiable" | [Yubico: Developer's guide to PRF](https://developers.yubico.com/WebAuthn/Concepts/PRF_Extension/Developers_Guide_to_PRF.html) |
| A6 | Windows Hello platform passkeys lack `hmac-secret`; iCloud Keychain passkeys give PRF in Safari 18+/Chrome on macOS 15 and iOS 18; Google Password Manager passkeys give PRF in Chrome on Android (Yubico table, mid-2025). None of these rows is about hybrid | [Yubico developer's guide](https://developers.yubico.com/WebAuthn/Concepts/PRF_Extension/Developers_Guide_to_PRF.html) |
| A7 | Linux system-level passkeys are being built (Credentials for Linux: `libwebauthn` lists hybrid caBLE v2; `credentialsd` D-Bus service and proposed portal). Origin binding and unprivileged browser APIs are open problems; no stable release found | [FOSDEM 2026 talk](https://fosdem.org/2026/schedule/event/credentials-for-linux-bringing-passkeys-to-linux); [libwebauthn](https://docs.rs/crate/libwebauthn/0.8.0) |
| A8 | A WebAuthn credential is scoped to an RP ID (a domain); a native desktop app that is not a browser needs the platform to let it assert for that RP ID. On Linux there is no such platform API today (A1, A7) | [W3C WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/) |

### Matrix: phone releases the profile key through hybrid + PRF

| Desktop + phone | State | Why |
|---|---|---|
| Linux + Android | **UNSUPPORTED** (Nulavio), **EXPERIMENTAL** (ecosystem) | No hybrid in Gecko on Linux (A1); `libwebauthn` implements hybrid but has no stable system service (A7); PRF over hybrid relies on an unspecified Android path (A4) |
| Linux + iPhone | **UNSUPPORTED** (Nulavio), **UNKNOWN** (ecosystem) | As above; no source documents PRF from iCloud Keychain over hybrid |
| Windows + Android | **UNKNOWN** | Hybrid sign-in is documented (A2), PRF over hybrid on Windows is not documented anywhere we found |
| Windows + iPhone | **UNKNOWN** | Same as above |

Even where it may work, hybrid needs Bluetooth, Internet on both devices and a third-party tunnel (A2, A3): **no offline unlock**, and normal unlock depends on Apple's or Google's servers.

## B. Nulavio Companion (a small app, our own protocol)

| Capability | Android | iOS | Source |
|---|---|---|---|
| Non-exportable hardware keys | TEE or StrongBox; key material never enters the app process; verify with `KeyInfo.getSecurityLevel()` | Secure Enclave keys cannot be exported | [Android Keystore](https://developer.android.com/privacy-and-security/keystore); [CryptoKit SecureEnclave](https://developer.apple.com/documentation/cryptokit/secureenclave) |
| Key use bound to local authentication | `setUserAuthenticationParameters` per operation with `AUTH_BIOMETRIC_STRONG` and/or `AUTH_DEVICE_CREDENTIAL`; `BiometricPrompt` | `SecAccessControl` (e.g. biometry current set, device passcode) | [Android Keystore](https://developer.android.com/privacy-and-security/keystore); [Android biometrics](https://developer.android.com/identity/sign-in/biometric-auth); [LocalAuthentication](https://developer.apple.com/documentation/localauthentication) |
| Invalidation on new biometric enrollment | Default for biometric-only keys (`setInvalidatedByBiometricEnrollment`) | "Current set" flag | same |
| Algorithms inside the hardware | StrongBox: AES-128/256, HMAC-SHA256, ECDSA and **ECDH P-256** (no X25519) | **P-256** signing and key agreement, ML-KEM-768/1024 | same |
| Offline, no account, no cloud | Yes: local network or QR, no push service required | Same | design |
| F-Droid (maintainer's decision D4) | Possible: no Google Play Services, no Firebase push | Not applicable | [F-Droid inclusion policy](https://f-droid.org/docs/Inclusion_Policy/) |

| Desktop + phone | State |
|---|---|
| Linux + Android | **DOCUMENTED_NOT_TESTED** (desktop side and protocol tested with a simulated phone in S3; device in S11) |
| Linux + iPhone | **UNKNOWN** (no iOS build planned before 1.0; never claimed without tests) |
| Windows + Android | **DOCUMENTED_NOT_TESTED** (same protocol; Windows desktop side evaluated in U10) |
| Windows + iPhone | **UNKNOWN** |

## C. Approval-only

The phone shows "Approve?" and the desktop then opens a key it already holds. If that key stays readable by any process of the same user on the desktop, the phone adds a prompt, **not protection**: an infostealer reads the key without asking the phone. Rejected as a strong unlock and as an anti-infostealer control; at most a confirmation step on top of a real method, labelled `phone_approved` and never equated with `phone_key_release_verified`.

## What can be built now, without a phone

| Method | Protection state | Needs |
|---|---|---|
| Password (Argon2id) | `password_protected` | nothing |
| Recovery code (high entropy) | `password_protected` (offline secret) | nothing |
| OS keyring (Secret Service / KWallet) | `os_user_protected` (any same-user process can read an unlocked keyring) | `secret-tool` (present) |
| TPM-sealed key | `hardware_bound` (this machine) | user in `tss` group (optional, D3) |
| FIDO2 key with `hmac-secret` | `hardware_bound` (the key) | a key (D5), libfido2 |
| Phone release | `phone_key_release_verified` | protocol: now with a simulated phone; app: S11 |
