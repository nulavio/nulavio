# Release criteria

## MVP definition of done — status on 2026-10-25

| # | Criterion | Status | Evidence / gap |
|---|---|---|---|
| 1 | Compiles in a supported environment | ✅ **Track B builds** from verified source in a Fedora 44 container (≈ 52 min); Track A needs no compilation | [build.md](../architecture/build.md) |
| 2 | Starts on Fedora KDE without disabling the sandbox | ✅ Track A (real Wayland window) and Track B build (headless) | `test_04`; ADR E3, E17 |
| 3 | Opens HTTP/HTTPS sites, tabs, downloads | ✅ | `test_05`, `test_06`, `test_07` |
| 4 | Authenticates via Proton Pass using the official extension | ✅ **Signed in to a real account and autofilled a real site** on the maintainer's desktop (Fedora 44 KDE Wayland, 2026-10-25); extension active, engine password manager off | `test_password_extensions` |
| 5 | KeePassXC integration demonstrated, or blocker recorded | ✅ **Demonstrated end to end** (association + autofill) in a Fedora 44 container with the distribution's KeePassXC 2.8.0, re-run in GitHub CI on every push. Manual desktop tests: community testers (the maintainer does not use KeePassXC) | [evidence](../research/evidence/keepassxc-2.8.0-native-messaging.json) |
| 6 | Blocks ads in a reproducible test | ✅ | `test_08` (EasyList first-party rule; control request; reversible) |
| 7 | Profile directory isolated and permission-protected | ✅ | `test_09`, registry hash check |
| 8 | Security documentation and out-of-scope threats | ✅ | [threat model](../security/threat-model.md), [residual risks](../security/residual-risks.md) |
| 9 | No improper use of Mozilla art or marks | ✅ for Nulavio assets (original). Track A displays Firefox's own UI as installed, with a non-affiliation notice. Track B must remove all marks | [LICENSES](../../LICENSES.md) |
| 10 | No known critical flaws introduced by the project | ✅ none known; Guard blocks weakened profiles | unit + integration suites |
| 11 | Test results and limitations recorded | ✅ | this file, ADR, residual risks |
| 12 | Original brand assets in the repository | ✅ | `docs/brand/assets/` |

## Alpha release gate (Track B)

1. All 12 MVP criteria ✅, built from verified source.
2. ✅ **Google Safe Browsing API key** provided at build time from a secret; `test_12` and `test_14` (lists downloaded, Google's test phishing page blocked) pass against the Nulavio build (2026-10-25). Still open: quota review with Google, and download protection (R15) either obtained from Google or explicitly accepted ([build](../architecture/build.md#google-safe-browsing-key)).
3. P0 providers certified (or explicitly documented as not supported, with cause): Proton Pass manually by the maintainer (its only provider); KeePassXC by the automated end-to-end test in CI, with manual desktop reports from community testers.
4. Update SLA process rehearsed once end-to-end.
5. Signed RPM in a signed repository; SBOM attached to the release.
6. Security policy contact live (✅ `security@nulavio.net`, `security.txt`, 2026-10-25); vulnerability intake tested (pending: a test report end to end).
7. Trademark/domain search completed. Domain `nulavio.net` registered (2026-10-25); INPI/USPTO/EUIPO searches still open ([status](../brand/strategy.md#trademark-and-availability-status)).
8. No critical Guard findings on a fresh install; integration suite green on CI.
