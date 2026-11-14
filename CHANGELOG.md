# Changelog

Published release notes are recorded below automatically through a pull request. Earlier releases and security details:

- **[GitHub releases](https://github.com/nulavio/nulavio/releases)**: what each version brings, how to install or update it, and the signing key's fingerprint.
- **[Security changelog](docs/security/changelog.md)**: for each version, the Firefox release inside it and Mozilla's advisories it ships, how long it took to ship after Mozilla's release, and the weaknesses fixed in Nulavio's own code, with what a user should do, if anything. Security advisories for Nulavio's own code are on the [Security tab](https://github.com/nulavio/nulavio/security/advisories).

Versions are `<Firefox version>-<Nulavio release>`, for example `160.0-0.2`: the Firefox release inside, then Nulavio's revision of it. Each version is a git tag (`v160.0-0.2`).

Update an installed Nulavio with `sudo dnf upgrade nulavio`. Only the latest release receives fixes ([SECURITY.md](SECURITY.md#supported-versions)).

<!-- releases -->

<!-- release:v160.0-0.4 -->
## [160.0-0.4](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.4) — 2026-11-14

Nulavio 160.0-0.4, built from Firefox 160.0 (commit a9ff2ff7c200).

### Features

- release: publish the Flatpak as a release asset until it is on Flathub (#87) ([b0a695bd8274](https://github.com/nulavio/nulavio/commit/b0a695bd8274af85b14aab3f0a7267cb52f21267))
- filter: a new profile starts with the lists Helium switches on (a default, never a lock) (#83) ([3584240963f1](https://github.com/nulavio/nulavio/commit/3584240963f1c2c5fea2bd7806473f625dccfdc7))
- experience: one settings page inside the engine's own, Immersive, the first run as a stage and the frame (#132) ([053a42ab3b7f](https://github.com/nulavio/nulavio/commit/053a42ab3b7fce8f365f55d972b62fd0408c9cb8))
- site: a waitlist sign-up is answered with a private link, which is what removes it (#178) ([1f706a72b193](https://github.com/nulavio/nulavio/commit/1f706a72b193b71cd50b26b22c96d8fb7df93102))
- site: add sitemap and bilingual search metadata (#191) ([e1db1d128b36](https://github.com/nulavio/nulavio/commit/e1db1d128b363b86b31ba6b117c77a45e28e22af))
- release: automate release notes and published metadata (#196) ([c779dfd770fd](https://github.com/nulavio/nulavio/commit/c779dfd770fddab9deab3e41b2a9c00d1d0b731e))
- release: a signed APT repository, so Ubuntu gets the .deb and its updates through apt (#214) ([9c2b64d3f208](https://github.com/nulavio/nulavio/commit/9c2b64d3f208dc17c34e5eecfe397db9a6324658))

### Fixes

- prefs: no question to Google's update service about a DRM module that is off (#110) ([7f44a7bd1e6e](https://github.com/nulavio/nulavio/commit/7f44a7bd1e6e36a49d9b2b1698d7ba0f161b4b80))
- profiles: the engine's start-up chooser off, and a protected profile is never the profile a plain start opens (#68) ([30e89aef22b7](https://github.com/nulavio/nulavio/commit/30e89aef22b7f3d171fac37e3db0e971a2c008f8))
- guard: the engine's held update is not reported, the bar says what waits, and what another program does to an extension is (#76) ([d45ede2c8283](https://github.com/nulavio/nulavio/commit/d45ede2c82834c7e779afdabfad4adbb934771aa))
- prefs: the plugin and built-in add-on checks no longer tell Mozilla the kernel, GTK and libpulse versions or Nulavio's name (#127) ([696802497844](https://github.com/nulavio/nulavio/commit/6968024978441d89a8c2e4107308879641e54bd4))
- packaging: the packages name both licences (#140) ([4dd36fc1f41d](https://github.com/nulavio/nulavio/commit/4dd36fc1f41d061e517063af12b3dee29866a205))
- frontend: the audit after the alpha and its seven corrections (#143) ([f7fb3cc28242](https://github.com/nulavio/nulavio/commit/f7fb3cc28242568a3ab3a0fc172eea50efc83511))
- ci: the upstream marker pattern has one reading, and the code scanning alerts are settled (#147) ([3fa431995b1f](https://github.com/nulavio/nulavio/commit/3fa431995b1f5daf58c34a80709b1d700d3baa15))
- ci: the AI review installs bubblewrap, which Claude Code needs to start (#188) ([69d36b92161a](https://github.com/nulavio/nulavio/commit/69d36b92161a89ee6453e0dd3451d1be3b0a4f8a))
- site: the landing marks what the alpha does not have yet; band initial at 11 px (#203) ([41b35b3c7fea](https://github.com/nulavio/nulavio/commit/41b35b3c7feac1197d97ec1c16383a01888c50d6))
- ci: the AI review says why it ended when the model API refuses it (#200) ([ac3dbaa754b4](https://github.com/nulavio/nulavio/commit/ac3dbaa754b4630dc6f85e5239f3a7516ea639ec))
- ci: the AI reviewer is told about the empty files its own tool leaves in the tree (#206) ([745a3a38657f](https://github.com/nulavio/nulavio/commit/745a3a38657f7d92099dda70b988c83aded57f96))

### Security-related changes

- stricter session, address and form checks in the AI Bridge; unlock-method changes recorded in the Vault (#150) ([c1ae83235fde](https://github.com/nulavio/nulavio/commit/c1ae83235fdeed18bfad48ae0318b98d9a854002))

### Documentation

- process: coding agents review and merge their own pull requests (#133) ([36ccaf86f85e](https://github.com/nulavio/nulavio/commit/36ccaf86f85e8b6eb83178019a3ec85824b5cc32))
- security: what a new profile contacts by itself, and a test that fails on an address that is not listed (#125) ([cdc79afec2a8](https://github.com/nulavio/nulavio/commit/cdc79afec2a8d4723a1f0218e863263ebe994d92))
- native content filter spike (ADR 0012, proposed) and issues as the shared backlog (#96) ([0476abb9f848](https://github.com/nulavio/nulavio/commit/0476abb9f848ecd492e312e2ec580116159d3178))
- repository layout measured, ADR 0013 proposed (one repository, organized by area), and where private work goes (#146) ([2751023a74a7](https://github.com/nulavio/nulavio/commit/2751023a74a7157a600ef7d4e89fbe7332d4184c))
- adr: ADR 0013 accepted, private work adopted with what its first run showed (#184) ([546deee14182](https://github.com/nulavio/nulavio/commit/546deee14182e7b16efaa8f45fa397ee5a489401))
- refine supporters and remove unregistered-trademark disclosures (#183) ([543079c58071](https://github.com/nulavio/nulavio/commit/543079c580718f10cd1886fbe5830a4784c1c86c))
- security: R70, what a removed unlock method still opens and what an interrupted change leaves (#186) ([2e8c3e846b03](https://github.com/nulavio/nulavio/commit/2e8c3e846b0312c6b44da324feca28e96c4af4d1))
- agents: project skills for pull requests, engine checks, the Shell and private fixes (#213) ([e2b68d283ce6](https://github.com/nulavio/nulavio/commit/e2b68d283ce60f745ebf1a0a382fed4caef35c4a))
- process: how the AI review's federation rule has to match this repository (#208) ([1e6ddc842c91](https://github.com/nulavio/nulavio/commit/1e6ddc842c912a9e320fcb8b15fa2b8fa40d16bf))
- product: the road to 1.0 in waves, with its milestones and release plan (#229) ([f3d453ed6bfe](https://github.com/nulavio/nulavio/commit/f3d453ed6bfe8d435289e32640d6a4a4b587b21a))
- process: the board's Model field follows Anthropic's model and effort guidance (#230) ([6c2168f75194](https://github.com/nulavio/nulavio/commit/6c2168f75194667901cc61cb4f359d146eadee27))

### Tests

- filter: the content-filter test removes its temporary home (#139) ([ea581e04d742](https://github.com/nulavio/nulavio/commit/ea581e04d74211b648d1a053dbb47263733a42fe))
- keepassxc: the end-to-end step waits for what it reads instead of sleeping (#144) ([bbe80464e7e0](https://github.com/nulavio/nulavio/commit/bbe80464e7e03755e0e0d711e2eae5c620031299))
- engine: the permissions walk skips a file the running engine removed (#210) ([3009d501413c](https://github.com/nulavio/nulavio/commit/3009d501413cade21b682ca1b09f16df6cd24d63))
- engine: the settings helper finds the driver's tab by its handle (#232) ([a9ff2ff7c200](https://github.com/nulavio/nulavio/commit/a9ff2ff7c2008448eb55087b09b19166deeb00df))

### Maintenance

- review: CodeRabbit configured as an advisory reviewer, with instructions per area (#145) ([11f4547d503e](https://github.com/nulavio/nulavio/commit/11f4547d503edde3c62f612762899f49c62bdc0c))
- dev: add shared Modern Web Guidance tooling (#197) ([45c66026c71e](https://github.com/nulavio/nulavio/commit/45c66026c71e8559f7983e09f86ffa1e5285b10c))

### Build and CI

- release: compose the Flatpak's appstream with absolute media URLs, as Flathub does (#82) ([52f393221e12](https://github.com/nulavio/nulavio/commit/52f393221e12ffa00a14230638990e8c670f6b1f))
- deps: claude-code-action v1.0.268 with Claude Code 2.1.318, and codeql-action v4.39.3 (#63) ([fae9c9d2b04b](https://github.com/nulavio/nulavio/commit/fae9c9d2b04b07c2dc773a613aff860d7e0598ef))
- deps: Bump wrangler from 4.157.0 to 4.158.0 in /ci/site in the site-deploy group (#134) ([c5629cafbfcd](https://github.com/nulavio/nulavio/commit/c5629cafbfcd60164377e759c09936d684cc1689))

### Other changes

- release: 160.0-0.3 is the published release (#85) ([e1768d03630d](https://github.com/nulavio/nulavio/commit/e1768d03630d4aa26e2838cab04d2f5ab96a05ab))

[Full changelog](https://github.com/nulavio/nulavio/compare/v160.0-0.3...a9ff2ff7c2008448eb55087b09b19166deeb00df)

### Install and verify

Install or upgrade on Fedora or Ubuntu: https://nulavio.net/en/download/

On Ubuntu, `nulavio.sources` from the download page has the SHA-256 `f77857a1515bcf9cb07a5e213f0525e36784e1d47bafb700f9d3e158fc537745`.

Other distributions, with Flatpak:

```sh
flatpak install --user nulavio-160.0-0.4.x86_64.flatpak
```

Every release asset is covered by `SHA256SUMS.asc` (key `298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1`) and a GitHub build-provenance attestation.

```sh
gh attestation verify <file> --repo nulavio/nulavio
```

[Build and test run](https://github.com/nulavio/nulavio/actions/runs/43534834214).

[Security changelog](https://github.com/nulavio/nulavio/blob/main/docs/security/changelog.md) and [published advisories](https://github.com/nulavio/nulavio/security/advisories). Commit categories are not a vulnerability assessment.


<!-- release:v160.0-0.3 -->
## [160.0-0.3](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.3) — 2026-11-11

Nulavio 160.0-0.3, built from Firefox 160.0 (commit 123b12def4eb).

Install or upgrade on Fedora: https://nulavio.net/en/download/

Every file here is signed (SHA256SUMS.asc, key 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1) and has a GitHub build-provenance attestation:

    gh attestation verify <file> --repo nulavio/nulavio

Built and tested by run https://github.com/nulavio/nulavio/actions/runs/43102367281.

