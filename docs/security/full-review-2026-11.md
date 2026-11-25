# Full review of what Nulavio ships, November 2026

[#454](https://github.com/nulavio/nulavio/issues/454) reviewed everything Nulavio ships at one commit of `main`: `74edfea4` (2026-11-24). Before this review, only the Vault and the release chain had a review scoped as a whole ([scope packet](independent-review.md), #224). Everything else had been read one pull request or one area at a time.

## Method

- **Areas.** The product was split into twelve areas: engine configuration, engine patches, Shell modules and actors, Shell pages, Settings, launcher and tools, AI Bridge and assistant, Vault and unlock, the Android Companion and its pairing, the site, CI and release, and dependencies.
- **Reviewers.** Each area was reviewed by a model other than the one that wrote most of it. The reviewer used the area's `AGENTS.md`, the [trust boundaries](../architecture/trust-boundaries.md), the threat-model scenarios that apply, and the invariants in [`REVIEW.md`](../../REVIEW.md). The reviewers were GPT-6.2 Sol and Claude Fable 5.2 or Opus 5.5. The OpenAI models' safety filter refused six areas, so Claude models reviewed those.
- **Verification.** A second model checked every finding adversarially, against the code and with targeted scripts where it was safe to run them.
- **Gaps.** A completeness pass read every reviewer's coverage notes, then reviewed five gaps nobody had reached, mostly where two areas meet: agents on a person's own profiles, agent input and Shell pages, the assistant panel, routing entry points, and window spoofing.
- **Tools on the commit.**
  - The scanners in `ci`: actionlint, zizmor, gitleaks, shellcheck, Opengrep.
  - CodeQL.
  - An AddressSanitizer run of the integration suite: 682 tests, no report.
  - A fuzz run.
  - The release rehearsal.

The checklist, with who reviewed each area, is on #454.

## What was found

- **Vulnerabilities: nine groups, all medium or low.**
  - **Where:** AI Bridge grants, Shell pages, phone pairing, the assistant key, the waitlist, confined mode, Vault entry points, the look-alike login warning, and Fedora update keys.
  - **Fix:** all of them were fixed privately and released together in [160.0.1-0.3](https://github.com/nulavio/nulavio/releases/tag/v160.0.1-0.3) (#694) on 2026-11-25.
  - **Advisory:** [GHSA-7qcr-35cg-393g](https://github.com/nulavio/nulavio/security/advisories/GHSA-7qcr-35cg-393g).
  - **Exploitation:** nothing suggests any of them was used against anyone.
  - **What the fixes leave:** recorded in the [residual risks](residual-risks.md) (R41, R83, R85, R86, R87) and in the [security changelog](changelog.md).
- **Not public yet: one more private advisory.** It is published, and added here, when its fix ships.
- **Ordinary bugs, doc errors and hardening: 90 public issues.** Each ends with "Found by the full review (#454)".
  - 74 were filed on 2026-11-24.
  - 16 were filed on 2026-11-25, after the advisory, because their text was close to a finding that was not public yet.
  - Two more drafts were not filed, because #694 had already fixed them.
  - Bugs and errors in the security docs are in milestone 1.0. Low-priority hardening is in After 1.0.
- **Docs the review showed wrong.** The fixes corrected the threat models, the trust boundaries, the residual risks and the ADRs they touch. The errors that remain in the security docs each have an issue in 1.0.

## Limits

- **Coverage.** The review read one commit, with the areas' own documents as its map. Code that changed after `74edfea4` is reviewed one pull request at a time, as before.
- **Who reviewed.** The reviewers are AI models, not an outside firm. The independent review of the Vault and the release chain (#224) is separate from this one.
- **What was run.** The reproductions ran against that commit's code and test engines. A finding that needs a real phone, account or network was argued from the code, and the finding says so.
