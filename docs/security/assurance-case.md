# Assurance case

Why we think Nulavio's own code meets its security requirements, and where the evidence is. This page ties together documents that already exist; it adds no new claim. Firefox's own security is Mozilla's: Nulavio's part is to ship Mozilla's fixes on time and not to weaken what Mozilla built.

The claim: **Nulavio does not make Firefox less safe, and the code Nulavio adds (launcher, Vault, AI Bridge, Shell, build and release) resists the threats in the threat model, within the limits stated in the residual risks.**

It rests on four arguments.

## 1. The threats are written down

- [Threat model](threat-model.md): the assets, the adversaries (web content, extensions, the network, local malware as the user or as root, the supply chain) and scenarios S1–S19, each with its controls and what they do not stop.
- Feature threat models: [Vault and unlock](threat-model-unlock.md), [AI Bridge](threat-model-ai.md). The [threat matrix](threat-matrix.md) maps scenarios to controls and tests.
- What we do not defend against, said plainly: [residual risks](residual-risks.md). Malware running as root defeats every control; malware running as the user can read an unlocked profile.

## 2. The trust boundaries are known

[Trust boundaries](../architecture/trust-boundaries.md) lists every place where data crosses from less to more trusted (web content to the parent process, extensions to browser APIs, native messaging hosts, the profile on disk, other local processes, the network, update and supply channels) and the rule that holds at each one. A new boundary must add a row there and a threat-model scenario (invariant I11 in the [review rules](../../.github/ai-review/instructions.md)).

## 3. Secure design principles are applied

The principles of Saltzer and Schroeder, and where each shows up:

| Principle | How Nulavio applies it |
|---|---|
| Economy of mechanism | The launcher uses only the Python standard library at run time; the engine patch stack stays at about ten small patches, and a pref, policy or built-in add-on is preferred over a patch (I6) |
| Fail-safe defaults | Blocking, HTTPS-Only, Safe Browsing and the other protections are on from the first launch ([hardening](hardening.md)); an extension that does not match its pinned hash and Mozilla's signature is refused; AI Bridge tools that run code or read cookies stay blocked unless the user grants them (I7) |
| Complete mediation | The AI Bridge re-reads the user's grants on every call and classifies each address before navigating (I7); Shell modules validate every message from content (I10) |
| Open design | Everything is public: code, threat model, residual risks, the review rules. Nothing depends on an attacker not knowing how it works |
| Separation of privilege | Release signing happens outside CI, with a key CI never holds (I3); `main` changes only through a pull request with green required checks ([pull requests](../process/pull-requests.md)) |
| Least privilege | Workflows start from `permissions: {}` and each job asks only for what it needs, enforced by `tests/unit/test_repo_hygiene.py`; each AI agent gets its own workspace with the user's extensions never loaded (I7); profile files are 0600 and directories 0700 (I9) |
| Least common mechanism | Profiles are separate engine profiles with separate storage; a Secure Profile is encrypted at rest and closed when locked ([Vault](../architecture/vault-and-unlock.md)) |
| Psychological acceptability | Protection needs no setup; a dangerous choice is removed rather than hidden behind a warning: the downloads UI cannot open a downloaded program |

## 4. Common implementation weaknesses are countered

Each weakness that applies to this code has a rule, a tool that checks it, and tests ([code scanning](code-scanning.md)):

| Weakness | Rule | Checked by |
|---|---|---|
| OS command injection (CWE-78) | Processes start from argument lists, never through a shell (I4) | Ruff's `S` rules; Opengrep `nulavio-py-shell-command`; ShellCheck on every script and every workflow `run:` block |
| Cross-site scripting in the browser UI (CWE-79) | No `innerHTML`, `eval` or dynamic code with untrusted data in the Shell (I10) | Opengrep `nulavio-js-html-sink`, `nulavio-js-dynamic-code` |
| Path traversal and symlink attacks (CWE-22, CWE-59) | Symlinks and paths owned by others are refused; atomic writes; umask 077 (I9) | Unit tests in `tests/unit/` |
| Secrets exposed in arguments, logs or the repository (CWE-214, CWE-532, CWE-798) | Secrets only on stdin or in 0600 files; logs redacted (I3) | Opengrep `nulavio-py-secret-in-argv`, `nulavio-sh-secret-in-argv`; gitleaks on every commit |
| Broken or home-made cryptography (CWE-327) | Only libsodium, Tink, Bouncy Castle and gocryptfs; no custom primitives (I8) | Opengrep `nulavio-java-weak-crypto`; fixed test vectors shared by Python and Java |
| Missing TLS certificate checks (CWE-295) and cleartext traffic (CWE-319) | TLS checks never turned off (I1) | Opengrep `nulavio-py-tls-verification-off`, `nulavio-java-tls-verification-off`, the cleartext-request rules |
| Download of code without an integrity check (CWE-494) | Every external input pinned by version and hash or signature (I5) | Opengrep `nulavio-verification-bypass`; actions pinned by SHA (`test_repo_hygiene.py`, zizmor); `pip --require-hashes`; Gradle dependency verification |
| Workflow injection and over-broad tokens | No untrusted `${{ }}` in `run:`; least-privilege permissions (I5) | zizmor, actionlint, `test_repo_hygiene.py` |
| A protection weakened by a pref or an environment variable | Forbidden prefs and environment variables (I1) | Opengrep `nulavio-js-weakening-pref`, `nulavio-py-engine-sandbox-env`; `tests/unit/test_prefs_and_guard.py`; integration tests that read the running engine's prefs |
| Vulnerable dependencies | Daily check of every pinned dependency against OSV.dev and the add-on blocklist | `scripts/release/watch_dependencies.py` in CI and in `upstream.yml`; Dependabot; [dependency updates](dependency-updates.md) |

GitHub's CodeQL also scans the repository, and OpenSSF Scorecard checks the project's practices weekly.

## How the case stays true

Every pull request is checked against the invariants I1–I12, by the CI checks above and by the reviewer ([review rules](../../.github/ai-review/instructions.md)). A change that alters behaviour updates the [residual risks](residual-risks.md) and the [security changelog](changelog.md) (I11). Vulnerabilities found after release are handled as [SECURITY.md](../../SECURITY.md) describes and fixed with a test that fails without the fix ([CONTRIBUTING.md](../../CONTRIBUTING.md#tests-are-part-of-the-change)).
