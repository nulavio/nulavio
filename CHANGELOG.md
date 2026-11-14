# Changelog

Published release notes are recorded below automatically through a pull request. Earlier releases and security details:

- **[GitHub releases](https://github.com/nulavio/nulavio/releases)**: what each version brings, how to install or update it, and the signing key's fingerprint.
- **[Security changelog](docs/security/changelog.md)**: for each version, the Firefox release inside it and Mozilla's advisories it ships, how long it took to ship after Mozilla's release, and the weaknesses fixed in Nulavio's own code, with what a user should do, if anything. Security advisories for Nulavio's own code are on the [Security tab](https://github.com/nulavio/nulavio/security/advisories).

Versions are `<Firefox version>-<Nulavio release>`, for example `160.0-0.2`: the Firefox release inside, then Nulavio's revision of it. Each version is a git tag (`v160.0-0.2`).

Update an installed Nulavio with `sudo dnf upgrade nulavio`. Only the latest release receives fixes ([SECURITY.md](SECURITY.md#supported-versions)).

<!-- releases -->

<!-- release:v160.0-0.5 -->
## [160.0-0.5](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.5) — 2026-11-14

Nulavio 160.0-0.5, built from Firefox 160.0 (commit f5f1f1b79456).

### What's new

An update of the alpha with the same engine (Firefox 160.0): protected profiles that are easier to open and to keep, and fixes in the Guard, the Assistant and the Immersive mode.

#### What is new

- Each version's notes come with the browser: they are in Settings, About, and reading them sends nothing anywhere. The Help menu entry and the bar after an update come in the next version (corrected after release: #306).
- The engine's profile chooser unlocks a protected profile before it opens it, with the password, this computer's login or the recovery code.
- Replacing the recovery code takes two steps: the old code keeps working until you type the new one back.
- The Nulavio Companion app for Android comes with each release, signed with the project's key: download it from nulavio.net's download page, which shows the certificate's fingerprint to check.

#### Fixes

- When a change to the unlock methods is saved but not recorded inside the profile, the browser says so.
- The Guard notices when an extension's package is replaced by another file, even under the same version.
- An agent without permission for local resources sends no request to this computer or the local network.
- In the Immersive mode, the side tab list stays below the toolbar.
- The Assistant's item for selected text does not show in private windows.
- After making Nulavio the default browser on a package install, the menu shows one Nulavio.
- The phone pairing page no longer sends people to F-Droid, where the app is not yet, and says where to get it.

In Portuguese and English: https://nulavio.net/novidades/160.0-0.5/ and https://nulavio.net/en/whats-new/160.0-0.5/

### Features

- profiles: the profile chooser unlocks a protected profile before it starts it (#267) ([96a98cc62685](https://github.com/nulavio/nulavio/commit/96a98cc626855c49ae0819c0b316dbef8265f6df))
- release: a KMS signer for the Companion's APK, and ADR 0014 for its key (#260) ([724ccb5b8eab](https://github.com/nulavio/nulavio/commit/724ccb5b8eab194a5b5f4742c5530a85a9b1265f))
- release: each release measures the media in the history against ADR 0013's budget (#271) ([1790160fbd79](https://github.com/nulavio/nulavio/commit/1790160fbd79c7a85179ebe8233e416753475b9d))
- release: what is new in each version, written once and shown on the site (#272) ([59e574bc033d](https://github.com/nulavio/nulavio/commit/59e574bc033dc32e22558c640c47d105dd0d9e3b))
- vault: a new key for a protected profile, so a removed method stops opening old copies of the key file (#275) ([92f995f8d51c](https://github.com/nulavio/nulavio/commit/92f995f8d51c10163836e391d87a1535f43661e9))
- release: the Companion's own signing key in KMS, and releases that build, sign and attach its APK (#281) ([ecf4bf476287](https://github.com/nulavio/nulavio/commit/ecf4bf47628711b7181a0f75fc7e348ab6a56f4f))
- site: the download pages offer the Flatpak bundle, with its checks, permissions and limits (#288) ([102dcd104a6e](https://github.com/nulavio/nulavio/commit/102dcd104a6e8fc240663651711272b57852eaac))
- shell: what's new in this version, in the browser: the packed notes, a reader, and one bar after an update (#290) ([fe7dd4a7a5d8](https://github.com/nulavio/nulavio/commit/fe7dd4a7a5d8befa04cc5c38c3047aa8596aa326))

### Fixes

- settings: states and words the settings review found untrue in narrow cases (#255) ([d0165f6a5746](https://github.com/nulavio/nulavio/commit/d0165f6a57464f0ba9ae3e96d7add7aec5b5c718))
- ai: an agent without local\_resources sends no request to this computer or the local network (#248) ([3f562ba2eb3c](https://github.com/nulavio/nulavio/commit/3f562ba2eb3cb60e2864c0ea55697d85ab5781d7))
- vault: a recovery code replacement keeps the old code until the new one is typed back (#252) ([80c580e36a36](https://github.com/nulavio/nulavio/commit/80c580e36a3686819266a598ed302973890a003e))
- assistant: the selection item is hidden in a private window before its menu is drawn (#254) ([846286f8dd36](https://github.com/nulavio/nulavio/commit/846286f8dd36a0029ea75b8b44e8be10ff82b1bc))
- immersive: the side tab list stays under the toolbar, and a click outside the toolbar takes the keyboard out of it (#256) ([058fa409e048](https://github.com/nulavio/nulavio/commit/058fa409e048bec66e966284826b84b361141519))
- vault: the browser says when a change to the unlock methods was saved but not recorded (#253) ([522031d8e1fa](https://github.com/nulavio/nulavio/commit/522031d8e1fa8e102f5de63d03a62605d53626a5))
- shell: the phone page no longer sends people to F-Droid for the Companion (#261) ([70e3b5f7eb78](https://github.com/nulavio/nulavio/commit/70e3b5f7eb78c8de6cc5a3b3ae10fee575b63f3d))
- site: the engineering pages say which alpha is out, from release.json (#266) ([dca4ff10b4f9](https://github.com/nulavio/nulavio/commit/dca4ff10b4f9375fb57bd7540d021364bb5122f5))
- guard: report a replaced extension package by its digest, whatever version the engine says (#264) ([818c26d682e6](https://github.com/nulavio/nulavio/commit/818c26d682e6cab29f672771b17a76bafd41299e))
- ci: a refused AI review says whether it was credit, a spending limit or a parameter (#265) ([2363a5dcd214](https://github.com/nulavio/nulavio/commit/2363a5dcd214926c6c574b0350f3a1075e47178a))
- connect: one Nulavio in the menu after making it the default on a package install (#278) ([365fe1a997c0](https://github.com/nulavio/nulavio/commit/365fe1a997c02225ba02384edf1ae15a59894596))
- release: the APK signer refuses a data descriptor that only the local header announces (#291) ([e29976343463](https://github.com/nulavio/nulavio/commit/e29976343463196f791d74b757d938dba0b92c48))

### Security-related changes

- site: the deploy job reads the Cloudflare token from the site environment (#233) ([183121407a6f](https://github.com/nulavio/nulavio/commit/183121407a6fa9caf848e4f4b9b1ba1e2d5bcb2b))
- process: agents' instructions and skills get the second, independent review (#262) ([9076ea88a8ba](https://github.com/nulavio/nulavio/commit/9076ea88a8baac4fb13ac0513b5e84b283da80b2))

### Documentation

- product: #201 waits on Cloudflare and leaves wave 0 for After 1.0 (#235) ([b507b61fa464](https://github.com/nulavio/nulavio/commit/b507b61fa46422c03098311dad870e1f36139147))
- adr: follow Firefox Release past ten engine patches (#247) ([d9c6a97ff531](https://github.com/nulavio/nulavio/commit/d9c6a97ff531da4c8eed81f44b838737d6d1f083))
- security: accept plain-http search engines added by hand (R72) (#259) ([3c98251fd3bf](https://github.com/nulavio/nulavio/commit/3c98251fd3bff454634eea2651cd1a180a7ace6d))
- design: the install journey, walked on a clean Fedora KDE session (#276) ([c7b3355fabf8](https://github.com/nulavio/nulavio/commit/c7b3355fabf85c40c3b486574e93de03e06c26b9))
- process: agents' worktrees leave out the design screenshots (#270) ([cffbeb60125f](https://github.com/nulavio/nulavio/commit/cffbeb60125fa8926c7ad7dc32198da8259512cf))
- an AGENTS.md in each area of the repository (#263) ([6ed3cc2bb563](https://github.com/nulavio/nulavio/commit/6ed3cc2bb5630de14a69391e30757bd325113fb0))
- release: what is new in 160.0-0.5 (#279) ([fec77f6761e3](https://github.com/nulavio/nulavio/commit/fec77f6761e30ab31f31a02323fb6b2429dd1916))
- security: R46 records what the confined mode costs on Ubuntu (#285) ([040e44bb18a4](https://github.com/nulavio/nulavio/commit/040e44bb18a422fbacebbcda7522202744f903cb))
- release: 160.0-0.5's what's new names the browser's own notes and the bar after an update (#293) ([f5f1f1b79456](https://github.com/nulavio/nulavio/commit/f5f1f1b79456ac636a23466cfec84bcc7733cf98))

### Tests

- guard: the release run downloads the pinned extension instead of skipping the Guard's checks on it (#250) ([3896500e36d5](https://github.com/nulavio/nulavio/commit/3896500e36d5a2732c4fdd4229cb6ce3d9c33c79))
- search: the engine's own dialog takes a plain-http search address with no word said (#251) ([9cecc8acdfc1](https://github.com/nulavio/nulavio/commit/9cecc8acdfc18751f28f46e04e2963aad5d83e71))
- harness: a failing nulavio call says its exit status and the end of its stderr (#269) ([3d0e302b65ee](https://github.com/nulavio/nulavio/commit/3d0e302b65ee4dd5053b9b610368519ae4cbacfa))
- release: run the release scripts to check their signing and publishing protections (#268) ([10cfc7a0006f](https://github.com/nulavio/nulavio/commit/10cfc7a0006ff9d132c0cc40858ddd830c262836))

### Maintenance

- release: record v160.0-0.3 (#234) ([89fc823c5bd6](https://github.com/nulavio/nulavio/commit/89fc823c5bd64796e2f1513e8814dc8d5cb9fc2f))
- release: record v160.0-0.4 (#237) ([c300b3ad5b2f](https://github.com/nulavio/nulavio/commit/c300b3ad5b2fee0c326022d96a97ce4cb386902b))

[Full changelog](https://github.com/nulavio/nulavio/compare/v160.0-0.4...f5f1f1b79456ac636a23466cfec84bcc7733cf98)

### Install and verify

Install or upgrade on Fedora or Ubuntu: https://nulavio.net/en/download/

On Ubuntu, `nulavio.sources` from the download page has the SHA-256 `f77857a1515bcf9cb07a5e213f0525e36784e1d47bafb700f9d3e158fc537745`.

Other distributions, with Flatpak:

```sh
flatpak install --user nulavio-160.0-0.5.x86_64.flatpak
```

Nulavio Companion, the Android app for phone unlock: `nulavio-companion-0.1.0.apk`. Its signing certificate's SHA-256 is `d78d255ac7d83cc3e70d946921a5921c76dd92d9b865fcd12893b36d2ae9d3be` (`apksigner verify --print-certs nulavio-companion-0.1.0.apk` prints it).

Every release asset is covered by `SHA256SUMS.asc` (key `298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1`) and a GitHub build-provenance attestation.

```sh
gh attestation verify <file> --repo nulavio/nulavio
```

[Build and test run](https://github.com/nulavio/nulavio/actions/runs/43633960941).

[Security changelog](https://github.com/nulavio/nulavio/blob/main/docs/security/changelog.md) and [published advisories](https://github.com/nulavio/nulavio/security/advisories). Commit categories are not a vulnerability assessment.


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

