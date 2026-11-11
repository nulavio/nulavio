# Changelog

Release notes for every Nulavio version live in two places, so they are not copied here:

- **[GitHub releases](https://github.com/nulavio/nulavio/releases)**: what each version brings, how to install or update it, and the signing key's fingerprint.
- **[Security changelog](docs/security/changelog.md)**: for each version, the Firefox release inside it and Mozilla's advisories it ships, how long it took to ship after Mozilla's release, and the weaknesses fixed in Nulavio's own code, with what a user should do, if anything. Security advisories for Nulavio's own code are on the [Security tab](https://github.com/nulavio/nulavio/security/advisories).

Versions are `<Firefox version>-<Nulavio release>`, for example `160.0-0.2`: the Firefox release inside, then Nulavio's revision of it. Each version is a git tag (`v160.0-0.2`).

Update an installed Nulavio with `sudo dnf upgrade nulavio`. Only the latest release receives fixes ([SECURITY.md](SECURITY.md#supported-versions)).
