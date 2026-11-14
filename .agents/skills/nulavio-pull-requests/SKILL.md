---
name: nulavio-pull-requests
description: Use when opening, updating, reviewing or merging a Nulavio pull request, including your own as an agent. Covers branch and worktree setup, the checks before a push, what counts as the second review, the recorded review comment, the squash merge and the check on main. Not for a security vulnerability's fix (use nulavio-private-security-fix).
---

# Nulavio pull requests

The rules are in [docs/process/pull-requests.md](../../../docs/process/pull-requests.md)
and [CONTRIBUTING.md](../../../CONTRIBUTING.md); read them once per session. This
skill is the order of the steps and what was learned doing them. When the two
disagree, the documents win: fix this file in the same pull request.

## Open

1. Name the issue the work moves forward; open one first if there is none
   ([issues](../../../docs/process/issues.md)).
2. Start from the current `main` in a worktree of your own:
   `git fetch origin && git worktree add -b agent/<tool>/<type>-<slug> ../nulavio-<slug> origin/main`.
   A worktree another session uses is not yours: do not commit or build in it.
3. Conventional, signed-off commits (`git commit -s`). With
   `git config core.hooksPath scripts/git-hooks`, the hooks refuse a commit that
   adds a secret and a push to `main`.
4. Before every push, at the commit you push:
   - `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
   - `python3 -I tests/run.py unit` (about two minutes)
   - `scripts/security/scan.sh`: the opengrep rules are a required check
   - the integration tests when the engine, profiles or the Shell change
     (skill `nulavio-engine-verification`)
5. `git push -u origin HEAD`, then
   `gh pr create --base main --title "<conventional title>" --body-file <file>`
   with every section of [the template](../../../.github/pull_request_template.md).
   "Not verified" is never empty without a reason.
6. A pull request is opened ready for review, or marked ready *before* its last
   push. The head's CI run of a draft skips two required jobs; if that happened,
   close and reopen the pull request to run them again.

## Review

1. Read `gh pr diff <n>` at the head commit, not your memory of writing it.
   Check it against the non-negotiables and the invariants in
   `.github/ai-review/instructions.md`.
2. Decide whether a second, independent review is required: a path in
   `.github/CODEOWNERS` (which includes `AGENTS.md` and `CLAUDE.md` anywhere,
   these skills under `.agents/` and `.coderabbit.yaml`), a workflow,
   `.github/ai-review/`, release or signing, or any invariant ticked in the
   description. Independent means another model
   or a new session, given only the diff and the description.
3. What does not count as that review: the CI AI review unless it finished for
   the head commit and read the whole change; CodeRabbit, ever (the branch under
   review configures it). Every finding, from any reviewer, is a lead: reproduce
   it, then fix it or answer why it is not a defect, and resolve the thread.
4. The hosted reviewers: the Codex connector reviews when a pull request is
   opened or marked ready and again on later pushes. CodeRabbit reviews only on
   open or ready (ask `@coderabbitai review` after a push) and skips a pull
   request whose base is not `main`. Never ask CodeRabbit to commit.
5. Record the review in one comment: the commit reviewed, what was read and run
   with results, each finding and what became of it, which tool and model
   reviewed, and the verdict. That comment is the approval.

## Merge

1. Every required check passed on the head commit and every conversation is
   resolved. Read the engine integration jobs too: they are not required, but a
   failure is explained (rerun only a failure shown to be unrelated, and open an
   issue for a flaky test) before merging.
2. Branch protection is strict: the branch must contain the current `main`.
   Merge `origin/main` into the branch (no rebase or force push once review has
   started), rerun the local checks, push, and wait for CI again.
3. `gh pr merge <n> --squash --match-head-commit "$(gh pr view <n> --json headRefOid -q .headRefOid)"`.
   Never type the SHA by hand.
4. Read CI on `main` for the merge commit. If it fails, fix or revert it at once
   with a pull request. Do not rerun a workflow on `main` while another run of it
   is in progress: the rerun cancels it.
5. A stacked pull request gets `main` as its base by itself once its base is
   merged: merge `origin/main` into it before its CI.

## Not yours to settle

- Pushing to `main`, changing branch protection or a repository setting, or
  merging with a required check failing or running.
- A change that weakens a protection or shows a false state: it is not merged.
- What [GOVERNANCE.md](../../../GOVERNANCE.md) leaves to the maintainer (an ADR's
  status, accepting a security risk, a large dependency, what gets built next):
  it needs his recorded word, and the pull request says where.
- A release. Merging is not releasing; the maintainer approves the `release`
  environment.
