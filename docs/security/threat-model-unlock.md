# Threat model: profile unlock (Vault, phone, other methods)

Scope: encrypted Nulavio profiles and how they are unlocked ([ADR 0005](../adr/0005-phone-profile-unlock.md), [ADR 0006](../adr/0006-nulavio-vault.md), [architecture](../architecture/vault-and-unlock.md)). Assets: the profile DEK, the profile data, unlock secrets (password, recovery code, phone keys). Boundaries UB1–UB5 are defined in the architecture. Tests are in `tests/unit/test_vault.py` (S3) unless noted.

Nothing here protects an **unlocked** profile from malware running as the same user: it can read the mounted files and the storage key in memory. Nulavio never claims otherwise.

| # | Scenario | Preconditions | Controls | Limits | Residual | Test |
|---|---|---|---|---|---|---|
| U-T1 | Offline theft of the profile (stolen disk, backup, synced folder) | Profile locked | Data encrypted; DEK only in envelopes; KEKs not on disk (password, phone) or outside the profile (keyring) | Weak password: offline guessing against Argon2id | Low (phone, strong password) / Medium (weak password) | copy-files-does-not-unlock; wrong-password |
| U-T2 | Malware as the same user, profile **locked** | Infection while locked | Phone and password methods need the user; the keyring method does not (shown as `os_user_protected`) | Keylogger captures a password at next unlock; keyring readable | Medium | keyring state labelled; phone needs response |
| U-T3 | Malware as the same user, profile **unlocked** | Session open | Lock when idle (auto-lock), short sessions for sensitive profiles | Full read access to mounted data and keys in memory | **High; out of reach** | documented (TB6) |
| U-T4 | Malware with root/administrator | — | None at the browser level | Everything | Out of scope | — |
| U-T5 | Compromised local IPC (fake coordinator, injected messages) | Same-user malware | Phone requests are signed by the paired desktop key; responses are bound to a one-time session key | Same-user malware can steal the desktop identity (0600 file) and send requests; the user still has to approve on the phone | Medium | unsigned/unpaired request rejected |
| U-T6 | Fraudulent pairing | Attacker on the network | QR carries a pairing secret; only a reader of the QR can say hello; 6-digit comparison on both screens | A user who skips the comparison | Low | wrong-secret pairing fails |
| U-T7 | Substituted QR code (screen tampering, shoulder relay) | Attacker controls what the phone scans | Codes differ on the two screens; desktop key in the QR must sign the accept message | User does not compare | Low/Medium | substituted-desktop-key pairing fails |
| U-T8 | Replay of an unlock response | Network observer or same-user malware | One-time session key and request id; desktop accepts once | — | Low | replayed response rejected |
| U-T9 | Fake desktop asks the phone for approval | Attacker with a stolen desktop identity or none | Unpaired desktops are rejected; requests show profile and desktop names; phone UI says "only approve if you just asked" | Paired-identity theft (U-T5) plus a user who approves | Medium | unpaired desktop rejected |
| U-T10 | User tricked into approving | Social engineering | Context on the phone; requests expire in 60 s; nothing to approve unless the desktop asked | Human factor | Medium | expired request rejected |
| U-T11 | Compromised phone | Malware on the phone | Phone keys under a hardware key with per-use biometrics; revoke the phone from the desktop | Rooted phone can capture keys after an approval (v1: key briefly in app memory) | Medium | revoked phone cannot unlock |
| U-T12 | Compromised Companion build | Supply chain | Reproducible F-Droid build; signature pinning; minimal permissions | Store or signing-key compromise | Medium | (S11) |
| U-T13 | Key material in memory | Same-user malware or crash dump | Short-lived buffers wiped (`sodium_memzero`); no core dumps of the coordinator | Python copies; storage key lives while unlocked | Medium | — |
| U-T14 | Data exposed by extensions | Malicious extension in the profile | Engine permission model; Guard extension audit | Extensions see what the profile sees when unlocked | Medium | — |
| U-T15 | Secrets in logs | Developer mistake | Logs never contain secrets; tests scan outputs and files | — | Low | no-secret-in-logs |
| U-T16 | Recovery code stolen | Paper or photo leaked | High entropy, shown once, replaceable (new code, old envelope removed) | Thief with the code and a profile copy unlocks it | Medium | recovery code works; replaced code no longer works |
| U-T17 | Lost device | Phone lost | Remove phone (envelope deleted), other methods remain; key rotation offered | Profile copies taken before removal stay decryptable with that phone | Low/Medium | revoked phone cannot unlock |
| U-T18 | Downgrade to a weaker method | Attacker edits metadata or blocks the phone | Combined policies are cryptographic (one envelope needs both KEKs); metadata MAC detects edits; no automatic fallback | Deleting envelopes is a denial of service, not a downgrade | Low | tampered metadata detected; combined policy needs both |
| U-T19 | User or profile switched during an operation | Concurrent actions | Requests bound to profile id and envelope id; one pending request per profile | — | Low | response for another profile rejected |
| U-T20 | Unlock after expiry | Delayed response | Expiry checked on both sides | Clock skew ±120 s | Low | expired response rejected |
