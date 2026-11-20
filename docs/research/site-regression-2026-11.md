# Real-site regression run, 2026-11-20

The second run of the 50-site check ([#202](https://github.com/nulavio/nulavio/issues/202)), on engine 160, with the filter lists a new profile now gets ([#83](https://github.com/nulavio/nulavio/issues/83)). The first run, on Firefox 158.0.1, is [site-regression-2026-10.md](site-regression-2026-10.md). Runner: [`tests/regression/run_sites.py`](../../tests/regression/run_sites.py); list: [`tests/regression/sites.json`](../../tests/regression/sites.json), unchanged. Data: [evidence/site-regression-2026-11-20.json](evidence/site-regression-2026-11-20.json).

## What was measured

- **Build.** Firefox 160.0.1, build 20261119020726: the engine of the published release 160.0.1-0.2, with the Shell and tools of this branch.
- **Content filter.** uBlock Origin 1.76.4, installed by the build's policy. The runner now waits until uBlock Origin has selected the new profile's lists and records them: the eight lists of `browser/distribution/content-filter.json` (cookie notices, newsletters and notifications, annoyances, AdGuard – Ads and URL tracking, #83) beside uBlock Origin's own defaults and the list it picks for the profile's language (AdGuard Spanish/Portuguese). The 19 lists are in the evidence file.
- **Method.** As in October: each public page opened twice in a throwaway engine profile, headless at 1366×900, first as Nulavio ships it (Strict tracking protection, uBlock Origin on), then as a stock profile (Standard, uBlock Origin off). A page is flagged when the protected run fails where the stock run does not, loses more than half of its text or links, or differs on more than 35% of the screen. Every flagged page, and the unflagged ones with a large difference in text or links or a challenge page, was looked at side by side from both screenshots. This time the comparison was made by an AI agent (Claude), not by a person; the screenshots stay outside the repository.
- **Re-runs.** The five pages that met a bot check (amazon, imdb, ifood, paypal, stackoverflow) were run twice more, each in a new profile. For Amazon, where the check met the protected run, one more profile reversed the order: stock first, then Strict alone, then Strict with uBlock Origin.

## Result

**50 sites tried; 48 reached with the protections on and judged whole; 0 breakages caused by Nulavio's protections.** 12 pages were flagged and 8 more checked by hand. The differences were ad slots removed, the sites' own modals and cookie notices (hidden by the default lists in the protected run), rotating banners, and bot checks.

- **Two pages were not reached.** IMDb and iFood stopped at their bot check in both runs, in all three runs; why is not established. Nothing behind the check was measured, so they are not counted as tested. The October run counted them, and its numbers for both pages (IMDb 214 / 188 characters and no links, iFood 277 / 277 and 2 links) look like the same checks. So the landing's figure is 48, not 50.
- **Amazon: the order explains the check.** Amazon's first-visit check ("Continuar comprando") met the protected run in all three runs, and in each the protected visit came first. With the order reversed in one profile, it met the stock visit, and both protected visits loaded the whole store (5124 characters with Strict alone, 6871 with uBlock Origin too). Amazon counts among the 48 on that probe.
- **Stack Overflow and PayPal: the cause is not established.** Cloudflare's check met Stack Overflow's stock run three times out of three, so there is no stock page to compare with; the protected run loaded the whole questions list each time. PayPal's check met the stock run once and both runs in the re-runs; its protected page loaded once and was whole.
- One load error: the stock run of Banco do Brasil timed out after the page was drawn. That is not a flag; the protected run had no error.

| Site | Category | Text (Nulavio / stock) | Links | Flag | Triage |
|---|---|---|---|---|---|
| google | search | 126 / 126 | 18 / 19 | ok | — |
| duckduckgo | search | 8657 / 8657 | 123 / 123 | ok | — |
| bing | search | 2252 / 2840 | 94 / 98 | ok | — |
| wikipedia-pt | reference | 17861 / 17861 | 641 / 641 | ok | — |
| wikipedia-en | reference | 20365 / 20365 | 1226 / 1226 | ok | — |
| github | developer | 12516 / 12516 | 536 / 536 | ok | — |
| stackoverflow | developer | 9586 / 278 | 230 / 2 | ok | the stock run stopped at Cloudflare's bot check ('Um momento…'), in this run and both re-runs, so there is no stock page to compare with; the protected run loaded the questions list each time and it is whole. Why the check met only the stock side is not established. |
| mdn | developer | 7872 / 7872 | 457 / 457 | ok | — |
| youtube | video | 176 / 176 | 8 / 8 | ok | — |
| twitch | video | 2600 / 2601 | 112 / 112 | ok | — |
| reddit | social | 12867 / 2155 | 181 / 67 | ok | more text with protections (the stock run stopped at a shorter page, as in October); an ad in the stock run's side column. No breakage. |
| x | social | 2407 / 2407 | 72 / 72 | ok | — |
| instagram | social | 561 / 762 | 49 / 51 | flagged | The stock run shows the site's own sign-up modal over the profile; the profile and posts are identical underneath. |
| facebook | social | 619 / 619 | 34 / 34 | ok | — |
| linkedin | social | 12204 / 12630 | 271 / 266 | flagged | The stock run shows the site's own sign-in modal and a Google sign-in prompt; the company page is identical underneath. |
| amazon | shopping | 161 / 7123 | 2 / 167 | flagged | The protected run stopped at Amazon's first-visit check ('Continuar comprando'), in this run and in both re-runs, where the protected run always comes first. With the order reversed in one throwaway profile, the stock visit got the check and the Strict, then Strict + uBlock Origin visits loaded the store (5124 and 6871 characters). The check follows the first visit, not the protections. |
| mercadolivre | shopping | 5188 / 10079 | 259 / 287 | ok | same landing; less text measured with protections because lower sections were still loading; the stock run shows the site's cookie notice. |
| magalu | shopping | 2904 / 2904 | 199 / 199 | ok | — |
| americanas | shopping | 5313 / 3904 | 305 / 140 | flagged | Banner rotation and an extra 'black cestas' band in the stock run, with the site's cookie notice (hidden by the cookie-notice lists in the protected run); the protected run measured more text and links. Same store. |
| olx | shopping | 12205 / 12501 | 311 / 316 | ok | — |
| ifood | shopping | 277 / 277 | 2 / 2 | not reached | both runs, here and in both re-runs, stopped at Cloudflare's bot check ('Um momento…'); cause not established. The October run's counts for this page (277 / 277, 2 links) look like the same check. |
| booking | travel | 5283 / 10688 | 281 / 328 | flagged | The site's own modal in both runs (a Genius sign-in offer with protections, a Black Friday offer without); the search form is identical underneath. Less text measured because lower sections were still loading. |
| airbnb | travel | 8172 / 8583 | 197 / 197 | ok | — |
| globo | news | 9375 / 9731 | 587 / 587 | ok | — |
| g1 | news | 3672 / 3672 | 710 / 710 | ok | ad slot removed (grey placeholder band in the stock run); content identical. |
| uol | news | 11529 / 11985 | 436 / 447 | flagged | Ad slot removed (the 'Publicidade' band in the stock run pushes the page down); content identical. |
| folha | news | 27926 / 28175 | 758 / 758 | ok | — |
| estadao | news | 14253 / 15261 | 397 / 398 | ok | — |
| bbc | news | 8295 / 8283 | 160 / 160 | flagged | Ad slot removed (empty band at the top in the stock run); content identical. |
| nytimes | news | 10631 / 10590 | 1020 / 996 | ok | — |
| theguardian | news | 18263 / 18263 | 354 / 354 | ok | — |
| reuters | news | 24945 / 14428 | 363 / 354 | flagged | The stock run shows the site's consent dialog and an empty ad band at the top; the protected run measured more text. Content identical. |
| cnn | news | 12347 / 12721 | 564 / 564 | flagged | Ad slot removed at the top and the site's cookie notice in the stock run; the lead story's picture differs (rotation). Content identical. |
| govbr | government | 5741 / 5689 | 285 / 285 | flagged | The site's own first-visit tooltip and dimmed overlay in the protected run, the cookie notice and cards still loading in the stock run; page identical. |
| receita | government | 6817 / 7213 | 881 / 881 | ok | — |
| caixa | banking | 3905 / 4264 | 279 / 283 | ok | — |
| bb | banking | 3234 / 3458 | 46 / 46 | ok | the stock run's load timed out after the page was drawn (3458 characters measured); both runs show the bank's own promotional modal. |
| itau | banking | 4100 / 4100 | 137 / 138 | ok | — |
| nubank | banking | 4551 / 4551 | 138 / 138 | ok | — |
| paypal | banking | 2199 / 0 | 17 / 0 | flagged | The stock run stopped at PayPal's human check (slider); the protected run loaded the page, which is whole. In both re-runs both runs got the check. Why the check met one side or the other is not established; the protected side loaded once. |
| correios | government | 3774 / 4159 | 217 / 217 | ok | — |
| proton | privacy | 8384 / 8384 | 212 / 212 | ok | — |
| mozilla | software | 5512 / 5512 | 86 / 86 | ok | — |
| microsoft | software | 3733 / 4203 | 111 / 111 | flagged | The site's cookie notice in the stock run pushes the page down; content identical. |
| apple | software | 3949 / 3949 | 277 / 277 | ok | — |
| spotify | music | 2710 / 2917 | 356 / 342 | ok | — |
| netflix | video | 1787 / 2078 | 19 / 27 | ok | the stock run shows the site's cookie notice (its links are the difference); the landing and sign-up field are identical. |
| imdb | reference | 214 / 214 | 0 / 0 | not reached | both runs, here and in both re-runs, stopped at IMDb's human check ('Vamos confirmar que você é humano'); cause not established. The October run's counts for this page (214 / 188, 0 links) look like the same check. |
| openstreetmap | maps | 605 / 605 | 42 / 42 | ok | — |
| googlemaps | maps | 411 / 387 | 2 / 2 | ok | — |

## Limits of this run

- The October limits hold: landing pages only, no sign-in, checkout, payment, video playback or web apps after sign-in; one run from one network (Brazil); uBlock Origin's own blocks are not in the engine's log; "no breakage" means the page's content and main controls were present, not that every feature of a site works.
- The triage was made by an AI agent comparing the two screenshots and the counts; no person looked at them for this run.
- A development package: the published 160.0.1-0.2 engine with the Shell of this branch.
- The "stock" pass is the same build with two changes: Standard tracking protection in place of Strict, and uBlock Origin off. Nulavio's other defaults, and the test conditions (Marionette, headless), are the same in both passes. So "not caused by the protections" means not caused by Strict and uBlock Origin; a bot check that reacts to something both passes share would meet both.
- Bot checks vary by run and by visit. A page behind one in both runs is reported as not reached, not as working; IMDb and iFood were not looked at in a normal, non-automated window.

Next run: before the 1.0 release, with the flagged list triaged the same way.
