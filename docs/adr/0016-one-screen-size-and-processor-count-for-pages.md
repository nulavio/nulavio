# ADR 0016 — Pages read one screen size and one processor count

- **Status:** Accepted (2026-11-14) for the screen: the maintainer decided it on [issue #79](https://github.com/nulavio/nulavio/issues/79) that day (decision 3 there: "a constant screen reported to pages, for example 1920×1080, with the window left alone, not letterboxing"). **Proposed** for the processor count, which the issue only asked to consider; it is in the same pull request (#375) and the maintainer can reverse it by removing one word from a preference.
- **Changed** (2026-11-16): the engine decides the screen's size for each document (engine patch 0012, with [ADR 0019](0019-rendered-audio-differs-per-site.md)'s audio noise), where the Shell decided it per tab. "Known limits" lost four entries with it.
- **Changed** (2026-11-18, [#468](https://github.com/nulavio/nulavio/issues/468)): the engine's way is the only one. The Shell's per-tab way is removed, after 160.0.1-0.1 shipped the patch; the maintainer decided it on 2026-11-17 ([feature review](../product/feature-review-2026-11.md), row P8). What was checked first, and what changes for a set of protections without the screen's entry, is under [One mechanism](#one-mechanism-since-468).
- **Related:** [fingerprinting, measured](../research/fingerprinting.md), [hardening](../security/hardening.md).

## Context

A site can recognise a computer by what it reads from it. PrivacyTests.org added 25 fingerprinting probes on 2026-11-11, and #79 asks that Nulavio pass all of them with its defaults. Measured on 2026-11-15 (160.0-0.5's engine), three of the failing probes were these:

| Probe | Read | Why it fails |
|---|---|---|
| `screen.width`, `screen.height` | the display's size: 1366×768 on one display, 1600×900 on another | The value follows the display |
| `navigator.hardwareConcurrency` | 8 on a 16-processor machine | The engine's protection reports two tiers, 4 below 8 processors and 8 from there up. A machine with 4 and one with 16 still read differently |

Until now Nulavio left the screen's size alone on purpose: the engine's own way to hide it (`ScreenRect`) reports the window's inner size as the screen, which only helps together with fixed window sizes and margins (letterboxing).

## Decision

### 1. The screen is 1920×1080 for every page

Pages read `screen.width` 1920 and `screen.height` 1080 on every computer. The available area is the same size at 0,0, and the `device-width` and `device-height` media queries agree with it.

- **How, since engine patch 0012:** the engine itself answers, for each document. The patch adds a target to the engine's fingerprinting protection, `ScreenSizeConstant`, which Nulavio turns on in `privacy.fingerprintingProtection.overrides`. `screen`, the available area and the two media queries ask it. Every document is asked for itself: a page, a frame, a pop-up (also its first, empty document) and an image. A page being printed keeps the paper's size.
- **How, before the patch (160.0-0.6):** the engine has a per-tab screen size made for automation (`browsingContext.setScreenAreaOverride`), and the Shell set it. Each page decided for itself as its window was created, in its own process (`NulavioFingerprintingChild.sys.mjs`): the one moment after the page before it is gone and before the new page's first script. An earlier version decided when the request was made, and the page still shown could then read the display's size until the answer came (found in review).
- **The per-tab way is gone (#468).** From #402 until then it stayed for one case, a set of protections the person wrote that leaves the target out, where the Shell went on setting the tab's size. Now the Shell sets nothing, and the tab's own screen size is automation's alone. See [One mechanism](#one-mechanism-since-468).
- **Which pages:** pages of the web, wherever they are shown. An extension's pages (its popup, its background page, its pages in a tab) and the browser's own read the display's size: the engine keeps its fingerprinting protection away from them, and an extension may place its windows by the screen.
- **Pages already open** follow the engine's switch at once, without a new load.
- **The window is left alone.** `innerWidth`, `innerHeight` and CSS layout are the window's real size. No margins, no fixed window sizes.
- **It follows the engine's protection.** It is on while fingerprinting protection is on (the Strict category, Nulavio's default) and off otherwise. A site the person exempts with the shield in the address bar reads the display's size, like the other plain values, in ordinary and in private windows. Responsive design mode and WebDriver BiDi's screen emulation come first, as they do in Firefox.
- **Why 1920×1080:** it is a size many real desktop displays have, so the value does not stand out the way an odd one would.

### 2. Every computer reports 4 processors

`+NavigatorHWConcurrency` joins `privacy.fingerprintingProtection.overrides`. The engine then reports 4 on Linux, whatever the machine has.

## Consequences

- **A page can see that the screen is not the window's.** On a display larger than 1920×1080 with a maximised window, `innerWidth` is larger than `screen.width`. That is a sign of a protected browser, which Nulavio already gives in other ways (the graphics card reads "Mozilla"). It is the same sign for every Nulavio user.
- **Window size still differs between people.** A page that reads `innerWidth` and `innerHeight` learns the window's size, and a maximised window gives away most of the display's. Hiding that needs letterboxing, which the maintainer ruled out for the bands it shows. PrivacyTests does not probe it.
- **Sites that use the screen's size:**
  - a pop-up centred on the screen is centred on 1920×1080: off-centre on another display, still on it;
  - a page that picks image sizes by screen size picks them for 1920×1080;
  - a remote-desktop page that asks for the screen's resolution gets 1920×1080.

  The fix for a site that needs the real size is the shield's switch for that site.
- **Fewer workers on large machines.** A page that starts one worker per processor starts 4, where the tiers gave it 8 on a machine with 8 or more. Work that page does in parallel (encoding, compression, some games) can take up to twice as long there. Machines with fewer than 8 processors already read 4.
- **Nulavio's own pages and extensions' pages read the display's size.** Only pages of the web are given the constant.
- **Distribution Firefox** does not have the screen, which needs the Nulavio build's engine patch. (The preview on distribution Firefox, Track A, is no longer offered: #464.)

## Known limits

1. **A frame goes by the page around it.** A frame of an exempted site inside a protected page reads the constant, and a frame inside an exempted page reads the display's. The engine's other protections go by the top page's exemption in the same way.
2. **A profile whose set of protections the person wrote themselves keeps it.** It keeps the processor tiers until they add the entry; `nulavio doctor` says so, with the value to set. A set the launcher seeded and nobody changed follows the baseline at the profile's next launch (#384); that concerns distribution Firefox (Track A), since in the Nulavio build a seeded set equal to the build's default is not kept in the profile at all. In the Nulavio build, a set the person wrote without the screen's entry reads the display's size since #468, as it goes without any other protection the set leaves out ([One mechanism](#one-mechanism-since-468)).

### One mechanism (since #468)

The screen's size reached pages two ways from #402 on: the engine's target, and the Shell's per-tab size where `engineDecides()` said the engine would not answer (an engine without the target, or a set that leaves it out). Two ways are two things to keep right at every engine update, and the second had the limits listed below. Before removing it, each case that could still need it was checked (2026-11-18):

| Case | What was found | Needs the per-tab way |
|---|---|---|
| An engine without the target | The Shell exists only in the Nulavio build, whose patch stack has 0012 since 160.0.1-0.1 (`browser/patches/series` at `v160.0.1-0.1`); a build of the tree without it fails `test_fingerprinting` and `test_privacytests`. The preview on distribution Firefox never had the Shell and is no longer offered (#464) | No |
| The build's default set | Has `+ScreenSizeConstant` (`firefox-branding.js`; a unit test holds it) | No |
| The set the Shell writes for "let sites see my motion and contrast preferences" | Written again from the build's default at every start, so a profile that turned the setting on in 160.0-0.6 gets the entry at its first start in a build that has it (`applyAccessibility`; `test_fingerprinting` 10b) | No |
| A set the launcher seeded | The baseline's set is the build's default, character for character, so the engine does not keep it in the profile. An earlier seed that nobody changed is replaced at the profile's next launch (#400), and every launch of a launcher profile passes there (`prepare_for_launch`). The packaged browser does not open the launcher's profiles | No |
| A set fixed by a policy | Nulavio ships none: the build's `policies.json` fixes no preference of the fingerprinting protection, and `distribution.ini` sets defaults only (`make_distribution.py`). A set an administrator locks is theirs, as the next row | No |
| A set the person wrote without the entry | The one case the per-tab way served. It gave such a profile the constant with the limits below, and it also meant that the set could not turn the screen's protection off: `-ScreenSizeConstant` changed nothing | Removed all the same (below) |

**What changes for a set written without the entry.** It reads the display's size after the update to the first build without the per-tab way. That is the rule every other entry already follows: such a set also goes without the audio noise, UTC or the processor count if it was written before they were added ([R78](../security/residual-risks.md)), and the engine's set is now the one place that says what a page reads. To get the constant back, add `+ScreenSizeConstant` to `privacy.fingerprintingProtection.overrides`, or reset the preference. The release's notes say so. `nulavio doctor` names the set only for a profile the launcher made; for a profile of the packaged browser nothing does.

### Limits of the per-tab way

History: they held for every profile in 160.0-0.6, then only for a set without the target, and for none since #468. An independent review of #375 traced them in the engine's code (2026-11-15); the second was then measured (`test_fingerprinting` 08e, forced on an engine without the patch).

- **A frame from another site in the page that leaves.** When a protected page gives way to an exempted site in the same tab, a frame of the old page that is in another process can read the display's size in its last moments.
- **A media query inside an SVG image** answers with the real display: an image document has no tab of its own. A page can read it by drawing the image on a canvas.
- **A pop-up of an exempted site, on the same origin,** reads the constant: its first, empty document decides before the site's own page takes its place. A remote-desktop site that opens its session in a pop-up gets 1920×1080.
- **Automation.** WebDriver BiDi's screen emulation uses the same per-tab value, and each page load overwrites it.

## Checked

- `test_privacytests`: PrivacyTests' own Screen probes on two display sizes, and its processor probe.
- `test_fingerprinting` 08: the size, the available area and the media query on two sites, from the page's first script; an exempted site reads the display's, also after a protected page in another process; back and forward.
- `test_fingerprinting` 08b: a protected page that sends the tab to an exempted site that takes 2.5 s to answer reads 1920×1080 the whole time; the exempted site then reads the display's from its first script.
- `test_fingerprinting` 08c: a private window has the constant, and its own exemption.
- `test_fingerprinting` 08d: an extension's page in a tab reads the display's size; a page that stays open follows the engine's switch off and on, without a new load.
- `test_fingerprinting` 08e, on an engine with the patch: a page, a frame from another site, a pop-up's empty document, a pop-up of the same site and a media query inside an SVG image all read the constant; on an exempted site all of them read the display's; a frame of the exempted site inside a protected page reads the constant; with a set that leaves the target out, pages read the display's size, the open one at once, and the constant comes back with the build's set (until #468 the per-tab way gave them the constant there).
- `test_fingerprinting` 10b: a set the Shell wrote in an earlier build, without the screen's entry, is written again from the build's default at the Shell's start.
- `tests/regression/run_sites.py` on 50 real sites, before and after: see the pull request.

Not checked: a display larger than 1920×1080 (headless runs have a smaller one).

## Alternatives

- **The window's inner size as the screen (the engine's `ScreenRect`).** It passes PrivacyTests only when the window does not follow the display, which a maximised window does.
- **Letterboxing.** It hides the window's size too. It shows margins around every page, against the calm interface the product asks for. Ruled out by the maintainer.
- **Keep the processor tiers.** PrivacyTests' own runners all have fewer than 8 processors, so the tiers pass on their site. They would still tell a 16-processor machine from a 4-processor one, which is what the probe is about.
