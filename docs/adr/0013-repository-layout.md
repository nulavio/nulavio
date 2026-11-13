# ADR 0013 — Repository layout: one repository, organized by area

- **Status:** Accepted (2026-11-13). Proposed that day in #146; the maintainer, asked to decide it together with [private work](../process/private-work.md), answered "prossiga" (go ahead) the same day, and "manter" (keep) for the installed Apps of point 4. The page is adopted with it. Tracked in [issue #97](https://github.com/nulavio/nulavio/issues/97) and its sub-issues.
- **Related:** [evidence](../research/evidence/org-layout-2026-11-13.md), [issues](../process/issues.md), [pull requests](../process/pull-requests.md), [agent guardrails](../process/agent-guardrails.md), [residual risks](../security/residual-risks.md) R62 and R67.

## Context

The `nulavio` organization has two repositories: `nulavio/nulavio`, which holds the browser, the launcher, the Shell, the tests, the build and release scripts, the site and the Android Companion, and `nulavio/.github`. One maintainer and the coding agents that work for him do all the work. The question in #97: keep one repository, reorganize it, or split parts out, so that it stays healthy for years for people and for agents.

What was measured on 2026-11-13 ([evidence](../research/evidence/org-layout-2026-11-13.md)):

- **It is small where it matters and heavy in one folder.** 9.8 MB of text; 79.4 MB of media, of which 73.6 MB are `docs/design/screenshots/`. 84 % of a clone is those screenshots (94 % is media of some kind). A full clone still took 4 seconds, and 1.9 seconds with a sparse checkout that leaves the design folders out (one run each, on one connection). The real cost is disk: 89 MB for each of the 90 worktrees on the agents' machine.
- **The components change together.** 35 % of the commits on `main` change more than one code component; 26 % on the strictest reading of "component" the evidence tries. With build scripts counted with what they build, the site changed alone in 1 of 15 commits (4 of 15 when edits to policy text are not counted against it) and the Companion in 1 of 8. The site publishes the release (repository file, key, download pages) and uses the product's tokens and brand assets; the Companion and the launcher speak one protocol with shared test vectors.
- **CI is cheap and already filtered.** 12.8 job-minutes for a `ci` run and a median of two runs for a pull request, on runners that are free for a public repository; the engine integration jobs are skipped when a change cannot affect the engine.
- **Outsiders are bound to this repository.** F-Droid's recipe (submitted to fdroiddata) names this repository, its `companion-v*` tags and `android/app`. The release signing role trusts this repository's immutable id. Attestations and the AI review credential name its workflows.
- **Agents get the same 15 k tokens of rules whatever they touch,** and nothing that says what an area needs.
- **Least privilege has two gaps that a split would not close by itself:** the site's deploy token is a repository secret that any workflow on any branch can read, and three hosted Apps hold write access to every repository (R67).
- **Private work had no written home.** Every issue here is public. Vulnerabilities found by audits, scanners and agents, and plans that are not announced yet, need one.

## Options

| | A. One repository, organized by area | B. Hybrid: site, Companion and design media in their own repositories | C. One repository per component |
|---|---|---|---|
| **AI context** | Per-area instructions fix what agents lack today. A cross-cutting change stays one pull request, one review, one CI run. Sparse checkout makes a worktree 12 MB | A site or Companion agent sees less, but most of their changes also touch the product or the release: two pull requests in two repositories, reviewed and merged in order, with a window where they disagree | Every cross-component change (a third of all) becomes coordinated pull requests; an agent needs several checkouts and several sets of rules |
| **Engineering** | Nothing external changes. Required checks, SAST rules, hooks and review rules stay in one place | F-Droid's submission is redone while in review; the nv1 protocol's shared vectors and the site's use of tokens, brand assets and `release.json` need a published contract or a copy that can drift | The same, for every pair: Shell ↔ launcher, tests ↔ everything, release ↔ everything |
| **Architecture** | Matches how the parts ship: one product, one version, one security model. The Companion has its own tags already | Splits along cadence (site: continuous; Companion: F-Droid) but not along coupling | Splits along directories, against both cadence and coupling |
| **Cost** | No migration. One set of branch protection, Dependabot, CodeQL, Scorecard, secrets and Apps | A migration with `git filter-repo`, then three or four sets of settings for one maintainer; Actions stay free | The highest: a setting, a secret and a scanner for each repository, and a release that assembles them |
| **Least privilege** | By environment: release and build secrets already are; the site's token moves to one. Per-area tokens are not possible | The site's token leaves the product repository; the Apps still see everything unless the maintainer limits them | As B |
| **Score (5 best): context / engineering / architecture / cost** | 4 / 5 / 4 / 5 | 3 / 2 / 3 / 2 | 2 / 1 / 2 / 1 |

The scores are the author's judgment of the rows above, with no weights; they are a summary, not a measurement.

What option A costs, so it is not chosen blind: about 80 MB of media stays in every full clone for good; per-area instruction files are one more thing that can drift from the code; ownership per area stays documentation while one account does everything; and if the media budget of point 3 is ever passed, A takes on a second repository after all.

Not chosen inside A: rewriting history to drop the screenshots. It would change every commit id, break the four tags (three releases and the one F-Droid builds from) and every reference in the changelog, the documents and the pull requests, to save 76 MB that a sparse checkout already avoids.

## Decision

**Option A.** One repository, with five changes that make it cheaper to work in. The first four are sub-issues of #97 (#179, #180, #181, #182); the fifth is done by adopting the page.

1. **Instructions per area.** A short `AGENTS.md` in `browser/`, `launcher/`, `android/`, `site/`, `tests/` and `scripts/release/`: what the area is, which documents and invariants apply, which checks to run, what belongs to another area. The root file stays the entry point and the only place for rules that apply everywhere. `.coderabbit.yaml`'s per-area instructions point to these files instead of repeating them. To be checked with each client before relying on it: whether it loads a nested `AGENTS.md` by itself (Claude Code reads `CLAUDE.md`; the root one imports `AGENTS.md`, and a nested one may need the same).
2. **Worktrees without the screenshots.** A documented sparse checkout for agents' worktrees (everything but `docs/design/screenshots/`, about 15.6 MB), used by default by whoever does not work on design. CI keeps the full checkout: the documents' link test needs the files, and so does any test that reads the tree.
3. **A budget for media, with a trigger.** The script of the evidence is run at each release. When media in the history passes 250 MB (three times today), new capture sets go to a repository of their own, public, with no CI, no secrets and no Dependabot, and the documents link to them by commit. Until then captures stay where the documents that cite them are. No history is rewritten in either case.
4. **Least privilege inside one repository.** The site's `CLOUDFLARE_API_TOKEN` moves into an environment limited to `main`, like the release and build secrets (a change to a workflow and to the repository's settings: the maintainer's to apply). The Apps stay as installed: the maintainer's decision of 2026-11-13, with what that leaves open written in R67. The fine-grained agent token of the [guardrails](../process/agent-guardrails.md) stays proposed.
5. **A written home for private work** ([private work](../process/private-work.md)): a vulnerability lives in a draft security advisory and its private fork until the fix ships; a plan that cannot be announced yet lives as a draft item in the organization's private project; everything else is a public issue. The project is the one view over all three. No private repository for now.

Not changed: build scripts stay under `scripts/` (moving them would rewrite paths in the workflows, CODEOWNERS and the documents for no measured gain; the per-area files name them). `nulavio/.github` stays as it is. Flathub's manifest repository will exist under the `flathub` organization whatever is decided here.

## When to look again

- The Companion gets a second maintainer or its own release team, or F-Droid needs a layout this repository cannot give.
- The site gets a build of its own (a framework, a package manager beyond the pinned deploy tool) or a contributor who should not see the product's CI.
- Media passes the budget in point 3.
- A second maintainer or an outside audit brings more private findings at once than a handful of advisories can hold: then a private repository for triage (point 5) is worth its upkeep.
- GitHub lets one account hold separate identities for agents and the maintainer: then approvals mean something and per-area ownership can be enforced.

## Consequences

- **Accepted:** four sub-issues and one adopted page, none of which moves code. Agents read less and know what an area needs. The cost of the screenshots stops growing unseen. Private work has one rule.
- **If B or C is chosen instead:** the migration plan has to redo F-Droid's submission, re-bind the signing role and the attestations, publish the nv1 protocol's vectors and the brand tokens as something two repositories consume, and repeat every repository setting; the evidence lists each consumer.
- **Either way:** the evidence and its script stay, so the question is reopened with new numbers, not with new opinions.
