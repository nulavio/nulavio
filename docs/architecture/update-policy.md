# Update and security-patch policy

## Principles

- Security updates are never disabled to simplify development or testing.
- No silent downgrades. The engine's profile-downgrade protection stays on (the launcher removes `MOZ_ALLOW_DOWNGRADE`).
- Every artefact Nulavio pins has a verifiable identity: a GPG key fingerprint, or a SHA-256 plus a Mozilla signature.
- Pins other than the engine (actions, ruff, Gradle and the Companion's libraries, base images, extensions) are kept current by Dependabot and checked daily for known vulnerabilities: [dependency updates](../security/dependency-updates.md).

## Pinned dependencies

- Dependabot (`.github/dependabot.yml`) opens grouped pull requests: actions weekly on Wednesdays with a 7-day cooldown; ruff, Gradle and the base-image digests monthly. Distribution upgrades (Fedora 45, Ubuntu 27.04) are product decisions and are not proposed.
- Nothing merges automatically. A pull request is merged only with green CI, after a person read the diff; without branch protection this rule is kept by hand.
- Gradle pull requests fail CI until a maintainer regenerates `android/gradle/verification-metadata.xml` and the lockfiles locally and reviews them with `scripts/upstream/review_gradle_verification.py`. CI or a bot never writes that file.
- A security fix does not wait for these schedules: `scripts/release/watch_dependencies.py` fails the daily `upstream` run on a known vulnerability without a dated exception (`docs/security/vulnerability-exceptions.json`), and the dependency is updated that day.

## Track A (preview)

| Component | Channel | Who acts | Nulavio's job |
|---|---|---|---|
| Engine (Firefox) | Distribution package (`dnf upgrade` on Fedora) | Distribution maintainers | `doctor` shows the package; the launcher refuses engines below `MIN_ENGINE_MAJOR` (140) |
| Language pack | Same package | Distribution | Launcher refreshes the profile copy on change |
| Extensions | AMO auto-update (signed) | Extension authors / AMO | Lock pins only the first install; refresh with review |
| Launcher | `git pull` | User | Signed releases in Phase 6 |

## Track B (Nulavio build) — targets

| Event | Target |
|---|---|
| Mozilla security release (critical/high MFSA) | Nulavio build published **≤ 72 h** after Mozilla's release (stretch: 24 h) |
| Regular release (every 4 weeks) | ≤ 7 days |
| Chemspill (out-of-band fix) | Same as critical |
| Missed SLA twice in a row | Reversal criterion 2 in [ADR 0001](../adr/0001-engine-selection.md) |

### Process

1. Watch Mozilla security advisories (MFSA) and release tags.
2. Verify the source release: `scripts/upstream/verify_firefox_release.py <version>` checks `SHA256SUMS` against the **pinned** Mozilla Software Releases key (`14F2 6682 D091 6CDD 81E3 7B6D 61B7 B526 D98F 0353`) and prints the tarball hash to pin.
3. Apply the patch stack (`browser/patches/series`, applied idempotently by `scripts/build/apply_patches.py`). Each patch has an owner, a reason and an upstreaming plan; the unit tests enforce this and cap the stack at about 10 patches.
4. Build in a clean container. Run unit and integration tests plus the provider certification smoke tests.
5. Sign packages (RPM GPG; provenance attestation planned). Publish. Record in the security changelog.

### Key rotation

If Mozilla rotates the primary release key, update the pinned fingerprint only after confirming it through two independent channels (Mozilla's KEY file plus a Mozilla blog/announcement or keyserver history). Then record it in this file.

### Automation (S19)

- `scripts/release/watch_upstream.py` compares `browser/build/engine.json` with Mozilla's public release history and states the deadline (72 hours from the first newer release; every release can carry security fixes, so the stricter target is used). The `upstream` workflow runs it daily and fails when the deadline has passed, so the maintainers get GitHub's failure notice.
- `scripts/release/rehearse_release.sh <version>` runs the whole path and times each step: Mozilla's signed checksums, the build, unit and integration tests, RPM and .deb with their clean-container checks, the signed-repository check (throwaway key), SBOMs. First full rehearsal (2026-10-27, Firefox 158.0.1, incremental build): **14 minutes**, every step passed ([report](../research/evidence/release-rehearsal-2026-10-27.md)). For a new Firefox release the build is a full one (about 52 minutes measured), so about 70 minutes from Mozilla's release to checked packages, against the 72-hour target. Not rehearsed: signing with the release key and publishing.
- [Security changelog](../security/changelog.md): one entry per published build.

## Base branch choice (open)

Recommendation: follow **Release**. Re-evaluate in favour of ESR if the non-branding patch stack exceeds about 10 patches or a rebase takes more than one working day.
