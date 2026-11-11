# Security changelog

What changed for security in each Nulavio build, in plain words. One entry per build that reaches users (packages); development milestones before the first package are grouped. Upstream fixes are Mozilla's: their advisories are linked, not copied.

Format of an entry:

- **Build**: Nulavio package version, the Firefox release inside it, date published.
- **Upstream**: Mozilla's release (date and time, UTC), its advisory, and the urgency with its reasons (urgent: 24-hour target; standard: 72 hours; the deadline is 72 hours either way, [update policy](../architecture/update-policy.md)).
- **Timing**: when the release was detected (staged or published), when the build was ready to sign, and when it was published, each in hours from Mozilla's release, against the target and the deadline.
- **Nulavio fixes**: weaknesses found in Nulavio's own code or configuration, with the commit and what a user should do, if anything.
- **New protections and their limits**: with the residual-risk entry that states what they do not do.

Template for an engine update (`scripts/release/bump_engine.py` prints the first lines):

```markdown
## Nulavio <package version> (Firefox <version>), published <date>

**Upstream**: Firefox <version>, released by Mozilla <date> <time> UTC ([mfsa<year>-<n>](https://www.mozilla.org/security/advisories/)).
Urgency: <urgent | standard> (<reasons>). Source SHA-256 <digest> (Mozilla's signed SHA256SUMS).

**Timing**

| Mozilla's release | Detected | Ready to sign | Published | Target | Deadline |
|---|---|---|---|---|---|
| <time UTC> | <staged or published>, <+/- h> | <+ h> | <+ h> | <24 or 72> h: <met or missed> | 72 h: <met or missed> |

**Nulavio fixes**: <none, or the table above>.
```

## Nulavio 160.0-0.2 (Firefox 160.0), published 2026-11-11

A security update of the alpha, with the same engine ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.2), [advisory GHSA-5mmp-gx3p-m7j8](https://github.com/nulavio/nulavio/security/advisories/GHSA-5mmp-gx3p-m7j8)). Prepared in the advisory's private fork and published together with the packages.

**Upstream**: unchanged, Firefox 160.0.

**Nulavio fixes** (security audit of 160.0-0.1, 2026-11-10; what a user does: `sudo dnf upgrade nulavio`):

| Severity | Area | Fix |
|---|---|---|
| High | Repository | `nulavio.repo`, which turns dnf's signature checks on, was uploaded to the package bucket; it is now `site/rpm/nulavio.repo`, served by the site from git (R1) |
| High | Vault | `vault.json.bak` kept removed or replaced unlock methods, which still opened the profile; the copy now holds the current file and a stale one is removed (V2) |
| High | AI Bridge | Address checks read hosts differently from the engine (backslash, encoded host, IPv4 shorthand) and missed redirects: the local network was reachable without `local_resources` (A1) |
| High | AI Bridge | The Shell's own pages (`moz-extension:`) needed only `local_resources`; they now need raw automation (A2) |
| Medium | Release | Every package was release 0.1, so a fix would not reach installed copies; the release now counts up and publishing refuses one that is not newer (R2) |
| Medium | Vault | A method change re-signed a tampered key file (V4); an interrupted encryption left the profile in the clear (V5); a crash left a locked profile's folder writable (V6) |
| Medium | AI Bridge | Typing could send a form without `submit_forms` (A3); an approval followed the tab to another site (A4); "Permitir" worked at once on a page that opened in front (A5); the agent-window lock rested on a pref (A6) |
| Low | Vault | Lock paths that failed open (V7); core dumps while keys were in memory (V8) |
| Low | AI Bridge | Activity lost earlier actions after a burst (A7); `tabs_list` ignored the site list (A8); scripts read cookies without `cookies_storage` (A9); the assistant followed redirects with its API key (A10); a new key left the old session open (A11); the agent bar took any text (A12); a reused PID kept a window marked (A13) |
| Low | Site | Manual verification imported the key without checking its fingerprint (R5) |

**Not fixed, residual risks**: repository metadata without expiry (R57), release-key rotation (R58), phone unlock bound to one desktop (R59; phone unlock is off).

## Nulavio 160.0-0.1 (Firefox 160.0), published 2026-11-10

The first public alpha, for Fedora ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.1), dnf repository at `packages.nulavio.net`, signed with `298A 9093 BAAB B26F 79BB  29F4 BF47 E5FA 9EDB 8DB1`).

**Upstream**: Firefox 160.0, released by Mozilla on 2026-11-10 ([advisories](https://www.mozilla.org/security/advisories/); [update issue #14](https://github.com/nulavio/nulavio/issues/14)). Urgency: urgent (no advisory yet when the build started, update policy). Source SHA-256 2b23d2bf6716ea16b45c10aa5c275c78a1d7ff50ad53150809ab27424c58fd81 (Mozilla's signed SHA256SUMS, verified against the pinned release key).

| Mozilla's release | Detected | Ready to sign | Published | Target | Deadline |
|---|---|---|---|---|---|
| 2026-11-10 (product-details gives the date only) | staged, 2026-11-09 23:35 UTC (upstream issue); pre-built from staging the same day | 2026-11-10 22:26 UTC (rehearsal: unit, 349 integration tests, RPM/DEB in clean containers, signed-repository check, 33 min) | 2026-11-10 22:59 UTC (repository uploaded and installed from in a clean Fedora 44 container; GitHub release) | 24 h: met (same day) | 72 h: met |

**Nulavio fixes**: engine pin and signed source digest moved from Firefox 159.0.1 to 160.0. Patch 0008 is gone: Firefox 160 animates the sidebar launcher with a view transition whose timing is CSS, so Horizon sets Nulavio's expand and collapse times there. Patches 0001–0007 apply unchanged. No change to what a user must do. The first signing with the real key also found that the signing container could not ask for a passphrase (#36, fixed before publishing), and that a patched tree could not be rebuilt (#34).

## Unreleased (development, Firefox 159.0.1)

**Upstream**: Firefox 159.0.1, released by Mozilla on 2026-11-03 14:09:02 UTC ([mfsa2026-123](https://www.mozilla.org/security/advisories/mfsa2026-123/), [update issue #4](https://github.com/nulavio/nulavio/issues/4)).
Urgency: urgent (impact high: CVE-2026-120572, incorrect boundary conditions in Layout: Block and Inline). Source SHA-256 b5fe407199685f8bddf3b2c81feb8b805429e6f3d307c9430f53456f85b6e063 (Mozilla's signed SHA256SUMS, verified against the pinned release key).

| Mozilla's release | Detected | Ready to sign | Published | Target | Deadline |
|---|---|---|---|---|---|
| 2026-11-03 14:09:02 UTC | published, by 20:39:45 UTC (+6.5 h; upstream issue) | blocked on 2026-11-04 (release `gkrust` with fat Rust LTO needs more memory than the 32 GiB laptop leaves above the 4 GiB reserve); the release build completed on 2026-11-09 23:42:10 UTC (+153.6 h) with thin Rust LTO | not published (no release key or host yet) | 2026-11-04 14:09:02 UTC (24 h): missed | 2026-11-06 14:09:02 UTC (72 h): missed. No package has been published yet, so no user ran an affected build |

**Nulavio fixes**: engine pin and signed source digest updated from Firefox 159.0 to 159.0.1. The initial release rehearsal failed during compilation (a `rustc` received SIGKILL). Resource containment was then added and checked with controlled cgroup, OOM, signal and disconnect probes. Both the two-job guarded build and its single permitted one-job retry were aborted by the host-memory reserve guard, without recorded OOM; the full rehearsal remains blocked ([evidence](../research/evidence/release-rehearsal-2026-11-04.md)). After freeing host memory and an opt-in 20 GiB budget, two more guarded attempts compiled every Rust crate except release `gkrust` (Rust LTO), which passed 17 GiB. A local build without Rust LTO (`--disable-release`, not a release configuration) completed on 2026-11-04 for the maintainer's own use; it is not signed, packaged or distributed. The rehearsal now passes its private install path to RPM/DEB packaging, with a regression test. On 2026-11-09 the release configuration moved to thin Rust LTO (`CARGO_RUSTCFLAGS=-Clto=thin`) and the guarded release build of 159.0.1 completed within the default 16 GiB budget (peak 13.0 GiB, [evidence](../research/evidence/release-rehearsal-2026-11-09.md)). Signing and publishing remain pending: there is no release key or repository host yet.

## Unreleased (development, Firefox 159.0)

No package has been published yet (the release key and repository host are pending), so no user has run an affected build.

**Upstream**: Firefox 159.0, released by Mozilla on 2026-10-27 12:57 UTC ([mfsa2026-118](https://www.mozilla.org/security/advisories/mfsa2026-118/)).
Urgency: urgent (impact high; a sandbox escape; no exploitation in the wild reported). Source SHA-256 3d98df785894057fce60603e845828e758a5411ad79aaaaff2b8230597f500d9 (Mozilla's signed SHA256SUMS). The development build moved to it on 2026-10-28 ([rehearsal](../research/evidence/release-rehearsal-2026-10-28.md)).

| Mozilla's release | Detected | Ready to sign | Published | Target | Deadline |
|---|---|---|---|---|---|
| 2026-10-27 12:57 UTC | published, by +2.4 h | +12.8 h | not yet (no release key or host) | 24 h: met for "ready to sign" | 72 h: open |

Earlier: Firefox 158.0.1, released by Mozilla on 2026-10-20; the development build moved to it on 2026-10-24.

**Nulavio fixes**

| Date | Weakness | Effect | Fixed in |
|---|---|---|---|
| 2026-10-26 | In the Nulavio build, the Strict tracking-protection category came only as a `distribution.ini` default, which the engine recomputes to Standard at start-up | Engine profiles of the build blocked tracking content and used fingerprinting protection only in private windows | `725d792` (S14): the Shell sets Strict once per profile as a user value; `test_privacy` checks every baseline pref of the build and a real blocked tracker |
| 2026-10-26 | An AI Workspace engine kept running when an agent killed its MCP bridge | Its automation endpoint stayed open on 127.0.0.1 until the user closed it (any process of the user could drive that workspace) | `46aced7`: engines start with a parent-death signal (`setpriv --pdeathsig`) |
| 2026-10-27 | The Companion formatted the 6-digit pairing code and JSON escapes with the phone's language | On a phone set to Persian, Arabic, Hindi or Thai the code would show in that script's digits, so the person could not compare it with the desktop's; the signed bytes were not affected (hexadecimal escapes are never localised) | `Locale.ROOT` in `Nv1.sasDigits` and `Json`, a test in four locales, and the Opengrep rule `nulavio-java-default-locale` |
| 2026-10-26 | The Shell's background page did not start with the browser after a profile's first run | AI permission requests did not appear in the browser on later runs (the fallback denied them), and the temporary-profile bar waited for an event | `725d792`: the page now starts with every run |
| 2026-11-09 | After a password was typed on the unlock page of a protected profile, the engine's password manager offered to save it ("Salvar senha de moz-extension://…?") | Accepting the offer copied that profile's password into the saved logins of the profile that was open, which may have no protection | [#15](https://github.com/nulavio/nulavio/pull/15): saving is off for the Shell's own pages, set at every start; `test_vault_ui` 02 types a password with real keys and checks that no tab offers to save it. No package had been published |
| 2026-11-10 | The Nulavio build's User-Agent ended in `Nulavio/<version>` instead of `Firefox/<version>` | Every site visited, and every request, could tell a Nulavio user from the far larger group of Firefox users, and saw the point release; sites that look for Firefox did not recognise the browser | Patch 0009: the User-Agent is Firefox's own, in pages and on the wire (`test_fingerprinting` 01). No package had been published |
| 2026-11-10 | The engine's font protection never applied on Fedora (its lists stop at release 39 and the release number is not read from Fedora's `os-release`), and its quick canvas mode leaves raw pixel reads unchanged | With tracking protection in Strict, every installed font and the plain canvas pixels were still readable by any page, while the docs named font limits among the protections | Patch 0010 and `privacy.fingerprintingProtection.overrides`; `test_fingerprinting` 03 and 05. The same defect is in Firefox on Fedora; to be reported to Mozilla |

**New protections and their limits**

| Date | Protection | Limit |
|---|---|---|
| 2026-11-10 | Fingerprinting: canvas, offscreen-canvas and WebGL reads differ per site; no graphics card model, toolbar size, window position, desktop colours or motion sensors for pages; installed fonts hidden on Fedora and Ubuntu | It reduces what a page reads and does not make people identical; a site can tell the build from a stock Firefox by these protections ([R56](residual-risks.md)) |
| 2026-10-27 | Engine security fast path: urgency from Mozilla's advisories (24-hour target for urgent releases, 72-hour deadline), an issue per release that @mentions the maintainer, verified engine bump, opt-in local timer that pre-builds staged releases | Signing and publishing wait for the maintainer; detection can lag about 14 hours with the timer off, more if Actions does not run ([R51](residual-risks.md), [R52](residual-risks.md)) |
| 2026-10-27 | Dependency watch (OSV.dev, the AMO blocklist, registries), Dependabot, Gradle locking and checksum verification, base images pinned by digest | Ten build-time advisories accepted until 2026-12-31; new Gradle artifacts trusted on first download ([R53](residual-risks.md)) |
| 2026-10-27 | Code scanning in CI: secrets (gitleaks), Nulavio's own Opengrep rules, ShellCheck, workflow audits (zizmor, actionlint); advisory AI review of pull requests | Findings arrive after the push; no CodeQL; the AI review is advisory and off until a credential is added ([R54](residual-risks.md)) |
| 2026-10-26 | Guard at run time: changes made to a profile outside the browser (extensions, protective settings, certificate authorities, security modules, native-messaging hosts, policies, `user.js`, search) | Detection, not prevention; Nulavio-aware malware can edit the record ([R38](residual-risks.md)) |
| 2026-10-26 | Look-alike login warning (flow D) | Compares only with logins kept by the browser's own manager ([R41](residual-risks.md)) |
| 2026-10-26 | Temporary profile, deleted on close | Downloads, other apps' data and swap outlive it ([R37](residual-risks.md)) |
| 2026-10-26 | Explicit DNS choice | The chosen resolver sees lookups ([R40](residual-risks.md)) |
| 2026-10-26 | One engine build reads the distribution's system Mozilla directory on Fedora and Ubuntu (patch 0006) | — ([R25](residual-risks.md), resolved) |
| 2026-10-26 | Encrypted profiles at rest (Vault, gocryptfs), AI Bridge permissions, stop and audit | [R30](residual-risks.md)–[R36](residual-risks.md) |
