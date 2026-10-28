# Release rehearsal: Firefox 159.0

The first urgent Firefox release since the engine security fast path was written. It was handled by hand while that work was being integrated: the rehearsal ran from `main` (commit `e2ca9e2`), before the fast-path scripts (watcher v2, autobuild, timer, manifest) were merged, so it shows what the build and release steps take, not the detectors. Mozilla rated it urgent under the [update policy](../../architecture/update-policy.md): [mfsa2026-118](https://www.mozilla.org/security/advisories/mfsa2026-118/), impact high, with a sandbox escape; no exploitation in the wild reported. Target 24 hours, deadline 72 hours.

| Time (UTC) | Hours after Mozilla's release | What happened |
|---|---|---|
| 2026-10-27 12:57 | 0 | Mozilla publishes Firefox 159.0 (product-details commit time) |
| 2026-10-27 15:21 | +2.4 | Source tarball fetched; Mozilla's signed `SHA256SUMS` verified (digest `3d98df78…f500d9`) |
| 2026-10-27 15:21–15:36 | | First build, cut short when the machine restarted |
| 2026-10-27 20:21–21:08 | +8.2 | Full build: 47 minutes |
| 2026-10-28, before 01:30 | | First rehearsal: the integration tests found that Firefox 159 removed `--remote-allow-system-access`; the test harness now sets `MOZ_REMOTE_ALLOW_SYSTEM_ACCESS` in the throwaway test profiles only (commit `e2ca9e2`). The launcher still strips every `MOZ_REMOTE_*` variable |
| 2026-10-28 01:46 | +12.8 | Rehearsal below: every step passed; packages ready to sign |

Signing and publishing were not done: they need the maintainer's release key and repository host. The rehearsal ran from the main branch before the fast-path scripts were merged, so it has no `manifest.json` step.

Started 2026-10-28T01:30:12Z.

| Step | Time | Result |
|---|---|---|
| verify-source | 0 min 00 s | ok |
| build | 1 min 10 s | ok |
| install | 0 min 02 s | ok |
| unit-tests | 1 min 00 s | ok |
| integration-tests | 9 min 03 s | ok |
| rpm | 2 min 19 s | ok |
| check-rpm | 0 min 29 s | ok |
| deb | 1 min 06 s | ok |
| check-deb | 0 min 41 s | ok |
| signed-repository | 0 min 46 s | ok |
| sbom | 0 min 00 s | ok |

Total: 0 h 16 min (the build step reused the compiled tree). Not rehearsed: signing with the release key and publishing.
