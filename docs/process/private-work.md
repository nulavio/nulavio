# Private work: what is not tracked in public, and where it goes

Status: the part about vulnerabilities is in force. [SECURITY.md](../../SECURITY.md) has asked for private handling since the repository became public on 2026-11-10, and this page writes down the steps (2026-11-13). The part about plans that are not announced yet is proposed with [ADR 0013](../adr/0013-repository-layout.md) and waits for the maintainer.

It complements [issues](issues.md): the default is public, and this page is the list of exceptions.

## Where each kind of work lives

| What | Where | Who can read it | It becomes public |
|---|---|---|---|
| A vulnerability in Nulavio's own code, configuration, build, release or site, whoever found it (a reporter, an audit, a scanner, a sanitizer, a review, a coding agent) | A **draft security advisory** of this repository, and the fix in the advisory's **temporary private fork** | The organization's owners and whoever they add to the advisory | When the release that fixes it is out and the advisory is published |
| A finding that may be a vulnerability and is not confirmed yet | Where it was found, if that place is private: the reporter's private report, the scanner's own platform (LESIS), the code scanning alerts of the Security tab. If it has no private home (an agent noticed it while doing something else): a draft advisory whose summary starts with "Triage:" | As above; a scanner's platform, the people with an account there | Never, when it is not a vulnerability: the advisory is closed with the reason. Otherwise as the row above |
| A scanner alert that is not a vulnerability (a false positive, test code, a posture score) | Fixed by an ordinary pull request, or dismissed in the Security tab with the reason | Public | Already |
| A vulnerability in Firefox | [Mozilla](https://www.mozilla.org/en-US/security/bug-bounty/). Shipping Mozilla's fix is public work ([update policy](../architecture/update-policy.md)) | | |
| Proposed: a plan that would mislead or commit the project if seen early (a launch date, a partner, a claim that is not true yet, someone else's confidential information) | A **draft item** in the organization's [project](https://github.com/orgs/nulavio/projects/1) (private; a draft item exists only there) | Members of the organization | When it is announced: the draft is converted into a public issue |
| Proposed: content ideas with nothing to hide (a post, a video, a talk) | A public issue with a label `content` (added to the [labels](issues.md#labels) when this is accepted) | Public | Already |
| Secrets, tokens, personal data | Not on GitHub at all, in any of these places | | |
| Everything else | A public [issue](issues.md) | Public | Already |

The project is the one view over all of it. It lists the public issues, the draft items, and one draft item per open advisory that carries only the advisory's address: GitHub cannot add an advisory to a project.

No private repository: with one maintainer, a handful of advisories and the project's draft items cover what it would hold, without another repository to configure and to keep the hosted Apps out of. [ADR 0013](../adr/0013-repository-layout.md) says when to look again.

## A vulnerability, step by step

For people and for coding agents. An agent that finds one stops writing about it in public first, then follows these steps; it does not need to ask before opening the draft advisory.

1. **Nowhere public.** Not in an issue, a pull request, a commit message, a branch name, a comment, a Discussion, or a question to a hosted reviewer (CodeRabbit, the Codex connector, the AI review in CI). A public change that fixes it silently is still a disclosure: it waits for step 6.
2. **Open a draft advisory** (Security → Advisories → New draft, or the API below). One advisory per release that fixes things: a batch of findings from one audit or scan goes in one advisory, each listed with the identifier its source gave it. A finding gets an advisory of its own when someone outside reported it (they are credited there), when it is high or critical, or when it should have a CVE.

   ```sh
   gh api -X POST repos/nulavio/nulavio/security-advisories --input advisory.json
   # advisory.json: summary, description, severity, vulnerabilities[{package{ecosystem:"other",name:"nulavio"},
   #                vulnerable_version_range}], start_private_fork: true
   ```

3. **Fix it in the private fork.** The fork is `nulavio/nulavio-ghsa-<id>`. Add it as a remote, branch as `sec/<slug>`, and push only there.

   ```sh
   git remote add ghsa https://github.com/nulavio/nulavio-ghsa-<id>.git
   git push ghsa HEAD
   ```

4. **Test on your machine.** GitHub runs no workflow in a temporary private fork, so no check is ever green there. Run what CI would run (`ruff`, the unit tests, `scripts/security/scan.sh`, and the integration tests when the engine, profiles or the Shell are touched) and write the commands and results in the description of the fork's pull request. A fix comes with a test that fails without it.
5. **Review it there.** The recorded review and, since every such change is security-relevant, the second, independent one ([review and merging](pull-requests.md#review-and-merging)) happen on the fork's pull request, recorded in its description or as a review (GitHub refuses ordinary comments on such a fork through the API). The independent reviewer is a model or session run by the maintainer or an agent, given the diff, never a hosted service asked through a public page.
6. **Land it and release it together.** Releases are built from `main` ([release workflow](../architecture/build.md#release-workflow-ci)), so the fix is public from the moment it lands, before anyone can install it. Therefore:
   - land when the maintainer is ready to start the release run, not before;
   - land through a pull request in the public repository from the same `sec/<slug>` branch, so the required checks run on it. Its title and description say what changes, not how to exploit what it replaces, until the advisory is published. The advisory's own "merge" button is not used (it would bring commits to `main` that no required check ran on; not tried);
   - a fix that only changes the site is live when the site workflow has deployed it, with no release.
7. **Publish.** When the packages are in the repository (or the site is deployed): set the patched version in the advisory and publish it, add the [security changelog](../security/changelog.md) entry, and update whatever tracked the finding (a scanner's status, the reporter).
8. **Afterwards** it is public work: follow-ups are ordinary issues.

What an advisory cannot do, so nobody looks for it: it has no labels, no sub-issues and no assignees, and it cannot be added to a project. The description is the place for the list of findings and their state.

## What the installed Apps see

The hosted services installed as GitHub Apps on the organization are installed for "all repositories" ([R67](../security/residual-risks.md)). Checked on 2026-11-13 in the private fork of a draft advisory, with a pull request that changed one blank line:

- Twenty minutes after it was opened, no App had commented, reacted or reported a check there. On a public pull request opened the same hour, CodeRabbit and the Codex connector had both answered within a minute.
- GitHub ran no workflow for it.
- Not tested: whether an App can read such a fork when it asks GitHub by itself, without an event. Treat the fork as private to the organization's owners, not as proven unreadable by the installed Apps.

Whatever they can read there, nothing about an unfixed vulnerability is ever *given* to a hosted reviewer: no `@coderabbitai` or `@codex` request in the fork, and the public pull request of step 6 is written so that their reviews of it reveal nothing more than the change itself.

## Access for agents

Agents work with the maintainer's token, whose `repo` scope covers the advisories of this repository (`gh api repos/nulavio/nulavio/security-advisories`). The fine-grained token proposed in the [agent guardrails](agent-guardrails.md) needs "Repository security advisories: read and write" added for this. Project draft items need the `project` scope (`gh project item-create 1 --owner nulavio --title … --body …`).
