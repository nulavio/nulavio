# Track B build (Nulavio from source)

Status: **development spike, first build succeeded on 2026-10-24.** Builds are not releases: they are not signed or distributed (see "Release blockers"). Since 2026-10-25 they include a Google Safe Browsing key (see below).

## Resource limits and recovery (local builds)

`scripts/build/build_nulavio.sh` uses `build_guard.py` for every engine build,
including builds started by `rehearse_release.sh` and `autobuild.py`. It refuses to
start when another Nulavio build container is active, `MemAvailable` is below
4 GiB, or memory PSI `full avg10` is above 10%. It requires enforceable cgroup v2
limits; it never falls back to an unlimited container.

Defaults for a 32 GiB laptop shared with other applications:

- The whole container, including descendants: **16 GiB memory maximum, no swap,
  two CPUs of quota, 512 tasks**. The entry point reads back `memory.max`,
  `memory.swap.max`, `cpu.max`, `pids.max` and `memory.oom.group` before executing.
- Firefox: **`MOZ_PARALLEL_BUILD=2`** in the environment and generated mozconfig,
  and explicit `mach build --jobs 2`. Make receives `-j2` and shares its jobserver.
- Rust: **`CARGO_BUILD_JOBS=1`**, explicit Cargo jobs via mozconfig, and a wrapper
  that serializes Cargo invocations across Make edges. The wrapper removes
  `MAKEFLAGS`, `MFLAGS` and `CARGO_MAKEFLAGS`: this Cargo prioritizes an inherited
  jobserver over `--jobs`. At one Make job, Gecko supplies its own `-j1`.
- Nested native builds: `CMAKE_BUILD_PARALLEL_LEVEL=1`, `NUM_JOBS=1`,
  `RAYON_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1` and
  `NINJAFLAGS=-j1` for callers that honor it. These variables are not universal
  enforcement for arbitrary tools: the cgroup still caps all threads/processes.
  Image bootstrap uses the same 16 GiB/no-swap/two-CPU budget and one image job.

Every five seconds the supervisor writes `telemetry.jsonl`: host available RAM,
swap used, memory PSI, kernel CPU and I/O-wait percentages, container memory,
OOM events, compiler counts/process IDs and Cargo/Make arguments. An inner
watchdog samples processes each second and aborts if more than one `rustc` is
observed. A reserve breach stops the workload immediately; PSI above 10% for
30 continuous seconds stops it with the reason recorded. It does not try to
reconfigure a running Make jobserver. On memory failure, the **next explicit
invocation** drops to one Make job. A memory failure at one job refuses another
attempt until the cause is investigated; there is no automatic retry loop.

The script prints a control directory under `$NULAVIO_BUILD_DIR/logs/guard-*`
(default build directory `~/.cache/nulavio-build`). To inspect or stop that exact
workload, substitute its printed path:

```sh
control=/absolute/path/to/logs/guard-TIMESTAMP-PID
cat "$control/config.json" "$control/limits.json"
tail -f "$control/build.log" "$control/telemetry.jsonl"
podman inspect "$(cat "$control/container-id")"
podman stop --time 10 "$(cat "$control/container-id")"
cat "$control/result.json"
```

SIGINT, SIGTERM and SIGHUP stop the identified container, then remove it after
recording the result. The container's init forwards signals and reaps children.
If the supervisor is killed or its connection disappears without a signal, a
30-second heartbeat lease stops the workload from inside the container (up to
10 additional seconds for graceful termination). An exited container may remain
in that case; inspect it and use `podman rm` with its recorded ID. Artifacts,
source and object directories remain for incremental builds. A 24-hour runtime
ceiling is an additional backstop, not the disconnect detector.

**Runner budget** (`NULAVIO_BUILD_PROFILE=runner`, the release workflow on a
disposable 16 vCPU / 64 GiB CI machine that runs nothing else): 48 GiB (at most 56),
`MOZ_PARALLEL_BUILD=16` (at most 16) with the same number of CPUs, Cargo in parallel
(no serializing wrapper; at most as many `rustc` as jobs), 8192 tasks. The guard
refuses this budget on a host with less RAM than the container plus 6 GiB, so it
cannot be used on the laptop by mistake. Kernels without memory PSI (Blacksmith's)
are accepted only with this budget; the available-memory reserve still applies.
After a memory failure the next run halves the jobs.

Adjustments are per invocation: `NULAVIO_BUILD_MEMORY_GIB=1..20` (default 16,
which the release build fits since it uses thin Rust LTO: 13 GiB at its peak on
2026-11-09; above 16 only on explicit request; the 4 GiB host reserve still applies),
`MOZ_PARALLEL_BUILD=1..2`, `NULAVIO_BUILD_MIN_AVAILABLE_GIB` (default 4),
`NULAVIO_BUILD_PSI_LIMIT` (default 10) and `NULAVIO_BUILD_PSI_SECONDS` (default
30). The maximum memory/jobs cannot silently exceed this laptop budget.
No host VM settings, swap configuration, unrelated processes or global service
configuration are changed. A successful one-job recovery stays at one job on
subsequent invocations. After reviewing the cause and logs, a maintainer can
archive `logs/last-result.json` to explicitly return to the configured budget.

Before a full engine build, the opt-in controlled probes can be repeated:

```sh
NULAVIO_BUILD_RESOURCE_TESTS=1 python3 -B -I tests/run.py integration test_build_resources.py
```

They use the already built `localhost/nulavio-build:f44` image, a 1 GiB cgroup,
and disposable directories. They check descendant limits, isolated cgroup OOM
and one-job recovery, SIGTERM cleanup with a child ignoring TERM, and SIGKILL
of the supervisor followed by lease expiry. They do not create host memory
pressure. On 2026-11-03 all four passed in 60 seconds; a separate Make `-j2`
probe compiled two local Rust packages with multiple dependencies and a C++
object, observing at most one `rustc` and no inherited-jobserver warning after
removing Cargo's jobserver environment. These checks do not certify a complete
Firefox build or desktop responsiveness under other applications' workloads.

## Pipeline

```
scripts/build/build_nulavio.sh <version>
 ├─ scripts/upstream/fetch_firefox_source.py   SHA256SUMS signature checked against the pinned Mozilla key,
 │                                              tarball hashed while streaming, extracted only on match;
 │                                              the tree is reused only if extracted from that digest
 ├─ scripts/upstream/fetch_firefox_l10n.py     translations (default pt-BR) at the revision signed off in the
 │                                              verified source's l10n-changesets.json + Nulavio's browser/l10n/
 ├─ scripts/build/make_branding.py             browser/branding/nulavio/ (text, reviewed in git)
 │                                              + generated icons/logos/wordmarks from docs/brand (no Mozilla art)
 │                                              + the Nulavio Shell built-in add-on (make_shell.py)
 ├─ scripts/build/apply_patches.py             browser/patches/series (3 patches: vendor, l10n mapping, Horizon link)
 ├─ browser/build/mozconfig                    copied into the source tree
 └─ podman (rootless) localhost/nulavio-build:f44   ci/containers/fedora-build.Containerfile
      ./mach build && ./mach package-multi-locale --locales en-US pt-BR
                                                toolchains fetched by --enable-bootstrap into a cached volume
```

Work directory (outside the repository): `${NULAVIO_BUILD_DIR:-~/.cache/nulavio-build}`, containing `downloads/`, `firefox-<v>/` (source and `obj-nulavio/`), `mozbuild/` (toolchains) and `logs/`, plus `firefox-<v>.stale-*/` when a tree was set aside because it was not extracted from the tarball Mozilla signs now. Deleting it removes everything the build created. Nothing is installed on the host.

## Measured on the reference machine (Ryzen 7 5825U, 8C/16T, 30 GiB, NVMe/LUKS)

| Metric | Value |
|---|---|
| First full build (configure + compile + link), Firefox 158.0.1 source | **≈ 52 min** wall clock (22:52:25 → 23:44, from mach's resource profile) |
| No-op incremental build | 20 s |
| Packaging (`./mach package`) | < 1 min → `nulavio-158.0.1.en-US.linux-x86_64.tar.xz` (85 MB), 317 MB installed |
| Disk: source tree / object dir / toolchains / tarball | 4.7 GB / 15 GB / 2.4 GB / 777 MB; **23 GB total** (estimate was ~45 GB) |
| Toolchains | Clang, cbindgen, nasm, node, Linux sysroot and the WASI sysroot (RLBox) via `--enable-bootstrap`; Rust 1.99 from Fedora's signed repositories |
| Result | `application.ini`: `Vendor=Nulavio`, `Name=Nulavio`, `RemotingName=nulavio`, add-on ID unchanged; `nulavio --version` → `Nulavio Nulavio 158.0.1` |
| Integration tests against the build | **17/17** on 2026-10-25, with network tests (official password-manager extensions, Safe Browsing end to end). Before the key: 14/15 |
| Rebuilds | Adding the key changes the configuration, so most of the tree recompiled: **38 min**. A branding-only change (prefs, icons) rebuilds and repackages in **< 1 min** |
| Release build under the guard (two CPUs, 16 GiB), Firefox 159.0.1, thin Rust LTO, 2026-11-09 | **104 min** wall clock with the Rust dependencies already compiled and the configuration changed back to release; `gkrust` itself 12 min. Container peak **13.0 GiB**, no cgroup `max` or OOM event; the host never had less than 15 GiB available. Package 81.8 MiB ([evidence](../research/evidence/release-rehearsal-2026-11-09.md)) |

Lessons from the first attempts: `MOZ_APP_VENDOR` cannot be set from a mozconfig (it is only implied by the project file, hence patch 0001). `--enable-bootstrap` does not install Rust, so it comes from Fedora packages. Keep the build output pipe alive for the whole build: a killed log `tee` interrupted the first packaging step.

## Configuration choices (`browser/build/mozconfig`)

| Option | Why |
|---|---|
| `--with-branding=browser/branding/nulavio` | Own names, icons and about dialog. No Mozilla marks (distribution policy) |
| `--with-app-name=nulavio`, `--with-app-basename=Nulavio`, `MOZ_APP_VENDOR=Nulavio`, `MOZ_APP_REMOTINGNAME=nulavio` | Binary name, profile location, Wayland app_id, remoting |
| Add-on application ID **unchanged** (Firefox's) | AMO extensions keep working (ADR 0001 open item 3: policy/legal check pending) |
| `MOZ_REQUIRE_SIGNING=1` | Mozilla-signed extensions only. A release milestone implies it, but ESR would not, so it is stated explicitly |
| `--disable-updater` | Updates come from the distribution package (RPM/DEB) under the [update policy](update-policy.md). This is a delivery-channel choice, not a removal of updates |
| `--disable-crashreporter` | There is no Nulavio crash server. Crash data is never sent anywhere |
| `--enable-release --enable-optimize --disable-debug --disable-tests` | Release-like build for realistic testing |
| `mk_add_options "export CARGO_RUSTCFLAGS=-Clto=thin"` | The release default runs a fat link-time optimisation pass over `gkrust` (all Rust code in one unit). It needed more than 17 GiB and stopped four guarded builds on the 32 GiB build laptop ([evidence](../research/evidence/release-rehearsal-2026-11-04.md)). Thin LTO still optimises across crates and fits in 13 GiB. The build system appends this value after its own `-Clto` and `rustc` keeps the last one, so no engine patch is needed; only `export` lines of the mozconfig reach the makefiles that run Cargo. Cost: somewhat less cross-crate optimisation in Rust code (style system, WebRender) than a fat pass; Mozilla's own builds go further in the other direction (cross-language LTO with profile-guided optimisation), which needs a larger builder and is a later item |

## Google Safe Browsing key

Firefox 158 uses one key for the Safe Browsing v5 lists (preferred), the v4 lists and the download-reputation check. The key is a build input, never part of this repository:

| Item | Value |
|---|---|
| Google Cloud project | `nulavio` (dedicated, owned by the maintainer, no billing account) |
| Key | "Nulavio Track B - Safe Browsing", **restricted to the Safe Browsing API only** |
| Location on the build machine | `~/.config/nulavio-build/google-safebrowsing.key`, mode 0600 (override: `NULAVIO_SAFEBROWSING_KEYFILE`) |
| How it reaches the build | `build_nulavio.sh` mounts it read-only at `/run/secrets/google-safebrowsing.key`. The mozconfig passes it to `--with-google-safebrowsing-api-keyfile`. The script never prints it |
| Missing key | The build **stops** (exit 2). `NULAVIO_ALLOW_NO_SAFEBROWSING_KEY=1` builds without it for development only. Phishing/malware lists are then inactive and `test_12` fails |
| Verified | v4 `threatLists` and v5 `hashes:search` answer HTTP 200 with the key and 403 without it. The build log never contains the key. `test_14` downloads the phishing and malware lists and gets Google's test page blocked (`about:blocked?e=deceptiveBlocked`) |

What Google serves to a Safe Browsing API key (measured 2026-10-25, [evidence](../research/evidence/trackb-158.0.1-safebrowsing.json)):

| Engine list | v5 name | Available | Effect in Nulavio |
|---|---|---|---|
| `googpub-phish-proto` (phishing) | `se-4b` | ✅ | Active. Mozilla-official builds call it `goog-phish-proto`; with v5 both are Google's single social-engineering list |
| `goog-malware-proto`, `goog-unwanted-proto`, `goog-harmful-proto`, `goog-globalcache-proto` | `mw-4b`, `uws-4b`, `pha-4b`, `gc-32b` | ✅ | Active |
| `goog-badbinurl-proto` (known malicious download URLs) | `mwb-4b` | ❌ HTTP 404 | Not requested |
| `goog-downloadwhite-proto` (download allowlist) | `csdda-32b` | ❌ HTTP 404 (v4 only) | Not requested; it only serves the remote check below |
| Remote download check (`sb-ssl.google.com/safebrowsing/clientreport/download`) | n/a | ❌ HTTP 403: "Safe Browsing Download Protection API" is not in the public API library | **Off** (`browser.safebrowsing.downloads.remote.enabled=false`) |

The engine fetches all lists of a provider in **one** request. With the stock list prefs, the unavailable `mwb-4b` made every update fail. The build then had a key but **no list at all**. `test_12` (key present) did not notice; `test_14` (end to end) did. The branding prefs now request only the available lists. They also switch off the remote download check, which would otherwise send download details (URL, hash, file name) to Google and get only an error back. This is a documented trade-off, not a simplification: page-level phishing and malware protection is active. Executable-download reputation needs Google's partner API (request access) or a replacement such as the planned flow E warning ([ux-flows](../brand/ux-flows.md)). See residual risk R15.

Caveats:

- **Terms.** Google's Safe Browsing API is "for non-commercial use only". Nulavio is non-commercial open source. Any commercial use would require Google's paid Web Risk API instead, and Gecko has no Web Risk provider today.
- **Quota.** A personal project has Google's default quota. It is enough for development and a small preview. A public release needs a quota review with Google.
- **The key is not secret from users.** It is embedded in every binary, as in Firefox and Chromium builds. The API restriction limits misuse to Safe Browsing quota. Keep it out of git and logs anyway, and rotate it in the Cloud console if it is abused.
- **Privacy.** Lists are downloaded and matched locally. On a local match the browser sends a short hash prefix (not the URL) to Google to confirm. Nothing goes to Nulavio.
- Other maintainers build with **their own** key (same steps: project → enable "Safe Browsing API" → API key restricted to it → save it to the path above).

## Languages

The build packages **en-US and pt-BR** (`NULAVIO_LOCALES`, default `pt-BR`). `fetch_firefox_l10n.py` reads each locale's firefox-l10n revision from `browser/locales/l10n-changesets.json` inside the signature-verified source, fetches only that locale's directory (partial, sparse git fetch; about 3.5 MB and 2 s for pt-BR) and checks the checked-out commit. Nulavio's own translations in `browser/l10n/<locale>/` (today the brand names and the "not affiliated with Mozilla" line) are laid over it.

- The branding strings are localizable (`%` entries in `browser/branding/nulavio/locales/jar.mn`). Firefox's l10n configuration only maps the official branding, so patch `0002` adds Nulavio's branding directory. Without it, packaging fails (`MissingJarSource`).
- The build follows the desktop's language (`intl.locale.requested=""`, as Fedora's Firefox does); users can pick another one in Settings.
- `test_15` checks that pt-BR is packaged, that "O Nulavio está atualizado" uses the Nulavio brand, that the legal line is translated and that no "Firefox" leaks into Portuguese UI strings.

## Nulavio Horizon (window theme)

`browser/branding/nulavio/content/theme/horizon.css` re-values Firefox's design tokens for the tab strip, toolbar and address bar; `tokens.css` next to it is generated from `docs/brand/tokens.json`. Patch 0003 adds one `<link>` to `browser.xhtml` so the theme applies from the first paint. Pref `nulavio.horizon.enabled` (default true) switches it off. Architecture and rebase notes: [docs/design/architecture.md](../design/architecture.md).

## Nulavio Shell (built-in add-on)

`browser/shell/` is a WebExtension shipped inside the build as a built-in system add-on (`shell@nulavio.net`). Firefox's `toolkit/mozapps/extensions/gen_built_in_addons.py` registers every `builtin-addons/<name>/manifest.json` packaged in `browser.jar`. `scripts/build/make_shell.py` assembles the add-on (plus the brand tokens and symbol) into the branding directory, whose `moz.build` lists it, so **no Mozilla file is patched**. Built-in add-ons need no AMO signature, are hidden from the add-ons list and cannot be removed by profile tampering. Track A (distribution Firefox) cannot load unsigned add-ons, so there the Shell only runs in tests, as a temporary add-on. Adding the directory rebuilt and repackaged in under 1 minute.

## Facts verified in the 158.0.1 source

| Fact | Source | Consequence |
|---|---|---|
| Per-user native-messaging manifests are always read from `~/.mozilla/native-messaging-hosts` ("Keep forcing the legacy path for compatibility") | `toolkit/xre/nsXREDirProvider.cpp` | KeePassXC and Bitwarden desktop integrations work unchanged in a rebranded build (resolves ADR open item 4) |
| Without `--with-google-safebrowsing-api-keyfile`, the key is `no-google-safebrowsing-api-key` and Google Safe Browsing providers are **skipped** | `build/moz.configure/keyfiles.configure`, `toolkit/components/url-classifier/SafeBrowsing.sys.mjs` | A self-built browser has **no phishing/malware list protection** without a key. Resolved: the build mounts a key (next section) |
| Extension signing is required by default only for release/beta milestones | `toolkit/moz.configure` (`require_signing`) | Kept explicit in mozconfig |
| The about dialog hard-codes Mozilla community, donation, terms and privacy-notice links | `browser/base/content/aboutDialog.xhtml` | Hidden with the branding's `aboutDialog.css`, no patch. A wider audit of Mozilla-hosted help/support URLs is a Track B to-do |
| The `unofficial` branding sets `devtools.selfxss.count=5`, which enables pasting into the web console without the Self-XSS gate. Official branding uses 0 | `browser/branding/*/pref/firefox-branding.js` | Nulavio branding sets 0 |
| (159.0) Mozilla's AI chatbot, smart tab groups, Link Preview (and its key points), Smart Window and `extensions.ml` are on or one Nimbus rollout away; the chatbot sends page text to a third-party site from the sidebar, the page context menu and a selection shortcut. Mozilla account and Sync are on, with an account button, an app-menu promo and a launcher tool for synced tabs; about:home's default shortcuts come from Remote Settings and include "Add-ons for Firefox" | `browser/app/profile/firefox.js`, `modules/libpref/init/all.js`, `browser/components/genai/GenAI.sys.mjs`, `browser/components/sidebar/`, `browser/base/content/browser-sync.js`, `browser/extensions/newtab/lib/TopSitesFeed.sys.mjs` | Off as build defaults in `firefox-branding.js` (decisions D-UX7, D-UX8); the AI prefs also in `baseline.js` for Track A. The launcher's default tools drop the chatbot and synced tabs. `test_mozilla_features` checks the rendered launcher, a real context menu, the toolbar, the app menu and about:home |
| Builds without `MOZILLA_OFFICIAL` (Nulavio) default to **`devtools.chrome.enabled=true` and `devtools.debugger.remote-enabled=true`** (privileged Browser Console and Browser Toolbox connections, a "paste this into the console" scam vector), plus chrome console output on stdout. The Guard did not catch it because it audits profile files, not engine defaults | `modules/libpref/init/all.js` | Nulavio branding restores Mozilla's shipped values (all `false`); `test_13` asserts them |
| Without `MOZILLA_OFFICIAL`, the phishing list is named `googpub-phish-proto` and the Safe Browsing client id is `Firefox` instead of Firefox's approved `navclient-auto-ffox`. `MOZILLA_OFFICIAL` is not set: it would claim Mozilla's Google-approved identity | `modules/libpref/init/all.js`, `nsUrlClassifierUtils.cpp` | Nothing to do; `test_14` reads the list name from the engine |

## Release blockers for Track B

1. ~~Google Safe Browsing API key~~ **Resolved 2026-10-25** (section above). R15 for downloads was accepted on 2026-11-04 (D9); the default quota was accepted for the alpha on 2026-11-10, to be reviewed with Google past 70 % of the daily update quota ([release criteria](../product/release-criteria.md#public-alpha-decided-2026-11-04)).
2. Signed packages and repository ([update policy](update-policy.md)): packages, signing and the publishing steps are done and verified (sections below); the release key (2026-11-10, fingerprint in `packaging/release.json`) and the host (`packages.nulavio.net`, Cloudflare R2) exist; what remains is the upload token and the first signed release.
3. ~~Policy/legal confirmation for keeping Firefox's add-on application ID and using AMO~~ **Decided 2026-11-10 by the maintainer** (keep it, as other Gecko-based browsers do); not reviewed by counsel.
4. Brand and trademark matters are handled outside the repository ([guidelines](../brand/guidelines.md)).

## Running the build output

`./mach package` produces `obj-nulavio/dist/nulavio-<version>.en-US.linux-x86_64.tar.xz`. To test it with the Nulavio launcher and tests:

```sh
tar -xJf ~/.cache/nulavio-build/firefox-158.0.1/obj-nulavio/dist/nulavio-158.0.1.en-US.linux-x86_64.tar.xz -C ~/.cache/nulavio-build/install
python3 -I scripts/build/make_distribution.py --out ~/.cache/nulavio-build/install/nulavio/distribution
python3 -I scripts/build/make_tools.py --out ~/.cache/nulavio-build/install/nulavio/nulavio-tools  # Vault helper for the Shell (S6)
NULAVIO_ENGINE=~/.cache/nulavio-build/install/nulavio/nulavio python3 -I tests/run.py integration
# add NULAVIO_NETWORK_TESTS=1 to also run the Safe Browsing end-to-end test (contacts Google)
```

## Packages (S18)

One engine build serves Fedora and Debian/Ubuntu: patch 0006 makes the engine read the system Mozilla directory the distribution has (`/usr/lib64/mozilla` on Fedora, `/usr/lib/mozilla` on Debian/Ubuntu), so native-messaging hosts installed by distribution packages are found on both ([R25](../security/residual-risks.md), resolved). Every step runs in a disposable rootless container; nothing is installed on the host.

| Step | Command | What it does |
|---|---|---|
| RPM | `scripts/release/make_rpm.sh [out]` | `packaging/rpm/nulavio.spec` in a Fedora 44 container: the tree under `/usr/lib64/nulavio`, `/usr/bin/nulavio`, desktop entry and icons; no install scripts; Requires python3 and util-linux, Recommends libsodium, gocryptfs, fuse3 |
| .deb | `scripts/release/make_deb.sh [out]` | The same tree under `/usr/lib/nulavio`, built in an Ubuntu 26.10 container; `Depends` computed from the libraries the engine needs and does not ship (readelf + apt-file); an AppArmor profile (`/etc/apparmor.d/nulavio`, conffile) that only allows the user namespaces the engine's content sandbox needs on Ubuntu 24.04+, loaded by the package's only maintainer scripts (S23, [spikes](../security/phase5-spikes.md#apparmor-on-ubuntu)) |
| Check | `scripts/release/check_rpm.sh <rpm>`, `check_deb.sh <deb>` | Install in a clean container with the distribution's own repositories; files as packaged (`rpm -V`, `dpkg --verify`), root-owned and not writable by users; `nulavio --version`; a headless start renders a page; the system Mozilla directory the engine reads (Marionette probe); the Nulavio tools answer |
| Sign | `GNUPGHOME=… scripts/release/sign_repo.sh <packages> <repo> <key>`, or with the key in AWS KMS: `NULAVIO_KMS_KEY_ID=alias/nulavio-release AWS_PROFILE=… AWS_REGION=us-east-1 scripts/release/sign_repo.sh …` (rpm 6 signs through `openpgp_sign.py`; AWS credentials enter the container as variables, by name) | `rpmsign`, `createrepo_c`, detached signature of `repomd.xml` and the public key. No `nulavio.repo`: the file that turns dnf's checks on is `site/rpm/nulavio.repo` (gpgcheck and repo_gpgcheck on), served by the site from git at `https://nulavio.net/rpm/nulavio.repo`, so writing to the package bucket cannot turn the checks off; the key is read from a read-only mount and its copy is deleted |
| Check signing | `scripts/release/test_signed_repo.sh <packages>` | With a throwaway key made for the run: install from the signed repository in a clean container with both checks on, then confirm a repository with altered metadata is refused |
| Check KMS signing | `scripts/release/test_kms_signing.sh` (a step of the rehearsal) | Signing through AWS KMS without AWS: a throwaway RSA-4096 key is handed to a stand-in `aws` command and deleted, then `sign_repo.sh` in its KMS mode signs a test package and `repomd.xml`; dnf installs it with both checks on and refuses a copy with altered metadata |
| SBOM | `scripts/release/sbom.py --package <file> --engine-version <v>` | CycloneDX for one package: the engine as redistributed (Mozilla source release plus each patch with its SHA-256 as pedigree), the pinned extensions, and the package's own SHA-256. Every component with an exact version carries a purl, and a CPE where the NVD has the product (the engine, uBlock Origin, KeePassXC-Browser, Bitwarden), so vulnerability scanners can match them; the distribution's libsodium, required as a version range, has neither |
| Companion SBOM | `scripts/release/sbom.py --companion [--apk <apk>]`; for the dependency graph too, first `android/gradlew -p android -q :app:dependencies --configuration releaseRuntimeClasspath > deps.txt`, then add `--gradle-dependencies deps.txt` | CycloneDX for the Android app: every library of the release build, from `android/app/gradle.lockfile` (no Gradle run needed), with its Maven purl and the SHA-256 from `android/gradle/verification-metadata.xml`. With Gradle's report, also the dependency graph at the versions Gradle resolved; the report must list the same libraries as the lock. It fails on an unresolved library, one the verification metadata does not pin, or a report that disagrees with the lock |

Measured on the reference laptop (2026-10-26): RPM 91 MB, built in about 2.5 minutes; .deb built in about 1 minute after the container's package index is fetched; each check about 30–60 seconds. Results of the first run: both packages install and pass every check; the signed repository installs with verified signatures and refuses altered metadata.

The APT repository (#211): `sign_apt_repo.sh <packages> <repo> <fingerprint>` builds `pool/` and `dists/stable/` with `apt-ftparchive` in an Ubuntu container (indexes also by hash, no MD5 or SHA-1, no `Valid-Until`, R57), then signs `Release` on the host: `InRelease` (cleartext, `openpgp_sign.py --clearsign` through KMS, or gpg) and `Release.gpg`, both checked with `gpgv` and the public key alone. The source file that turns apt's checks on is `site/apt/nulavio.sources`, served by the site, with the release key inline in `Signed-By`. `scripts/release/test_apt_repo.sh` signs a test package through a stand-in KMS and has apt install it with that file, then refuses a changed index, a changed package, a changed `InRelease` and another key.

### Signing in CI through AWS KMS

Goal: release builds signed by CI after the maintainer approves the run, so a Firefox security release does not wait for the maintainer's laptop. Decided on 2026-11-11: the existing release key (`298A 9093 BAAB B26F 79BB  29F4 BF47 E5FA 9EDB 8DB1`) is imported into AWS KMS, where it cannot be exported, so users keep the key they already trust. The original stays offline, with the revocation certificate.

| Part | Status |
|---|---|
| `scripts/release/openpgp_sign.py`: builds the OpenPGP signature (version 4, SHA-256) and asks KMS only for the RSA operation; refuses a KMS key whose modulus is not the release key's; works as rpm 6's signer (`%_openpgp_sign kms`) and for detached signatures (`repomd.xml`, `SHA256SUMS`) | **Done**: unit tests check every signature with gpg; `test_kms_signing.sh` checks rpm and dnf |
| `scripts/release/kms_import_key.py`: run once by the maintainer. Asks for the key's passphrase on the terminal, has gpg export the secret key with it (on standard input; the key's home is only read), decrypts the export's OpenPGP protection and checks the numbers against the public key, builds the PKCS#8 key material, wraps it with KMS's import parameters (RSA_AES_KEY_WRAP_SHA_256) and imports it without expiry, checks that KMS now signs as the release key | **Done**: unit tests for decrypting the export (and refusing a wrong passphrase), S2K, the PKCS#8 material (`openssl pkey -check`), the wrapping, and the whole run against a stand-in KMS; not yet run against KMS |
| `scripts/release/kms_setup.sh` with the policies in `ci/aws/`: the KMS key `alias/nulavio-release` (RSA_4096, SIGN_VERIFY, origin EXTERNAL) and the role `nulavio-release-signing`, which only a job of this repository in the `release` environment can assume (GitHub OIDC, immutable repository subject), allowed Sign, GetPublicKey and DescribeKey on that key only. The key policy lets only that role and the account's administrator SSO roles sign, only with RSASSA_PKCS1_V1_5_SHA_256. The GitHub environment `release` asks for an approval by the maintainer's account (which coding agents also work with: [R62](../security/residual-risks.md)), accepts only `main`, and holds the key and role ARNs as variables | **Done** 2026-11-11 (account `lombello-dev`, us-east-1); the key is empty until `kms_import_key.py` runs |
| `.github/workflows/release-signing-check.yml` (manual): signs a test file through KMS in the `release` environment and verifies it with `site/keys/nulavio-packages.asc` | **Done** 2026-11-11: run 42963429141, `VALIDSIG 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1` |
| `sign_repo.sh` and `publish_release.sh` sign through KMS when `NULAVIO_KMS_KEY_ID` is set (packages, `repomd.xml`, `SHA256SUMS`); the gpg-agent path stays for a release without AWS | **Done** 2026-11-11: the 160.0-0.2 RPM signed through the real KMS key installed in a clean Fedora 44 with both checks on (`RSA/SHA256, Key ID bf47e5fa9edb8db1`); nothing was published |
| `.github/workflows/release.yml`: build and rehearse on Blacksmith, then a signing job in the `release` environment (maintainer approval) that uploads and drafts the GitHub release (section below) | Written 2026-11-11; first run pending |

### Release workflow (CI)

`.github/workflows/release.yml`, started by hand from `main` (Actions → release → Run workflow), builds the Firefox release that `browser/build/engine.json` pins. Bump the pin first (`bump_engine.py`, a pull request).

| Job | Runs on | Holds | Does |
|---|---|---|---|
| `build` | Blacksmith `blacksmith-16vcpu-ubuntu-2404` (16 vCPU, 62 GiB, 738 GB disk, rootless Podman 5.8 with cgroup v2 limits; measured 2026-11-11), environment `build` (main only) | the Google Safe Browsing key (secret `GOOGLE_SAFEBROWSING_API_KEY`; it ships inside the browser anyway) | `rehearse_release.sh` with the runner budget: verified source, build, unit and integration tests, RPM and .deb checked in clean containers, the signed-repository checks, SBOMs, `manifest.json`; a GitHub build-provenance attestation of the packages and the manifest |
| `publish` | GitHub-hosted `ubuntu-24.04`, environment `release` (the maintainer approves, see R62; main only) | the KMS signing role (OIDC) and the bucket-scoped R2 upload token (secrets `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`) | checks the attestation (this workflow, `refs/heads/main`), `publish_release.sh` through KMS (the dnf and the APT repository), `upload_repo.sh` for each (packages first, signed metadata last, nothing deleted), `check_published.sh` (installs from `https://nulavio.net/rpm/nulavio.repo` in a clean Fedora and from `https://nulavio.net/apt/nulavio.sources` in a clean Ubuntu, with the signature checks on, and requires the new version), attests the signed files, drafts the GitHub release |

The integration step runs in the pinned container `ci/containers/fedora-release-itest.Containerfile` (`NULAVIO_INTEGRATION_IMAGE`, `scripts/release/run_integration.sh`), the same on the laptop and in CI. It fixes the fonts the component gallery's pixel baselines were made with (Noto and Liberation, as on the reference Fedora 44 KDE laptop) and has the tools the tests use. Run on Blacksmith's Ubuntu host, the gallery rendered 44 px taller and its baselines failed. FUSE works there for the Vault tests: `/dev/fuse` is passed in, and `SYS_ADMIN` applies only inside the rootless user namespace. Without the variable, the suite runs on the host as before.

The maintainer then publishes the draft (which creates the tag), sets `version` in `packaging/release.json` by pull request (the site workflow rebuilds the download pages), and adds the changelog entry; the job summary lists these steps. `publish: false` stops after the build: a rehearsal in CI. The build machine never holds the signing role or the upload token.

### Flatpak (Flathub)

The Flatpak `net.nulavio.Nulavio` packages the same signed build as the RPM: the portable archive `nulavio-<firefox>-<release>.linux-x86_64.tar.xz` that `rehearse_release.sh` makes from the installed tree (sorted, owner 0, the commit's time), that the manifest lists with its SHA-256 and that `publish_release.sh` attaches to the GitHub release. It is not built from source on Flathub: a Firefox build does not fit Flathub's builders, and the binary then differs from the one the RPM users run (Mozilla's and LibreWolf's Flatpaks do the same).

`scripts/release/flatpak_manifest.py` writes the build directory (manifest `net.nulavio.Nulavio.json`, desktop entry renamed to the app ID, AppStream metadata from `packaging/flatpak/` with this release, entry point, Flatpak-only preferences). Runtime `org.freedesktop.Platform` 26.08; its `codecs-extra` extension brings the patented codecs.

| Permission | Why |
|---|---|
| `--share=network`, `--share=ipc`, `--socket=wayland`, `--socket=fallback-x11`, `--socket=pulseaudio`, `--device=all`, `--socket=pcsc` | A browser: network, display, sound, cameras and FIDO2 security keys (WebAuthn), smart cards; as Mozilla's Flatpak |
| `--persist=.nulavio`, `--filesystem=xdg-download` | Profiles stay in the app's own directory (`~/.var/app/net.nulavio.Nulavio`); downloads go to the Downloads folder; nothing else of the home |
| `--talk-name=org.freedesktop.NativeMessagingProxy` with the preference `widget.use-xdg-desktop-portal.native-messaging-proxy=1` | Password-manager apps (KeePassXC, Bitwarden) through `xdg-native-messaging-proxy` on the host ([spike](../security/phase5-spikes.md#flatpak-and-native-messaging)) |
| `--own-name=org.mozilla.nulavio.*`, `--talk-name=org.freedesktop.FileManager1`, `org.a11y.Bus`, NetworkManager (system bus) | Remoting (a second start opens a window in the running browser), "show in folder", accessibility, online state |

Not in the Flatpak: the Vault (it needs `gocryptfs` and FUSE on the host), `nulavio run --confined` (bubblewrap inside the sandbox), and the Connect features that talk to desktop services over D-Bus (KRunner, KDE Connect, activities). The AppStream text says so. `tests/unit/test_flatpak.py` refuses permissions that undo the sandbox (the home, the host, any D-Bus name, the Flatpak service).

Every release run builds it: the `flatpak` job of `release.yml` builds and installs it from the archive that run made with Flathub's own builder (`org.flatpak.Builder`, with `--compose-url-policy=full` as `flathub-build` does), runs `flatpak-builder-lint` on the manifest and the repository, and `check_flatpak.sh` starts it headless in the sandbox and requires a rendered page. Measured on 2026-11-11 with 160.0-0.3: builds, renders, both lints clean. The `publish` job writes the Flathub manifest (`--url`: the GitHub release asset and its SHA-256) into the `published` artifact.

Until it is on Flathub, the release carries the Flatpak itself: the job bundles what it built (`flatpak build-bundle`, `nulavio-<version>.x86_64.flatpak`, with Flathub as the runtime's source), and `publish_release.sh` adds the bundle to the assets (`NULAVIO_FLATPAK_BUNDLE`, which must be this release's name), so `SHA256SUMS.asc` and the `publish` job's attestation cover it. The `flatpak` job cannot attest (no OIDC token): it runs Flathub's builder, which must not be able to attest anything; the bundle is as trustworthy as that builder and the runtime it pulls from Flathub. `flatpak install --user nulavio-<version>.x86_64.flatpak` installs it and adds Flathub for the runtime; a bundle has no update channel, so the next release is installed the same way. A failed Flatpak job does not hold back the release: `publish` goes on without the bundle and warns, because a security update has a deadline.

Submitting to Flathub (once, by the maintainer): open a pull request to `flathub/flathub` (branch `new-pr`) with that folder; after it is merged, Flathub creates the repository `flathub/net.nulavio.Nulavio`, where each release is a pull request with the new folder. Verify the app on Flathub's developer page: it gives a token to serve at `https://nulavio.net/.well-known/org.flathub.VerifiedApps.txt`.

### Repeatable builds

The same commit must give the same bytes (OpenSSF Best Practices `build_repeatable`). What makes that hold:
- every build runs in the pinned `fedora-build` image with the same paths (`/src`, `/root/.mozbuild`);
- the toolchains come from Mozilla's bootstrap, pinned by the source release;
- the branding icons are rendered in the pinned image;
- the build ID (`MOZ_BUILD_DATE`) and `SOURCE_DATE_EPOCH` are the Nulavio commit's time, not the clock;
- the portable archive is packed reproducibly (`make_archive.sh`: sorted, owner 0, normalized modes, one time).

`.github/workflows/repeatable.yml` checks it monthly and by hand. It builds the pinned Firefox twice, on two separate Blacksmith machines, installs and packs each build (`install_build.sh`, `make_archive.sh`), and `compare_builds.py` requires identical archives. On a difference, it lists the entries that differ and what differs (content, mode, link, time, owner), and attaches diffoscope's report on the first files.

### Publishing a release

| Step | Command | What it does |
|---|---|---|
| Release key (once) | `scripts/release/make_release_key.sh <new-gnupg-home>` | RSA 4096 signing key, two years, in a new GnuPG home outside the repository; writes only the public key to `site/keys/nulavio-packages.asc` (served at `https://nulavio.net/keys/nulavio-packages.asc`) and prints the fingerprint for `packaging/release.json` and the backup steps |
| Check the rehearsal | `scripts/release/release_manifest.py verify <rehearsal-out>` | Refuses an unfinished rehearsal, a tree with uncommitted or untracked changes, an `engine.json` that does not pin the source built, a package or SBOM whose SHA-256 changed, or a base commit not on `origin/main`; prints the tag `v<firefox>-<release>` |
| Sign and stage | `GNUPGHOME=<key-home> scripts/release/publish_release.sh <rehearsal-out> <fingerprint>`, or with `NULAVIO_KMS_KEY_ID` (and AWS credentials) instead of `GNUPGHOME` | Runs the check above, then `sign_repo.sh` with `NULAVIO_RELEASE_MANIFEST` (any package not listed with the same SHA-256 stops it), and `sign_apt_repo.sh` the same way, and stages `publish/rpm/` (the dnf repository), `publish/apt/` (the APT repository) and `publish/github/` (signed RPM, the .deb, their SBOMs, manifest, public key, `SHA256SUMS` and its signature, checked with only the published key). A rehearsal without its .deb is refused. Uploads nothing; writes the upload, tag and release commands to `publish/NEXT.md` |
| Upload | `R2_ACCESS_KEY_ID=… R2_SECRET_ACCESS_KEY=… R2_ACCOUNT=<account id> scripts/release/upload_repo.sh publish/rpm`, then `… publish/apt` | `publish/rpm/` goes to `https://packages.nulavio.net/rpm/` as it is (`repodata/` at the top): packages and hash-named metadata first, `repomd.xml.asc` and `repomd.xml` last. `publish/apt/` goes to `https://packages.nulavio.net/apt/`: `pool/` and the indexes first, then `Release` and `Release.gpg`, `InRelease` last. Nothing is deleted. Then `scripts/release/check_published.sh <version>-<release>` installs from the site's dnf and APT files in clean Fedora and Ubuntu containers; the APT file must be byte for byte the release commit's `site/apt/nulavio.sources`, so a change to it is deployed by the site workflow before a release runs |
| Download pages | `packaging/release.json` → `scripts/site/build_site.py --release` | `/baixar/` and `/en/download/` appear only when the file names a version and a key fingerprint and the public key in the repository has that fingerprint; their Ubuntu instructions only once it names the APT source file, which `release_metadata.py` adds after the first release published with a .deb |

