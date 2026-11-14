# launcher/: the `nulavio` command (Python, standard library only)

Read the root [AGENTS.md](../AGENTS.md) first; its rules apply here and are not repeated.

## What is here

`nulavio_launcher/`: profiles and paths, starting the engine, `run --confined`, Connect, the Guard's audit, `doctor`; `vault/`, the protected profiles and their unlock methods (password, recovery code, phone); `ai/`, the AI Bridge that lets an agent use a profile under the user's grants.

## Rules that apply here

- Standard library only; a new runtime dependency needs an ADR (I5).
- Secrets travel on standard input or in 0600 files, never in argv, a child's environment, logs, URLs or the clipboard (I3). Processes start with argument lists and Python helpers with `-I`; no shell (I4).
- Directories 0700, files 0600, atomic writes; symlinks and paths owned by others are refused; profiles live under XDG (I9). The launcher never forwards arbitrary engine flags or remote-control flags (I1).
- `vault/` (I8): cryptography only through libsodium (`vault/sodium.py`) and gocryptfs, never a primitive, KDF, MAC, random source or password storage of our own. Fresh nonces, associated data covering the header, constant-time comparison, secrets wiped, Argon2id parameters bounded when read from disk, the data key never in clear on disk or in a log, a locked mount point stays 0500, format and protocol changes versioned. A change to the unlock methods is recorded inside the volume under the profile's state lock (`Container.recording`), so a key file put back from before is refused and two changes cannot overwrite each other.
- `ai/` (I7): grants come only from the user's registry, read again on every call; no tool reads or edits policy; page content is untrusted and never reaches the policy decision; tokens are stored only as SHA-256 and never logged; every address is classified before navigation (loopback, private, link-local and `.local` need `local_resources`), and checked again before a tool reads or acts on a tab; a stopped, revoked, paused or re-keyed session gets no tool but `session_state`; forms a page sends by itself are held until `submit_forms` allows them; locked profiles are refused; the audit keeps metadata only.

Documents: [vault and unlock](../docs/architecture/vault-and-unlock.md), [AI Bridge](../docs/architecture/ai-bridge.md), [trust boundaries](../docs/architecture/trust-boundaries.md), the [threat model](../docs/security/threat-model.md), [unlock threat model](../docs/security/threat-model-unlock.md) and [AI threat model](../docs/security/threat-model-ai.md), ADRs [0003](../docs/adr/0003-nulavio-profiles-and-routing.md), [0005](../docs/adr/0005-phone-profile-unlock.md), [0006](../docs/adr/0006-nulavio-vault.md) and [0007](../docs/adr/0007-ai-bridge.md). A suspected vulnerability: [nulavio-private-security-fix](../.agents/skills/nulavio-private-security-fix/SKILL.md) before writing anything about it.

## Checks

- `python3 -I tests/run.py unit` (here mostly `test_profile_and_paths.py`, `test_vault.py`, `test_vault_storage.py`, `test_phone_link.py`, `test_ai_bridge.py`, `test_confine.py`, `test_connect.py`). CI sets `NULAVIO_REQUIRE_SODIUM=1` and `NULAVIO_REQUIRE_GOCRYPTFS=1`: install libsodium and gocryptfs so the Vault tests run instead of skipping.
- The integration tests for what reaches the engine (`tests/integration/test_vault_ui.py`, `test_ai_bridge.py`, `test_confined.py`, …), as [nulavio-engine-verification](../.agents/skills/nulavio-engine-verification/SKILL.md) says.

## Not here

The browser pages that call the launcher (`browser/shell/vault/`, `browser/shell/ai/`) are in `browser/`; the phone's side of the unlock protocol is in `android/`.
