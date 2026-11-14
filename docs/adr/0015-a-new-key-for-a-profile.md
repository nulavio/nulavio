# ADR 0015 — A new key for a protected profile's volume

- **Status:** Proposed (2026-11-14, by an agent, for [issue #204](https://github.com/nulavio/nulavio/issues/204)). The maintainer's word on it is recorded here when given; the implementation in the same pull request is not merged before that.
- **Related:** [ADR 0006](0006-nulavio-vault.md) (the Vault; its lifecycle already names "Rotate the DEK: new DEK, new storage, data copied; offered, never automatic"), [threat model for unlock](../security/threat-model-unlock.md) (U-T16, U-T17, U-T21), [residual risks](../security/residual-risks.md) R70, [architecture](../architecture/vault-and-unlock.md).

## Context

A protected profile's files are in one gocryptfs volume. Its key chain:

1. Each unlock method wraps the profile's DEK in an envelope in `vault.json`.
2. The volume's password is derived from the DEK.
3. gocryptfs wraps its own master key with that password in `gocryptfs.conf`, next to the encrypted files.

Removing a method, or replacing the recovery code, deletes an envelope and leaves all three as they were. So someone who kept `vault.json` from before the change and knows the secret that was valid then still gets the DEK, and with it the files as they are now, outside Nulavio (R70). The record of the change inside the volume (U-T21) only stops an old `vault.json` that was put back in place.

The cases that matter: a recovery code someone else saw, a password that leaked, a phone that was lost. "Remove this method" reads as "that secret no longer opens my profile". Until now that was true only for someone who never had a copy of the key file.

## Decision

### 1. What gets a new key: everything

A new key means a new DEK **and** a new gocryptfs volume with its own master key. The files are copied from the old volume into the new one and read back, and the old volume is deleted.

Why both:

- **A new DEK alone is not enough.** With gocryptfs's `-passwd`, the new DEK would wrap the same master key. `gocryptfs.conf` sits next to `vault.json`, so whoever kept one very likely kept the other, and the old pair still yields the master key.
- **A new volume alone is not enough.** The old `vault.json` still yields the DEK, which opens the new `gocryptfs.conf`.

What a new key does not do, and the pages say so:

- A copy of the old **encrypted files**, together with the old key file and secret, still opens what the profile held then.
- The old volume is deleted, not wiped. On an SSD, fragments may remain.

### 2. Which unlock methods carry over

The new DEK has to be wrapped again for every method, and that needs each method's key. The program has some of them at that moment and not others:

| Method | After the new key |
|---|---|
| The password or recovery code typed to authorize it | Carried: wrapped again with the same secret |
| This computer's login | Carried: a new key in the system keyring, and the old one removed from it |
| A connected phone | Carried: a new envelope from the phone's public keys. The phone is not needed and is not paired again |
| Any other password | Dropped. It can be added again afterwards |
| The recovery code, when the password was typed | Dropped. A new one is made right after, shown once and typed back, as any new recovery code (#187) |
| Password + phone (one envelope that needs both) | Dropped |

The person is told this before it starts. After it, the pages and the command line say what stopped working.

The recovery code is made after the new key, not as part of it. A code made inside it would exist before anyone had seen it, which is the problem #187 removed. In between, the profile has the method that was typed, which the person evidently has.

### 3. Offered, never automatic

This is ADR 0006's rule, kept. Removing a method stays quick and needs no free space. What changes is that the product no longer leaves the wrong impression:

- **The key file records its key's age**: when the key was made, and when a method was last removed or replaced since (`key` in `vault.json`, under the metadata MAC).
- **The methods page shows which of the two states the profile is in**, and offers "Criar nova chave".
- **A removal's confirmation and result say what a removal leaves behind.** So does `nulavio vault remove-method`.
- **A key file from before this ADR has no such record.** The pages then say what is not known ("if a method was ever removed…"), instead of claiming either state.

### 4. The profile must be closed

Locked, with no engine on it. The files are copied, and a copy of files in use would not be the profile.

### 5. An interruption never leaves a profile without a way in

The new volume is built under `P.vault/rekey/`, beside the old one, which is only read (mounted read-only).

- **Until the copy is whole, checked and on disk, nothing outside `rekey/` has changed.** An interruption there is undone: `rekey/` is removed, and the profile is as it was, its methods included.
- **Then a marker is written, durably.** From there it is only ever finished, never undone: the new volume and key file take the old ones' place in steps that can each be repeated, and an interruption is finished from where it stopped. An error after the marker is reported as such ("the new key was made; putting it in place did not finish"), not as "nothing was changed".
- **Either is done the next time the profile is used** (any command or page that touches it), under the profile's state lock. An unlock, and a change to the unlock methods, do it first under that same lock, so the old volume is never opened while a new one waits to take its place.
- **The switch never happens under a volume that is still served.** It renames and deletes the profile's encrypted directory, so it waits until nothing has that directory mounted and no gocryptfs process still holds it (a volume detached with files open is gone from the mount table and still written to).

So after any interruption the profile opens with a method the person has: the ones from before, or the one that was typed. The typed method is carried or nothing changes: if it cannot be wrapped again, the new key is not made.

The copy is made and checked through open handles on the two volumes, not through the directories they are mounted on: a volume detached under the process is still the one read and written. The source must hold the profile's own record (`.nulavio-vault/state.json`). Both sides are read back: names, kinds, sizes and SHA-256 of every file. Not compared: permissions and times (copied, not checked), hard links (copied as separate files) and extended attributes.

What an interruption can leave behind: a new key in the system keyring that wraps nothing (the new key was undone), or the old one (it was finished by a later use, which does not know the keyring). Neither opens anything.

### 6. Cost

Measured on the reference laptop (NVMe, LUKS), 256 MiB in 2 001 files, while a test suite ran:

- copying between two gocryptfs volumes: 1.9 s (135 MiB/s);
- reading both sides back: 1.1 s.

That is roughly 10 to 15 seconds per GiB. It needs free space for a second copy while it runs, and refuses to start without it.

While it runs, the files are readable at `P.vault/rekey/` by the person's own processes, as during any change to a locked profile (U-T21).

## Alternatives

- **`gocryptfs -passwd` with a new DEK.** Seconds instead of minutes, no free space. Rejected: it does not cover the case in point 1, and the product would again claim more than it does.
- **Envelopes that hold a key pair** (the DEK sealed to each method's public key, the private key wrapped by the method). A new DEK could then be sealed for every method without any of their secrets, so nothing would be dropped. Not chosen now: it is a new envelope format, and an old envelope can only be converted when its own method is used, so both formats would live side by side for as long as a profile has a method nobody uses. Worth its own ADR if dropped methods turn out to be a real cost.
- **Always re-key on removal.** Rejected by ADR 0006 already. It would also make removing a lost phone wait on free space and minutes of copying, at the moment a person wants it gone at once.
- **Asking for every other secret at re-key time,** so that everything carries over. Rejected: a secret that is not at hand is often the reason for the change.

## Consequences

- R70's first half (an old key file with an old secret) has an end the person can reach. Its second half is unchanged until then, and for profiles nobody re-keys.
- U-T21's record inside the volume stays: it is what stops an old key file between a removal and a new key.
- The launcher's key file gains one field. Older launchers ignore it and keep its MAC valid, because they sign the whole file as they found it.
- A profile whose other passwords were dropped needs them added again. A profile re-keyed with its password needs a new recovery code written down.

## Verification

`tests/unit/test_vault_storage.py` `RekeyTest`, `tests/unit/test_vault.py` `KeyAgeTest`, `tests/integration/test_vault_ui.py` test 19:

- Before the new key, the removed password reads the files with the key file from before, using gocryptfs alone. After it, that key file reads nothing with any secret: by itself, with the `gocryptfs.conf` of then, or put back in place under Nulavio.
- Every file is as it was. The typed method opens the profile; the dropped ones do not.
- The process is killed before the copy is whole, then at each step of the switch. The next use of the profile undoes or finishes it, and the profile opens.
- From the review of #275: a volume detached during the copy is still the one copied; an unlock that had read the key file before the interruption does not open the old volume; the switch waits while the volume is mounted; a switch that fails says the new key was made; leftovers of an undone one do not stop the profile; the typed method is carried or nothing changes.
- A phone's envelope is carried without the phone, and the phone then unlocks the new key file.
