# ADR 0016 — Pages read one screen size and one processor count

- **Status:** Accepted (2026-11-14) for the screen: the maintainer decided it on [issue #79](https://github.com/nulavio/nulavio/issues/79) that day (decision 3 there: "a constant screen reported to pages, for example 1920×1080, with the window left alone, not letterboxing"). **Proposed** for the processor count, which the issue only asked to consider; it is in the same pull request (#375) and the maintainer can reverse it by removing one word from a preference.
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

- **How:** the engine has a per-tab screen size made for automation (`browsingContext.setScreenAreaOverride`). The Shell sets it. No engine patch.
- **When:** each page decides for itself as its window is created, in its own process (`NulavioFingerprintingChild.sys.mjs`). That is the one moment after the page before it is gone and before the new page's first script, so:
  - a page's first script already reads the right size;
  - a protected page keeps the constant until it is replaced, also while a site the person exempted is on its way. An earlier version of this change decided when the request was made, and the page still shown could then read the display's size until the answer came (found in review).
- **Which pages:** pages of the web, in tabs. An extension's pages (its popup, its background page, its pages in a tab) and the browser's own read the display's size: the engine keeps its fingerprinting protection away from them too, and an extension may place its windows by the screen.
- **Pages already open** are decided again when the engine's protection is switched on or off, and when the Shell starts.
- **The window is left alone.** `innerWidth`, `innerHeight` and CSS layout are the window's real size. No margins, no fixed window sizes.
- **It follows the engine's protection.** It is on while fingerprinting protection is on (the Strict category, Nulavio's default) and off otherwise. A site the person exempts with the shield in the address bar reads the display's size, like the other plain values: the page asks the engine's own record of that exemption, in ordinary and in private windows. Mozilla's remote list of per-site exceptions for single protections does not reach the screen's size, which is not one of the engine's protections.
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
- **Distribution Firefox (Track A)** gets the processor count, which is a preference, and not the screen, which needs the Shell.

## Known limits

The size is kept per tab, by the Shell, and not per document, by the engine. An independent review of the merged change (2026-11-15) traced these in the engine's code; none was run:

1. **A frame from another site in the page that leaves.** When a protected page gives way to an exempted site in the same tab and the same browsing context (the page has an `unload` listener, or both are on one host), a frame of the old page that is in another process can read the display's size in its last moments, after the new page has decided.
2. **A media query inside an SVG image.** An image document has no tab of its own, so `device-width` there answers with the real display. A page could read it by drawing such an image and reading the result back, where canvas reads allow it.
3. **A pop-up of an exempted site, on the same origin,** reads the constant: its first, empty document decides before the site's own page takes its place, and that page creates no new window. This fails on the safe side; a remote-desktop site that opens its session in a pop-up gets 1920×1080.
4. **A frame is not asked.** The tab's top page decides for every frame in it: a frame of an exempted site inside a protected page reads the constant, and a frame inside an exempted page reads the display's. The engine's own protections go by the top page's exemption in the same way.
5. **Automation.** WebDriver BiDi's screen emulation uses the same per-tab value, and each page load overwrites it.
6. **A profile whose set of protections the person wrote themselves keeps it**, so it keeps the processor tiers until they add the entry; `nulavio doctor` says so, with the value to set. A set the launcher seeded and nobody changed follows the baseline at the profile's next launch (#384). That concerns distribution Firefox (Track A): in the Nulavio build a seeded set equal to the build's default is not kept in the profile at all, so every profile there takes the build's default.

Limits 1 to 4 go away with the size decided per document inside the engine (`nsScreen`, `nsMediaFeatures`), which is an engine patch and is tracked in #79 with the audio patch.

## Checked

- `test_privacytests`: PrivacyTests' own Screen probes on two display sizes, and its processor probe.
- `test_fingerprinting` 08: the size, the available area and the media query on two sites, from the page's first script; an exempted site reads the display's, also after a protected page in another process; back and forward.
- `test_fingerprinting` 08b: a protected page that sends the tab to an exempted site that takes 2.5 s to answer reads 1920×1080 the whole time; the exempted site then reads the display's from its first script.
- `test_fingerprinting` 08c: a private window has the constant, and its own exemption.
- `test_fingerprinting` 08d: an extension's page in a tab reads the display's size; a page that stays open follows the engine's switch off and on, without a new load.
- `tests/regression/run_sites.py` on 50 real sites, before and after: see the pull request.

Not checked: a display larger than 1920×1080 (headless runs have a smaller one).

## Alternatives

- **The window's inner size as the screen (the engine's `ScreenRect`).** It passes PrivacyTests only when the window does not follow the display, which a maximised window does.
- **Letterboxing.** It hides the window's size too. It shows margins around every page, against the calm interface the product asks for. Ruled out by the maintainer.
- **Keep the processor tiers.** PrivacyTests' own runners all have fewer than 8 processors, so the tiers pass on their site. They would still tell a 16-processor machine from a 4-processor one, which is what the probe is about.
