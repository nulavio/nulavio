---
name: nulavio-private-security-fix
description: Use as soon as you find, suspect or are given a possible vulnerability in Nulavio's code, configuration, build, release or site, before writing anything about it anywhere. Says what never goes in public, how to open the draft advisory, where the fix is developed and reviewed, and when it may become public.
---

# A vulnerability in Nulavio

The steps are in [docs/process/private-work.md](../../../docs/process/private-work.md);
read the whole page before step 2. This skill exists so the first moves are
right, because a public word cannot be taken back.

## Stop first

Write nothing about it in public: not an issue, a pull request, a commit
message, a branch name, a code comment, a Discussion, or a request to a hosted
reviewer (CodeRabbit, the Codex connector, the CI AI review). A public change
that fixes it silently is a disclosure too. If you are in the middle of another
pull request, keep the finding out of it.

A finding that is not confirmed yet is handled the same way: a draft advisory
whose summary starts with "Triage:". A vulnerability in Firefox itself goes to
Mozilla instead.

## Then

1. Open a draft security advisory with a private fork
   (`gh api -X POST repos/nulavio/nulavio/security-advisories --input advisory.json`,
   `start_private_fork: true`). A draft is visible to nobody else: no need to
   ask first. One advisory per release that fixes things; a reported, high or
   critical finding, or one that should have a CVE, gets its own.
2. Fix it in the fork `nulavio/nulavio-ghsa-<id>` on a branch `sec/<date>-<letter>`
   (`sec/2026-11-a`): the name becomes public later and says nothing about the flaw.
3. Test on your machine: no workflow runs in the fork. Run ruff, the unit tests,
   `scripts/security/scan.sh` and the integration tests that apply, and write
   commands and results in the fork's pull request. The fix comes with a test
   that fails without it.
4. Review there: the recorded review and an independent second one, by a model
   or session given the diff, never a hosted service.
5. Stop. Pushing to the public repository, opening the public pull request
   (as a draft with the label `no-ai-review`, then ready), the release, and
   publishing the advisory wait for the maintainer's word as the page says. A
   site-only fix needs his word to land, not a release.

Secrets, tokens and personal data never go on GitHub at all.
