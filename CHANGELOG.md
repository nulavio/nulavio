# Changelog

Published release notes are recorded below automatically through a pull request. Earlier releases and security details:

- **[GitHub releases](https://github.com/nulavio/nulavio/releases)**: what each version brings, how to install or update it, and the signing key's fingerprint.
- **[Security changelog](docs/security/changelog.md)**: for each version, the Firefox release inside it and Mozilla's advisories it ships, how long it took to ship after Mozilla's release, and the weaknesses fixed in Nulavio's own code, with what a user should do, if anything. Security advisories for Nulavio's own code are on the [Security tab](https://github.com/nulavio/nulavio/security/advisories).

Versions are `<Firefox version>-<Nulavio release>`, for example `160.0-0.2`: the Firefox release inside, then Nulavio's revision of it. Each version is a git tag (`v160.0-0.2`).

Update an installed Nulavio with `sudo dnf upgrade nulavio`. Only the latest release receives fixes ([SECURITY.md](SECURITY.md#supported-versions)).

<!-- releases -->

<!-- release:v160.0-0.3 -->
## [160.0-0.3](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.3) — 2026-11-11

Nulavio 160.0-0.3, built from Firefox 160.0 (commit 123b12def4eb).

Install or upgrade on Fedora: https://nulavio.net/en/download/

Every file here is signed (SHA256SUMS.asc, key 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1) and has a GitHub build-provenance attestation:

    gh attestation verify <file> --repo nulavio/nulavio

Built and tested by run https://github.com/nulavio/nulavio/actions/runs/43102367281.

