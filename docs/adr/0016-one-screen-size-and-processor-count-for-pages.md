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

- **How:** the engine has a per-tab screen size made for automation (`browsingContext.setScreenAreaOverride`). The Shell sets it on every tab (`NulavioFingerprinting.sys.mjs`). No engine patch.
- **When:** before the tab's first page, and again before each page is asked for, so a page's first script already reads it. Measured through navigations that change process and through back and forward.
- **The window is left alone.** `innerWidth`, `innerHeight` and CSS layout are the window's real size. No margins, no fixed window sizes.
- **It follows the engine's protection.** It is on while fingerprinting protection is on (the Strict category, Nulavio's default) and off otherwise. A site the person exempts with the shield in the address bar reads the display's size, like the other plain values.
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
- **Nulavio's own pages read the same values.** The override is per tab, not per page. Nothing in the Shell uses the screen's size.
- **Distribution Firefox (Track A)** gets the processor count, which is a preference, and not the screen, which needs the Shell.

## Checked

- `test_privacytests`: PrivacyTests' own Screen probes on two display sizes, and its processor probe.
- `test_fingerprinting` 08: the size, the available area and the media query on two sites, from the page's first script; an exempted site reads the display's, also after a protected page in another process; back and forward.
- `tests/regression/run_sites.py` on 50 real sites, before and after: see the pull request.

Not checked: a private window (the same code path, with the private window's own switch and exemption list), and a display larger than 1920×1080 (headless runs have a smaller one).

## Alternatives

- **The window's inner size as the screen (the engine's `ScreenRect`).** It passes PrivacyTests only when the window does not follow the display, which a maximised window does.
- **Letterboxing.** It hides the window's size too. It shows margins around every page, against the calm interface the product asks for. Ruled out by the maintainer.
- **Keep the processor tiers.** PrivacyTests' own runners all have fewer than 8 processors, so the tiers pass on their site. They would still tell a 16-processor machine from a 4-processor one, which is what the probe is about.
