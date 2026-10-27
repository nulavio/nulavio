# Agent guardrails (proposal)

Status: **proposal for the maintainer**. Nothing here is active until he applies it. In particular, `.claude/settings.json` does not exist in the repository; create it from section 2 only with his approval.

It complements the [pull request flow](pull-requests.md).

## The problem

Coding agents work as the maintainer. Their commits carry his name, and `gh` on this machine holds his classic token with the scopes `repo`, `workflow`, `gist` and `read:org`, valid for every repository he can reach. So an agent that makes a mistake, or that was steered by text it read (a web page, an issue, a file in a pull request), can push to `main`, change workflows and with them how secrets are used, merge or approve, and GitHub cannot tell it apart from him. With a private repository on GitHub Free there is no branch protection to stop any of this.

The layers below go from the only one GitHub enforces to the ones that only prevent accidents.

## 1. A fine-grained token for agents

The one control GitHub enforces on this plan: GitHub refuses a push that adds or changes a file under `.github/workflows/` when the token lacks the Workflows permission.

The maintainer creates it under Settings → Developer settings → Fine-grained tokens:

- resource owner `caiolombello`; repository access: only `caiolombello/nulavio`;
- permissions: Contents read and write; Pull requests read and write; Issues read and write (optional); Metadata read (automatic);
- **no access** to Workflows, Actions, Administration, Secrets, Variables and Environments;
- expiry: 90 days.

Give it to agent sessions only, for example through a separate `gh` configuration that agents start with and the maintainer's own shell does not:

```sh
# once: the token comes from stdin, never from the command line
GH_CONFIG_DIR="$HOME/.config/gh-agent" gh auth login --with-token < /path/to/0600-token-file
# in the environment that starts agents
export GH_CONFIG_DIR="$HOME/.config/gh-agent"
```

`git push` over HTTPS uses the same login when the git credential helper is `gh auth git-credential` (`gh auth setup-git`), because the helper reads `GH_CONFIG_DIR`.

What changes: agents can no longer add a workflow that reads secrets, or change CI or the AI review workflow. A change to a workflow goes into the pull request description as a patch, and the maintainer applies and pushes it with his own token. The classic token stays for his own interactive use.

What it does not change: agents can still push to `main` (that needs Contents write, which they need for branches). Only branch protection stops that, on GitHub Pro or a public repository. Any program running as the same user can read the token file (trust boundary TB6).

Later, on GitHub Pro: a separate machine account for agents (GitHub's terms allow one per person), so that authorship and approvals mean something.

## 2. Claude Code project settings

Proposed content of `.claude/settings.json`:

```json
{
  "permissions": {
    "deny": [
      "Bash(git push * main)",
      "Bash(git push * main *)",
      "Bash(git push *:main)",
      "Bash(git push *:main *)",
      "Bash(git push *:refs/heads/main*)",
      "Bash(git push --force)",
      "Bash(git push --force *)",
      "Bash(git push * --force)",
      "Bash(git push * --force *)",
      "Bash(git push -f *)",
      "Bash(git push * -f)",
      "Bash(git push * -f *)",
      "Bash(git push * +*)",
      "Bash(git push *--no-verify*)",
      "Bash(git config *core.hooksPath*)",
      "Bash(git -c *core.hooksPath*)",
      "Bash(gh pr merge *)",
      "Bash(gh pr review *--approve*)",
      "Bash(gh pr review * -a)",
      "Bash(gh pr review * -a *)",
      "Bash(gh api *merge*)",
      "Bash(gh secret *)",
      "Bash(gh variable *)",
      "Bash(gh repo edit *)",
      "Edit(/.claude/**)"
    ],
    "ask": [
      "Edit(/.github/workflows/**)",
      "Edit(/.github/ai-review/**)",
      "Edit(/scripts/ci/**)",
      "Edit(/scripts/git-hooks/**)"
    ]
  }
}
```

What each group does:

- pushing to `main`, force-pushing (`--force-with-lease` on the agent's own branch stays allowed), skipping hooks and turning the pre-push hook off are refused;
- merging, approving, and changing secrets, variables or repository settings are refused;
- the agent cannot edit its own Claude Code settings;
- editing the workflows, the AI review files, the comment script or the hooks asks the person first (in a run nobody watches, asking means refusing).

These rules match the command text. `git -C . push origin main`, an alias, a script or another tool gets around them, so they prevent accidents and are not a security boundary. Other agents (for example Codex) need the same rules in their own configuration format.

## 3. The pre-push hook

[`scripts/git-hooks/pre-push`](../../scripts/git-hooks/pre-push) refuses pushes to `main` and branch names outside the convention. Turn it on once per clone; worktrees share it:

```sh
git config core.hooksPath scripts/git-hooks
```

`git push --no-verify` skips it, and `NULAVIO_ALLOW_MAIN_PUSH=1` lets the maintainer push to `main` on the [emergency path](pull-requests.md#emergency-path-engine-security-update). The rules in section 2 refuse both for Claude Code. `core.hooksPath` takes one directory, so any other hook (for example a pre-commit hook) belongs in `scripts/git-hooks/` as well.

## 4. Detection after the fact

A step in CI's "lint, unit tests, generated files, SBOM" job, "main changed only through a merged pull request", fails when a commit reaches `main` without a merged pull request, so GitHub's failure email reaches the maintainer. It runs only when the repository variable `REQUIRE_PR_FOR_MAIN` is `true`: set it once the pull request flow is in use, otherwise every direct push fails CI.

## 5. Repository settings

Settings only the maintainer can change:

- Actions → General: require actions to be pinned to a full-length commit SHA, and allow only the actions in use (today `actions/checkout`, `actions/upload-artifact`, `anthropics/claude-code-action` and `oven-sh/setup-bun`, which that action contains). Whether this choice exists for a private repository on GitHub Free is unverified.
- Keep: workflow permissions read-only; "Allow GitHub Actions to create and approve pull requests" off; workflows from fork pull requests off.
- General → Pull requests: allow squash merging only, and turn on "Automatically delete head branches".

## What this still does not stop

- An agent that still uses the classic token.
- A push to `main` with the fine-grained token (needs branch protection).
- Programs running as the same user reading tokens (TB6, see [residual risks](../security/residual-risks.md)).
- An agent steered within what these layers allow. Reading every pull request before merging stays the main control.
