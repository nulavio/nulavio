# Security changelog

What changed for security in each Nulavio build, in plain words. One entry per build that reaches users (packages); development milestones before the first package are grouped. Upstream fixes are Mozilla's: their advisories are linked, not copied.

Format of an entry:

- **Build**: Nulavio package version, the Firefox release inside it, date published.
- **Upstream**: Mozilla's release date, its advisory, and the time from Mozilla's release to the Nulavio build (target: 72 hours, [update policy](../architecture/update-policy.md)).
- **Nulavio fixes**: weaknesses found in Nulavio's own code or configuration, with the commit and what a user should do, if anything.
- **New protections and their limits**: with the residual-risk entry that states what they do not do.

## Unreleased (development, Firefox 158.0.1)

No package has been published yet (the release key and repository host are pending), so no user has run an affected build.

**Upstream**: Firefox 158.0.1, released by Mozilla on 2026-10-20 ([advisories](https://www.mozilla.org/security/advisories/)). The development build moved to it on 2026-10-24.

**Nulavio fixes**

| Date | Weakness | Effect | Fixed in |
|---|---|---|---|
| 2026-10-26 | In the Nulavio build, the Strict tracking-protection category came only as a `distribution.ini` default, which the engine recomputes to Standard at start-up | Engine profiles of the build blocked tracking content and used fingerprinting protection only in private windows | `725d792` (S14): the Shell sets Strict once per profile as a user value; `test_privacy` checks every baseline pref of the build and a real blocked tracker |
| 2026-10-26 | An AI Workspace engine kept running when an agent killed its MCP bridge | Its automation endpoint stayed open on 127.0.0.1 until the user closed it (any process of the user could drive that workspace) | `46aced7`: engines start with a parent-death signal (`setpriv --pdeathsig`) |
| 2026-10-26 | The Shell's background page did not start with the browser after a profile's first run | AI permission requests did not appear in the browser on later runs (the fallback denied them), and the temporary-profile bar waited for an event | `725d792`: the page now starts with every run |

**New protections and their limits**

| Date | Protection | Limit |
|---|---|---|
| 2026-10-26 | Guard at run time: changes made to a profile outside the browser (extensions, protective settings, certificate authorities, security modules, native-messaging hosts, policies, `user.js`, search) | Detection, not prevention; Nulavio-aware malware can edit the record ([R38](residual-risks.md)) |
| 2026-10-26 | Look-alike login warning (flow D) | Compares only with logins kept by the browser's own manager ([R41](residual-risks.md)) |
| 2026-10-26 | Temporary profile, deleted on close | Downloads, other apps' data and swap outlive it ([R37](residual-risks.md)) |
| 2026-10-26 | Explicit DNS choice | The chosen resolver sees lookups ([R40](residual-risks.md)) |
| 2026-10-26 | One engine build reads the distribution's system Mozilla directory on Fedora and Ubuntu (patch 0006) | — ([R25](residual-risks.md), resolved) |
| 2026-10-26 | Encrypted profiles at rest (Vault, gocryptfs), AI Bridge permissions, stop and audit | [R30](residual-risks.md)–[R36](residual-risks.md) |
