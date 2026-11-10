# Fingerprinting: what a page can read in the Nulavio build, measured

A site can recognise a browser without cookies by what it reads from it: its name, the graphics card, the installed fonts, how a canvas is drawn. This page says what the Nulavio build gives out, measured on the real engine, what it changes against Firefox's own defaults, and what it leaves alone on purpose. Every row marked "tested" fails a test run if it stops being true (`tests/integration/test_fingerprinting.py`).

Measured on 2026-11-10 with the release build of Firefox 159.0.1 and patches 0001–0010, on Fedora 44 (16 logical processors). The first analysis (2026-10-26, Firefox 158.0.1) is at the end.

## Two things the build does

1. **It looks like Firefox.** Nulavio has few users. Anything that says "Nulavio" to a site singles them out, so the build says "Firefox" where Firefox does. It also changes no TLS or HTTP setting, so the connection itself (the handshake a server or a network observer sees) is Firefox's.
2. **It gives each site less, or something different.** Where the engine can blur a reading without breaking sites, the build turns that on: a value that changes per site and per day cannot follow a person from one site to another.

Neither makes two people identical. The time zone, the language, the screen size and the internet address still differ between people. For that level, use Tor Browser.

## What a page reads

"Plain" is the reading with every protection off. "Firefox, Strict" is what the engine does in the tracking-protection category Nulavio uses, without Nulavio's additions.

| Reading | Plain | Firefox, Strict | Nulavio | Checked by |
|---|---|---|---|---|
| Browser name (`navigator.userAgent` and the `User-Agent` header) | — | `… Firefox/159.0` | **The same as Firefox.** Before patch 0009 it was `… Nulavio/159.0.1` on every request | tested (01) |
| Canvas, exported image (`toDataURL`, `toBlob`) | the same on every site | differs per site | differs per site | tested (03) |
| Canvas, raw pixels (`getImageData`) and offscreen canvases | the same on every site | **the same on every site**: the engine's quick mode changes only exported images | **differs per site** | tested (03) |
| WebGL pixels (`readPixels`) | the same on every site | the same on every site | differs per site | tested (06, with a display) |
| Graphics card (WebGL renderer and vendor) | model family, for example "Radeon R9 200 Series, or similar" | the same | **"Mozilla"**; the vendor only as a broad class | tested (06, with a display) |
| Number of processors | 16 | 8 (reported in tiers) | 8 | tested (04) |
| Installed fonts | all of them | **all of them on Fedora** (see below) | **only the fonts the distribution installs by default** | tested (05) |
| Size of the toolbars and the sidebar (`outerWidth` − `innerWidth`), window position | real | real | **not given out** (outer size equals inner size, position 0,0) | tested (04) |
| System colours a page can ask for (accent, selection) | the desktop theme's | the desktop theme's | standard colours | in the set (02) |
| Motion and orientation sensors | readings, where the computer has them | readings | none | in the set (02) |
| Usable screen area | the screen minus panels | the whole screen | the whole screen | in the set (02) |
| Touch points | real | 0, 1 or 5 | 0, 1 or 5 | in the set (02) |

"Differs per site" means: two sites read different values, the same site reads the same value again during the day (so sites that read twice keep working), and the value changes with the next session or day. The engine does it by changing the lowest bit of a few colour values, chosen from a random key per site.

The whole set in effect is the engine's own for Strict (`CanvasRandomization`, `FontVisibilityLangPack`, `JSMathFdlibm`, `ScreenAvailToResolution`, `NavigatorHWConcurrencyTiered`, `MaxTouchPointsCollapse`, `IMEStyle`) plus Nulavio's (`privacy.fingerprintingProtection.overrides` in `firefox-branding.js`): `WebGLRendererConstant`, `WebGLVendorSanitize`, `WindowOuterSize`, `WindowScreenXY`, `WindowInnerScreenXY`, `MouseEventScreenPoint`, `UseStandinsForNativeColors`, `DeviceSensors`, and without `EfficientCanvasRandomization`. Test 02 reads the set from the engine and compares.

## Three things that were wrong before 2026-11-10

- **The name.** The engine builds the User-Agent from the application's name. With the build's own name, every request ended in `Nulavio/159.0.1`: a label for a small group of people, sent to every site, with the point release included. No document recorded it as a decision. Patch 0009 gives the engine the name Firefox uses, and the string is now Firefox's, character for character.
- **Fonts on Fedora.** The engine hides fonts a person installed, using a list of default fonts per distribution release. Its Fedora lists stop at release 39 and are never used: the release number is read from `VERSION_ID="…"` with quotes, which Fedora's `os-release` does not have. On Fedora 44 the same 33 of 63 probed font families were visible with the protection off, on, and even with `privacy.resistFingerprinting`. Patch 0010 uses the two newest lists for every Fedora. On Ubuntu the engine's lists already apply (22.04 and 20.04 together for other releases).
- **Raw canvas pixels.** The first analysis found "no canvas noise" and did not claim any. The cause is now known: the engine's quick mode, on by default since then, changes exported images only, and that analysis compared two modes on one site, which share a key. Nulavio turns the quick mode off, so the full one covers raw reads, offscreen canvases and WebGL.

## What is left alone, and why

| Reading | Why it stays |
|---|---|
| Time zone, date format, language | A wrong time or language breaks calendars, banks and forms |
| Screen size, window size, zoom | Hiding them means fixed window sizes with margins (letterboxing) |
| Dark mode, reduced motion, contrast | They are how a site respects a person's accessibility settings |
| Audio (how the engine mixes a test sound) | The engine has no protection for it. The value depends on the engine build and processor, not on the person's settings |
| Speech voices, cameras and microphones (count only, no names before permission) | Hiding them breaks reading aloud and device choice in calls |
| System font name and size | No protection in the engine outside `privacy.resistFingerprinting` |
| Keyboard layout | Faking a layout breaks shortcuts in web apps on non-US keyboards |
| Internet address | A browser cannot hide it; that is a VPN's or Tor's job |

`privacy.resistFingerprinting`, the engine's stricter mode, changes several of these. Nulavio does not turn it on ([hardening](../security/hardening.md), "Deliberately not changed"). It may become an opt-in mode.

## Limits

- **A site can still tell this is not a stock Firefox.** A release that reports "Mozilla" as its graphics card, or an outer window as large as the inner one, is unusual. What the build aims at is that Nulavio users look alike and that one person does not carry the same values from site to site, not that they vanish among all Firefox users.
- **A site the person exempts gets the plain values.** Turning the shield off for a site in the address bar turns these protections off there too (tested, 07), and only there. Mozilla's own per-site exceptions for broken sites (Remote Settings) apply as in Firefox.
- **Other distributions.** The engine has font lists for Fedora and Ubuntu only. Elsewhere every installed font stays visible.
- **Cost.** A page that reads canvas pixels back gets a few of them changed by one step. Image editors and games that draw and read many times pay for the extra work on each read.
- **Extensions.** uBlock Origin, which Nulavio installs, can be noticed by what it blocks, as in any browser that has it.
- **Distribution Firefox (Track A).** The launcher seeds the same additions, but patches 0009 and 0010 exist only in the Nulavio build. Distribution Firefox already says "Firefox"; its fonts on Fedora stay visible.

## Kept true by

- `tests/integration/test_fingerprinting.py`, seven tests on the real engine. The plain values are read in the same session with the protections off, so the comparison holds on any machine. The font test installs a font made for the test in the throwaway home.
- `tests/unit/test_prefs_and_guard.py`: the additions are the same in both tracks, and nothing that breaks sites or accessibility (time zone, language, colour scheme, reduced motion, keyboard, window rounding) can enter the default.
- Guard at run time: a change to `privacy.fingerprintingProtection` or its branch made while the browser was closed is reported at the next start.
- `tests/integration/test_privacy.py` (`test_04`) still compares Strict with Standard.

## First analysis (2026-10-26, Firefox 158.0.1)

`test_privacy` `test_04` loaded a probe page in Strict and in Standard in one session. Strict tiered the processor count (16 to 8); the canvas reading was the same in both, because both carried the engine's noise with the same key for that one site. The page then said "no canvas noise was observed", which was true of that comparison and wrong about the engine.
