# Contributing to Nulavio

Thanks for helping. Nulavio is a security-sensitive project, so the rules below are strict and short. Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md); how decisions are made and who does what is in [GOVERNANCE.md](GOVERNANCE.md).

## Non-negotiables (reviewers will block on these)

1. Never disable or weaken: sandboxing, site isolation, TLS/certificate checks, extension signatures, Safe Browsing, Remote Settings, or security updates. Not even "temporarily" and not even in CI.
2. No telemetry and no remote service operated by Nulavio. Nothing may send history, URLs, credentials or fingerprints anywhere.
3. No custom cryptography, authentication or password storage.
4. Never use undocumented vendor APIs for password managers; never read, scrape or export vault data.
5. Separate implemented / prototype / planned in docs and PR descriptions. Never claim immunity or "100%" anything.
6. No Mozilla or third-party trademarks or art in Nulavio assets.

## Reporting bugs and asking for features

- **Bugs:** open an [issue](https://github.com/nulavio/nulavio/issues/new/choose) with the bug form: the Nulavio version (Help → About Nulavio, or `rpm -q nulavio`), the distribution, the steps, and what you expected. English or Portuguese.
- **Features and ideas:** open an issue with the feature form, or start a thread in [Discussions](https://github.com/nulavio/nulavio/discussions) when it is still a question.
- **Firefox engine bugs** (they also happen in Firefox) go to [Mozilla's Bugzilla](https://bugzilla.mozilla.org/).
- **Security problems:** never in a public issue; see [Reporting vulnerabilities](#reporting-vulnerabilities).

How maintainers and coding agents use issues to organise the work: [docs/process/issues.md](docs/process/issues.md).

Every issue gets a first answer, even if only a label or a question; the issue list is public and searchable, closed issues included.

## Development setup

The launcher and test suites use only the Python standard library (≥ 3.11). No virtualenv is needed to run them.

```sh
python3 -I tests/run.py unit
python3 -I tests/run.py integration                         # needs firefox ≥ 140 (not Snap)
NULAVIO_NETWORK_TESTS=1 python3 -I tests/run.py integration # downloads pinned XPIs from AMO
```

Linting (dev-only tool, hash-pinned):

```sh
python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements/dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Security scanners (workflows, secrets in the history, shell scripts, Nulavio's own rules; pinned release binaries, nothing installed system-wide, Linux x86_64). CI runs the same checks and blocks on findings; see [code scanning](docs/security/code-scanning.md) for what each one checks and how to handle a false positive:

```sh
scripts/security/scan.sh
git config core.hooksPath scripts/git-hooks   # optional: refuse a commit that adds a secret, and pushes to main (see below)
```

Tests never use your real profile: integration tests set `NULAVIO_HOME` to a temporary directory and use disposable engine profiles. Never put real credentials in tests.

## Modern Web Guidance (development only)

For HTML, CSS and client-side JavaScript work, consult the project's
[Modern Web Guidance skill](.agents/skills/modern-web-guidance/SKILL.md):

```sh
DISABLE_TELEMETRY=1 npm ci --ignore-scripts --prefix ci/modern-web-guidance
scripts/dev/modern_web_guidance.sh search "accessible modal dialog"
scripts/dev/modern_web_guidance.sh retrieve dialog
```

This needs Node.js >= 22 and npm. The lockfile pins `modern-web-guidance@1.0.0`
and its integrity; installation disables lifecycle scripts. The wrapper runs the
installed CLI locally with telemetry disabled. It is not
shipped with Nulavio or the site. `.mwgrc` keeps experimental guidance opt-ins off.
Check each suggestion against the actual Gecko target and the site's static
HTML/CSS policy. The skill describes the query and version-update workflow.

## Track B (building Nulavio from source)

```sh
scripts/build/build_nulavio.sh 160.0     # verified source -> branding -> patches -> container build
```

Everything happens in rootless podman containers and in `~/.cache/nulavio-build` (about 23 GB). Nothing is installed on the host. See [docs/architecture/build.md](docs/architecture/build.md).

The build needs **your own** Google Safe Browsing key; without it phishing and malware protection would be inactive, so the script stops. Create a Google Cloud project, enable "Safe Browsing API", create an API key restricted to that API, then save it without echoing it:

```sh
install -d -m 700 ~/.config/nulavio-build
(umask 077; read -rs -p "Safe Browsing key: " k && printf '%s\n' "$k" > ~/.config/nulavio-build/google-safebrowsing.key; unset k; echo)
```

Never commit it or paste it into issues or logs. For a local experiment only, `NULAVIO_ALLOW_NO_SAFEBROWSING_KEY=1` builds without it; such a build must never be shared.

Languages: the build packages en-US plus `NULAVIO_LOCALES` (default `pt-BR`), fetched at the revision Mozilla signed off for the release. Nulavio's own strings for other languages go in `browser/l10n/<locale>/`.

Patches go in `browser/patches/` with `Owner:` and `Upstream:` headers, listed in `series`. Prefer prefs, policies, branding or built-in add-ons over patches.

Integration tests against your build: `NULAVIO_ENGINE=~/.cache/nulavio-build/install/nulavio/nulavio python3 -I tests/run.py integration`. The search tests (`test_search.py`) record every HTTP request while typing into the real address bar; the profile tests (`test_profiles.py`) need the build because they use the engine's own profile management, so they register a profile in a throwaway home (`harness.GeckoProfileSession`) and drive the second instance a switch starts. It also starts a private D-Bus session bus, because the engine's remote service (how links from other apps and profile switches reach a running instance) uses D-Bus on Linux; `test_routing.py` delivers links that way.

## Website (nulavio.net)

The pages are static (`site/`): no JavaScript in them, no third-party resources, no cookies, security headers in `site/_headers`. There are three kinds: the landing (`index.html`, `en/index.html`, styled by `landing.css`), which presents Nulavio as it is meant to ship and carries the comparison and the waitlist form; the waitlist pages (`lista/`, `en/waitlist/`, and the link page under each); and the engineering document (`engenharia/`, `en/engineering/`, styled by `site.css`), which says what is ready today. Build the site with the brand assets and check it with the unit tests:

```sh
python3 -I scripts/site/build_site.py          # -> dist/site/
python3 -I tests/run.py unit                   # tests/unit/test_site.py
```

It is hosted on Cloudflare Pages (project `nulavio`, production branch `main`). The `site` workflow (`.github/workflows/site.yml`) deploys it: on a push to `main` that changes what the build reads, or by hand (Actions → site → Run workflow). It builds the site, runs the site tests, uploads it with `wrangler` (locked in `ci/site/package-lock.json`) and checks that https://nulavio.net/ serves that build with the headers of `site/_headers` (`scripts/site/verify_live.py`). It needs `CLOUDFLARE_API_TOKEN` (an API token limited to Account → Cloudflare Pages → Edit) and the repository variable `CLOUDFLARE_ACCOUNT_ID`. The deploy job runs in the environment `site`. The token is out of reach of a workflow pushed on another branch only when that environment accepts only `main`, holds the token as its own secret and no repository secret of the same name is left: a job in an environment still reads repository secrets. Moving it there is a repository setting, the maintainer's (#182). To go back to an earlier version: Pages → `nulavio` → Deployments → that deployment → Rollback. Cloudflare's email obfuscation would rewrite the addresses in the HTML and inject a script that the site's own policy blocks, so the build wraps every page in `<!--email_off-->` (checked by `test_site`). Renew `site/.well-known/security.txt` before its `Expires` date (the unit test fails once it has passed).

The waitlist is the one piece that runs on a server: `site/_worker.js`, which Cloudflare Pages calls for `/api/*` and the two link pages only (`site/_routes.json`). It stores the address, the language, the platform and the time of each sign-up in a D1 database, plus the SHA-256 of the key of that sign-up's link, and nothing else. A sign-up is answered with a link page whose address carries the key (`/lista/link/?k=…`, `/en/waitlist/link/?k=…`): the link is the only thing that removes the entry, because knowing an address does not prove the sign-up is yours. Signing up an address that is already on the list changes nothing and hands out a key that opens nothing, so whoever signs an address up first holds the only link to it (R69). The pages have no script, so the link page is a static file that the worker serves at that address, and its form has no `action`: it posts to the address it is on. It needs that database bound to the Pages project once, by the maintainer: `wrangler d1 create nulavio-waitlist`, then Pages → `nulavio` → Settings → Bindings → Add → D1 database, variable name `WAITLIST`, and a new deployment. Until then the forms answer "the list is unavailable" and keep nothing. To read the list: `wrangler d1 execute nulavio-waitlist --remote --command "SELECT * FROM waitlist ORDER BY joined"`. To remove someone who lost the link, who signed up before links existed or whose address someone else signed up: they write to the address on the pages; answer to the address that is on the list and remove it only once a reply comes back from it (a From line proves as little as an address typed in a form), then both rows in one command: `--command "DELETE FROM waitlist WHERE email = '…'; DELETE FROM waitlist_links WHERE email = '…'"`. The forms have no CAPTCHA (it would need a script): add a rate-limiting rule for `/api/waitlist` and the link pages in the zone's WAF. Requests to the link pages count as Functions requests too: on a plan with a daily allowance, a project set to fail open serves the link page as a plain file once it is used up, and its button then fails (it never says "done"). `tests/unit/test_site.py` runs the worker under Node and replays its SQL in SQLite.

When a comparison row or a claim of the landing changes, change both languages (the tests compare their structure) and keep the comparison's date current. The link-preview images (`site/assets/og-*.png`) come from `scripts/site/og-template.html`.

## Window theme (Nulavio Horizon, Track B)

1. Change values in `docs/brand/tokens.json`, never in CSS. Run `python3 -I scripts/brand/build_tokens.py` and `python3 -I scripts/brand/contrast.py`; add a contrast pair for every new foreground/background use.
2. Map tokens to Firefox variables in `browser/branding/nulavio/content/theme/horizon.css`: geometry in the `tokens-foundation-brand-nova` layer, colours inside the accessibility guard, no literal colours, no `!important`, no security UI selectors (`tests/unit/test_horizon_theme.py` checks these).
3. Rebuild (about 1 minute), then run `tests/integration/test_horizon.py` against the build and capture before/after with `scripts/research/shell_screenshots.py`. Captures stay in the history for good (nothing is rewritten); each release measures the media against the budget of [ADR 0013](docs/adr/0013-repository-layout.md), point 3, and once it is passed new capture sets go to a repository of their own.

## Common changes

| Change | How |
|---|---|
| Add or modify a default pref | Edit `browser/config/prefs/baseline.js` with `@mode`, `@category`, `@why`, `@tradeoff`. Run the unit tests (they reject weakening prefs) and the integration tests (they reject prefs unknown to the engine). Update `docs/security/hardening.md` if relevant |
| Guard rule | `browser/config/guard-rules.json` + a unit test in `tests/unit/test_prefs_and_guard.py` |
| Extension update | `python3 -I scripts/upstream/refresh_extensions_lock.py`, review hash **and permission** changes, then `--write` (it re-copies uBlock Origin's list registry and says when a default list of `browser/distribution/content-filter.json` is gone) and run all tests |
| Design tokens | Edit `docs/brand/tokens.json`, run `scripts/brand/build_tokens.py` and `scripts/brand/contrast.py` |
| Logo/icons | Edit `scripts/brand/build_logo.py` (never hand-edit generated SVGs), then run `build_logo.py` and `build_icons.py` |
| Mockups | Edit `docs/brand/mockups/`, then run `scripts/brand/render_mockups.py` |
| New integration or trust boundary | Add a row to `docs/architecture/trust-boundaries.md` and a scenario to the threat model |
| Search provider | `PROVIDERS` in `browser/shell/modules/NulavioSearch.sys.mjs`, with URLs from the provider's own OpenSearch description; `firstRun: false` for paid services; never a public SearXNG instance. Run `test_search.py` on the build |
| Shell privileged API | Logic in `browser/shell/modules/*.sys.mjs` (validates everything it receives), a thin `experiments/<name>/parent.js`, a schema; error codes need `err_*` messages in both locales (`tests/unit/test_shell.py`) |

## Tests are part of the change

- New behaviour comes with tests that exercise it: unit tests (`tests/unit/`) for logic, and integration tests (`tests/integration/`, the real engine through Marionette) when it touches the engine, profiles, the Shell or the build.
- A bug fix comes with a test that fails without the fix, when the bug can be reproduced in a test; when it cannot, the pull request says why.
- Never delete, skip or weaken a test to make a change pass. A test that is wrong is fixed in its own commit, with the reason.
- The pull request lists the commands that were run and their results, and what was not verified ([template](.github/pull_request_template.md)). CI runs the unit tests, lint and the scanners on every push and pull request; `main` accepts only pull requests with those checks green.

## Commits and pull requests

- Conventional commits (`feat:`, `fix:`, `docs:`, `security:`, `test:`, `chore:`), small and verifiable.
- Sign off your commits (`git commit -s`, Developer Certificate of Origin).
- Branch names, how to open a pull request, and what coding agents may do: [docs/process/pull-requests.md](docs/process/pull-requests.md). Agents push only their own branch and open a pull request; they never push to `main`. They review and merge their own pull requests as that page says.
- A PR description states: what changed, how it was verified (commands + results), and what remains unverified ([template](.github/pull_request_template.md)).
- Security-relevant PRs need a second, independent review, which may be another AI reviewer. The automatic AI review comment is advisory: whoever merges decides, and an empty AI review proves nothing.

## Release automation

Releases use `<Firefox version>-<Nulavio revision>`, not SemVer: `feat:` does not select the engine version or publish a package. `release_manifest.py next-release` reserves revisions from both `packaging/release.json` and existing tags. Squash PR titles must be Conventional Commits. The existing required CI checks validate them when code is checked; the separate `pr-title` workflow also validates title edits without restarting builds when a bot edits the description. The maintainer must add its `Conventional Commit title` check to main's required checks (#195) to enforce edits at merge time.

The manual `release` workflow builds and tests on `main`, refusing to overlap an existing unpublished draft. Its summary and rehearsal artifact include notes from the exact build's public first-parent history, grouped by commit type, with breaking changes marked by `!`, commit links and a comparison with the preceding release. Nonconventional historical subjects remain under Other changes. Commit bodies are not copied. Installation, signing fingerprint and provenance instructions are added to the draft. The maintainer still approves signing in the `release` environment and reviews and publishes the GitHub draft.

Publishing a release (including a prerelease) triggers `release-metadata`. It runs code from `main`, downloads and verifies the release manifest's build-provenance attestation, derives the full version from the attested RPM entries and checks the tag, commit and engine pin, then prepares `CHANGELOG.md` and `packaging/release.json`. It never downgrades the site, changes its signing key or channel, approves or merges a PR. After the metadata PR merges, the existing site workflow updates the download pages. A failed run can be retried with **Actions → release-metadata → Run workflow**, on `main`, supplying the published tag. The `release-metadata` artifact keeps the patch and published release data for 90 days.

**One-time activation (maintainer, #195):** configure `RELEASE_METADATA_TOKEN` as a repository secret, using a dedicated fine-grained token scoped only to `nulavio/nulavio`, with Contents and Pull requests read/write. It must have no signing, administrative or advisory permission. Repository policy currently disables PR creation with `GITHUB_TOKEN`; this separate token also lets the generated PR trigger normal CI without an extra workflow approval. Do not enable auto-approval or relax branch protection. Without this secret, generation and provenance checks still run, but the summary warns that no PR was opened. Download the artifact, apply `release-metadata.patch` on a branch based on current `main`, run the normal checks, and open a PR. A retry reuses an open PR; an orphan branch is reused only when its entire tree matches the generated tree, otherwise the run fails for inspection rather than force-pushing.

The security changelog remains an evidence-backed editorial review: commit categories do not establish vulnerabilities fixed, advisory disclosure permission, user impact or an update SLA. Review `docs/security/changelog.md` before publication, and publish private advisories only through the maintainer's existing process. Flathub submission still depends on the admission work tracked in #90; the release workflow prepares its manifest as an artifact.

## Reporting vulnerabilities

Do **not** open public issues for security problems. See [SECURITY.md](SECURITY.md).
