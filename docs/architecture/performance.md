# Performance

How Nulavio's performance is measured, and the numbers (#80). Requirement: [NFR-02](../product/requirements.md#non-functional).

## The suite

One command, [`scripts/perf/run.py`](../../scripts/perf/run.py), measures a Nulavio build against a baseline build, and with `--firefox` against Mozilla's Firefox. Each side starts from a fresh profile, and the runs alternate the sides, so a machine that slows down slows all of them.

- **Startup:** from the process to the engine's "session restored", on the profile's first start and on its second.
- **Memory:** the proportional memory (PSS) of every process of the instance, with 1 and 10 tabs of a local page, after the engine's own "Minimize memory usage".
  - It is read on the profile's third start. The second start runs 60 s first: a new profile's first work, uBlock Origin compiling its lists, held the extension process at up to 1.3 GiB for about 40 s ([below](#a-new-profiles-first-minute-2026-11-17), #362).
- **First minute** (`--first-minute`): the highest PSS of the whole instance in the 60 s after a new profile's first start, and in the 60 s its second start runs anyway.
  - It is read until two readings in a row agree within 3 %.
- **Frame time** (`--frames`): the UX7 scenes of [`frame_scene.py`](../../scripts/research/frame_scene.py) on a private Xvfb. These are the sidebar, a tab switch, a Settings dialog and the new tab ([budget](../design/design-system.md#ux7-motion-and-performance-budget-2026-11-04)).
- **Benchmarks:** Speedometer 3.1, JetStream 3.0 and MotionMark 1.3.2. Each is pinned to an upstream commit and its archive's SHA-256, served from the machine, and run in a start of its own.
- **Firefox:** Mozilla's linux-x86_64 archive, pinned by SHA-256 and SHA-512. Its SHA-512 is the line in Mozilla's `SHA512SUMS`, whose signature is checked with the release key that [`verify_firefox_release.py`](../../scripts/upstream/verify_firefox_release.py) pins.

The table gives each side's median and the build's change against the baseline, with a 95 % bootstrap interval from 5 runs a side.

**A change whose interval holds 0 is not told apart from noise.** With the same engine on both sides, 5 runs give intervals of about ±3 to ±11 % for startup and ±9 % for memory (#361). Smaller changes need more runs.

`--fingerprinting-cost` turns the engine's fingerprinting protections off for one start. That is a named exception to "never turn a protection off", for this measure only. It applies only in a throwaway profile under the temporary directory, checked before anything is turned off. That profile then loads only the benchmark's own pages from loopback, and its `user.js` sets the protections again at its next start. A test keeps the switch from being used anywhere else.

All of it runs headless with software rendering. It is a regression signal for this project, not a measure of a person's hardware.

## When it runs

- **By hand**, before and after a change that may cost time or memory.
- **On every published release**, by [`perf.yml`](../../.github/workflows/perf.yml):
  - It compares the release with the published release before it and with Firefox, both checked against their `SHA256SUMS` signed with the release key ([`fetch_releases.py`](../../scripts/perf/fetch_releases.py)).
  - It runs 5 runs with Speedometer, on a GitHub-hosted runner, in the integration job's container, and fails a run whose web content processes are not in the full content sandbox.
  - The table goes into the job summary and the JSON into a 90-day artifact per release, which is the history. Since #367 a measure worse than its threshold (below) fails the run, with the reason in the summary. The release is already published by then: the maintainer reads the result, and a regression is a bug for the next release.

## Thresholds

Decided on 2026-11-18 (#367) from four `perf.yml` runs on GitHub's runner, kept in [the evidence folder](../research/evidence/perf-runner-noise-2026-11-18/) (the artifacts expire after 90 days): 160.0-0.6 against 0.5 twice (run 43908609249 on release, 44220905151 by hand), 0.5 against 0.4, and 0.4 against 0.3.

**The runner's noise, as measured:**

| Measure | Spread of 5 runs (coefficient of variation) | The same comparison twice (0.6 against 0.5) | Largest change between releases with no change meant to affect it | Widest 95 % interval |
|---|---|---|---|---|
| First start | 1–10 %, one run 23 % (a single slow start) | +1.1 %, +4.1 % | +4.1 % | −7 … +55 % |
| Second start | 2–9 % | −3.5 %, −1.1 % | −3.5 % | −10.3 … +14.0 % |
| Memory, 1 and 10 tabs | 0.1–4.7 % | −0.1 %, +0.1 % | −4.7 % | −8.4 … +8.7 % |
| Speedometer 3 | 1–7 % | −1.3 %, +3.5 % | +3.5 % | −7.6 … +11.5 % |

Between runs on different days the absolute numbers move a lot (the first start of 0.6: 1246 ms, then 906 ms; Speedometer 12.2, then 15.6): the runner's hardware differs from run to run. Only the change against the release before, measured in the same run, is compared.

**The gate** (`scripts/perf/gate.py`, in `perf.yml` since #367): a measure fails when its 95 % interval excludes 0 on the worse side **and** its median change is worse than:

| Measure | Fails past |
|---|---|
| First and second start | +15 % |
| Memory, 1 and 10 tabs | +10 % |
| Speedometer 3 | −10 % |

That is two to four times the largest change seen with no change meant (memory 2.1×, Speedometer 2.9×, first and second start 3.7× and 4.3×). A measure that was not measured, has no interval, or (memory) had processes whose memory could not be read (`unreadable_*_tabs` in the JSON: their memory is missing from the sum, so the reading is too low on either side) is not judged, and fails in `perf.yml` too (`--strict`): it always measures all five, so a missing one means the measuring broke. Past a threshold is strict: exactly +10 % passes, and a failure prints enough digits to be seen past the limit. The interval alone is not enough: 0.4 against 0.3 shows a first start 2.3 % slower with an interval of +0.5 … +5.0 %: outside noise, but far under the threshold, and a change that small cannot be told apart from the runner's variation between runs, so it does not fail. The four runs above all pass. The thresholds are looked at again when the gate fails on a release with no change that explains it, or when ten releases have run.

For 1.0, the [release criterion](../product/release-criteria.md#scope-of-10-decided-2026-11-04) is this gate: the 1.0 candidate's run against the release before it passes it, or the reason is recorded.

## Baseline, 2026-11-15

Nulavio 160.0-0.5 and 160.0-0.4 come from their GitHub releases' archives (signature and SHA-256 checked); they share the engine build. Firefox 160.0 is Mozilla's.

- Machine: AMD Ryzen 7 5825U (8 cores, 16 threads), 30 GiB, Fedora 44, headless.
- Startup, memory and frame time: 5 runs a side.
- Benchmarks: 1 run.
- Raw results: [evidence](../research/evidence/perf-baseline-2026-11-15/).

| measure | 160.0-0.5 | 160.0-0.4 | 0.5 against 0.4 (95 % interval) | Firefox 160.0 |
|---|---|---|---|---|
| startup, first start | 994 ms | 973 ms | +2.2 % (−9.4 … +11.1) | 678 ms |
| startup, second start | 508 ms | 496 ms | +2.4 % (−5.4 … +14.3) | 348 ms |
| memory, 1 tab (PSS) | 536 MiB | 491 MiB | +9.1 % (−8.9 … +9.8) | 431 MiB |
| memory, 10 tabs (PSS) | 588 MiB | 540 MiB | +8.9 % (−8.1 … +9.0) | 457 MiB |
| processes, 10 tabs | 11 | 11 | | 11 |
| frame interval, sidebar collapse / expand | 16.9 / 16.9 ms | 16.9 / 16.9 ms | −0.2 / +0.1 % | |
| frame interval, tab switch | 17.0 ms | 17.0 ms | −0.1 % (−0.3 … +0.2) | |
| frame interval, Settings dialog | 17.1 ms | 17.1 ms | +0.0 % | |
| new tab, to its first paint | 69 ms | 67 ms | +3.0 % (−2.1 … +10.1) | |
| Speedometer 3.1 | 13.0 | 12.4 | (1 run) | 19.1 |
| JetStream 3.0 | 121.4 | 119.6 | (1 run) | 136.5 |
| MotionMark 1.3.2 | 779 | 779 | (1 run) | 917 |

What the numbers say:

- **0.5 against 0.4:** no change told apart from noise. Every interval holds 0.
- **Nulavio against Firefox:** startup is about 47 % slower, memory with 10 tabs about 29 % higher, and Speedometer about a third lower.
  - The two diagnoses below point at the build: Mozilla's builds use PGO and full cross-language LTO, and Nulavio's uses thin LTO for Rust only.
  - The maintainer decided for C++ LTO first, then PGO (#364, 2026-11-15). The first part is measured [below](#cross-language-lto-2026-11-17): it closes little of the distance. PGO waits until after 1.0 ([#612](https://github.com/nulavio/nulavio/issues/612)).
  - NFR-02 ("comparable to the engine") is not met.

Two diagnoses, both Speedometer with 3 iterations:

| | score |
|---|---|
| Firefox 160.0 | 18.7 |
| Firefox 160.0 with Nulavio's preferences (`baseline.js`: ETP Strict, the fingerprinting overrides) | 18.6 |
| Nulavio 160.0-0.5 | 12.1 |
| Nulavio 160.0-0.5 with uBlock Origin turned off | 12.9 |

## Cross-language LTO, 2026-11-17

The release build is linked with link-time optimisation across C++ and Rust since #364 (`--enable-lto=cross`, thin). This is its first build, measured before any release carries it: the archive of the rehearsal of `main` at 43a41674 (`release.yml` with `publish: false`, run 44025025108), against 160.0-0.6 from its GitHub release (signature and SHA-256 checked), which has no C++ LTO, and Mozilla's Firefox 160.0.

- Machine: the same as the baseline's. 5 runs a side, Speedometer included.
- Raw results: [evidence](../research/evidence/perf-cross-lto-2026-11-17/).

| measure | with cross-language LTO | 160.0-0.6 | against 0.6 (95 % interval) | Firefox 160.0 |
|---|---|---|---|---|
| startup, first start | 950 ms | 997 ms | −4.7 % (−15.7 … −2.4) | 685 ms |
| startup, second start | 500 ms | 502 ms | −0.4 % (−7.9 … +8.8) | 347 ms |
| memory, 1 tab (PSS) | 544 MiB | 549 MiB | −1.0 % (−1.1 … +8.4) | 420 MiB |
| memory, 10 tabs (PSS) | 593 MiB | 599 MiB | −0.9 % (−1.0 … +7.7) | 446 MiB |
| processes, 10 tabs | 11 | 11 | | 11 |
| Speedometer 3.1 | 13.1 | 12.7 | +3.3 % (+2.0 … +4.5) | 19.1 |

What the numbers say:

- **It is faster, by little.** Speedometer gains 3.3 % and the first start is 4.7 % shorter; both intervals exclude 0. The second start and memory do not move. `libxul.so` is 2.7 % smaller (187.0 MB against 192.2 MB).
- **The distance to Firefox is almost all still there:** the first start is 39 % slower (it was 46 % for 0.6 in this run), Speedometer 32 % lower (34 %), memory with 10 tabs 33 % higher (34 %). NFR-02 is still not met.
- **So the missing C++ LTO was a small part of the difference.** The baseline's guess named two things Mozilla's builds have and Nulavio's did not; this one accounts for about two points of Speedometer's 34. What is left has not been diagnosed. Profile-guided optimisation is the other thing named; that it explains the rest is a guess until a build with it is measured.
- **Nulavio's LTO is not Mozilla's.** Both are cross-language; Mozilla's Linux x86_64 release builds are full LTO with PGO, and Nulavio's is thin without PGO. The engine's configure chooses: `--enable-lto=cross` alone becomes full only in a PGO build in Mozilla's automation, where its comment says the pair is what pays on Speedometer (`build/moz.configure/lto-pgo.configure`). Full LTO without PGO was not tried here; it needs more memory at the link than thin.
- **What ships, and the gap that is left.** Nulavio ships thin cross-language LTO without PGO, until [#612](https://github.com/nulavio/nulavio/issues/612) (After 1.0) is done. Mozilla's Linux release is full cross-language LTO with PGO. The gap, from the run above: Speedometer 32 % lower than Firefox 160.0 (13.1 against 19.1), first start 39 % slower (950 ms against 685 ms), memory with 10 tabs 33 % higher (593 MiB against 446 MiB). PGO was moved out of 1.0 by the maintainer on 2026-11-24: by his estimate (not measured) it would about double the release build's time, against the internal 24-hour target for urgent security releases (the commitment is 72 hours, [update policy](update-policy.md#urgency)). With this build NFR-02 is not met; the 1.0 candidate is measured again by the [release criteria](../product/release-criteria.md). How much of the first start's gap is the Shell's own startup work is not measured yet ([#617](https://github.com/nulavio/nulavio/issues/617)).
- **What it cost:** the build takes 20 min 26 s on the build machine where it took 17 min 49 s, with the same room in memory; and the engine's own networking check no longer runs in the build that ships, with Nulavio's reading and its attestation in its place ([build](build.md#the-networking-check-on-rust-code), [R79](../security/residual-risks.md)).
- Not measured here: frame time, JetStream and MotionMark.

## A new profile's first minute, 2026-11-17

#362 asked what holds the extension process at about 1.2 GiB in a new profile's first minute, and whether it can be lowered.

- Machine: the same as the baseline's. Nulavio 160.0, the locally built engine with `main`'s Shell, headless, a new profile.
- How:
  - the PSS of every process every few seconds for 60 s after each of the first three starts;
  - an `about:memory` dump of every process at the extension process's peak;
  - `scripts/perf/run.py --first-minute` once, the build against itself.
- Raw results: [evidence](../research/evidence/first-minute-2026-11-17/). The memory dump itself is not kept: it holds local paths.

| start | extension process, peak | whole instance, peak | when |
|---|---|---|---|
| first | 1318 MiB | 1941 MiB | about 8 s after the start, back to about 170 MiB after about 40 s |
| second | 457 MiB | 936 MiB | |
| third | 644 MiB | 1179 MiB | about 56 s after the start (a list update, below) |

`run.py --first-minute` gave a peak of 1862 MiB (build) and 1824 MiB (baseline) for the whole instance in the first minute, and 953 and 931 MiB in the second. The same build with one tab settles at about 500 MiB.

What it is:
- **It is uBlock Origin compiling its filter lists**, in its background page (`background.html`) in the extension process.
- At the peak, that page's window objects held about 337 MiB, and one more JavaScript zone of the process about 130 MiB. The large strings are the lists in uBlock Origin's compiled format (`#block-start-NETWORK_FILTERS:GOOD`).
- **The largest single item is one list:** the "Online Malicious URL Blocklist" (URLhaus, `urlhaus-1`) compiled into one string of 76 million characters, about 164 MiB. The next lists take 12, 8, 7 and 5 MiB.
- On 2026-11-15, with uBlock Origin 1.75.0 and the 0.4 package, the peak came after the first two starts. Here, with 1.76.4, it comes after the first only. Why it moved was not looked into.
- The third start's peak is uBlock Origin updating its lists a minute after the start and compiling them again, so every list update brings it back.

Why Nulavio does not lower it now:
- **The heaviest list is the content filter's only malware list.** uBlock Origin turns the same list on by default for everyone. Taking it out, or a lighter set first, weakens a protection, which CONTRIBUTING's non-negotiables forbid without the maintainer's decision.
- **uBlock Origin offers no way to ship its compiled lists with an install** (its "selfie" is written by itself, after a first compile), **nor to delay or spread that compile.** Both are changes to uBlock Origin's own code; asking its maintainers is the maintainer's to decide.
- So a person's first minute in Nulavio costs about 1.3 GiB more than a settled one, for about 40 s, and again for a moment whenever the lists update. On a machine with 4 GiB that can mean swap during the first pages.

`scripts/perf/run.py --first-minute` now gives this as a number (`first_minute_peak_mib`, `second_minute_peak_mib`), so a change to the content filter's lists, or a new uBlock Origin, shows up in it.
