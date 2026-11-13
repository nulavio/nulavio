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
7. Brand domain and identity setup (`nulavio.net` registered 2026-10-25; [brand guidelines](../brand/guidelines.md)).
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
| 7 | Trademark and domain | ✅ `nulavio.net` registered | Handled privately outside the repository (**maintainer or counsel**) |
| 8 | Fresh install, CI | ✅ A fresh profile has no Guard finding above "info" on either track (the Nulavio build from the developer cache warns that its binary is user-writable; installed packages are root-owned, checked by `check_rpm`/`check_deb`); CI green at `39aa3ba` | — |
| — | Found in S23: Ubuntu host | ✅ 2026-11-13, on the maintainer's Ubuntu 26.04.1 KDE machine with the restriction on: the profile gives the content processes their own user namespaces, and without it they get none ([spikes](../security/phase5-spikes.md#apparmor-on-ubuntu)) | — |

**Result:** the alpha is **not released yet**. Everything that can be done without the maintainer is done and verified; the release waits on the items marked **maintainer** above (release key and repository host, Safe Browsing quota and download protection decision, test security report, Proton Pass once on the Nulavio build). Slices outside the alpha that also wait: S10 (a FIDO2 security key) and S11 (Android, last by decision; the test phone).


## Public alpha (decided 2026-11-04)

**Published on 2026-11-10: [v160.0-0.1](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.1)** (Firefox 160.0, Fedora, signed dnf repository at `packages.nulavio.net`). Security update [v160.0-0.2](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.2) on 2026-11-11 ([advisory GHSA-5mmp-gx3p-m7j8](https://github.com/nulavio/nulavio/security/advisories/GHSA-5mmp-gx3p-m7j8)). [v160.0-0.3](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.3) on 2026-11-11, the first from the release workflow (built on Blacksmith, signed through KMS after approval).

The maintainer's decisions [D8–D11](execution-plan.md#decisions-for-the-public-release-maintainer-2026-11-04): a public alpha first, Fedora only through the signed dnf repository; R15 accepted; phone and FIDO2 unlock out of 1.0; the independent audit limited to the Vault and the release chain.

What is in place for it (2026-11-04): `publish_release.sh` signs only what a rehearsal of reviewed, committed history checked and stages the repository and the GitHub release assets; `make_release_key.sh` creates the key and puts only its public part in the repository; the site's download pages (`/baixar/`, `/en/download/`) appear only once `packaging/release.json` names a version and a key the repository holds ([build](../architecture/build.md#publishing-a-release)).

| # | Still open | Owner |
|---|---|---|
| 1 | ✅ **Done 2026-11-10.** Thin Rust LTO (#17) fits the release build in the guarded budget: Firefox 160.0 built from scratch in 2 h 21 min, container peak 13.0 GiB of 16, and passed the 363-test integration suite (#19) | — |
| 2 | ✅ **Done 2026-11-10.** Key created with `make_release_key.sh` (RSA 4096, signing only, expires 2028-11-09, fingerprint `298A 9093 BAAB B26F 79BB  29F4 BF47 E5FA 9EDB 8DB1`); public key and fingerprint committed (#27); passphrase in the maintainer's password manager. Still open: the offline backups of the private key and of the revocation certificate, kept apart | maintainer (backups) |
| 3 | ✅ **Done 2026-11-10.** Cloudflare R2 bucket `nulavio-packages` served at `packages.nulavio.net` (TLS 1.2 minimum). Still open: an R2 API token limited to that bucket, for the upload step of `publish/NEXT.md` | maintainer (token) |
| 4 | ✅ **Decided 2026-11-10: the default quota is accepted for the alpha.** The `nulavio` project has 10,000 requests a day for each Safe Browsing API (Update, Lookup, Submission, other) and 1,800 a minute; at about 48 list updates a day per browser, that is room for roughly 200 daily active installs. Review it with Google (a quota increase may need a billing account) when "Update API requests per day" passes 70 % | maintainer (watch the quota) |
| 5 | ✅ **Done 2026-11-10.** A test report sent from an outside address to `security@nulavio.net` arrived (Cloudflare Email Routing forwards it to the maintainer) and was answered. Replies come from the maintainer's own address: the routing only receives | — |
| 6 | ✅ **Done 2026-11-10.** Brand and domain setup (`nulavio.net`) checked; formal trademark filings are handled privately by the maintainer | maintainer |
| 7 | ✅ **Done 2026-11-10.** On the Nulavio build of Firefox 160.0: the provider chooser installed the pinned Proton Pass from addons.mozilla.org, sign-in worked and a saved login was offered and filled | — |
| 8 | ✅ **Decided 2026-11-10 by the maintainer: keep Firefox's add-on application ID and install from addons.mozilla.org**, as other Gecko-based browsers do (LibreWolf, Waterfox); a separate ID would make AMO's extensions, uBlock Origin and Proton Pass included, incompatible. This is a product decision on that prior art, not a legal opinion: no counsel has reviewed it ([ADR 0001](../adr/0001-engine-selection.md#open-items)) | — |
| 9 | With the release: the landing page's status ("Em desenvolvimento", "repositório ainda privado") and the README's status change in the same commit that sets the version; once the repository is public, the evidence references can become links (site spec §2.2) | with the release |

## Scope of 1.0 (decided 2026-11-04)

1.0 is the public alpha's scope made stable: every phase's DoD except FIDO2 unlock (S10), which the UI and the site show as not available yet (phone unlock, U6/U7 and S11, came back in on 2026-11-10 after its device test on a real phone, with the Companion on F-Droid); an independent review of the Vault and of the release chain with its findings fixed or recorded; at least one month of alpha releases inside the update SLA; the remaining Proton Pass checklist (unlock after restart, autosave, passkeys); and the UX DoD (both themes, every preset, WCAG 2.2 AA checks).
