# Release rehearsal: Firefox 159.0.1, guarded local attempts

Result: **BLOCKED by host memory headroom, not ready to sign.** Both guarded
attempts stopped when host `MemAvailable` fell below the 4 GiB reserve. The
guard recorded exit 75 and `memory_failure: true`, with `oom: false`. Neither
attempt completed compilation. No fresh engine integration, packages, signed
repository test, SBOMs or release manifest were produced by these attempts.
No release signing, publication, merge or approval was performed.

## Source and checked implementation

- Checkout: `release/firefox-159.0.1`, initially
  `cbb438299092ee72ce183615ba95a06c09f505e7`.
- The one-job attempt started with that commit plus the private-install-path
  fix and its test, committed during compilation as
  `f0ab0028e1bceadcbc20229a632d7095ed9b38bc`. The live mounted build scripts
  were not edited. Later changelog/evidence changes do not imply a new build.
- Both `verify-source` steps passed for Firefox 159.0.1. The retained source
  marker and engine pin agree with Mozilla's verified source SHA-256:
  `b5fe407199685f8bddf3b2c81feb8b805429e6f3d307c9430f53456f85b6e063`.
- Mozilla signing subkey: `827E658608679618CD349F93678E455D76767AA3`.
- Source, object files and toolchains remain under
  `/home/caiobarbieri/.cache/nulavio-release-159.0.1/`.

## Enforced limits and stops

Both containers read back `memory.max=17179869184`, `memory.swap.max=0`,
`memory.oom.group=1`, `cpu.max=200000 100000` and `pids.max=512` before building.
The host policy remained reserve 4 GiB and PSI `full avg10 > 10%` continuously
for 30 seconds. Container swap zero does not mean host swap was empty; host
swap was already largely occupied, and host settings were not changed.

The first guard ran from 00:01:47 UTC on 2026-11-04; its result was written at
00:07:11 UTC. It used Make `-j2`, Cargo `--jobs=1`, and observed at most one
`rustc`. Exact reason: `available memory below reserve (3.02 GiB)`. Its 65
telemetry samples recorded minimum host availability 3.0234 GiB, peak container
memory 11.1800 GiB and maximum PSI full avg10 1.81%. Thus the reserve, rather
than PSI or OOM, triggered the stop.

Only the owning rehearsal shell was paused before downstream packaging after
inspection found a missing private-install-path handoff. The guard continued
unchanged. Once it stopped its container, that paused shell was terminated
(exit 143). The manually annotated first rehearsal report identifies this;
the guard's exit 75 is the workload classification.

After 12 headroom samples spanning 55 seconds (minimum 13.8605 GiB available,
maximum PSI zero), the single permitted changed attempt used Make `-j1`.
The existing `last-result.json` was preserved. Cargo's observed command had
one `-j1`, with at most one `rustc`; there was no concurrent C++ compiler in
the final sample. The guard ran from 00:10:41 UTC; its result was written at
00:15:48 UTC. Exact reason: `available memory below reserve (3.43 GiB)`.
Its 62 samples recorded minimum availability 3.4335 GiB, peak container memory
10.3708 GiB and maximum PSI full avg10 1.88%. The rehearsal's build step was
reported failed after 5 min 12 s; its actual cause was the guard abort.

Both inner stop records say `signal 15`, `oom: false`, consistent with the
supervisor requesting shutdown. No compiler failure or supervisor disconnect
was established by these records. Both identified containers were removed;
`podman ps` was empty afterwards. The final retry state has `jobs: 1` and
`memory_failure: true`; a no-launch policy check refuses another attempt with
`previous memory failure at one job; inspect logs before another attempt`.
There was no further retry or budget increase.

## Retained artifacts

Paths below are relative to the named checkout or private build cache.

- Checkout: `dist/rehearsal-159.0.1-guarded/`, including `retry-headroom.json`
  and `logs/unit-after-install-path-fix.log`.
- Checkout: `dist/rehearsal-159.0.1-guarded-onejob/`, including `console.log`,
  `rehearsal.md`, `logs/verify-source.log` and `logs/build.log`.
- Cache: `logs/guard-20261103T210147-656883/`, container
  `0336a28a0bbb281e5d1213978edff07963bdaa75fff7a39cdc04af3fbf81dc8c`.
- Cache: `logs/guard-20261103T211041-684887/`, container
  `a5a86fec2505e1b2436995dd2d2dba3e62cab20aca30caebb295eb54cb33665e`.

Each guard directory retains `build.log`, `telemetry.jsonl`, `limits.json`,
`result.json` and `inside-stop.json`. SHA-256 custody values, first attempt:

```text
5b23e08ec96c707f66338799a948aebd0dfbd2c9721b1776c3884b77d1f275bf  build.log
4a53b005ea8b976397412a9fa50d91bde030b3834102e690e81ae49e8d405813  telemetry.jsonl
c3286af5ebb450b31a1455a585cf75c4a12bb8158d18caea26b27a327470f275  limits.json
76fc6ab90c3a7a6bcb437e3719082dd59057d2d46519555455e87247094bd153  result.json
```

Second attempt:

```text
4aed7410b34bee72ca8803eb0f5fb75f74ffe4af986a612543f68016205a29a5  build.log
7b155279007cda2c4d94260d8b608286d24fc496a3c787767b770894026924bb  telemetry.jsonl
9ff3b9cbb97ea493a5276e5fa5fad8921604ac300dcb7fef8492861d6eb2a525  limits.json
b2fa0ea890e489621b755b891a95b9844467c27d9699e3698dbff17e98f81cbb  result.json
```

## Third attempt after freeing host memory

Stale `/tmp` directories (tmpfs, partly held in a full zram swap) that no
process had open were removed at the maintainer's request; host
`MemAvailable` rose from about 15 to about 19 GiB. The previous one-job
`last-result.json` was kept as `logs/last-result.onejob-20261104T001548.json`
and the rehearsal was rerun with Make `-j1`, Cargo `--jobs=1` and the same
16 GiB container budget and 4 GiB host reserve (out dir
`dist/rehearsal-159.0.1-guarded-after-cleanup/`, guard log
`logs/guard-20261104T085253-1276634/` in the private cache).

`verify-source` passed again. The build now got past `firefox-on-glean`
(single `rustc` at about 9.7 GiB RSS), `webrender`, `style` and the rest of the
Rust graph, and stopped in the final `gkrust` crate after 12 min 33 s of Make
time. Guard window 11:52:53 to 12:14:09 UTC, 256 samples. Exact reason:
`available memory below reserve (3.94 GiB)`, `oom: false`, exit 75. Container
`memory.current` reached its 16.00 GiB `memory.max` (17 `max` events) as host
availability crossed the reserve, so `gkrust` with release Rust LTO
(`RUST_LTO_ELIGIBLE=1`) needs more than this budget leaves on this host. The
container was removed. SHA-256: `build.log`
`84d2204578db43a0eb2e6cc80672a9974eb88dbd9b5d2055b6e034affd941710`,
`telemetry.jsonl`
`9f3581bda9ba7de7290a2230fb150aef99be75d7924e74291eccc80dfb0f4a5b`,
`result.json`
`d714609fbbaa952b671ec7e288b1420793407298174f06ac0e85ab3b5e9f60ce`.

The compiled Rust dependencies stay in the objdir, so a later attempt resumes
at `gkrust`. Finishing needs either more memory than the 16 GiB budget (larger
host or runner) or a reviewed change to the release Rust LTO setting; neither
was made here.

## Verification and remaining gates

The install-path regression test failed before the fix: a stub packager
received an unrelated install path. After exporting the rehearsal's own
`NULAVIO_INSTALL_DIR`, it passed for RPM and DEB handoffs without accessing
the default cache or invoking a real packager.

`python3 -B -I tests/run.py unit`: **609 tests, OK, 3 skipped**, 66.940 s.
`ruff check .`, `ruff format --check .` (218 Python files), ShellCheck on
`rehearse_release.sh`, `bash -n` and `git diff --check`: PASS. These verify the
path fix and repository checks; they do not certify the unbuilt engine.

All downstream release gates remain **UNRUN** for these guarded attempts:
install, full engine integration, RPM/DEB generation and clean-container checks,
throwaway-key repository checks, SBOMs and manifest. The earlier controlled
cgroup probes remain separate evidence, not a completed release rehearsal.
Remote CI and human review are separate from these local results. PR #5 stays
draft. Further build work requires a diagnosed host/runner headroom solution
under the unchanged resource budget; no ready time is claimed.
