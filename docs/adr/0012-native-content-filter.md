# ADR 0012 — Nulavio Filter: keep uBlock Origin, or a native filter on adblock-rust

- **Status:** Proposed (draft, 2026-11-11). Nothing changes until the [spike](../research/spike-native-content-filter.md) meets its approval criteria; until then uBlock Origin stays the filter (option A).
- **Related:** [ADR 0001](0001-engine-selection.md) (Gecko, full uBlock Origin), [extension model](../architecture/extension-model.md), [residual risks](../security/residual-risks.md) R6 and R39, issue #80 (performance suite), spike [issue #95](https://github.com/nulavio/nulavio/issues/95).

## Context

Nulavio Filter is uBlock Origin, pinned from AMO and installed by the build's policy, plus Enhanced Tracking Protection in Strict mode. It works with its full feature set on Gecko, and the 50-site run of 2026-10-26 found no breakage it caused.

What it leaves open:

- **Integration.** Settings cannot read or change uBlock Origin's per-site switch or trusted sites (R39). The Privacy pages can only point at uBlock Origin's own dashboard.
- **Cost per request.** Every request crosses from the network code to the extension process and back before it can go out. Not measured on Nulavio.
- **Dependency.** The filter that defines a large part of Nulavio's privacy is a third-party extension with essentially one maintainer, updated through AMO.

Brave's [adblock-rust](https://github.com/brave/adblock-rust) (MPL-2.0, the engine Brave builds into its browser) is a candidate for a filter Nulavio owns. It matches requests and resolves cosmetic filters and scriptlets. Intercepting requests, injecting styles and scriptlets, updating lists and the per-site UI remain the browser's job.

## Options

| Option | For | Against |
|---|---|---|
| A. **Keep uBlock Origin** + ETP Strict (today) | Full features (dynamic filtering, logger, element picker); maintained by its community against anti-adblock every week; runs outside the parent process; no engine patch | R39 stays; per-request round trip to the extension process; third-party dependency |
| B. adblock-rust compiled to WebAssembly inside Nulavio's built-in add-on | No engine patch; Nulavio owns the per-site state (closes R39); stays in the extension process | Same round trip as A; we maintain cosmetic filtering, scriptlets and list updates; fewer features than A |
| C. adblock-rust **native in the engine**: network blocking in the engine, cosmetic filters and scriptlets through the built-in add-on or engine actors | No round trip; blocks from the first request; Nulavio owns the state (R39) | Larger patch stack and rebase cost on every engine update; matching in the parent process; we maintain cosmetic filtering, scriptlets and list updates |
| D. Fork uBlock Origin, or rewrite it (in Rust or otherwise) | Full control | Loses the weekly upstream fixes the day after the fork; stays GPL-3.0 as derived work; rewriting a mature blocker is out of scope for a small team |
| E. Fork adblock-rust | Full control of the engine | Not needed: it is a library with a compatible licence; we contribute upstream and fork only if Brave's direction becomes incompatible |

## Decision (proposed)

1. **No fork of either project (D and E rejected).** The value of a content blocker is in its continuous upstream maintenance.
2. **A stays until the spike concludes.** Nothing ships from the spike before this ADR is accepted.
3. **The spike measures C first and B as the fallback** for the case where C's performance gain is small but integration (R39) still justifies the change. Approval criteria A1–A10 in the [spike plan](../research/spike-native-content-filter.md#approval-criteria-for-adr-0012-to-be-accepted) decide.
4. If C or B is accepted, uBlock Origin is no longer installed by default, and a user can still install it from AMO. The two must not filter at the same time without the user knowing. The rollout is a separate, issue-tracked plan.

## Consequences

- **If accepted (B or C):** Nulavio maintains a filter, its list updates and its breakage reports. The patch-stack policy and the update SLA need room for C. The threat model gains a parent-process component that processes data derived from untrusted lists. The SBOM gains the crate and its dependencies.
- **If rejected:** R39 stays as documented. Integration work goes through uBlock Origin's documented management interfaces only, and the evidence is kept so the question is not reopened without new facts (a change in uBlock Origin's maintenance, in Gecko's `webRequest`, or in adblock-rust).
