# ADR 0018 — Sites are not told the system's motion and contrast preferences, unless the person says so

- **Status:** Accepted (2026-11-14). The maintainer decided it on [issue #79](https://github.com/nulavio/nulavio/issues/79) that day (decision 2 there): "pages get `no-preference`; one setting 'Let sites see my motion and contrast preferences'; the first run offers it when the system has either one on. Nulavio's own pages and window keep honouring the system." This ADR writes down how it is built and what it costs, including one cost found while building it (smooth scrolling, below).
- **Related:** [ADR 0016](0016-one-screen-size-and-processor-count-for-pages.md), [ADR 0017](0017-pages-read-utc-with-a-switch-per-site.md), [accessibility](../design/accessibility.md), [fingerprinting, measured](../research/fingerprinting.md).

## Context

A page can ask whether the system prefers reduced motion (`prefers-reduced-motion`) and more contrast (`prefers-contrast`). Few people turn these on, so the answer tells them apart, and it is the same on every site. PrivacyTests.org probes both by changing the system's settings between two runs. Measured on 2026-11-15, Nulavio read `reduce` and `more` in one run and `no-preference` in the other.

These settings exist for people who need them. A site that honours reduced motion stops its animations for someone they make ill. Until now Nulavio left both alone for that reason.

## Decision

### 1. By default, pages read "no preference"

`+CSSPrefersReducedMotion`, `+CSSPrefersContrast` and `+CSSPrefersReducedTransparency` join `privacy.fingerprintingProtection.overrides`, in both tracks. The third costs nothing today: the engine keeps that media query off and pages already read "no preference". It is added so that the answer stays constant when the engine turns the query on.

### 2. One setting tells sites again

**"Deixar os sites verem minhas preferências de movimento e contraste"**, in Settings › Privacidade e Segurança, with the protections. On, the engine's set is the build's default without those three entries. Everything else in the set stays.

- It is written by `NulavioFingerprinting.sys.mjs`, not by the personalisation options: it relaxes a protection, and those options may write none.
- On, the set is written again from the build's default at each start, so a later build's default is taken in.
- Off, the value is cleared at the moment the setting is turned off, and never at a start: a set a person wrote themselves in `about:config` is left alone.

### 3. A bar offers the setting once

When the system has reduced motion or more contrast on, and the setting is off, the first window shows a bar: what Nulavio does, why, and two answers, "Deixar os sites verem" and "Manter assim". Either answer, or closing the bar, ends the offer. It is shown on a new profile and, once, on a profile that existed before this change, so nobody who relies on these settings finds sites animating again without being told.

### 4. Nulavio's own pages and window follow the system

The new tab, Settings and the window's own motion are not pages of sites, and the engine's protection does not reach them.

## Consequences

- **Sites animate for a person who asked the system for less motion, until they answer the bar with "Deixar os sites verem" or turn the setting on.** "Manter assim", or closing the bar, ends the offer and changes nothing: sites go on animating. This is the cost the decision accepts, and the bar is what it rests on.
- **Pages also scroll smoothly.** With the reduced-motion entry in the set, the engine scrolls smoothly whatever the system asks (`nsLayoutUtils::IsSmoothScrollingEnabled`), because a page can tell smooth scrolling from the number of scroll events it gets. This was not in the decision of 2026-11-14 and is a second cost for the same people. It is why the setting rewrites the set itself: the engine's per-site list would give sites the media query back and leave the scrolling smooth.
- **Contrast:** what sites lose is the chance to choose their own high-contrast styles. The colours the engine itself forces on pages under a high-contrast theme are a setting of the engine, not this answer (not measured here).
- **With the setting on, the person can be told apart by these answers again**, on every site: reduced motion, contrast and, once the engine answers it, reduced transparency. The three are given back together.
- **Distribution Firefox (Track A)** gets the three entries, in profiles made from now on, and has no setting and no bar. There the way out is to remove the entries from the preference by hand.
- **A profile the launcher seeded before this change keeps the set it was seeded with**, without the three entries: sites there are still told the system's preferences (#384). The profiles the Nulavio build makes itself take the new default.

## Checked

- `test_privacytests`: PrivacyTests' own motion and contrast probes, with the system's settings on in one run and off in the other.
- `test_fingerprinting` 10, on the real engine:
  - with both system settings on, a page reads "no preference" for both, and Nulavio's new tab reads them as the system has them;
  - no bar while the system has neither on; with them on, a new window shows the bar once, with its two answers; "Manter assim" changes nothing and ends the offer; "Deixar os sites verem" turns the setting on;
  - on, the engine's set is the build's without exactly the three entries, pages read both preferences, and the processor count and the screen size are unchanged;
  - off again, the set is the build's default;
  - Settings has the switch with the protections, with its explanation, and pressing it is the same setting.

Not checked: smooth scrolling itself (read from the engine's code, not measured); a real desktop's settings (the test uses the engine's own stand-ins for them, `ui.prefersReducedMotion` and `ui.useAccessibilityTheme`, which is what a headless run has); a screen reader's reading of the bar.

## Alternatives

- **Leave both alone.** The probes fail, and the two answers keep telling people apart. This was the choice until 2026-11-14.
- **Tell sites by default when the system has a setting on.** Nobody would be surprised by animations. The people the probes are about, those who have these settings on, would get no protection at all.
- **A switch per site.** The preferences are about the person, not about a site: someone who needs less motion needs it everywhere.
