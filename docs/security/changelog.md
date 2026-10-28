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

**New protections and their limits**

| Date | Protection | Limit |
|---|---|---|
| 2026-10-27 | Engine security fast path: urgency from Mozilla's advisories (24-hour target for urgent releases, 72-hour deadline), an issue per release that @mentions the maintainer, verified engine bump, opt-in local timer that pre-builds staged releases | Signing and publishing wait for the maintainer; detection can lag about 14 hours with the timer off, more if Actions does not run ([R51](residual-risks.md), [R52](residual-risks.md)) |
| 2026-10-27 | Dependency watch (OSV.dev, the AMO blocklist, registries), Dependabot, Gradle locking and checksum verification, base images pinned by digest | Ten build-time advisories accepted until 2026-12-31; new Gradle artifacts trusted on first download ([R53](residual-risks.md)) |
| 2026-10-27 | Code scanning in CI: secrets (gitleaks), Nulavio's own Opengrep rules, ShellCheck, workflow audits (zizmor, actionlint); advisory AI review of pull requests | Findings arrive after the push; no CodeQL; the AI review is advisory and off until a credential is added ([R54](residual-risks.md)) |
| 2026-10-26 | Guard at run time: changes made to a profile outside the browser (extensions, protective settings, certificate authorities, security modules, native-messaging hosts, policies, `user.js`, search) | Detection, not prevention; Nulavio-aware malware can edit the record ([R38](residual-risks.md)) |
| 2026-10-26 | Look-alike login warning (flow D) | Compares only with logins kept by the browser's own manager ([R41](residual-risks.md)) |
| 2026-10-26 | Temporary profile, deleted on close | Downloads, other apps' data and swap outlive it ([R37](residual-risks.md)) |
| 2026-10-26 | Explicit DNS choice | The chosen resolver sees lookups ([R40](residual-risks.md)) |
| 2026-10-26 | One engine build reads the distribution's system Mozilla directory on Fedora and Ubuntu (patch 0006) | — ([R25](residual-risks.md), resolved) |
| 2026-10-26 | Encrypted profiles at rest (Vault, gocryptfs), AI Bridge permissions, stop and audit | [R30](residual-risks.md)–[R36](residual-risks.md) |
