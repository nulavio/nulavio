# Security policy

## Supported versions

Nulavio has **no releases yet**. The `main` branch (Track A preview) is the only supported code. Once releases exist, the latest release and the previous one will receive security fixes.

## Reporting a vulnerability

- **Do not open a public issue.**
- Preferred channel once the repository is public: **GitHub private vulnerability reporting** ("Report a vulnerability" under the Security tab).
- A dedicated security contact address will be published here before the first public release. *Pending: the domain `nulavio.net` is registered, but no mailbox exists yet. Do not send reports to any `@nulavio.net` address until it is listed here.*
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

Track A relies on the distribution's Firefox package. Track B commits to the SLA in [update policy](docs/architecture/update-policy.md): critical/high Mozilla security releases shipped within 72 hours.

## Safe harbour

Good-faith research that respects user privacy, avoids data destruction and does not degrade service is welcome. We will not pursue legal action for such research.
