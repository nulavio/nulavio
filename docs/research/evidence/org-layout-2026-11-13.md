# Repository layout: what was measured, 2026-11-13

Evidence for [ADR 0013](../../adr/0013-repository-layout.md) (issue #97). Measured on `main` at `bbe8046` (2026-11-13). The numbers that come from git are in [`org-layout-2026-11-13.json`](org-layout-2026-11-13.json), written by `python3 -I scripts/research/org_layout_measure.py`; run it again to compare later. Clone times, CI numbers and GitHub settings were read by hand, with the commands given in each section.

The repository was created on 2026-10-25, so "the last 30 days" of the issue's plan is the repository's whole life: 20 days.

## Size

1,587 files: 9.8 MB of text and 79.4 MB of images and video.

| Component (how the script attributes paths) | Files | Text lines | Text, estimated tokens | Media |
|---|---|---|---|---|
| browser (`browser/`, `scripts/build`, `scripts/upstream`, `scripts/brand`, `scripts/research`) | 211 | 38,268 | 454 k | 0 |
| tests (not attributed to a component below) | 140 | 32,977 | 440 k | 1.6 MB |
| launcher (`launcher/`, `bin/`) | 41 | 10,455 | 109 k | 0 |
| release (`scripts/release`, `packaging/`, `ci/aws`, `ci/containers`, the release workflows and their tests) | 62 | 10,111 | 122 k | 0 |
| site (`site/`, `scripts/site`, `ci/site`, its workflow and test) | 87 | 11,787 | 149 k | 1.8 MB |
| android (`android/` and its two tests) | 45 | 5,303 | 64 k | 0 |
| process (`.github/`, `scripts/ci`, `scripts/security`, hooks, SAST rules, `docs/process`, the root policy files) | 47 | 5,557 | 73 k | 0 |
| docs (everything under `docs/` not listed elsewhere) | 67 | 9,525 | 222 k | 0 |
| design and brand (`docs/design`, `docs/brand`) | 880 | 69,656 | 814 k | 76.0 MB |

Tokens are an estimate (four bytes a token) to compare areas, not a measurement of any model.

**Where the bytes are.** `docs/design/screenshots/` alone is 73.6 MB (769 files); the rest of `docs/design` is 3.8 MB and `docs/brand` 1.8 MB. Over the whole history of `main`, media blobs take 75.8 MB of the pack and every text file ever committed 4.8 MB: 94 % of what a clone downloads is screenshots. They arrived in bursts with the UX work: 438 files on 2026-10-29, 127 on 2026-10-28, 96 on 2026-11-04, 47 on 2026-11-13. 126 lines of the documents link to them, and two scripts write there (`scripts/site/capture_site.py`, `scripts/research/ux7_captures.py`).

## What a clone and a worktree cost

One run each, from GitHub, on the maintainer's laptop (`git clone https://github.com/nulavio/nulavio.git`):

| | Time | `.git` | Working tree |
|---|---|---|---|
| Full clone | 4.2 s | 83 MB | 89 MB |
| `--filter=blob:none` (the checkout then fetches the blobs) | 5.5 s | 74 MB | 89 MB |
| `--depth 1` | 4.5 s | 73 MB | 89 MB |
| `--filter=blob:none --no-checkout`, then a sparse checkout without `docs/design/` and `docs/brand/` | 1.9 s | 7 MB | 12 MB |
| `git worktree add` from an existing clone | 0.3 s | shared | 89 MB |

On the machine where the agents work there were 90 worktrees of this repository on 2026-11-13: about 8 GB of working trees, of which about 6.6 GB are 90 copies of the same screenshots.

## CI

`gh api 'repos/nulavio/nulavio/actions/runs?created=>=2026-10-14'`: 926 workflow runs between 2026-10-25 and 2026-11-13.

| Workflow | Runs | Wall time per run (median / 90th percentile) |
|---|---|---|
| `ci` | 416 | 4.1 / 5.7 min |
| `ai-review` | 106 (39 skipped) | 0.1 min |
| `main-via-pr` | 82 | 0.2 min |
| `scorecard` | 39 | 0.7 min |
| `upstream` | 32 | 0.3 min |
| `site` | 21 | 0.5 / 5.6 min |
| `release` | 6 | 34.5 / 41.8 min |
| `asan` | 1 | 58.9 min |
| `repeatable build` | 1 | 17.0 min |

- A successful `ci` run costs 12.8 job-minutes (median of the latest 40): Fedora integration 3.9, lint and unit tests 3.2, Ubuntu integration 3.0, Companion 2.2, scanners 0.5. All of it on `ubuntu-24.04` standard runners, which are free for a public repository. `release`, `asan` and `repeatable build` run on Blacksmith, which is billed.
- A pull request branch had 2 `ci` runs (median; at most 9), over 114 branches.
- The gate job "does this change need the engine integration run" already skips the two integration jobs for changes that cannot affect the engine. The Companion job runs on every change.

## Coupling

`main` has 162 commits; 152 are not Dependabot's. Since 2026-10-27 each is one squash-merged pull request. A commit is counted for a component when it changes a path the table above attributes to it, so a site build script counts as the site, not as "scripts".

**53 of 152 (35 %) change more than one of the six code components** (browser, launcher, site, android, release, process).

| Component | Commits that change it | …and no other code component | Changed together with |
|---|---|---|---|
| browser | 79 | 54 (launcher and tests do not count as "other") | release 15, process 13, site 4, android 3 |
| launcher | 23 | 13 | release 5, process 4, android 3, site 2 |
| release | 37 | 8 | process 16, browser 15, site 8, launcher 5, android 3 |
| process | 41 | 15 | release 16, browser 13, site 5, android 5, launcher 4 |
| site | 15 | **1** | release 8, process 5, browser 4, launcher 2, android 1 |
| android | 8 | **1** | process 5, browser 3, launcher 3, release 3, site 1 |

The issue asked whether the site and the Companion only looked coupled because their build scripts live in `scripts/`. With those scripts attributed to them, they still almost never change alone. Why, read from the commits and the code:

- **Site ↔ release.** The site is where a release is published from: it serves the package repository file (`site/rpm/nulavio.repo`) and the release key (`site/keys/`), and the download pages are rebuilt from `packaging/release.json`. Eight of its fifteen commits are release changes.
- **Site ↔ browser.** `site.yml` rebuilds the site when `browser/startpage/tokens.css`, `docs/brand/assets/**`, `browser/build/engine.json` or `browser/patches/series` change: the site uses the product's design tokens and brand assets and states the engine version and the patch count. Four commits changed product code and the site together (#42, #44, #18, #3).
- **Companion ↔ launcher.** The phone and the desktop speak one protocol (`android/nv1` and `launcher/nulavio_launcher/vault/`): canonical JSON that must be byte-identical in Java and Python, shared test vectors, one threat model. Four of its eight commits changed both sides (#48, #40 and two before the pull request flow).
- **Everything ↔ process.** Required checks, the SAST rules, the hygiene tests and the review rules apply to every component from one place.

## What depends on this repository's name and layout

Read from the files and from GitHub's API on 2026-11-13:

| Consumer | What it is bound to |
|---|---|
| F-Droid (`android/fdroid/net.nulavio.companion.yml`, merge request open in fdroiddata) | `Repo: https://github.com/nulavio/nulavio.git`, tags `companion-v*`, `subdir: android/app` |
| Release signing (`ci/aws/release-signing-trust.json`) | The OIDC subject of this repository by its immutable id, environment `release` |
| Build-provenance attestations | Checked against this repository's `release.yml` on `refs/heads/main` |
| AI review credential (Workload Identity Federation) | `repository == nulavio/nulavio` and `ai-review.yml@refs/heads/main` |
| Site deploy | `site.yml` here, repository secret `CLOUDFLARE_API_TOKEN` |
| Flathub manifest | The GitHub release asset of this repository |
| Branch protection | Four required check names of `ci.yml` |
| Dependabot | Five ecosystems, each with its directory here |
| Tags | `v160.0-0.1` … `v160.0-0.3`, `companion-v0.1.0`: a history rewrite would break every one, and every commit id the documents, the changelog and the pull requests cite |

## Secrets and who can reach them

`gh api repos/nulavio/nulavio/actions/secrets` and `…/environments/<name>/secrets` (names only):

| Secret | Scope | Who can use it |
|---|---|---|
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Environment `release` (`main` only, the maintainer approves) | The `publish` job of an approved release run |
| `GOOGLE_SAFEBROWSING_API_KEY` | Environment `build` (`main` only) | The release build |
| `CLOUDFLARE_API_TOKEN` | **Repository** | Any workflow on any branch that someone with write access pushes |

GitHub Apps installed on the organization, all for "all repositories" (`gh api orgs/nulavio/installations`):

| App | Since | Write access to |
|---|---|---|
| Codex connector | 2026-11-10 | contents, workflows, pull requests, issues, actions |
| Blacksmith | 2026-11-10 | contents, workflows, pull requests, actions, checks, self-hosted runners |
| CodeRabbit | 2026-11-12 | contents, workflows, pull requests, issues, checks, statuses |
| LESIS | 2026-11-11 | none (contents: read) |

## What an agent has to read

The root `AGENTS.md` sends every agent to `CONTRIBUTING.md`, the three pages of `docs/process/` and (for reviews) `.github/ai-review/instructions.md`: 62 KB, about 15 k tokens, the same whatever the task. Nothing tells an agent that changes the site which of the 9.8 MB it needs: the rules of an area are spread over `CONTRIBUTING.md` ("Common changes"), the invariants and the architecture documents.

## Private fork of a security advisory

Checked on 2026-11-13: a pull request with a blank-line change was opened in the temporary private fork of a draft advisory. What the installed Apps did there is recorded in [private work](../../process/private-work.md#what-the-installed-apps-see).
