# PrivacyTests.org's fingerprinting probe pages

These files are copied, unchanged, from [privacytests/privacytests](https://github.com/privacytests/privacytests) at commit `ec9ad19f3cc7b2f02bf7d511b3d78cae115b0111` (2026-11-17), directory `static/`. The first copy was of `12e48c75` (2026-11-11), then `5e675fa8` (2026-11-16); the move to this one renamed the Settings probe `Time zone` to `Time zone region` and reworded its description, nothing else (#587). The site's comparison reads the old name in their published results and in a release's log as the new one (`RENAMED` in `scripts/site/privacytests_pages.py`). They are © Arthur Edelstein and contributors, under the MIT license in [`LICENSE`](LICENSE), which is their repository's.

| File | What it is |
|---|---|
| `deviceFingerprinting.html`, `deviceFingerprinting.js` | the Device probes (12) |
| `settingsFingerprinting.html`, `settingsFingerprinting.js` | the Settings probes (11) |
| `screenFingerprinting.html`, `screenFingerprinting.js` | the Screen probes (2) |
| `post_data.js` | their helper that shows the results and, with a `sessionId` in the address, posts them |

`tests/integration/test_privacytests.py` serves them from this machine on three local names and reads each page's `data-test-results`. It never gives a `sessionId`, so `post_data.js` posts nothing. The Device page's watchdog posts without one when `new AudioContext()` takes over two seconds, so the test also resolves both results addresses (`results.privacytests.org`, `results.pto2.example`) to this machine, where nothing listens. The pages ask for a `test.css` that is not copied; it only styles them.

[`pinned.json`](pinned.json) holds the commit and each file's SHA-256, and also the digests of their scoring: two scripts whole, and the two functions that score the Device group. `tests/unit/test_privacytests_fixture.py` compares the files here with it.

**Keeping up with them.** They add probes and change the rule, and a pinned copy would go on passing without them. `scripts/research/watch_privacytests.py` compares their repository with `pinned.json` (the copied files, the functions of their harness that hold the pass rule, and the harness lines where a new group of probes would be wired in), and the `privacytests` workflow runs it every week and fails when something changed. To move to a newer commit: read what changed, copy the files again, update `pinned.json` (the commit and the digests) and the commit above, and change the pass rule in the integration test where theirs changed.

## nulavio.net's comparison (#437)

Three more files here are ours, and only `scripts/site/privacytests_pages.py` writes them. The site's pages `/engenharia/impressao-digital/` and `/en/engineering/fingerprinting/`, and the picture for sharing them (`site/assets/og-fingerprinting-*.png`), are built from them; `tests/unit/test_privacytests_comparison.py` checks that nothing in them was typed by hand.

| File | What it is |
|---|---|
| [`published.json`](published.json) | What PrivacyTests.org published for the desktop browsers: each cell's pass or fail as their page (`https://privacytests.org/`) shows it, with the runs it comes from as their data file (`https://privacytests.org/index.json`) has them (for a Device probe, whether each run was randomized and a digest of its value; for a Settings probe, whether each run passed). The SHA-256, size and Last-Modified of both files and the day they were read. |
| [`nulavio.json`](nulavio.json) | A published Nulavio release's `device` job of the `privacytests` workflow: the release, its commit, the run and the job, and the job's result lines, verbatim. |
| [`picture.json`](picture.json) | The SHA-256 of each picture for sharing and of the SVG it was drawn from. |

**Refreshing.** When PrivacyTests.org publishes a new issue (the weekly `privacytests` workflow says so: `scripts/research/watch_privacytests.py` compares both files' SHA-256 with `published.json`) or Nulavio releases, run `python3 -I scripts/site/privacytests_pages.py refresh` (it needs `gh` signed in, the network and Firefox for the picture), read the diff and open a pull request; the site workflow deploys it once it is on `main`. `refresh` stops instead of guessing: on a browser it does not name yet, a cell that is not one of their three marks, a row with a cell missing, a probe the integration test does not run, a probe of the integration test that has no row on their page (unless `NOT_ON_THEIR_PAGE` names it, with the reason), a cell whose verdict is not what its runs say (unless `PAGE_OVER_RULE` names it, with what their page shows), and a release whose run lacks a result line.

**What they publish, and what we take.** PrivacyTests.org's code is under the MIT license; their site and their results state no terms of use (read on 2026-11-20: the home page, `/about`, `/news`, and both repositories, `privacytests/privacytests` and `privacytests/privacytests-website`, the second with no license). We take the pass or fail of each cell, the probe names (which are in their MIT files) and the browsers' versions; not their descriptions, their tooltips or their design. The page credits them by name, says which issue and links to their files by address.
