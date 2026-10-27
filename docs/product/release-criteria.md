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

## Alpha gate walk-through — 2026-10-27 (S24)

Each item was checked again on 2026-10-27 against the Nulavio build of Firefox 158.0.1 and distribution Firefox 158.0.1 on Fedora 44 KDE, at commits `39aa3ba` (S22) and `6c2875f` (S23).

| # | Item | Verified | Still open (owner) |
|---|---|---|---|
| 1 | 12 MVP criteria, built from verified source | ✅ The release rehearsal checked Mozilla's signed checksums and built from that source ([report](../research/evidence/release-rehearsal-2026-10-27.md)); Track B suites: unit 320, integration 159 (8 opt-in skips, run separately below; three failures in one run were a test sampling a starting process and a timing race under extra load, fixed and re-run green); brand and identity of the build (`test_engine_slice` 13, 15) | — |
| 2 | Google Safe Browsing | ✅ The build carries its own key (`test_engine_slice` 12) and, against Google's live service, downloads the lists and replaces Google's official test phishing page with the warning (`test_engine_slice` 14, run again 2026-10-27) | Quota review with Google; download protection (R15): request partner access or accept it in writing (**maintainer**) |
| 3 | P0 password providers | ✅ Proton Pass: real account on the maintainer's desktop (Track A, 2026-10-25); on the Nulavio build, the official extension from addons.mozilla.org loads, and the provider chooser installs the pinned version (`test_password_extensions`, `test_passwords` 05, 2026-10-27); KeePassXC: end to end in CI on every push | Proton Pass sign-in and autofill once on the Nulavio build on the maintainer's desktop (**maintainer**); KeePassXC on a real desktop and Bitwarden (**community testers**) |
| 4 | Update SLA rehearsed end to end | ✅ 14 minutes for an incremental build, every step passed; about 70 minutes expected with a full build, against 72 hours ([update policy](../architecture/update-policy.md)) | The rehearsal's last two steps: signing with the release key and publishing (**maintainer**: key and host) |
| 5 | Signed RPM in a signed repository; SBOM | ✅ Packages build and pass clean-container checks on Fedora 44 and Ubuntu 26.10 (S18; the .deb again in S23 with its AppArmor profile); signed repository installs with both checks on and refuses altered metadata (throwaway key); CycloneDX SBOM per package | The release key, where its public part is published, and the repository host (`packages.nulavio.net` is a placeholder) (**maintainer**) |
| 6 | Security contact and intake | ✅ `security@nulavio.net` and `security.txt` live (2026-10-25); security changelog started ([changelog](../security/changelog.md)) | Send one test report to `security@nulavio.net` and confirm it arrives and is answered (**maintainer**; Nulavio sends no mail on anyone's behalf) |
| 7 | Trademark and domain | ✅ `nulavio.net` registered | INPI, USPTO and EUIPO searches (**maintainer or counsel**) |
| 8 | Fresh install, CI | ✅ A fresh profile has no Guard finding above "info" on either track (the Nulavio build from the developer cache warns that its binary is user-writable; installed packages are root-owned, checked by `check_rpm`/`check_deb`); CI green at `39aa3ba` | — |
| — | Found in S23: Ubuntu host | The `.deb` AppArmor profile parses in a clean Ubuntu container | On a real Ubuntu 26.04 host: install the `.deb`, open `about:support` and check that user namespaces are available ([R46](../security/residual-risks.md)) (**maintainer or a community tester**) |

**Result:** the alpha is **not released yet**. Everything that can be done without the maintainer is done and verified; the release waits on the items marked **maintainer** above (release key and repository host, Safe Browsing quota and download protection decision, test security report, trademark searches, Proton Pass once on the Nulavio build). Slices outside the alpha that also wait: S10 (a FIDO2 security key) and S11 (Android, last by decision; the test phone).

