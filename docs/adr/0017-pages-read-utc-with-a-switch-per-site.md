# ADR 0017 — Pages read UTC as the time zone, with a switch per site

- **Status:** Accepted (2026-11-14). The maintainer decided it on [issue #79](https://github.com/nulavio/nulavio/issues/79) that day (decision 1 there): "pages get UTC by default, with a per-site switch 'use my time zone' in the shield panel. It is the only way the probe passes, and the per-site switch covers banks and calendars without relaxing it for everyone." This ADR writes down how it is built and what it costs.
- **Related:** [ADR 0016](0016-one-screen-size-and-processor-count-for-pages.md) (the screen and the processors), [fingerprinting, measured](../research/fingerprinting.md), [hardening](../security/hardening.md).

## Context

A page can read the computer's time zone (`Intl.DateTimeFormat().resolvedOptions().timeZone`, and the offset of any `Date`). It narrows a person down to a region, and it follows them from site to site. PrivacyTests.org probes it by changing the system's time zone between two runs: the probe passes only when the page reads the same value in both. Measured on 2026-11-15, Nulavio read `Europe/Paris` in one run and `Europe/Berlin` in the other.

Until now the time zone was left alone on purpose, and `tests/unit/test_prefs_and_guard.py` kept it out of the defaults: a wrong hour breaks calendars, banks and forms.

## Decision

### 1. Every page reads UTC

`+JSDateTimeUTC` joins `privacy.fingerprintingProtection.overrides`, in both tracks. A page then reads the time zone `Atlantic/Reykjavik`, which is the engine's name for UTC, and an offset of 0. Dates the page formats itself come out in UTC.

It follows the engine's protection like the rest of that list: on in the Strict category, off for a site exempted with the shield.

### 2. A site gets the real time zone from one switch

In the Nulavio build, the address bar's shield panel has a second switch under the engine's own: **"Usar meu fuso horário neste site"**. Turning it on reloads the page, which then reads the system's time zone.

- **What it covers:** the site's registrable domain with its subdomains, and frames from other sites inside its pages (a calendar's widget shows the same hours as the page around it). No other site.
- **Where it is kept:** as a permission of that site (`nulavio-timezone`). So Settings lists it with the other site exceptions, where it can be removed.
- **How the engine learns it:** the engine has its own per-site list (`privacy.fingerprintingProtection.granularOverrides`). `NulavioFingerprinting.sys.mjs` writes that list from the permissions. It replaces only entries of the shape it writes; an entry a person added by hand stays.
- **Where the switch is not offered:**
  - a site without a registrable domain (an IP address, `localhost`), because the engine's list goes by domain;
  - a site exempted with the shield, which reads the real time zone already;
  - a private window, which must leave no record of the site. A choice made in a normal window applies there too.

### 3. Nulavio's own pages are not changed

The new tab, Settings and the other pages of the browser keep the system's time zone. So do the browser's own menus and dialogs.

## Consequences

- **Hours on most sites are in UTC until the person turns the switch on for that site.** This is the largest cost of #79, and it is by decision. It shows wherever a page formats a time itself: message times in web chats and mail, a calendar's grid, a bank statement, a delivery estimate, a flight search. For a person in Brazil they read three hours ahead. A site that formats times on its server from an account setting is not affected.
- **Nothing tells the person why an hour is wrong.** The switch's own text does ("Os sites veem o horário universal (UTC), igual para todos. Ligue se este site mostrar horas erradas."), but only once the panel is open. The notes of the release that ships this must say it first.
- **Some sites ask to "update your time zone"** when the browser's differs from the account's (calendars do). The switch answers that.
- **A site with the switch on can tell this person's time zone again**, and only that site.
- **Distribution Firefox (Track A)** gets UTC from the preference, and has no switch. A profile the launcher seeded before gets it at its next launch, unless the person changed the set themselves (#384). There the way out for a site is the shield, which turns the other protections off for that site as well.

## Checked

- `test_privacytests`: PrivacyTests' own time zone probe, with the system in Paris and in Berlin.
- `test_fingerprinting` 09, on the real engine with the system in São Paulo:
  - every page reads UTC;
  - the switch is under the engine's own in the panel, with a name and an explanation, reached with the arrow keys and pressed with Space;
  - on: the page reloads and reads São Paulo, and so does a subdomain; another site still reads UTC;
  - off again, and removed from the permission list: UTC again, and the engine's list is empty;
  - a site without a registrable domain is not offered the switch;
  - Nulavio's own page reads São Paulo.
- The values are read with the page's own `Intl` and `Date`. A script run from the test harness has a realm of its own, which always keeps the system's time zone.

Not checked: a private window; a frame from another site inside a page with the switch on; real calendar and chat sites.

## Alternatives

- **Leave the time zone alone.** The probe fails, and the time zone keeps following the person between sites. This was the choice until 2026-11-14.
- **A different value per site.** A page would show a different wrong hour on every site, with no benefit over one known value.
- **Only the shield's own switch as the way out.** It works, and it is what Track A has. It also turns off canvas noise and the rest for that site, when all the site needed was the hour.
