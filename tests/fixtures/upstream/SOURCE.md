# Upstream fixtures: where they come from

Recorded on 2026-10-27 for `tests/unit/test_upstream_fast_path.py`. The tests read
them offline; they never reach the network.

| Path | Source | Licence |
|---|---|---|
| `mfsa/*.yml` | Mozilla's security advisories, [mozilla/foundation-security-advisories](https://github.com/mozilla/foundation-security-advisories) (`announce/<year>/`). Files unchanged; `mfsa2026-106`, `mfsa2026-118` and `mfsa2026-121` are excerpts (header and the first CVE entries) | MPL-2.0 |
| `product-details/*.json` | [product-details.mozilla.org](https://product-details.mozilla.org/1.0/) (`mozilla-releng/product-details`). Histories trimmed to 2026 (majors) and June 2026 onwards (stability) | MPL-2.0 |
| `github/announce/2026.json` | GitHub API listing of `announce/2026`, reduced to the files above (`name`, `type`) | Mozilla's data, MPL-2.0 |
| `github/commits/*.json` | GitHub API commits of `mozilla-releng/product-details` (branch `production`) on the release days, reduced to sha, dates and message | Mozilla's data, MPL-2.0 |
| `synthetic/*.yml` | Written for the tests, in the shape of real advisories | MPL-2.0 (Nulavio) |

The advisory files keep Mozilla's own first line (`## mfsa…`); in `mfsa2026-106.yml`
it reads `mfsa2026-105`, as upstream.
