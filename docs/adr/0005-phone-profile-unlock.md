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
