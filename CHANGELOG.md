# Changelog

Published release notes are recorded below automatically through a pull request. Earlier releases and security details:

- **[GitHub releases](https://github.com/nulavio/nulavio/releases)**: what each version brings, how to install or update it, and the signing key's fingerprint.
- **[Security changelog](docs/security/changelog.md)**: for each version, the Firefox release inside it and Mozilla's advisories it ships, how long it took to ship after Mozilla's release, and the weaknesses fixed in Nulavio's own code, with what a user should do, if anything. Security advisories for Nulavio's own code are on the [Security tab](https://github.com/nulavio/nulavio/security/advisories).

Versions are `<Firefox version>-<Nulavio release>`, for example `160.0-0.2`: the Firefox release inside, then Nulavio's revision of it. Each version is a git tag (`v160.0-0.2`).

Update an installed Nulavio with `sudo dnf upgrade nulavio`. Only the latest release receives fixes ([SECURITY.md](SECURITY.md#supported-versions)).

<!-- releases -->

<!-- release:v160.0.1-0.2 -->
## [160.0.1-0.2](https://github.com/nulavio/nulavio/releases/tag/v160.0.1-0.2) — 2026-11-19

Nulavio 160.0.1-0.2, built from Firefox 160.0.1 (commit be6d3ea3671b).

### What's new

Automatic updates of Nulavio, turned on by you: twice a day the system installs the new version of the package, without waiting for the browser.

#### Changes that need your attention

- Send Link to Device, in a link's menu, is gone: Plasma Browser Integration has its own KDE Connect sharing. The KDE Connect row in Integrations still shows the devices in reach.
- If you wrote your own list of protections in about:config (privacy.fingerprintingProtection.overrides), add +ScreenSizeConstant: without that entry, sites no longer read the 1920 by 1080 screen, and read the size of yours. If you never changed it, there is nothing to do.

#### What is new

- Automatic updates, in Settings and on the first run: when on, the system installs Nulavio's new version at midnight and noon (on Fedora only from Nulavio's repository; on Ubuntu the highest among the system's sources). Turning them on or off asks for the administrator's password.
- More Nulavio actions in the address bar: Ctrl+Alt+P lists them, and they now include Immersive, a temporary window, switching profile and copying a link to the selected text.
- The security panels open at once, with no animation: the site's panel (identity and protections), the site's permissions and permission prompts. The sidebar's panels move at the same pace as the sidebar.

In Portuguese and English: https://nulavio.net/novidades/160.0.1-0.2/ and https://nulavio.net/en/whats-new/160.0.1-0.2/

### Features

- packaging: automatic updates shipped off, turned on through polkit (#523) ([e1a376fa1ee6](https://github.com/nulavio/nulavio/commit/e1a376fa1ee61a2971786e99ccfbde4862c33142))
- shell: automatic updates in the first run and in Settings, About (#538) ([5de838b7084c](https://github.com/nulavio/nulavio/commit/5de838b7084c012b0c17e96a81437415234bfa51))
- connect: sending a link to a KDE Connect device is left to Plasma Browser Integration (#532) ([d511856f7416](https://github.com/nulavio/nulavio/commit/d511856f74167d2c8685809e382e48946eef83b8))
- shell: Imersivo's tab list on the right leaves and comes back by the right edge (#539) ([801d3a9c36c2](https://github.com/nulavio/nulavio/commit/801d3a9c36c2dbc84ff494f0a4f6e4fdb48c6300))
- shell: Nulavio's actions in the address bar, and Ctrl+Alt+P to list them (#533) ([4549d3b77bf5](https://github.com/nulavio/nulavio/commit/4549d3b77bf58dd2c77ee13043a6a1ac4eec06fb))
- perf: perf.yml fails a release's run past the runner's noise (#525) ([794c6f2c4fc5](https://github.com/nulavio/nulavio/commit/794c6f2c4fc510042ffb28e4eb260d7a2899a42b))
- window: the motion map, with security panels that open at once and sidebar panels on the motion tokens (#554) ([5c626c72f697](https://github.com/nulavio/nulavio/commit/5c626c72f6977c36166216fc3c89113f59ba3bb7))

### Fixes

- shell: the page menu's submenu is named "Nulavio", not "Nulavio Shell" (#530) ([a5a2704e36c4](https://github.com/nulavio/nulavio/commit/a5a2704e36c458415a225945bd25c40fd4eea8c9))
- ai: the AI Workspace refuses public pages' requests to local addresses after its own DNS lookup (#542) ([cfd0b07b4608](https://github.com/nulavio/nulavio/commit/cfd0b07b46085b6b62bdea6786d47fe05042890b))
- vault: the methods page says what a missing method or profile is (#548) ([2313f64d30d4](https://github.com/nulavio/nulavio/commit/2313f64d30d4c64539f6d121d844339692fd4489))
- ci: the Companion's Gradle steps read Maven Central through a mirror first (#552) ([733fae997fc3](https://github.com/nulavio/nulavio/commit/733fae997fc31247677ef83adf487de7f3537cdc))
- vault: the phone, unlock and create pages say what a missing profile or method is (#557) ([fca86d0fe2a5](https://github.com/nulavio/nulavio/commit/fca86d0fe2a546757e38c15fb9659c10b7f58330))
- shell: a temporary window that fails to launch and a link that fails to copy say so (#559) ([0c3bd7e9f622](https://github.com/nulavio/nulavio/commit/0c3bd7e9f62247d33c1c2c25cf3e07753af535d0))
- ai: harden the AI Bridge's engine lookup (#563) ([8d265dc8320d](https://github.com/nulavio/nulavio/commit/8d265dc8320d50cba301c74a6a341248af712bb6))

### Security-related changes

- release: the daily watch reads each pinned extension's security advisories (#556) ([44c30cc41674](https://github.com/nulavio/nulavio/commit/44c30cc416746312aaf7423680a9a2687079cba3))

### Documentation

- security: 160.0.1-0.1 published within the 24-hour target (#541) ([64658caafee4](https://github.com/nulavio/nulavio/commit/64658caafee41a062ec7e060c6520c67e3473505))
- research: the side panel opposite the tabs, the #249 spike's result (#528) ([0fd1d3941aae](https://github.com/nulavio/nulavio/commit/0fd1d3941aae04cb8431bb36d42de23a2b27fc4a))
- security: R83 accepted by the maintainer (#551) ([214a3635c636](https://github.com/nulavio/nulavio/commit/214a3635c6365cf31572932103fbf76cfc4b7eee))

### Tests

- search: a sign-in survives the lock and unlock of a protected profile (#529) ([e63efa18a301](https://github.com/nulavio/nulavio/commit/e63efa18a301507b8a57c3d592208642fad1daea))
- immersive: the pointer journeys end their tab drag, and the toolbar takes the pointer again (#531) ([25a3d89cbfd1](https://github.com/nulavio/nulavio/commit/25a3d89cbfd11f2a7a4c0c8ae1d49e4968badd48))
- ai: the dark captures end the buttons' colour transition before they are taken (#537) ([da0b3c6206dc](https://github.com/nulavio/nulavio/commit/da0b3c6206dcdff25534dedda3d839c3fdba650c))
- services: menus read once the last drawing is in, and a failure says what the engine holds (#545) ([2b170596f40d](https://github.com/nulavio/nulavio/commit/2b170596f40d276f5bde77cdb69b2ab81c449a85))
- perf: the page-loading line measured in the UX7 frame budget (#534) ([434411a4760d](https://github.com/nulavio/nulavio/commit/434411a4760d18a41bd6f7d0f755f1e3b2ed5ebb))
- passwords: the popup check waits for the page and retries a discarded tab once (#522) ([a67e4ced8f65](https://github.com/nulavio/nulavio/commit/a67e4ced8f6563be99a4fba1b1f2bf02d579866e))
- downloads: keep the state that has the button's accessible name (#567) ([be6d3ea3671b](https://github.com/nulavio/nulavio/commit/be6d3ea3671bfd19eb65597b591529da6c3cb9ac))

### Maintenance

- release: record v160.0.1-0.1 (#540) ([94450e598f5e](https://github.com/nulavio/nulavio/commit/94450e598f5e06f9d264d8c52a6426822ba28137))
- fingerprinting: the engine alone gives pages the constant screen size (#549) ([32fc58b37634](https://github.com/nulavio/nulavio/commit/32fc58b376345d8320b08694009582013c076791))

[Full changelog](https://github.com/nulavio/nulavio/compare/v160.0.1-0.1...be6d3ea3671bfd19eb65597b591529da6c3cb9ac)

### Install and verify

Install or upgrade on Fedora or Ubuntu: https://nulavio.net/en/download/

On Ubuntu, `nulavio.sources` from the download page has the SHA-256 `f77857a1515bcf9cb07a5e213f0525e36784e1d47bafb700f9d3e158fc537745`.

Nulavio Companion, the Android app for phone unlock: `nulavio-companion-0.1.0.apk`. Its signing certificate's SHA-256 is `d78d255ac7d83cc3e70d946921a5921c76dd92d9b865fcd12893b36d2ae9d3be` (`apksigner verify --print-certs nulavio-companion-0.1.0.apk` prints it).

Every release asset is listed in `SHA256SUMS`, signed in `SHA256SUMS.asc` (key `298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1`): check that first, as the download page shows. Each also has a GitHub build-provenance attestation from the release workflow on `main`; check it with both of these options:

```sh
gh attestation verify <file> --repo nulavio/nulavio \
  --signer-workflow nulavio/nulavio/.github/workflows/release.yml --source-ref refs/heads/main
```

[Build and test run](https://github.com/nulavio/nulavio/actions/runs/44442004774).

[Security changelog](https://github.com/nulavio/nulavio/blob/main/docs/security/changelog.md) and [published advisories](https://github.com/nulavio/nulavio/security/advisories). Commit categories are not a vulnerability assessment.


<!-- release:v160.0.1-0.1 -->
## [160.0.1-0.1](https://github.com/nulavio/nulavio/releases/tag/v160.0.1-0.1) — 2026-11-18

Nulavio 160.0.1-0.1, built from Firefox 160.0.1 (commit 419967a45604).

### What's new

A security update of the alpha, with the engine on Firefox 160.0.1 and Mozilla's security fixes. Also, sites get even less to recognise your computer by, a site can be stopped from blocking copy and paste, and the window gains a loading line.

#### Changes that need your attention

- Sites are no longer told that your system asks for less motion or more contrast, because that helps recognise you from one site to the next. Sites then show their animations, and pages scroll smoothly.
- If you rely on those settings, turn on Let sites see my motion and contrast preferences in Settings, Privacy and security. When your system has one of them on, a bar offers it once.
- Copying a link to the selected text is now Ctrl+Alt+C instead of Ctrl+Shift+L, which is a key of Bitwarden, 1Password and Proton Pass.
- Nulavio's KRunner plugin is gone: KDE's KRunner already opens an address or a search in the default browser. If you used Add to KRunner, delete krunner/dbusplugins/net.nulavio.krunner.desktop and dbus-1/services/net.nulavio.krunner.service under ~/.local/share (or XDG\_DATA\_HOME, if set).

#### What to do

- If you used the preview, which ran Nulavio's profile on the distribution's Firefox: it is no longer offered. Install the package. The preview's profiles stay in ~/.local/share/nulavio/profiles, and the project's README says how to bring their bookmarks and passwords along.
- If you installed the Flatpak bundle of an earlier version: it never updates, and releases no longer carry it. On Fedora or Ubuntu, install the RPM or APT package, export bookmarks and passwords in the Flatpak and import them, then remove it. Elsewhere, remove it and wait for Flathub.
- If you gave an AI agent raw automation: it was removed from Nulavio. The agent keeps working through Nulavio's tools, with your permissions and the activity log; an automation library of its own needs a Firefox profile outside Nulavio. Reconnect the agent after updating.
- If you ran nulavio desktop install for the preview: the command is gone. Delete ~/.local/share/applications/nulavio-preview.desktop and the nulavio-preview icons under ~/.local/share/icons/hicolor (or XDG\_DATA\_HOME, if set); the package installs its own menu entry.

#### What is new

- The sound a page renders to recognise your computer is now different on every site, and the 1920 by 1080 screen holds for every part of a page: frames, pop-ups and images too. What you hear does not change.
- Allow copy and paste on this site, in the shield's panel: for a site that blocks copying, pasting or the page menu. Off by default, kept per site, and listed in Settings with the other site exceptions.
- Hide the page title in the window title, in Settings, Appearance: the title bar, the taskbar and screen-sharing pickers show Nulavio, not the page's title.
- Immersive is in the View menu, next to Full Screen, and the first run offers it when the tabs are in the side list.
- A thin line along the top of the page while it loads, off by default: turn it on in Settings, Appearance, Show a loading line at the top of the page.
- Diagnostics from a terminal on a package install: nulavio-doctor checks the package's engine, the codecs, the system keyring and the password managers' connection. The nulavio command still opens the browser.

#### Fixes

- The engine moves to Firefox 160.0.1, with the security fixes of Mozilla's advisory mfsa2026-130, of high severity.
- On a system without the codec library, sound in MP4, as most video sites send it, did not play. The packages now recommend the library, and the nulavio-doctor command says when it is missing and what to install.
- The first run's choice of tab arrangement fits the screen at 150 % on a small display, where the options' names were set one letter per line.

In Portuguese and English: https://nulavio.net/novidades/160.0.1-0.1/ and https://nulavio.net/en/whats-new/160.0.1-0.1/

### Features

- privacy: a per-site switch lets a site's pages no longer block copy, paste and the page menu (#386) ([3b2f36a8e271](https://github.com/nulavio/nulavio/commit/3b2f36a8e2712f6ed11f620d35b68ca3a8d5ae20))
- shell: edit the text of a page in place, from the page menu or Ctrl+Alt+E (#385) ([0355da12b276](https://github.com/nulavio/nulavio/commit/0355da12b276d208d7d93a3e86f6b0a579cf0523))
- settings: a switch keeps the page's title out of the window's title (D-UX17) (#390) ([fe334c49c81b](https://github.com/nulavio/nulavio/commit/fe334c49c81bed9a01c10969e7e5dc88d0d2ee41))
- newtab: the first run's layout step offers Imersivo with the side tab list (#391) ([8c13ef83ede4](https://github.com/nulavio/nulavio/commit/8c13ef83ede4e417fda9c56d2f519dc8d628dfcb))
- layout: Imersivo in the View menu, next to Full Screen (#393) ([f8870a30de70](https://github.com/nulavio/nulavio/commit/f8870a30de70929457f949da523a84d878ffb9ae))
- window: keep a window above the others on KDE Plasma, from the View menu or Ctrl+Alt+K (#392) ([827413fd02b0](https://github.com/nulavio/nulavio/commit/827413fd02b064147970a6ffb333b3cf43b910b1))
- window: a calm page-loading line along the top of the page (#394) ([814396269086](https://github.com/nulavio/nulavio/commit/8143962690867baf1a904b1ce2b71d004fdc4b7c))
- fingerprinting: sites are not told the system's motion and contrast preferences, unless the person says so (#380) ([42750b1647d8](https://github.com/nulavio/nulavio/commit/42750b1647d866bde3536cdb0ccb7b96886a8eb6))
- fingerprinting: rendered audio differs per site, and the engine gives every document one screen size (#402) ([7f9e6f5210b5](https://github.com/nulavio/nulavio/commit/7f9e6f5210b572b800fb53cbcfeb0298be6931ed))
- ci: a nightly rehearsal of main runs the tests that pull requests skip, and an issue says when it fails (#431) ([3d399f0a67ca](https://github.com/nulavio/nulavio/commit/3d399f0a67cab7b6ff609b2f0c6a23230d31cb68))
- release: the engine's Rust networking check is read from a build made for it, and gates the pin and publishing (#438) ([68ec0575faad](https://github.com/nulavio/nulavio/commit/68ec0575faad9116a3aa0ce2f9abef314a3473e1))
- release: a workflow makes the Rust networking reading and attests it, and signing requires that attestation (#457) ([ddd0c8bae220](https://github.com/nulavio/nulavio/commit/ddd0c8bae220a6a6108b9b82270f4bbe23ead647))
- build: C++ and Rust link-time optimisation across each other (cross-language ThinLTO) (#371) ([d4d7aef595f8](https://github.com/nulavio/nulavio/commit/d4d7aef595f861f5fd1dd8f3ff80e1ec5be40f84))
- release: the attested networking reading names the Rust compiler, and a release built with another is refused (#481) ([aaeb03fe63c8](https://github.com/nulavio/nulavio/commit/aaeb03fe63c8dab5b33c86799d65422ac1dcb323))
- search: choose a profile's search provider in one step, signed in where it has accounts (#442) ([6178b3a86c5d](https://github.com/nulavio/nulavio/commit/6178b3a86c5db0bb191e905e0d1b0f5aa942175c))
- search: an account-based provider is said before it is chosen, and no search address carries a session (#484) ([114090a8fe12](https://github.com/nulavio/nulavio/commit/114090a8fe12004fd1ea21d7485a17947452276c))
- passwords: 1Password as a credential provider (#478) ([26a8177dee3f](https://github.com/nulavio/nulavio/commit/26a8177dee3f5f8826c242a685a3587666938a6f))
- services: translation with a web service the person adds, used only on a click (#443) ([99156580bb08](https://github.com/nulavio/nulavio/commit/99156580bb088977125ec66f90714464e198375b))
- launcher: the Track A preview is no longer a way to use Nulavio (#500) ([eeb66ce8b353](https://github.com/nulavio/nulavio/commit/eeb66ce8b3535e53c28c2af633998eb021647341))
- release: releases stop offering the Flatpak bundle, which never updates, until Flathub (#501) ([82bc55dde68c](https://github.com/nulavio/nulavio/commit/82bc55dde68c1d9fa5acff3340e0825c4f5cc3b1))
- window: the page-loading line is off in a new profile, with a switch in Settings (#505) ([e3f665dd9b74](https://github.com/nulavio/nulavio/commit/e3f665dd9b74c0283b5383cd13779792c23d0e59))
- shell: Copy Link to Highlight moves to Ctrl+Alt+C, off the password managers' Ctrl+Shift+L (#506) ([dabad4517be6](https://github.com/nulavio/nulavio/commit/dabad4517be6d7698bbfb508e6e296736431361f))
- ai: raw automation is removed from the AI Bridge: agents act only through the policy (#504) ([e94674979f5a](https://github.com/nulavio/nulavio/commit/e94674979f5a173a14a1431ce9f69009712b8b2f))
- packaging: nulavio-doctor runs the diagnostics from a package install (#507) ([763cc23329ed](https://github.com/nulavio/nulavio/commit/763cc23329ed5839033333b50609e0cdada427c5))
- launcher: nulavio desktop install is removed with the preview (#511) ([08f6cee33bc6](https://github.com/nulavio/nulavio/commit/08f6cee33bc690c9d303f2aee461cf42ea83ae9f))
- shell: editing a page's text leaves the browser for an extension the documentation names (#512) ([0ed225117eb1](https://github.com/nulavio/nulavio/commit/0ed225117eb15d00c8906e68045e8d1ae1901cb4))
- shell: keeping a window above others is left to KDE's own window menu (#513) ([a4b26522fde0](https://github.com/nulavio/nulavio/commit/a4b26522fde0148b16f8a78c0526c00203418184))
- connect: the KRunner plugin is removed (#514) ([270b142a43a9](https://github.com/nulavio/nulavio/commit/270b142a43a95e4fb42b0f6ad0706619a79ca835))

### Fixes

- packaging: the packages ask for the system's codec library, and doctor names it when it is missing (#401) ([e6ccc59caf84](https://github.com/nulavio/nulavio/commit/e6ccc59caf84829c42a62d8a8d112fe01682a387))
- launcher: a seeded preference nobody changed follows the baseline (#400) ([f887797e523c](https://github.com/nulavio/nulavio/commit/f887797e523ccfc89898613be215a51cba670539))
- newtab: the first run's layout card after Imersivo: its tests, its error state and 150 % on a small screen (#404) ([d1aa8cac84ca](https://github.com/nulavio/nulavio/commit/d1aa8cac84ca47fe4c30f46d451c78c079b804d9))
- fingerprinting: a site with its own set follows a change of the general set at once (#410) ([aede8f29a37d](https://github.com/nulavio/nulavio/commit/aede8f29a37d4ab30f5fca97dd5263340d1bfc99))
- release: an older run's publish job cannot roll the repositories back (#418) ([2c1b9b38880e](https://github.com/nulavio/nulavio/commit/2c1b9b38880e33488ff504073ab4d8be2a57486e))
- vault: a refused unlock writes nothing into the volume (#432) ([55f4c5e84be3](https://github.com/nulavio/nulavio/commit/55f4c5e84be36e1f908ef9a43d984e1afcdcd486))
- vault: the key file of a profile being protected is saved once a stop can be undone (#433) ([ec3f93cf421f](https://github.com/nulavio/nulavio/commit/ec3f93cf421f833b8fe012f4db2f5d3102713014))
- vault: the lock between two protections of a profile counts only on the file its name points to (#480) ([8cf180d2d9e8](https://github.com/nulavio/nulavio/commit/8cf180d2d9e8af5f5cc960a0958ec26e2510671b))
- settings: the add-provider button keeps the provider's name for assistive tech only (#487) ([05ccf5319a8b](https://github.com/nulavio/nulavio/commit/05ccf5319a8ba7b46acb43a994a9e091e909f3dc))
- filter: pin uBlock Origin 1.76.4, past the element-picker XSS (GHSA-cmqw-9r2w-6wv2) (#416) ([40706ba272f3](https://github.com/nulavio/nulavio/commit/40706ba272f36ccec68621055a83068142efe131))
- profiles: a refused search choice in a new profile has its own message (#517) ([5b71ab627605](https://github.com/nulavio/nulavio/commit/5b71ab62760546a167cb18df2e870cc8aa00d247))
- ci: the Companion's Gradle steps run again when Maven Central rate-limits the runner (#518) ([bdf68ec9c313](https://github.com/nulavio/nulavio/commit/bdf68ec9c313b90e28bff94c10f18ea3642fd10e))
- ai: an address agents never act on is refused before the tool's own question (#520) ([b4885d7b9a45](https://github.com/nulavio/nulavio/commit/b4885d7b9a450ce38d413af271434adf9861aef3))
- ci: the Gradle retry waits 2 and then 5 minutes (#536) ([425d80cf7dfa](https://github.com/nulavio/nulavio/commit/425d80cf7dfa48af9de0de3f9f0fd758312718e8))

### Documentation

- release: what is new in 160.0-0.7, as main stands (#422) ([a1e534f14a18](https://github.com/nulavio/nulavio/commit/a1e534f14a1819334b88c2b0078c9b68d67a2059))
- review: every reviewer reads the security invariants from REVIEW.md (#424) ([55c0ccbc7ddd](https://github.com/nulavio/nulavio/commit/55c0ccbc7ddd9252165e23d806970ec0e483d664))
- security: the changelog entries for 160.0-0.5 and 160.0-0.6 (#426) ([9f471442f25c](https://github.com/nulavio/nulavio/commit/9f471442f25cbd4af463577e89cf45e0c65e06dc))
- vault: a lost record is restored from a backup, and the page says how to make one (#429) ([52d910b0f1f0](https://github.com/nulavio/nulavio/commit/52d910b0f1f0475b72c14703469fcb79070d0193))
- release: the independent review's summary is in the release criteria (#441) ([549e30c1fbbb](https://github.com/nulavio/nulavio/commit/549e30c1fbbb54582a87b8e0a78efab52aecd06e))
- product: review every feature before the 1.0 freeze, with a recommendation each (#456) ([4bbf2133a5b1](https://github.com/nulavio/nulavio/commit/4bbf2133a5b12254d171f34a8f88e2bc2d48dfe1))
- product: the feature review says its milestones and closures are applied (#471) ([a5b3081206e2](https://github.com/nulavio/nulavio/commit/a5b3081206e21274e9f9e829dcdcac0f00cdddac))
- research: the first video call record, Jitsi Meet as a guest with no account (#477) ([901a1f39eed0](https://github.com/nulavio/nulavio/commit/901a1f39eed00aa4b656712152bb969c3a6d5625))
- performance: the first build with cross-language LTO, measured (#479) ([29f2dee61efb](https://github.com/nulavio/nulavio/commit/29f2dee61efbde91846b1656c7df7242f1427ebb))
- what the LTO build is against Mozilla's, where the reading's compiler comes from, and why Jitsi offered no end-to-end encryption (#485) ([819d5259ff9f](https://github.com/nulavio/nulavio/commit/819d5259ff9f03be42269d4c9f3370f067f6140f))
- process: the Actions event policy that keeps the AI review running (#499) ([a032ac09fd28](https://github.com/nulavio/nulavio/commit/a032ac09fd28d9273c5462faf2e45e80d678260d))
- confined mode is out of 1.0's promise until a package can start it (#515) ([1fd3941d150a](https://github.com/nulavio/nulavio/commit/1fd3941d150a9cfd2a47b4d3e2809376820983eb))
- perf: a new profile's first minute is uBlock Origin compiling its lists (#510) ([a6c1e587a2aa](https://github.com/nulavio/nulavio/commit/a6c1e587a2aac86056742d46dcd9b804bd1271dc))

### Tests

- tabs: the engine's tab groups checked in the Nulavio build, per arrangement (#395) ([59ef65f32890](https://github.com/nulavio/nulavio/commit/59ef65f32890a2e56c70f3ee51eb8f2949a67fb1))
- split-view: the engine's split view checked with the band, Imersivo and both arrangements (#396) ([e7b7e2388936](https://github.com/nulavio/nulavio/commit/e7b7e2388936e78a289678b8617cfb325e84d52e))
- fingerprinting: a weekly check that PrivacyTests' probes are the ones copied here (#399) ([b82245423752](https://github.com/nulavio/nulavio/commit/b8224542375202e826829b877fbb4fc03b231b02))
- Settings' navigation never shows a pane with nothing to use (#407) ([dde32d4a20e6](https://github.com/nulavio/nulavio/commit/dde32d4a20e6fc1b09f6a51837a6d166a0c4b319))
- routing inside a split view, its menu in both languages, and where to read about it (#408) ([57dabe72090b](https://github.com/nulavio/nulavio/commit/57dabe72090bd8569fffdc845acb5193d8396878))
- two tests that failed once in a whole-suite run wait or allow for rounding (#409) ([84be37ed63f0](https://github.com/nulavio/nulavio/commit/84be37ed63f034e9986ccbb0b6e7157d18daf199))
- tab groups come back from the closed groups and after a restart, and keep through Imersivo (#414) ([9f1bd1dc602d](https://github.com/nulavio/nulavio/commit/9f1bd1dc602d94118fcaab7dccd05e625fd07cd9))
- a wait for a page to be ready survives the moment the document has no root (#435) ([ce649092bac0](https://github.com/nulavio/nulavio/commit/ce649092bac07f7a1c6c2f88dd31fff877058ae4))
- split view and load line wait for what they read, and one slow test leaves nothing to the next (#439) ([0afb537cece4](https://github.com/nulavio/nulavio/commit/0afb537cece4b5e80a04f18cfe89c2b41ec00bc3))
- allow-copy: after the switch, wait for the reloaded page and not for the one that is leaving (#445) ([517afb6f88de](https://github.com/nulavio/nulavio/commit/517afb6f88def17fcf7834b8564673145ff66787))
- content-filter: wait for uBlock Origin to say it loaded its lists again (#474) ([51d5d2ad29be](https://github.com/nulavio/nulavio/commit/51d5d2ad29be242849829fb53083a72138150b0e))
- drm: the Widevine stream must play past its clear start, and stop there without a licence (#475) ([f5c3ca0f6d0b](https://github.com/nulavio/nulavio/commit/f5c3ca0f6d0b9d797dfef4461fd409f9b96f538d))
- drm: each step of the ClearKey playback has a name and a limit (#476) ([43a41674cd05](https://github.com/nulavio/nulavio/commit/43a41674cd05e88b34f048fa92f90b2f8d35277d))
- engine: the sandbox check says why it cannot run in an AddressSanitizer build, and only there (#489) ([db53a39659f2](https://github.com/nulavio/nulavio/commit/db53a39659f2840b587bcf9b9ffe2dd6fdb7ba27))
- temporary: close the temporary instance once its window is up (#496) ([5cae029ef7d6](https://github.com/nulavio/nulavio/commit/5cae029ef7d6d9ecb58543fd86647cc14bbda3e8))

### Maintenance

- release: record v160.0-0.6 (#425) ([3f63d3440a71](https://github.com/nulavio/nulavio/commit/3f63d3440a71ede7c43a561f3c0ed5bdfae22daa))
- brand: remove the raw-automation tokens left after #463 (#521) ([419967a45604](https://github.com/nulavio/nulavio/commit/419967a4560488c3cd44c17d2e604cd6d494fcf8))

### Build and CI

- engine: Firefox 160.0.1, urgent security update (mfsa2026-130) (#524) ([c0d31d6447e6](https://github.com/nulavio/nulavio/commit/c0d31d6447e6a161533d27d1f840a745d00ce721))

[Full changelog](https://github.com/nulavio/nulavio/compare/v160.0-0.6...419967a4560488c3cd44c17d2e604cd6d494fcf8)

### Install and verify

Install or upgrade on Fedora or Ubuntu: https://nulavio.net/en/download/

On Ubuntu, `nulavio.sources` from the download page has the SHA-256 `f77857a1515bcf9cb07a5e213f0525e36784e1d47bafb700f9d3e158fc537745`.

Nulavio Companion, the Android app for phone unlock: `nulavio-companion-0.1.0.apk`. Its signing certificate's SHA-256 is `d78d255ac7d83cc3e70d946921a5921c76dd92d9b865fcd12893b36d2ae9d3be` (`apksigner verify --print-certs nulavio-companion-0.1.0.apk` prints it).

Every release asset is listed in `SHA256SUMS`, signed in `SHA256SUMS.asc` (key `298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1`): check that first, as the download page shows. Each also has a GitHub build-provenance attestation from the release workflow on `main`; check it with both of these options:

```sh
gh attestation verify <file> --repo nulavio/nulavio \
  --signer-workflow nulavio/nulavio/.github/workflows/release.yml --source-ref refs/heads/main
```

[Build and test run](https://github.com/nulavio/nulavio/actions/runs/44252459660).

[Security changelog](https://github.com/nulavio/nulavio/blob/main/docs/security/changelog.md) and [published advisories](https://github.com/nulavio/nulavio/security/advisories). Commit categories are not a vulnerability assessment.


<!-- release:v160.0-0.6 -->
## [160.0-0.6](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.6) — 2026-11-16

Nulavio 160.0-0.6, built from Firefox 160.0 (commit 7b94d699d48b).

### What's new

An update of the alpha with the same engine (Firefox 160.0): the whole browser can sit behind a password, sites get less to recognise your computer by, the Immersive mode works better in real use, and protected profiles and each version's checks are stricter.

#### Changes that need your attention

- Sites now see universal time (UTC) in place of your time zone, which helps recognise you from one site to the next. Hours a page works out by itself, as in calendars, chats and statements, show in UTC.
- For a site that needs the right hour, open the shield in the address bar and turn on Use my time zone on this site. The choice is kept in Settings, with the other site exceptions.

#### What is new

- Every profile can be protected by a password: the last unprotected profile can be removed, and the profile chooser is then the only way in.
- Sites read the same screen, 1920 by 1080, and 4 processors on every computer. The window's size does not change, and a site exempted with the shield reads the real values.
- After an update, a bar offers what is new in the version, and the Help menu has an entry for it.
- Ctrl+Shift+L copies a link to the selected text.
- Meeting links, per profile: with Join in the browser, Zoom and Microsoft Teams links stay on the service's page and no app is opened. It is in Settings, Integrations.
- When you sign in to Google in a profile of a group, a bar offers, once, to always open Google's sites in that profile.
- The Immersive mode has a pin that keeps the toolbar and the tabs in view, shows the tab list for a moment when a tab opens in the background, and gives a very long site name a line of its own.
- Clean links drop eleven more tracking parameters, from Google's ads, Instagram, Reddit, Facebook, X and others.

#### Fixes

- A protected profile refuses to open when its record of unlock-method changes is missing, and says what to restore from a backup.
- Each version's notes give a stricter command to check where a download was built: it names the release workflow and the main branch.
- The Flatpak bundle is checked file by file against the attested archive before it is signed.
- In the Immersive mode, the toolbar no longer covers the tab list or the Assistant's panel, the page does not shift in Focus, and a dragged tab keeps the tab list open.
- On KDE, the profile button keeps its contrast after the system changes between light and dark with the browser open.
- The Guard's review page updates by itself when a finding changes, and a replaced extension shows the version the browser took in.
- A profile unlocked from the phone is locked again when its lock watcher cannot start, and the watcher no longer misses a browser that closed within half a second.
- After a change to the unlock methods, the protected profile's pages show the result even when the state cannot be read again.
- Started with the confined option on a system where the browser could not sandbox page content inside it, such as Ubuntu by default, Nulavio refuses to start and says why, instead of running with less protection.
- Nulavio removes one more environment variable that weakens the engine's sandbox before the browser starts, and the doctor command says when it is set.
- A window density fixed by an administrator shows as fixed in Settings.

In Portuguese and English: https://nulavio.net/novidades/160.0-0.6/ and https://nulavio.net/en/whats-new/160.0-0.6/

### Features

- profiles: every profile behind a password, with the chooser as the only way in (#289) ([64e2348f7816](https://github.com/nulavio/nulavio/commit/64e2348f78163b980ea828eea03b3c20e11d6800))
- prefs: clean links drop the tracking parameters the engine's lists miss (#309) ([eb452e389412](https://github.com/nulavio/nulavio/commit/eb452e38941262db8c84eeb5cff7983c66997c2f))
- shell: Ctrl+Shift+L copies a link to the selected text (#329) ([ab0ed735694b](https://github.com/nulavio/nulavio/commit/ab0ed735694ba9647e4f9bfb5025584676715207))
- shell: Immersive gets a pin for touch, and shows a tab opened in the background (#335) ([b05c1fa0200b](https://github.com/nulavio/nulavio/commit/b05c1fa0200be6c22c569217c4ea822dd1d08b17))
- shell: in Immersive a site too long for the band's row gets a line of its own (#342) ([60da0b269e2d](https://github.com/nulavio/nulavio/commit/60da0b269e2dc4afd1eb0b9d9cb676ade188bb37))
- shell: routing rules for Google's sites offered when the person signs in to Google in a profile (#350) ([ec029ba886fd](https://github.com/nulavio/nulavio/commit/ec029ba886fd433c4a5ec79f629521a4725f157f))
- perf: one command measures startup and memory against a baseline build (#353) ([1b00ed654376](https://github.com/nulavio/nulavio/commit/1b00ed654376a3f330f1f356604461b87fcae14d))
- perf: Speedometer 3.1, pinned and served from this machine (#354) ([2f497f9c4f1d](https://github.com/nulavio/nulavio/commit/2f497f9c4f1dc4401d6c66b2442c318a22d5d704))
- perf: JetStream 3.0 and MotionMark 1.3.2, pinned and served from this machine (#357) ([09a1843e5c34](https://github.com/nulavio/nulavio/commit/09a1843e5c342a7830a7ec7920f772503bcef58d))
- perf: frame time from the same command, on a private Xvfb (#358) ([72c34d0e8138](https://github.com/nulavio/nulavio/commit/72c34d0e8138c7dac6673b280ebb969f765c370b))
- perf: stock Firefox 160.0 as a second baseline, pinned to Mozilla's archive (#359) ([4ed5f12a3fc8](https://github.com/nulavio/nulavio/commit/4ed5f12a3fc85c09609b6c10d6ab5335dbc797d2))
- perf: a 95 % bootstrap interval for each change (#360) ([f90fc7caacfb](https://github.com/nulavio/nulavio/commit/f90fc7caacfbba17b83e428ab0f6d96a1ca35778))
- perf: measure each published release against the one before it and Firefox (#363) ([df5e937f5cc4](https://github.com/nulavio/nulavio/commit/df5e937f5cc48a52fa3fd1adf3869ddcaa8d51e4))
- perf: the tools CLI and the fingerprinting protections' cost from the same command (#366) ([5e289a2e9050](https://github.com/nulavio/nulavio/commit/5e289a2e90503006c7210a2db42428d5292207b7))
- shell: meeting links open in the app or join in the browser, per profile (#343) ([1016f9000d57](https://github.com/nulavio/nulavio/commit/1016f9000d5743d77c73961512be5809dca4be4b))
- fingerprinting: pages read one screen size and one processor count on every computer (#375) ([aa3590b6d1eb](https://github.com/nulavio/nulavio/commit/aa3590b6d1eb4fb5117eca72e14b63040bc57064))
- fingerprinting: pages read UTC as the time zone, with a switch per site in the shield's panel (#379) ([9bde32867450](https://github.com/nulavio/nulavio/commit/9bde32867450657a6c6fa821ba822202437d6a73))

### Fixes

- the rest of the experience follow-ups (cookie notices, the band, tests that switched HTTPS-Only off) (#287) ([81e94bdf4dad](https://github.com/nulavio/nulavio/commit/81e94bdf4dad6b02a857e6c9ac7bb5873b40d79d))
- shell: what's new starts with the browser: SessionStore from the address the engine has (#306) ([445192aea483](https://github.com/nulavio/nulavio/commit/445192aea483082d7c4836617d4190ff1e458eb2))
- release: the Companion job validates the Gradle wrapper and refuses an app changed without a new version (#299) ([3dcb1af0ba2e](https://github.com/nulavio/nulavio/commit/3dcb1af0ba2ee6ede32f78255e6212c358535057))
- vault: the lock watcher sees an engine that lived under half a second (#303) ([f9e483ac6a6d](https://github.com/nulavio/nulavio/commit/f9e483ac6a6d72deba02167b528f4c211d94ae75))
- launcher: --confined refuses to start where the engine could not sandbox its content inside bubblewrap (#295) ([a8e09b9a7a40](https://github.com/nulavio/nulavio/commit/a8e09b9a7a40388919d02612c60f27c3fd32a7e1))
- release: sign\_repo.sh and sign\_apt\_repo.sh verify the rehearsal before they sign (#298) ([a812a118db66](https://github.com/nulavio/nulavio/commit/a812a118db6699566917b716212e5cdbee60ebc8))
- shell: a density an administrator fixed reads as fixed in Settings (#302) ([f626623e2b41](https://github.com/nulavio/nulavio/commit/f626623e2b41e5fe0af7ff489b4f0c7ee87946e0))
- vault: the lock watcher's fallback allows the kernel's coarse file clock (#314) ([e68d02e963fe](https://github.com/nulavio/nulavio/commit/e68d02e963fe2f9794eb9dcb68b2a3e0538b2c41))
- shell: the vault pages keep a change's result when the state cannot be read again (#308) ([d6978110c7fe](https://github.com/nulavio/nulavio/commit/d6978110c7fea8e7c21fa06a5d2e7e7ab3b3892c))
- vault: a phone unlock locks the profile again when its watcher cannot start (#330) ([7d6b49e00d8c](https://github.com/nulavio/nulavio/commit/7d6b49e00d8cf7c1c5388ea3cdb187b04b0c39ec))
- release: the check after upload compares the served dnf repository file whole (#331) ([a7df2e5e5014](https://github.com/nulavio/nulavio/commit/a7df2e5e5014493bec8432f2073621dbfdc128bc))
- release: the signing role's session leaves the publish job once it has signed (#332) ([02107a1b364f](https://github.com/nulavio/nulavio/commit/02107a1b364f6be6f817941e8c4a1dc53f064388))
- launcher: the engine starts without MOZ\_ASSUME\_USER\_NS, and doctor says when it is set (#333) ([a142f9ca2e14](https://github.com/nulavio/nulavio/commit/a142f9ca2e14cdf676ec4bd4ac346d27a96a8ec4))
- release: the Flatpak bundle is checked against the attested archive before it is signed (#338) ([f16063f44d66](https://github.com/nulavio/nulavio/commit/f16063f44d661b49824039420021bdeff350a444))
- guard: a waiting finding says the version the engine took in after the start-up check (#341) ([a3dfaa1b6625](https://github.com/nulavio/nulavio/commit/a3dfaa1b66256cf901a25e06714b8ba30b330458))
- guard: the review page redraws when a finding changes while it is open (#352) ([5786cbaad6ed](https://github.com/nulavio/nulavio/commit/5786cbaad6ed962ba995d56ffbbfe6b1ac211f7a))
- shell: in Immersive the toolbar covers neither the tab list nor the assistant, and a dragged tab keeps the list (#355) ([f07a873e48bc](https://github.com/nulavio/nulavio/commit/f07a873e48bcf991af241c40edca1809d3fffc12))
- perf: memory is read in a third start and only once two readings agree (#361) ([371269024479](https://github.com/nulavio/nulavio/commit/371269024479e028babbe5f70957a22efc948c53))
- shell: the profile button follows a desktop's live scheme change (#369) ([6bb714023d32](https://github.com/nulavio/nulavio/commit/6bb714023d329397e370f8991fbb15cf4ed2ad6d))
- release: the upload runs in a job that cannot take the signing role (#356) ([cc1bb14342fe](https://github.com/nulavio/nulavio/commit/cc1bb14342fe727a33ee19a3fcc2f12ef92cb054))
- harden the release notes' attestation check and the Vault's generation record (#370) ([3a5dece8c545](https://github.com/nulavio/nulavio/commit/3a5dece8c5457b58fe8a3b5a0c5632f6867ec366))
- release: the signing role trusts the two signing workflows on main, not any job of the environment (#372) ([c4567628b4f8](https://github.com/nulavio/nulavio/commit/c4567628b4f89531d5a618740714a02568be45ed))
- release: the release run's integration tests pass on a build of a new version (#376) ([05956707afee](https://github.com/nulavio/nulavio/commit/05956707afee77e7ade439b20c34b14741a5cfad))
- fingerprinting: only pages of the web, in tabs, read the constant screen, and an open page follows the switch (#382) ([7b94d699d48b](https://github.com/nulavio/nulavio/commit/7b94d699d48b91cd8b3422c4a63a1039ca6b278d))

### Documentation

- security: the scope packet for the independent review of the Vault and the release chain (#294) ([e39a4ac3c029](https://github.com/nulavio/nulavio/commit/e39a4ac3c0292e04b2064e7bb4a726ab8482a9ce))
- security: what Google still sees when you sign in to its services, and what is allowed on other sites (#307) ([cf0bdf733005](https://github.com/nulavio/nulavio/commit/cf0bdf733005539475e62e355df01652014d4f50))
- design: the maintainer's mockup of Imersivo "Faixa" as the spike's reference (#349) ([8884a072b947](https://github.com/nulavio/nulavio/commit/8884a072b947a51d65368f6c46c623d39ca674c9))
- perf: the suite, its method and the first published baseline against Firefox 160.0 (#365) ([c4fefbb81d84](https://github.com/nulavio/nulavio/commit/c4fefbb81d84ada88be5b73b3ab3b4386eaa3da1))
- release: what is new in 160.0-0.6 (#373) ([38ddc81845e1](https://github.com/nulavio/nulavio/commit/38ddc81845e1a01e03b2eb930984b659ece2111e))
- release: 160.0-0.6's notes name the fingerprinting changes it ships (#383) ([39afecfa19be](https://github.com/nulavio/nulavio/commit/39afecfa19be482978748ee56f38c20605004ca5))

### Tests

- the clock-step test waits for its stand-in engine to finish starting (#297) ([f26201b07483](https://github.com/nulavio/nulavio/commit/f26201b07483880e2a9df32a16d0d8c9924ae4c8))
- Copy Link to Highlight in the Nulavio build, and where to read about it (#300) ([43c313f41882](https://github.com/nulavio/nulavio/commit/43c313f41882aeaa2e3f19e16957f4db945ccedd))
- calls work with Nulavio's prefs: a WebRTC call on this computer carries audio and video (#311) ([03ef3af41223](https://github.com/nulavio/nulavio/commit/03ef3af4122348504c64722e6d9d9b571742d293))
- the text-fragment test reads the highlight from the page, and waits for the menu to close (#313) ([bcb02e4744b5](https://github.com/nulavio/nulavio/commit/bcb02e4744b531ff4b18a3ad728256d3f7e94fba))
- protected media plays in the Nulavio build once DRM is on, and a site's DRM storage clears with its data (#310) ([3832b802d3d6](https://github.com/nulavio/nulavio/commit/3832b802d3d60d6df626641b7e61df42c6c76865))
- fuzz the nv1 messages and the AI Bridge's address classifier with Hypothesis (#305) ([dfc5de2b417b](https://github.com/nulavio/nulavio/commit/dfc5de2b417bc4331b3da1a2f2c95156b09c4abf))
- guard: another signed version put in place while closed is reported (#336) ([637bd545d4bd](https://github.com/nulavio/nulavio/commit/637bd545d4bd4bc33fbb89b68c473304c78471a4))
- drm: Widevine installs and a public test stream plays; the bar and the setting are there (#340) ([6bd2506bc0e9](https://github.com/nulavio/nulavio/commit/6bd2506bc0e9889b33b0543f62c7a4e60f34fb16))
- content-filter: Google's analytics, tag manager and ad tags on another site load nothing (#339) ([1ae7b0583755](https://github.com/nulavio/nulavio/commit/1ae7b0583755f18a44b9061ac2aadb714754fcf0))
- fingerprinting: PrivacyTests' 25 probes run on the Nulavio build with their pass rule (#374) ([554208990df6](https://github.com/nulavio/nulavio/commit/554208990df6ab24e489f4078f8a9d98ad82cb50))
- clean-links: the menu opens once the engine has read its clean-link lists (#381) ([6ae7deae247e](https://github.com/nulavio/nulavio/commit/6ae7deae247e57c27ee9cb0d330f775db68f218c))

### Maintenance

- release: record v160.0-0.5 (#304) ([30e3ba941373](https://github.com/nulavio/nulavio/commit/30e3ba9413732c7b2062dbc349284109a40e5ed8))

### Build and CI

- ai-review: send a pull request to the model only when it touches a CODEOWNERS path or carries the ai-review label (#296) ([3267fa5af450](https://github.com/nulavio/nulavio/commit/3267fa5af450c358f475bf5d8676d590ee0c0763))
- ai-review: call the Messages API from a standard-library script instead of Claude Code (#301) ([4ff8867c8189](https://github.com/nulavio/nulavio/commit/4ff8867c8189af9c9953db1354da45df2286c707))

[Full changelog](https://github.com/nulavio/nulavio/compare/v160.0-0.5...7b94d699d48b91cd8b3422c4a63a1039ca6b278d)

### Install and verify

Install or upgrade on Fedora or Ubuntu: https://nulavio.net/en/download/

On Ubuntu, `nulavio.sources` from the download page has the SHA-256 `f77857a1515bcf9cb07a5e213f0525e36784e1d47bafb700f9d3e158fc537745`.

Other distributions, with Flatpak:

```sh
flatpak install --user nulavio-160.0-0.6.x86_64.flatpak
```

Nulavio Companion, the Android app for phone unlock: `nulavio-companion-0.1.0.apk`. Its signing certificate's SHA-256 is `d78d255ac7d83cc3e70d946921a5921c76dd92d9b865fcd12893b36d2ae9d3be` (`apksigner verify --print-certs nulavio-companion-0.1.0.apk` prints it).

Every release asset is listed in `SHA256SUMS`, signed in `SHA256SUMS.asc` (key `298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1`): check that first, as the download page shows. Each also has a GitHub build-provenance attestation from the release workflow on `main`; check it with both of these options:

```sh
gh attestation verify <file> --repo nulavio/nulavio \
  --signer-workflow nulavio/nulavio/.github/workflows/release.yml --source-ref refs/heads/main
```

[Build and test run](https://github.com/nulavio/nulavio/actions/runs/43811410472).

[Security changelog](https://github.com/nulavio/nulavio/blob/main/docs/security/changelog.md) and [published advisories](https://github.com/nulavio/nulavio/security/advisories). Commit categories are not a vulnerability assessment.


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
gh attestation verify <file> --repo nulavio/nulavio \
  --signer-workflow nulavio/nulavio/.github/workflows/release.yml --source-ref refs/heads/main
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
gh attestation verify <file> --repo nulavio/nulavio \
  --signer-workflow nulavio/nulavio/.github/workflows/release.yml --source-ref refs/heads/main
```

[Build and test run](https://github.com/nulavio/nulavio/actions/runs/43534834214).

[Security changelog](https://github.com/nulavio/nulavio/blob/main/docs/security/changelog.md) and [published advisories](https://github.com/nulavio/nulavio/security/advisories). Commit categories are not a vulnerability assessment.


<!-- release:v160.0-0.3 -->
## [160.0-0.3](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.3) — 2026-11-11

Nulavio 160.0-0.3, built from Firefox 160.0 (commit 123b12def4eb).

Install or upgrade on Fedora: https://nulavio.net/en/download/

Every file here is signed (SHA256SUMS.asc, key 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1) and has a GitHub build-provenance attestation:

    gh attestation verify <file> --repo nulavio/nulavio \
      --signer-workflow nulavio/nulavio/.github/workflows/release.yml --source-ref refs/heads/main

Built and tested by run https://github.com/nulavio/nulavio/actions/runs/43102367281.

