# Pull requests, branches and the advisory AI review

Status: convention adopted 2026-10-27. On the current GitHub plan (private repository, GitHub Free) most of it is **advisory**: the table under [What is enforced](#what-is-enforced-and-what-is-advisory) says which parts GitHub itself enforces.

In short:

- Every change reaches `main` through a pull request that a person merges.
- Coding agents push their own branch and open a pull request. They never push to `main`, merge or approve.
- CI runs on the pull request. An advisory AI review may add one comment. The maintainer reads both, decides and squash-merges.

## Branch names

Lowercase letters, digits and `._/-`, at most 60 characters. `<type>` is one of the commit types in [CONTRIBUTING.md](../../CONTRIBUTING.md): `feat`, `fix`, `docs`, `security`, `test`, `chore`.

| Who | Pattern | Example |
|---|---|---|
| A coding agent | `agent/<tool>/<type>-<slug>` | `agent/claude/feat-s25-ai-review`, `agent/codex/fix-vault-nonce` |
| A person | `<name>/<type>-<slug>` | `caio/docs-readme` |
| An engine update under the [update policy](../architecture/update-policy.md) | `release/firefox-<version>` | `release/firefox-159.0` |
| A vulnerability fix | `sec/<slug>` | `sec/launcher-symlink` |

Once the repository is public, develop fixes for undisclosed vulnerabilities in a GitHub private security advisory fork, not in a public `sec/` branch.

The pre-push hook checks names and refuses pushes to `main`; the pre-commit hook next to it refuses a commit that adds a secret ([code scanning](../security/code-scanning.md)). Turn both on once per clone (worktrees share it):

```sh
git config core.hooksPath scripts/git-hooks
```

## Opening a pull request

The same steps for agents and people:

1. Start from the current `main` in a separate worktree, for example `git fetch origin && git worktree add -b agent/claude/fix-x ../nulavio-fix-x origin/main`.
2. Make small, verifiable conventional commits, signed off (`git commit -s`, see [CONTRIBUTING.md](../../CONTRIBUTING.md)).
3. Run the local checks: `ruff check .`, `ruff format --check .`, `python3 -I tests/run.py unit`, and the integration tests when the change touches the engine, profiles or the Shell.
4. Push only your own branch: `git push -u origin HEAD`. Never push to `main`. Never force-push, except `--force-with-lease` on your own branch before review starts.
5. Open the pull request with `gh pr create --base main --title "<conventional title>" --body-file <file>`, filling in [the template](../../.github/pull_request_template.md): what changed and why, how it was verified (commands and results), what was not verified, implemented / prototype / planned, and which security invariants it touches. Draft pull requests may not be available for private repositories on this plan (unconfirmed); where they are, use them while work is in progress.
6. Agents stop there: report the pull request's address and do not merge (`gh pr merge`), approve or close it. Agents change `.github/workflows/` or `.github/ai-review/` only when the task asks for it, and then say so at the top of the description so the maintainer reviews it closely.
7. The maintainer reads the CI result, the AI comment if there is one, and the diff, then squash-merges. The pull request title becomes the commit on `main`. Security-relevant pull requests need a second human reviewer once there is one.

Pushes to branches cost no Actions minutes: CI runs on pushes to `main` and on pull requests, not on other branches.

## What is enforced and what is advisory

| Control | Today | What enforces it |
|---|---|---|
| Changes reach `main` only through a pull request | **Advisory** | Convention; the pre-push hook (opt-in, skipped by `git push --no-verify`); agent permission rules ([proposal](agent-guardrails.md)) |
| A commit that reached `main` without a merged pull request is reported | **Ready, off** | CI check "main changed only through merged pull requests", on when the repository variable `REQUIRE_PR_FOR_MAIN` is `true` (set it after adopting this flow, or every direct push fails CI) |
| CI must pass before merging | **Advisory** | The maintainer reads CI. Required status checks need branch protection, which this plan does not offer for private repositories |
| A person approves | **Advisory** | Only the maintainer merges. `GITHUB_TOKEN` cannot approve pull requests (repository setting) |
| Code owners review their paths | **Documentation** | [`.github/CODEOWNERS`](../../.github/CODEOWNERS) has no effect on this plan |
| AI review | **Advisory, never required** | [`ai-review.yml`](../../.github/workflows/ai-review.yml); it can miss problems and can be misled |
| Agents cannot change workflows | **Proposed** | A fine-grained token without the Workflows permission ([proposal](agent-guardrails.md)); GitHub enforces it once agents use it |
| Actions pinned by commit SHA, least-privilege permissions | **Enforced in the repository** | `tests/unit/test_repo_hygiene.py` in CI; the matching GitHub setting is a maintainer item ([proposal](agent-guardrails.md#5-repository-settings)) |
| Pull requests from forks get no secrets and no write token | **Enforced by GitHub** | Repository settings (fork workflows are off) |

## The advisory AI review

[`.github/workflows/ai-review.yml`](../../.github/workflows/ai-review.yml) asks Claude (model `claude-opus-5-5`, through `anthropics/claude-code-action` pinned by commit) to check a pull request against the project's security invariants in [`.github/ai-review/instructions.md`](../../.github/ai-review/instructions.md). It is a second pair of eyes, not a gate: findings are leads to check, an empty result proves nothing, and a person decides.

### When it runs

- When a pull request is opened or marked ready for review, and when someone adds the label `ai-review` (remove and add it again to review new pushes). Not on every push, to save Actions minutes.
- For any pull request that touches something other than `docs/brand/`, `docs/design/`, `docs/product/`, `docs/research/`, `LICENSE`, `LICENSES.md` and `.editorconfig`. New directories, agent instruction files (`CLAUDE.md`, `AGENTS.md`, `.claude/`) and scanner settings are covered without changing the workflow. A pull request that touches only the excluded files is never reviewed, not even with the label.
- Skipped, before any runner starts: drafts; branches from forks; pull requests opened by bots (unless a person adds the label); the label `no-ai-review`; more than 80 changed files or more than 4,000 added or 4,000 deleted lines; the repository variable `AI_REVIEW` set to `off`.
- A diff over 1.5 MB gets a comment saying it needs a human-only review.
- A newer review of the same pull request cancels the running one. Adding `no-ai-review` cancels it too.

### How it is locked down

- `pull_request_target`: the workflow, the instructions and the output schema always come from `main`, so a pull request cannot change its own reviewer. Changes to them take effect only after they are merged.
- Nothing from the pull request runs. Its head is checked out into `.ai-review/head` only so git can compute the diff (`--no-ext-diff --no-textconv`), then deleted ([`ai_review_input.py`](../../scripts/ci/ai_review_input.py)). Git attributes come from `main` (`--attr-source`), so a `.gitattributes` in the pull request cannot hide a file from the diff by marking it binary. Files git still shows only as binary (a NUL byte in the content is enough) cannot be read by the model: the comment gives their number, and the model is told to flag any that look like code or configuration.
- Job "review" holds the model credential with a read-only GitHub token and only the Read, Grep and Glob tools, limited to the working directory (no shell, network, edit or MCP tools, no hooks, `.git/` unreadable). Its only output is JSON that must match [`schema.json`](../../.github/ai-review/schema.json).
- Job "publish" never runs the model. [`post_ai_review.py`](../../scripts/ci/post_ai_review.py) from `main` validates the JSON again, drops findings about files that do not exist, removes invisible and bidirectional characters, redacts secret-like strings, neutralises mentions and HTML comments, shows every model-written text inside a code fence, and creates or updates one comment marked `<!-- nulavio-ai-review -->`. It cannot approve or request changes.
- Claude Code and Bun are downloaded by version and checked against SHA-256 pins. The Claude Code pin comes from a release manifest whose signature [`verify_claude_code_release.py`](../../scripts/upstream/verify_claude_code_release.py) checks against Anthropic's pinned key; a unit test checks the pin against that signed manifest.
- Telemetry, error reporting and non-essential traffic of Claude Code are turned off.

What it sends: the diff, the pull request's title and description, and the files the model chooses to read from `main` go to Anthropic's API. Nothing else leaves GitHub.

What it can still get wrong: text in the change can steer the review (prompt injection), so it can miss a problem or report a false one. The comment lists text that looked like an injection attempt. The repository deliberately contains such text in test fixtures (`tests/lib/harness.py`, route `/agent-task`).

### Cost

About 8–10 billed Actions minutes per review (both jobs, rounded up) and, as an estimate to measure on the first ten reviews, USD 0.5–2 of API use. Each run stops at 40 turns, at an estimated USD 3 (a client-side estimate that can be passed slightly) and after 15 minutes. Without a credential, a run that passes the filters starts one job that prints a notice and stops (about one billed minute).

### Turning it on (maintainer)

Preferred, with no long-lived secret: Workload Identity Federation.

1. In the Claude Console: Settings → Workload identity → Connect workload → GitHub Actions, issuer `https://token.actions.githubusercontent.com`. Create a service account `nulavio-ai-review` in a dedicated workspace (for example `nulavio-ci`) with a monthly spend limit (for example USD 40).
2. Create a federation rule with a token lifetime of 1,200 seconds, scope `workspace:developer`, and a condition on the claims `repository == 'caiolombello/nulavio'`, `event_name == 'pull_request_target'` and `job_workflow_ref == 'caiolombello/nulavio/.github/workflows/ai-review.yml@refs/heads/main'`. After the first run, compare these with the claim values in the Console's authentication history before tightening the rule.
3. In GitHub, Settings → Secrets and variables → Actions → Variables, add `ANTHROPIC_FEDERATION_RULE_ID` (`fdrl_…`), `ANTHROPIC_ORGANIZATION_ID`, `ANTHROPIC_SERVICE_ACCOUNT_ID` (`svac_…`) and, if the rule covers several workspaces, `ANTHROPIC_WORKSPACE_ID`. These are identifiers, not secrets.

Fallback: a Console API key from the same spend-capped workspace, stored as the repository secret `ANTHROPIC_API_KEY` and used only by this workflow. Rotate it every 90 days and at once after any unexpected change under `.github/`. On this plan any workflow pushed by someone with write access can read repository secrets, which is why federation is preferred. If both are configured, the workflow uses federation and warns.

Then create the labels `ai-review` and `no-ai-review`. Do not install the Claude GitHub App: the workflow uses its own job token, and the app asks for far broader permissions. Never set `ACTIONS_STEP_DEBUG` for this repository: debug mode makes the action print its full output.

To turn it off, set the repository variable `AI_REVIEW` to `off` (no cost), or remove the credential.

### Checks on the first run

- The review ends with a result. If it ends without one, `--tools Read,Grep,Glob` may have removed the tool Claude Code uses to return structured output: replace it with `--disallowedTools "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,mcp__*"` and keep the deny list in `settings`.
- The log shows that `--append-system-prompt-file`, `--effort` and `--max-budget-usd` reached Claude Code.
- With federation, the claim values in the Console's history match the rule.
- One comment appears and is updated, not duplicated, when the label is added again.

### Updating the pins

At most monthly, or at once for a security advisory (the daily [dependency watch](../security/dependency-updates.md) reports them for both, as npm packages):

1. Choose a release of `anthropics/claude-code-action`, resolve its tag to a commit with `gh api repos/anthropics/claude-code-action/tags`, and read `action.yml` and `src/entrypoints/run.ts` at that commit.
2. `CLAUDE_CODE_VERSION` must equal `claudeCodeVersion` in `run.ts`. Run `python3 -I scripts/upstream/verify_claude_code_release.py <version>` for `CLAUDE_CODE_SHA256`, and replace the files in `tests/fixtures/claude-code/` with that release's manifest and signature.
3. `BUN_VERSION` must equal `bun-version` in `action.yml`. Take `BUN_ZIP_SHA256` from Bun's `SHASUMS256.txt` for that release and compare it with the asset digest GitHub shows.
4. Update the commit in `uses:`, its version comment and `AI_REVIEW_SOURCE`, then run the unit tests.

Known gaps: the action installs its own dependencies with `bun install --production` from its pinned `bun.lock` but without `--frozen-lockfile`; the signature of Bun's checksum file is not verified; the action's release commits are not signed, so trust rests on GitHub and the commit id.

### Local review

`scripts/review/ai_review_local.sh <number>` runs the same review on your machine with your own Claude Code login: no Actions minutes, no secret on GitHub. It fetches the pull request's head as git objects, reviews it from a throwaway worktree of `origin/main` with the same tools, settings and instructions, and prints the comment. With `--post` it asks, then posts the comment as you. It needs Git 2.41 or later (for `--attr-source`). Your machine holds real secrets (the Safe Browsing key, later signing keys); the working-directory limit and the read-only tools are what keep them out of reach, so do not loosen them. Claude Code's interactive `/code-review` is another option.

## Emergency path: engine security update

When Mozilla publishes a security release, the [update policy](../architecture/update-policy.md) sets the deadline. The pull request flow still applies, with these allowances:

1. Work on `release/firefox-<version>` and open the pull request as soon as the build passes locally.
2. The AI review never blocks; add `no-ai-review` if it would only cost time.
3. Wait for at least the "lint, unit tests, generated files, SBOM" job. If the deadline requires it, merge while the slower jobs still run and watch them on `main`.
4. Only if GitHub's pull request path itself is unavailable: the maintainer pushes with `NULAVIO_ALLOW_MAIN_PUSH=1 git push origin HEAD:main`. The "main changed only through merged pull requests" check, if on, will fail for that commit; record the reason in a pull request or in the [security changelog](../security/changelog.md) afterwards.
5. Never weaken a protection to ship faster.

## If the plan changes

### GitHub Pro (repository stays private)

- A ruleset on `main`: require a pull request; require the status checks "lint, unit tests, generated files, SBOM", "Companion app (lint, release build)" and both "engine integration (…)" jobs, never "AI review (advisory)"; linear history; block force pushes and deletion; let only the maintainer bypass it (for the update deadline).
- Require one approval and code-owner review only after agents use a separate machine account. Otherwise the maintainer could not approve pull requests that agents opened under his own account.
- An environment `release`, with the maintainer as required reviewer and limited to `main`, for signing and publishing jobs once the release key exists. An environment `ai-review` holding `ANTHROPIC_API_KEY` (if not using federation), limited to `main`.
- 3,000 Actions minutes a month are included.

### Public repository

- Actions minutes on standard runners are free. Secret scanning with push protection, Dependabot alerts and CodeQL become available at no cost. Turn on private vulnerability reporting ([SECURITY.md](../../SECURITY.md) already points to it).
- Pull requests from forks get no secrets: keep the `pull_request_target` design and its same-repository condition. Review automatically only when the author is an owner, member or collaborator (`author_association`); for outside contributors, a maintainer adds the label after reading the raw diff (hidden Markdown can carry instructions).
- Keep the action's `allowed_non_write_users` and `allowed_bots` empty.
- AI comments and workflow logs become public.

## Rejected

- Anthropic's managed Code Review (runs on Anthropic's infrastructure, no Actions minutes): it needs a Team or Enterprise plan and the Claude GitHub App, whose permissions (workflows, actions and contents read/write, repository hooks, administration read) are far more than a comment-only reviewer needs. Reconsider only on a Team plan, if the maintainer accepts that permission set.
- A Claude subscription token (`claude setup-token`) as the CI credential: long-lived and tied to one person's subscription.

## Next steps

- After the first ten reviews: measure minutes, cost and false findings; tune the instructions; consider `claude-sonnet-5-5` for routine pull requests.
- On the first squash merge: confirm that GitHub links the merge commit to its pull request, which the "main changed only through merged pull requests" check relies on.
- Apply the [agent guardrails proposal](agent-guardrails.md), then turn on `REQUIRE_PR_FOR_MAIN`.
- If the plan changes, apply the matching section above.
