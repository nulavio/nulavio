# Dependency updates and the vulnerability watch

Everything Nulavio pins, except the Firefox engine, and how it stays current. The engine has its own policy and watcher ([update policy](../architecture/update-policy.md)).

## What is pinned

| Pin | Where | Pinned by | Kept current by | Vulnerability signal |
|---|---|---|---|---|
| GitHub Actions | `.github/workflows/*.yml` | commit SHA plus `# vX.Y.Z` on the same line | Dependabot, weekly | the daily watch (GitHub raises no alerts for actions pinned by SHA) |
| ruff (development only) | `requirements/dev.txt` | version and SHA-256 (`--require-hashes`) | Dependabot, monthly | the daily watch; Dependabot alerts once enabled |
| Hypothesis and sortedcontainers (fuzzing only, #149) | `requirements/fuzz.txt` | version and SHA-256 of each Linux x86_64 wheel (`--require-hashes`) | Dependabot, monthly (same directory) | the daily watch; Dependabot alerts once enabled |
| Gradle | `android/gradle/wrapper/gradle-wrapper.properties` | version and `distributionSha256Sum` | Dependabot, monthly | the daily watch (OSV lists Gradle's own advisories under "Bitnami") |
| Companion libraries and the Android Gradle plugin | `android/*/build.gradle.kts` | version, SHA-256 of every artifact in `android/gradle/verification-metadata.xml`, and the APK's classpath in `android/app/gradle.lockfile` (`nv1` in `android/nv1/gradle.lockfile`) | Dependabot, monthly, plus a local step (below) | the daily watch, for every component in the metadata (213 today), build-time ones included |
| Base images | `ci/containers/*.Containerfile` | `tag@sha256:digest`; the release scripts read it there (`scripts/release/base_image.sh`) | Dependabot, monthly (new digest of the same release) | the daily watch reports a newer build |
| Extensions | `browser/distribution/extensions.lock.json` | version and SHA-256 | `scripts/upstream/refresh_extensions_lock.py`, with review; it also re-copies uBlock Origin's list registry (`browser/distribution/ublock-origin/`), which new profiles start from | the daily watch: Mozilla's blocklist, a replaced or removed file for the pinned version, a published security advisory of the extension's repository that covers the pin, more than 30 days since AMO first published a newer version |
| Security scanners | `scripts/security/fetch_tools.sh` | version and SHA-256 | by hand ([code scanning](code-scanning.md#updating-a-tool)) | none yet: read the tool's advisories when bumping it (next steps) |

Not pinned by hash, on purpose: libsodium, gocryptfs and fuse3 on the CI runner, the JDK and the Android SDK of the runner image, and the packages `dnf` and `apt` install inside the images. They are signed distribution packages.

The lockfiles make any change to what the APK contains visible in review. Locking is strict: a lockfile that does not match the build fails it (the Android lint tasks resolve both locked classpaths, so the `companion` CI job catches it), and `tests/unit/test_dependency_pins.py` fails earlier, without Gradle, when a version in a build file differs from its lockfile or is missing from the verification metadata.

Where CI downloads them from (#535): GitHub's runners share egress addresses, and Maven Central answers them with 429 Too Many Requests for longer than a retry waits. So the two CI steps that run Gradle (`scripts/ci/gradle.sh`) ask Google's [mirror of Maven Central](https://storage-download.googleapis.com/maven-central/index.html) first, right before Maven Central, through `scripts/ci/maven-mirror.init.gradle`. When the mirror fails a run (refuses it, drops it or answers with an error status), the next run goes to Maven Central without it. The mirror is "not an officially supported Google product" and states no rate limits, so it is a convenience, not a trust anchor:

- What it serves is checked against `verification-metadata.xml` like anything from Maven Central. If it serves bytes that differ, the build fails closed with "Dependency verification failed", and `gradle.sh` does not try Maven Central instead. Treat that as a supply-chain alert: find out which repository served the file, and if it was the mirror, remove `NULAVIO_MAVEN_MIRROR` from the two steps in `.github/workflows/ci.yml`.
- The lockfiles fix the APK's classpaths only (`nv1`'s `runtimeClasspath`, the app's `releaseRuntimeClasspath`). The plugin, lint, test and debug classpaths have no lock, so a version range or a dynamic version there would be resolved from the repository's `maven-metadata.xml`, which dependency verification does not check, and from the mirror in CI. On 2026-11-18 there was none: no build file declares one, and none of the 129 configurations that `buildEnvironment` and `:app:dependencies :nv1:dependencies` list resolves one (lint's own detached configurations are not in those reports).
- `android/settings.gradle.kts` does not name the mirror, so local, F-Droid and release builds (`scripts/release/build_companion.sh`) read Maven Central as before.

CI keeps no Gradle cache between runs, on purpose. Dependency verification does not check everything a restored `~/.gradle/caches/modules-2` holds, so nothing from Gradle's cache is kept between runs. The hashes in a project's `.gradle/` directory stand in for the files' own, so that directory is never cached or restored either ([#535](https://github.com/nulavio/nulavio/issues/535)).

Android lint's security checks that default to a warning are errors (`android/app/lint.xml`), for the app and for `nv1` (`checkDependencies`). After an Android Gradle plugin update, compare `lint --show` (Android SDK command-line tools) with that file: new checks in the Security category go in `lint.xml` and in `LINT_SECURITY` in the test.

## The daily watch

`scripts/release/watch_dependencies.py` runs every day in the `upstream` workflow, after the Firefox check, and writes its findings in the job summary. CI runs it too, so a push or pull request that brings in a vulnerable version is flagged at once (there, data that cannot be fetched is only a warning; the daily run fails on it). It checks:

- every pinned package above but the security scanners against [OSV.dev](https://osv.dev) (one batch query; GitHub Actions versions are matched locally because OSV.dev does not match them);
- each pinned extension against addons.mozilla.org: blocklist, the file served for the pinned version (its SHA-256 and size, read on every run, also once a newer version is out), and how long the lock has been behind, counted from the first version AMO published after the pin (#629: counted from AMO's newest version, an extension that releases every few weeks never reached the limit however long the pin stayed behind). The versions list is read newest first, 50 a page and at most 4 pages, until it reaches the pin; only listed, public versions with a higher number count, and AMO's current version counts only when it came after the pin in number and date (a backport made current is reported, not failed, since refreshing to it would downgrade the pin). The blocklist, the pinned file and the lag are judged apart: one AMO reply missing hides no failure the others show, and with no failure shown the row is unavailable data. The tests are in `tests/unit/test_dependency_pins.py` (`ExtensionLagTest`), on replies recorded in `tests/fixtures/amo/` and on a made-up stream of releases;
- each pinned extension against the security advisories its repository has published on GitHub (below);
- each base image digest against its registry.

Exit status 1 (the job fails, GitHub emails the maintainers) means: a known vulnerability without a valid exception, a blocked extension, a pinned extension file that AMO now serves differently or no longer serves, a published advisory that covers a pinned extension (or one whose range the watch cannot read), or a pin that AMO first superseded more than 30 days ago (when the 4 pages do not reach back to the pin, what they show is a lower bound: over 30 days it fails, under it the row is unavailable data). A newer base image build is only reported. Exit status 2 means some data could not be fetched and nothing else needs action. Each source is checked on its own: OSV.dev, AMO, GitHub or one registry being down does not hide what the others found. Only public package names and versions are sent, to api.osv.dev, addons.mozilla.org, api.github.com and the registries.

### Extension advisories (#415)

A blocklist entry or a newer AMO version says nothing about a vulnerability the vendor has published but Mozilla has not blocked: uBlock Origin's GHSA-cmqw-9r2w-6wv2 (a universal XSS from the element picker, 1.75.2 and lower, fixed in 1.75.4) was published while the lock pinned 1.75.0. So the watch reads `GET /repos/{owner}/{repo}/security-advisories` (published repository advisories; no authentication needed, the workflow's read-only `GITHUB_TOKEN` is passed on stdin only to raise the rate limit) for the repository of each extension and fails at once, naming the advisory's id, severity, range, fixed version and link, when one covers the pinned version.

- **The table is reviewed, not guessed.** `docs/security/extension-advisory-sources.json` maps each key of `extensions.lock.json` to its repository, or says why there is none. A unit test requires the two to list the same extensions, and the watch fails when they differ. Package names and ecosystems in an advisory are free text (uBlock Origin's own says `ecosystem: ""`), so for a repository of one product (uBlock Origin, KeePassXC-Browser: `"monorepo": false`) every advisory counts whatever it names its package. A monorepo (Bitwarden's `bitwarden/clients`: `"monorepo": true`) is filtered by the package names in the table, and an advisory that names a package in neither list **fails** until the name is added to one of them or the advisory is accepted (below).
- **Another product of the monorepo (the routine).** `"other_packages"` in the table lists the names that are known not to be the extension (Bitwarden's `@bitwarden/cli`). An advisory that names only such packages is skipped, so it needs no exception at each change of the pin. When the watch fails on `it names package 'X', which is not this extension's in the table`, read the advisory: if `X` is another product (the CLI, the desktop app, the web vault), add it to `other_packages` (reviewed like the rest of `docs/security/`); if it is the extension under another name, add it to `packages`; if it is the extension and it cannot be fixed yet, accept it with an exception. Never add a name just to turn the watch green, and a name in both lists is refused.
- **No source today:** Proton Pass (its source is in the `ProtonMail/WebClients` monorepo, which publishes no repository advisories, and Proton has no feed) and 1Password (closed source). For these the AMO blocklist check is the only signal, the daily summary names them, and [R84](residual-risks.md) records the gap. GitHub's global advisory database (`GET /advisories`) returned nothing for uBlock Origin on 2026-11-18 (it indexes package ecosystems, not extensions), so it is not used.
- **Ranges are read strictly.** GitHub stores the range as free text. The watch reads comma-separated clauses of `<`, `<=`, `>`, `>=`, `=`, `==` and `X and lower` (also `or lower`, `and below`, `or earlier`), over dotted numeric versions of any length with an optional `v` (`1.75.2`, `1.10.4.1`, `v2026.10.2`). Anything else fails naming the advisory: an empty or unreadable range, and an advisory that lists no affected package at all. Read it by hand, and extend the reader (with a test) if the form is legitimate. Drafts and withdrawn advisories are ignored.
- **Accepting one.** An advisory that has no fix yet, or does not apply to how Nulavio uses the extension, would turn every pull request red (CI runs the watch), so it takes an entry in `vulnerability-exceptions.json` like any other, with `"ecosystem": "Browser extension"`, `"package"` the extension's key in the lock (`ublock-origin`), `"version"` the pinned version, the advisory's `id` (GHSA, or its CVE), a reason and an expiry. It covers that one advisory for that one pinned version, so moving the pin looks at it again; after `until` it fails again; an entry that matches nothing is reported so it gets removed (not on a day when that extension's advisories could not be read: then nothing is known about the entry, and it is left alone).
- **Fetch errors are not a pass.** A server error, a 429, a rate-limited 403 (GitHub's `Retry-After`, or no calls left until its reset time, waited for when that fits) or a network failure is retried (2, 8 and 30 seconds, as `watch_upstream.py` does) within a budget of 120 seconds for all repositories together: no retry is waited for after it, and a request's timeout is what is left of it, never less than 10 seconds. That budget is soft: a repository reached after the 120 seconds still gets its first request, with a 10-second timeout. The hard bound is the whole watch's budget, `WATCH_BUDGET` (360 seconds from the start, OSV.dev, AMO and the registries included): no request starts after it, no request's timeout exceeds what is left of it, and the checks that did not finish report an error row (a unit test keeps the two budgets coherent). A timeout bounds each socket wait (one connect attempt, one read), not the whole request: the address lookup has no timeout, a host with several addresses gets one connect attempt per address, and a server that keeps dripping bytes is not cut off. So the summary and the exit status (2) normally come out well inside the step's 8 minutes, the 2 minutes of margin cover a slow lookup or a few dead addresses, and a pathological network can still hit the step's timeout, which fails the job without a summary (never a pass). Any other 403 is not retried. If it still fails, the extension's row is an error and the run exits 2, which fails the daily job; CI only warns. A malformed reply (an element that is not an object, or has no state, id or link) and more than 99 advisories in a repository are errors too (one page is read).
- **The token** (the workflow's read-only `GITHUB_TOKEN`, only to raise api.github.com's rate limit) reaches the script on stdin (`--token-stdin`), not in its environment or arguments (I3); it is optional, and the script runs without it.
- **The tests are `tests/unit/test_extension_advisories.py`**, on replies recorded in `tests/fixtures/advisories/`: the uBO advisory fails the old pin 1.75.0 and passes 1.76.4, an unreadable range fails, an API error is an error.

```sh
python3 -I scripts/release/watch_dependencies.py           # the check
python3 -I scripts/release/watch_dependencies.py --list    # what it checks, no network
python3 -I scripts/release/watch_dependencies.py --json
```

When it fails: update the dependency (any day, without waiting for Dependabot's schedule), or, after looking at the advisory, add an exception.

## Exceptions

`docs/security/vulnerability-exceptions.json` lists accepted findings. Each entry names one advisory (`id`, or one of its aliases), one package and one exact version, with a reason and an expiry date (`until`, at most a year ahead; the unit test checks this). A version change is therefore looked at again. An expired entry fails the watch again; an entry that matches nothing is reported so it gets removed. Accepting a risk is the maintainer's decision.

The first entries (2026-10-27, until 2026-12-31) are advisories in tooling of the Android Gradle plugin 9.4.1 (ten then, nine since one went with a tooling update), the latest stable release: Bouncy Castle 1.80.2, Guava, jdom2, jose4j, HttpClient, Commons Lang and the Kotlin Gradle plugin. None is in the APK (it ships Bouncy Castle 1.86, which is fixed). The build reads only this repository and artifacts pinned by SHA-256, and uses no shared build cache. Re-check them at the next plugin update.

## Dependabot pull requests

`.github/dependabot.yml` groups updates to keep pull requests and CI minutes down. Its own runs are free; each pull request runs CI (about 14 billed minutes). Nothing merges automatically. Branch protection on `main` requires the quick CI checks; the engine integration result and the diff are read by hand: **merge only with green CI, after reading the diff.** Merge in GitHub (a direct push to `main` is refused); Dependabot closes a pull request once `main` has the version.

- **Actions**, weekly on Wednesdays (Firefox releases on Tuesdays), with a 7-day cooldown so that a hijacked tag has time to be noticed. Check that the new SHA is the tag's commit (`git ls-remote https://github.com/<owner>/<repo> refs/tags/<tag>^{}`).
- **pip**, monthly. Dependabot writes one hash per file PyPI publishes for the new version, so one hash becomes about twenty. That is expected.
- **docker**, monthly, digest updates within the pinned release only. Moving to Fedora 45 or Ubuntu 27.04 is a product decision (major versions are ignored; Fedora's newest numeric tag is Rawhide). The release scripts follow the Containerfiles automatically. Ubuntu only: Dependabot cannot read `registry.fedoraproject.org` without credentials, so a newer Fedora 44 digest comes from the daily watch, and the update is the command below.
- **gradle**, monthly (major versions wait 30 days). These pull requests fail CI until the step below is done.

## Finishing a Gradle pull request

Dependabot updates the build files and the wrapper, but it cannot write `verification-metadata.xml` ([dependabot-core #1996](https://github.com/dependabot/dependabot-core/issues/1996)), and its attempt to rewrite the lockfiles fails on that same verification. So CI fails with "Dependency verification failed", and the unit tests name the coordinate that is missing.

**CI or a bot must never write this file.** (The Opengrep rule `nulavio-ci-writes-gradle-verification` rejects `--write-verification-metadata` in workflows and CI files.)

1. The file is the trust anchor. Writing it in the same pipeline that checks it makes the check circular: it passes on whatever the repositories serve that day. Gradle's documentation says a generated file must be reviewed.
2. Writing back needs a token with `contents: write` while running code the pull request controls (`build.gradle.kts` is code, and plugins run during configuration). That is the "pwn request" pattern, and it breaks the read-only token CI has today.
3. Dependabot's pull requests get a read-only token and no secrets. Giving them write access would need a personal token or an app secret.
4. A green CI over self-approved hashes removes the signal (the red job) that makes a person look at what changed. A plugin update changes hundreds of transitive artifacts.

Instead, on the machine with the toolchain:

```sh
git fetch origin && git switch --track origin/dependabot/gradle/android/<branch>
export JAVA_HOME=~/.local/share/nulavio-dev/jdk-21 ANDROID_HOME=~/Android/Sdk
export GRADLE_USER_HOME=$(mktemp -d)   # empty cache: everything is downloaded fresh, nothing older is recorded
android/gradlew -p android --no-daemon --write-verification-metadata sha256 --write-locks \
    :app:dependencies --configuration releaseRuntimeClasspath \
    :nv1:dependencies --configuration runtimeClasspath \
    :nv1:test :app:lintDebug :app:assembleRelease
python3 -I scripts/upstream/review_gradle_verification.py --base origin/main
```

Never use `--write-verification-metadata` with anything but `sha256`, and never edit the `<configuration>` block. The review script prints the components added and removed, and the change in what the APK ships. For each new artifact it compares the recorded SHA-256 with the downloaded file and with the checksum the repository publishes next to it, and says whether a PGP signature is published. It fails on a mismatch, a missing checksum, a changed hash for a version already pinned, or a changed `<configuration>` block. Check that only the expected groups were added. Then:

1. Delete the older versions it lists, if nothing uses them any more (Gradle never removes entries).
2. Prove strict mode without the write flags: `android/gradlew -p android --no-daemon -q :nv1:test :app:lintDebug :app:assembleRelease && python3 -I tests/run.py unit`.
3. Run the watch (`watch_dependencies.py`): a plugin update changes build-time versions, so exceptions may need a new look.
4. Commit on the pull request's branch (`build(android): verification metadata and locks for <dependency>`), push, wait for green CI, merge. Remove the temporary `GRADLE_USER_HOME`.

The first download is about 140 MB (Gradle) plus the dependencies. Rehearsed on 2026-10-27 with a simulated `com.google.zxing:core` change: two components added, checksums matched Maven Central's, both signed, and the strict build passed after the old version was removed.

A pull request that only updates the wrapper changes `gradle-wrapper.properties`, `gradlew` and `gradle-wrapper.jar`, not the metadata. Compare `distributionSha256Sum` with `https://services.gradle.org/distributions/gradle-<version>-bin.zip.sha256`. The jar is a binary nobody can review in a diff, so CI checks it against Gradle's published checksums (`gradle/actions/wrapper-validation`) before any job runs `gradlew`.

The APK stays reproducible: Gradle locking and lint settings do not change its bytes (checked on 2026-10-27, same SHA-256 before and after). After any Gradle change, build twice from fresh copies and compare.

## Base images by hand

If Dependabot's docker pull request does not come while the watch reports a newer build:

```sh
skopeo inspect --format '{{.Digest}}' docker://registry.fedoraproject.org/fedora:44
skopeo inspect --format '{{.Digest}}' docker://docker.io/library/ubuntu:26.10
```

Put the digest after the tag in the Containerfiles (the same digest for the same tag), run the unit tests, and run `check_rpm.sh` and `check_deb.sh` (or `rehearse_release.sh`).

## uBlock Origin's default lists

A new profile starts with the lists of `browser/distribution/content-filter.json` switched on in uBlock Origin ([how](../architecture/extension-model.md#the-lists-a-new-profile-starts-with)). That rests on uBlock Origin's own code, which Nulavio does not control: an older managed setting (`adminSettings.assetsBootstrapLocation`), the rule that only `scheme://` is an external address, and the way `off` decides what a new profile selects. The policy always installs the **pinned** version first, so the lists are switched on by the version that was tested; the risk there is in moving the pin. uBlock Origin then updates itself from AMO like any extension (on 2026-11-12 the engine had 1.76.0 downloaded within the first minute of a first session, and it ran from the next start at the latest), and what a newer version does with lists that are already selected is not something the suite sees: it runs with add-on updates off.

**How it is noticed, in the order it would happen:**

1. `refresh_extensions_lock.py` reads the new package for that code and prints `! THE DEFAULT LISTS MAY NO LONGER APPLY`, naming the file and the line that is gone (`BOOTSTRAP_MARKERS`). It also says when a default list is gone or already on upstream.
2. `refresh_extensions_lock.py --check-registry` gets the pinned package (from the local cache or from AMO, checked against the lock's SHA-256) and compares the registry copy and the licence with it byte for byte, and reads it for the same code. CI runs it on every change and the release rehearsal runs it before it writes `policies.json`; it fails when the copy differs and when the package cannot be had. This is the check that the copy is uBlock Origin's: the checksum in `content-filter.json`, which the build compares the copy with, sits beside the copy and can be edited with it. `tests/unit/test_track_b.py` makes the same comparison when the package is in the local cache.
3. `tests/integration/test_content_filter.py` starts a new profile with the real package: this is the proof. Run it on every change of uBlock Origin's pin.

**If it broke, nothing is unprotected:** a new profile gets uBlock Origin's own defaults (ads, trackers, malware), without the extra lists. A profile that already exists is never touched by this mechanism.

**What to do, first that fits:**

| What changed | What to do |
|---|---|
| A default list was renamed or removed upstream | Edit `default_on` in `content-filter.json` (the registry copy names the lists of the pinned version) and set `changed_on` to that day: it is the date in the notice that goes out with the modified copy |
| The registry copy was refreshed (`--registry`), whatever changed in it | Run `scripts/build/make_distribution.py --filter-lists`: it writes the lists' names into the Shell (`browser/shell/shared/filter-lists.json`), which Settings uses to say whether a list that hides cookie notices is on. A unit test and the build stop while that file is not the registry's. It stops too when the registry has no list in the group `cookies` any more: then read how the new registry names them and adjust `filter_lists` |
| A default list is on by default upstream now | Remove it from `default_on` and set `changed_on`; the build asks for the first |
| The address is no longer loaded (the rule for external addresses, or the cache token, changed in `js/assets.js`) | Read `assets.fetchText` and `getAssetSourceRegistry` in the new package and adjust `registry_address` in `scripts/build/make_distribution.py`; its unit test states the form expected |
| `off` no longer decides the selection (`autoSelectRegionalFilterLists`, the `assets.json-updated` handler in `js/storage.js`) | Read both in the new package. The registry must mark a list so that a new profile selects it **and** a later registry update does not take it for a stock default; if no value of `off` does both, treat it as the next row |
| `assetsBootstrapLocation` is gone, or no change above fits | Keep the pin where it is (the daily watch allows 30 days) and ask upstream for a supported default (below). If the pin must move, set `default_on` to `[]`: the build then ships no managed setting, and the row in Settings that opens uBlock Origin's lists is how a person switches them on |

**Never** use `toOverwrite.filterLists` or `adminSettings.selectedFilterLists` as the fix: they replace the person's selection at every start (a unit test refuses any managed key but the registry's address).

**The lasting fix is upstream's**: a managed key that adds lists to a new profile's selection without overwriting it later (the counterpart of `toAdd.trustedSiteDirectives` for filter lists). Asking for it is the maintainer's to do; until it exists, the steps above are the procedure.

## Settings only the maintainer can change

Everything above works without them; they add GitHub's own alerts (free on private repositories, also on the Free plan):

- Settings → Advanced Security: turn on Dependency graph, Dependabot alerts, Dependabot security updates and Grouped security updates. Or, as the maintainer: `gh api -X PUT repos/nulavio/nulavio/vulnerability-alerts` and `gh api -X PUT repos/nulavio/nulavio/automated-security-fixes`.
- To be told: Watch → Custom → Security alerts on the repository, and email for Dependabot alerts in your notification settings.

These alerts cover little here (ruff only: no alerts for actions pinned by SHA, Gradle needs a dependency submission workflow, Docker has no security updates), which is why the daily watch exists.

## Next steps (not done yet)

- **Watch the security scanners.** zizmor (PyPI, crates.io), actionlint and gitleaks (Go) and ShellCheck (Hackage) are in ecosystems OSV.dev covers, but none of them has had an advisory yet to confirm the package names against. Opengrep's release binary needs its own source of advisories.
- **Gradle signature verification.** Most artifacts publish PGP signatures. Trusting each publisher's key for its group (`verify-signatures`, a committed keyring, key servers off, fingerprints checked through an independent channel) would let most Gradle pull requests pass on their own, with the publisher's proof instead of trust on first use. Needs the maintainer to approve the list of keys.
- **Fewer CI jobs on Dependabot branches.** pip pull requests need only `checks`; Gradle ones `checks` and `companion`; docker ones `checks` and `integration`.
- **Extension permissions.** `refresh_extensions_lock.py --write` copies AMO's permissions into `reviewed_permissions`. It should require an explicit `--accept-permissions` when permissions were added.
- **Stale base images.** Dependabot may suppress pull requests that change only a digest (a server-side option it is testing). If the monthly docker pull request never comes while the watch keeps reporting a newer build, make the watch fail when a newer build has waited more than a month.
- **Repository content filters.** In `android/settings.gradle.kts`, ask Google's repository only for the groups it publishes (`com.android.*`, `androidx.*`, `com.google.android.*`, `com.google.testing.platform`), so a regeneration cannot pick a same-named artifact from the wrong repository. The exact list has to be found by building.

Considered and not adopted: Renovate (a third-party app with write access, or self-hosted with a token to keep, and it rewrites the verification metadata itself); an OSV-Scanner binary (the same data as the watch, without actions, extensions or images, and one more binary to pin); Gradle dependency submission (a workflow with write access running the build, for alerts the watch already gives).
