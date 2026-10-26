# ADR 0006 — Nulavio Vault: profile keys, envelopes and lifecycle

- **Status:** Accepted (2026-10-26). Key management **implemented (S3)**; encrypted profile storage **implemented (S5)**; unlock and onboarding in the browser **implemented (S6)** for password, computer login (OS keyring) and recovery code. Phone (S11) and security keys (S10) to come.
- **Related:** [ADR 0005](0005-phone-profile-unlock.md), [architecture](../architecture/vault-and-unlock.md), [threat model for unlock](../security/threat-model-unlock.md).

## Decision

### Keys

- **Profile DEK:** 32 random bytes per profile, generated once (`randombytes_buf`). It never touches disk in clear: not in the profile, not in logs, not in the clipboard. It is the key of the profile's encrypted storage (S5: the gocryptfs volume password is derived from it with its own context).
- **Envelopes:** one per unlock method, each `XChaCha20-Poly1305(KEK_method, DEK)` with a fresh 24-byte nonce and the envelope header as associated data. Adding or removing a method writes or deletes an envelope; the data is never re-encrypted for that.
- **KEK per method:**

| Method | KEK | State shown |
|---|---|---|
| Password | `crypto_pwhash` Argon2id13, `opslimit=3`, `memlimit=256 MiB` (libsodium "moderate"), random 16-byte salt; parameters stored | `password_protected` |
| Recovery code | 140-bit random code (28 Crockford base32 characters in 7 groups of 4, shown once; look-alike letters accepted); KEK by Argon2id, `opslimit=2`, `memlimit=64 MiB` (the code is high-entropy) | `password_protected` |
| OS keyring | 32 random bytes stored in the Secret Service (KWallet, GNOME Keyring) under the profile's attributes | `os_user_protected` |
| Phone (`nv1`) | derived from X25519(ephemeral, phone public key); only the phone can recompute it ([ADR 0005](0005-phone-profile-unlock.md)) | `phone_key_release_verified` |
| Security key | FIDO2 `hmac-secret` output treated as input keying material | `hardware_bound` (S10) |
| TPM | sealed to this machine's TPM | `hardware_bound` (optional) |
| Combined ("password + phone") | KDF over both KEKs; one envelope that needs both | both states (`password_protected`, `phone_key_release_verified`) |

- **Domain separation:** every derivation uses `crypto_generichash` (BLAKE2b) keyed with the input secret over a context string `nulavio/vault/v1/<purpose>` plus the profile id and envelope id; envelope headers are the AEAD associated data, so an envelope cannot be moved to another profile or method.
- **Key commitment:** `dek_check = BLAKE2b(key=DEK, "nulavio/vault/v1/dek-check")` lets an unlock prove it recovered the right DEK before touching data. A wrong key fails here, never as garbage data.
- **Metadata MAC:** after unlock, `BLAKE2b(key=KDF(DEK, "metadata-mac", profile_id), canonical metadata)` detects tampering (removed envelopes, changed labels or policy). A tampered vault stays locked until the user reviews its methods and accepts them (the coordinator then signs the metadata again); tampering cannot add a working method without the DEK.
- **Rollback:** `generation` counts saves. A restored older `vault.json` (for example with a revoked phone's envelope) has a valid MAC; S5 stores the generation inside the encrypted storage too, so the mismatch is detected after unlock. Until then this is a residual risk ([U-T21](../security/threat-model-unlock.md)).

### Metadata (`vault.json`, beside the encrypted storage, mode 0600)

```json
{
  "format": "nulavio-vault", "version": 1, "suite": "nv1",
  "profile_id": "…", "created": "2026-10-26T12:00:00Z",
  "dek_check": "…", "generation": 3,
  "policy": {},
  "envelopes": [
    {"id": "…", "method": "password", "label": "", "created": "…",
     "data": {"kdf": "argon2id13", "ops": 3, "mem": 268435456, "salt": "…"},
     "nonce": "…", "ct": "…"},
    {"id": "…", "method": "phone", "label": "Galaxy S24+", "created": "…",
     "data": {"phone_id": "…", "psig_pk": "…", "pkx_pk": "…", "name": "…", "eph_pk": "…"},
     "nonce": "…", "ct": "…"}
  ],
  "mac": "…"
}
```

Method data by envelope: `password` and `recovery-code` hold Argon2id parameters; `os-keyring` holds the Secret Service lookup attributes (never the key); `phone` holds the phone's public keys and the envelope's ephemeral key; `combined` holds a `password` and a `phone` part. The AEAD associated data is the canonical JSON of format, version, suite, profile id, envelope id, method and data, so editing any of them makes the envelope fail to open.

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

## Implementation (S3, 2026-10-26)

Package `launcher/nulavio_launcher/vault/` (standard-library Python plus the system libsodium through `ctypes`, decision D1):

| Module | Content |
|---|---|
| `sodium.py` | Minimal binding: XChaCha20-Poly1305-IETF, Argon2id13, keyed BLAKE2b, X25519, Ed25519, `randombytes_buf`, `sodium_memzero`, `sodium_memcmp`. Secrets are `bytearray` so they can be wiped |
| `core.py` | `Vault`: create, load (backup fallback, newer formats refused), atomic save, envelopes for password, recovery code and raw KEKs, key commitment, metadata MAC, lock. Argon2id parameters read from disk are bounded (ops 1–10, memory up to 1 GiB) so an edited file cannot stall or exhaust the machine; damaged envelopes fail with `damaged-envelope` |
| `providers.py` | OS keyring through `secret-tool`: the key goes over stdin, never argv; read back after storing |
| `phone.py` | `nv1` desktop side: identity, pairing, phone and password + phone envelopes, signed one-shot requests, response verification, revocation |
| `coordinator.py` | The unlock state machine (states of the [architecture](../architecture/vault-and-unlock.md#unlock-coordinator-states)), alternatives without automatic fallback, tampered-metadata gate, logs without secrets |

Tests: `tests/unit/test_vault.py` (60 tests, one class per mandatory test of the brief plus tampering, combined policy, keyring and logs), `tests/lib/phone_reference.py` (the phone side, the executable spec for S11), `tests/fixtures/vault-v1/` (a version-1 vault with artificial secrets that every later version must still open with password, recovery code and phone). CI installs `libsodium23` and fails rather than skips without it.

Not yet (after S3): storage encryption and real lock (done in S5, below), UI (S6), DEK rotation, security keys (S10), the phone app (S11).

## Implementation (S5, 2026-10-26): encrypted profile storage

- **Layout.** For a profile directory `P` (what the engine opens with `--profile`): `P` is the gocryptfs mount point and `P.vault/` holds `vault.json` and `cipher/` (gocryptfs, `-xchacha`: XChaCha20-Poly1305, file names encrypted). While locked, `P` is empty and **read-only (0500)**, so an engine started directly on it cannot write plaintext there (tested with the real engine); it becomes writable only for the instant of mounting, because `fusermount` requires it.
- **Key.** The volume password is `KDF(DEK, "storage/gocryptfs", profile_id)` (64 hex characters, on gocryptfs's stdin, never argv or disk). gocryptfs wraps its own master key with it; its scrypt cost is low (`-scryptn 10`) because the input is already 256 bits of key material.
- **Unlock = mount; lock = end the instance, then unmount.** `nulavio run` on a locked profile unlocks with the profile's own methods (the system keyring if the user chose it, otherwise the password from the terminal, a KDE dialog or `--password-stdin`), runs the engine as a child and locks when it exits; SIGTERM to the launcher ends the engine first. `nulavio vault unlock/lock` keep a profile open on purpose; `lock` refuses while the engine runs unless `--force`, which ends it gracefully.
- **Checks on every mount.** A mount point that is not empty (plaintext appeared while locked) is refused. Inside the volume, `.nulavio-vault/state.json` records the profile id and the vault generation: a `vault.json` older than the volume (a rolled-back key file, U-T21) or from another profile is refused. A tampered `vault.json` (MAC) is refused as in S3.
- **Crash.** If the launcher dies, the engine keeps running on the open volume; when it exits the volume stays open until `nulavio vault lock` (reported by `nulavio vault status` as "open (no engine running)"). An idle timer (`-idle`) is available for an auto-lock policy.
- **Existing profiles.** `nulavio vault encrypt (NAME | --path DIR)` moves a closed profile into a new volume, verifies by mounting, restores the original on any failure, then deletes the plaintext originals (fragments can remain on SSDs and in backups; the command says so).
- **Browser profiles (Track B).** The Shell reads two facts per profile (`NulavioVaultState.sys.mjs`): is there a `P.vault/vault.json`, and is the volume mounted. Locked profiles show "Locked" in the selector and Settings; switching, "Open link in profile" and deleting refuse with a plain message; routing a link or typed address to a locked profile shows an explanation instead of starting it. Unlocking from the browser is S6; until then `nulavio vault unlock --path DIR`.

## Implementation (S6, 2026-10-26): unlock and onboarding in the browser

- **One crypto implementation.** The browser never handles keys. The Shell (`NulavioVault.sys.mjs`, experiment API `nulavioVault`) runs `nulavio-tools/bin/nulavio vault api` (installed next to the engine by `scripts/build/make_tools.py`) with an argument list; one JSON request on stdin carries the operation and, when needed, the password or recovery code; one JSON answer comes back. Typed secrets are JavaScript strings and cannot be wiped; they live in the page and that call only.
- **Locked profile page** (`vault/unlock.html`): shown instead of a locked profile from routing (links from apps, typed addresses), the profile selector, "Open link in profile" and Settings. Password first; "Use my computer login" and "Use the recovery code" when configured; states `idle`, `unlocking`, `unlocked`, `error`, `device-unavailable`, `recovery-required`, `storage-unavailable`, `not-locked`. A held-back address is shown as text and opened only after unlock, in the unlocked profile.
- **Lock when the window closes.** Unlocking from the browser starts a small watcher (`nulavio vault autolock`) that waits for that profile's engine to start and exit, then locks; if nobody opens it within two minutes it locks too. When the engine's helpers still hold files, it waits up to a minute, then detaches the volume (lazy unmount: gone from the file system at once, open files finish closing).
- **New protected profile** (`vault/create.html`), three decisions: name and kind; how it unlocks (a password, optionally also the computer login, or only the computer login, each with one line on what it protects against); the recovery code, shown once, with two groups typed back. The profile is encrypted before anything is written to it; if encryption fails the new profile is removed rather than left unprotected.
- **Settings and selector.** Locked profiles show "Locked" and "Unlock…"; an open protected profile that is not running offers "Lock now". Deleting a protected profile requires it locked: the helper first deletes its keys (`P.vault/`), which makes whatever remains unreadable, then the browser deletes the profile.

Tests: `tests/integration/test_vault_ui.py` (7, every page state, keyboard focus, light and dark captures), `HelperApiTest` in `tests/unit/test_vault_storage.py` (the helper API, autolock).

Tests (S5): `tests/unit/test_vault_storage.py` (15, real FUSE mounts, a stand-in engine for supervision, SIGTERM and crash), `tests/integration/test_vault_profiles.py` (real engine: a visited address is in the profile while unlocked and nowhere readable after lock; a direct engine start writes nothing; Track B selector, switching and routing). CI installs `gocryptfs` and `fuse3` and requires these tests.

## Consequences

- Phone, password, recovery code and keyring are independent: losing one method does not lose the profile.
- Encryption at rest protects **locked** profiles and offline copies; it does not protect an unlocked session from same-user malware ([threat model](../security/threat-model-unlock.md)).
- Track A (distribution Firefox) gets the same Vault through the launcher; Track B integrates it with engine profiles (S5).
