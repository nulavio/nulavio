# PrivacyTests.org's fingerprinting probe pages

These files are copied, unchanged, from [privacytests/privacytests](https://github.com/privacytests/privacytests) at commit `12e48c75ec5dbbd127478166b26009f95cbd8918` ("detect farbling more effectively", 2026-11-11), directory `static/`. They are © Arthur Edelstein and contributors, under the MIT license in [`LICENSE`](LICENSE), which is their repository's.

| File | What it is |
|---|---|
| `deviceFingerprinting.html`, `deviceFingerprinting.js` | the Device probes (12) |
| `settingsFingerprinting.html`, `settingsFingerprinting.js` | the Settings probes (11) |
| `screenFingerprinting.html`, `screenFingerprinting.js` | the Screen probes (2) |
| `post_data.js` | their helper that shows the results and, with a `sessionId` in the address, posts them |

`tests/integration/test_privacytests.py` serves them from this machine on three local names and reads each page's `data-test-results`. It never gives a `sessionId`, so nothing is posted. The pages ask for a `test.css` that is not copied; it only styles them.

`tests/unit/test_privacytests_fixture.py` pins each file's SHA-256. To move to a newer commit: copy the files again, update the digests and the commit there and here, and read what changed in their scoring (`scripts/test.js`, `scripts/settings-fingerprint-test.js`, `scripts/render.js`), which the integration test mirrors.
