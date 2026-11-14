# site/: nulavio.net

Read the root [AGENTS.md](../AGENTS.md) first; its rules apply here and are not repeated.

## What is here

Static pages in Portuguese and English: the landing (`index.html`, `en/index.html`), which presents Nulavio as it is meant to ship; the engineering document (`engenharia/`, `en/engineering/`), which says what is ready today; the download pages, built from `packaging/release.json`; the waitlist pages and their worker (`_worker.js`, `_routes.json`); the dnf and APT files and the public keys (`rpm/`, `apt/`, `keys/`); the headers (`_headers`).

## Rules that apply here

- Static pages (I2): no JavaScript in them, no third-party resource, no cookie; security headers in `_headers`.
- The worker answers `/api/*` and the two link pages only, and stores the address, the language, the platform, the time and the hash of the link's key, nothing else. An entry changes or goes only through its link, never on an address alone; no answer (status, headers, body, whether the database was written) tells whether an address or a key is on the list.
- Claims (I11): a claim or comparison row changes in both languages, and what is ready today is never confused with what is planned. The engineering pages must agree with `packaging/release.json` and the download pages.

Documents: CONTRIBUTING's [Website](../CONTRIBUTING.md#website-nulavionet) section (build, deploy, the waitlist's operation), [residual risks](../docs/security/residual-risks.md) R69 and R71.

## Checks

- `python3 -I scripts/site/build_site.py` (writes `dist/site/`), then `python3 -I tests/run.py unit` (`test_site.py` runs the worker under Node and its SQL in SQLite; `test_site_discovery.py`).
- Look at the built pages in both languages, at phone width too, before claiming a visual change is done.

## Not here

The deploy workflow is `.github/workflows/site.yml` and its tools are locked in `ci/site/`; the build script is `scripts/site/build_site.py`; the brand assets come from `docs/brand/`.
