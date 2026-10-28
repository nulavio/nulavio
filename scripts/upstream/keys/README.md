# Pinned release keys

The signing keys that the verification scripts trust. They are kept here, never fetched from the server that serves the signed files: a server that could swap a signed file could also swap the key file next to it, for example to drop a revocation.

| File | Key | Allowed signing keys | Copied from | Checked |
|---|---|---|---|---|
| `mozilla-release-signing.asc` | Mozilla Software Releases, primary `14F2 6682 D091 6CDD 81E3 7B6D 61B7 B526 D98F 0353` | subkey `827E 6586 0867 9618 CD34 9F93 678E 455D 7676 7AA3` (created 2026-08-06, expires 2028-08-05) | `https://archive.mozilla.org/pub/firefox/releases/159.0/KEY` (the same file as for 158.0.1) | 2026-10-28: primary fingerprint matches the one pinned since 2026-10-24; subkey `09BE ED63 … C1A2 0256` revoked by Mozilla on 2026-08-06 ("We no longer trust this key"), five older subkeys expired |
| `claude-code-release-signing.asc` | Anthropic Claude Code Release Signing, primary `31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE` | the primary itself | `https://downloads.claude.ai/keys/claude-code.asc`; fingerprint published at `https://code.claude.com/docs/en/setup` | 2026-10-28: identical to the file in `tests/fixtures/claude-code/` |

## When a check fails because of a new signing key

`verify_firefox_release.py` names the subkey it does not know. Before adding it to `SIGNING_SUBKEYS`:

1. Download the release's `KEY` into a new, empty directory and import it into a throwaway `GNUPGHOME`.
2. Confirm the primary fingerprint is still the pinned one and the new subkey is certified by it (`gpg --list-sigs <subkey>`).
3. Confirm the subkey through a second channel (a Mozilla announcement, the KEY file of an older release directory, or a keyserver's history).
4. Replace `mozilla-release-signing.asc` with that `KEY`, keeping every revocation it had, add the subkey to `SIGNING_SUBKEYS`, and update this table. A revoked or expired subkey is never added back.

A rotation of the primary key follows [key rotation](../../../docs/architecture/update-policy.md#key-rotation).
