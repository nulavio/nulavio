# Track B build (Nulavio from source)

Status: **development spike, first build succeeded on 2026-10-24.** Builds are not releases: they are not signed or distributed (see "Release blockers"). Since 2026-10-25 they include a Google Safe Browsing key (see below).

## Pipeline

```
scripts/build/build_nulavio.sh <version>
 ├─ scripts/upstream/fetch_firefox_source.py   SHA256SUMS signature checked against the pinned Mozilla key,
 │                                              tarball hashed while streaming, extracted only on match
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

Work directory (outside the repository): `${NULAVIO_BUILD_DIR:-~/.cache/nulavio-build}`, containing `downloads/`, `firefox-<v>/` (source and `obj-nulavio/`), `mozbuild/` (toolchains) and `logs/`. Deleting it removes everything the build created. Nothing is installed on the host.

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
| Builds without `MOZILLA_OFFICIAL` (Nulavio) default to **`devtools.chrome.enabled=true` and `devtools.debugger.remote-enabled=true`** (privileged Browser Console and Browser Toolbox connections, a "paste this into the console" scam vector), plus chrome console output on stdout. The Guard did not catch it because it audits profile files, not engine defaults | `modules/libpref/init/all.js` | Nulavio branding restores Mozilla's shipped values (all `false`); `test_13` asserts them |
| Without `MOZILLA_OFFICIAL`, the phishing list is named `googpub-phish-proto` and the Safe Browsing client id is `Firefox` instead of Firefox's approved `navclient-auto-ffox`. `MOZILLA_OFFICIAL` is not set: it would claim Mozilla's Google-approved identity | `modules/libpref/init/all.js`, `nsUrlClassifierUtils.cpp` | Nothing to do; `test_14` reads the list name from the engine |

## Release blockers for Track B

1. ~~Google Safe Browsing API key~~ **Resolved 2026-10-25** (section above). What remains: a quota review with Google, and either access to Google's download-protection API or acceptance of R15 for downloads.
2. Signed packages and repository ([update policy](update-policy.md)).
3. Policy/legal confirmation for keeping Firefox's add-on application ID and using AMO.
4. Brand clearance ([strategy](../brand/strategy.md#trademark-and-availability-status)).

## Running the build output

`./mach package` produces `obj-nulavio/dist/nulavio-<version>.en-US.linux-x86_64.tar.xz`. To test it with the Nulavio launcher and tests:

```sh
tar -xJf ~/.cache/nulavio-build/firefox-158.0.1/obj-nulavio/dist/nulavio-158.0.1.en-US.linux-x86_64.tar.xz -C ~/.cache/nulavio-build/install
python3 -I scripts/build/make_distribution.py --out ~/.cache/nulavio-build/install/nulavio/distribution
python3 -I scripts/build/make_tools.py --out ~/.cache/nulavio-build/install/nulavio/nulavio-tools  # Vault helper for the Shell (S6)
NULAVIO_ENGINE=~/.cache/nulavio-build/install/nulavio/nulavio python3 -I tests/run.py integration
# add NULAVIO_NETWORK_TESTS=1 to also run the Safe Browsing end-to-end test (contacts Google)
```
