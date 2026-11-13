# Private work: what is not tracked in public, and where it goes

Status: **adopted** on 2026-11-13 with [ADR 0013](../adr/0013-repository-layout.md), by the maintainer's word of that day. A vulnerability never goes in a public issue ([SECURITY.md](../../SECURITY.md), since 2026-11-10), and its fix is developed in the private fork of a security advisory ([pull requests](pull-requests.md#branch-names)). The steps below are how to do that. They were followed once, on 2026-11-13, through step 6 (#150 for the browser, #178 for the site); what that run showed is written into steps 5 and 6 and into [what the installed Apps see](#what-the-installed-apps-see). Step 7 is written from the one earlier case (GHSA-5mmp-gx3p-m7j8) and has not been run in this form.

Nothing here is enforced by GitHub while agents work with the maintainer's own token: a push of a `sec/` branch to the public repository is refused by nothing, and the hooks check only the shape of a branch name. These are rules people and agents keep.

It complements [issues](issues.md): the default is public, and this page is the list of exceptions.

## Where each kind of work lives

| What | Where | Who can read it | It becomes public |
|---|---|---|---|
| A vulnerability in Nulavio's own code, configuration, build, release or site, whoever found it (a reporter, an audit, a scanner, a sanitizer, a review, a coding agent) | A **draft security advisory** of this repository, and the fix in the advisory's **temporary private fork** | The repository's administrators (the organization's owners) and whoever they add to the advisory | When the release that fixes it is out and the maintainer publishes the advisory |
| A finding that may be a vulnerability and is not confirmed yet | Where it was found, if that place is private: the reporter's private report, the scanner's own platform (LESIS), the code scanning alerts of the Security tab. If it has no private home (an agent noticed it while doing something else): a draft advisory whose summary starts with "Triage:" | As above; a scanner's platform, the people with an account there | Never, when it is not a vulnerability: the advisory is closed with the reason. Otherwise as the row above |
| A scanner alert that is not a vulnerability (a false positive, test code, a posture score) | Fixed by an ordinary pull request, or dismissed in the Security tab with the reason | Public | Already |
| A vulnerability in Firefox | [Mozilla](https://www.mozilla.org/en-US/security/bug-bounty/). Shipping Mozilla's fix is public work ([update policy](../architecture/update-policy.md)) | | |
| A plan that would mislead or commit the project if seen early (a launch date, a partner, a claim that is not true yet, someone else's confidential information) | A **draft item** in the organization's [project](https://github.com/orgs/nulavio/projects/1) (private; a draft item exists only there) | Members of the organization | When it is announced: the draft is converted into a public issue |
| Content ideas with nothing to hide (a post, a video, a talk) | A public issue with the label `content` ([labels](issues.md#labels)) | Public | Already |
| Secrets, tokens, personal data | Not on GitHub at all, in any of these places | | |
| Everything else | A public [issue](issues.md) | Public | Already |

The project is the one view over all of it. It lists the public issues, the draft items, and one draft item per open advisory that carries only the advisory's address: GitHub cannot add an advisory to a project.

No private repository: with one maintainer, a handful of advisories and the project's draft items cover what it would hold, without another repository to configure and to keep the hosted Apps out of. [ADR 0013](../adr/0013-repository-layout.md) says when to look again.

## A vulnerability, step by step

For people and for coding agents. An agent that finds one stops writing about it in public first, then follows these steps. Opening a draft advisory needs no question first: a draft is visible to nobody else. Landing the fix and publishing the advisory are the maintainer's to decide (steps 6 and 7).

1. **Nowhere public.** Not in an issue, a pull request, a commit message, a branch name, a comment, a Discussion, or a question to a hosted reviewer (CodeRabbit, the Codex connector, the AI review in CI). A public change that fixes it silently is still a disclosure: it waits for step 6.
2. **Open a draft advisory** (Security → Advisories → New draft, or the API below). One advisory per release that fixes things: a batch of findings from one audit or scan goes in one advisory, each listed with the identifier its source gave it. A finding gets an advisory of its own when someone outside reported it (they are credited there), when it is high or critical, or when it should have a CVE.

   ```sh
   gh api -X POST repos/nulavio/nulavio/security-advisories --input advisory.json
   # advisory.json: summary, description, severity, vulnerabilities[{package{ecosystem:"other",name:"nulavio"},
   #                vulnerable_version_range}], start_private_fork: true
   ```

3. **Fix it in the private fork.** The fork is `nulavio/nulavio-ghsa-<id>`. Add it as a remote, branch as `sec/<slug>`, and push only there. The slug says nothing about the flaw, because the branch name becomes public in step 6: a date and a letter (`sec/2026-11-a`), not `sec/launcher-symlink`.

   ```sh
   git remote add ghsa https://github.com/nulavio/nulavio-ghsa-<id>.git
   git push ghsa HEAD
   ```

4. **Test on your machine.** GitHub runs no workflow in a temporary private fork, so no check is ever green there. Run what CI would run (`ruff`, the unit tests, `scripts/security/scan.sh`, and the integration tests when the engine, profiles or the Shell are touched) and write the commands and results in the description of the fork's pull request. A fix comes with a test that fails without it.
5. **Review it there.** The recorded review and, since every such change is security-relevant, the second, independent one ([review and merging](pull-requests.md#review-and-merging)) happen on the fork's pull request, recorded in its description or as a review (GitHub refuses ordinary comments on such a fork through the API). The independent reviewer is a model or session run by the maintainer or an agent, given the diff, never a hosted service asked through a public page. Take the time here: on 2026-11-13, after three private rounds, the first public review still found a real problem (step 6), and what a hosted reviewer finds in public is read by everyone before the fix is merged.
6. **Land it and release it together, on the maintainer's word.** Releases are built from `main` ([release workflow](../architecture/build.md#release-workflow-ci)), so the fix has to be public before anyone can install it, and it is public from the moment its branch is pushed to the public repository, not only once it is merged: the pull request shows the diff while the checks run (about five minutes) and until the release is out. Therefore:
   - an agent pushes the branch and opens the public pull request only after the maintainer has said, in the advisory or the fork's pull request, that he is ready to start the release run. Until then the fix stays in the fork;
   - the public pull request is opened as a draft with the label `no-ai-review` (`gh pr create --draft --label no-ai-review`) and then marked ready (`gh pr ready`). The label is added a moment after the pull request exists, so a pull request opened ready would start the AI review before the label is there; a draft starts none, in CI or from CodeRabbit, and when it is marked ready the label is already on it. If the required checks ran only as a draft's, close and reopen the pull request to run them. The Codex connector cannot be kept away from the repository's side ([R67](../security/residual-risks.md)): it reviews when the pull request is marked ready, and writes what it finds in public comments. On #150 it found three real problems that way, each public until its fix was merged. The time between opening and the release is kept short for that reason too, and a finding it posts is fixed in that pull request before anything else;
   - its title, description and commit subject say what changes in plain terms ("harden …"), not what could be done with what it replaces, and do not name the advisory. The squash commit keeps that subject on `main`;
   - the head of the public pull request is the commit that was reviewed in the fork, and a comment there says so in one line ("reviewed privately at `<commit>`; the record is with the advisory"). That line stands in for the review record that [review and merging](pull-requests.md#review-and-merging) asks for, until the advisory is published and the record can be copied over. A commit added after the private review is reviewed like any other change;
   - the required checks run on it as on any pull request. The advisory's own "merge" button is not used: by GitHub's documentation it does not go through branch protection (not tried);
   - a fix that only changes the site is live when the site workflow has deployed it, with no release, so it does not wait for one: the maintainer's word to land it is enough.
7. **Publish.** When the packages are in the repository (or the site is deployed), the maintainer sets the patched version in the advisory and publishes it: that is his act ([GOVERNANCE.md](../../GOVERNANCE.md), security contact), and an agent prepares the text and does not press the button. Then: the [security changelog](../security/changelog.md) entry, the review record on the public pull request, and whatever tracked the finding (a scanner's status, the reporter).
8. **Afterwards** it is public work: follow-ups are ordinary issues.

What an advisory cannot do, so nobody looks for it: it has no labels, no sub-issues and no assignees, and it cannot be added to a project. The description is the place for the list of findings and their state.

## What the installed Apps see

The hosted services installed as GitHub Apps on the organization are installed for "all repositories" ([R67](../security/residual-risks.md)). Checked on 2026-11-13 in the private fork of a draft advisory, with a pull request that changed one blank line:

- Twenty minutes after it was opened, no App had commented, reacted or reported a check there. On a public pull request opened the same hour, CodeRabbit and the Codex connector had both answered within a minute.
- GitHub ran no workflow for it. Its documentation says the same and more: "integrations, including CI, cannot access temporary private forks".
- Not tested: whether an App can read such a fork when it asks GitHub by itself, without an event. The sentence above says it cannot; this page does not rest on it.
- None of the Apps has a permission on the organization's projects, so a draft item of the private project is not theirs to read either.

Whatever they can read there, nothing about an unfixed vulnerability is ever *given* to a hosted reviewer: no `@coderabbitai` or `@codex` request in the fork. The public pull request of step 6 is the one place where the fix does reach them; the label and the short window are what that step has against it, and what a reviewer writes there about a change it does read is public.

Seen on the public pull requests of 2026-11-13 (#150, #178), opened as drafts with `no-ai-review` and then marked ready: CodeRabbit answered "review skipped" and the AI review workflow did not run; the Codex connector reviewed at once and posted its findings as review comments; Blacksmith added its footer to the description. Once a pull request is public, asking the connector again (`@codex review`) after a fix gives away nothing more, and was used as one more independent reading.

## Access for agents

Agents work with the maintainer's token, whose `repo` scope covers the advisories of this repository (`gh api repos/nulavio/nulavio/security-advisories`) and their private forks. The fine-grained token proposed in the [agent guardrails](agent-guardrails.md) would need "Repository security advisories: read and write" for this, and it is limited to `nulavio/nulavio`: whether it could push to an advisory's fork, which is another repository created later, was not tested. Project draft items need the `project` scope (`gh project item-create 1 --owner nulavio --title … --body …`).
