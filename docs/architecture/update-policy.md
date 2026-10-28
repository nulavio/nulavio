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

| Event | Deadline (the commitment) | Target |
|---|---|---|
| Mozilla security release (critical/high MFSA) | Nulavio build published **≤ 72 h** after Mozilla's release | 24 h (urgent, rules below) |
| Chemspill (out-of-band fix) | Same as critical | 24 h (urgent) |
| Regular release (a major every 2 weeks since Firefox 155, dot releases about weekly) | ≤ 7 days | 24 h when urgent by the rules below, else 72 h |
| Missed SLA twice in a row | Reversal criterion 2 in [ADR 0001](../adr/0001-engine-selection.md) | |

The tools hold every Release-channel release (major or dot) to the 72-hour deadline, because any release can carry security fixes: "overdue" and the failing `upstream` job mean 72 hours have passed since Mozilla published it. The clock starts at Mozilla's publication: the time of the product-details commit that lists the release, or the start of that day (UTC) when the time is unknown, which is stricter.

### Urgency

A release is **urgent** (24-hour target) when Mozilla's advisory for it ([MFSA](https://www.mozilla.org/security/advisories/), read by `scripts/release/mfsa.py`) shows any of:

- highest impact critical or high;
- a sandbox escape;
- exploitation in the wild reported, or mentioned in words the reader cannot settle ("unclear");
- public exploit code;
- no usable advisory: it cannot be fetched or read, or none has appeared yet (until 6 hours after Mozilla's release; an advisory that appears later raises the urgency again).

Otherwise it is **standard** (72 hours): only moderate or low issues, or still no advisory 6 hours after the release. A platform note ("only affects Firefox on Windows") is shown and never lowers the urgency. In 2025 and 2026 nearly every Firefox security release was urgent (high or critical; every major had sandbox escapes): about 2 or 3 a month.

**Proposed, for the maintainer to decide:** make 24 hours the public commitment for urgent releases (in [SECURITY.md](../../SECURITY.md)). Until then 24 hours is the internal target (formerly "stretch") and 72 hours the commitment.

### Process

1. Watch Mozilla's releases and security advisories (MFSA); see the fast path below.
2. Verify the source release: `scripts/upstream/verify_firefox_release.py <version>` checks `SHA256SUMS` against the **pinned** Mozilla Software Releases key (`14F2 6682 D091 6CDD 81E3 7B6D 61B7 B526 D98F 0353`) and prints the tarball hash. `scripts/release/bump_engine.py <version>` runs that check and pins the version and the hash in `browser/build/engine.json`.
3. Apply the patch stack (`browser/patches/series`, applied idempotently by `scripts/build/apply_patches.py`). Each patch has an owner, a reason and an upstreaming plan; the unit tests enforce this and cap the stack at about 10 patches.
4. Build in a clean container. Run unit and integration tests plus the provider certification smoke tests.
5. Sign packages (RPM GPG; provenance attestation planned): only the files the rehearsal's `manifest.json` lists, with those SHA-256 digests. Publish. Record in the security changelog.

### Key rotation

If Mozilla rotates the primary release key, update the pinned fingerprint only after confirming it through two independent channels (Mozilla's KEY file plus a Mozilla blog/announcement or keyserver history). Then record it in this file. Until then every tool here refuses the release: a signature that does not verify stops the build and raises an alert.

### Release cadence

Mozilla has shipped a major release every 2 weeks since Firefox 155 (2026-09-01), plus dot releases about weekly: about 4 or 5 full builds a month. It stages each release (the signed `SHA256SUMS` in `archive.mozilla.org/pub/firefox/releases/<version>/`) 8 to 25 hours before publishing it, so a build can be ready before the clock starts. Android uses some dot numbers that desktop skips (158.0.2 was Android only), so the next desktop dot release may skip a number.

### Fast path: from Mozilla's fix to a build ready to sign

| Step | Tool | What it does |
|---|---|---|
| Detect | [`watch_upstream.py`](../../scripts/release/watch_upstream.py) | Reads product-details (published releases, Release channel only, ESR excluded), probes the archive for the next likely versions (staged), reads the advisories, finds the publication time; with `--verify` checks Mozilla's signature for each newer release and that `engine.json`'s digest is still the signed one |
| Alert (GitHub) | [`upstream_issue.py`](../../scripts/release/upstream_issue.py) in the [`upstream` workflow](../../.github/workflows/upstream.yml) | One issue per newer release, with urgency, target, deadline, signature and advisories; @mentions the maintainer when it opens and on escalations (published, urgency raised, exploited in the wild, target missed, deadline passed, signature failure); closes when `engine.json` reaches the release |
| Alert and pre-build (laptop) | [`autobuild.py`](../../scripts/release/autobuild.py) from the [local timer](../../contrib/systemd/nulavio-upstream.timer) | Desktop notifications; builds in a separate git worktree as soon as a release is staged or published; says READY TO SIGN once Mozilla has published it and the signed digest equals the one built |
| Pin | [`bump_engine.py`](../../scripts/release/bump_engine.py) | Moves `engine.json` to the release with the verified digest; refuses downgrades, ESR, unpublished releases (unless `--allow-staged`) and anything whose signature does not verify; `--check` verifies the pinned digest again |
| Build and test | [`rehearse_release.sh`](../../scripts/release/rehearse_release.sh) | The whole path, timed; ends with `manifest.json` (Firefox version, signed digest and subkey, base commit, hash of the worktree diff, packages and SBOMs with their SHA-256) |

`scripts/upstream/fetch_firefox_source.py` refuses to download when `engine.json` pins the version with a digest that differs from Mozilla's signed one.

Detection runs in two places. The local timer is the primary detector: every 30 minutes, no Actions minutes, and the build can start hours before Mozilla publishes. The `upstream` workflow is the backstop for when the laptop is off: it runs at 04:47 UTC (releases staged overnight) and 14:47 UTC (about an hour after Mozilla's usual 12:15–13:55 UTC publication), about 60 Actions minutes a month. GitHub's scheduled runs can be late or skipped, which is why it is not the primary.

The watcher's report (`--json`, schema 2) has, for each newer release: `version`, `phase` (`staged`, `shipped`, or `unconfirmed` when on the archive without a verified signature), `released_at` and `clock_source`, `urgency` and `reasons`, `itw`, `public_exploit`, `platform_notes`, `advisories`, `target` and `target_hours` (24 or 72), `deadline` and `deadline_hours` (72), `target_missed`, `overdue`, and after `--verify` `verified`, `source_sha256` and the signing subkey. Exit status: 0 up to date, staged or within the deadline; 1 overdue; 2 Mozilla's data unavailable (no verdict, never "up to date"); 3 a signature did not verify.

What stays manual: reviewing the worktree's diff and committing the bump to `main`; rebasing a patch that no longer applies; signing with the real key and publishing (they need the key and the host); the security changelog entry; deciding about platform notes; any change to the pinned Mozilla key.

### Local timer (opt-in)

Nothing installs or enables it. Before enabling: a local `main` branch to build from (the timer never fetches or pulls, so only code already in your clone runs), the Google Safe Browsing key at `~/.config/nulavio-build/google-safebrowsing.key` (mode 600, as for `build_nulavio.sh`), about 30 GiB free under `~/.cache/nulavio-build`, and a file `~/.config/nulavio-build/autobuild.env` with one line, `NULAVIO_REPO=/path/to/your/clone`. Then, from the clone:

```sh
install -Dm644 contrib/systemd/nulavio-upstream.service contrib/systemd/nulavio-upstream.timer -t ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now nulavio-upstream.timer
```

Check it with `systemctl --user list-timers nulavio-upstream.timer` and `journalctl --user -u nulavio-upstream`; stop it with `systemctl --user disable --now nulavio-upstream.timer`. For alerts without builds, add `--no-build` to `ExecStart` (`systemctl --user edit --full nulavio-upstream.service`).

Each run takes a lock, so runs never overlap. It builds only a release whose signature verified, and checks it again in the worktree. It refuses to start a build on battery, with less than 30 GiB free, without the Safe Browsing key (a development override is ignored), or while another build or rehearsal runs (they share the source tree), and it inhibits sleep while it builds (about 70 minutes and 22 GB per release). It never commits, pushes, signs or publishes. A failed build is not retried until you run `autobuild.py --retry` or Mozilla's digest changes. `autobuild.py --prune` removes its own worktrees and outputs for releases older than the pinned one; the source trees in `~/.cache/nulavio-build/firefox-<version>` (about 19 GB each) are left to you.

### Measured

`rehearse_release.sh <version>` was first run in full on 2026-10-27 (Firefox 158.0.1, incremental build): **14 minutes**, every step passed ([report](../research/evidence/release-rehearsal-2026-10-27.md)). The first urgent release, Firefox 159.0 (2026-10-27), had its packages ready to sign 12.8 hours after Mozilla's release, inside the 24-hour target, with one interruption and one test fix on the way ([report](../research/evidence/release-rehearsal-2026-10-28.md)). For a new Firefox release the build is a full one (about 52 minutes measured), so about 70 minutes from the start to checked packages. With a pre-build from the staged release, the packages are ready before Mozilla publishes; without it, about 1 hour 40 minutes after. Not rehearsed: signing with the release key and publishing.

[Security changelog](../security/changelog.md): one entry per published build, with the hours from Mozilla's release to "ready to sign" and to "published".

### Next steps (not adopted yet)

- `sign_repo.sh` refusing any package that `manifest.json` does not list with the same SHA-256 (today the rule above is followed by hand).
- Patch stack pre-check against the `FIREFOX_<version>_BUILD<n>` tag of Mozilla's GitHub mirror, days before a major: an early warning that a rebase is needed. Indicative only; builds keep using the signed tarball.
- `sccache` for dot releases (estimated 52 to 15–25 minutes, not measured yet).
- The `upstream` job on the 1-vCPU `ubuntu-slim` runner, once the billing shows it costs less.
- CISA's Known Exploited Vulnerabilities catalogue as a second "exploited in the wild" signal.

Not adopted: building Firefox on GitHub-hosted runners (2 vCPU and 14 GB of disk against a 22 GB build, near the 6-hour limit, half the monthly minutes), a self-hosted runner on the laptop (it would run jobs defined by any commit), bump pull requests from Actions (the repository does not let Actions create pull requests, and the work goes straight to `main`), and hourly polling in Actions (about a third of the monthly minutes for what the local timer does for free).

## Base branch choice (open)

Recommendation: follow **Release**. Re-evaluate in favour of ESR if the non-branding patch stack exceeds about 10 patches or a rebase takes more than one working day.
