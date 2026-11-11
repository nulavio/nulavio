# ADR 0005 — Phone profile unlock (the brief's `phone-profile-unlock`)

- **Status:** Accepted (2026-10-26). Desktop side and protocol: prototype with a simulated phone (S3). Android app: last slice (S11). Transport amended 2026-10-27 (S11): the phone listens, the desktop resolves it over mDNS and connects out.
- **Scope:** unlocking **Nulavio profiles** only. Not a passkey manager for websites; WebAuthn for pages is unchanged; no remote login.
- **Related:** [compatibility report](../research/phone-unlock-compatibility.md), [ADR 0006 Vault](0006-nulavio-vault.md), [architecture](../architecture/vault-and-unlock.md), [threat model](../security/threat-model-unlock.md), [brief](../product/briefs/2026-10-26-profile-unlock.md).

## Context

The maintainer wants the phone to be the first, everyday way to unlock encrypted profiles, with OS authentication, a password and an optional FIDO2 key as alternatives. The central rule: an authentication unlocks data only if it takes part in releasing the key.

## Options

| | A. WebAuthn hybrid + PRF | B. Nulavio Companion | C. Approval-only |
|---|---|---|---|
| Releases key material | Yes, if PRF is returned over hybrid | Yes (phone computes the key-wrapping secret) | **No** |
| Linux (first target) | Unsupported in Gecko; ecosystem experimental | Desktop side in Nulavio | Possible but not protection |
| Offline | No (Internet tunnel) | Yes (local network or QR fallback) | Yes |
| Third-party services | Apple or Google tunnel | None | None |
| Phone hardware protection | Passkey provider's | Keystore/StrongBox, Secure Enclave | n/a |
| Spec maturity of the path we need | PRF over hybrid unspecified on Android (W3C #2489) | Our protocol, standard primitives | n/a |
| Maintenance | Low code, high dependency risk | An app per platform, store builds | Low |

Evidence and per-platform states: [compatibility report](../research/phone-unlock-compatibility.md).

## Decision

1. **Nulavio Companion** is the phone unlock architecture. The UI calls it "Unlock with phone"; documentation never says it uses passkeys or WebAuthn.
2. **WebAuthn hybrid + PRF is not used** now. Re-evaluate when all of these hold: a Linux system passkey service ships in Fedora (Credentials for Linux or equivalent), PRF over hybrid is specified (W3C) and returned by both Android and iOS providers, and Nulavio's own tests release a key with it.
3. **Approval-only is rejected** as an unlock method. It may exist later only as an extra confirmation on top of a real method, shown as `phone_approved`.
4. **Protocol v1 (`nv1`)**, standard primitives through libsodium on the desktop (decision D1): X25519, Ed25519, XChaCha20-Poly1305, BLAKE2b-based key derivation. Pairing and unlock are specified in [architecture](../architecture/vault-and-unlock.md#phone-protocol-nv1):
   - **Pairing:** one-time QR invitation (desktop key, pairing secret, expiry), an authenticated key exchange over the local network, and a 6-digit code the user compares on both screens (defeats QR substitution and relays). The QR alone never pairs.
   - **Envelope:** the desktop wraps the profile key for the phone with an ephemeral X25519 key against the phone's long-term key and keeps only the result. The desktop cannot open it without the phone.
   - **Unlock:** a request signed by the desktop, bound to profile, device, operation and a 60-second expiry; the phone shows it, the user authenticates locally, the phone computes the wrapping key and returns it encrypted to a fresh desktop session key and signed. Replayed, expired, unpaired or substituted responses fail.
   - **Phone key storage (v1):** the phone's Curve25519 keys are kept encrypted under a **non-exportable hardware key that requires biometrics or the device PIN for each use** (Android Keystore, StrongBox when present; iOS Keychain with access control). This is *hardware-protected*, not *hardware-bound*: during an unlock the private key is briefly in the app's memory.
   - **Suite v2 (reserved):** HPKE (RFC 9180) with DHKEM(P-256) computed inside StrongBox or the Secure Enclave, so the phone key never leaves hardware. Both phone platforms support P-256 key agreement in hardware; the desktop needs a vetted P-256 implementation, which libsodium does not provide. Adopted in S11 if the device test confirms it, with a reviewed desktop library; the metadata is versioned for it.
5. **Transport:** local network, no relay in v1 (a relay, if ever added, would only carry end-to-end encrypted messages it cannot open). **Amended 2026-10-27 (S11):** the *phone* listens and the desktop connects out, instead of the reverse. See [Transport amendment](#transport-amendment-2026-10-27).
6. **Recovery before release:** phone unlock is not offered for distribution until at least two other methods work for the same profile (recovery code, plus a password, a second phone or a security key), and the onboarding tests the recovery code.

## Transport amendment (2026-10-27)

**Evidence.** On the reference Fedora 44 KDE desktop the firewall's default zone is `public`, which accepts incoming connections only for cockpit, dhcpv6-client, mDNS and SSH. A desktop listening on a random port, as first decided, is unreachable from the phone unless the user changes the system firewall (an administrator action Nulavio must not take silently). Outgoing connections and mDNS are allowed; Avahi runs by default on Fedora and Ubuntu desktops and answers on the system bus.

**Decision.** For pairing and for each unlock request, the phone opens a listening socket on its Wi-Fi address for that operation only (at most the pairing's 5 minutes or the request's 60 seconds) and announces it over mDNS as service `_nulavio-nv1._tcp` with an instance name derived from the operation: `nv1-p-<16 base32 chars of BLAKE2b(invite_id)>` for pairing, `nv1-u-<… of BLAKE2b(req_id)>` for unlock. The desktop resolves exactly that name through Avahi (`ResolveService` on the system bus, IPv4) and connects out. Neither side needs a firewall change. On the connection, messages are canonical JSON lines (at most 16 KiB each) and the phone speaks first:

| Operation | Phone → desktop | Desktop → phone |
|---|---|---|
| Pairing | `{"t":"hello",…}`, later `{"t":"confirm",…}` or `{"t":"cancel"}` | `{"t":"accept",…}`, then `{"t":"paired"}` or `{"t":"error","code":…}` |
| Unlock | `{"t":"response",…}` (box or refusal, signed) | `{"t":"ok"}` or `{"t":"error","code":…}` |

**Why it is safe.** The transport adds no trust: everything the desktop accepts is authenticated by the protocol (`nv1`). Someone on the network who announces the same name, or connects to the phone first, learns nothing usable (the pairing box needs the QR secret; the unlock box needs the desktop's session key) and can only delay the operation; the desktop ignores a response not signed by the paired phone and keeps resolving until the request expires. The mDNS name reveals to the local network that a Nulavio phone operation is under way, not which profile or desktop.

**Limits.** Networks that isolate Wi-Fi clients or drop multicast (some guest and corporate networks) block both directions alike; then the UI says the phone could not be reached and offers the profile's other methods. Without Avahi on the desktop, "Unlock with phone" is unavailable (shown as such).

## Implementation (S11, 2026-10-27)

**Built and tested, on the real phone since 2026-11-10.** Everything below runs; the device test passed on the maintainer's Galaxy S24+ (Android 17) over the real network path, and so did a manual pass with the camera (see *Real-phone run* and *Manual pass*).

- **Desktop:** the transport above (`vault/link.py`), pairing and unlock sessions in a short-lived helper process (`vault/phone_session.py`), browser API ops `phone-pair-start`, `phone-unlock-start`, `phone-session`. Pairing re-authenticates with the profile's password or recovery code and refuses unless the profile has a recovery code and one other method (§6).
- **Browser:** Settings → Profiles → *Phones* on a protected profile opens `vault/phone.html` (current secret, code, the 6 digits with "They match"/"They are different", phones listed and removable); the locked-profile page offers *Unlock with phone* (code, "Approve on your phone", then the profile and any held-back address open). The code is drawn as SVG from the engine's own QR encoder (`moz-src:///toolkit/components/qrcode/encoder.mjs`), always dark on light.
- **Phone protocol library:** `android/nv1`, plain Java: Tink (X25519, Ed25519, XChaCha20-Poly1305) and Bouncy Castle (keyed BLAKE2b), canonical JSON byte for byte as the desktop's. Checked against fixed vectors from the desktop's libsodium and against the Python desktop over a socket.
- **App:** `android/app` (`net.nulavio.companion`, minSdk 30, target 37), Java, platform UI, no AndroidX, no Google services; ZXing for the camera. Permissions: internet, local network (`ACCESS_LOCAL_NETWORK`, asked at run time on Android 17), camera, biometrics; backups and device transfers excluded.
- **Phone key storage (v1, as decided):** the nv1 private keys are encrypted with an AES-256-GCM key in the Android Keystore (StrongBox when present, else the TEE; the app shows which, as the Keystore reports it), non-exportable, usable only on an unlocked device and only through a BiometricPrompt `CryptoObject` with biometrics or the device credential for **each** use (timeout 0); invalidated when biometrics change. The public state (public keys, paired computers, answered request ids) is a plain file in the app's private storage: nothing in it unlocks a profile. So pairing costs one authentication (to sign the confirmation) and each unlock one (to compute the answer). *Not now* sends nothing; the desktop offers its other methods.
- **Suite v2** (P-256 inside StrongBox) is not adopted: it needs the device test and a reviewed P-256 implementation on the desktop; v1 stays as specified.
- **F-Droid:** recipe `android/fdroid/net.nulavio.companion.yml` (submitted to fdroiddata on 2026-11-11 for tag `companion-v0.1.0`; the summary sits in `net.nulavio.companion/<locale>/summary.txt`, as fdroiddata requires); the release APK is byte-for-byte identical when rebuilt from a fresh copy in another folder (2026-10-27); Gradle 9.8.2 and all 213 build artifacts are pinned by SHA-256 (`gradle/verification-metadata.xml`). CI runs the library tests, the cross test, Android lint and the release build.

**Tests:** `tests/unit/test_phone_link.py` (transport and sessions with the reference phone over TCP against real encrypted profiles; with `NULAVIO_LAN_TESTS=1` through the machine's real Avahi, pairing and unlocking in 3 s), `tests/unit/test_companion_protocol.py` (the Java phone against the Python desktop: pairing, unlock that mounts the profile, replay, tampered, unknown-desktop and expired requests refused), `android/nv1` JUnit (vectors, JSON, public state without secrets), `tests/integration/test_vault_ui.py` 08–09 (the browser pages, Nulavio build), `tests/unit/test_companion_build.py` (no Google services, the four permissions, per-use key, debug-only hooks, pinned inputs, recipe matches the build), and `tests/integration/test_companion_emulator.py` (the app driven over adb against the real desktop; opt-in).

**Real-phone run (2026-11-10).** `test_companion_emulator.py` passed 5/5 on the Galaxy S24+ (SM-S926B, Android 17, keys in StrongBox) over wireless debugging, with the desktop finding the phone through Avahi on the home network (no adb port forward): set up, pairing with the same six digits on both sides, unlock that mounts an encrypted profile, the answered request refused again, *Not now*. A screenshot pass covered every screen in pt-BR and en-US, dark and light. The Android emulator still crashes on the reference desktop, so the phone is the only device run. What the run found and fixed:

- **Scanning crashed the app.** The scanner library's own activity asks for the camera through AndroidX, which the APK does not ship (`isTransitive = false`); the debug-intent path of the test never opened the camera. The app now has its own `ScanActivity` (platform permission request, the library's view only) and removes the library's activity from the manifest; `test_companion_build` refuses any code path that needs AndroidX.
- **The unlock request's profile and computer were hidden.** Apps that target Android 15+ are drawn edge to edge; the first lines of each screen sat under the action bar. The app now has no action bar (each screen has its own title) and pads every screen by the system bars.
- **A cancel on the desktop did not stop a held request.** The phone connects as soon as it shows the request; the desktop then waited for its answer without watching for a cancel, so an approval on the phone after a cancel on the computer would still have unlocked the profile. The desktop now ends the session at once (`test_phone_link` 06), and *Not now* on the phone closes the accepted connection so the computer offers its other methods immediately.
- **An expired request said "the computer did not connect".** It now says the request expired.
- **Screens.** Brand colours (light and dark), a filled primary and an outlined secondary button with space between them, problems in red and news in mint, a confirmation before removing a computer, a progress indicator, the version in a footer.

**Manual pass (2026-11-10, the maintainer, on the S24+ against the v160.0-0.1 package with this Shell applied by `dev_sync.py`):** a protected profile created in the browser, the phone paired by scanning the code on the browser's page with the camera, the profile unlocked by scanning the unlock code, an unlock with the phone in airplane mode that did not open the profile and left the other methods offered, and the phone removed on the desktop, after which the unlock page no longer offered it. All as expected.

**Desktop binding (2026-11-11, audit V3).** The 2026-11-10 security audit found that a phone answered any desktop it is paired with for any envelope that desktop could name: one holding a copy of another desktop's `vault.json` could get that profile's key under harmless names. The fix, before phone unlock is offered: the phone envelope's KEK derivation includes the signing key of the desktop that made it (the phone uses the key of the desktop whose request it verified), the phone shows the desktop name from its own pairing record, and it refuses requests that claim to stay valid longer than 60 s plus clock skew. Envelopes made earlier report `phone-needs-pairing`; nothing shipped with them (pairing was off in every release). Tests: `test_vault.DesktopBindingTest` (the attack fails before the fix and is refused after it), the Java side against the same vectors (`nv1-vectors.json`, `VectorsTest`, `test_companion_protocol`).

## Availability (decision D10, 2026-11-04; revised 2026-11-10)

D10 took phone unlock out of 1.0 while the Companion had not run on a real phone. After the device test passed on the Galaxy S24+ (2026-11-10) and the desktop binding closed audit V3 (2026-11-11), the maintainer put it back: the browser offers to connect a phone, and the Companion ships on F-Droid.

- `nulavio.vault.phone.pairing` is on in the build. The unlock-methods page links to the phones and says only that the security key is not available yet (FIDO2, slice S10, is not built); the phone page tells people without the app to install it from F-Droid.
- With the pref off, the page offers no code and the Shell refuses to start a pairing (`phone-not-yet`); a phone already connected keeps unlocking its profile and can be removed, so nobody is locked out.
- The pages' "no master key" line names no method, so it is true for every profile.
- Release order: the browser release that turns the offer on goes out once the Companion is on F-Droid (or its APK is attached to the release), so the page never sends people to an app they cannot get.

`test_vault_ui` 08 and 09 run with the offer on (the default), 13 with it off.

## Threat model summary

Full list: [threat model for unlock](../security/threat-model-unlock.md). Key points:
- Offline theft of the profile: protected (the key is not on the desktop in any usable form while locked).
- Same-user malware **while the profile is locked**: cannot unlock without the phone and the user's biometrics. **While unlocked**: the data is readable through the mounted profile; no method changes that.
- Fake desktop or tricked user: requests show the profile and desktop name; requests are signed by a paired desktop; a request the user did not start is a warning sign the UI explains.
- Lost phone: remove it from the desktop (its envelope is deleted); a copy of the profile taken before removal stays decryptable by that phone, so the guidance is to rotate the profile key if theft is suspected.

## Maintenance cost

One small Android app (F-Droid build: no Google services; Play Store later), the desktop protocol in the launcher, and later an iOS app. The protocol is versioned; any change gets new test vectors.

## Implementation criteria (all required before "Unlock with phone" ships)

- Protocol tests pass with the simulated phone and then with a real Galaxy S24+ (Android 17): unlock works; expired, replayed, unpaired, substituted and cancelled requests fail; network loss offers another method.
- Two recovery methods verified per profile.
- No secret in logs, clipboard or files outside the envelopes (tested).
- Threat-model scenarios mapped to tests.

## Cancellation criteria

- The Android app cannot keep keys behind per-use local authentication on supported devices, or cannot be built for F-Droid without proprietary components.
- A design review finds the protocol unfixable without a different primitive set; then suite v2 or WebAuthn hybrid + PRF (if criteria in Decision 2 are met) are reconsidered.
- Users cannot complete pairing reliably on a local network in field tests; then a relay that only carries end-to-end encrypted messages is designed as a separate ADR.
