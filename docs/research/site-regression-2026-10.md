# Real-site regression run, 2026-10-26

Phase 3 asks for "a 50-site regression run with recorded breakage and per-site fixes". This is the first run, on the Nulavio build (Firefox 158.0.1), with the runner in [`tests/regression/run_sites.py`](../../tests/regression/run_sites.py) and the list in [`tests/regression/sites.json`](../../tests/regression/sites.json). Data: [evidence/site-regression-2026-10-26.json](evidence/site-regression-2026-10-26.json).

## Method

Each public page (landing or article pages; no sign-in, no forms) was opened twice in a throwaway engine profile, headless at 1366×900:

1. **Nulavio**: as shipped: Strict tracking protection, uBlock Origin installed by the build's policy.
2. **Stock**: the engine's Standard tracking protection and no content filter, as a stock Firefox profile.

For each run the runner records the final address, title, length of the visible text, links, images, how many origins the engine's own protection blocked (uBlock Origin's blocks are not in that log), and a screenshot. A page is flagged when the protected run fails where the stock run does not, loses more than half of the text or links, or differs visually on more than 35% of the screen. Flagged pages, and pages with large text differences, were then compared side by side by a person.

## Result

**50 sites, 0 load errors, 0 breakages caused by Nulavio's protections.** 6 pages were flagged and 3 more checked by hand; every difference was an ad slot removed, a site variant (A/B tests, personalised banners) or a modal of the site itself. No per-site fix was needed.

| Site | Category | Text (Nulavio / stock) | Links | Flag | Triage |
|---|---|---|---|---|---|
| google | search | 147 / 147 | 11 / 11 | ok | — |
| duckduckgo | search | 8550 / 8550 | 123 / 123 | ok | — |
| bing | search | 2270 / 2870 | 93 / 97 | ok | — |
| wikipedia-pt | reference | 17853 / 17853 | 637 / 637 | ok | — |
| wikipedia-en | reference | 20360 / 20360 | 1224 / 1224 | ok | — |
| github | developer | 12552 / 12552 | 562 / 562 | ok | — |
| stackoverflow | developer | 9785 / 9373 | 237 / 237 | ok | — |
| mdn | developer | 7872 / 7872 | 457 / 457 | ok | — |
| youtube | video | 577 / 577 | 28 / 28 | ok | — |
| twitch | video | 2672 / 2540 | 115 / 108 | ok | — |
| reddit | social | 10812 / 2106 | 204 / 69 | ok | More text with protections (the stock run stopped at a shorter page); no breakage. |
| x | social | 2002 / 2002 | 67 / 67 | ok | — |
| instagram | social | 695 / 695 | 49 / 49 | ok | — |
| facebook | social | 619 / 532 | 34 / 34 | flagged | Site variant: a QR-code sign-in landing in one run, the marketing landing in the other; the sign-in form works in both. |
| linkedin | social | 11691 / 11691 | 276 / 276 | ok | — |
| amazon | shopping | 11215 / 17112 | 159 / 190 | ok | Rotating and personalised banners differ; the stock run shows the site's sign-in popover; product rows identical. |
| mercadolivre | shopping | 5018 / 9411 | 269 / 293 | ok | Personalised cards differ; less text measured because lower sections were still loading; no missing function. |
| magalu | shopping | 4303 / 4043 | 216 / 214 | ok | — |
| americanas | shopping | 6256 / 6810 | 200 / 200 | ok | — |
| olx | shopping | 13328 / 13342 | 508 / 508 | ok | — |
| ifood | shopping | 277 / 277 | 2 / 2 | ok | — |
| booking | travel | 9782 / 9469 | 305 / 303 | flagged | The site's own sign-in offer (modal) in the protected run; page and search form identical underneath. |
| airbnb | travel | 6084 / 5932 | 177 / 177 | ok | — |
| globo | news | 13331 / 13705 | 596 / 598 | flagged | Ad slot removed (grey placeholder band in the stock run); content identical. |
| g1 | news | 4829 / 5201 | 720 / 722 | ok | — |
| uol | news | 11492 / 11879 | 444 / 446 | ok | — |
| folha | news | 30226 / 30256 | 777 / 777 | ok | — |
| estadao | news | 12744 / 13694 | 362 / 363 | ok | — |
| bbc | news | 7855 / 7855 | 159 / 159 | flagged | Ad slot removed (empty band at the top in the stock run); content identical. |
| nytimes | news | 13316 / 13361 | 1058 / 1058 | ok | — |
| theguardian | news | 17979 / 17979 | 343 / 343 | ok | — |
| reuters | news | 13491 / 13491 | 356 / 356 | ok | — |
| cnn | news | 8536 / 8779 | 494 / 495 | flagged | Ad slot removed at the top; the stock run's video tile shows the site's DRM notice (no DRM module in the headless test profile). |
| govbr | government | 5689 / 5689 | 285 / 285 | flagged | The site's own first-visit tooltip and dimmed overlay in the protected run; page identical. |
| receita | government | 7019 / 7019 | 854 / 854 | ok | — |
| caixa | banking | 5792 / 6151 | 290 / 294 | ok | — |
| bb | banking | 3277 / 3277 | 44 / 44 | ok | — |
| itau | banking | 4156 / 4156 | 136 / 136 | ok | — |
| nubank | banking | 4354 / 4354 | 78 / 78 | ok | — |
| paypal | banking | 2435 / 2435 | 17 / 17 | ok | — |
| correios | government | 3955 / 3955 | 217 / 217 | ok | — |
| proton | privacy | 8353 / 8353 | 212 / 212 | ok | — |
| mozilla | software | 5512 / 5512 | 86 / 86 | ok | — |
| microsoft | software | 4183 / 4183 | 111 / 111 | ok | — |
| apple | software | 3691 / 3691 | 276 / 276 | ok | — |
| spotify | music | 2888 / 2888 | 147 / 147 | ok | — |
| netflix | video | 3837 / 3837 | 27 / 27 | ok | — |
| imdb | reference | 214 / 188 | 0 / 0 | ok | — |
| openstreetmap | maps | 617 / 617 | 43 / 43 | ok | — |
| googlemaps | maps | 384 / 360 | 2 / 2 | ok | — |

## Limits of this run

- Landing pages only: no sign-in, checkout, payment, video playback or web apps after login. DRM video was not available in the headless test profile, so streaming sites are covered only up to their landing page.
- One run from one network (Brazil). Sites vary by region, time and A/B tests; a difference in one run is not a trend.
- uBlock Origin's own blocking is not counted (it never reaches the engine's log); the visual and text comparison covers its effect.
- "No breakage" means the page's content and main controls were present; it does not prove that every feature of a site works.

Next runs: before each alpha release (release criteria), with the flagged list triaged the same way.
