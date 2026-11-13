# Spike: a native content filter (adblock-rust) against uBlock Origin

- **Status:** planned, not started (2026-11-11). Nothing here changes what Nulavio ships.
- **Decision it feeds:** [ADR 0012](../adr/0012-native-content-filter.md) (proposed).
- **Tracking:** [issue #95](https://github.com/nulavio/nulavio/issues/95); each phase ends with a comment there ([how we use issues](../process/issues.md)).

## The question

Should Nulavio Filter move from uBlock Origin (an extension, GPL-3.0) to a filter built into the browser on [adblock-rust](https://github.com/brave/adblock-rust) (Brave's engine, a Rust library, MPL-2.0, 0.13.5 on 2026-10-28)? It is worth it only if Nulavio gets faster pages, a smaller attack surface or a Settings page that knows the filter's real state, and blocks at least as well as today.

## What we already know

- On Gecko, uBlock Origin keeps its full feature set because Firefox keeps the blocking `webRequest` API ([ADR 0001](../adr/0001-engine-selection.md)). Nothing forces Nulavio to change. Brave filters inside the browser's network code, not through that API, and wrote adblock-rust in 2019 to replace its earlier C++ engine for speed ([announcement](https://brave.com/blog/improved-ad-blocker-performance/)): it is a matching library made to be embedded.
- adblock-rust matches requests and resolves which cosmetic filters and scriptlets apply. Everything else is the browser's job: intercepting requests, hiding elements, injecting scriptlets before the page's own scripts, downloading and checking the lists, and the per-site switch.
- Today Settings cannot see uBlock Origin's per-site switch or its trusted sites ([residual risk R39](../security/residual-risks.md)). A filter Nulavio owns would fix that.
- uBlock Origin runs in the extension process. A native filter would run its matching in the parent process, the most privileged one, so a bug there costs more.
- Every request uBlock Origin sees crosses from the network code to the extension process and back. A native filter avoids that round trip. Nobody has measured how much of a page load this round trip costs on Nulavio.

## Out of scope

- Forking uBlock Origin or adblock-rust, or rewriting either. adblock-rust is used as a pinned upstream dependency and fixes go upstream ([ADR 0012](../adr/0012-native-content-filter.md#options), options D and E).
- Shipping anything. Prototype code lives on a branch behind a build flag that is off. It merges only after ADR 0012 is accepted.
- The element picker, the logger and dynamic filtering. The spike lists them as features we would lose, it does not rebuild them.

## Setup shared by every measurement

- The same Nulavio build, machine and power profile, with the network warm. Each figure is the median of at least five runs, with p95 and the spread.
- The same lists on both sides: what a new profile gets today, which is uBlock Origin's own default lists, the list for the person's language, and the cookie-notice lists of [`content-filter.json`](../../browser/distribution/content-filter.json). All lists are pinned by hash for the duration of the spike.
- Corpus: the 50 public pages of [`tests/regression/sites.json`](../../tests/regression/sites.json). Every request they make is recorded once (URL, type, initiator), so both engines are fed the same input.
- Results go to `docs/research/evidence/spike-native-filter-<phase>-<date>.json` together with the commit, the engine build and the versions of the lists.

## Phases

Each phase ends with a go/no-go decision, posted as a comment on the issue. A no-go closes the spike, and the ADR records why.

### Phase 1: offline, no engine change (about 2 days)

Compare the two matching engines outside the browser, on the recorded corpus:

- adblock-rust through a small Rust harness, at the pinned version;
- uBlock Origin's own static filtering engine through [`@gorhill/ubo-core`](https://www.npmjs.com/package/@gorhill/ubo-core), which is published by uBlock Origin's author (GPL-3.0, used here only as a test tool and never shipped).

Measure:

- agreement: which requests one blocks and the other does not, by list and by request type;
- matching cost per request (median, p95);
- time to load and compile the lists, and the memory the result takes;
- size of the serialized adblock-rust engine.

**Go when** adblock-rust blocks at least 98% of what uBlock Origin blocks on the corpus, no request it misses is one that a privacy or malware list blocks (criterion A1), and every request it blocks and uBlock Origin does not is listed with the rule that matched. **No-go** under 90%, or when the differences come from list syntax that adblock-rust does not support and upstream has no plan for.

Whether those extra blocks break a page cannot be answered here: nothing in this phase puts adblock-rust's decisions into a browser, and `run_sites.py` compares Nulavio with uBlock Origin against a stock engine, not one filter against another. Phase 2 gives it a mode that runs the corpus with the candidate filtering in place of uBlock Origin; breakage is judged from there on (criterion A3).

### Phase 2: network blocking inside the engine (about 4 days)

A prototype that blocks requests only, with no cosmetic filtering yet:

- adblock-rust vendored in the engine's Rust tree, behind a build flag;
- candidate integration points, to choose between: a URL classifier feature (where Enhanced Tracking Protection already blocks) and a request observer. The phase picks one and records why;
- lists downloaded and checked exactly as `extensions.lock.json` checks an extension (pinned source, hash). They are compiled outside the parent process, which only loads the serialized result;
- the per-site switch read and written by Settings;
- a mode of `tests/regression/run_sites.py` that runs the corpus with the prototype filtering and uBlock Origin off, so that the two filters can be compared page by page.

Measure against uBlock Origin on the same build:

- page load on the corpus (load event, Largest Contentful Paint), cold and warm;
- start-up: time until the first page can load, and **whether any request the filter would block leaves before the filter is ready** (criterion A4);
- memory of the parent process and of the extension process with the lists loaded (`about:memory`);
- Speedometer 3, JetStream and MotionMark as regression guards (shared with #80);
- patch size outside `third_party/`, and build time and binary size added.

### Phase 3: cosmetic filters, scriptlets, security (about 4 days)

- Element hiding: one stylesheet per document for the specific filters, generic class and id filters as the page changes, and procedural filters in the content process.
- Scriptlets: injected before the page's own scripts, in the page's world, in every frame. The phase tries the built-in add-on's `scripting` API first, then an engine actor.
- Scriptlet sources: the licence of every scriptlet we would ship. Brave's `adblock-resources` is MPL-2.0 at the repository level, but scriptlets that come from uBlock Origin are GPL-3.0. Record the exact source of each one.
- Visible ads on the corpus compared with screenshots (`run_sites.py`, `pngdiff`), and breakage triaged as in the [October run](site-regression-2026-10.md).
- Fuzzing (`cargo-fuzz`): the list parser and the loader of the serialized engine.
- What a panic does in the parent process, and how to contain it.
- Threat model entries: new trust boundary, where untrusted lists are parsed.
- Dependencies of the crate: licences, `cargo-deny`/`cargo-vet` result, SBOM entry.
- Rebase rehearsal: apply the patch to the next engine version and time the conflicts.

## Approval criteria (for ADR 0012 to be accepted)

All of them must hold. Each one names the evidence that proves it.

| # | Criterion | Threshold | Evidence |
|---|---|---|---|
| A1 | Network blocking | ≥ 98% of uBlock Origin's blocks on the corpus, **and** every block it misses is listed with the list and rule that made uBlock Origin block it. None of them may come from a privacy or malware list (the registry's groups `privacy` and `malware`, and uBlock filters – Privacy and – Badware risks): a tracker or a malware address that gets through fails the criterion, whatever the percentage. A miss from a list that mixes ads and tracking (Peter Lowe's) is classified by hand and fails the same way when it is a tracking server. The 2% is room for ad requests only | phase 1 and 2 JSON, with the table of misses |
| A2 | Element hiding | ≥ 95% of the ad slots uBlock Origin hides are hidden | phase 3 screenshots |
| A3 | Breakage | no more breakages caused by the filter than with uBlock Origin on `sites.json`, counted after the triage of the [October run](site-regression-2026-10.md) (6 pages flagged then, 0 breakages). A flagged page is a lead: an ad slot removed or a site variant is not a breakage | `run_sites.py` in the mode phase 2 adds (candidate in place of uBlock Origin), and its triage table |
| A4 | Start-up | zero requests that the ready filter blocks leave before it is ready. That covers rules by address and by type on a site that is otherwise allowed (such as `/adbanners/*$image`, which `test_engine_slice.py` checks for uBlock Origin today), not only listed domains. Probed on purpose: requests of each kind made by the first page of a cold start and of a restored session | phase 2 network log and the probe's result |
| A5 | A real gain | at least one: page load median ≥ 5% faster on the corpus; ≥ 30 MB less memory overall; Settings shows and changes the real per-site state (closes R39) | phase 2 and 3 |
| A6 | No loss elsewhere | no metric worse by more than its run-to-run noise, browser benchmarks included | phase 2 |
| A7 | Security | untrusted lists are never parsed in the parent process; 24 CPU-hours of fuzzing per target without a crash; a panic cannot leave requests unfiltered; threat model and residual risks updated | phase 3 |
| A8 | Maintenance cost | ≤ 1,500 changed lines in the patch stack outside `third_party/`; the rebase onto one new engine version takes ≤ 1 working day | phase 2 and 3 |
| A9 | Licences | every shipped file is compatible with MPL-2.0 or kept separate as data, the way uBlock Origin is today | phase 3 |
| A10 | What users lose | the list of uBlock Origin features that are gone, and how a user who needs them can still install uBlock Origin, accepted by the maintainer | report |

## Stop early when

- injecting scriptlets before the page's scripts needs a large engine patch or does not hold in every frame;
- phase 1 ends under 90% agreement;
- the time box (about two working weeks in total) runs out before phase 3 can conclude. The ADR then says what is still unknown.

## What the spike delivers

- The evidence files and a short report in this folder.
- ADR 0012 moved to *Accepted* (with the chosen option) or *Rejected*, with the reasons.
- When accepted, an implementation plan split into issues (sub-issues of the spike issue).
