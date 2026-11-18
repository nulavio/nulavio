# Fingerprinting: what a page can read in the Nulavio build, measured

A site can recognise a browser without cookies by what it reads from it: its name, the graphics card, the installed fonts, how a canvas is drawn. This page says what the Nulavio build gives out, measured on the real engine, what it changes against Firefox's own defaults, and what it leaves alone on purpose. Every row marked "tested" fails a test run if it stops being true (`tests/integration/test_fingerprinting.py`).

Measured on 2026-11-10 with the release build of Firefox 159.0.1 and patches 0001–0010, on Fedora 44 (16 logical processors). The screen, processor, time zone and motion rows, and the PrivacyTests section, were measured on 2026-11-15 with 160.0-0.5's engine. The audio row, the screen per document and the cost of the audio noise were measured on 2026-11-16 with a local build of 160.0 and patch 0012. The first analysis (2026-10-26, Firefox 158.0.1) is at the end.

## Two things the build does

1. **It looks like Firefox.** Nulavio has few users. Anything that says "Nulavio" to a site singles them out, so the build says "Firefox" where Firefox does. It also changes no TLS or HTTP setting, so the connection itself (the handshake a server or a network observer sees) is Firefox's.
2. **It gives each site less, or something different.** Where the engine can blur a reading without breaking sites, the build turns that on: a value that changes per site and per day cannot follow a person from one site to another.

Neither makes two people identical. The language, the window's size and the internet address still differ between people. For that level, use Tor Browser.

## What a page reads

"Plain" is the reading with every protection off. "Firefox, Strict" is what the engine does in the tracking-protection category Nulavio uses, without Nulavio's additions.

| Reading | Plain | Firefox, Strict | Nulavio | Checked by |
|---|---|---|---|---|
| Browser name (`navigator.userAgent` and the `User-Agent` header) | — | `… Firefox/159.0` | **The same as Firefox.** Before patch 0009 it was `… Nulavio/159.0.1` on every request | tested (01) |
| Canvas, exported image (`toDataURL`, `toBlob`) | the same on every site | differs per site | differs per site | tested (03) |
| Canvas, raw pixels (`getImageData`) and offscreen canvases | the same on every site | **the same on every site**: the engine's quick mode changes only exported images | **differs per site** | tested (03) |
| WebGL pixels (`readPixels`) | the same on every site | the same on every site | differs per site | tested (06, with a display) |
| Graphics card (WebGL renderer and vendor) | model family, for example "Radeon R9 200 Series, or similar" | the same | **"Mozilla"**; the vendor only as a broad class | tested (06, with a display) |
| Number of processors | 16 | 8 (reported in tiers: 4, or 8 from 8 processors up) | **4 on every computer** ([ADR 0016](../adr/0016-one-screen-size-and-processor-count-for-pages.md)) | tested (04) |
| Screen size (`screen.width`, `screen.height`, the `device-width` media query) | the display's | the display's | **1920×1080 on every computer**, for every document (a frame, a pop-up and an image too; engine patch 0012); the window's own size is not changed (ADR 0016) | tested (08, 08e) |
| Installed fonts | all of them | **all of them on Fedora** (see below) | **only the fonts the distribution installs by default** | tested (05) |
| Size of the toolbars and the sidebar (`outerWidth` − `innerWidth`), window position | real | real | **not given out** (outer size equals inner size, position 0,0) | tested (04) |
| System colours a page can ask for (accent, selection) | the desktop theme's | the desktop theme's | standard colours | in the set (02) |
| Motion and orientation sensors | readings, where the computer has them | readings | none | in the set (02) |
| Usable screen area | the screen minus panels | the whole screen | the same 1920×1080, at 0,0 | tested (08) |
| Time zone (`Intl`, `Date`) | the system's | the system's | **UTC on every computer** (the engine names it `Atlantic/Reykjavik`). A site gets the system's from the switch "Usar meu fuso horário neste site" in the shield's panel ([ADR 0017](../adr/0017-pages-read-utc-with-a-switch-per-site.md)) | tested (09) |
| Touch points | real | 0, 1 or 5 | 0, 1 or 5 | in the set (02) |
| Rendered audio (what an `OfflineAudioContext` returns) | the same on every site | the same on every site | **differs per site** (engine patch 0012, [ADR 0019](../adr/0019-rendered-audio-differs-per-site.md)) | tested (11) |
| Reduced motion, more contrast (`prefers-reduced-motion`, `prefers-contrast`) | the system's | the system's | **"no preference" on every computer**, until the person turns on "Deixar os sites verem minhas preferências de movimento e contraste" ([ADR 0018](../adr/0018-sites-are-not-told-motion-and-contrast-preferences.md)) | tested (10) |

"Differs per site" means: two sites read different values, the same site reads the same value again during the day (so sites that read twice keep working), and the value changes with the next session or day. The engine does it by changing the lowest bit of a few colour values, chosen from a random key per site.

The whole set in effect is the engine's own for Strict (`CanvasRandomization`, `FontVisibilityLangPack`, `JSMathFdlibm`, `ScreenAvailToResolution`, `NavigatorHWConcurrencyTiered`, `MaxTouchPointsCollapse`, `IMEStyle`) plus Nulavio's (`privacy.fingerprintingProtection.overrides` in `firefox-branding.js`): `WebGLRendererConstant`, `WebGLVendorSanitize`, `WindowOuterSize`, `WindowScreenXY`, `WindowInnerScreenXY`, `MouseEventScreenPoint`, `UseStandinsForNativeColors`, `DeviceSensors`, `NavigatorHWConcurrency`, `JSDateTimeUTC`, `CSSPrefersReducedMotion`, `CSSPrefersContrast`, `CSSPrefersReducedTransparency`, the two targets Nulavio's own engine patch 0012 adds, `AudioRandomization` and `ScreenSizeConstant`, and without `EfficientCanvasRandomization`. Test 02 reads the set from the engine and compares. The screen's size is in that set since engine patch 0012 (`ScreenSizeConstant`), and the engine answers for each document. Nothing else sets it: the Shell's per-tab screen size is gone since #468 ([ADR 0016](../adr/0016-one-screen-size-and-processor-count-for-pages.md#one-mechanism-since-468)).

## Three things that were wrong before 2026-11-10

- **The name.** The engine builds the User-Agent from the application's name. With the build's own name, every request ended in `Nulavio/159.0.1`: a label for a small group of people, sent to every site, with the point release included. No document recorded it as a decision. Patch 0009 gives the engine the name Firefox uses, and the string is now Firefox's, character for character.
- **Fonts on Fedora.** The engine hides fonts a person installed, using a list of default fonts per distribution release. Its Fedora lists stop at release 39 and are never used: the release number is read from `VERSION_ID="…"` with quotes, which Fedora's `os-release` does not have. On Fedora 44 the same 33 of 63 probed font families were visible with the protection off, on, and even with `privacy.resistFingerprinting`. Patch 0010 uses the two newest lists for every Fedora. On Ubuntu the engine's lists already apply (22.04 and 20.04 together for other releases).
- **Raw canvas pixels.** The first analysis found "no canvas noise" and did not claim any. The cause is now known: the engine's quick mode, on by default since then, changes exported images only, and that analysis compared two modes on one site, which share a key. Nulavio turns the quick mode off, so the full one covers raw reads, offscreen canvases and WebGL.

## What is left alone, and why

| Reading | Why it stays |
|---|---|
| Date format, language | A wrong language breaks forms and reading. The time zone is no longer left alone: pages read UTC, with a switch per site (ADR 0017) |
| Window size, zoom | Hiding them means fixed window sizes with margins (letterboxing). The screen's size is no longer left alone (ADR 0016) |
| Dark mode | It is how a site respects the person's theme. Reduced motion and contrast are no longer left alone: sites are not told them unless the person says so (ADR 0018) |
| Audio read inside the graph, or from a context that plays (an `AnalyserNode`, a `ScriptProcessorNode`, an `AudioWorklet`) | Engine patch 0012 covers the buffer an offline rendering returns, which is what the probes it was measured against read (ADR 0019). A node inside an offline graph still hands script the samples without the noise, the same on every site; that is a gap for a later patch. Readings from sound that plays are not changed either: noise there would have to stay out of what the person hears |
| Speech voices, cameras and microphones (count only, no names before permission) | Hiding them breaks reading aloud and device choice in calls |
| System font name and size | No protection in the engine outside `privacy.resistFingerprinting` |
| Keyboard layout | Faking a layout breaks shortcuts in web apps on non-US keyboards |
| Internet address | A browser cannot hide it; that is a VPN's or Tor's job |

`privacy.resistFingerprinting`, the engine's stricter mode, changes several of these. Nulavio does not turn it on ([hardening](../security/hardening.md), "Deliberately not changed"). It may become an opt-in mode.

## Limits

- **A site can still tell this is not a stock Firefox.** A release that reports "Mozilla" as its graphics card, an outer window as large as the inner one, or a window wider than its screen (a maximised window on a display larger than 1920×1080) is unusual. What the build aims at is that Nulavio users look alike and that one person does not carry the same values from site to site, not that they vanish among all Firefox users.
- **Hours are in UTC on a site until the person says otherwise.** A page that formats a time itself shows it in UTC. The shield's panel has a switch for that site alone ("Usar meu fuso horário neste site"), listed afterwards in Settings with the other site exceptions.
- **A site the person exempts gets the plain values.** Turning the shield off for a site in the address bar turns these protections off there too (tested, 07), and only there. Mozilla's own per-site exceptions for broken sites (Remote Settings) apply as in Firefox to the engine's protections; they reach the screen's size and the audio noise too, which are targets of the engine's protection since patch 0012.
- **The screen's size goes by the page around a frame.** A frame of an exempted site inside a protected page reads 1920×1080, and a frame inside an exempted page reads the display's ([ADR 0016](../adr/0016-one-screen-size-and-processor-count-for-pages.md#known-limits)). An extension's own pages read the display's size.
- **A set of protections the person wrote themselves is kept.** The launcher seeds the set into a profile on distribution Firefox. A seeded set that nobody changed follows the baseline at the profile's next launch, so newer entries (the processor count, UTC, the audio noise) reach it. A set the person changed stays as it is, without them; `nulavio doctor` names it, with the value to set (#384). In the Nulavio build, a set written without the screen's entry (`+ScreenSizeConstant`) reads the display's size, like any other protection the set leaves out: until 160.0.1-0.1 the Shell set the screen per tab for such a set, and since #468 the engine's set alone decides ([ADR 0016](../adr/0016-one-screen-size-and-processor-count-for-pages.md#one-mechanism-since-468)).
- **Other distributions.** The engine has font lists for Fedora and Ubuntu only. Elsewhere every installed font stays visible.
- **Cost.** A page that reads canvas pixels back gets a few of them changed by one step. Image editors and games that draw and read many times pay for the extra work on each read.
- **Extensions.** uBlock Origin, which Nulavio installs, can be noticed by what it blocks, as in any browser that has it.
- **Distribution Firefox (Track A).** The launcher seeds the same additions, but patches 0009, 0010 and 0012 exist only in the Nulavio build. Distribution Firefox already says "Firefox"; its fonts on Fedora stay visible, its rendered audio is the same on every site and its screen is the display's.

## Kept true by

- `tests/integration/test_fingerprinting.py`, fifteen tests on the real engine. The plain values are read in the same session with the protections off, so the comparison holds on any machine. The font test installs a font made for the test in the throwaway home.
- `tests/unit/test_prefs_and_guard.py`: the additions are the same in both tracks, and nothing that breaks sites or accessibility without a decision (language, colour scheme, keyboard, window rounding) can enter the default.
- Guard at run time: a change to `privacy.fingerprintingProtection` or its branch made while the browser was closed is reported at the next start.
- `tests/integration/test_privacy.py` (`test_04`) still compares Strict with Standard.

## PrivacyTests.org's probes

[PrivacyTests.org](https://privacytests.org) added 25 fingerprinting probes on 2026-11-11. Their own pages, unchanged, run in `tests/integration/test_privacytests.py` with their pass rule: a probe passes when its value differs between three sites, or when it stays the same while the system's settings (or the machine) change. Measured on 2026-11-15, headless, on Fedora 44:

| Group | Probes | Pass | Not yet |
|---|---|---|---|
| Device | 12 | 12 | |
| Settings | 11 | 11 | |
| Screen | 2 | 2 | |

All 25 pass in a build with engine patch 0012 (measured on 2026-11-16 on a local build of 160.0 with the patch; before it, 24: the audio fingerprint read `35.749972093850374` on all three sites, and now reads a different value on each). A probe that stops passing fails the run; the test file's `KNOWN_GAPS` is empty. Limits of that run: one machine, so a Device probe passes there only by differing per site or by a value that is the same on every machine by construction; and no panels around the screen, so the available-area probes show stability only.

- **Between machines.** The test holds each Device value that does not differ per site to one written value (`DEVICE_CONSTANTS`). The module needs the Nulavio build, so pull requests do not run it. It runs on a developer's computer, on the release build's machine for every release before it is signed, and on GitHub's own runner for every published release (the `device` job of the [`privacytests` workflow](../../.github/workflows/privacytests.yml), with the published archive checked against the release key). A value that followed the machine fails on one of them.
- **Their own harness is not run.** It drives browsers at fixed paths and sends each run to their results server, which is theirs to fill. Their pages are what a browser is measured by, and those are the copy here.
- **Keeping up with them.** The copy is of one commit of theirs (`tests/fixtures/privacytests/pinned.json`). [`watch_privacytests.py`](../../scripts/research/watch_privacytests.py) compares their repository with it: each copied file, the two functions of their harness that hold the pass rule, and the harness lines where a new group of probes would be wired in. The same workflow runs it every Monday and fails when something changed. Its first run found their change of 2026-11-16: a probe of something the browser does not have now answers "Unsupported", which their table shows as "no such feature". Nulavio answers that for the keyboard layout and for reduced transparency.

## Cost of the audio noise

Engine patch 0012 makes one more pass over the samples an offline rendering returns, on the page's main thread ([ADR 0019](../adr/0019-rendered-audio-differs-per-site.md)). Measured on 2026-11-16 with `scripts/perf/audio_noise_cost.py` on a local build of 160.0 with the patch (Fedora 44, the laptop, with other work running): a page renders stereo sound at 44.1 kHz through an oscillator and a compressor, 11 times a side, with the default set and with the audio noise alone turned off.

| Sound rendered | Samples | With the noise | Without | Difference |
|---|---|---|---|---|
| 10 s | 882,000 | 53 ms | 51 ms | +2 ms |
| 60 s | 5,292,000 | 314 ms | 301 ms | +13 ms |
| 300 s | 26,460,000 | 1601 ms | 1531 ms | +70 ms |

About 4 % on top of the rendering, growing with the length. The difference is time on the page's main thread at the end of the rendering: 70 ms for five minutes of sound is a pause a person can notice once; for the short renderings sites make (a sound effect, a waveform preview) it is 2 ms. Sound that plays does not pass through it.

## First analysis (2026-10-26, Firefox 158.0.1)

`test_privacy` `test_04` loaded a probe page in Strict and in Standard in one session. Strict tiered the processor count (16 to 8); the canvas reading was the same in both, because both carried the engine's noise with the same key for that one site. The page then said "no canvas noise was observed", which was true of that comparison and wrong about the engine.
