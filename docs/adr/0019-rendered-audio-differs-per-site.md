# ADR 0019 — What a page renders as audio differs per site

- **Status:** Accepted (2026-11-14) for the direction. The maintainer decided on [issue #79](https://github.com/nulavio/nulavio/issues/79) that day (decision 4 there) that the audio fingerprint is answered with an engine patch, with its cost measured. This ADR writes down how the patch works, what it leaves out and what it costs. **Proposed** for those details, until the pull request that carries this ADR is merged.
- **Changed** (2026-11-20): the noise also reaches what a node inside an offline rendering hands to script (engine patch 0016, [#406](https://github.com/nulavio/nulavio/issues/406), decision 3), and decision 2 says what that means for a context that plays. **Proposed** for those two parts, until the pull request that carries them is merged.
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

Patch 0012 changes only the buffer an offline rendering returns, and patch 0016 only what a node hands to script inside an offline rendering. What the person hears, and what a call sends, does not pass through either.

**A context that plays is left as it is, its readers included.** The same nodes hand samples to script there, and the choice is not the same for all of them:

- **A script processor's input and a worklet's inputs** are what the page's script makes its own sound from. Noise on them would go on, through the script, to the speakers, a recording or a call. It would be about 80 dB below the sound and not heard, but it would be in what is sent, and a script that needs exact samples (an effect, an echo canceller) would not get them. That is what this decision rules out.
- **An analyser's data and a compressor's reduction** are only read: nothing a script reads there goes back into the sound, so noise there could not be heard. It is left out all the same, because it would not close the reading: a probe would read the same sound through a worklet, which stays plain.

So in a context that plays these readers give the plain values, the same on every site. Two things limit that reading, and neither is Nulavio's doing. By the engine's autoplay rules a context starts to play only after the person has clicked or typed in the page, or on a site the person allowed to play sound by itself or to use the camera or the microphone. And what an analyser reads there depends on the moment the script asks. (Read in the engine's source, `dom/media/autoplay/AutoplayPolicy.cpp`; not run.)

The other choices, for whoever takes this up again:

| Choice | What a person hears or sends | What it closes |
|---|---|---|
| Leave a playing context alone (this decision) | Unchanged | Nothing there: a probe that plays a sound and reads it gets the plain values |
| Noise on the analyser and the reduction of a playing context too | Unchanged: they are only read | Those two readings. The same sound read through a worklet or a script processor stays plain, so a probe moves there |
| Noise on every reader of a playing context | Changed wherever a script passes on what it read: 80 dB below the sound, in the speakers, in a recording, in a call | The reading, at the price of this decision |

### 3. What a node inside an offline rendering hands to script gets the same noise

Patch 0016 ([#406](https://github.com/nulavio/nulavio/issues/406)). While an offline rendering runs, a node inside the graph hands values to the page's script before the noise of decision 1. They are as steady as the returned buffer: the same on every site. The patch puts decision 1's noise (a factor between 0.9999 and 1.0001 for each value, from the site's key and the values themselves) in the five places where they leave the graph:

| What the page reads | Where the noise goes |
|---|---|
| An `AnalyserNode`'s data: `getFloatTimeDomainData`, `getByteTimeDomainData`, `getFloatFrequencyData`, `getByteFrequencyData` | On the copy of the last samples that all four are made from |
| A `ScriptProcessorNode`'s `inputBuffer`, in its `audioprocess` event | On that buffer, as the event is made |
| An `AudioWorklet`'s `inputs`, in `process()` | On the arrays `process()` reads, as each block of 128 samples is copied into them, on the rendering thread |
| An `AudioWorklet`'s `parameters`, for a parameter a node is connected to (its values carry that node's samples) | The same way. A parameter with only its own value and schedule is not changed |
| A `DynamicsCompressorNode`'s `reduction`, a number the compressor makes of the samples | On the number, as it is read |

- **A probe in use reads two of them.** CreepJS's audio module reads an analyser's float data and the compressor's `reduction` when an offline rendering completes, beside the returned buffer (its `src/audio/index.ts`, read on 2026-11-20; its page was not run against the build).
- **On the copy script reads.** What the graph holds and passes to the next node is not changed, so the buffer the rendering returns gets decision 1's noise once, as before. A script that writes what it read into its own output passes that noise on.
- **Keyed the same way.** Two sites read different values; one site reads the same values again for the same sound, in one page and in the next.
- **Each reading has its own noise.** The factors come from the values that reading hands over (the samples an analyser was asked for, a worklet's block of 128), so two readers of the same samples do not get the same factors.
- **Only in an offline context** (decision 2). The context takes the site's key once, when it is made, and only an offline one gets it; the readers ask the context, never the document.
- **No new target and no new preference.** The readers follow `AudioRandomization`, which the build's set already has: on in the Strict category, off for a site the person exempts, off for the browser's own pages and for extensions.
- **The two byte getters round to 256 steps**, which hides most of the noise, and most of what differs between two computers with it. They are made from the same samples as the other two.

## Consequences

- **The change cannot be heard.** One part in ten thousand is about 80 dB below the sound itself. `test_fingerprinting` 11 holds the loudest sample within one part in a thousand of the plain one, and 11b does the same for what each reader hands over.
- **A page that needs exact samples does not get them.** An audio editor that renders offline and compares with a reference bit for bit, a page that analyses a sound offline through an analyser or a worklet, or a test suite for audio code, sees the difference. The shield's switch for that site turns it off.
- **Other ways to read audio are not covered.** The noise is on what an offline rendering returns and on what its nodes hand to script, and only there:
  - what a page reads from a context that plays is not changed (decision 2);
  - nor are the samples `decodeAudioData` returns for a file.

  They are a known gap, written in [fingerprinting](../research/fingerprinting.md) and in R56 of the [residual risks](../security/residual-risks.md).
- **A script written against this noise can get around it.** The noise for a buffer comes from the buffer's own samples, so a script that renders the same sound many times at slightly different lengths gets different noise on the same samples each time, and the average comes close to the plain value. Reading the same samples through several readers does the same, since each reading has its own noise. The engine's canvas noise has the same limit. The noise is aimed at the probes in use, which render once and read once; it does not stop a tracker that targets Nulavio.
- **A pause at the end of a long rendering.** The key is made from every sample (so that one known sound does not give away the noise of another), and that pass runs on the page's main thread when the rendering is handed over. See Cost.
- **Two patches to carry.** Patch 0012 touches five engine files (`RFPTargets.inc`, `nsRFPService`, `AudioDestinationNode`, `nsScreen`, `nsMediaFeatures`). Patch 0016 touches `nsRFPService` again and five classes of `dom/media/webaudio` (`AudioContext`, `AnalyserNode`, `ScriptProcessorNode`, `AudioWorkletNode`, `DynamicsCompressorNode`), nine files in all. Both have to be carried across engine updates. Mozilla tracks its own audio protection in its bug 1358149; if the engine gets one, this target goes.
- **Distribution Firefox (Track A)** does not have either patch. The launcher seeds the same set, and that engine skips the names it does not know.

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
