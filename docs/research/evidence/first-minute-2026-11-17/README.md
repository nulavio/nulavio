# A new profile's first minute, 2026-11-17 (#362)

- `samples.json`: a new profile's first three starts, read every few seconds for 60 s after each. It holds the PSS in MiB of the whole instance and of the extension process (the engine's process type "extension"), from `/proc/<pid>/smaps_rollup` and `ChromeUtils.requestProcInfo()`.
- `run.json`: one run of `scripts/perf/run.py --first-minute`, the build against itself.

The `about:memory` dump taken at the first start's peak is not kept here, because it holds local paths. What it showed is summarised in [performance](../../../architecture/performance.md#a-new-profiles-first-minute-2026-11-17).
