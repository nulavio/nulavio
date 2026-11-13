# Code scanning

What checks the code, the workflows and the history for security problems, where each check runs, and what to do when one fails. Status: **implemented** (2026-10-27). The checks run in the CI job `security` (`.github/workflows/ci.yml`) on every push to `main`, every pull request and the weekly scheduled run, and locally with one command.

These scanners add to what already runs in the `checks` job: ruff with its `S` rules (the Bandit checks), the unit tests that reject weakening prefs, unpinned actions and committed secrets (`tests/unit/test_prefs_and_guard.py`, `tests/unit/test_repo_hygiene.py`), and Gradle's dependency verification for the Companion app.

## The checks

| Check | Tool (licence) | Reads | Configuration |
|---|---|---|---|
| `actionlint` | actionlint 1.7.12 (MIT) | The workflows: syntax, expressions, and ShellCheck on every `run:` block | none |
| `zizmor` | zizmor 1.31.1 (MIT) | The workflows, for security problems: template injection, credentials left in the checkout, broad permissions, dangerous triggers. In CI also its online audits, with the job's read-only token: is each pinned SHA a commit of the action's own repository, and does a pinned action have a known advisory | none |
| `gitleaks` | gitleaks 8.30.1 (MIT) | Every commit of every branch the clone has, with gitleaks' default rules and one Nulavio rule (private key, keystore, keyring or password database files, such as `.jks`, `.p12`, `.pem`, `.gpg` or `.kdbx`). This includes what a merge's resolution added (also in an octopus merge), a symlink replaced by a file, and binary files or files that `.gitattributes` marks as binary, which gitleaks' own `git log` leaves out. Inline `gitleaks:allow` comments are ignored: every exception is in the two files on the right | `.gitleaks.toml`, `.gitleaksignore` |
| `shellcheck` | ShellCheck 0.11.0 (GPL-3.0, run as a separate program) | Every shell script in the repository, at every severity: files ending in `.sh` and files starting with a `sh`, `bash`, `dash` or `ksh` `#!` line (14 today) | directives in the scripts |
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

The tools are cached in `~/.cache/nulavio-security-tools` (or `$NULAVIO_SECURITY_TOOLS`). Without `GH_TOKEN` in the environment, zizmor runs its offline audits only. Run them before pushing a change to workflows, shell scripts, privileged JavaScript, the launcher or the Companion app. They take a few seconds.

### Secrets before the commit (optional hook)

Commits go straight to `main`, and the plan has no push protection, so CI finds a secret only after it is on GitHub, when it must already be revoked. The pre-commit hook in `scripts/git-hooks/` runs gitleaks on the staged changes, binary files included unless a committed `.gitattributes` marks them `binary` or `-diff` (the CI history scan reads those too) (`scripts/security/scan.sh staged`, under a second) and refuses the commit if it finds one. It is off by default; turn it on in each clone:

```sh
git config core.hooksPath scripts/git-hooks
```

This is git's local configuration, nothing changes on GitHub. `git commit --no-verify` skips it; CI still scans every commit. Git reads hooks from one directory, so the same command turns on the [pre-push hook](../process/pull-requests.md) that refuses pushes to `main`; while commits still go straight to `main`, push there with `NULAVIO_ALLOW_MAIN_PUSH=1 git push`.

## Nulavio's rules

`ci/sast/nulavio-rules.yml` turns the [non-negotiables](../../CONTRIBUTING.md#non-negotiables-reviewers-will-block-on-these) into checks. No rules are downloaded at run time: community rule packs are code that changes without review.

| Rule | Rejects |
|---|---|
| `nulavio-py-shell-command` | `shell=True`, `os.system`, `os.popen` and the other ways of running a command through a shell |
| `nulavio-py-cleartext-request` | `urllib` and `http.client` requests over `http://` to anything but the loopback interface |
| `nulavio-py-tls-verification-off` | Unverified SSL contexts, `check_hostname = False`, `CERT_NONE`, contexts without a protocol, TLS below 1.2, and replacing `ssl._create_default_https_context`, which turns the checks off for every later request |
| `nulavio-py-secret-in-argv` | A password, passphrase, token or key passed as a command-line argument (readable in `/proc/<pid>/cmdline`) |
| `nulavio-py-engine-sandbox-env` | Starting the engine with `MOZ_*SANDBOX*`, `MOZ_ALLOW_DOWNGRADE`, `MOZ_MARIONETTE*` or `MOZ_REMOTE*` |
| `nulavio-js-html-sink` | `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `srcdoc`, `on*` attributes in `browser/` |
| `nulavio-js-dynamic-code` | `eval`, `new Function`, string timers, `loadSubScript`, `evalInSandbox`, module imports from a computed URL |
| `nulavio-js-weakening-pref` | Writing a pref that weakens sandboxing, site isolation, signatures, TLS, Safe Browsing, Remote Settings or updates, or that enables remote control or privileged consoles (the same list as `FORBIDDEN` in `tests/unit/test_prefs_and_guard.py`) |
| `nulavio-js-cleartext-request` | `fetch`, `WebSocket`, `EventSource` and `XMLHttpRequest` to `http://` or `ws://` hosts other than loopback |
| `nulavio-java-weak-crypto` | ECB, DES, RC2, RC4, Blowfish, MD5, SHA-1, provider-default `"AES"`, `SHA1PRNG` and `java.util.Random` in `android/` |
| `nulavio-java-tls-verification-off` | Trust managers and host-name verifiers that accept everything |
| `nulavio-java-default-locale` | `String.format`, `formatted`, `toLowerCase` and `toUpperCase` without a `Locale` in `android/`: in Persian, Arabic or Hindi they write other digits, so the pairing code and the canonical JSON would differ from the desktop's (found and fixed in `Nv1.sasDigits` on 2026-10-27) |
| `nulavio-android-unsafe-storage-or-manifest` | World-readable files, cleartext traffic, `debuggable` or `allowBackup` in the Companion app |
| `nulavio-verification-bypass` | `curl -k`, `curl … \| sh` (also when the command goes on over lines ending in `\`), `--no-check-certificate`, `gpgcheck=0`, `--nogpgcheck`, `trusted=yes`, `pip install` without `--require-hashes`, Gradle dependency verification off (`--dependency-verification`, `-F`), and similar, in scripts, CI, containers, packaging and Gradle files |
| `nulavio-ci-writes-gradle-verification` | `--write-verification-metadata` (or `-M`) in workflows and CI files: only a person regenerates the Companion's trust anchor, and reviews it |
| `nulavio-sh-secret-in-argv` | `--password=…`, `--token …`, `sshpass -p` and similar in shell, CI and packaging files |

To add or change a rule, add test cases in `tests/fixtures/sast/nulavio-rules.<ext>`: a `ruleid: <id>` comment above each line that must match and an `ok: <id>` comment above lines that must not. Then run `scripts/security/scan.sh opengrep-rules opengrep`. `tests/unit/test_security_tooling.py` checks that every rule has both kinds of cases.

## When a check fails

1. Read the finding. If it is real, fix the code. A real secret in a commit stays in the history and in every clone: revoke or rotate it first, then remove it.
2. If it is a false positive, suppress that one finding, with the reason, where the next reader will see it:

| Tool | How |
|---|---|
| Opengrep | `# nosemgrep: <rule id> -- <why this line is safe>` on the line (`//` in JavaScript and Java), one rule id only. Opengrep also obeys `nosem`, `noopengrep` and other spellings in any case, and a bare one silences every rule on the line: the unit tests reject any form but this one, in every file Opengrep reads, `.github/` included |
| gitleaks | The finding's fingerprint (`commit:file:rule:line`, printed by gitleaks) in `.gitleaksignore`, under a comment with the reason. In a merge, a file with a conflict is named `b/<path>` in the finding and in its fingerprint. `.gitleaks.toml` allowlists only documented test fixtures, by exact file (with or without that `b/`) and value |
| ShellCheck | `# shellcheck disable=SC<number> # <reason>` on the line before the command |
| zizmor | `# zizmor: ignore[<audit>] <reason>` on the line |
| actionlint | Fix it; actionlint reports real errors in the workflow |

Never switch a rule or a check off, leave a directory out of a scan, or make the job non-blocking to get past a finding.

## Updating a tool

Change the version, URL and SHA-256 in `scripts/security/fetch_tools.sh` together, in one commit that says why. Take the SHA-256 from the release's checksum file where there is one (actionlint, gitleaks) and compare it with the digest GitHub shows for the asset. Read the release notes: new checks can bring new findings, which the same commit fixes or suppresses. Wait about a week after a release unless it fixes a problem that affects Nulavio. Opengrep 1.33.0 came out on 2026-10-27 and is not adopted yet for that reason. The daily [dependency watch](dependency-updates.md) does not check these tools yet, so look at each one's security advisories when bumping it.

## LESIS (external, supporter)

[LESIS](https://lesis.lat) supports Nulavio with free use of its vulnerability platform, which scans code and secrets automatically and also takes manual findings and produces reports. It runs outside CI and is not a required check: its results reach the maintainer and are handled like any other report ([SECURITY.md](../../SECURITY.md)), privately until a fix ships.

## Dynamic analysis: AddressSanitizer

The `asan` workflow (`.github/workflows/asan.yml`) builds the pinned Firefox with Nulavio's patches and AddressSanitizer (`browser/build/mozconfig.asan`, appended through `NULAVIO_MOZCONFIG_EXTRA`) on a Blacksmith runner, monthly and by hand (after an engine update), and runs the whole integration suite against it. AddressSanitizer stops the process at the first memory error in C or C++ (out-of-bounds access, use after free, double free) and writes a report; the job fails on any report or failing test and puts the first lines of each report in the summary. Leak detection is off, as in Mozilla's own ASan builds.

When it fails with a report: download the `asan-reports` artifact, find the first frame in Nulavio's code (patches 0006 and 0010 are the C++ Nulavio adds) or in Gecko. A frame in a Nulavio patch is our bug: fix it, with a test. One only in Gecko goes to Mozilla privately (Bugzilla, security group); record it in [residual risks](residual-risks.md) until a Firefox release fixes it. The variant is never packaged: `rehearse_release.sh` refuses to run with `NULAVIO_MOZCONFIG_EXTRA` set.

## OpenSSF Scorecard

The `scorecard` workflow (`.github/workflows/scorecard.yml`) runs [OpenSSF Scorecard](https://scorecard.dev) on every push to `main`, weekly and when branch protection changes. It rates how the repository is maintained (branch protection, pinned dependencies, token permissions, signed releases, code review, fuzzing and others), publishes the score to scorecard.dev for the README badge, and uploads its findings to the Security tab under the category `scorecard`. It needs no secret; without an admin token the Branch-Protection check sees only what a public token can read, so that check may score lower than the protection actually configured. A low check is a prompt to look, not a defect by itself: read the finding, then fix it or record why it does not apply.

## Alerts in the Security tab (CodeQL and Scorecard)

CodeQL (GitHub's default setup) and Scorecard report in the repository's Security tab, which only people with write access see. Neither is a required check. An alert is settled in one of three ways, and never left open without a reason written here:

- **Fixed** by a pull request; the alert closes by itself when the fix is on `main`. If the alert describes a vulnerability someone could use, the fix is private first ([SECURITY.md](../../SECURITY.md)).
- **Dismissed** in the tab, with the reason typed into the dismissal: "false positive" when the code does not do what the rule assumes, "used in tests" for test code that does it on purpose, "won't fix" for something the project decided to keep, with where that decision is written.
- **Left open** when it states a gap that is real and not closed yet.

How the alerts open on 2026-11-13 were settled (20, on `main` at `bbe8046`):

| Alert | Where | Settled |
|---|---|---|
| CodeQL `py/redos` | `scripts/release/upstream_issue.py`, the marker pattern | Fixed: the pattern could be matched in many ways, and a long marker without its end took time that doubled with each pair. Only issues the workflow's own bot opened are read, so nobody outside could feed it one |
| CodeQL `py/insecure-protocol` | `tests/lib/doh_server.py` | Fixed: the test server asks for TLS 1.2 or later |
| CodeQL `js/client-side-unvalidated-url-redirection` | `browser/shell/passwords/lookalike.js` | False positive: the Shell has no web-accessible page, and this one is opened only by privileged code (`NulavioLookalikeParent`), which writes its address from the document the engine was loading. "Go to the real site" builds its address from a name held to letters, digits, dots and hyphens; "continue" goes back to that document's own http(s) address |
| CodeQL `py/clear-text-logging-sensitive-data` | `launcher/nulavio_launcher/vault/phone_session.py` | False positive: not a log. As the browser starts it (`spawn_phone_session`), the helper answers on a pipe, with the pairing invitation the screen then shows as a QR code. Run by hand in a terminal, the hidden subcommand would print that invitation there |
| CodeQL `py/overly-large-range` (3) | `scripts/ci/post_ai_review.py` | False positive: the ranges are the ones meant (control characters other than tab and line feed, tag characters, variation selectors), and `test_post_ai_review` checks them |
| CodeQL `py/bad-tag-filter`, `py/clear-text-storage-sensitive-data` (4), `py/bind-socket-all-network-interfaces`, `py/http-response-splitting` | `tests/` | Used in tests: a pattern that reads a page the test built, stand-in secrets in a temporary directory, a listener a real announcement can reach for a few seconds, a fixture's redirect |
| Scorecard Dangerous-Workflow | `.github/workflows/ai-review.yml` | False positive for this workflow: the pull request's head is checked out into its own path only so git can make the diff, and nothing from it runs ([how it is locked down](../process/pull-requests.md#how-it-is-locked-down), `test_pull_request_head_is_checked_out_only_into_its_own_path`) |
| Scorecard Binary-Artifacts | `android/gradle/wrapper/gradle-wrapper.jar` | Won't fix: Gradle's own wrapper. `test_security_tooling` checks it is the file Gradle published, and the distribution it downloads is pinned by SHA-256 |
| Scorecard Code-Review | no file | Won't fix: one maintainer, whose account the agents also use, so GitHub records no approval. The review is a recorded comment ([R62](residual-risks.md)) |
| Scorecard Vulnerabilities | no file | Won't fix for now: the nine advisories are tooling of the Android Gradle plugin, none in the APK, each with a reason and an expiry in [`vulnerability-exceptions.json`](vulnerability-exceptions.json) ([R53](residual-risks.md)) |
| Scorecard Fuzzing | no file | Left open: nothing is fuzzed yet |
| Scorecard Maintained | no file | Left open: it says the repository is younger than 90 days, and stops saying so on 2027-01-23 |

## Decisions

- **CodeQL by GitHub's default setup** since 2026-11-10, when the repository became public (before that, code scanning needed Advanced Security). It is configured in the repository settings, not in a workflow, and runs alongside the Opengrep rules and ruff.
- **No community rule packs** (Semgrep registry or others) in CI: they are downloaded unpinned at run time and change without review.
- **No Bandit.** ruff's `S` rules are Bandit's checks and already run on every push.
- **Dependency vulnerabilities** (OSV.dev) are checked separately, by a standard-library script against the OSV.dev API, not by these scanners.
- **SARIF.** Only Scorecard and CodeQL upload findings to the Security tab. gitleaks and Opengrep still report in the job log (see Next steps).
- **No `paths-ignore` for documentation-only changes.** It applies to a whole workflow, and the unit tests read `docs/` (design tokens, links, the claims in `test_brand_and_docs.py`), so a documentation change can fail them. A secret pasted into a document would also wait for the next code change to be found. The security job costs about a minute per push. Only the engine integration matrix, the most expensive job, is skipped when every file changed since the last tested tree is Markdown (`scripts/ci/needs_integration.py`, job `changes`): no integration test reads a Markdown file's content. For a pull request the last tested tree is its base; for a push to `main` it is the head of the last successful CI run on `main`, not the previous push, because a newer push cancels the run of the previous one. Anything else, an unknown base, or the weekly scheduled run (which a push never cancels) means it runs.
- **A separate job, not more steps in `checks`.** The scanners run in parallel with the other jobs and fail on their own, with `contents: read` and a token only in zizmor's step. Each check is its own step. The downloads (about 70 MB of release archives) and their checks take a few seconds.
- **Artifact retention.** The CI SBOM is kept 14 days and the integration artifacts 7 days (GitHub's default is 90). Artifacts count against the plan's storage, and releases keep their own SBOMs.
- **Community rule packs only as a manual audit.** On 2026-10-27 the Semgrep registry packs for Python, JavaScript, Java, Android, Bash, Dockerfiles and GitHub Actions gave 47 findings with Opengrep and no true positive; their licence also forbids redistributing them. Before a major release, a maintainer may run them once from a throwaway checkout of `semgrep/semgrep-rules` (never committed) and turn anything worth keeping into a Nulavio rule.

## First run (2026-10-27)

Counts on the repository as of commit 40149a2, before the fixes in the same change:

| Check | Found | Outcome |
|---|---|---|
| actionlint | 0 | — |
| zizmor (default persona) | 0 (7 lower-severity findings are only shown with `--persona pedantic`) | Of the 7: `upstream.yml` got a job name and a concurrency group; 5 are `${{ matrix.image }}` in `run:` blocks of the integration job (values fixed in the matrix, so not exploitable). Moving them into an environment variable is proposed to the maintainer |
| gitleaks (75 commits) | 16, all false positives | 2 are the nv1 test vectors (bytes 00…1f), 2 the AI tests' artificial keys: allowlisted by file and exact value. 12 are the words after "API key." in a `mozconfig` comment and after "Safe Browsing key:" in a test message, in 6 commits: fingerprinted in `.gitleaksignore`. 0 after |
| ShellCheck (13 scripts; CI checked 2 before) | 7 | 1 fixed (quoting in `make_deb.sh`); 3 suppressed with the reason in `rehearse_release.sh` (`ls -t` to pick the newest build output; `$0`/`$1` expanded by the inner `bash -c`); 3 in `browser/branding/nulavio/configure.sh`, which Mozilla's build reads as variables (shell directive added). 0 after |
| Opengrep (14 rules, 211 files) | 2, both in tests | The test harness enables Marionette for its throwaway sessions, and a unit test builds the hostile environment `launch_env()` must strip: suppressed with the reason. 0 in the launcher, scripts, Shell, branding modules, Companion app, CI and packaging. Rule test cases: 14/14 pass |

A mutation test on a throwaway copy put one violation in each kind of file the rules cover (a Shell page, a privileged `.sys.mjs` module, the baseline and branding prefs, Java, the Android manifest, a build script, the launcher, a workflow and a test): Opengrep found all ten.

Again on 2026-10-27, over the branches then waiting to be merged (85 commits): gitleaks found one more false positive, the fingerprint of Mozilla's release-signing subkey in a test (public, in Firefox's `KEY` file), allowlisted by file and value. Opengrep flagged prose that names `curl | sh` in a Markdown file under `.github/`, so the two generic rules now skip `*.md`.

## Next steps (not done)

- Verify Opengrep's Sigstore signature, not only its SHA-256, when bumping it (needs a pinned `cosign`).
- ~~Make `security` a required check~~: done, it is required by `main`'s branch protection (read 2026-11-10). It still runs after a branch is pushed, so a secret pushed to a branch is on GitHub before the job reports it; only push protection (public repository or Advanced Security) stops that.
- ~~Turn on secret scanning with push protection and private vulnerability reporting~~: done on 2026-11-10, when the repository became public, with CodeQL's default setup. Still open: upload the scanners' SARIF (gitleaks, Opengrep) so their findings show in the Security tab.
- Run zizmor with `--persona pedantic` in CI once the integration job no longer expands `${{ matrix.image }}` in `run:` blocks.
- Repository settings (the maintainer's decision; nothing here changes them): require actions pinned by full SHA and allow only GitHub's own actions, so GitHub refuses an unpinned action before it runs, where today `tests/unit/test_repo_hygiene.py` notices it after the commit:
  `gh api -X PUT repos/nulavio/nulavio/actions/permissions -F enabled=true -f allowed_actions=selected -F sha_pinning_required=true`, then
  `gh api -X PUT repos/nulavio/nulavio/actions/permissions/selected-actions -F github_owned_allowed=true -F verified_allowed=false`.
  If "selected actions" is not offered for a private repository on the free plan, set `sha_pinning_required` alone.
- Patches to the engine: `./mach lint -l eslint -l file-whitespace` on the files the patches touch, and `./mach clang-format` on the C++ one, as a step of `scripts/release/rehearse_release.sh` after the patches are applied (Mozilla's own linters run only inside the source tree). First check that it works in the build container without the network. Opengrep does not read diffs, so until then review each patch by hand at every engine update: privileged APIs it calls, prefs it changes, URL and IPC handling, and a regression test for each security patch (as patch 0007 has).
- `rpmlint` and `lintian` in the package checks (`check_rpm.sh`, `check_deb.sh`): report only at first, blocking once each override has a reason.
- Shell commands inside Containerfiles (`RUN`), the RPM spec and `bash -c '…'` strings are not checked by ShellCheck yet.
