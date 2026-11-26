# Independent review of the Vault and the release chain: scope packet

A review of everything Nulavio ships, by AI models, was done separately in November 2026: [full review](full-review-2026-11.md) (#454).

Status: prepared 2026-11-14 for #224, not yet sent. The reviewer and the terms are the maintainer's to choose (an outside engagement); nothing here is agreed with anyone yet. This page is what the reviewer receives, together with a commit of this repository.

The [scope of 1.0](../product/release-criteria.md#scope-of-10-decided-2026-11-04) asks for "an independent review of the Vault and of the release chain with its findings fixed or recorded" (decision D11 in the [execution plan](../product/execution-plan.md): the audit is limited to those two areas). Every pull request gets a review of its own, and the riskier ones a second, independent one ([pull requests](../process/pull-requests.md#review-and-merging)), but those are coding agents reading one change at a time. Nobody outside the project has read either area as a whole.

## What Nulavio is, in two lines

A desktop browser for Linux built from Mozilla Firefox, with its own interface, defaults and a launcher (`nulavio`, Python, standard library only). Two parts of it hold keys that a mistake would expose: the **Vault**, which encrypts browser profiles at rest, and the **release chain**, which builds, signs and publishes the packages people install with `dnf`, `apt` and Flatpak.

## The commit to review

The maintainer names one commit of `main` when the engagement starts, and the review reads that commit. The Vault's key handling that 1.0 ships landed before 2026-11-14: a new key for a profile (#204, [ADR 0015](../adr/0015-a-new-key-for-a-profile.md)), replacing the recovery code (#187), and reporting a change that was saved but not recorded (#177). A finding against a later commit is welcome, but the report says which commit each finding was read on.

To list what is in scope at that commit:

```sh
git ls-files launcher/nulavio_launcher/vault/ browser/shell/vault/ browser/shell/chooser/ \
  browser/shell/modules/NulavioVault.sys.mjs browser/shell/modules/NulavioVaultState.sys.mjs \
  browser/patches/0011-profiles-unlock-a-protected-profile-in-the-chooser.patch \
  .github/workflows/release.yml .github/workflows/repeatable.yml .github/workflows/release-signing-check.yml \
  .github/workflows/release-metadata.yml .github/workflows/upstream.yml \
  scripts/release/ ci/aws/ packaging/ site/rpm/ site/apt/ browser/build/engine.json scripts/upstream/
```

## Area 1: the Vault

A protected profile is a [gocryptfs](https://github.com/rfjakob/gocryptfs) volume keyed from a data encryption key (DEK). The DEK is kept only in envelopes, one per unlock method (password through Argon2id, recovery code, the system keyring, a paired Android phone over the `nv1` protocol). The metadata file `vault.json` carries the envelopes, a MAC and a generation counter mirrored inside the volume.

| Read first | Why |
|---|---|
| [ADR 0006](../adr/0006-nulavio-vault.md), [ADR 0005](../adr/0005-phone-profile-unlock.md), [ADR 0015](../adr/0015-a-new-key-for-a-profile.md) | What was decided and what was rejected |
| [Vault and unlock architecture](../architecture/vault-and-unlock.md) | Components, trust boundaries UB1–UB5, the key flow, `nv1`, the coordinator's states, the effective protection matrix |
| [Unlock threat model](threat-model-unlock.md) | Scenarios U-T1 to U-T33, each with its controls, limits and the test that holds it |
| [Residual risks](residual-risks.md) R11, R18, R30, R31, R32, R48, R49, R70 | What the project already accepts or knows is open |

| Code | Lines (2026-11-14) | What it does |
|---|---|---|
| `launcher/nulavio_launcher/vault/core.py` | 535 | Envelopes, KDFs, the metadata MAC, the generation |
| `launcher/nulavio_launcher/vault/storage.py` | 956 | The gocryptfs volume: create, mount, unmount, re-key, the record inside the volume, locks |
| `launcher/nulavio_launcher/vault/cli.py` | 723 | `nulavio vault …` and the helper the browser's pages call over stdin/stdout |
| `launcher/nulavio_launcher/vault/sodium.py` | 247 | The libsodium binding (ctypes), memory wiping |
| `launcher/nulavio_launcher/vault/phone.py`, `phone_session.py`, `link.py`, `coordinator.py` | 1,259 | The desktop side of `nv1`: pairing, signed requests, one-time session keys, mDNS and the local link |
| `launcher/nulavio_launcher/vault/profiles.py`, `providers.py` | 378 | Which profiles are protected; the keyring provider |
| `browser/shell/vault/`, `browser/shell/modules/NulavioVault*.sys.mjs` | — | The browser's unlock, methods and phone pages, and the module that talks to the helper |
| `browser/shell/chooser/`, patch 0011 | — | Unlocking a protected profile in the engine's profile chooser (#43) |

Questions the project would most like answered:

1. Can someone holding a copy of the profile's files (a stolen disk, a backup, a synced folder) recover the DEK without a valid secret, given the KDF parameters and the envelope format?
2. Do a removed method, a replaced recovery code and a new key ([ADR 0015](../adr/0015-a-new-key-for-a-profile.md)) end what they claim to end? R70 says what the project believes is left.
3. Can the metadata be rolled back or edited (U-T18, U-T21) to restore a removed method or to downgrade a combined policy?
4. Is there a path where a failure (a full disk, a killed process, a volume that cannot be mounted) leaves plaintext on disk, leaves the volume open without saying so, or loses the profile?
5. The desktop side of `nv1`: pairing (U-T6, U-T7), replay (U-T8), binding to one desktop (U-T31), expiry (U-T20).
6. The helper's boundary with the browser (U-T27, U-T32): secrets only on stdin, never in argv, logs or files; the fixed words that pass back to the page.

Out of scope for this area: malware running as the same user while the profile is unlocked (U-T3, stated as out of reach), root, the Android Companion app itself (it has its own checks; the review covers the desktop side of `nv1` only), FIDO2 unlock (not in 1.0).

## Area 2: the release chain

The packages are built on Blacksmith runners by `release.yml`, checked against a rehearsal manifest, and signed in a separate job that runs only after the maintainer approves the `release` environment. The OpenPGP release key and the Companion's APK key are used through AWS KMS: the job gets a short-lived role through GitHub's OIDC token, and the key material in KMS is not exportable. Both keys were made outside KMS, on the maintainer's machine, and imported (origin `EXTERNAL`; `make_release_key.sh`, `kms_import_key.py`); an offline backup of each, and the release key's revocation certificate, are kept by the maintainer ([build](../architecture/build.md), [ADR 0014](../adr/0014-companion-signing-key.md), R60). The making and import scripts are in scope; the backups themselves, and how they are kept, are the maintainer's and outside what the reviewer can read.

| Read first | Why |
|---|---|
| [Build](../architecture/build.md): "Packages", "Signing in CI through AWS KMS", "Release workflow", "Flatpak (Flathub)", "Repeatable builds", "Publishing a release" | How a release is made |
| [Update policy](../architecture/update-policy.md) | The times the chain has to meet |
| [Trust boundaries](../architecture/trust-boundaries.md) TB18, TB19, TB21 | Who is trusted at each step |
| [ADR 0014](../adr/0014-companion-signing-key.md) | The Companion's signing key |
| [Residual risks](residual-risks.md) R51, R53, R57, R58, R60, R61, R62, R67 (R12 is the old preview's, before signed releases) | What the project already accepts or knows is open |
| [`scripts/release/AGENTS.md`](../../scripts/release/AGENTS.md) | The rules the scripts keep (no unsigned publish, pinned downloads, no protection made non-fatal) |

| Code | What it does |
|---|---|
| `.github/workflows/release.yml` | Jobs `build`, `flatpak`, `flatpak-check`, `companion`, `sign`, `publish`; the `release` and `release-upload` environments, OIDC, attestations |
| `.github/workflows/repeatable.yml`, `scripts/release/compare_builds.py` | A second build to compare with the release |
| `.github/workflows/release-signing-check.yml`, `scripts/release/test_kms_signing.sh` | A manual check that KMS signs and the result verifies |
| `scripts/release/rehearse_release.sh`, `release_manifest.py` | The rehearsal and the manifest `sign` checks before it signs |
| `scripts/release/openpgp_sign.py`, `sign_repo.sh`, `sign_apt_repo.sh` | OpenPGP signatures made through KMS: RPMs, the dnf and APT repository metadata |
| `scripts/release/apk_sign.py`, `sign_companion.sh` | The Companion's APK signature (v2/v3 scheme) through KMS |
| `scripts/release/publish_release.sh`, `upload_repo.sh`, `check_published.sh` | Staging, upload to the package bucket, the check after upload |
| `scripts/release/kms_setup.sh`, `kms_import_key.py`, `make_release_key.sh`, `ci/aws/*.json` | Creating and importing the keys; the key and role policies |
| `scripts/release/flatpak_manifest.py`, `check_flatpak.sh` | The Flatpak for Flathub: its manifest and the checks of its build (no bundle is released since #467) |
| `packaging/`, `site/rpm/nulavio.repo`, `site/apt/nulavio.sources` | The packages, and the repository files people install, which turn signature checks on |

Questions the project would most like answered:

1. Can anything other than an approved job in the `release` environment on `main` (`release.yml`, and `release-signing-check.yml`, which signs a test file there) get a signature from either key (R60)? Read the trust policy, the role policy and the key policy together with the workflow's triggers and permissions.
2. Can a pull request, a branch, a cache, an artifact or a dependency download put bytes into what gets signed? What does the manifest bind, and what does `sign` check before it signs?
3. Do the signatures and repository files make `dnf`, `apt` and Flatpak refuse a tampered or older package (R57 says the metadata has no expiry)?
4. Are the scripts' refusals really fatal, and is there a path that publishes unsigned or partly signed?
5. The APK signer is the project's own code (`apk_sign.py`): is its output what Android's verifier checks, and could a crafted input make it sign something other than the built APK?
6. Releases 160.0-0.4 to 0.6 carried a Flatpak bundle, built in a job without OIDC and with no attestation; what bound it to the release was its line in the signed `SHA256SUMS`, and `flatpak install` of a bundle does not check the project's signature. Since #467 releases carry none (the Flatpak waits for Flathub), and the `flatpak` jobs only check Flathub's build ([build](../architecture/build.md), "Flatpak (Flathub)"). Can anything those jobs make still reach what `sign` signs or `publish` uploads?

Out of scope for this area: the engine's own source (Mozilla's), Blacksmith's and GitHub's infrastructure (R61, accepted), and the maintainer's own machine (where the offline key backups are). Also in scope, as "updates" in D11: how a new Firefox release is noticed and pinned (`upstream.yml`, `scripts/upstream/`, `browser/build/engine.json`) and the release metadata pull request (`release-metadata.yml`, TB21).

## What the project already did

- An internal audit of 160.0-0.1 on 2026-11-10 by a coding agent: its findings and fixes are in the [security changelog](changelog.md) under 160.0-0.2 (V2 and V4 to V8 for the Vault; V3 became R59, resolved in #48; R1, R2 and R5 for the release chain, whose R3 and R4 became the residual risks R57 and R58). Not independent: the same kind of agent wrote the code.
- Scans and manual findings on the [LESIS](code-scanning.md#lesis-external-supporter) platform (2026-11-13), whose retest led to R70.
- CI on every pull request: gitleaks, Nulavio's Opengrep rules, ShellCheck, zizmor and actionlint for the workflows, CodeQL; OpenSSF Scorecard on `main`, weekly ([code scanning](code-scanning.md)).
- The unit suites `tests/unit/test_vault.py`, `test_vault_storage.py`, `test_release_*.py`, `test_apk_sign.py`, `test_openpgp_sign.py`, `test_kms_import_key.py` and `test_signatures.py`, and the integration suites `test_vault_ui.py`, `test_vault_profiles.py` and `test_profile_chooser.py`.

## Running it

- The unit tests: `python3 -I tests/run.py unit`, with Python 3.11 or later, gocryptfs, libsodium, `gpg`, `openssl`, Python's `cryptography`, Android's `apksigner`, and Node, which runs the Shell modules' behavioural tests. Without one of them, the tests that need it are skipped, not failed: set `NULAVIO_REQUIRE_SODIUM=1`, `NULAVIO_REQUIRE_GOCRYPTFS=1`, `NULAVIO_REQUIRE_APKSIGNER=1` and `NULAVIO_REQUIRE_NODE=1` to make those skips failures, as CI does (question 5 of the release chain rests on `apksigner`). Nothing in them touches a real profile or a real key.
- The signing chain end to end, in containers (podman): `scripts/release/test_kms_signing.sh` and `test_apt_repo.sh` sign through a stand-in for KMS, as releases do; `test_signed_repo.sh <packages-dir>` signs through a gpg-agent instead.
- The integration suites need a Nulavio build or the released package, named by `NULAVIO_ENGINE`; without it the tests that need the build are skipped, not failed ([CONTRIBUTING](../../CONTRIBUTING.md)).
- The reviewer gets no access to the AWS account, the `release` environment or the package bucket. A question that needs them goes to the maintainer.

## Reporting

- A vulnerability goes through a private security advisory ([SECURITY.md](../../SECURITY.md)), never a public issue, and is fixed in the advisory's private fork ([private work](../process/private-work.md)).
- Each finding names the commit, the file and line, a scenario and its preconditions, and a severity.
- The project then fixes each finding, or records it in [residual risks](residual-risks.md) with the maintainer's acceptance. The review's summary, or a link to the published report, goes into the [release criteria](../product/release-criteria.md).

## The maintainer's part

1. Choose the reviewer and agree the terms: scope (this page), the commit, the time, the cost, whether the report is published and when (after the fixes are released).
2. Send this page and the commit; answer the reviewer's questions about the AWS account and the `release` environment.
3. Accept or reject each finding that is not fixed (an accepted risk is the maintainer's decision, [GOVERNANCE](../../GOVERNANCE.md)).
