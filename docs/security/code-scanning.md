# Code scanning

What checks the code, the workflows and the history for security problems, where each check runs, and what to do when one fails. Status: **implemented** (2026-10-27). The checks run in the CI job `security` (`.github/workflows/ci.yml`) on every push to `main`, every pull request and the weekly scheduled run, and locally with one command.

These scanners add to what already runs in the `checks` job: ruff with its `S` rules (the Bandit checks), the unit tests that reject weakening prefs, unpinned actions and committed secrets (`tests/unit/test_prefs_and_guard.py`, `tests/unit/test_repo_hygiene.py`), and Gradle's dependency verification for the Companion app.

## The checks

| Check | Tool (licence) | Reads | Configuration |
|---|---|---|---|
| `actionlint` | actionlint 1.7.12 (MIT) | The workflows: syntax, expressions, and ShellCheck on every `run:` block | none |
| `zizmor` | zizmor 1.31.1 (MIT) | The workflows, for security problems: template injection, credentials left in the checkout, broad permissions, dangerous triggers. In CI also its online audits, with the job's read-only token: is each pinned SHA a commit of the action's own repository, and does a pinned action have a known advisory | none |
| `gitleaks` | gitleaks 8.30.1 (MIT) | Every commit of the history, with gitleaks' default rules and one Nulavio rule (private key, keystore or keyring files) | `.gitleaks.toml`, `.gitleaksignore` |
| `shellcheck` | ShellCheck 0.11.0 (GPL-3.0, run as a separate program) | Every shell script in the repository: files ending in `.sh` and files starting with a `sh`, `bash`, `dash` or `ksh` `#!` line (13 today) | directives in the scripts |
| `opengrep` | Opengrep 1.32.0 (LGPL-2.1) | Nulavio's own rules (below) on the code, including `tests/` | `ci/sast/nulavio-rules.yml`, `.semgrepignore` |
| `opengrep-rules` | Opengrep 1.32.0 | The same rules on their test cases: each must match its "ruleid" lines and no other line | `tests/fixtures/sast/` |

Every tool is a release binary for Linux x86_64, pinned by version and SHA-256 in `scripts/security/fetch_tools.sh`. The script checks the download against the pinned SHA-256 on every run and extracts the program again, so a changed cache is never executed. Nothing is installed system-wide. Opengrep unpacks its own libraries into a new temporary directory on each run and runs without its version check; it needs no network (tested with the network cut off).

The job is blocking: a finding fails it. Each check is its own step and runs even when an earlier one failed, so one run shows every finding. The job has `contents: read` only, keeps no credentials in the checkout, and takes about a minute.

## Run them locally

```sh
scripts/security/scan.sh                      # every check
scripts/security/scan.sh gitleaks shellcheck  # some of them
scripts/security/scan.sh shell-files          # the files the shellcheck check reads
```

The tools are cached in `~/.cache/nulavio-security-tools` (or `$NULAVIO_SECURITY_TOOLS`). Without `GH_TOKEN` in the environment, zizmor runs its offline audits only. Run them before pushing a change to workflows, shell scripts, privileged JavaScript, the launcher or the Companion app.

## Nulavio's rules

`ci/sast/nulavio-rules.yml` turns the [non-negotiables](../../CONTRIBUTING.md#non-negotiables-reviewers-will-block-on-these) into checks. No rules are downloaded at run time: community rule packs are code that changes without review.

| Rule | Rejects |
|---|---|
| `nulavio-py-shell-command` | `shell=True`, `os.system`, `os.popen` and the other ways of running a command through a shell |
| `nulavio-py-cleartext-request` | `urllib` and `http.client` requests over `http://` to anything but the loopback interface |
| `nulavio-py-tls-verification-off` | Unverified SSL contexts, `check_hostname = False`, `CERT_NONE`, contexts without a protocol, TLS below 1.2 |
| `nulavio-py-secret-in-argv` | A password, passphrase, token or key passed as a command-line argument (readable in `/proc/<pid>/cmdline`) |
| `nulavio-py-engine-sandbox-env` | Starting the engine with `MOZ_*SANDBOX*`, `MOZ_ALLOW_DOWNGRADE`, `MOZ_MARIONETTE*` or `MOZ_REMOTE*` |
| `nulavio-js-html-sink` | `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `srcdoc`, `on*` attributes in `browser/` |
| `nulavio-js-dynamic-code` | `eval`, `new Function`, string timers, `loadSubScript`, `evalInSandbox`, module imports from a computed URL |
| `nulavio-js-weakening-pref` | Writing a pref that weakens sandboxing, site isolation, signatures, TLS, Safe Browsing, Remote Settings or updates, or that enables remote control or privileged consoles (the same list as `FORBIDDEN` in `tests/unit/test_prefs_and_guard.py`) |
| `nulavio-js-cleartext-request` | `fetch`, `WebSocket`, `EventSource` and `XMLHttpRequest` to `http://` or `ws://` hosts other than loopback |
| `nulavio-java-weak-crypto` | ECB, DES, RC2, RC4, Blowfish, MD5, SHA-1, provider-default `"AES"`, `SHA1PRNG` and `java.util.Random` in `android/` |
| `nulavio-java-tls-verification-off` | Trust managers and host-name verifiers that accept everything |
| `nulavio-android-unsafe-storage-or-manifest` | World-readable files, cleartext traffic, `debuggable` or `allowBackup` in the Companion app |
| `nulavio-verification-bypass` | `curl -k`, `curl … \| sh`, `--no-check-certificate`, `gpgcheck=0`, `--nogpgcheck`, `trusted=yes`, `pip install` without `--require-hashes`, Gradle dependency verification off, and similar, in scripts, CI, containers, packaging and Gradle files |
| `nulavio-sh-secret-in-argv` | `--password=…`, `--token …`, `sshpass -p` and similar in shell, CI and packaging files |

To add or change a rule, add test cases in `tests/fixtures/sast/nulavio-rules.<ext>`: a `ruleid: <id>` comment above each line that must match and an `ok: <id>` comment above lines that must not. Then run `scripts/security/scan.sh opengrep-rules opengrep`. `tests/unit/test_security_tooling.py` checks that every rule has both kinds of cases.

## When a check fails

1. Read the finding. If it is real, fix the code. A real secret in a commit stays in the history and in every clone: revoke or rotate it first, then remove it.
2. If it is a false positive, suppress that one finding, with the reason, where the next reader will see it:

| Tool | How |
|---|---|
| Opengrep | `# nosemgrep: <rule id> -- <why this line is safe>` on the line (`//` in JavaScript and Java). The unit tests reject a suppression without a rule id and a reason |
| gitleaks | The finding's fingerprint (`commit:file:rule:line`, printed by gitleaks) in `.gitleaksignore`, under a comment with the reason. `.gitleaks.toml` allowlists only documented test fixtures, by exact file and value |
| ShellCheck | `# shellcheck disable=SC<number> # <reason>` on the line before the command |
| zizmor | `# zizmor: ignore[<audit>] <reason>` on the line |
| actionlint | Fix it; actionlint reports real errors in the workflow |

Never switch a rule or a check off, leave a directory out of a scan, or make the job non-blocking to get past a finding.

## Updating a tool

Change the version, URL and SHA-256 in `scripts/security/fetch_tools.sh` together, in one commit that says why. Take the SHA-256 from the release's checksum file where there is one (actionlint, gitleaks) and compare it with the digest GitHub shows for the asset. Read the release notes: new checks can bring new findings, which the same commit fixes or suppresses. Wait about a week after a release unless it fixes a problem that affects Nulavio. Opengrep 1.33.0 came out on 2026-10-27 and is not adopted yet for that reason.

## Decisions

- **No CodeQL.** GitHub's code scanning for a private repository needs GitHub Advanced Security, and the CodeQL licence does not allow it otherwise. The Opengrep rules and ruff cover the checks that matter here.
- **No community rule packs** (Semgrep registry or others) in CI: they are downloaded unpinned at run time and change without review.
- **No Bandit.** ruff's `S` rules are Bandit's checks and already run on every push.
- **Dependency vulnerabilities** (OSV.dev) are checked separately, by a standard-library script against the OSV.dev API, not by these scanners.
- **No SARIF upload.** Uploading results needs GitHub code scanning (Advanced Security on a private repository); the findings are in the job log.
- **No `paths-ignore` for documentation-only changes.** The unit tests read `docs/` (design tokens, links, claims), and gitleaks must see every commit, including those that only change documentation. The security job costs about a minute.
- **Artifact retention.** The CI SBOM is kept 14 days and the integration artifacts 7 days (GitHub's default is 90). Artifacts count against the plan's storage, and releases keep their own SBOMs.

## First run (2026-10-27)

Counts on the repository as of commit 40149a2, before the fixes in the same change:

| Check | Found | Outcome |
|---|---|---|
| actionlint | 0 | — |
| zizmor (default persona) | 0 (7 lower-severity findings are only shown with `--persona pedantic`) | Of the 7: `upstream.yml` got a job name and a concurrency group; 5 are `${{ matrix.image }}` in `run:` blocks of the integration job (values fixed in the matrix, so not exploitable). Moving them into an environment variable is proposed to the maintainer |
| gitleaks (75 commits) | 16, all false positives | 2 are the nv1 test vectors (bytes 00…1f), 2 the AI tests' artificial keys: allowlisted by file and exact value. 12 are the words after "API key." in a `mozconfig` comment and after "Safe Browsing key:" in a test message, in 6 commits: fingerprinted in `.gitleaksignore`. 0 after |
| ShellCheck (13 scripts; CI checked 2 before) | 7 | 1 fixed (quoting in `make_deb.sh`); 3 suppressed with the reason in `rehearse_release.sh` (`ls -t` to pick the newest build output; `$0`/`$1` expanded by the inner `bash -c`); 3 in `browser/branding/nulavio/configure.sh`, which Mozilla's build reads as variables (shell directive added). 0 after |
| Opengrep (14 rules, 211 files) | 2, both in tests | The test harness enables Marionette for its throwaway sessions, and a unit test builds the hostile environment `launch_env()` must strip: suppressed with the reason. 0 in the launcher, scripts, Shell, branding modules, Companion app, CI and packaging. Rule test cases: 14/14 pass |

## Next steps (not done)

- Verify Opengrep's Sigstore signature, not only its SHA-256, when bumping it (needs a pinned `cosign`).
- Make `security` a required check once `main` has branch protection (not available for private repositories on the free plan). Until then the job reports problems after the push; it cannot stop one.
- If the repository becomes public or gets Advanced Security: turn on secret scanning with push protection and private vulnerability reporting, and upload the scanners' SARIF.
- Run zizmor with `--persona pedantic` in CI once the integration job no longer expands `${{ matrix.image }}` in `run:` blocks.
- A local pre-commit hook for `gitleaks git --pre-commit --staged`, so a secret is caught before it becomes a commit.
- Shell commands inside Containerfiles (`RUN`) and the RPM spec are not checked by ShellCheck yet.
