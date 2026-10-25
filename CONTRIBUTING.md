# Contributing to Nulavio

Thanks for helping. Nulavio is a security-sensitive project, so the rules below are strict and short.

## Non-negotiables (reviewers will block on these)

1. Never disable or weaken: sandboxing, site isolation, TLS/certificate checks, extension signatures, Safe Browsing, Remote Settings, or security updates. Not even "temporarily" and not even in CI.
2. No telemetry and no remote service operated by Nulavio. Nothing may send history, URLs, credentials or fingerprints anywhere.
3. No custom cryptography, authentication or password storage.
4. Never use undocumented vendor APIs for password managers; never read, scrape or export vault data.
5. Separate implemented / prototype / planned in docs and PR descriptions. Never claim immunity or "100%" anything.
6. No Mozilla or third-party trademarks or art in Nulavio assets.

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

Tests never use your real profile: integration tests set `NULAVIO_HOME` to a temporary directory and use disposable engine profiles. Never put real credentials in tests.

## Track B (building Nulavio from source)

```sh
scripts/build/build_nulavio.sh 158.0.1   # verified source -> branding -> patches -> container build
```

Everything happens in rootless podman containers and in `~/.cache/nulavio-build` (about 23 GB). Nothing is installed on the host.

The build needs **your own** Google Safe Browsing key; without it phishing and malware protection would be inactive, so the script stops. Create a Google Cloud project, enable "Safe Browsing API", create an API key restricted to that API, then save it without echoing it:

```sh
install -d -m 700 ~/.config/nulavio-build
(umask 077; read -rs -p "Safe Browsing key: " k && printf '%s\n' "$k" > ~/.config/nulavio-build/google-safebrowsing.key; unset k; echo)
```

Never commit it or paste it into issues or logs. For a local experiment only, `NULAVIO_ALLOW_NO_SAFEBROWSING_KEY=1` builds without it; such a build must never be shared. See [docs/architecture/build.md](docs/architecture/build.md). Patches go in `browser/patches/` with `Owner:` and `Upstream:` headers, listed in `series`. Prefer prefs, policies, branding or built-in add-ons over patches.

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

## Commits and pull requests

- Conventional commits (`feat:`, `fix:`, `docs:`, `security:`, `test:`, `chore:`), small and verifiable.
- Sign off your commits (`git commit -s`, Developer Certificate of Origin).
- A PR description states: what changed, how it was verified (commands + results), and what remains unverified.
- Security-relevant PRs need a second reviewer.

## Reporting vulnerabilities

Do **not** open public issues for security problems. See [SECURITY.md](SECURITY.md).
