# Performance

How Nulavio's performance is measured, and the numbers (#80). Requirement: [NFR-02](../product/requirements.md#non-functional).

## The suite

One command, [`scripts/perf/run.py`](../../scripts/perf/run.py), measures a Nulavio build against a baseline build, and with `--firefox` against Mozilla's Firefox. Each side starts from a fresh profile, and the runs alternate the sides, so a machine that slows down slows all of them.

- **Startup:** from the process to the engine's "session restored", on the profile's first start and on its second.
- **Memory:** the proportional memory (PSS) of every process of the instance, with 1 and 10 tabs of a local page, after the engine's own "Minimize memory usage".
  - It is read on the profile's third start. The second start runs 60 s first: a new profile's first work held the extension process at up to 1.2 GiB for about 30 s after each of the first two starts (#362).
  - It is read until two readings in a row agree within 3 %.
- **Frame time** (`--frames`): the UX7 scenes of [`frame_scene.py`](../../scripts/research/frame_scene.py) on a private Xvfb. These are the sidebar, a tab switch, a Settings dialog and the new tab ([budget](../design/design-system.md#ux7-motion-and-performance-budget-2026-11-04)).
- **Benchmarks:** Speedometer 3.1, JetStream 3.0 and MotionMark 1.3.2. Each is pinned to an upstream commit and its archive's SHA-256, served from the machine, and run in a start of its own.
- **Firefox:** Mozilla's linux-x86_64 archive, pinned by SHA-256 and SHA-512. Its SHA-512 is the line in Mozilla's `SHA512SUMS`, whose signature is checked with the release key that [`verify_firefox_release.py`](../../scripts/upstream/verify_firefox_release.py) pins.

The table gives each side's median and the build's change against the baseline, with a 95 % bootstrap interval from 5 runs a side.

**A change whose interval holds 0 is not told apart from noise.** With the same engine on both sides, 5 runs give intervals of about ±3 to ±11 % for startup and ±9 % for memory (#361). Smaller changes need more runs.

All of it runs headless with software rendering. It is a regression signal for this project, not a measure of a person's hardware.

## When it runs

- **By hand**, before and after a change that may cost time or memory.
- **On every published release**, by [`perf.yml`](../../.github/workflows/perf.yml):
  - It compares the release with the published release before it and with Firefox, both checked against their `SHA256SUMS` signed with the release key ([`fetch_releases.py`](../../scripts/perf/fetch_releases.py)).
  - It runs 5 runs with Speedometer, on a GitHub-hosted runner, in the integration job's container, and fails a run whose web content processes are not in the full content sandbox.
  - It is report only. The table goes into the job summary and the JSON into a 90-day artifact per release, which is the history.

## Thresholds

Not written yet.

- For 1.0 the suite gates nothing by itself. The release criterion is that the 1.0 candidate's run against the release before it has no measure that gets worse with an interval that excludes 0, unless the reason is recorded ([release criteria](../product/release-criteria.md#scope-of-10-decided-2026-11-04)).
- Fixed thresholds come once `perf.yml` has kept enough releases to show the runner's own noise.

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
  - The decision is open in #364.
  - Until it is taken, NFR-02 ("comparable to the engine") is not met.

Two diagnoses, both Speedometer with 3 iterations:

| | score |
|---|---|
| Firefox 160.0 | 18.7 |
| Firefox 160.0 with Nulavio's preferences (`baseline.js`: ETP Strict, the fingerprinting overrides) | 18.6 |
| Nulavio 160.0-0.5 | 12.1 |
| Nulavio 160.0-0.5 with uBlock Origin turned off | 12.9 |
