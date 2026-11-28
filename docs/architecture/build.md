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

The image is rebuilt from nothing (`--no-cache`) when it is older than `NULAVIO_IMAGE_MAX_AGE_DAYS` days (default 1), because its Containerfile installs `rust` without a version and a cached layer would keep the compiler it had on the day it was built (#482). That costs a few minutes against a build of about an hour; a younger image is reused and the call takes seconds.

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
| `--enable-lto=cross` | Link-time optimisation across C++ and Rust, thin (#364). Mozilla's Linux release builds are cross-language too, but full and with profile-guided optimisation: the engine's configure picks full LTO only for a PGO build in Mozilla's automation, and thin for this one (`build/moz.configure/lto-pgo.configure`, `build/mozconfig.common`). Measured on its first build: 3.3 % on Speedometer and 4.7 % on the first start over the build without it, which leaves the build 32 % under Firefox 160.0 on Speedometer ([performance](performance.md#cross-language-lto-2026-11-17)). Rust is part of that link, so `rustc` is not asked for its own LTO: it refuses `-Clto` together with the `-Cembed-bitcode=no` that Cargo passes for a cross-language build. Costs: a longer link that needs more memory than the build laptop's 16 GiB cap allows (the release build runs with the build guard's runner profile: its container is capped at 48 GiB, at most 56, on the 16 vCPU / 64 GiB build machine, [above](#resource-limits-and-recovery-local-builds)), and the engine's own check that Rust code imports no networking function does not run in a cross-language build: Nulavio makes that reading itself on another build of the same source, which the engine pin and publishing depend on ([below](#the-networking-check-on-rust-code), [R79](../security/residual-risks.md)). Profile-guided optimisation, and full LTO with it, is after 1.0 ([#612](https://github.com/nulavio/nulavio/issues/612)): by an estimate the coordinating agent gave with the decision (not measured), it would about double the build's time, against the internal 24-hour target for urgent security releases (the commitment is 72 hours, [update policy](update-policy.md#urgency)) |
| `mozconfig.no-lto` (variant) | `NULAVIO_MOZCONFIG_EXTRA=mozconfig.no-lto` builds as before #364: no C++ LTO, and thin Rust LTO (`mk_add_options "export CARGO_RUSTCFLAGS=-Clto=thin"`) in place of the release default's fat pass over `gkrust`, which needed more than 17 GiB and stopped four guarded builds on the 32 GiB build laptop ([evidence](../research/evidence/release-rehearsal-2026-11-04.md)). The build system appends this value after its own `-Clto` and `rustc` keeps the last one; only `export` lines of the mozconfig reach the makefiles that run Cargo. For the build laptop and for trying an engine change quickly; never a release (`rehearse_release.sh` refuses a variant). The AddressSanitizer variant carries the same two lines |

## The networking check on Rust code

The engine has a build-time check, `check_networking` (`python/mozbuild/mozbuild/action/check_binary.py`): its Rust library may import none of a list of networking functions (`recv`, `send`, the `gethostby…`, `getserv…` and `getproto…` families). It lowers the chance that Rust code talks to the network around the engine's own network stack, and so around a proxy the person set. The build system runs it only when Rust gets its own link-time optimisation; a cross-language build and a sanitised one skip it. **The release build is cross-language since #364, so the engine's own check no longer runs in it.** Nulavio makes the check itself, on a build that can be read, and keeps the result in the repository (#430):

| Piece | What it does |
|---|---|
| `browser/build/mozconfig.no-lto` | A variant (`NULAVIO_MOZCONFIG_EXTRA=mozconfig.no-lto`): no cross-language LTO, thin Rust LTO. Its Rust library is one the check can read, and it fits the build laptop (16 GiB, 2 processors). A variant is never a release |
| [`scripts/build/networking_check.py`](../../scripts/build/networking_check.py) | Reads `libgkrust.a` of such a build as the engine's check does (the symbols at address 0, against the list in the very source tree that was built). It refuses a tree that is not the pinned release, a tree whose mozconfig is not this checkout's release mozconfig and variant (plus the machine's own lines), a tree that does not have this checkout's whole patch stack applied, a build whose library says nothing (no Rust LTO, cross-language LTO, a sanitiser), a library older than its source tree, and a reading that looks empty. A pass is written to `browser/build/networking-check.json`; a finding names the functions and exits 1 |
| `scripts/release/rehearse_release.sh --precheck <version>` | The pre-check of a new engine release: builds the variant, runs the script above right after the build, then the unit and the integration tests. No packages, no `manifest.json`, only `precheck.json`: nothing it leaves can be signed or published. `autobuild.py` runs it for every release Mozilla stages or publishes |
| The pin test (`tests/unit/test_track_b.py`) | `networking-check.json` must name the release `engine.json` pins, with the same source digest, and carry the digests of this tree's `mozconfig`, `mozconfig.no-lto` and patch stack: a pull request that moves the pin, changes a patch or changes the mozconfig fails CI until the record is of a reading made with them. Only the maintainer may record a release as accepted without the check, naming where he said so and carrying the same three digests (`networking_check.py <version> --inputs` prints them); that it is his word is for the reviewer to check |
| [`networking-check.yml`](../../.github/workflows/networking-check.yml) (#455) | The same reading made by a workflow: on the build machine, from `main`, it builds the variant, reads the Rust library and writes the **claim** ("this Firefox release, built with this mozconfig, variant, patch stack and Rust compiler, passed": a fixed JSON form with no date in it), and hands it to a second job, which builds nothing, writes the claim again from its own checkout, requires the two to be the same bytes and attests them (so the job that runs the build holds no token that can sign). Only the compiler is taken from the build job's claim, in a checked form: nothing but a build knows it. The claim also carries the digests of what makes the reading (the reader and the patch applier it asks, the build script, the build container's file, the workflow file), so an attestation made before one of them changed is not the one a later release asks for. It runs when the build configuration, the pin, the patch stack or one of those files changes on `main`, and by hand; about US$1 to US$3 a run. The container's file installs the Rust toolchain from the distribution without a version, and the standard library is part of what is read, so the claim names the compiler the build used: `rustc`'s version and commit, as the build's own configuration records them (#472). It is the only workflow that builds the variant, and only the claim leaves it |
| The signing job of `release.yml` | Writes the claim again from the release's manifest and base commit (`release_manifest.py networking-claim`) and requires an attestation of exactly those bytes by `networking-check.yml` on `main` (`gh attestation verify`), before it takes the signing role. The manifest names the Rust compiler the release was built with, so a release built with another compiler than the reading's asks for a claim nobody attested, and is refused: running `networking-check.yml` again (by hand; 15 to 20 minutes in its three runs so far) makes a reading with the compiler the distribution serves that day: on the build machine both workflows build the container anew in every run (seen in the reading's run: the base image is pulled and the packages installed each time). A machine that keeps its image used to keep its compiler: the build laptop's had `rustc` 1.99.0 on a day the build machine's had 1.99.1 (#482). Since then `build_nulavio.sh` builds the image through `scripts/build/build_image.sh` (a file the reading is read with, so changing it leaves an earlier attestation invalid), which builds it again with `--no-cache` when podman's copy is older than `NULAVIO_IMAGE_MAX_AGE_DAYS` (default 1; 0 every time) and prints the image's `rustc`, so the pre-check's log says which compiler it used. A laptop that built the day before can still be one release of Fedora's `rust` behind, for up to that many days; the attestation, not this, is what stops a release. The record in the repository plays no part in it, and a record that says "accepted" does not get round it. The build job says after its build whether that attestation exists, as a notice: a rehearsal (`publish: false`) stops before signing, and that is where it says whether a release of that build could be signed |
| `release_manifest.py verify` | Before anything is signed: the record **at the manifest's base commit** must name the Firefox release the rehearsal built and that commit's mozconfig, variant and patch stack, with a pass or the maintainer's word. A release the record does not cover is not published |
| The Rust guard (`tests/unit/test_track_b.py`) | No engine patch may touch a Rust file, a Cargo manifest, `third_party/rust/` or the build files that decide which Rust code is compiled and whether the check can run; nor rename, copy or carry a binary file. It is a tripwire, not a proof: a list of paths cannot name every file that can change which Rust code is compiled, which is why the record is also bound to the patch stack it was read with |

What this does not do, also in residual risk [R79](../security/residual-risks.md):

- **It does not check the release build's own binary.** That build's Rust library is LLVM bitcode until the final link, where the engine's own code imports those functions legitimately. It checks the same Rust source, with the same patches, in another build.
- **The record is a statement; the attestation is what a release rests on.** In a pull request, CI checks that the record names the pinned release and the tree's inputs; it cannot tell that the build and the reading happened. A release does not rest on it: the signing job requires the workflow's attestation of the claim (above). The record is written by the script on the machine that built (the build laptop), and what stands behind it is the review of the pull request that lands it: a second review by the project's rule for a CODEOWNERS path, which is a convention and not something GitHub enforces. To let a reviewer check it against a build of their own, the record carries the SHA-256 of the library that was read, of the mozconfig that built it and of the patch stack.
- **What a new reading costs.** A change to a patch or to the mozconfig needs one, because the record is bound to them. Whoever changes a patch builds the engine anyway; after a build of the variant, `python3 -I scripts/build/networking_check.py <version> --write` takes about a second, and the record goes into the same pull request.

The first record (Firefox 160.0, read on 2026-11-17 UTC) is the script's reading of a local build with patches 0001 to 0012: 267 052 symbols, 6 874 undefined names, none of the engine's 21 functions. Firefox 160.0.1 was read the same way on 2026-11-18. Patch 0013 (#527) then changed the stack with chrome JavaScript only, and the maintainer accepted the stack without a new reading (#562, 2026-11-19): the record says "accepted", with the new stack's digests. The release's attestation is still a reading, made by `networking-check.yml` on `main` (above).

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
| RPM | `scripts/release/make_rpm.sh [out]` | `packaging/rpm/nulavio.spec` in a Fedora 44 container: the tree under `/usr/lib64/nulavio`, `/usr/bin/nulavio`, desktop entry and icons, the repository's public key `site/keys/nulavio-packages.asc` at `/usr/share/nulavio/nulavio-packages.asc` (the only key the automatic updates import signing keys from); no install scripts; Requires python3 and util-linux, Recommends libsodium, gocryptfs, fuse3 and `libavcodec-free`, the system's codec library, which the engine loads at run time for AAC and for audio in MP4 (#377) |
| .deb | `scripts/release/make_deb.sh [out]` | The same tree under `/usr/lib/nulavio`, built in an Ubuntu 26.10 container; `Depends` computed from the libraries the engine needs and does not ship (readelf + apt-file); `Recommends` the same three and the codec library, by the names it has in Debian and Ubuntu releases (`libavcodec62 | libavcodec-extra62 | …`); an AppArmor profile (`/etc/apparmor.d/nulavio`, conffile) that only allows the user namespaces the engine's content sandbox needs on Ubuntu 24.04+, loaded by the package's only maintainer scripts (S23, [spikes](../security/phase5-spikes.md#apparmor-on-ubuntu)) |
| Check | `scripts/release/check_rpm.sh <rpm>`, `check_deb.sh <deb>` | Install in a clean container with the distribution's own repositories, with what the package recommends; the codec library is there after it; files as packaged (`rpm -V`, `dpkg --verify`), root-owned and not writable by users; `nulavio --version`; a headless start renders a page; the system Mozilla directory the engine reads (Marionette probe); the Nulavio tools answer; with a distribution Firefox installed beside Nulavio (a stub at the path each distribution uses) and no `NULAVIO_ENGINE`, the installed tools resolve to the package's own engine and its vendor is Nulavio (`engine_lookup_probe.py`, #575) |
| Sign | `GNUPGHOME=… scripts/release/sign_repo.sh <packages> <repo> <fingerprint>`, or with the key in AWS KMS: `NULAVIO_KMS_KEY_ID=alias/nulavio-release AWS_PROFILE=… AWS_REGION=us-east-1 scripts/release/sign_repo.sh …` (rpm 6 signs through `openpgp_sign.py`; AWS credentials enter the container as variables, by name) | `rpmsign`, `createrepo_c`, detached signature of `repomd.xml` and the public key. No `nulavio.repo`: the file that turns dnf's checks on is `site/rpm/nulavio.repo` (gpgcheck and repo_gpgcheck on), served by the site from git at `https://nulavio.net/rpm/nulavio.repo`, so writing to the package bucket cannot turn the checks off; the key is read from a read-only mount and its copy is deleted. With `NULAVIO_RELEASE_MANIFEST` it signs only a rehearsal that passes `release_manifest.py verify` and only the packages that manifest lists; the release key and a real KMS key are refused without one (#292), as by `sign_apt_repo.sh` |
| Check signing | `scripts/release/test_signed_repo.sh <packages>` | With a throwaway key made for the run: install from the signed repository in a clean container with both checks on, then confirm a repository with altered metadata is refused |
| Check the updates' key | `scripts/release/test_update_key.sh` | With throwaway keys made in a clean Fedora container and a stand-in `nulavio` package: `update-nulavio` installs a release signed with the current key; refuses one whose repository and `gpgkey` address changed to another key, without importing it, and refuses without the packaged key; a new key is accepted once a release signed with the current key carries it, or after the administrator accepts it in a manual `dnf upgrade` |
| Check KMS signing | `scripts/release/test_kms_signing.sh` (a step of the rehearsal) | Signing through AWS KMS without AWS: a throwaway RSA-4096 key is handed to a stand-in `aws` command and deleted, then `sign_repo.sh` in its KMS mode signs a test package and `repomd.xml`; dnf installs it with both checks on and refuses a copy with altered metadata |
| SBOM | `scripts/release/sbom.py --package <file> --engine-version <firefox> --release-version <firefox>-<revision>` | CycloneDX for one package: the root component `nulavio` at the release (`<firefox>-<revision>`, as the package and `packaging/release.json` name it, so two revisions on one Firefox never share a name and version), the engine as redistributed (at the Firefox version: Mozilla source release plus each patch in `browser/patches` as pedigree, by its path; each patch's SHA-256 is a property of the engine component, `nulavio:patch-sha256:<patch file>`, because CycloneDX 1.6 allows no other field in a patch), the pinned extensions, and the package's own SHA-256. Every component with an exact version carries a purl, and a CPE where the NVD has the product (the engine, uBlock Origin, KeePassXC-Browser, Bitwarden), so vulnerability scanners can match them; the distribution's libsodium, required as a version range, has neither |
| Companion SBOM | `scripts/release/sbom.py --companion [--apk <apk>]`; for the dependency graph too, first `android/gradlew -p android -q :app:dependencies --configuration releaseRuntimeClasspath > deps.txt`, then add `--gradle-dependencies deps.txt` | CycloneDX for the Android app: every library of the release build, from `android/app/gradle.lockfile` (no Gradle run needed), with its Maven purl and the SHA-256 from `android/gradle/verification-metadata.xml`. With Gradle's report, also the dependency graph at the versions Gradle resolved; the report must list the same libraries as the lock. It fails on an unresolved library, one the verification metadata does not pin, or a report that disagrees with the lock |

Measured on the reference laptop (2026-10-26): RPM 91 MB, built in about 2.5 minutes; .deb built in about 1 minute after the container's package index is fetched; each check about 30–60 seconds. Results of the first run: both packages install and pass every check; the signed repository installs with verified signatures and refuses altered metadata.

The APT repository (#211): `sign_apt_repo.sh <packages> <repo> <fingerprint>` builds `pool/` and `dists/stable/` with `apt-ftparchive` in an Ubuntu container (indexes also by hash, no MD5 or SHA-1, no `Valid-Until`, R57), then signs `Release` on the host: `InRelease` (cleartext, `openpgp_sign.py --clearsign` through KMS, or gpg) and `Release.gpg`, both checked with `gpgv` and the public key alone. The source file that turns apt's checks on is `site/apt/nulavio.sources`, served by the site, with the release key inline in `Signed-By`. `scripts/release/test_apt_repo.sh` signs a test package through a stand-in KMS and has apt install it with that file, then refuses a changed index, a changed package, a changed `InRelease` and another key.

### Signing in CI through AWS KMS

Goal: release builds signed by CI after the maintainer approves the run, so a Firefox security release does not wait for the maintainer's laptop. Decided on 2026-11-11: the existing release key (`298A 9093 BAAB B26F 79BB  29F4 BF47 E5FA 9EDB 8DB1`) is imported into AWS KMS, where it cannot be exported, so users keep the key they already trust. The original stays offline, with the revocation certificate.

| Part | Status |
|---|---|
| `scripts/release/openpgp_sign.py`: builds the OpenPGP signature (version 4, SHA-256) and asks KMS only for the RSA operation; refuses a KMS key whose modulus is not the release key's; works as rpm 6's signer (`%_openpgp_sign kms`) and for detached signatures (`repomd.xml`, `SHA256SUMS`) | **Done**: unit tests check every signature with gpg; `test_kms_signing.sh` checks rpm and dnf |
| `scripts/release/kms_import_key.py`: run once by the maintainer. Asks for the key's passphrase on the terminal, has gpg export the secret key with it (on standard input; the key's home is only read), decrypts the export's OpenPGP protection and checks the numbers against the public key, builds the PKCS#8 key material, wraps it with KMS's import parameters (RSA_AES_KEY_WRAP_SHA_256) and imports it without expiry, checks that KMS now signs as the release key | **Done**: unit tests for decrypting the export (and refusing a wrong passphrase), S2K, the PKCS#8 material (`openssl pkey -check`), the wrapping, and the whole run against a stand-in KMS; not yet run against KMS |
| `scripts/release/kms_setup.sh` with the policies in `ci/aws/`: the KMS key `alias/nulavio-release` (RSA_4096, SIGN_VERIFY, origin EXTERNAL) and the role `nulavio-release-signing`, which only a job of `release.yml` or `release-signing-check.yml` on `main`, in this repository's `release` environment, can assume (GitHub OIDC: the repository's subject template adds `job_workflow_ref`, on the immutable repository subject, #326), allowed Sign, GetPublicKey and DescribeKey on that key and on `alias/nulavio-companion` (the Companion's APK key, [ADR 0014](../adr/0014-companion-signing-key.md), the same kind, imported with `kms_import_key.py --pkcs8` on 2026-11-14) only. The key policy lets only that role and the account's administrator SSO roles sign, only with RSASSA_PKCS1_V1_5_SHA_256. The GitHub environment `release` asks for an approval by the maintainer's account (which coding agents also work with: [R62](../security/residual-risks.md)), accepts only `main`, has no tag rule, does not let administrators bypass it (checked 2026-11-15), and holds the key and role ARNs as variables. Both keys have the same key policy (compared in the account on 2026-11-15) | **Done** 2026-11-11 (account `lombello-dev`, us-east-1); the key is empty until `kms_import_key.py` runs |
| `.github/workflows/release-signing-check.yml` (manual): signs a test file through KMS in the `release` environment and verifies it with `site/keys/nulavio-packages.asc` | **Done** 2026-11-11: run 42963429141, `VALIDSIG 298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1` |
| `sign_repo.sh` and `publish_release.sh` sign through KMS when `NULAVIO_KMS_KEY_ID` is set (packages, `repomd.xml`, `SHA256SUMS`); the gpg-agent path stays for a release without AWS | **Done** 2026-11-11: the 160.0-0.2 RPM signed through the real KMS key installed in a clean Fedora 44 with both checks on (`RSA/SHA256, Key ID bf47e5fa9edb8db1`); nothing was published |
| `.github/workflows/release.yml`: build and rehearse on Blacksmith, then a signing job in the `release` environment (maintainer approval) and an upload job in `release-upload` that uploads and drafts the GitHub release (section below) | Written 2026-11-11; first run pending |

### Release workflow (CI)

`.github/workflows/release.yml`, started by hand from `main` (Actions → release → Run workflow), builds the Firefox release that `browser/build/engine.json` pins. Bump the pin first (`bump_engine.py`, a pull request).

| Job | Runs on | Holds | Does |
|---|---|---|---|
| `build` | Blacksmith `blacksmith-16vcpu-ubuntu-2404` (16 vCPU, 62 GiB, 738 GB disk, rootless Podman 5.8 with cgroup v2 limits; measured 2026-11-11), environment `build` (main only) | the Google Safe Browsing key (secret `GOOGLE_SAFEBROWSING_API_KEY`; it ships inside the browser anyway) | picks the package release one above every tagged, published or served one (`release_manifest.py next-release --also` with the versions the bucket's APT index and dnf index serve, #656, #723; the dnf one from the primary file `repomd.xml` names, through `release_manifest.py dnf-primary` and `dnf-served`, the APT one from the `Packages` file the `Release` text names, fetched by its hash (`by-hash/`, `apt-packages`) and read through `apt-served`; each index only once the release key's signature verifies: `InRelease`, one object as apt reads it, through `release_manifest.py verify-clearsigned`, and `repomd.xml` with `repomd.xml.asc` through `verify-signed`, both with `site/keys/nulavio-packages.asc` alone, #729; the compressed primary file is checked against `repomd.xml`'s checksum before it is decompressed (`dnf-compressed`); an index it cannot read or verify, one past the download and decompression size limits, or a download that stalls (60 s a transfer, 180 s with retries) stops the job), then `rehearse_release.sh` with the runner budget: verified source, build, unit and integration tests, RPM and .deb checked in clean containers, the signed-repository checks, SBOMs, `manifest.json`; a GitHub build-provenance attestation of the packages and the manifest |
| `sign` | GitHub-hosted `ubuntu-24.04`, environment `release` (the maintainer approves, see R62; main only) | the KMS signing role (OIDC), and the attestation token | checks the attestation (this workflow, `refs/heads/main`), `publish_release.sh` through KMS (the dnf and the APT repository), signs the Companion APK (no Flatpak bundle since #467), takes the role's session out of the environment, attests the signed files, and hands them to `publish` as one archive whose SHA-256 is its output |
| `publish` | GitHub-hosted `ubuntu-24.04`, environment `release-upload` (main only, no reviewer: it runs after the approved `sign` job, #334) | the bucket-scoped R2 upload token (secrets `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`); no OIDC token, and the signing role does not trust this environment | refuses the archive unless its SHA-256 is `sign`'s output, and refuses a release older than any tag, any GitHub release (drafts included) or the version the bucket's APT index serves (`release_manifest.py not-older`: a re-run of this job in an older run would roll the bucket back, #417), then `upload_repo.sh` for each repository (packages first, signed metadata last, the dnf repository's signed pair under its revision's keys before the served one (#740), nothing deleted, and no package written over one with other bytes, #656), `check_published.sh` (installs from `https://nulavio.net/rpm/nulavio.repo` in a clean Fedora and from `https://nulavio.net/apt/nulavio.sources` in a clean Ubuntu, with the signature checks on, and requires the new version), the Flathub manifest, drafts the GitHub release; measures the media in the history against [ADR 0013](../adr/0013-repository-layout.md)'s budget (`org_layout_measure.py --budget`: the job summary and `media-budget.json` in the `published` artifact) |
| `companion` | GitHub-hosted `ubuntu-24.04`, `main` only (it attests), no environment, no secret | nothing | The Gradle wrapper checked as an official release (`gradle/actions/wrapper-validation`, as in `ci.yml`) before it runs with the attestation token. `build_companion.sh`: first `companion_version.py`, which refuses an app whose `android/` changed since the last release that shipped the APK while `versionCode` did not go up or `versionName` stayed the same (#286); then Nulavio Companion's release APK built twice from two clean copies of `android/` (Gradle and every dependency checksum-verified), the same bytes required; its SBOM; a build-provenance attestation of both. `sign` then checks that attestation, signs the APK through KMS with the Companion's own key (`sign_companion.sh`, `apk_sign.py`, [ADR 0014](../adr/0014-companion-signing-key.md)), requires `apksigner verify` to pass v2 and v3 with the certificate `site/keys/nulavio-companion.der`, and attaches it with its SBOM (in `SHA256SUMS`). `publish_release.sh` refuses a build whose branding prefs offer phone pairing without it ([ADR 0005](../adr/0005-phone-profile-unlock.md)'s release order) |

The integration step runs in the pinned container `ci/containers/fedora-release-itest.Containerfile` (`NULAVIO_INTEGRATION_IMAGE`, `scripts/release/run_integration.sh`), the same on the laptop and in CI. It fixes the fonts the component gallery's pixel baselines were made with (Noto and Liberation, as on the reference Fedora 44 KDE laptop) and has the tools the tests use. Run on Blacksmith's Ubuntu host, the gallery rendered 44 px taller and its baselines failed. FUSE works there for the Vault tests: `/dev/fuse` is passed in, and `SYS_ADMIN` applies only inside the rootless user namespace. Without the variable, the suite runs on the host as before. Either way the script tells the tests that the engine is a build of this tree (`NULAVIO_BUILT_FROM_TREE=1`): a test of what an engine patch adds then fails when the engine does not have it, where it skips on an older engine with this tree's Shell (a development package).

#### After a failed publish

The `publish` job uploads the whole dnf repository (packages, then its signed metadata: first under keys named after the revision, then the served pair), then the whole APT repository, checks the install, and only then drafts the GitHub release. When it fails after an upload, the bucket holds that run's packages under their revision, `v<firefox>-<release>`, but there is no tag and no draft. A new run's build job counts the versions the bucket's APT and dnf indexes serve (#656, #723), and `upload_repo.sh` refuses to write a package over one with other bytes (exit 3, with the object's name and upload time), before it writes anything of that repository.

First, while that run's `signed` artifact lasts (7 days): **re-run its failed `publish` job** (Actions → the run → Re-run failed jobs). It uploads the same signed bytes again, which `upload_repo.sh` and `not-older` let through. This is the way out in every state below.

Otherwise, before starting a new run, find out how far that run got (`https://packages.nulavio.net/apt/dists/stable/main/binary-amd64/Packages`, and `https://packages.nulavio.net/rpm/repodata/repomd.xml` with the primary file it names; the bucket serves no directory listing. Or read the run's publish log):

1. **Both repositories serve that revision** (the upload finished; a later step failed). A new run builds the next revision by itself. `whats_new.py require` then asks for `packaging/whats-new/<firefox>-<next release>.json`: rename the record (and its `version`) in a pull request before starting the run.
2. **dnf serves it, APT does not** (the APT upload failed). As in 1: a new run reads the dnf index too and builds the next revision by itself (#723); rename the whats-new record the same way. The RPM of the failed run stays in the bucket, unlisted once the new run's dnf metadata is up: people may have installed it, so it is never deleted or replaced.
3. **Neither serves it** (the upload stopped before the dnf metadata). A new run picks the same revision and stops at the upload. Those packages are in no served metadata: the maintainer deletes them from the bucket (`nulavio-packages`, `rpm/x86_64/` and `apt/pool/main/n/nulavio/`, after checking that neither the primary file `rpm/repodata/repomd.xml` names nor `apt/dists/stable/main/binary-amd64/Packages` lists them; the failed run may have uploaded a newer primary file that does list them but is not the one `repomd.xml` names), then re-runs the new run's `publish` job.
4. **The build job stops at the signature of `repomd.xml`** (`repomd.xml.asc is not a good signature`): the upload stopped between `repomd.xml.asc` and `repomd.xml`, so the bucket serves a new signature beside the old file. dnf refuses the repository too (`repo_gpgcheck=1`), so it is urgent. The route of state 3 does not work here: a new run stops at that signature before it can upload a pair of its own, and the build job does not fall back to another pair (it stays fail-closed). Re-run the failed `publish` job while it can; otherwise copy the signed pair `upload_repo.sh` left under the failed run's revision onto the served keys (#740). From the repository's root, paste the block below with `<firefox>-<release>` set to the failed run's revision (the `v<firefox>-<release>` its `publish` log names) and `<account id>` to the Cloudflare account id. It needs `curl` 8.4.0 or later, `python3`, `zstd` and the AWS CLI. It runs in a subshell that stops at the first failure, so nothing is written unless every check before it passed:
   - Over HTTPS, before it asks for anything: the revision's pair verifies with the release key, and the served signature is that run's.
   - It then asks for the R2 upload token (`nulavio-packages-upload`, the key pair the `release-upload` environment holds as `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`; GitHub does not show a secret again, so use the maintainer's own copy of that token), with `read -rs`, into shell variables that are never exported (it turns `set -a` off first: left on, it would export them). Each `aws` call gets it from `r2()`, a subshell that exports it and becomes `aws`: it is never on a command line, in the shell history, or in the environment of `curl`, `python3` or `zstd`.
   - The live objects in R2, read with that token, pass the same checks: a CDN cache can serve other bytes than the bucket holds. The primary file that pair names, read from R2 too and checked against its checksum, lists that revision: a pair that lists another one, or names a primary file R2 does not hold, is never written.
   - Unless R2 already serves that pair (an earlier paste wrote it, then stopped at the CDN), it uploads it onto the served keys, in the upload's order (the signature, then `repomd.xml`). Either way it reads the served pair back from R2.
   - What `https://packages.nulavio.net` now serves, as dnf and the build job read it: the same pair, which verifies, naming a primary file that lists that revision.
   - Every download is bounded as in the build job: 60 s a transfer and 180 s with retries for `curl`, 30 s to connect and 60 s a read for `aws`, 1 MiB for the pair and 8 MiB for the primary file over HTTPS (`curl --max-filesize`, which bounds a body sent without `Content-Length` only from curl 8.4.0 on, so the block requires that version before its first download; Fedora 44 and Ubuntu 24.04 ship later ones), and 32 MiB for any file the block writes, what `aws` reads from R2 and the decompressed primary file included (`ulimit -f`; a lower limit the shell already has stays).
   - Nothing in the bucket serialises the block with a publish. It compares R2's served signature with the revision's before it writes, so a newer publish stops it there, but a newer pair uploaded between that read and the block's upload would be rolled back. What keeps them apart is the `release` environment's approval, which a new run's upload waits for: do not approve a run while the block runs. A re-run of a `publish` job asks for no approval (#334): do not start one meanwhile either.

   ```sh
   (
   set -euo pipefail
   set +a  # a shell left in allexport would export what read assigns
   rev=<firefox>-<release>
   rpm=https://packages.nulavio.net/rpm
   bucket=s3://nulavio-packages/rpm
   r2=https://<account id>.r2.cloudflarestorage.com
   fpr=298A9093BAABB26F79BB29F4BF47E5FA9EDB8DB1  # site/keys/nulavio-packages.asc
   soft=$(ulimit -S -f)  # a lower limit the shell already has stays: it may not be raised
   if [[ $soft == unlimited ]] || (( soft > 32768 )); then ulimit -f 32768; fi
   # Before curl 8.4.0, --max-filesize does not bound a body sent without Content-Length (curl's man page).
   read -r _ curl_version _ < <(curl --version)
   IFS=. read -r major minor _ <<< "$curl_version"
   if ! [[ $major =~ ^[0-9]+$ && $minor =~ ^[0-9]+$ ]] || (( major < 8 || (major == 8 && minor < 4) )); then
       echo "curl $curl_version: the block needs curl 8.4.0 or later, whose --max-filesize bounds every download" >&2
       exit 1
   fi
   tmp=$(mktemp -d)
   trap 'rm -rf "$tmp"' EXIT
   mkdir "$tmp/https" "$tmp/r2" "$tmp/after" "$tmp/public"
   get() {  # <size> <file> <url>
       curl -fsS --proto '=https' --retry 3 --max-time 60 --retry-max-time 180 --max-filesize "$1" -o "$2" "$3"
   }
   verify() {  # <dir>: its repomd.xml.asc is the release key's signature of its repomd.xml
       python3 -I scripts/release/release_manifest.py verify-signed "$1/repomd.xml" "$1/repomd.xml.asc" \
           --key site/keys/nulavio-packages.asc --fingerprint "$fpr"
   }
   same() {  # <dir> <dir>: the same pair
       cmp "$1/repomd.xml.asc" "$2/repomd.xml.asc"
       cmp "$1/repomd.xml" "$2/repomd.xml"
   }
   primary() {  # <dir>: the key of the primary file its repomd.xml names, repodata/<sha256>-primary.xml.zst
       python3 -I scripts/release/release_manifest.py dnf-primary "$1/repomd.xml"
   }
   lists() {  # <dir>: its primary.xml.zst matches the checksum its repomd.xml gives and lists $rev
       local served
       python3 -I scripts/release/release_manifest.py dnf-compressed "$1/repomd.xml" "$1/primary.xml.zst"
       zstd -q -d -o "$1/primary.xml" "$1/primary.xml.zst"
       served=$(python3 -I scripts/release/release_manifest.py dnf-served "$1/repomd.xml" "$1/primary.xml")
       echo "the dnf index lists nulavio $served"
       [[ $served == "$rev" ]]
   }
   # Over HTTPS: the pair is that run's, signed by the release key, and the served signature is that run's.
   get 1M "$tmp/https/repomd.xml" "$rpm/repodata/$rev/repomd.xml"
   get 1M "$tmp/https/repomd.xml.asc" "$rpm/repodata/$rev/repomd.xml.asc"
   get 1M "$tmp/https/served.asc" "$rpm/repodata/repomd.xml.asc"
   verify "$tmp/https"
   cmp "$tmp/https/repomd.xml.asc" "$tmp/https/served.asc"
   # The upload token, typed at the prompts (not echoed) into variables this shell never exports.
   unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_PROFILE AWS_DEFAULT_PROFILE
   read -rsp 'R2_ACCESS_KEY_ID: ' AWS_ACCESS_KEY_ID; echo
   read -rsp 'R2_SECRET_ACCESS_KEY: ' AWS_SECRET_ACCESS_KEY; echo
   r2() {  # <from> <to>: aws s3 cp, as upload_repo.sh's r2() runs it; only here does the token reach a process
       (
       export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null \
           AWS_PAGER='' AWS_REGION=auto AWS_DEFAULT_REGION=auto \
           AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
       exec aws --endpoint-url "$r2" --cli-connect-timeout 30 --cli-read-timeout 60 s3 cp --only-show-errors "$1" "$2"
       )
   }
   # The live objects in R2, which a CDN cache may not show: the same checks.
   r2 "$bucket/repodata/$rev/repomd.xml" "$tmp/r2/repomd.xml"
   r2 "$bucket/repodata/$rev/repomd.xml.asc" "$tmp/r2/repomd.xml.asc"
   r2 "$bucket/repodata/repomd.xml.asc" "$tmp/r2/served.asc"
   r2 "$bucket/repodata/repomd.xml" "$tmp/r2/served.xml"
   verify "$tmp/r2"
   cmp "$tmp/r2/repomd.xml.asc" "$tmp/r2/served.asc"
   href=$(primary "$tmp/r2")
   r2 "$bucket/$href" "$tmp/r2/primary.xml.zst"
   lists "$tmp/r2"
   # Those verified bytes onto the served keys, in the upload's order: the signature, then repomd.xml. The served
   # signature already is the revision's (cmp above): when the served repomd.xml is too, an earlier paste wrote them.
   if cmp -s "$tmp/r2/repomd.xml" "$tmp/r2/served.xml"; then
       echo "R2 already serves $rev's pair: nothing to upload"
   else
       r2 "$tmp/r2/repomd.xml.asc" "$bucket/repodata/repomd.xml.asc"
       r2 "$tmp/r2/repomd.xml" "$bucket/repodata/repomd.xml"
   fi
   r2 "$bucket/repodata/repomd.xml.asc" "$tmp/after/repomd.xml.asc"
   r2 "$bucket/repodata/repomd.xml" "$tmp/after/repomd.xml"
   same "$tmp/r2" "$tmp/after"
   echo "the bucket serves $rev's pair; checking what https://packages.nulavio.net serves"
   # What dnf and the build job read: that pair, which verifies with the committed key alone and lists $rev.
   get 1M "$tmp/public/repomd.xml" "$rpm/repodata/repomd.xml"
   get 1M "$tmp/public/repomd.xml.asc" "$rpm/repodata/repomd.xml.asc"
   same "$tmp/r2" "$tmp/public"
   verify "$tmp/public"
   href=$(primary "$tmp/public")
   get 8M "$tmp/public/primary.xml.zst" "$rpm/$href"
   lists "$tmp/public"
   echo "restored: dnf is served $rev's pair, which verifies and lists $rev"
   )
   ```

   It ends with `restored: …`; anything else stopped it, and nothing after the failed step ran. If a `cmp` before the upload reports a difference, the served signature is not that run's: find the revision whose `repomd.xml.asc` it is before copying anything. If it stops after `the bucket serves …`, the bucket holds the restored pair and the site does not serve it yet: a CDN cache still holds the old `repomd.xml`. Wait for it to expire, or purge those two URLs in Cloudflare, and paste the block again: every check then passes, and since R2 already serves that pair it writes nothing. A purge does not help when it stops at the public primary file because that file is over 8 MiB, the bound the build job reads it with: the file is named by its digest, so the CDN and R2 hold the same bytes, and the block fails the same way each time. The bucket then holds the restored pair; find out why the primary file grew before pasting the block again. If it stops at `the dnf index lists nulavio …` with another version before the upload, the pair under that revision does not list it and nothing was written: find out why before going on. The packages and the primary file that pair names went up before it, so dnf then serves the failed run's revision and APT does not: go on as in state 2. A run made from a commit before #740 left no such pair; for it, only the re-run of its `publish` job restores one. The APT side has no such state: the build reads `InRelease`, one object, uploaded last, and the `Packages` file it names by hash.

The maintainer then publishes the draft (which creates the tag), sets `version` in `packaging/release.json` by pull request (the site workflow rebuilds the download pages), and adds the changelog entry; the job summary lists these steps. `publish: false` stops after the build: a rehearsal in CI. The build machine never holds the signing role or the upload token.

### Which tests run where

A test that pull request CI does not run can be broken by a merge without anyone seeing it. Two runs of the 160.0-0.6 release stopped on such tests, about an hour in (#376, #378). This is what runs where, and how soon a failure shows.

| Where | When | Engine and container | What it runs | What it cannot show |
|---|---|---|---|---|
| Pull request CI (`ci.yml`, GitHub-hosted) | every pull request and every push to `main`; the integration jobs are skipped when only Markdown changed | distribution Firefox with this tree's launcher (Track A): Fedora's RPM (`fedora-itest`) and Mozilla's APT build (`ubuntu-itest`) | the unit tests (the Vault ones on real gocryptfs where the runner has it) and the integration suite as far as a stock engine goes | anything that needs Nulavio's own engine: the engine patches, the built-in Shell, the branding and the packed notes of a version. Those tests skip. The two containers have no gocryptfs and no `/dev/fuse`, so the integration tests of a protected profile skip too |
| Nightly rehearsal (`rehearsal.yml`, Blacksmith) | every night that `main` has something other than Markdown since the last green night (02:17 UTC), and by hand | a build of `main` in the release configuration, tested in `fedora-release-itest` with FUSE | `rehearse_release.sh`, the same script as the release's `build` job: the build, the unit tests, the whole integration suite on that build with `NULAVIO_BUILT_FROM_TREE=1` (a test of an engine patch fails where it would skip), the RPM and the .deb in clean containers, the signed-repository checks, the SBOMs and the manifest | signing, upload and what `check_published.sh` installs from the site; the Flatpak and the Companion jobs of `release.yml`; the release-only guards (an open draft, the next version's notes: a build of `main` without notes for the next version is packed without them) |
| AddressSanitizer (`asan.yml`, Blacksmith) | monthly and by hand | a sanitised build of `main` (`mozconfig.asan`), in `fedora-release-itest` | the integration suite, failing on any memory error report | the packages; it is a variant, never a release |
| Release (`release.yml`) | by hand, for a release or with `publish: false` | as the nightly rehearsal | everything above, then the Flatpak, the Companion, signing and publishing | nothing more: it is the last place a failure can show, which is what the nightly rehearsal is for |
| The build laptop | by hand, and the upstream timer's pre-build | a local build, or a published build with the branch's Shell (`NULAVIO_BUILT_FROM_TREE=0` for an engine older than the tree) | whatever is asked: one module, or the whole rehearsal | the build machine's timing |

**When the nightly rehearsal fails** it opens one issue (labels `bug` and `P1`, found again by a hidden marker in its body and by its author, the workflow's bot), adds a comment each further night it fails, and closes the issue on the first green night (`scripts/ci/rehearsal_issue.py`). The issue names the commit and the run; the run's summary has the rehearsal's table of steps and the `rehearsal-logs` artifact has the failing step's log. A failure is therefore reported within a day of the merge that caused it. A night whose build was skipped or cancelled says nothing and touches no issue. Started by hand, the workflow always builds and only says what it would do to the issue (`--dry-run`); such a run is not counted as a green night, so the night after it builds and is the one that closes an open issue.

**What it costs:** about an hour of the 16-processor runner, about US$3, each night that builds (its first run, on 2026-11-16, took 70 minutes: 19 of build, 3 of unit tests and 48 of integration tests). `scripts/ci/rehearsal_needed.py` skips the build when `main` is at the commit of the last green night or only Markdown changed since. After a failed night it builds again even with nothing new, which is how a test that fails only sometimes shows. The job holds the `build` environment for the Safe Browsing key and has `contents: read` only: no attestation, no signing role, no upload token, and no package leaves the runner.

### Flatpak (Flathub)

The Flatpak `net.nulavio.Nulavio` packages the same signed build as the RPM: the portable archive `nulavio-<firefox>-<release>.linux-x86_64.tar.xz` that `rehearse_release.sh` makes from the installed tree (sorted, owner 0, the commit's time), that the manifest lists with its SHA-256 and that `publish_release.sh` attaches to the GitHub release. It is not built from source on Flathub: a Firefox build does not fit Flathub's builders, and the binary then differs from the one the RPM users run (Mozilla's and LibreWolf's Flatpaks do the same).

`scripts/release/flatpak_manifest.py` writes the build directory (manifest `net.nulavio.Nulavio.json`, desktop entry renamed to the app ID, AppStream metadata from `packaging/flatpak/` with this release, entry point, Flatpak-only preferences). Runtime `org.freedesktop.Platform` 26.08; its `codecs-extra` extension brings the patented codecs.

| Permission | Why |
|---|---|
| `--share=network`, `--share=ipc`, `--socket=wayland`, `--socket=fallback-x11`, `--socket=pulseaudio`, `--device=all`, `--socket=pcsc` | A browser: network, display, sound, cameras and FIDO2 security keys (WebAuthn), smart cards; as Mozilla's Flatpak |
| `--persist=.nulavio`, `--filesystem=xdg-download` | Profiles stay in the app's own directory (`~/.var/app/net.nulavio.Nulavio`); downloads go to the Downloads folder; nothing else of the home |
| `--talk-name=org.freedesktop.NativeMessagingProxy` with the preference `widget.use-xdg-desktop-portal.native-messaging-proxy=1` | Password-manager apps (KeePassXC, Bitwarden) through `xdg-native-messaging-proxy` on the host ([spike](../security/phase5-spikes.md#flatpak-and-native-messaging)) |
| `--own-name=org.mozilla.nulavio.*`, `--talk-name=org.freedesktop.FileManager1`, `org.a11y.Bus`, NetworkManager (system bus) | Remoting (a second start opens a window in the running browser), "show in folder", accessibility, online state |

Codecs in the Flatpak (checked on 2026-11-16, runtime 26.08): the runtime carries the codec library the engine loads (`libavcodec.so.62`) with AAC, MP3, Opus and FLAC, and its `codecs-extra` extension, installed with the runtime and first in the library path, adds H.264. The Flatpak asks for nothing more (#377).

Not in the Flatpak: the Vault (it needs `gocryptfs` and FUSE on the host), `nulavio run --confined` (bubblewrap inside the sandbox), and the Connect features that talk to desktop services over D-Bus (KDE Connect, activities). The AppStream text says so. `tests/unit/test_flatpak.py` refuses permissions that undo the sandbox (the home, the host, any D-Bus name, the Flatpak service).

Every release run builds it: the `flatpak` job of `release.yml` builds and installs it from the archive that run made with Flathub's own builder (`org.flatpak.Builder`, with `--compose-url-policy=full` as `flathub-build` does), runs `flatpak-builder-lint` on the manifest and the repository, and `check_flatpak.sh` starts it headless in the sandbox and requires a rendered page. Measured on 2026-11-11 with 160.0-0.3: builds, renders, both lints clean. The `publish` job writes the Flathub manifest (`--url`: the GitHub release asset and its SHA-256) into the `published` artifact.

Releases do not carry the Flatpak (#467, decided on 2026-11-17 in the [feature review](../product/feature-review-2026-11.md#l6-flatpak-bundle-attached-to-releases), reversing #274): a bundle has no update channel, so someone who installed one stayed on that version and its security holes ([R75](../security/residual-risks.md)). The Flatpak comes with Flathub, which updates it (#88 to #91). Until then the `flatpak` and `flatpak-check` jobs stay in `release.yml` as a check that Flathub's build still works with each release, and `sign` neither waits for them nor takes what they make: the job still bundles what it built (`flatpak build-bundle`, kept with the run for 30 days), and `flatpak-check`, which has no token and no secret, checks that bundle against the attested archive (`check_flatpak_bundle.py`, #324): imported into a temporary OSTree repository, its one ref must hold the archive file for file (bytes and executable bit), plus exactly what `flatpak_manifest.py` adds (the preferences, the entry point, the desktop entry, the metainfo, the archive's own icons), Flathub's AppStream data (data files only), and the manifest's runtime, SDK and permissions in its `metadata`; its header must hold only what `flatpak build-bundle --runtime-repo` writes. A failed Flatpak job changes nothing in the release; it is read in the run. `publish_release.sh` still accepts a bundle given by hand (`NULAVIO_FLATPAK_BUNDLE`, checked as above), and `release.yml` no longer gives it one. The download pages offer no bundle: `release_metadata.py` records none, `build_site.py` refuses a `flatpak_bundle` in `packaging/release.json` and any Flatpak block in a page, and the pages tell people who installed the bundle of 160.0-0.4 to 0.6 that it gets no fixes, how to move to the RPM or APT package with their bookmarks and passwords, and how to remove it.

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
| Check the rehearsal | `scripts/release/release_manifest.py verify <rehearsal-out>` | Refuses an unfinished rehearsal, a tree with uncommitted or untracked changes, an `engine.json` that does not pin the source built, a package or SBOM whose SHA-256 changed, a base commit not on `origin/main`, or a release whose Rust code the networking check's record does not cover (`browser/build/networking-check.json` at the base commit is missing, names another Firefox release or source digest, was read with another mozconfig, variant or patch stack, or says neither "passed" nor "accepted" with an issue number; [above](#the-networking-check-on-rust-code)); prints the tag `v<firefox>-<release>` |
| Sign and stage | `GNUPGHOME=<key-home> scripts/release/publish_release.sh <rehearsal-out> <fingerprint>`, or with `NULAVIO_KMS_KEY_ID` (and AWS credentials) instead of `GNUPGHOME` | Runs the check above, then `sign_repo.sh` with `NULAVIO_RELEASE_MANIFEST` (any package not listed with the same SHA-256 stops it), and `sign_apt_repo.sh` the same way, and stages `publish/rpm/` (the dnf repository), `publish/apt/` (the APT repository) and `publish/github/` (signed RPM, the .deb, their SBOMs, manifest, public key, `SHA256SUMS` and its signature, checked with only the published key). A rehearsal without its .deb is refused. Uploads nothing; writes the upload, tag and release commands to `publish/NEXT.md` |
| Upload | `R2_ACCESS_KEY_ID=… R2_SECRET_ACCESS_KEY=… R2_ACCOUNT=<account id> scripts/release/upload_repo.sh publish/rpm`, then `… publish/apt` | `publish/rpm/` goes to `https://packages.nulavio.net/rpm/` as it is (`repodata/` at the top): packages and hash-named metadata first, then the signed pair under keys named after the revision (`repodata/<firefox>-<release>/repomd.xml.asc` and `repomd.xml`, #740), `repomd.xml.asc` and `repomd.xml` last. `publish/apt/` goes to `https://packages.nulavio.net/apt/`: `pool/` and the indexes first, then `Release` and `Release.gpg`, `InRelease` last. Nothing is deleted. Before the first write, each staged package the bucket already holds under its name is downloaded and compared: other bytes stop the upload with exit 3 ([after a failed publish](#after-a-failed-publish)). Then `scripts/release/check_published.sh <version>-<release>` installs from the site's dnf and APT files in clean Fedora and Ubuntu containers; each must be byte for byte the release commit's `site/rpm/nulavio.repo` or `site/apt/nulavio.sources` (#327), so a change to either is deployed by the site workflow before a release runs |
| Download pages | `packaging/release.json` → `scripts/site/build_site.py --release` | `/baixar/` and `/en/download/` appear only when the file names a version and a key fingerprint and the public key in the repository has that fingerprint; their Ubuntu instructions only once it names the APT source file, which `release_metadata.py` adds after the first release published with a .deb |

