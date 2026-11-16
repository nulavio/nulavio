# ADR 0019 — What a page renders as audio differs per site

- **Status:** Accepted (2026-11-14) for the direction. The maintainer decided on [issue #79](https://github.com/nulavio/nulavio/issues/79) that day (decision 4 there) that the audio fingerprint is answered with an engine patch, with its cost measured. This ADR writes down how the patch works, what it leaves out and what it costs. **Proposed** for those details, until the pull request that carries this ADR is merged.
- **Related:** [ADR 0016](0016-one-screen-size-and-processor-count-for-pages.md) (the screen, in the same patch), [fingerprinting, measured](../research/fingerprinting.md), [hardening](../security/hardening.md).

## Context

A page can make the browser render a sound without playing it (an `OfflineAudioContext`) and read the samples back. The usual probe, which FingerprintJS and PrivacyTests.org use, sends an oscillator through a compressor and adds up some of the samples. The sum depends on the engine's build and on the processor's arithmetic. It is the same on every site, in every session, and it tells groups of computers apart.

The engine has no protection for it outside `privacy.resistFingerprinting`, which Nulavio does not turn on ([hardening](../security/hardening.md)). Measured on 2026-11-15 with 160.0-0.5's engine, PrivacyTests' audio probe read the same value, `35.749972093850374`, on three sites. It was the one probe of the 25 that still failed after ADRs 0016 to 0018.

## Decision

### 1. An engine patch adds noise per site to what an offline context renders

Patch 0012 adds a target to the engine's fingerprinting protection, `AudioRandomization`, and Nulavio turns it on in `privacy.fingerprintingProtection.overrides`.

- **Where:** at the one place the engine hands a finished offline rendering to the page (`AudioDestinationNode`, as the rendered buffer is made). Every channel of the buffer goes through it once.
- **What:** each sample is multiplied by a factor between 0.9999 and 1.0001. Every sample gets its own factor.
- **From what:** the factors come from the key the engine's canvas noise already uses, which is random per site and per session, mixed with the samples themselves. So:
  - two sites read different values for the same sound;
  - one site reads the same values again for the same sound, in one page and in the next, during a session. A page that renders twice and compares still works;
  - the next session reads other values.
- **Why a factor per sample:** one factor for the whole buffer could be divided out by comparing two samples.
- **It follows the engine's protection** like the rest of the set: on in the Strict category, off for a site the person exempts with the shield, off for the browser's own pages and for extensions.
- **It does not depend on the canvas noise.** The engine makes its per-site key only while a canvas noise is on; the patch makes it for the audio noise alone as well, so a set without the canvas entries still has this one.

### 2. Sound that is played is not touched

The patch changes only the buffer an offline rendering returns. What the person hears, and what a call sends, does not pass through it.

## Consequences

- **The change cannot be heard.** One part in ten thousand is about 80 dB below the sound itself. `test_fingerprinting` 11 holds the loudest sample within one part in a thousand of the plain one.
- **A page that needs exact samples does not get them.** An audio editor that renders offline and compares with a reference bit for bit, or a test suite for audio code, sees the difference. The shield's switch for that site turns it off.
- **Other ways to read audio are not covered.** The noise is put on the buffer an offline rendering returns, and only there:
  - a node inside the offline graph hands its samples to script while the rendering runs (an `AnalyserNode`, a `ScriptProcessorNode`, an `AudioWorklet`), before the noise. Those values are as steady as the returned buffer's, so a probe built on them reads the same on every site. The probes this was measured against (PrivacyTests', FingerprintJS's) read the returned buffer;
  - what a page reads from a context that plays is not changed (harder to make steady, since it depends on timing);
  - nor are the samples `decodeAudioData` returns for a file.

  They are a known gap, written in [fingerprinting](../research/fingerprinting.md) and tracked in [#406](https://github.com/nulavio/nulavio/issues/406).
- **A script written against this noise can get around it.** The noise for a buffer comes from the buffer's own samples, so a script that renders the same sound many times at slightly different lengths gets different noise on the same samples each time, and the average comes close to the plain value. The engine's canvas noise has the same limit. The noise is aimed at the probes in use, which render once and read once; it does not stop a tracker that targets Nulavio.
- **A pause at the end of a long rendering.** The key is made from every sample (so that one known sound does not give away the noise of another), and that pass runs on the page's main thread when the rendering is handed over. See Cost.
- **A patch to carry.** It touches five engine files (`RFPTargets.inc`, `nsRFPService`, `AudioDestinationNode`, `nsScreen`, `nsMediaFeatures`) and has to be carried across engine updates. Mozilla tracks its own audio protection in its bug 1358149; if the engine gets one, this target goes.
- **Distribution Firefox (Track A)** does not have the patch. The launcher seeds the same set, and that engine skips the names it does not know.

## Cost

One more pass over the returned samples, on the page's main thread, at the end of a rendering. Measured on 2026-11-16 with `scripts/perf/audio_noise_cost.py` on a local build with the patch: about 4 % on top of the rendering. That is 2 ms for 10 s of stereo sound, 13 ms for a minute and 70 ms for five minutes. The table is in [fingerprinting](../research/fingerprinting.md#cost-of-the-audio-noise).

The screen's part of the patch is one more comparison where the engine answers `screen`, the available area and the two media queries.

## Checked

- `test_privacytests`: PrivacyTests' own audio probe reads three different values on three sites.
- `test_fingerprinting` 11, on the real engine: two sites read different sums and different digests of the whole buffer; one site reads the same again in the same page and in a later one; with the protections off both sites read the same; the loudest sample stays within one part in a thousand. Measured on 2026-11-16: the probe's sum was `35.749972093850374` plain, `35.74992819688123` on one site and `35.750030019269616` on another; the loudest sample was 0.113791 plain and 0.113782 with the noise.

Not checked: a second session (the key is the canvas noise's, whose change per session the engine's own tests hold); live contexts, which the patch does not touch.

## Alternatives

- **Leave it.** The probe fails, and the value follows a person across sites. It was the choice until this patch, for lack of a preference to turn on.
- **`privacy.resistFingerprinting`.** It does not add noise to audio either; it limits sample rates and reports fixed latencies. It breaks sites in other ways and has no way out per site.
- **Block offline rendering, or ask first.** Sites that use it for real work (waveform previews, audio editors, speech) would break or ask for a permission nobody understands.
- **One constant result for every computer.** It would need the engine to render with exactly the same arithmetic on every processor, which it does not.
