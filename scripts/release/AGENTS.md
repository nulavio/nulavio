# scripts/release/: building, signing and publishing releases

Read the root [AGENTS.md](../../AGENTS.md) first; its rules apply here and are not repeated.

## What is here

The scripts `.github/workflows/release.yml` runs: the rehearsal (`rehearse_release.sh`: build, tests, RPM, `.deb`, SBOMs, `manifest.json`), the check of a rehearsal (`release_manifest.py verify`), signing through AWS KMS (`openpgp_sign.py`, `sign_repo.sh`, `sign_apt_repo.sh`), staging and upload (`publish_release.sh`, `upload_repo.sh`), the check after upload (`check_published.sh`), release notes and metadata (`release_notes.py`, `release_metadata.py`), the Flatpak manifest (`flatpak_manifest.py`), and the engine-update tools (`bump_engine.py`, `watch_upstream.py`, `upstream_issue.py`, `mfsa.py`).

## Rules that apply here

- Nothing is published unsigned or signed from an unapproved run: signing happens only in the `release` environment, after the maintainer's approval, through the role and key policies in `ci/aws/`. The key never reaches CI, a log or the disk.
- Every download is pinned by version and by hash or signature and verified before use; no `curl | sh`, no verification turned off (I5). Shell scripts quote every expansion; processes start with argument lists (I4); secrets only on standard input or in 0600 files (I3).
- A protection a script has (a refusal, a signature check, a comparison) is not removed or made non-fatal; `tests/unit/` holds a test for each one.
- Releasing is not merging: an agent never runs the release workflow's publish step, approves the `release` environment, creates a tag or publishes a draft.

Documents: [build](../../docs/architecture/build.md) ("Packages", "Signing in CI through AWS KMS", "Release workflow", "Publishing a release"), [update policy](../../docs/architecture/update-policy.md), CONTRIBUTING's [Release automation](../../CONTRIBUTING.md#release-automation), [trust boundaries](../../docs/architecture/trust-boundaries.md) TB18 and TB19, [residual risks](../../docs/security/residual-risks.md) R57 to R62. Every change here gets the second, independent review ([pull requests](../../docs/process/pull-requests.md#review-and-merging)).

## Checks

- `python3 -I tests/run.py unit` (here mostly `test_release_*.py`, `test_openpgp_sign.py`, `test_kms_import_key.py`, `test_track_b.py`, `test_sbom.py`).
- End to end without AWS: `scripts/release/test_kms_signing.sh`, `test_signed_repo.sh` and `test_apt_repo.sh` (podman, clean containers).

## Not here

The workflows are in `.github/workflows/`; the build scripts the rehearsal calls are in `scripts/build/`; the AWS policies are in `ci/aws/`; packaging files are in `packaging/`.
