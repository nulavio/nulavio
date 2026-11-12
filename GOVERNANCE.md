# Governance

How decisions are made in Nulavio, who does what, and what happens if the maintainer is unavailable.

## Model

Nulavio has one maintainer, Caio Barbieri ([@caiolombello](https://github.com/caiolombello)), who owns the `nulavio` GitHub organization and makes the final call. The project is young (first public alpha on 2026-11-10); this file changes when a second maintainer joins.

Decisions are made in public, in writing:

| Kind of decision | Where it is proposed | Where it is recorded |
|---|---|---|
| Day-to-day changes | A pull request against `main` | The merged pull request and its squash commit |
| Architecture, security model, choice of engine or of a dependency with a large footprint | A pull request with an Architecture Decision Record | [`docs/adr/`](docs/adr/) |
| What gets built next | An issue or a [Discussion](https://github.com/nulavio/nulavio/discussions) | [`docs/product/roadmap.md`](docs/product/roadmap.md) |
| Accepted security risks | The pull request that accepts them | [`docs/security/residual-risks.md`](docs/security/residual-risks.md) |

Anyone can propose a change or argue against one in the issue or pull request. The maintainer decides what the project is and does: its direction, its ADRs, the risks it accepts. Day-to-day changes are reviewed and merged by the coding agents that work for him ([how](docs/process/pull-requests.md#review-and-merging)), and a proposal that is declined is told why. A decision recorded in an ADR is changed by a new ADR that supersedes it, not by editing the old one.

Some rules are not up for a case-by-case decision: the non-negotiables in [CONTRIBUTING.md](CONTRIBUTING.md#non-negotiables-reviewers-will-block-on-these) and the security invariants reviewers check ([`.github/ai-review/instructions.md`](.github/ai-review/instructions.md)).

## Roles and responsibilities

| Role | Who today | Responsibilities |
|---|---|---|
| Maintainer | Caio Barbieri | Sets the direction and decides what the project leaves to him (ADRs, accepted risks, what gets built next); answers for what is merged in his name and can revert it; answers every issue at least once; keeps the roadmap and the ADRs current; enforces the [code of conduct](CODE_OF_CONDUCT.md) |
| Security contact | Caio Barbieri | Receives reports ([SECURITY.md](SECURITY.md)): acknowledges within 3 working days, assesses within 10, coordinates disclosure within 90; publishes GitHub security advisories and credits reporters who want credit |
| Release manager | Caio Barbieri | Holds the release signing key (`298A 9093 BAAB B26F 79BB  29F4 BF47 E5FA 9EDB 8DB1`); ships Mozilla's security releases within 72 hours ([update policy](docs/architecture/update-policy.md)); signs and publishes packages; writes the [security changelog](docs/security/changelog.md) entry |
| Contributor | Anyone | Opens issues and pull requests following [CONTRIBUTING.md](CONTRIBUTING.md): tests with every change, signed-off commits (DCO), what was verified and what was not |
| Coding agent | AI tools working for the maintainer | Writes code and opens pull requests that name the tool; reviews them, records the review and merges them when the required checks pass, with a second independent review for the security-sensitive paths. Does not merge a change that weakens a protection, does not settle what is the maintainer's to decide, and does not release ([review and merging](docs/process/pull-requests.md#review-and-merging)) |

Mozilla maintains the Firefox engine. Engine bugs go to [Bugzilla](https://bugzilla.mozilla.org/); Nulavio's job is to ship Mozilla's fixes on time and keep its own patches small ([update and patch policy](docs/architecture/update-policy.md)).

## Continuity

The project must survive the maintainer becoming unavailable. These are the accounts and keys someone else would need to keep issues answered, merge fixes and ship a release within a week:

| What | Used for |
|---|---|
| Owner of the `nulavio` GitHub organization | Issues, pull requests, releases, security advisories, repository settings |
| Cloudflare account that holds `nulavio.net` | DNS, the website (Pages), the package repository bucket (R2), mail forwarding for `security@nulavio.net` |
| Release signing key and its revocation certificate | Signing packages and the dnf repository metadata |

**Current state: not met.** Today one person holds all three. Until a second person holds them, an outage of the maintainer stops releases. The plan, tracked as a maintainer item: a second organization owner with access to the Cloudflare account, and offline copies of the release key and its revocation certificate that this person can reach without the maintainer. This section will name that person and say how to contact them.

If the release key is lost, the revocation certificate is published and a new key is announced on the website, in the README and in a signed message from the old key, if it is still available.
