# ADR 0014 — The Companion's signing key: its own key in AWS KMS, signed in the release workflow

- **Status:** Proposed (2026-11-14). The maintainer decided on 2026-11-13 that releases carry the Companion's APK ([#205](https://github.com/nulavio/nulavio/issues/205)); this record proposes where its key lives, how it signs and what F-Droid publishes. Accepting it is the maintainer's ([GOVERNANCE.md](../../GOVERNANCE.md)); creating the key is too (an AWS change).
- **Related:** [ADR 0005](0005-phone-profile-unlock.md) (phone unlock, its release-order rule), [build](../architecture/build.md#publishing-a-release), [trust boundaries](../architecture/trust-boundaries.md) TB18, [residual risks](../security/residual-risks.md) R58 and R60, [#207](https://github.com/nulavio/nulavio/issues/207) (F-Droid again from 2027-01-27), [#227](https://github.com/nulavio/nulavio/issues/227) (the signed APK on the real phone).

## Context

The browser has offered to connect a phone since 160.0-0.3, and its pairing page sends people to F-Droid for Nulavio Companion. F-Droid closed the inclusion request on 2026-11-11 under its three-month rule, so until at least 2027-01-27 an APK attached to Nulavio's releases is the only official way to get the app. CI builds that APK reproducibly but unsigned, and Android installs only signed APKs.

An Android app's signing certificate is its identity for good. Every update must be signed by the same key (or by a successor the old key vouched for, APK Signature Scheme v3 rotation, which also needs the old key). A lost key means every installed copy must be removed and the app installed again; for the Companion that also loses the phone's paired computers and keys, so every protected profile would need pairing again. A stolen key means someone else can ship an update that installed copies accept.

The package key moved to AWS KMS on 2026-11-11 for the same reason a signing key should: CI signs after the maintainer's approval and never holds the key ([TB18](../architecture/trust-boundaries.md)); the original stays offline for recovery and revocation ([R60](../security/residual-risks.md)).

## Decision (proposed)

1. **A key for the app only.** RSA 4096, not the package key: the two are used by different verifiers (rpm, dnf and apt; Android), are replaced on different schedules (the package key expires in 2028, an app key cannot simply expire) and should not fall together. Its self-signed certificate (subject `CN=Nulavio Companion, O=Nulavio`, no expiry: Android ignores the dates) is made once and committed; its SHA-256 is the fingerprint people and F-Droid check.
2. **Held like the package key.** Generated on the maintainer's machine in a new directory, backed up offline next to the package key, imported into KMS (`alias/nulavio-companion`, `SIGN_VERIFY`, origin `EXTERNAL`, no expiry), then the working copy deleted. The key policy has the package key's shape: only the release signing role and the account's administrator SSO roles may sign, only with `RSASSA_PKCS1_V1_5_SHA_256`. The role `nulavio-release-signing` gets Sign on this key as well; it is the same `release` environment behind the same approval, so a second role would add no barrier.
3. **Signed in the release workflow, by a small signer of our own.** [`scripts/release/apk_sign.py`](../../scripts/release/apk_sign.py) builds the APK Signing Block (v2 and v3 signers, RSASSA-PKCS1-v1_5 with SHA-256) and asks KMS only for the RSA operation over digests, as `openpgp_sign.py` does for the packages: standard library only, no JCA provider to vet. It checks that KMS holds the certificate's key and that every signature verifies before it writes anything, and it only inserts the block, so the signed APK is the unsigned build plus its signature. `apksigner verify` is the check, in the unit tests and in the release. In the `publish` job: the APK is built from the `companion-v*` tag the release names, compared with a second build, signed, verified with `apksigner`, listed in `SHA256SUMS` and its signature, attested, and attached as `nulavio-companion-<version>.apk` with its SBOM.
4. **One signature everywhere.** When F-Droid takes the app (#207), the recipe asks it to publish our signed APK: a reproducible build checked against the APK on the release (`Binaries:` and `AllowedAPKSigningKeys:` with the certificate's SHA-256). F-Droid then ships the same bytes, and a copy installed from either place updates from the other. If F-Droid signs with its own key instead, the two installs cannot replace each other, and the pages say so.
5. **The release-order rule holds again.** The pairing page and the site point to the release's APK (and to F-Droid once it is there), with the fingerprint. Once the first release carries the APK, a release that offers phone pairing without a signed APK is refused by the release scripts, as a rehearsal without its `.deb` is today. Until then the pairing page does not name a place the app is not.

## Alternatives

| | Recommended: own key, imported into KMS, offline backup | Key generated inside KMS, no copy anywhere | Keystore file on the maintainer's machine |
|---|---|---|---|
| Theft | Only through KMS (approval, CloudTrail) or the offline backup | Only through KMS | Anyone who gets the file and its password; signing happens on a laptop |
| Loss | The backup restores it into any account | Losing the AWS account or the key loses the app's identity: everyone reinstalls and pairs again | The file's own backups |
| Signing | In CI after approval, like the packages | Same | By hand, outside the attested workflow |

A third-party JCA provider for KMS with `apksigner` was set aside: a new dependency on the signing path that would need its own review and pinning, for what about 300 lines of standard-library code do and `apksigner` checks.

## Consequences

- The maintainer creates and imports the key, commits the certificate and publishes its fingerprint (the keys page, `SECURITY.md`); the steps go with the pull request that wires the workflow.
- The offline backup is now two keys. Its loss would cost the app's identity; its theft, the ability to sign updates. The same care as the package key's.
- Rotation (a successor key vouched for by v3) is not built. It needs the old key, which the backup keeps.
- What is not verified yet: that the Companion signed this way installs and updates on a real phone. That is #227, on the first release that carries it.
