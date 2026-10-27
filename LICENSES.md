# Licences and third-party components

## Nulavio's own material

| Material | Licence | Notes |
|---|---|---|
| Source code (launcher, scripts, tests, configuration, start page, mockups) | **MPL-2.0** ([LICENSE](LICENSE)) | Matches Gecko's licence, so Track B patches can be shared with upstream |
| Documentation (`docs/`, `*.md`) | **CC BY 4.0** | Attribution: "Nulavio contributors" |
| Brand assets (`docs/brand/assets/`: name, symbol, wordmark, icons) | **All rights reserved; trademark rules apply** | The SVG/PNG files are in the repo so the project can be built and documented. Use to refer to Nulavio is allowed under [guidelines](docs/brand/guidelines.md). Use in other products or modified builds is not allowed |

The name "Nulavio" is a candidate trademark and is **not registered** ([status](docs/brand/strategy.md#trademark-and-availability-status)).

## Third-party components

Nothing below is **redistributed** by the Track A preview. Nulavio downloads pinned files from their official source, or uses software installed by the user's distribution.

| Component | Version | Licence | How Nulavio uses it |
|---|---|---|---|
| Mozilla Firefox (Gecko) | ≥ 140 (tested 158.0.1) | MPL-2.0; Firefox name and logo are Mozilla trademarks | Executes the distribution package unmodified. **Not redistributed; no Mozilla marks in Nulavio assets.** A modified build (Track B) must carry no Mozilla marks ([distribution policy](https://www.mozilla.org/en-US/foundation/trademarks/distribution-policy/)) |
| Firefox language packs | match engine | MPL-2.0 | Copied from the distribution package into the user's profile |
| uBlock Origin | 1.75.0 | GPL-3.0-only | Downloaded from AMO on user setup, SHA-256 pinned |
| Proton Pass extension | 1.41.1 | GPL-3.0-only | Downloaded on explicit request |
| KeePassXC-Browser | 1.10.4.1 | GPL-3.0-only | Downloaded on explicit request |
| Bitwarden extension | 2026.10.0 | Not declared on AMO. The upstream repo mixes GPL-3.0 and the Bitwarden License | Downloaded on explicit request; **must not be bundled** until clarified |
| Inter, JetBrains Mono, Noto Sans (fonts) | — | SIL OFL 1.1 | Referenced by CSS only; **not bundled** (system fonts are used if absent) |
| ruff (dev tool) | 0.17.2 | MIT | Lint/format in development and CI only; hash-pinned |
| actionlint, gitleaks, zizmor (dev tools) | 1.7.12, 8.30.1, 1.31.1 | MIT | Security scanners in development and CI only; version and SHA-256 pinned ([code scanning](docs/security/code-scanning.md)) |
| Opengrep (dev tool) | 1.32.0 | LGPL-2.1 | Runs Nulavio's own rules in development and CI only; version and SHA-256 pinned |
| ShellCheck (dev tool) | 0.11.0 | GPL-3.0 | Shell script checks in development and CI only, run as a separate program; version and SHA-256 pinned |

## SBOM

`python3 -I scripts/release/sbom.py > sbom/nulavio-preview.cdx.json` (CycloneDX 1.6). CI regenerates it on every run and attaches it as a build artifact.

The Companion app has its own: `scripts/release/sbom.py --companion --gradle-dependencies <report>` lists every library of its release build as Gradle resolved it, each with its Maven purl and the SHA-256 Gradle verifies ([build](docs/architecture/build.md#packages-s18)).
