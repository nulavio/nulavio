# Release build: Firefox 159.0.1 with thin Rust LTO, guarded, 2026-11-09

Result: **the release build completed inside the default budget** (16 GiB, two CPUs), where four attempts on 2026-11-04 stopped on memory ([evidence](release-rehearsal-2026-11-04.md)). The only change is the Rust link-time optimisation mode: thin, set in `browser/build/mozconfig`. Nothing was signed or published.

## What was built

- Source: Firefox 159.0.1, SHA-256 `b5fe407199685f8bddf3b2c81feb8b805429e6f3d307c9430f53456f85b6e063` (Mozilla's signed SHA256SUMS), patches 0001–0008.
- Repository: `main` at `c36d254` plus the mozconfig line of this change (branch `agent/claude/build-rust-thin-lto`).
- Configuration: `--enable-release`, as before, with `mk_add_options "export CARGO_RUSTCFLAGS=-Clto=thin"`. The engine's build system appends that value after its own `-Clto`, and `rustc` keeps the last one.
- Build tree and tools: `/home/caiobarbieri/.cache/nulavio-release-159.0.1/` (the tree of the 2026-11-04 attempts, so the Rust dependencies were already compiled; the previous build there was the local `--disable-release` one).
- Limits read back by both containers: `memory.max=17179869184`, `memory.swap.max=0`, `memory.oom.group=1`, `cpu.max=200000 100000`, `pids.max=512`; host reserve 4 GiB, PSI limit 10 % for 30 s.

## First attempt: the option did not reach Cargo

Guard window 21:35:08 to 21:57:03 UTC (`logs/guard-20261109T183508-1058663/`). The mozconfig line was `mk_add_options CARGO_RUSTCFLAGS=-Clto=thin`, without `export`. Only `export` lines of a mozconfig are written to `.mozconfig.mk`, which the makefiles that run Cargo include, so `rustc` for `gkrust` was started with `-Clto` alone (read from `/proc/<pid>/cmdline`) and ran the fat pass again. The container reached its 16.00 GiB `memory.max` (2893 `max` events, no OOM) with one `rustc` at 12.7 GiB.

The build was stopped by hand (SIGTERM to the supervisor) before the memory guard had to: `result.json` records exit 75, `signal 15`, `oom: false`, `memory_failure: false`, so the next attempt kept two jobs. `tests/unit/test_track_b.py` now checks that the line has `export`.

## Second attempt: completed

Guard window 21:57:44 to 23:42:10 UTC (`logs/guard-20261109T185744-1120894/`), 1254 samples.

| | |
|---|---|
| `gkrust` | started 20 s in with `-Clto -Clto=thin`; `Finished release profile [optimized] target(s) in 12m 04s` |
| Whole build | 102 min 31 s of build time (mach: wall time 6151 s, CPU 18 % of 16 processors), then packaging |
| Container memory | peak **13.03 GiB**, no `max` event, no OOM |
| Host | never below 14.97 GiB available; PSI `full avg10` at most 1.06 % |
| Result | `{"exit_code": 0, "reason": null, "oom": false, "jobs": 2, "memory_failure": false}` |
| Package | `nulavio-159.0.1.en-US.linux-x86_64.tar.xz`, 81.8 MiB, SHA-256 `5e488dc402ac4a011c897abca59a83408aaa1b581b86913fd68d04a8143d6d14`; `application.ini`: `Vendor=Nulavio`, `Version=159.0.1`, `BuildID=20261109234006` |

For comparison, the fat pass on 2026-11-04 was at 17.36 GiB and still growing by about 1 GiB a minute when the host reserve stopped it.

SHA-256 of the guard records, second attempt: `build.log` `02cf97ae332ac5a37c1f220d4744eaa55a811c5d6c4f8e7e4f13bbca9ae652d4`, `telemetry.jsonl` `a43a21686ce04ec73c3f9f21173c682bccc5aa89f6e51b735c458fce82fa90dd`, `result.json` `4329f64de0471b5d9011352b2bdac6037d13d93b2cfefce22c72f3e6b01b997d`. First attempt: `build.log` `c690ad6418f782973cdd9f0109371eb29b420f7c4b0014252a103e17848d9e31`, `telemetry.jsonl` `f2a2c9f9413b58dafb02def16077cfa17f299134aea3f64526d07eb55ce64ede`, `result.json` `a55813005d67090bd9fd2030573104f073a95f3862af80da57b5dffd617cd91d`.

## Tests on the package

- **Integration suite on the real build:** 356 tests, 338 OK, 18 skipped, none failed. Run one module at a time against this package with the Shell of pull request #15 copied in by `scripts/build/dev_sync.py` (that branch changes the Vault's pages and three tests, nothing in the engine). The skips are opt-in (network, a phone on adb, real agents, Podman probes, a visible window, a reference build).
- **Packaging, from this package:** the steps of `rehearse_release.sh` after the tests, each in a clean container:

  | Step | Time | Result |
  |---|---|---|
  | RPM (`make_rpm.sh`) | 2 min 50 s | `nulavio-159.0.1-0.1.fc44.x86_64.rpm`, 87.3 MiB, SHA-256 `63da8b3385d4b018cc29152d46b04bc99e54d2bb1280aee22f6a7cc15466b9bc` |
  | `check_rpm.sh` (Fedora 44) | 35 s | installs, starts headless and renders a page, reads `/usr/lib64/mozilla`, the tools answer, desktop entry and icons present |
  | DEB (`make_deb.sh`) | 1 min 26 s | `nulavio_159.0.1-0.1_amd64.deb`, 81.9 MiB, SHA-256 `abaefee785d277fc30d1ba321c9af2d8be4467dfe3bdee33a0788e8bfd6b463d` |
  | `check_deb.sh` (Ubuntu) | 52 s | installs, the AppArmor profile parses, reads `/usr/lib/mozilla`, the tools answer |
  | `test_signed_repo.sh` (throwaway key) | 53 s | installed with verified signatures; an unsigned package and tampered metadata are refused |
  | SBOM (`sbom.py`) | under 1 s | one CycloneDX file per package |

## Not done

- `scripts/release/rehearse_release.sh` as one run. The engine tree was already building the next change, so its steps were run separately: the build above, the integration suite, and the packaging steps on the same package.
- A measurement of what thin LTO costs in speed against a fat pass. No fat release build exists on this machine to compare with.
- Signing and publishing: there is no release key or repository host yet.
