# perf.yml on GitHub's runner, four runs (2026-11-16 to 2026-11-18)

The JSON each run of [`perf.yml`](../../../../.github/workflows/perf.yml) uploaded, copied here because the artifacts expire after 90 days. They are what the thresholds in [performance.md](../../../architecture/performance.md#thresholds) come from (#367).

| File | Run | What it compares |
|---|---|---|
| `43908609249-perf-v160.0-0.6.json` | [43908609249](https://github.com/nulavio/nulavio/actions/runs/43908609249), on the release | 160.0-0.6 against 0.5, and Firefox |
| `44220905151-perf-v160.0-0.6.json` | [44220905151](https://github.com/nulavio/nulavio/actions/runs/44220905151), by hand | the same, again |
| `44226178496-perf-v160.0-0.5.json` | [44226178496](https://github.com/nulavio/nulavio/actions/runs/44226178496), by hand | 0.5 against 0.4 |
| `44220927367-perf-v160.0-0.4.json` | [44220927367](https://github.com/nulavio/nulavio/actions/runs/44220927367), by hand | 0.4 against 0.3 |

Each holds five runs a side of the first and second start, memory with 1 and 10 tabs, and Speedometer 3, with their 95 % bootstrap intervals (`scripts/perf/run.py`). `python3 -I scripts/perf/gate.py <file>` gives the gate's verdict on each; all four pass.
