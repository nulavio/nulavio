# Pull requests, branches, review and merging

Status: convention adopted 2026-10-27; review and merging by coding agents adopted 2026-11-12 ([below](#review-and-merging)), in place of the maintainer reading every pull request. `main` has branch protection (settings read from GitHub on 2026-11-10). The repository moved to the `nulavio` organization and became public on 2026-11-10; branch protection was restored with the same values the same day (read back through the API). The table under [What is enforced](#what-is-enforced-and-what-is-advisory) says which parts GitHub enforces and which stay advisory.

In short:

- Every change reaches `main` through a pull request.
- Coding agents push their own branch and open a pull request. They never push to `main`.
- CI runs on the pull request. The agent that did the work reviews it, records that review in the pull request and squash-merges it when the required checks pass. The automatic AI review in CI may add one comment: it is one more reading, not the review.
- What an agent does not settle by itself: a change that weakens a protection or shows a false state is not merged, and a decision the project leaves to the maintainer needs his recorded word first. A release is still signed and published only with the maintainer's approval.

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
6. Agents change `.github/workflows/` or `.github/ai-review/` only when the task asks for it, and then say so at the top of the description: such a change always gets the second review below.
7. Review and merge as [Review and merging](#review-and-merging) says. The pull request title becomes the commit on `main`.

Pushes to branches cost no Actions minutes: CI runs on pushes to `main` and on pull requests, not on other branches.

## Review and merging

Adopted 2026-11-12. Until then every merge waited for the maintainer to read the pull request; with one maintainer and agents doing most of the work, pull requests waited for weeks and were stacked dozens deep on each other. Now the agent that did the work reviews it and merges it. The review has to be a real one, and this is what makes it one:

1. **Read the change, not the memory of writing it.** The diff as GitHub shows it (`gh pr diff`), at the head commit, after the last push. The description's "Verified" and "Not verified" must be true of that commit.
2. **Check it against the rules that are not up for decision**: the [non-negotiables](../../CONTRIBUTING.md#non-negotiables-reviewers-will-block-on-these) and the security invariants in [`.github/ai-review/instructions.md`](../../.github/ai-review/instructions.md). Tests come with the change; a bug fix has a test that fails without it.
3. **A second review by an independent reviewer** when the change touches a path in [`.github/CODEOWNERS`](../../.github/CODEOWNERS), a workflow, the review's own files or scripts, release or signing, or anything the description marks as touching a security invariant. Independent means another model, or a new session, given the diff and the description and not the author's reasoning. The automatic AI review in CI counts only when it finished with a result for the head commit and read the whole change: a run that failed, was skipped, had no credential, found the diff too large or could not read some files is not a review, and another independent one is needed. Its findings are leads, not verdicts: each is checked and answered in the pull request, fixed or with the reason it is not a defect.
4. **Record the review** in one comment on the pull request: the commit reviewed, what was read and run, each finding and what became of it, which tool and model reviewed, and the verdict. That comment is the approval: agents work with the maintainer's account, and GitHub does not let an account approve its own pull request.
5. **Merge** with a squash merge when every required check has passed on the head commit and every review conversation is resolved. Never with a required check failing or still running, never by changing branch protection or a repository setting, never by pushing to `main`.
6. **Afterwards** read CI on `main` for that commit. If it fails, fix it or revert it with a pull request at once.

What an agent does not settle by itself:

- A change that weakens a protection or shows a false state is not merged. That is a non-negotiable, not a judgement call.
- A decision the project leaves to the maintainer ([GOVERNANCE.md](../../GOVERNANCE.md): an ADR's status, accepting a security risk, a dependency with a large footprint, what gets built next) needs his recorded word first, in the ADR, the issue or the pull request. The pull request says where.
- A release. Merging is not releasing: signing and publishing wait for the maintainer's approval in the `release` environment ([R60](../security/residual-risks.md)), and an agent never gives that approval. GitHub does not enforce the difference: the environment's reviewer is the account the agents also use, it may approve its own runs and administrators may bypass it (read on 2026-11-12). It is a rule agents keep, and it becomes a barrier only when agents have an account of their own.
- A pull request from someone outside the project is reviewed the same way; the agent merges it for the maintainer, who is named as the one who decided when it is declined.

What this gives up, said plainly: the person who could tell that an agent had been misled no longer reads every change. An agent steered by text it read can now write a change, review it and merge it. What stands in the way is the required checks, the second review for the sensitive paths, the hooks and the `main`-only-through-pull-requests check; after that, only the rule that the maintainer himself approves a release, which the shared account does not enforce ([R62](../security/residual-risks.md), [threat model S19](../security/threat-model.md)).

## What is enforced and what is advisory

| Control | Today | What enforces it |
|---|---|---|
| Changes reach `main` only through a pull request | **Enforced by GitHub** | Branch protection on `main`: a pull request is required, administrators included; no force pushes or deletion; linear history (squash merges only, head branches deleted after merging) |
| A commit that reached `main` without a merged pull request is reported | **On** | Workflow `main-via-pr.yml` ("main changed only through merged pull requests"); the repository variable `REQUIRE_PR_FOR_MAIN` is `true` |
| CI must pass before merging | **Enforced for four checks** | Required status checks, branch up to date with `main`: "lint, unit tests, generated files, SBOM", "security scanners (…)", "Companion app (lint, release build)" and "does this change need the engine integration run". The engine integration result itself is not required yet: whoever merges reads it (see [Upgrading the plan](#if-the-plan-changes)) |
| A review before merging | **Convention** | [Review and merging](#review-and-merging): the agent's recorded review, and a second independent one for the sensitive paths. Branch protection asks for no approval (one maintainer, whose account the agents also use, and GitHub does not let an account approve its own pull request). Open review conversations must be resolved before merging. `GITHUB_TOKEN` cannot approve pull requests (repository setting) |
| Code owners review their paths | **Documentation** | [`.github/CODEOWNERS`](../../.github/CODEOWNERS): code-owner review is not a merge requirement |
| The automatic AI review in CI | **Advisory, never required** | [`ai-review.yml`](../../.github/workflows/ai-review.yml); it can miss problems and can be misled |
| Agents cannot change workflows | **Proposed** | A fine-grained token without the Workflows permission ([proposal](agent-guardrails.md)); GitHub enforces it once agents use it |
| Actions pinned by commit SHA, least-privilege permissions | **Enforced in the repository** | `tests/unit/test_repo_hygiene.py` in CI; the matching GitHub setting is a maintainer item ([proposal](agent-guardrails.md#5-repository-settings)) |
| Pull requests from forks get no secrets and no write token | **Enforced by GitHub** | Repository settings (fork workflows are off) |

## The automatic AI review in CI

[`.github/workflows/ai-review.yml`](../../.github/workflows/ai-review.yml) asks Claude (model `claude-opus-5-5`, through `anthropics/claude-code-action` pinned by commit) to check a pull request against the project's security invariants in [`.github/ai-review/instructions.md`](../../.github/ai-review/instructions.md). It is a second pair of eyes, not a gate: findings are leads to check, an empty result proves nothing, and whoever merges decides.

### When it runs

- When a pull request is opened or marked ready for review, and when someone adds the label `ai-review` (remove and add it again to review new pushes). Not on every push, to save Actions minutes.
- For any pull request that touches something other than `docs/brand/`, `docs/design/`, `docs/research/`, `LICENSE`, `LICENSES.md` and `.editorconfig`. New directories, agent instruction files (`CLAUDE.md`, `AGENTS.md`, `.claude/`) and scanner settings are covered without changing the workflow. A pull request that touches only the excluded files is never reviewed, not even with the label.
- Skipped, before any runner starts: drafts; branches from forks; pull requests opened by bots (unless a person adds the label); the label `no-ai-review`; more than 80 changed files or more than 4,000 added or 4,000 deleted lines; the repository variable `AI_REVIEW` set to `off`.
- A diff over 1.5 MB gets a comment saying it is too large for this review and has to be reviewed another way.
- A newer review of the same pull request cancels the running one. Adding `no-ai-review` cancels it too.
- The comment names the commit it reviewed and says later commits are not covered. When a later run is skipped (draft, size limits), the earlier comment stays as it was: check its commit against the pull request's head.

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
2. Create a federation rule with a token lifetime of 1,200 seconds, scope `workspace:developer`, and a condition on the claims `repository == 'nulavio/nulavio'`, `event_name == 'pull_request_target'` and `job_workflow_ref == 'nulavio/nulavio/.github/workflows/ai-review.yml@refs/heads/main'`. After the first run, compare these with the claim values in the Console's authentication history before tightening the rule.
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
3. Wait for the four required checks: GitHub does not merge without them, and nobody merges around them. The engine integration jobs are not required: if the deadline requires it, merge while they still run and watch them on `main`.
4. If GitHub's pull request path itself is unavailable, nothing reaches `main`: branch protection refuses a direct push, administrators included (`NULAVIO_ALLOW_MAIN_PUSH=1` only silences the local hook). Lifting the protection is the maintainer's act alone; he records the reason in a pull request or in the [security changelog](../security/changelog.md) afterwards.
5. Never weaken a protection to ship faster.

## If the plan changes

### GitHub Pro (repository stays private)

- Protection on `main` (in place as branch protection, read 2026-11-10): a pull request, the status checks "lint, unit tests, generated files, SBOM", "Companion app (lint, release build)", "security scanners (…)" and "does this change need the engine integration run", never "AI review (advisory)"; linear history; no force pushes or deletion; administrators included, so an urgent engine update also goes through a pull request. **Still open:** the engine integration result. A matrix job skipped by the Markdown-only gate reports no per-image check name, so first add a small job that needs `changes` and `integration` and fails unless `changes` succeeded and `integration` succeeded or was skipped, then require that job.
- Require one approval and code-owner review only after agents use a separate machine account: then the reviewing agent's approval can be the one GitHub asks for. Under one account nobody could approve.
- An environment `release`, with the maintainer as required reviewer and limited to `main`, for signing and publishing jobs once the release key exists. An environment `ai-review` holding `ANTHROPIC_API_KEY` (if not using federation), limited to `main`.
- 3,000 Actions minutes a month are included.

### Public repository

- Done on 2026-11-10, when the repository became public: secret scanning with push protection, Dependabot alerts, CodeQL (default setup) and private vulnerability reporting ([SECURITY.md](../../SECURITY.md) points to it) are on. Actions minutes on standard runners are free.
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
