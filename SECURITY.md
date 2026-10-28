# Security policy

## Supported versions

Nulavio has **no releases yet**. The `main` branch (Track A preview) is the only supported code. Once releases exist, the latest release and the previous one will receive security fixes.

## Reporting a vulnerability

- **Do not open a public issue.**
- Preferred channel once the repository is public: **GitHub private vulnerability reporting** ("Report a vulnerability" under the Security tab).
- Email: **security@nulavio.net** (Portuguese or English). It is forwarded to the maintainer; no other `@nulavio.net` address receives mail. Also published as [`https://nulavio.net/.well-known/security.txt`](https://nulavio.net/.well-known/security.txt) (RFC 9116).
- Include affected commit or version, environment (distribution, desktop, engine version), reproduction steps and impact. Never include real credentials, cookies or personal data; use throwaway accounts.

We aim to acknowledge within **3 working days**, give an assessment within **10 working days**, and coordinate disclosure within **90 days** (sooner if a fix ships earlier, later only by agreement).

## Scope

| In scope | Out of scope (report upstream) |
|---|---|
| Nulavio launcher, configuration, Guard, start page, build and packaging scripts, Nulavio patches (Track B) | Gecko/Firefox engine bugs → [Mozilla security bug reporting](https://www.mozilla.org/en-US/security/bug-bounty/) |
| Weakening of upstream protections caused by Nulavio | Bugs in uBlock Origin, Proton Pass, KeePassXC, Bitwarden → their own projects |
| Information leaks in Nulavio logs or files | Malware already running as the user or as root (see [residual risks](docs/security/residual-risks.md)) |
| Supply-chain issues in pinned artefacts or CI | Distribution packages (report to the distribution) |

## Engine security updates

Track A relies on the distribution's Firefox package. Track B commits to the SLA in [update policy](docs/architecture/update-policy.md): critical/high Mozilla security releases shipped within 72 hours of Mozilla's release.

Within that commitment, urgent releases (critical or high impact, a sandbox escape, exploitation in the wild, public exploit code, or an advisory not yet available) have an internal target of 24 hours. Making 24 hours the public commitment is proposed and waits for the maintainer's decision.

How it works: GitHub Actions checks Mozilla's releases and advisories twice a day and alerts the maintainer through an issue with the target and the deadline. An opt-in timer on the maintainer's machine checks every 30 minutes and starts a build as soon as Mozilla stages a release. Builds use only source whose signature verifies against Mozilla's pinned release key. Signing and publishing stay with the maintainer. Each published build gets an entry in the [security changelog](docs/security/changelog.md) with the time it took.

## Safe harbour

Good-faith research that respects user privacy, avoids data destruction and does not degrade service is welcome. We will not pursue legal action for such research.
