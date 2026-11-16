# PrivacyTests.org's fingerprinting probe pages

These files are copied, unchanged, from [privacytests/privacytests](https://github.com/privacytests/privacytests) at commit `5e675fa8a73b876a924d2ec1be648db43ebaf050` (2026-11-16), directory `static/`. The first copy was of `12e48c75` (2026-11-11). They are © Arthur Edelstein and contributors, under the MIT license in [`LICENSE`](LICENSE), which is their repository's.

| File | What it is |
|---|---|
| `deviceFingerprinting.html`, `deviceFingerprinting.js` | the Device probes (12) |
| `settingsFingerprinting.html`, `settingsFingerprinting.js` | the Settings probes (11) |
| `screenFingerprinting.html`, `screenFingerprinting.js` | the Screen probes (2) |
| `post_data.js` | their helper that shows the results and, with a `sessionId` in the address, posts them |

`tests/integration/test_privacytests.py` serves them from this machine on three local names and reads each page's `data-test-results`. It never gives a `sessionId`, so `post_data.js` posts nothing. The Device page's watchdog posts without one when `new AudioContext()` takes over two seconds, so the test also resolves both results addresses (`results.privacytests.org`, `results.pto2.example`) to this machine, where nothing listens. The pages ask for a `test.css` that is not copied; it only styles them.

[`pinned.json`](pinned.json) holds the commit and each file's SHA-256, and also the digests of their scoring: two scripts whole, and the two functions that score the Device group. `tests/unit/test_privacytests_fixture.py` compares the files here with it.

**Keeping up with them.** They add probes and change the rule, and a pinned copy would go on passing without them. `scripts/research/watch_privacytests.py` compares their repository with `pinned.json` (the copied files, the functions of their harness that hold the pass rule, and the harness lines where a new group of probes would be wired in), and the `privacytests` workflow runs it every week and fails when something changed. To move to a newer commit: read what changed, copy the files again, update `pinned.json` (the commit and the digests) and the commit above, and change the pass rule in the integration test where theirs changed.
