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

## Unreleased (on `main`, after 160.0.1-0.2)

**Nulavio fixes**:

- AI Bridge, local network, continued (#243, #560):
  - In your own profiles opened for an agent, the engine's Local Network Access now refuses a public page's requests to local addresses with no prompt, a pop-up's included. This holds for the agent's run only, and none of these settings stays in the profile.
  - A page the agent itself opens, or that a redirect on its way leads to, is not shown when it comes from an address the engine reads as local and the agent may not reach that place. The engine knows the address only once it has connected, so that request has been sent and the local service still receives it (R29).
  - For that check, the agent's engines never take a top-level page from the cache: it is fetched, or not shown.
  - A page loaded through a proxy is not checked this way, and in your profiles a site you allowed yourself to reach local addresses keeps that permission; R29 lists what else is not.
  - Engine patch 0015 (#561): in the engines an agent drives, a page the agent opens at this computer or the local network, a redirect hop's and a new tab's included, is now refused before the request is sent, unless the agent may reach that place then. The engine still connects to that address, and the tab shows a blocked page. A page loaded through a proxy is not checked this way either (R29).
  - Nothing to do: it comes with the update.

## Nulavio 160.0.1-0.2 (Firefox 160.0.1), published 2026-11-19

A Nulavio release on the same engine ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0.1-0.2), [run 44442004774](https://github.com/nulavio/nulavio/actions/runs/44442004774)), built from `main` at `be6d3ea3`. The first run, from `8d265dc8` (run 44418820464), stopped twice on `test_downloads_indicator` 01: a second read after its wait, which #567 fixed. The run from `be6d3ea3` stopped once on `test_tab_groups` 05, the order of a restored group's tabs, which passed on the rerun. In the same attempt the Companion's Gradle steps could not resolve dependencies from Maven Central, and that job also passed on the rerun. At the maintainer's request in chat, the agent dispatched the run, gave the `release` environment's approval and published the draft. It published only after checking `SHA256SUMS.asc` against the published key (`298A 9093 … 8DB1`) and every asset against `SHA256SUMS`. `scripts/release/AGENTS.md` leaves those steps to the maintainer, who asked for this exception, as for 160.0.1-0.1.

**Upstream**: unchanged, Firefox 160.0.1.

**New protections and their limits**:

- Extension advisories (#415): the daily watch reads the security advisories that uBlock Origin's, KeePassXC-Browser's and Bitwarden's repositories publish on GitHub, and fails at once when one covers the version Nulavio pins (uBlock Origin's GHSA-cmqw-9r2w-6wv2 was the case that was missed: the pin moved in #416). It does not cover Proton Pass or 1Password, which publish no machine-readable advisories (R84), and a vendor's unpublished fix is not seen. It is a maintainer-side alert: users get a pinned extension's fix as a new Nulavio build, and, as the extension updates itself from AMO, usually sooner.
- Automatic updates (#241): the RPM and .deb packages carry a timer and a service that update only the `nulavio` package, at midnight and noon, as root: with dnf from Nulavio's repository only, with APT from the highest version among the system's sources (R83). They do nothing until the person turns them on, which asks for the administrator's password through polkit; nothing runs at install ([TB24](../architecture/trust-boundaries.md), S24). The switch is in Settings and on the first run, which offers it once; the browser runs the helper through `pkexec`, and a person without a polkit agent gets the command to type instead.

**Nulavio fixes**:

- AI Bridge, engine lookup (#563, [advisory GHSA-95h5-h3m4-3jhv](https://github.com/nulavio/nulavio/security/advisories/GHSA-95h5-h3m4-3jhv), medium): on a package install with a distribution Firefox present, an agent connected from Settings got its AI Workspace in that Firefox, without the Nulavio Shell (the agent window's band and lock, the forms guard), uBlock Origin or the engine patches; the user's own profiles opened for an agent too. The tools installed with Nulavio now use the engine of their own install, and the Bridge drives only the Nulavio build. Nothing to do: it comes with the update, and an agent already connected needs no new configuration. The advisory was published on 2026-11-19.
- AI Bridge, local network (LESIS 929cb094, high; #243): a page an agent opened could reach this computer or the local network through a name that answered the Bridge's DNS lookup with a public address and the engine's with a local one (DNS rebinding), with no `local_resources` grant; R29 listed it as not held. In the AI Workspace the engine's own Local Network Access, which decides on the address it connects to, now refuses a public page's requests to local addresses with no prompt, a pop-up's included. Not covered yet (R29): a rebinding name the agent itself opens, or a redirect on its way, and your own profiles opened for an agent. Nothing to do: it comes with the update.

**Removed**:

- Fingerprinting: the 1920×1080 screen comes from the engine alone (patch 0012's `ScreenSizeConstant`, in the build's set of protections); the Shell no longer sets a screen size per tab (#468, [ADR 0016](../adr/0016-one-screen-size-and-processor-count-for-pages.md#one-mechanism-since-468)). Nothing changes with the build's set, also while "Deixar os sites verem minhas preferências de movimento e contraste" is on. A profile whose set the person wrote themselves in `about:config` without `+ScreenSizeConstant` read the constant through the Shell until 160.0.1-0.1 and reads the display's size from this version on (where the set has the engine's own `+ScreenRect`, `+ScreenAvailRect` or `+CSSDeviceSize`, the value that entry covers is the window's inner size, as before; the values it does not cover read 1920×1080 before and read the display's now): add the entry to `privacy.fingerprintingProtection.overrides`, or reset the preference ([R56, R78](residual-risks.md)). Such a set can now also turn the screen's protection off, which it could not before.

## Nulavio 160.0.1-0.1 (Firefox 160.0.1), published 2026-11-18

The urgent engine update ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0.1-0.1), [run 44252459660](https://github.com/nulavio/nulavio/actions/runs/44252459660)), built from `main` at `419967a4`, which also carries what landed after 160.0-0.6 (below). The engine pin landed in #524 after the laptop pre-check of 160.0.1 (networking check passed; integration 641 of 643, the two failures timing races in the tests that passed alone, #526). The first attempt of the release run stopped on two integration tests whose navigation timed out (`test_layout_presets`, `test_window_frame`; `main`'s CI skips both, which need the built-in Shell, and both passed in `main`'s scheduled rehearsal of the same commit, run 44283732010, which stopped on three `test_web_services` tests that passed here); the second was cancelled while it was only slow (its build took 83 minutes instead of 15); the third passed every step. At the maintainer's request in chat, the agent dispatched the run, gave the `release` environment's approval and published the draft (after checking `SHA256SUMS.asc` against the published key): `scripts/release/AGENTS.md` leaves those steps to the maintainer, who asked for this exception. Signing through KMS ended at 11:05 UTC, the packages were uploaded and installed from the site's repository files in clean containers by 11:11 UTC, and the GitHub release was published at 11:51 UTC.

**Upstream**: Firefox 160.0.1, released by Mozilla 2026-11-17 14:06:53 UTC ([mfsa2026-130](https://www.mozilla.org/security/advisories/mfsa2026-130/), high). Urgency: urgent (an advisory of high impact; not exploited in the wild, no public exploit code). Source SHA-256 `7b9d95ddf24f7bbf5d0d05698bc02a66dac1eca438f80e093c5c76af7648b06d` (Mozilla's signed SHA256SUMS, subkey `827E658608679618CD349F93678E455D76767AA3`). 160.0.1-0.1 carries it (#444, #524).

**Timing**

| Mozilla's release | Detected | Ready to sign | Published | Target | Deadline |
|---|---|---|---|---|---|
| 2026-11-17 14:06:53 UTC | staged, by the `upstream` workflow, −14.6 h (#444 opened 2026-11-16 23:31 UTC); published seen +8.6 h | 2026-11-18 10:58 UTC, +20.9 h (rehearsal of the third attempt: build, unit, 633 integration tests with 30 skipped, RPM, .deb, signed-repository and KMS checks, 71 min) | 2026-11-18 11:51 UTC, +21.7 h (packages in the repositories at 11:11 UTC) | 24 h (2026-11-18 14:06 UTC): met | 72 h (2026-11-20 14:06 UTC): met |

**New protections and their limits**:

- Fingerprinting: what a page renders as audio offline differs per site (engine patch 0012, [ADR 0019](../adr/0019-rendered-audio-differs-per-site.md), #79). The usual audio probe then reads a different value on every site and the same value again on one site. It covers the buffer an offline rendering returns: a probe that reads through a node inside the rendering (an analyser, a script processor, a worklet) or from sound that plays is not changed, and a script written against the noise can average it out (R56). Distribution Firefox (Track A) does not have the patch.
- Fingerprinting: the 1920×1080 screen is answered by the engine for each document, a frame, a pop-up and an image too (engine patch 0012, ADR 0016, #79). In 160.0-0.6 the size is kept per tab, which leaves the display's size readable in two corners (below, under 160.0-0.6).
- Fingerprinting: sites are not told that the system asks for less motion or more contrast ([ADR 0018](../adr/0018-sites-are-not-told-motion-and-contrast-preferences.md), #79). Sites then animate, and pages scroll smoothly, also for a person who asked the system for less motion, until they answer the bar that offers the setting once with "Deixar os sites verem", or turn on "Deixar os sites verem minhas preferências de movimento e contraste" in Settings; with it on, those answers (motion, contrast and reduced transparency) tell them apart again (R56).
- Translation with a web service (#156): none is used until the person adds one, and then only on a click on a menu item that names it; it receives the selection or the page's address without its fragment, never an address of this computer or a local network as far as its form shows ([web services](../architecture/web-services.md), TB23, S23). What a site puts in its own query still goes to the service with the address (R80).
- Passwords (#81): 1Password can be chosen as the credential provider. Its official extension is pinned and installed only when chosen; its desktop app talks to it through its own native-messaging host. For the Nulavio build, `nulavio doctor` gives the step that lets the app accept the browser (a line in `/etc/1password/custom_allowed_browsers`, which Nulavio never writes), only when root alone can change the engine, since the line trusts the name ([R82](residual-risks.md)); whether the app refuses a browser binary root does not own, as in a tarball, was not measured. The extension's required `privacy` permission is R81.
- Search (#151): a new profile can start with the search provider chosen when it is created. The creating profile writes one file into the new profile's folder (a provider of the curated list, mode 0600, never through a link), read at that profile's first start only and removed unread at any later start, so a file left in a profile that has run cannot change its search (TB13).

**Fixes**:

- Content filter: a new profile installed uBlock Origin 1.75.0, which has the element-picker flaw of [GHSA-cmqw-9r2w-6wv2](https://github.com/gorhill/uBlock/security/advisories/GHSA-cmqw-9r2w-6wv2) (high: a page on which a `prevent-xhr` or `prevent-fetch` filter answers with one of uBlock Origin's own resources could, after a click on it, add a trusted filter that runs script on any site), and kept it until its first add-on update check (#415). The pin is now 1.76.4, past the fix in 1.75.4. Profiles that check for add-on updates already have the fix; with add-on updates off, check that uBlock Origin is at 1.75.4 or later (Add-ons and themes).

- Profiles the launcher made (the preview's, and encrypted profiles made with `nulavio vault` from a source checkout): a profile the launcher made before a fingerprinting protection was added did not get it, with no message (#384). The launcher wrote the set of protections into a profile once. It now follows the baseline in a profile where nobody changed it, at the profile's next launch; a set the person wrote themselves is kept, and `nulavio doctor` names it with the value to set ([R78](residual-risks.md)). The Nulavio build was not affected: there the set is the build's default, or the one the Shell writes while "let sites see my motion and contrast preferences" is on, and the launcher leaves both alone.

- A site with "Usar meu fuso horário neste site" on kept the earlier set of fingerprinting protections until the browser restarted, when the set changed while it was open: turning "Deixar os sites verem minhas preferências de movimento e contraste" on or off did not reach that site (#405). The engine works out each site's own set when the per-site list is set, and not again; the Shell now hands it the list again after the general set changes.

- Release chain: the engine pin may only name, and a release may only be published from, a Firefox release whose Rust code passed the engine's networking check (no `recv`, `send` or resolver function imported, the engine's guard against Rust code going around a proxy). The check is read from a build made for it, by a script, and its record is in the repository; CI refuses a pin without it and signing refuses a manifest without it (#430, [build](../architecture/build.md#the-networking-check-on-rust-code)). The record is a statement by whoever ran the reading, and the maintainer may record a release as accepted without one, naming the issue where he said so; nothing checks that but the review of the pull request ([R79](residual-risks.md)). The build laptop's automatic pre-build of a new engine release is now this pre-check, and makes nothing that can be signed. A release does not rest on the record: a workflow makes the same reading on the build machine and attests it, and the signing job refuses a release without that attestation for its exact source, configuration and patch stack (#455; first exercised by 160.0.1-0.1). The attestation also names the Rust compiler its build used, and the release's manifest the one the release was built with: built with two compilers, the reading does not count for the release (#472).

- Build: the release build is linked with link-time optimisation across C++ and Rust, as Mozilla's own Linux builds are (#364). In such a build the engine skips its own check that Rust code imports no networking function, which ran in every release build up to 160.0-0.6. The reading above, made on another build of the same source, is what stands in its place; it does not read the binary that ships ([R79](residual-risks.md)).

- Release chain: re-running only the upload job of an older release run could put that release's signed dnf and APT metadata back in the bucket, with no approval, since the upload token moved to an environment without a reviewer (#417). The job now refuses, before it uploads, a release older than any tagged or drafted one or than what the bucket already serves; runs made before this change are covered only once their artifacts expire (7 days). No release run has been re-run since that change, so the bucket never held anything but the latest release.

- Vault, two fixes from the independent review (#224), neither of which exposed a secret: protecting an existing profile saved the key file before the files were encrypted, so a stop between the two (a kill, a power cut) left a profile that said it was protected, could not be opened, and still had its files in the clear; the key file is now saved once the step can be undone, and the next use of the profile undoes it and says so (#411). A profile an earlier version already left that way is not repaired by itself: it shows as protected and does not open. What to do: look inside the profile's `.vault` folder, and if it holds only `vault.json` and `vault.json.bak` (no `cipher` folder), remove that folder; the profile's files were never encrypted and are in its own folder as they were. A refused unlock wrote an empty directory into the volume it refused; it now writes nothing (#412). A third fix, from the work on #411: the lock that keeps two protections of one profile apart is on a file removed at release, so a run that waited for it and a run that started just then could both hold it; it only mattered when a first run had failed and been undone, three runs at once on one profile, and was not seen to happen. The lock now counts only on the file its name points to (#434).

**Removed**:

- The Track A preview, Nulavio's profile on the distribution's Firefox (#464, ADR 0001 amendment of 2026-11-17): `nulavio setup` and `run` refuse an engine that is not the Nulavio build, and its chrome theme is gone. People who used it move to the RPM or APT package; their profiles stay where they were, and the README gives the steps to bring bookmarks and passwords. R1, R4, R5, R12, R13 and R17 closed with it.
- The KRunner plugin (#461, ADR 0004 amendment of 2026-11-17): Nulavio no longer runs a session-bus service that any program of the user could call to open an address or a search in it, and R44 closes with it. The two files "Add to KRunner" wrote under the data folder (`krunner/dbusplugins/net.nulavio.krunner.desktop`, `dbus-1/services/net.nulavio.krunner.service`) stay until the person deletes them; the release notes give them.
- Raw automation (#463, ADR 0007 amendment of 2026-11-17): no tool hands an agent the AI Workspace's WebDriver BiDi endpoint any more, so nothing an agent does through the bridge escapes the per-call policy and the activity record (a program running as the user can still reach the workspace's automation port, AI-T17 and AI-T18). The browser's internal pages, which only its opt-in opened, are offered to no agent; an opt-in recorded by an earlier version grants nothing, and the agents' page says once that it was removed. R42 closed.

**Per-site choices that loosen a site's own rules (not a protection)**:

- "Permitir copiar e colar neste site" in the shield's panel (#160): off by default, kept per origin in the profile and listed in Settings' site exceptions. On, that origin's pages cannot cancel copy, cut, paste, the page menu or selection, so their own handlers for those events no longer run there (R76).

## Nulavio 160.0-0.6 (Firefox 160.0), published 2026-11-16

A security update of the alpha, with the same engine ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.6), [advisory GHSA-9hc4-cxv9-5wf2](https://github.com/nulavio/nulavio/security/advisories/GHSA-9hc4-cxv9-5wf2), [run 43811410472](https://github.com/nulavio/nulavio/actions/runs/43811410472)). The two findings came from the independent review of the Vault and the release chain (#224); the fix was prepared in the advisory's private fork and landed in #370. The release was approved by the maintainer and signed through KMS; the job then installed it in clean Fedora and Ubuntu containers from the site's repository files, with the signature checks on. The packages were in the repositories at 14:27 UTC and the GitHub release was published at 16:32 UTC. Three release runs before this one stopped on tests and on a failed download, none on the product (#376, #381; what that costs is #378).

**Upstream**: unchanged, Firefox 160.0.

**Nulavio fixes** (what a user does: on Fedora, `sudo dnf upgrade nulavio`; on Ubuntu, `sudo apt upgrade nulavio`; to check a download, the command in the release's notes):

| # | Severity | Area | Fix |
|---|---|---|---|
| F1 | Medium | Release chain | The notes told people to check a download with `gh attestation verify <file> --repo nulavio/nulavio`, which accepts an attestation from any workflow or branch of the repository. The notes and `CHANGELOG.md` now print the command with the release workflow and the `main` branch, and name `SHA256SUMS.asc` as the first check (#370). The notes of 160.0-0.3 to 160.0-0.5 were edited to the same command on 2026-11-16 |
| F2 | Low | Vault | A protected profile's record of which key file is current could be deleted without any key, after which an older `vault.json` with a removed secret opened the profile through Nulavio. A key file now says, in its authenticated part, that the volume has a record, and a missing record is refused (#370). What the record does not stop is R70 |

No release's files are known to have been replaced: on 2026-11-16 every asset of 160.0-0.3, 160.0-0.4 and 160.0-0.5 matched its release's signed `SHA256SUMS`.

Also fixed, found by the project's own reviews:

- Release chain: the upload runs in a job that cannot take the signing role, and signing in one that holds no upload token (#356); the signing role in AWS trusts the two signing workflows on `main`, not any job of the environment (#372, R60); the role's session leaves the job once it has signed (#332); `sign_repo.sh` and `sign_apt_repo.sh` verify the rehearsal before they sign (#298); the check after upload compares the served dnf repository file whole (#331); the Flatpak bundle is checked file by file against the attested archive before it is signed (#338, R75). The Companion's build validates the Gradle wrapper before the job that signs, and refuses an app changed without a new version (#299).
- Vault: a profile unlocked from the phone is locked again when its lock watcher cannot start (#330), and the watcher sees a browser that lived under half a second (#303, #314).
- Sandbox: started with `--confined` where the engine could not sandbox its content inside it (Ubuntu by default), Nulavio refuses to start and says why, where it ran with less protection before (#295, R46); one more environment variable that weakens the engine's sandbox is removed before the browser starts, and `nulavio doctor` names it (#333).

**New protections and their limits**:

- Every profile can be behind a password: the last unprotected profile can be removed, and the profile chooser is then the only way in (#289).
- Fingerprinting: pages read a 1920×1080 screen and 4 processors on every computer ([ADR 0016](../adr/0016-one-screen-size-and-processor-count-for-pages.md), #79). The window's own size still differs between people, and a window wider than that screen is a visible sign of the protection ([R56](residual-risks.md)). A site exempted with the shield reads the display's size, and so do extensions' pages. In this version the size is kept per tab, which leaves the display's size readable in two corners (a media query inside an SVG image, and a frame of a page that is leaving), and a pop-up of an exempted site reads the constant where the site would read the display's size, which fails on the safe side; the engine's own answer per document comes with the next version (ADR 0016, "Known limits").
- Fingerprinting: pages read UTC as the time zone ([ADR 0017](../adr/0017-pages-read-utc-with-a-switch-per-site.md), #79). Hours a page formats itself are in UTC until the person turns on "Usar meu fuso horário neste site" in the shield's panel; that site then reads the real time zone again (R56). Distribution Firefox (Track A) has no such switch, only the shield's own.
- Clean links drop eleven more tracking parameters that the engine's lists miss (#309).
- Accepted and written down: what Google still receives when a page of another site uses its services, and what is allowed there so that pages work (R73, #307); with DRM turned on, a closed module from Google runs inside Nulavio, in the engine's sandboxed plugin process (R74, #310).

## Nulavio 160.0-0.5 (Firefox 160.0), published 2026-11-14

An update of the alpha with the same engine ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.5), [run 43633960941](https://github.com/nulavio/nulavio/actions/runs/43633960941)), approved by the maintainer, signed through KMS and installed by the job from the site's repository files in clean Fedora and Ubuntu containers. No advisory: the AI Bridge and Vault fixes close what 160.0-0.4 had already published as residual risks (R29, R70), the Guard and Assistant fixes came from public issues (#136, #138), and the two release-chain fixes were found by the project's own reviews of code that was already public (#291, #233).

**Upstream**: unchanged, Firefox 160.0.

**Nulavio fixes** (what a user does: `sudo dnf upgrade nulavio` or `sudo apt upgrade nulavio`):

- AI Bridge: an agent without `local_resources` sends no request to this computer or the local network. In 160.0-0.4 a redirect still sent the request before the Bridge refused to act on the page (L5 and L6 there); it is now stopped before it is sent, for the tabs an agent drives (#248). What the engine does not show the Bridge stays in R29.
- Vault: a protected profile can get a new key, so that a removed unlock method stops opening old copies of the key file (#275, [ADR 0015](../adr/0015-a-new-key-for-a-profile.md)): that is what ends the power of an old secret, which R70 describes. Replacing the recovery code keeps the old code until the new one is typed back (#252), and the browser says when a change to the unlock methods was saved but not recorded inside the profile (#253).
- Guard: a replaced extension package is reported by its digest, whatever version the engine says (#264).
- Assistant: the item for selected text does not show in a private window (#254).
- Release chain: the APK signer refuses a data descriptor that only the local header announces (#291); the site's deploy job reads the Cloudflare token from the `site` environment (#233).

**New protections and their limits**:

- The engine's profile chooser unlocks a protected profile before it starts it, with the password, this computer's login or the recovery code (#267, engine patch 0011).
- The Nulavio Companion for Android comes with each release, signed with its own key held in AWS KMS (#260, #281, ADR 0014); the download page shows the certificate's fingerprint to check. It is not on F-Droid.
- Each version's notes come with the browser, and reading them sends nothing anywhere (#290).
- Accepted and written down: a search engine added by hand may use a plain-`http` address (R72); what the confined mode costs on Ubuntu (R46).

## Nulavio 160.0-0.4 (Firefox 160.0), published 2026-11-14

A security update of the alpha, with the same engine ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.4), [advisory GHSA-j8cq-r5j6-q2x3](https://github.com/nulavio/nulavio/security/advisories/GHSA-j8cq-r5j6-q2x3), [run 43534834214](https://github.com/nulavio/nulavio/actions/runs/43534834214)). The findings came from the LESIS automated code scan; the fixes were prepared in the advisory's private fork and landed in #150 and #178. The release was approved by the maintainer and signed through KMS; the job then installed it in clean Fedora and Ubuntu containers from the site's repository files, with the signature checks on. Drafting the GitHub release failed in the job (#236); the maintainer's token drafted it from the job's own files, after their signed checksums were checked.

**Upstream**: unchanged, Firefox 160.0.

**Nulavio fixes** (what a user does: on Fedora, `sudo dnf upgrade nulavio`; nothing else to change):

| # | Severity | Area | Fix |
|---|---|---|---|
| L1 | Medium | AI Bridge | A `view-source:` address took an agent outside its site list; the address inside is now checked as if it were opened itself (#150) |
| L3 | Medium | Vault | Putting back an older `vault.json` re-enabled a recovery code replaced while the profile was locked; the volume now records which key file is current (#150). What that record does not stop is R70 |
| L4 | Medium | AI Bridge | A page's own click handler could send a form for an agent without `submit_forms`; the forms a page sends by itself are held until the permission allows them (#150). What the hold does not reach is R68 |
| L5, L6 | Medium | AI Bridge | After a redirect to this computer or the local network, `tabs_list` and the result of a click still described the local page; they no longer do without `local_resources` (#150). The read itself was closed in 160.0-0.2 (A1) |
| L7 | Medium | AI Bridge | A new agent key left three ways for the old session to keep acting; each now ends it (#150) |
| L8 | Low | AI Bridge | A revoked connection could still read the agent's profile routes (#150) |
| L9 | Low | Site | Anyone who knew a sign-up email could remove it from the waitlist; leaving now takes the private link given at sign-up (#178, live on the site since 2026-11-13). What it leaves is R69 |

L2 (method changes signing a tampered key file) was already fixed in 160.0-0.2 (V4).

**Not fixed, residual risks**: the redirect request of L5 and L6 still reaches the local address before the Bridge refuses to act on the page (R29: an agent without `local_resources` cannot read what comes back); stopping it before it is sent, for the tabs an agent drives, is the next change. An interrupted unlock-method change (R70) and a click that sends data that is not a form (R68) are as their entries say.

**New protections and their limits**:

- Ubuntu: the first release in the signed APT repository (`https://nulavio.net/apt/nulavio.sources`, key inline, checked by SHA-256 on the download page and in the release notes). Like the dnf metadata, it carries no expiry (R57), and one key signs both (R58).
- The Flatpak bundle is a release asset, signed in `SHA256SUMS.asc` and attested, until Nulavio is on Flathub (#87).

## Nulavio 160.0-0.3 (Firefox 160.0), published 2026-11-11

The first release built, tested and signed by the release workflow ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.3), [run 43102367281](https://github.com/nulavio/nulavio/actions/runs/43102367281)): built on a Blacksmith runner, signed through the release key held in AWS KMS after the maintainer approved, installed from `https://nulavio.net/rpm/nulavio.repo` in a clean Fedora with both signature checks on. Every file has a GitHub build-provenance attestation.

**Upstream**: unchanged, Firefox 160.0.

**Nulavio fixes** (what a user does: `sudo dnf upgrade nulavio`): R59 (audit V3), left open in 160.0-0.2 while phone unlock was off, is resolved before phone unlock is offered. A desktop the phone is paired with, holding a copy of another desktop's `vault.json`, could get that profile's key; each phone envelope is now bound to the signing key of the desktop that made it, and the phone shows the desktop name from its own pairing record (#48).

**New protections and their limits**:

- Connecting a phone is offered by default (`nulavio.vault.phone.pairing`, #42). The pairing screen tells people to install the Companion from F-Droid, where it is still in review; until F-Droid publishes it, they cannot.
- The release key no longer signs from a laptop: KMS holds it, and only the `release` environment, after approval, on main, can use it (#54, #56, #58, #64; TB19, R61).
- A portable archive (`nulavio-160.0-0.3.linux-x86_64.tar.xz`) is published with the packages; it is what the Flatpak is built from.

## Nulavio 160.0-0.2 (Firefox 160.0), published 2026-11-11

A security update of the alpha, with the same engine ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.2), [advisory GHSA-5mmp-gx3p-m7j8](https://github.com/nulavio/nulavio/security/advisories/GHSA-5mmp-gx3p-m7j8)). Prepared in the advisory's private fork and published together with the packages.

**Upstream**: unchanged, Firefox 160.0.

**Nulavio fixes** (security audit of 160.0-0.1, 2026-11-10; what a user does: `sudo dnf upgrade nulavio`):

| Severity | Area | Fix |
|---|---|---|
| High | Repository | `nulavio.repo`, which turns dnf's signature checks on, was uploaded to the package bucket; it is now `site/rpm/nulavio.repo`, served by the site from git (R1) |
| High | Vault | `vault.json.bak` kept removed or replaced unlock methods, which still opened the profile; the copy now holds the current file and a stale one is removed (V2) |
| High | AI Bridge | Address checks read hosts differently from the engine (backslash, encoded host, IPv4 shorthand) and missed redirects: the local network was reachable without `local_resources` (A1) |
| High | AI Bridge | The Shell's own pages (`moz-extension:`) needed only `local_resources`; they now need raw automation (A2) |
| Medium | Release | Every package was release 0.1, so a fix would not reach installed copies; the release now counts up and publishing refuses one that is not newer (R2) |
| Medium | Vault | A method change re-signed a tampered key file (V4); an interrupted encryption left the profile in the clear (V5); a crash left a locked profile's folder writable (V6) |
| Medium | AI Bridge | Typing could send a form without `submit_forms` (A3); an approval followed the tab to another site (A4); "Permitir" worked at once on a page that opened in front (A5); the agent-window lock rested on a pref (A6) |
| Low | Vault | Lock paths that failed open (V7); core dumps while keys were in memory (V8) |
| Low | AI Bridge | Activity lost earlier actions after a burst (A7); `tabs_list` ignored the site list (A8); scripts read cookies without `cookies_storage` (A9); the assistant followed redirects with its API key (A10); a new key left the old session open (A11); the agent bar took any text (A12); a reused PID kept a window marked (A13) |
| Low | Site | Manual verification imported the key without checking its fingerprint (R5) |

**Not fixed, residual risks**: repository metadata without expiry (R57), release-key rotation (R58), phone unlock bound to one desktop (R59; phone unlock is off).

## Nulavio 160.0-0.1 (Firefox 160.0), published 2026-11-10

The first public alpha, for Fedora ([release](https://github.com/nulavio/nulavio/releases/tag/v160.0-0.1), dnf repository at `packages.nulavio.net`, signed with `298A 9093 BAAB B26F 79BB  29F4 BF47 E5FA 9EDB 8DB1`).

**Upstream**: Firefox 160.0, released by Mozilla on 2026-11-10 ([advisories](https://www.mozilla.org/security/advisories/); [update issue #14](https://github.com/nulavio/nulavio/issues/14)). Urgency: urgent (no advisory yet when the build started, update policy). Source SHA-256 2b23d2bf6716ea16b45c10aa5c275c78a1d7ff50ad53150809ab27424c58fd81 (Mozilla's signed SHA256SUMS, verified against the pinned release key).

| Mozilla's release | Detected | Ready to sign | Published | Target | Deadline |
|---|---|---|---|---|---|
| 2026-11-10 (product-details gives the date only) | staged, 2026-11-09 23:35 UTC (upstream issue); pre-built from staging the same day | 2026-11-10 22:26 UTC (rehearsal: unit, 349 integration tests, RPM/DEB in clean containers, signed-repository check, 33 min) | 2026-11-10 22:59 UTC (repository uploaded and installed from in a clean Fedora 44 container; GitHub release) | 24 h: met (same day) | 72 h: met |

**Nulavio fixes**: engine pin and signed source digest moved from Firefox 159.0.1 to 160.0. Patch 0008 is gone: Firefox 160 animates the sidebar launcher with a view transition whose timing is CSS, so Horizon sets Nulavio's expand and collapse times there. Patches 0001–0007 apply unchanged. No change to what a user must do. The first signing with the real key also found that the signing container could not ask for a passphrase (#36, fixed before publishing), and that a patched tree could not be rebuilt (#34).

## Unreleased (development, Firefox 159.0.1)

**Upstream**: Firefox 159.0.1, released by Mozilla on 2026-11-03 14:09:02 UTC ([mfsa2026-123](https://www.mozilla.org/security/advisories/mfsa2026-123/), [update issue #4](https://github.com/nulavio/nulavio/issues/4)).
Urgency: urgent (impact high: CVE-2026-120572, incorrect boundary conditions in Layout: Block and Inline). Source SHA-256 b5fe407199685f8bddf3b2c81feb8b805429e6f3d307c9430f53456f85b6e063 (Mozilla's signed SHA256SUMS, verified against the pinned release key).

| Mozilla's release | Detected | Ready to sign | Published | Target | Deadline |
|---|---|---|---|---|---|
| 2026-11-03 14:09:02 UTC | published, by 20:39:45 UTC (+6.5 h; upstream issue) | blocked on 2026-11-04 (release `gkrust` with fat Rust LTO needs more memory than the 32 GiB laptop leaves above the 4 GiB reserve); the release build completed on 2026-11-09 23:42:10 UTC (+153.6 h) with thin Rust LTO | not published (no release key or host yet) | 2026-11-04 14:09:02 UTC (24 h): missed | 2026-11-06 14:09:02 UTC (72 h): missed. No package has been published yet, so no user ran an affected build |

**Nulavio fixes**: engine pin and signed source digest updated from Firefox 159.0 to 159.0.1. The initial release rehearsal failed during compilation (a `rustc` received SIGKILL). Resource containment was then added and checked with controlled cgroup, OOM, signal and disconnect probes. Both the two-job guarded build and its single permitted one-job retry were aborted by the host-memory reserve guard, without recorded OOM; the full rehearsal remains blocked ([evidence](../research/evidence/release-rehearsal-2026-11-04.md)). After freeing host memory and an opt-in 20 GiB budget, two more guarded attempts compiled every Rust crate except release `gkrust` (Rust LTO), which passed 17 GiB. A local build without Rust LTO (`--disable-release`, not a release configuration) completed on 2026-11-04 for the maintainer's own use; it is not signed, packaged or distributed. The rehearsal now passes its private install path to RPM/DEB packaging, with a regression test. On 2026-11-09 the release configuration moved to thin Rust LTO (`CARGO_RUSTCFLAGS=-Clto=thin`) and the guarded release build of 159.0.1 completed within the default 16 GiB budget (peak 13.0 GiB, [evidence](../research/evidence/release-rehearsal-2026-11-09.md)). Signing and publishing remain pending: there is no release key or repository host yet.

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
| 2026-11-09 | After a password was typed on the unlock page of a protected profile, the engine's password manager offered to save it ("Salvar senha de moz-extension://…?") | Accepting the offer copied that profile's password into the saved logins of the profile that was open, which may have no protection | [#15](https://github.com/nulavio/nulavio/pull/15): saving is off for the Shell's own pages, set at every start; `test_vault_ui` 02 types a password with real keys and checks that no tab offers to save it. No package had been published |
| 2026-11-10 | The Nulavio build's User-Agent ended in `Nulavio/<version>` instead of `Firefox/<version>` | Every site visited, and every request, could tell a Nulavio user from the far larger group of Firefox users, and saw the point release; sites that look for Firefox did not recognise the browser | Patch 0009: the User-Agent is Firefox's own, in pages and on the wire (`test_fingerprinting` 01). No package had been published |
| 2026-11-10 | The engine's font protection never applied on Fedora (its lists stop at release 39 and the release number is not read from Fedora's `os-release`), and its quick canvas mode leaves raw pixel reads unchanged | With tracking protection in Strict, every installed font and the plain canvas pixels were still readable by any page, while the docs named font limits among the protections | Patch 0010 and `privacy.fingerprintingProtection.overrides`; `test_fingerprinting` 03 and 05. The same defect is in Firefox on Fedora; to be reported to Mozilla |

**New protections and their limits**

| Date | Protection | Limit |
|---|---|---|
| 2026-11-10 | Fingerprinting: canvas, offscreen-canvas and WebGL reads differ per site; no graphics card model, toolbar size, window position, desktop colours or motion sensors for pages; installed fonts hidden on Fedora and Ubuntu | It reduces what a page reads and does not make people identical; a site can tell the build from a stock Firefox by these protections ([R56](residual-risks.md)) |
| 2026-10-27 | Engine security fast path: urgency from Mozilla's advisories (24-hour target for urgent releases, 72-hour deadline), an issue per release that @mentions the maintainer, verified engine bump, opt-in local timer that pre-builds staged releases | Signing and publishing wait for the maintainer; detection can lag about 14 hours with the timer off, more if Actions does not run ([R51](residual-risks.md), [R52](residual-risks.md)) |
| 2026-10-27 | Dependency watch (OSV.dev, the AMO blocklist, registries), Dependabot, Gradle locking and checksum verification, base images pinned by digest | Ten build-time advisories accepted until 2026-12-31; new Gradle artifacts trusted on first download ([R53](residual-risks.md)) |
| 2026-10-27 | Code scanning in CI: secrets (gitleaks), Nulavio's own Opengrep rules, ShellCheck, workflow audits (zizmor, actionlint); advisory AI review of pull requests | Findings arrive after the push; no CodeQL; the AI review is advisory and off until a credential is added ([R54](residual-risks.md)) |
| 2026-10-26 | Guard at run time: changes made to a profile outside the browser (extensions, protective settings, certificate authorities, security modules, native-messaging hosts, policies, `user.js`, search) | Detection, not prevention; Nulavio-aware malware can edit the record ([R38](residual-risks.md)) |
| 2026-10-26 | Look-alike login warning (flow D) | Compares only with logins kept by the browser's own manager ([R41](residual-risks.md)) |
| 2026-10-26 | Temporary profile, deleted on close | Downloads, other apps' data and swap outlive it ([R37](residual-risks.md)) |
| 2026-10-26 | Explicit DNS choice | The chosen resolver sees lookups ([R40](residual-risks.md)) |
| 2026-10-26 | One engine build reads the distribution's system Mozilla directory on Fedora and Ubuntu (patch 0006) | — ([R25](residual-risks.md), resolved) |
| 2026-10-26 | Encrypted profiles at rest (Vault, gocryptfs), AI Bridge permissions, stop and audit | [R30](residual-risks.md)–[R36](residual-risks.md) |
