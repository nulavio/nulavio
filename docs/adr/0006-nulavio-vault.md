# ADR 0006 — Nulavio Vault: profile keys, envelopes and lifecycle

- **Status:** Accepted (2026-10-26). Key management prototype with artificial data (S3); profile storage integration (S5).
- **Related:** [ADR 0005](0005-phone-profile-unlock.md), [architecture](../architecture/vault-and-unlock.md), [threat model for unlock](../security/threat-model-unlock.md).

## Decision

### Keys

- **Profile DEK:** 32 random bytes per profile, generated once (`randombytes_buf`). It never touches disk in clear: not in the profile, not in logs, not in the clipboard. It is the key of the profile's encrypted storage (S5: the gocryptfs volume password is derived from it with its own context).
- **Envelopes:** one per unlock method, each `XChaCha20-Poly1305(KEK_method, DEK)` with a fresh 24-byte nonce and the envelope header as associated data. Adding or removing a method writes or deletes an envelope; the data is never re-encrypted for that.
- **KEK per method:**

| Method | KEK | State shown |
|---|---|---|
| Password | `crypto_pwhash` Argon2id13, `opslimit=3`, `memlimit=256 MiB` (libsodium "moderate"), random 16-byte salt; parameters stored | `password_protected` |
| Recovery code | 130-bit random code (26 Crockford base32 characters, shown once); KEK by Argon2id with interactive parameters (the code is high-entropy) | `password_protected` |
| OS keyring | 32 random bytes stored in the Secret Service (KWallet, GNOME Keyring) under the profile's attributes | `os_user_protected` |
| Phone (`nv1`) | derived from X25519(ephemeral, phone public key); only the phone can recompute it ([ADR 0005](0005-phone-profile-unlock.md)) | `phone_key_release_verified` |
| Security key | FIDO2 `hmac-secret` output treated as input keying material | `hardware_bound` (S10) |
| TPM | sealed to this machine's TPM | `hardware_bound` (optional) |
| Combined ("password + phone") | KDF over both KEKs; one envelope that needs both | the stronger states together |

- **Domain separation:** every derivation uses `crypto_generichash` (BLAKE2b) keyed with the input secret over a context string `nulavio/vault/v1/<purpose>` plus the profile id and envelope id; envelope headers are the AEAD associated data, so an envelope cannot be moved to another profile or method.
- **Key commitment:** `dek_check = BLAKE2b(key=DEK, "nulavio/vault/v1/dek-check")` lets an unlock prove it recovered the right DEK before touching data. A wrong key fails here, never as garbage data.
- **Metadata MAC:** after unlock, `BLAKE2b(key=KDF(DEK, "metadata"), canonical metadata)` detects tampering (removed envelopes, changed labels or policy). Tampering is reported; it cannot add a working method without the DEK.

### Metadata (`vault.json`, beside the encrypted storage, mode 0600)

```json
{
  "format": "nulavio-vault", "version": 1, "suite": "nv1",
  "profile_id": "…", "created": "2026-10-26T12:00:00Z",
  "dek_check": "…",
  "policy": {"combine": [], "auto_lock_minutes": 0},
  "envelopes": [
    {"id": "…", "method": "password", "created": "…",
     "kdf": {"alg": "argon2id13", "ops": 3, "mem": 268435456, "salt": "…"},
     "nonce": "…", "ct": "…"}
  ],
  "mac": "…"
}
```

### Lifecycle

- **Create:** generate the DEK, the first envelope (the method chosen in onboarding) and the recovery-code envelope together; the profile is not created without a recovery code unless the user explicitly declines, which the UI states as "no way back if you forget".
- **Add method:** requires the profile unlocked (the DEK in memory) and a fresh authentication with an existing method ("re-authenticate for protection changes").
- **Remove method:** requires an unlocked profile; refuses to remove the last method; warns below two.
- **Rotate a wrapping key** (new password, re-paired phone): replace that envelope only.
- **Rotate the DEK** (suspected compromise, lost phone with a stolen profile copy): new DEK, new storage, data copied; offered, never automatic.
- **Lock:** end the profile's engine instance, unmount the storage, drop the DEK. Nothing sensitive stays unlocked by a hidden path.
- **All factors lost:** the data cannot be recovered. No Nulavio master key, no escrow, no backdoor; onboarding says so.

### Crash consistency

Write `vault.json.tmp` (0600), `fsync`, rename over `vault.json`, `fsync` the directory; keep the previous file as `vault.json.bak`. Loading verifies structure and, after unlock, the MAC; a corrupt main file falls back to the backup. A crash never leaves a DEK or KEK on disk.

### Memory

Secrets live in `bytearray` buffers that are wiped with `sodium_memzero` after use; Python may still copy values, so this is best effort and documented. The lasting exposure is by design: while unlocked, the storage key is in the storage driver's memory and the files are readable by the user's processes.

## Consequences

- Phone, password, recovery code and keyring are independent: losing one method does not lose the profile.
- Encryption at rest protects **locked** profiles and offline copies; it does not protect an unlocked session from same-user malware ([threat model](../security/threat-model-unlock.md)).
- Track A (distribution Firefox) gets the same Vault through the launcher; Track B integrates it with engine profiles (S5).
