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

The pages are static (`site/`): no JavaScript in them, no third-party resources, no cookies, security headers in `site/_headers`. There are three kinds: the landing (`index.html`, `en/index.html`, styled by `landing.css`), which presents Nulavio as it is meant to ship and carries the comparison and the waitlist form; the waitlist pages (`lista/`, `en/waitlist/`); and the engineering document (`engenharia/`, `en/engineering/`, styled by `site.css`), which says what is ready today. Build the site with the brand assets and check it with the unit tests:

```sh
python3 -I scripts/site/build_site.py          # -> dist/site/
python3 -I tests/run.py unit                   # tests/unit/test_site.py
```

It is hosted on Cloudflare Pages (project `nulavio`, production branch `main`). The `site` workflow (`.github/workflows/site.yml`) deploys it: on a push to `main` that changes what the build reads, or by hand (Actions → site → Run workflow). It builds the site, runs the site tests, uploads it with `wrangler` (locked in `ci/site/package-lock.json`) and checks that https://nulavio.net/ serves that build with the headers of `site/_headers` (`scripts/site/verify_live.py`). It needs the repository secret `CLOUDFLARE_API_TOKEN` (an API token limited to Account → Cloudflare Pages → Edit) and the repository variable `CLOUDFLARE_ACCOUNT_ID`. To go back to an earlier version: Pages → `nulavio` → Deployments → that deployment → Rollback. Cloudflare's email obfuscation would rewrite the addresses in the HTML and inject a script that the site's own policy blocks, so the build wraps every page in `<!--email_off-->` (checked by `test_site`). Renew `site/.well-known/security.txt` before its `Expires` date (the unit test fails once it has passed).

The waitlist is the one piece that runs on a server: `site/_worker.js`, which Cloudflare Pages calls for `/api/*` only (`site/_routes.json`). It stores the address, the language, the platform and the time of each sign-up in a D1 database, and nothing else. It needs that database bound to the Pages project once, by the maintainer: `wrangler d1 create nulavio-waitlist`, then Pages → `nulavio` → Settings → Bindings → Add → D1 database, variable name `WAITLIST`, and a new deployment. Until then the forms answer "the list is unavailable" and keep nothing. To read the list: `wrangler d1 execute nulavio-waitlist --remote --command "SELECT * FROM waitlist ORDER BY joined"`. The forms have no CAPTCHA (it would need a script): add a rate-limiting rule for `/api/waitlist` in the zone's WAF. `tests/unit/test_site.py` runs the worker under Node and replays its SQL in SQLite.

When a comparison row or a claim of the landing changes, change both languages (the tests compare their structure) and keep the comparison's date current. The link-preview images (`site/assets/og-*.png`) come from `scripts/site/og-template.html`.

## Window theme (Nulavio Horizon, Track B)

1. Change values in `docs/brand/tokens.json`, never in CSS. Run `python3 -I scripts/brand/build_tokens.py` and `python3 -I scripts/brand/contrast.py`; add a contrast pair for every new foreground/background use.
2. Map tokens to Firefox variables in `browser/branding/nulavio/content/theme/horizon.css`: geometry in the `tokens-foundation-brand-nova` layer, colours inside the accessibility guard, no literal colours, no `!important`, no security UI selectors (`tests/unit/test_horizon_theme.py` checks these).
3. Rebuild (about 1 minute), then run `tests/integration/test_horizon.py` against the build and capture before/after with `scripts/research/shell_screenshots.py`.

## Common changes

| Change | How |
|---|---|
| Add or modify a default pref | Edit `browser/config/prefs/baseline.js` with `@mode`, `@category`, `@why`, `@tradeoff`. Run the unit tests (they reject weakening prefs) and the integration tests (they reject prefs unknown to the engine). Update `docs/security/hardening.md` if relevant |
| Guard rule | `browser/config/guard-rules.json` + a unit test in `tests/unit/test_prefs_and_guard.py` |
| Extension update | `python3 -I scripts/upstream/refresh_extensions_lock.py`, review hash **and permission** changes, then `--write` and run all tests |
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
- Branch names, how to open a pull request, and what coding agents may do: [docs/process/pull-requests.md](docs/process/pull-requests.md). Agents push only their own branch and open a pull request; they never push to `main`, merge or approve.
- A PR description states: what changed, how it was verified (commands + results), and what remains unverified ([template](.github/pull_request_template.md)).
- Security-relevant PRs need a second reviewer. The AI review comment is advisory: a person decides, and an empty AI review proves nothing.

## Reporting vulnerabilities

Do **not** open public issues for security problems. See [SECURITY.md](SECURITY.md).
